"""Data coordinator: fetches everything from CWFIS / Open-Meteo once per update and does the maths.

Every entity reads from `coordinator.data` (a plain dict built in `_async_update_data`), so the
servers are queried once per update no matter how many entities exist.

Data flow per update:
  1. Reported fires (required; if this fails the whole update fails and HA retries).
  2. Fires known at midnight, prescribed burns, hotspots, perimeters, fire danger, last year's numbers and the smoke
     forecast (all optional; if one fails only its own sensors show "unknown").
  3. Distances/bearings from Home and every extra watch zone to each active fire, and each zone's smoke forecast.

Everything the servers send is untrusted. A response that isn't a feature collection counts as a failed request;
inside one, each fire record goes through helpers.clean_fire(), and every other value is checked where it's used, so
a malformed record or value is skipped (or treated as missing) instead of failing the update.
"""

import asyncio
from datetime import UTC, datetime, timedelta
from itertools import islice
import logging
from math import cos, radians

import aiohttp
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed
from homeassistant.util import dt as dt_util

from .const import (
    CONF_RADIUS,
    CONF_SMOKE_RADIUS,
    CONF_ZONES,
    CWFIF_WFS,
    DANGER_LEVELS,
    DEFAULT_RADIUS,
    DEFAULT_SMOKE_RADIUS,
    DOMAIN,
    FIRE_FIELDS,
    LAYER_DANGER,
    LAYER_HOTSPOTS,
    LAYER_PERIMETERS,
    LAYER_PRESCRIBED,
    LAYER_REPORTED,
    LEGACY_WFS,
    MAX_PERIMETER_VERTICES,
    MAX_PM25,
    OPEN_METEO_URL,
    PROVINCES,
    STAGES,
    UPDATE_INTERVAL,
)
from .helpers import bearing, clean_fire, dedupe, fire_size, has_xy, km, number, pct_change, points

_LOGGER = logging.getLogger(__name__)

# Anything a flaky server or unexpected response can raise while we parse it (RecursionError: absurdly deep JSON).
FETCH_ERRORS = (
    aiohttp.ClientError,
    TimeoutError,
    KeyError,
    ValueError,
    TypeError,
    IndexError,
    AttributeError,
    ArithmeticError,
    RecursionError,
)


def _properties(feature: dict) -> dict:
    """A feature's properties, or an empty dict when they're missing or not an object."""
    properties = feature.get("properties")
    return properties if isinstance(properties, dict) else {}


def _has_lat_lon(properties: dict) -> bool:
    """True when a hotspot's properties hold a usable lat/lon pair."""
    return has_xy(properties.get("lat"), properties.get("lon"))


def _perimeter_distances(lat: float, lon: float, perimeters: list[dict] | None) -> list[float]:
    """Distance (km) from a point to every vertex of every fire perimeter.

    The closest vertex stands in for the nearest fire edge: exact point-to-polygon distance isn't worth the code
    for a number shown to one decimal of a kilometre.
    """

    def vertices():
        """Every usable vertex of every perimeter, in order."""
        for perimeter in perimeters or []:
            geometry = perimeter.get("geometry")
            if isinstance(geometry, dict):
                yield from points(geometry.get("coordinates"))

    # points() yields (lon, lat, ...) in GeoJSON order; extra values such as elevation are ignored. The cap keeps an
    # oversized response from tying up Home Assistant; real perimeters near one place stay well under it.
    return [km(lat, lon, y, x) for x, y, *_ in islice(vertices(), MAX_PERIMETER_VERTICES)]


def _danger_codes(danger: list[dict] | None) -> list[int]:
    """The valid fire danger codes (0 to 4) in the polygons around a point; any other value means "no data"."""
    codes = []
    for polygon in danger or []:
        code = number(_properties(polygon).get("GRIDCODE"), 0, len(DANGER_LEVELS) - 1)
        if code is not None and code.is_integer():
            codes.append(int(code))
    return codes


def _utc_stamp(when: datetime) -> str:
    """Format a datetime as the UTC timestamp GeoServer's CQL filters expect."""
    return dt_util.as_utc(when).strftime("%Y-%m-%dT%H:%M:%SZ")


type CwfisConfigEntry = ConfigEntry[CwfisCoordinator]


