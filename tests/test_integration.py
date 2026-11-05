"""Offline simulation of the CWFIS integration — run before every release.

    python3 tests/test_integration.py

No Home Assistant install or internet connection needed: Home Assistant and aiohttp are replaced by
the stand-ins in stubs.py, and the CWFIS / Open-Meteo servers by fake responses. Each scenario sets up the
integration, reads every entity the way the HA frontend would, and checks the results.

Add a scenario whenever a real-world data problem turns up, so it can never come back unnoticed.
Exit code is 0 when every scenario passes, 1 otherwise.
"""

import asyncio
from datetime import datetime, timedelta, timezone
import logging
import os
from pathlib import Path
import random
import re
import sys
import traceback
import types

sys.dont_write_bytecode = True  # keep __pycache__ out of the repository
logging.basicConfig(level=logging.ERROR)
sys.path.insert(0, str(Path(__file__).resolve().parent))  # for stubs.py
from stubs import CLOCK, EVENTS, LOCAL, SESSION, ClientError, UpdateFailed  # noqa: E402,I001  (registers the stand-ins first)

# ---------------------------------------------------------------------------
# Fake servers. SCENARIO holds the data the current scenario wants them to return.
# ---------------------------------------------------------------------------
SCENARIO: dict = {}


class FakeResponse:
    status = 200

    def __init__(self, body, content_type="application/json"):
        self.body, self.content_type = body, content_type

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc):
        pass

    def raise_for_status(self):
        pass

    async def json(self, content_type=None):
        if isinstance(self.body, str):
            raise ValueError("not JSON")
        return self.body

    async def read(self):
        return b"PNG"

    async def text(self):
        return str(self.body)


def features(rows):
    return FakeResponse({"features": [{"properties": row} for row in rows]})


def server_filter(fires, cql):
    """Mimic GeoServer's fire_year / stage filter closely enough for the integration's queries."""
    years = [int(y) for y in re.findall(r"fire_year=(\d+)", cql)]
    holdovers = "<>'EX'" in cql
    return [
        f
        for f in fires
        if not years or f.get("fire_year") in years or (holdovers and f.get("stage_of_control_status") != "EX")
    ]


class FakeSession:
    def get(self, url, params, timeout):
        down = SCENARIO.get("down", set())
        if "open-meteo" in url:
            if "meteo" in down:
                raise ClientError("forecast server down")
            return FakeResponse(SCENARIO.get("meteo", {"hourly": {"time": [], "pm2_5": []}}))
        if url.endswith("/wms"):
            return FakeResponse(b"", "image/png")

        layer, cql = params.get("TYPENAMES") or params.get("TYPENAME"), params.get("CQL_FILTER", "")
        if layer in down or ("main" in down and layer.endswith("reportedfires")):
            raise ClientError(f"{layer} down")
        if layer.endswith("reportedfires"):
            if "BEFORE" in cql:
                if f"fire_year={CLOCK['now'].astimezone(LOCAL).year - 1} " in cql:  # last-year comparison
                    if SCENARIO.get("last_year") is None:
                        raise ClientError("last-year query down")
                    return features(SCENARIO["last_year"])
                # "Known at midnight": every fire except the ones flagged as new today.
                return features(server_filter([f for f in SCENARIO["fires"] if not f.get("_new")], cql))
            return features(server_filter(SCENARIO["fires"], cql))
        if layer.endswith("prescribedfires"):
            return features(SCENARIO.get("burns", []))
        if layer == "public:hotspots_last24hrs":
            return features(SCENARIO.get("hotspots", []))
        if layer == "public:m3_polygons_current":
            return FakeResponse({"features": SCENARIO.get("perimeters", [])})
        if layer == "public:fdr_current_shp":
            return features([{"GRIDCODE": code} for code in SCENARIO.get("danger", [])])
        raise AssertionError(f"unexpected layer {layer}")


SESSION["factory"] = FakeSession

# ---------------------------------------------------------------------------
# Load the integration
# ---------------------------------------------------------------------------
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "custom_components"))
import cwfis  # noqa: E402
from cwfis import binary_sensor, event, geo_location, image, sensor  # noqa: E402

# Home is a different random point on every run, and every fire, zone, hotspot and perimeter below is placed relative
# to it, so the results never depend on one real place. Set CWFIS_TEST_SEED to replay a particular run.
SEED = int(os.environ.get("CWFIS_TEST_SEED", random.randrange(1_000_000)))
_place = random.Random(SEED)
HOME = (round(_place.uniform(42, 52), 2), round(_place.uniform(-120, -62), 2))


def near(dlat, dlon):
    """The point `dlat` degrees north and `dlon` degrees east of Home, as (lat, lon)."""
    return round(HOME[0] + dlat, 4), round(HOME[1] + dlon, 4)


# The usual spot for a test fire: about 555 km north of Home, inside the 600 km alert radius set in OPTIONS.
FIRE_LAT, FIRE_LON = near(4.98, 0.21)


def perimeter(*corners):
    """GeoJSON (lon, lat) corners of a fire perimeter, from (dlat, dlon) offsets from Home."""
    return [[near(dlat, dlon)[1], near(dlat, dlon)[0]] for dlat, dlon in corners]


def fire(fire_id, stage="OC", size=10, lat=FIRE_LAT, lon=FIRE_LON, agency="QC", year=2026, **extra):
    """One reported-fire record as CWFIS returns it."""
    return dict(
        national_fire_id=fire_id,
        agency_code=agency,
        stage_of_control_status=stage,
        fire_size=size,
        latitude=lat,
        longitude=lon,
        status_date="2026-10-12T10:00:00Z",
        fire_year=year,
        **extra,
    )


def forecast(start, values):
    """Open-Meteo style hourly PM2.5 forecast starting at `start`."""
    times = [(start + timedelta(hours=h)).strftime("%Y-%m-%dT%H:%M") for h in range(len(values))]
    return {"hourly": {"time": times, "pm2_5": values}}


class FakeStates:
    """Other Home Assistant entities the integration reads (a watch zone, wind, PM2.5)."""

    def get(self, entity_id):
        return {
            "zone.cottage": types.SimpleNamespace(
                name="Cottage", state="0", attributes={"latitude": FIRE_LAT, "longitude": FIRE_LON}
            ),
            "sensor.wind": types.SimpleNamespace(state="315"),
            "sensor.pm25": types.SimpleNamespace(state="unavailable"),
        }.get(entity_id)


async def _forward_setups(entry, platforms):
    pass


hass = types.SimpleNamespace(
    config=types.SimpleNamespace(latitude=HOME[0], longitude=HOME[1]),
    states=FakeStates(),
    async_create_task=lambda coro: coro.close(),
    config_entries=types.SimpleNamespace(async_forward_entry_setups=_forward_setups),
)
OPTIONS = {
    "radius": 600.0,
    "smoke_radius": 1500.0,
    "zones": ["zone.cottage"],
    "wind_entity": "sensor.wind",
    "pm25_entity": "sensor.pm25",
    "pm25_threshold": 35.0,
    "map_fires": "all",
    "provinces": ["QC", "ON"],
    "map_images": ["fire_danger", "fire_danger_tomorrow"],
}

# Unique IDs must never change between versions, or users' entity IDs/history break.
EXPECTED_UNIQUE_IDS = sorted(
    [
        f"E_{k}"
        for k in (
            "reported_today",
            "active",
            "out",
            "total",
            "area",
            "fires_vs_last_year",
            "area_vs_last_year",
            "smoke_forecast",
        )
    ]
    + [f"E_{p}_{k}" for p in ("qc", "on") for k in ("active", "area")]
    + [
        f"E_{z}{k}"
        for z in ("", "zone.cottage_")
        for k in ("nearest", "nearby", "perimeter", "hotspots", "prescribed", "danger", "fire_nearby")
    ]
    + ["E_fire_upwind", "E_wildfire_smoke", "E_fire_alert", "E_map_fire_danger", "E_map_fire_danger_tomorrow"]
)


async def read_everything(entities):
    """Read each entity's state and attributes, as the HA frontend would. Returns {unique id: state}."""
    states = {}
    for entity in entities:
        entity.hass = getattr(entity, "hass", None) or hass
        entity.name = getattr(entity, "_attr_name", None)
        key = getattr(entity, "_attr_unique_id", entity.name)
        if not entity.available:
            states[key] = "unavailable"
            continue
        if isinstance(entity, geo_location.FireMarker):
            value = (entity.latitude, entity.longitude, entity.distance)
        elif isinstance(entity, image.CwfisMap):
            value = await entity.async_image()
        elif hasattr(entity, "native_value"):
            value = entity.native_value
        else:
            value = getattr(entity, "is_on", None)
        if hasattr(type(entity), "extra_state_attributes"):
            entity.extra_state_attributes  # noqa: B018 - reading it is the test
        states[key] = value
    return states