class CwfisCoordinator(DataUpdateCoordinator[dict]):
    """Fetches and combines all CWFIS data for the integration."""

    config_entry: CwfisConfigEntry

    def __init__(self, hass: HomeAssistant, entry: CwfisConfigEntry) -> None:
        """Read the options once; the integration reloads whenever they change."""
        super().__init__(hass, _LOGGER, config_entry=entry, name=DOMAIN, update_interval=UPDATE_INTERVAL)
        self.session = async_get_clientsession(hass)
        self.radius = entry.options.get(CONF_RADIUS, DEFAULT_RADIUS)
        self.smoke_radius = entry.options.get(CONF_SMOKE_RADIUS, DEFAULT_SMOKE_RADIUS)
        self.zone_ids = entry.options.get(CONF_ZONES, [])
        self._last_year_cache: dict = {}  # last year's totals only change once a day

    # ------------------------------------------------------------------
    # Low-level requests
    # ------------------------------------------------------------------
    async def _wfs(self, url: str, params: dict) -> list[dict]:
        """Run a WFS GetFeature request and return the GeoJSON features (only those that are objects).

        Raises ValueError when the response isn't a feature collection, so it counts as a failed request.
        """
        params = {"SERVICE": "WFS", "REQUEST": "GetFeature", "OUTPUTFORMAT": "application/json", **params}
        async with self.session.get(url, params=params, timeout=aiohttp.ClientTimeout(total=60)) as resp:
            resp.raise_for_status()
            body = await resp.json(content_type=None)
        features = body.get("features") if isinstance(body, dict) else None
        if not isinstance(features, list):
            raise ValueError("response is not a GeoJSON feature collection")
        return [feature for feature in features if isinstance(feature, dict)]

    async def _cwfif(self, layer: str, fields: str, cql: str) -> list[dict]:
        """Query a CWFIF fire layer with a CQL filter; returns each fire's checked properties (see clean_fire)."""
        params = {"VERSION": "2.0.0", "TYPENAMES": layer, "PROPERTYNAME": fields, "CQL_FILTER": cql}
        features = await self._wfs(CWFIF_WFS, params)
        return [fire for feature in features if (fire := clean_fire(feature.get("properties"))) is not None]

    async def _around(self, layer: str, fields: str, lat: float, lon: float, reach_km: float) -> list[dict]:
        """Query a legacy CWFIS layer for features inside a box of ±reach_km around a point.

        WFS 1.0.0 is used on purpose: it keeps the BBOX in plain lon/lat order.
        """
        dlat = reach_km / 111  # ~111 km per degree of latitude
        dlon = reach_km / (111 * max(cos(radians(lat)), 0.01))  # degrees of longitude shrink towards the poles
        return await self._wfs(
            LEGACY_WFS,
            {
                "VERSION": "1.0.0",
                "TYPENAME": layer,
                "PROPERTYNAME": fields,
                "SRSNAME": "EPSG:4326",
                "BBOX": f"{lon - dlon},{lat - dlat},{lon + dlon},{lat + dlat},EPSG:4326",
            },
        )

    async def _optional(self, coro):
        """Await an optional request; on any failure log at debug level and return None."""
        try:
            return await coro
        except FETCH_ERRORS as err:
            _LOGGER.debug("Optional CWFIS request failed: %s", err)
            return None

    # ------------------------------------------------------------------
    # Main update
    # ------------------------------------------------------------------
    async def _async_update_data(self) -> dict:
        """Build the data dict every entity reads from."""
        year = dt_util.now().year
        midnight = _utc_stamp(dt_util.start_of_local_day())
        now_cql = "now()>=record_start AND now()<=record_end"  # each fire's current record only

        try:
            # This season's fires PLUS any earlier-season fire still burning, so fires that carry
            # over New Year don't vanish (and don't trigger false "fire out" alerts) at midnight.
            fires = dedupe(
                await self._cwfif(
                    LAYER_REPORTED, FIRE_FIELDS, f"(fire_year={year} OR stage_of_control_status<>'EX') AND {now_cql}"
                )
            )
        except FETCH_ERRORS as err:
            raise UpdateFailed(f"CWFIS request failed: {err}") from err

        # Fires that already existed at local midnight; anything else was reported today.
        known = await self._optional(
            self._cwfif(
                LAYER_REPORTED,
                "national_fire_id",
                f"fire_year={year} AND record_start BEFORE {midnight} AND record_end AFTER {midnight}",
            )
        )
        if known is not None:
            known = {fire["national_fire_id"] for fire in known}

        burns = await self._optional(
            self._cwfif(LAYER_PRESCRIBED, "national_fire_id,stage_of_control_status,latitude,longitude", now_cql)
        )
        if burns is not None:
            # Only burns still going ("EX" is extinguished) that can be placed on a map count.
            burns = [
                burn
                for burn in burns
                if burn.get("stage_of_control_status") != "EX" and has_xy(burn.get("latitude"), burn.get("longitude"))
            ]

        for fire in fires:
            fire["agency_code"] = fire.get("agency_code") or "Unknown"
        season = [f for f in fires if f.get("fire_year") == year]  # year-to-date numbers
        burning = [f for f in fires if f.get("stage_of_control_status") != "EX"]
        # Fires we can place on a map and track over time need an ID and valid coordinates.
        trackable = [f for f in burning if f.get("national_fire_id") and has_xy(f.get("latitude"), f.get("longitude"))]

        # Measure from Home and every watch zone at the same time; each zone makes its own optional requests.
        zones = self._zones()
        zone_requests = [self._zone_data(name, lat, lon, trackable, burns) for name, lat, lon in zones.values()]
        zone_results = await asyncio.gather(*zone_requests)
        by_zone = dict(zip(zones, zone_results))
        home_fires = by_zone["home"]["all"]

        last_year = await self._last_year(year)
        smoke = by_zone["home"]["smoke"]
        last_year_total = last_year["total"] if last_year else None
        last_year_area = last_year["area"] if last_year else None

        total = len(season)
        area = round(sum(fire_size(fire) for fire in season))
        provinces = self._by_province(fires, season, burning)
        active_by_stage = {}
        for code, name in STAGES.items():
            in_stage = [fire for fire in burning if fire.get("stage_of_control_status") == code]
            active_by_stage[name.lower().replace(" ", "_")] = len(in_stage)
        reported_today = None
        if known is not None:
            reported_today = len([fire for fire in season if fire["national_fire_id"] not in known])
        out = [fire for fire in season if fire.get("stage_of_control_status") == "EX"]  # "EX" is extinguished

        smoke_peak = smoke["max_24h"] if smoke else None
        details = ("peak_time_24h", "max_48h", "peak_time_48h", "source")
        smoke_details = {key: smoke[key] for key in details} if smoke else None

        # Keys ending in "_attrs" are picked up automatically as that sensor's attributes.
        return {
            "zones": by_zone,
            "fires": {fire["national_fire_id"]: fire for fire in home_fires},  # map markers, measured from Home
            "provinces": provinces,
            "reported_today": reported_today,
            "active": len(burning),
            "active_attrs": {
                **active_by_stage,
                "by_province": {PROVINCES.get(code, code): p["active"] for code, p in provinces.items() if p["active"]},
            },
            "out": len(out),
            "total": total,
            "area": area,
            "area_attrs": {"by_province_ha": {PROVINCES.get(code, code): p["area"] for code, p in provinces.items()}},
            "fires_vs_last_year": pct_change(total, last_year_total),
            "fires_vs_last_year_attrs": {"this_year": total, "same_date_last_year": last_year_total},
            "area_vs_last_year": pct_change(area, last_year_area),
            "area_vs_last_year_attrs": {"this_year_ha": area, "same_date_last_year_ha": last_year_area},
            "smoke_forecast": smoke_peak,
            "smoke_forecast_attrs": smoke_details,
            # Candidate smoke sources for the Fire upwind / Wildfire smoke binary sensors.
            "smoke_pool": [fire for fire in home_fires if fire["distance"] <= self.smoke_radius],
        }

    @staticmethod
    def _by_province(fires: list[dict], season: list[dict], burning: list[dict]) -> dict:
        """Active fires and this season's area burned (ha) for each reporting agency, in code order."""
        provinces = {}
        for code in sorted({fire["agency_code"] for fire in fires}):
            area = sum(fire_size(fire) for fire in season if fire["agency_code"] == code)
            provinces[code] = {
                "active": len([fire for fire in burning if fire["agency_code"] == code]),
                "area": round(area),
            }
        return provinces

    # ------------------------------------------------------------------
    # Per-zone proximity
    # ------------------------------------------------------------------
    def _zones(self) -> dict:
        """Home plus every configured extra zone that still exists: id -> (name, lat, lon)."""
        found = {"home": ("Home", self.hass.config.latitude, self.hass.config.longitude)}
        for zone_id in self.zone_ids:
            state = self.hass.states.get(zone_id)
            if zone_id == "zone.home" or not state:
                continue
            lat, lon = state.attributes.get("latitude"), state.attributes.get("longitude")
            if has_xy(lat, lon):
                found[zone_id] = (state.name, lat, lon)
        return found

    async def _zone_data(self, name: str, lat: float, lon: float, fires: list[dict], burns: list | None) -> dict:
        """Everything measured relative to one zone."""
        radius = self.radius
        spots, perims, danger, smoke = await asyncio.gather(
            self._optional(self._around(LAYER_HOTSPOTS, "lat,lon", lat, lon, radius)),
            self._optional(self._around(LAYER_PERIMETERS, "geometry", lat, lon, radius)),
            # A tiny box (0.5 km) is enough to find the danger polygon covering the zone itself.
            self._optional(self._around(LAYER_DANGER, "GRIDCODE", lat, lon, 0.5)),
            self._optional(self._smoke_forecast(lat, lon)),
        )

        # Every trackable fire with distance/bearing from this zone, nearest first.
        measured = []
        for fire in fires:
            distance = round(km(lat, lon, fire["latitude"], fire["longitude"]), 1)
            measured.append(
                {**fire, "distance": distance, "bearing": bearing(lat, lon, fire["latitude"], fire["longitude"])}
            )
        here = sorted(measured, key=lambda fire: fire["distance"])

        edges = _perimeter_distances(lat, lon, perims)
        codes = _danger_codes(danger)

        # Counts are None (shown as "unknown") when their request failed, rather than a misleading 0.
        hotspots = hotspot_distance = None
        if spots is not None:
            located = [props for spot in spots if _has_lat_lon(props := _properties(spot))]
            spot_distances = [km(lat, lon, spot["lat"], spot["lon"]) for spot in located]
            in_radius = [d for d in spot_distances if d <= radius]
            hotspots = len(in_radius)
            hotspot_distance = round(min(in_radius), 1) if in_radius else None
        prescribed = None
        if burns is not None:
            prescribed = len([burn for burn in burns if km(lat, lon, burn["latitude"], burn["longitude"]) <= radius])

        return {
            "name": name,
            "all": here,
            "nearby": [fire for fire in here if fire["distance"] <= radius],
            "nearest": here[0] if here else None,
            "hotspots": hotspots,
            "perimeter": round(min(edges), 1) if edges else None,
            "danger": DANGER_LEVELS[max(codes)] if codes else None,
            "prescribed": prescribed,
            "hotspot_distance": hotspot_distance,
            "smoke": smoke,
        }

    # ------------------------------------------------------------------
    # Optional extras
    # ------------------------------------------------------------------
    async def _last_year(self, year: int) -> dict | None:
        """Season totals exactly as they stood at this moment last year (fetched once a day)."""
        cache = self._last_year_cache
        today = dt_util.now().date()
        if cache.get("date") != today:
            now = dt_util.utcnow()
            try:
                then = now.replace(year=now.year - 1)
            except ValueError:  # today is Feb 29 and last year had none
                then = now.replace(year=now.year - 1, day=28)
            stamp = _utc_stamp(then)
            prev = await self._optional(
                self._cwfif(
                    LAYER_REPORTED,
                    "stage_of_control_status,fire_size",
                    f"fire_year={year - 1} AND record_start BEFORE {stamp} AND record_end AFTER {stamp}",
                )
            )
            if prev is None:  # request failed: keep yesterday's value rather than going blank
                return cache.get("value")
            cache.update(date=today, value={"total": len(prev), "area": round(sum(fire_size(f) for f in prev))})
        return cache["value"]

    async def _smoke_forecast(self, lat: float, lon: float) -> dict | None:
        """Forecast PM2.5 at a zone now, and its highest over the next 24 h and 48 h (Open-Meteo / ECMWF CAMS)."""
        params = {
            "latitude": lat,
            "longitude": lon,
            "hourly": "pm2_5",
            "forecast_days": 3,
            "timezone": "UTC",
        }
        async with self.session.get(OPEN_METEO_URL, params=params, timeout=aiohttp.ClientTimeout(total=30)) as resp:
            resp.raise_for_status()
            body = await resp.json(content_type=None)
        hourly = body.get("hourly") if isinstance(body, dict) else None
        times = hourly.get("time") if isinstance(hourly, dict) else None
        values = hourly.get("pm2_5") if isinstance(hourly, dict) else None
        if not isinstance(times, list) or not isinstance(values, list):
            raise ValueError("response has no hourly PM2.5 forecast")

        now = dt_util.utcnow()
        series = []
        for when, value in zip(times, values):
            # Skip each hour that's missing, isn't a time, or isn't a believable PM2.5 value (NaN, negative, huge).
            pm25 = number(value, 0, MAX_PM25)
            if pm25 is None or not isinstance(when, str):
                continue
            try:
                series.append((datetime.fromisoformat(when).replace(tzinfo=UTC), pm25))
            except ValueError:
                continue

        def peak(hours: int):
            """(time, value) of the highest reading from an hour ago until `hours` ahead."""
            window = [p for p in series if now - timedelta(hours=1) <= p[0] <= now + timedelta(hours=hours)]
            return max(window, key=lambda p: p[1], default=(None, None))

        (t24, v24), (t48, v48) = peak(24), peak(48)
        if v24 is None:  # no usable forecast values
            return None
        # The current hour's value: the latest one that isn't in the future.
        current = [p for p in series if now - timedelta(hours=1) <= p[0] <= now]
        return {
            "now": round(current[-1][1], 1) if current else None,
            "max_24h": round(v24, 1),
            "peak_time_24h": dt_util.as_local(t24).isoformat(),
            "max_48h": round(v48, 1),
            "peak_time_48h": dt_util.as_local(t48).isoformat(),
            "source": "Open-Meteo / ECMWF CAMS",
        }