async def scenario(name, start, data, then=None, expect_events=None, expect=None, expect_failure=False):
    """Set up at time `start` with server data `data`; optionally move to (time, data) `then` and refresh.

    expect: {key: value} checked against entity states (by unique id) or the coordinator's data.
    Returns True when the scenario passes.
    """
    SCENARIO.clear()
    SCENARIO.update(data)
    EVENTS.clear()
    CLOCK["now"] = start
    entry = types.SimpleNamespace(entry_id="E", options=OPTIONS, async_on_unload=lambda f: None)
    try:
        await cwfis.async_setup_entry(hass, entry)
        entities = []
        for platform in (sensor, binary_sensor, event, image, geo_location):
            await platform.async_setup_entry(hass, entry, entities.extend)
        problems = []
        ids = sorted(e._attr_unique_id for e in entities if hasattr(e, "_attr_unique_id"))
        if ids != EXPECTED_UNIQUE_IDS:
            problems.append(f"unique IDs changed: {sorted(set(ids) ^ set(EXPECTED_UNIQUE_IDS))}")
        states = await read_everything(entities)

        if then:
            CLOCK["now"], new_data = then
            SCENARIO.clear()
            SCENARIO.update(new_data)
            await entry.runtime_data.refresh()
            states = await read_everything(entities)

        if expect_events is not None and sorted(EVENTS) != sorted(expect_events):
            problems.append(f"events {EVENTS} != expected {expect_events}")
        for key, want in (expect or {}).items():
            got = states.get(f"E_{key}", entry.runtime_data.data.get(key))
            if got != want:
                problems.append(f"{key} = {got!r}, expected {want!r}")
        print(("PASS  " if not problems else "FAIL  ") + name + "".join(f"\n      - {p}" for p in problems))
        return not problems
    except UpdateFailed as err:
        print(f"{'PASS' if expect_failure else 'FAIL'}  {name}  (UpdateFailed: {err})")
        return expect_failure
    except Exception:  # noqa: BLE001 - report any crash as a failure with its location
        frame = traceback.extract_tb(sys.exc_info()[2])[-1]
        print(
            f"FAIL  {name}\n      - CRASH {sys.exc_info()[0].__name__}: {sys.exc_info()[1]}"
            f"  at {Path(frame.filename).name}:{frame.lineno}  `{frame.line}`"
        )
        return False


async def main() -> bool:
    utc = timezone.utc
    day = datetime(2026, 10, 12, 15, tzinfo=utc)
    results = []

    results.append(
        await scenario(
            "Normal day",
            day,
            {
                "fires": [
                    fire("2026_QC_1"),
                    fire("2026_QC_2", "EX", 500),
                    fire("2026_ON_3", agency="ON", lat=near(6.68, -9.89)[0], lon=near(6.68, -9.89)[1], _new=True),
                ],
                "last_year": [fire("2025_QC_9", "EX", 300, year=2025)],
                "hotspots": [{"lat": FIRE_LAT, "lon": FIRE_LON}],
                "perimeters": [
                    {
                        "geometry": {
                            "type": "Polygon",
                            "coordinates": [perimeter((4.88, 0.11), (4.88, 0.31), (5.08, 0.31), (4.88, 0.11))],
                        }
                    }
                ],
                "meteo": forecast(day - timedelta(hours=2), [8.0] * 72),
            },
            expect={"total": 3, "active": 2, "out": 1, "reported_today": 1, "fires_vs_last_year": 200},
        )
    )

    dec31, jan1 = datetime(2027, 1, 1, 4, 30, tzinfo=utc), datetime(2027, 1, 1, 5, 30, tzinfo=utc)  # 23:30 / 00:30
    holdover = [
        fire("2026_QC_77", "BH", 4000, lat=near(3.78, -2.19)[0], lon=near(3.78, -2.19)[1])
    ]  # still burning over New Year
    results.append(
        await scenario(
            "New Year rollover with a fire still burning",
            dec31,
            {"fires": holdover, "last_year": [], "meteo": forecast(dec31, [5.0] * 72)},
            then=(jan1, {"fires": holdover, "last_year": [], "meteo": forecast(jan1, [5.0] * 72)}),
            expect_events=[],
            expect={"active": 1, "total": 0, "reported_today": 0},
        )
    )

    feb = datetime(2027, 2, 10, 15, tzinfo=utc)
    results.append(
        await scenario(
            "Empty off-season, forecast all null",
            feb,
            {"fires": [], "last_year": [], "meteo": forecast(feb - timedelta(hours=2), [None] * 72)},
            expect={"total": 0, "active": 0, "area": 0, "smoke_forecast": None, "fires_vs_last_year": None},
        )
    )

    dirty = [
        fire("2026_QC_1"),
        fire("2026_QC_1", size=12),  # duplicate record for the same fire
        fire("2026_XX_2", agency=None),
        fire("2026_QC_3", lon=None),
        fire("2026_QC_4", lat=None, lon=None),
        fire("2026_QC_5", size=None),
        fire("2026_QC_6", size=-1),
        fire("2026_QC_7", stage=None),
        fire(None),
        fire("NOUNDERSCORE"),
    ]
    results.append(
        await scenario(
            "Dirty data: nulls, duplicates, odd IDs, invalid codes",
            day,
            {
                "fires": dirty,
                "last_year": [fire("2025_A", size=None, year=2025)],
                "burns": [
                    {"national_fire_id": "RX", "stage_of_control_status": "OC", "latitude": FIRE_LAT, "longitude": None}
                ],
                "hotspots": [{"lat": None, "lon": FIRE_LON}, {"lat": FIRE_LAT, "lon": FIRE_LON}],
                "perimeters": [
                    {"geometry": None},
                    {"geometry": {"type": "Polygon", "coordinates": []}},
                    {
                        "geometry": {
                            "type": "MultiPolygon",
                            "coordinates": [[perimeter((4.98, 0.21), (4.98, 0.31), (5.08, 0.21))]],
                        }
                    },
                ],
                "danger": [None, -1, 7],
                "meteo": forecast(day, [3.0, None, 9.5] + [None] * 69),
            },
            then=(day + timedelta(minutes=30), {"fires": dirty, "last_year": [], "meteo": forecast(day, [3.0] * 72)}),
            expect_events=[],
            expect={"total": 9},
        )
    )

    results.append(
        await scenario(
            "Optional sources down",
            day,
            {
                "fires": [fire("2026_QC_1")],
                "last_year": None,
                "down": {
                    "public:hotspots_last24hrs",
                    "public:m3_polygons_current",
                    "public:fdr_current_shp",
                    "public:cwfif_national_prescribedfires",
                    "meteo",
                },
            },
            expect={"total": 1, "smoke_forecast": None},
        )
    )

    results.append(
        await scenario("Main CWFIS server down at startup", day, {"fires": [], "down": {"main"}}, expect_failure=True)
    )

    leap = datetime(2028, 2, 29, 15, tzinfo=utc)
    results.append(
        await scenario(
            "Leap day (compares with Feb 28 last year)",
            leap,
            {
                "fires": [],
                "last_year": [fire("2027_A", "EX", 50, year=2027)],
                "meteo": forecast(leap - timedelta(hours=1), [4.0] * 72),
            },
            expect={"area_vs_last_year": -100},
        )
    )

    results.append(
        await scenario(
            "Alerts: new fire, stage change, growth, fire out",
            day,
            {"fires": [fire("2026_QC_1", "OC", 50), fire("2026_QC_2", "UC", 5)], "last_year": []},
            then=(
                day + timedelta(minutes=30),
                {
                    "fires": [
                        fire("2026_QC_1", "BH", 80),
                        fire("2026_QC_2", "EX", 5),
                        fire("2026_QC_8", lat=near(3.98, 0.11)[0], lon=near(3.98, 0.11)[1]),
                    ],
                    "last_year": [],
                },
            ),
            # Each alert fires once per zone the fire is in (Home and Cottage both cover these fires).
            expect_events=[("new_fire_nearby", "2026_QC_8")] * 2
            + [("stage_changed", "2026_QC_1")] * 2
            + [("fire_grew", "2026_QC_1")] * 2
            + [("fire_out", "2026_QC_2")] * 2,
        )
    )

    print(f"\n{sum(results)}/{len(results)} scenarios passed (Home at {HOME}, CWFIS_TEST_SEED={SEED})")
    return all(results)


if __name__ == "__main__":
    sys.exit(0 if asyncio.run(main()) else 1)
