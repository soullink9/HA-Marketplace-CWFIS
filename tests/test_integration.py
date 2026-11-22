"""Offline simulation of the CWFIS integration — run before every release.

    python3 tests/test_integration.py

No Home Assistant install or internet connection needed: Home Assistant and aiohttp are replaced by
the stand-ins in stubs.py, and the CWFIS / Open-Meteo servers by fake responses. Each scenario sets up the
integration, reads every entity the way the HA frontend would, and checks the results.

Add a scenario whenever a real-world data problem turns up, so it can never come back unnoticed.
Exit code is 0 when every scenario passes, 1 otherwise.
"""

import asyncio
from datetime import UTC, datetime, timedelta
import json
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
from stubs import CLOCK, EVENTS, LOCAL, SESSION, STORAGE, ClientError, UpdateFailed  # noqa: E402,I001  (registers the stand-ins first)

# ---------------------------------------------------------------------------
# Fake servers. SCENARIO holds the data the current scenario wants them to return.
# ---------------------------------------------------------------------------
SCENARIO: dict = {}


PNG = b"\x89PNG\r\n\x1a\n" + b"\0" * 100  # enough of a PNG for the integration's checks


class FakeStream:
    def __init__(self, data):
        self.data = data

    async def iter_chunked(self, n):
        for start in range(0, len(self.data), n):
            yield self.data[start : start + n]


class FakeResponse:
    def __init__(self, body, content_type="application/json", status=200, content_length=None):
        self.body, self.content_type, self.status, self.content_length = body, content_type, status, content_length
        self.content = FakeStream(body if isinstance(body, bytes) else str(body).encode())

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
            if "meteo_raw" in SCENARIO:
                return FakeResponse(SCENARIO["meteo_raw"])
            return FakeResponse(SCENARIO.get("meteo", {"hourly": {"time": [], "pm2_5": []}}))
        if url.endswith("/wms"):
            return FakeResponse(*SCENARIO.get("map", (PNG, "image/png")))

        layer, cql = params.get("TYPENAMES") or params.get("TYPENAME"), params.get("CQL_FILTER", "")
        if layer in down or ("main" in down and layer.endswith("reportedfires")):
            raise ClientError(f"{layer} down")
        if layer in SCENARIO.get("raw", {}):  # a response exactly as given, however malformed
            return FakeResponse(SCENARIO["raw"][layer])
        if layer.endswith("reportedfires"):
            if "BEFORE" in cql:
                if "known" in down and params.get("PROPERTYNAME") == "national_fire_id":
                    raise ClientError("known-at-midnight query down")
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
from cwfis import binary_sensor, const, event, geo_location, image, sensor  # noqa: E402

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
    """One reported-fire record as CWFIS returns it (`extra` adds or replaces fields)."""
    record = dict(
        national_fire_id=fire_id,
        agency_code=agency,
        stage_of_control_status=stage,
        fire_size=size,
        latitude=lat,
        longitude=lon,
        status_date="2026-10-12T10:00:00Z",
        fire_year=year,
    )
    return record | extra


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
    config=types.SimpleNamespace(latitude=HOME[0], longitude=HOME[1], country="US"),
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
        for k in (
            "nearest",
            "nearby",
            "perimeter",
            "hotspots",
            "prescribed",
            "danger",
            "fire_nearby",
            "smoke_impact",
            "fire_threat",
        )
    ]
    + ["E_fire_upwind", "E_wildfire_smoke", "E_fire_alert", "E_map_fire_danger", "E_map_fire_danger_tomorrow"]
)

# Entity names, by unique ID without the entry ID. A new install's entity IDs come from them, so they stay the same
# from version to version too. They come from translations/en.json, with icons from icons.json (see entity.py).
EXPECTED_NAMES = {
    "active": "Active fires",
    "area": "Area burned",
    "area_vs_last_year": "Area burned vs last year",
    "danger": "Fire danger",
    "fire_alert": "Fire alert",
    "fire_threat": "Fire threat",
    "fire_nearby": "Fire within alert radius",
    "fire_upwind": "Fire upwind",
    "fires_vs_last_year": "Fires vs last year",
    "hotspots": "Hotspots nearby (24h)",
    "map_fire_danger": "Fire danger map",
    "map_fire_danger_tomorrow": "Fire danger forecast map (tomorrow)",
    "nearby": "Active fires nearby",
    "nearest": "Nearest active fire",
    "on_active": "Active fires (Ontario)",
    "on_area": "Area burned (Ontario)",
    "out": "Out fires",
    "perimeter": "Nearest fire perimeter",
    "prescribed": "Prescribed burns nearby",
    "qc_active": "Active fires (Quebec)",
    "qc_area": "Area burned (Quebec)",
    "reported_today": "Reported today",
    "smoke_impact": "Smoke impact",
    "smoke_forecast": "Smoke forecast PM2.5 (24h max)",
    "total": "Total fires",
    "wildfire_smoke": "Wildfire smoke",
    "zone.cottage_danger": "Fire danger (Cottage)",
    "zone.cottage_fire_nearby": "Fire within alert radius (Cottage)",
    "zone.cottage_fire_threat": "Fire threat (Cottage)",
    "zone.cottage_smoke_impact": "Smoke impact (Cottage)",
    "zone.cottage_hotspots": "Hotspots nearby (24h) (Cottage)",
    "zone.cottage_nearby": "Active fires nearby (Cottage)",
    "zone.cottage_nearest": "Nearest active fire (Cottage)",
    "zone.cottage_perimeter": "Nearest fire perimeter (Cottage)",
    "zone.cottage_prescribed": "Prescribed burns nearby (Cottage)",
}
INTEGRATION_DIR = Path(__file__).resolve().parents[1] / "custom_components" / "cwfis"
TRANSLATIONS = json.loads((INTEGRATION_DIR / "translations" / "en.json").read_text(encoding="utf-8"))
ICONS = json.loads((INTEGRATION_DIR / "icons.json").read_text(encoding="utf-8"))


def naming_problems(entities):
    """Check every entity's name and icon resolve from its translation key, to the names in EXPECTED_NAMES."""
    problems = []
    for entity in entities:
        if isinstance(entity, geo_location.FireMarker):
            continue  # markers are named after their fire
        platform, key = type(entity).__module__.rsplit(".", 1)[-1], entity._attr_translation_key
        template = TRANSLATIONS["entity"].get(platform, {}).get(key, {}).get("name")
        if template is None:
            problems.append(f"{platform}.{key} has no name in translations/en.json")
            continue
        name = template.format(**(getattr(entity, "_attr_translation_placeholders", None) or {}))
        uid = entity._attr_unique_id.removeprefix("E_")
        if name != EXPECTED_NAMES.get(uid):
            problems.append(f"{uid} is named {name!r}, expected {EXPECTED_NAMES.get(uid)!r}")
        if "default" not in ICONS["entity"].get(platform, {}).get(key, {}):
            problems.append(f"{platform}.{key} has no icon in icons.json")
    return problems


def selector_problems():
    """Every choice in the Configure form's lists has a label in translations/en.json."""
    problems = []
    for selector, options in (
        ("map_fires", const.MAP_FIRES_MODES),
        ("map_images", list(const.MAPS)),
        ("air_quality_scale", const.AQ_SCALES),
    ):
        labels = TRANSLATIONS["selector"][selector]["options"]
        if sorted(labels) != sorted(options):
            problems.append(f"selector.{selector} labels {sorted(labels)} != options {sorted(options)}")
    return problems


def level_problems():
    """The US AQI and AQHI lookups give the published levels at and either side of each breakpoint."""
    from cwfis.helpers import air_quality  # noqa: PLC0415

    cases = [
        (0, "us_aqi", "good", 0),
        (9.0, "us_aqi", "good", 50),
        (9.1, "us_aqi", "moderate", 51),
        (35.4, "us_aqi", "moderate", 100),
        (35.49, "us_aqi", "moderate", 100),
        (35.5, "us_aqi", "unhealthy_sensitive", 101),
        (55.5, "us_aqi", "unhealthy", 151),
        (125.5, "us_aqi", "very_unhealthy", 201),
        (225.5, "us_aqi", "hazardous", 301),
        (900, "us_aqi", "hazardous", 500),
        (0, "ca_aqhi", "low_risk", 1),
        (30, "ca_aqhi", "low_risk", 3),
        (30.1, "ca_aqhi", "moderate_risk", 4),
        (60.1, "ca_aqhi", "high_risk", 7),
        (100, "ca_aqhi", "high_risk", 10),
        (100.1, "ca_aqhi", "very_high_risk", "10+"),
    ]
    problems = []
    for pm25, scale, level, index in cases:
        got = air_quality(pm25, scale)
        if (got["level"], got["index"]) != (level, index):
            problems.append(f"{pm25} µg/m³ on {scale} = {got['level']} {got['index']}, expected {level} {index}")
    return problems


def helper_problems():
    """number(), clean_fire(), points() and state_as_float() turn anything a server or sensor sends into safe values."""
    from cwfis import helpers  # noqa: PLC0415

    problems = []
    for value, want in (
        (5, 5.0),
        (2.5, 2.5),
        (True, None),
        (float("nan"), None),
        (float("inf"), None),
        (10**400, None),
        (-1, None),
        (101, None),
        ("5", None),
        (None, None),
    ):
        if helpers.number(value, 0, 100) != want:
            problems.append(f"number({value!r:.20}, 0, 100) = {helpers.number(value, 0, 100)!r}, expected {want!r}")
    if helpers.clean_fire("x") is not None or helpers.clean_fire(None) is not None:
        problems.append("clean_fire accepts a record that isn't an object")
    cleaned = helpers.clean_fire({"national_fire_id": " " + "x" * 500, "fire_size": -1, "fire_year": 2026.5})
    if (len(cleaned["national_fire_id"]), cleaned["fire_size"], cleaned["fire_year"]) != (const.MAX_TEXT, None, None):
        problems.append(f"clean_fire gave {cleaned}")
    deep = [[1.0, 2.0]]
    for _ in range(const.MAX_GEOMETRY_DEPTH + 5):
        deep = [deep]
    if list(helpers.points(deep)) or list(helpers.points({"not": "a list"})) != []:
        problems.append("points() walks geometry deeper than MAX_GEOMETRY_DEPTH, or a non-list")
    if list(helpers.points([[[1.0, 2.0], [3.0, 4.0]]])) != [[1.0, 2.0], [3.0, 4.0]]:
        problems.append("points() misses a normal polygon's vertices")
    states = types.SimpleNamespace(get=lambda e: types.SimpleNamespace(state=e))
    for state in ("nan", "inf", "-inf", "abc"):
        if helpers.state_as_float(types.SimpleNamespace(states=states), state) is not None:
            problems.append(f"state_as_float accepts {state!r}")
    return problems


def blueprint_problems():
    """The notification blueprint only uses inputs it declares, and offers only levels the sensors can have."""
    path = Path(__file__).resolve().parents[1] / "blueprints" / "automation" / "cwfis" / "local_impact_alert.yaml"
    text = path.read_text(encoding="utf-8")
    declared = set(re.findall(r"^ {8}(\w+):\n {10}name:", text, re.MULTILINE))
    used = set(re.findall(r"!input (\w+)", text))
    problems = [f"blueprint uses undeclared input {name}" for name in sorted(used - declared)]
    problems += [f"blueprint declares unused input {name}" for name in sorted(declared - used)]
    states = {level[0] for level in const.US_AQI + const.CA_AQHI} | set(const.FIRE_THREAT)
    problems += [f"blueprint offers unknown level {v}" for v in re.findall(r"value: (\w+)", text) if v not in states]
    return problems


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


async def set_up(options):
    """Set up the integration and every entity, as Home Assistant does at start-up. Returns (entry, entities)."""
    entry = types.SimpleNamespace(entry_id="E", options={**OPTIONS, **(options or {})}, async_on_unload=lambda f: None)
    await cwfis.async_setup_entry(hass, entry)
    entities = []
    for platform in (sensor, binary_sensor, event, image, geo_location):
        await platform.async_setup_entry(hass, entry, entities.extend)
    for entity in entities:
        entity.hass = getattr(entity, "hass", None) or hass
        await entity.async_added_to_hass()
    return entry, entities


async def scenario(
    name,
    start,
    data,
    then=None,
    expect_events=None,
    expect=None,
    expect_failure=False,
    options=None,
    attrs=None,
    restart=None,
    storage=None,
):
    """Set up at time `start` with server data `data`; optionally move to (time, data) `then` and refresh.

    restart: (time, data) to restart Home Assistant at instead, keeping what was saved in .storage/.
    storage: what .storage/ holds before the first set-up (empty when not given).
    expect: {key: value} checked against entity states (by unique id) or the coordinator's data.
    attrs: {(unique id, attribute): value} checked against entity attributes.
    options: settings to change from OPTIONS for this scenario.
    Returns True when the scenario passes.
    """
    SCENARIO.clear()
    SCENARIO.update(data)
    EVENTS.clear()
    STORAGE.clear()
    STORAGE.update(storage or {})
    CLOCK["now"] = start
    try:
        entry, entities = await set_up(options)
        problems = []
        ids = sorted(e._attr_unique_id for e in entities if hasattr(e, "_attr_unique_id"))
        if ids != EXPECTED_UNIQUE_IDS:
            problems.append(f"unique IDs changed: {sorted(set(ids) ^ set(EXPECTED_UNIQUE_IDS))}")
        problems += naming_problems(entities)
        states = await read_everything(entities)

        if then:
            CLOCK["now"], new_data = then
            SCENARIO.clear()
            SCENARIO.update(new_data)
            await entry.runtime_data.refresh()
            states = await read_everything(entities)
        if restart:
            CLOCK["now"], new_data = restart
            SCENARIO.clear()
            SCENARIO.update(new_data)
            entry, entities = await set_up(options)
            states = await read_everything(entities)

        if expect_events is not None and sorted(EVENTS) != sorted(expect_events):
            problems.append(f"events {EVENTS} != expected {expect_events}")
        for key, want in (expect or {}).items():
            got = states.get(f"E_{key}", entry.runtime_data.data.get(key))
            if got != want:
                problems.append(f"{key} = {got!r}, expected {want!r}")
        by_id = {getattr(e, "_attr_unique_id", None): e for e in entities}
        for (key, attr), want in (attrs or {}).items():
            got = (by_id[f"E_{key}"].extra_state_attributes or {}).get(attr)
            if got != want:
                problems.append(f"{key}.{attr} = {got!r}, expected {want!r}")
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
    utc = UTC
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

    # Local impact: Home is ~555 km from the fire (inside the 600 km alert radius), the Cottage sits right on it.
    smoky = forecast(day - timedelta(hours=2), [8.0] * 2 + [12.0] + [60.0] * 30 + [8.0] * 39)
    impact_data = {"fires": [fire("2026_QC_1")], "last_year": [], "meteo": smoky}
    results.append(
        await scenario(
            "Local impact: smoke on its way (US AQI), fire at the Cottage",
            day,
            impact_data,
            expect={
                "smoke_impact": "unhealthy",
                "zone.cottage_smoke_impact": "unhealthy",
                "fire_threat": "watch",
                "zone.cottage_fire_threat": "danger",
            },
            attrs={
                ("smoke_impact", "level_now"): "moderate",
                ("smoke_impact", "pm25_now"): 12.0,
                ("smoke_impact", "pm25_now_source"): "forecast",
                ("smoke_impact", "index"): 154,
                ("smoke_impact", "severity"): 3,
                ("fire_threat", "severity"): 1,
                ("zone.cottage_fire_threat", "severity"): 3,
            },
        )
    )
    results.append(
        await scenario(
            "Local impact: Canada's AQHI, and a controlled fire is only a warning",
            day,
            {**impact_data, "fires": [fire("2026_QC_1", "UC")]},
            options={"air_quality_scale": "ca_aqhi"},
            expect={"smoke_impact": "moderate_risk", "zone.cottage_fire_threat": "warning"},
            attrs={("smoke_impact", "index"): 6, ("smoke_impact", "level_now"): "low_risk"},
        )
    )
    hotspot = near(0.2, 0)  # ~22 km north of Home
    results.append(
        await scenario(
            "Local impact: a hotspot inside the warning distance, nothing reported, automatic scale",
            day,
            {"fires": [], "last_year": [], "hotspots": [{"lat": hotspot[0], "lon": hotspot[1]}], "danger": [4]},
            options={"air_quality_scale": "auto", "danger_distance": 10, "warning_distance": 40},
            expect={"fire_threat": "warning", "smoke_impact": None, "zone.cottage_fire_threat": "watch"},
            attrs={("smoke_impact", "scale"): "us_aqi", ("fire_threat", "nearest_hotspot_km"): 22.2},
        )
    )

    # --- Malformed and hostile responses: each bad value is skipped or treated as missing, never fatal ---
    nan, inf = float("nan"), float("inf")
    deep = [[FIRE_LON, FIRE_LAT]]
    for _ in range(200):  # far deeper than any real geometry
        deep = [deep]
    hostile_fires = {
        "features": [
            "not a feature",
            None,
            {"properties": None},
            {"properties": ["a", "list"]},
            {"properties": fire("2026_QC_1", size=40)},
            {"properties": fire("2026_QC_2", size=nan)},
            {"properties": fire("2026_QC_3", size=inf)},
            {"properties": fire("2026_QC_4", size=10**400)},  # too big for a float
            {"properties": fire("2026_QC_5", size=True, lat=True, lon=False)},
            {"properties": fire("2026_QC_6", size="12", lat=nan, lon=inf)},
            {"properties": fire(["unhashable"], stage={"a": 1}, agency=7, status_date=20261012)},
            {"properties": fire(12345, year=1e300)},  # a numeric ID is kept as text; an impossible year is missing
            {"properties": fire("2026_QC_7", status_date=None, year="2026")},
        ]
    }
    hostile = {
        "fires": [],
        "raw": {
            "public:cwfif_national_reportedfires": hostile_fires,
            "public:hotspots_last24hrs": {
                "features": [{"properties": ["x"]}, {"properties": {"lat": nan, "lon": 0}}, 5, {"properties": None}]
            },
            "public:m3_polygons_current": {
                "features": [
                    {"geometry": "a string"},
                    {"geometry": {"coordinates": deep}},
                    {"geometry": {"coordinates": [[[nan, inf], [True, False], "x", None]]}},
                ]
            },
            "public:fdr_current_shp": {
                "features": [{"properties": {"GRIDCODE": g}} for g in (True, nan, inf, 2.5, -1, 99, "4")]
            },
            "public:cwfif_national_prescribedfires": {"features": [{"properties": "x"}]},
        },
        "last_year": [fire("2025_A", size=inf, year=2025)],
        "meteo_raw": {
            "hourly": {
                "time": [(day + timedelta(hours=h)).strftime("%Y-%m-%dT%H:%M") for h in range(6)] + [5, "garbage"],
                "pm2_5": [nan, inf, -3.0, 1e9, "12", 22.5, 50.0, 60.0],
            }
        },
    }
    results.append(
        await scenario(
            "Hostile data: non-objects, NaN, infinity, huge numbers, wrong types, absurdly deep geometry",
            day,
            hostile,
            then=(day + timedelta(minutes=30), hostile),
            expect_events=[],
            expect={
                "active": 9,  # every record with properties that are an object
                "total": 7,  # ...of which 7 have this year as a believable fire_year
                "area": 50,  # 40 ha + 10 ha; NaN, infinity, huge, true and text sizes count as nothing
                "hotspots": 0,
                "perimeter": None,
                "danger": None,
                "prescribed": 0,
                "smoke_forecast": 22.5,  # NaN, infinity, negative, absurd and non-numeric hours skipped
                "smoke_impact": "moderate",
                "fire_threat": "watch",
            },
        )
    )

    results.append(
        await scenario(
            "Main CWFIS response isn't a feature collection: the update fails cleanly",
            day,
            {"fires": [], "raw": {"public:cwfif_national_reportedfires": {"features": "oops"}}},
            expect_failure=True,
        )
    )

    results.append(
        await scenario(
            "Only Reported today goes unknown when its query fails",
            day,
            {"fires": [fire("2026_QC_1")], "last_year": [], "down": {"known"}},
            expect={"reported_today": None, "total": 1, "active": 1},
        )
    )

    results.append(
        await scenario(
            "Optional responses malformed: each goes unknown on its own",
            day,
            {
                "fires": [fire("2026_QC_1")],
                "last_year": [],
                "raw": {
                    "public:hotspots_last24hrs": [],
                    "public:m3_polygons_current": {"features": None},
                    "public:fdr_current_shp": "not JSON",
                    "public:cwfif_national_prescribedfires": {"no": "features"},
                },
                "meteo_raw": {"hourly": "nope"},
            },
            expect={
                "total": 1,
                "hotspots": None,
                "perimeter": None,
                "danger": None,
                "prescribed": None,
                "smoke_forecast": None,
                "fire_nearby": True,
                "fire_threat": "watch",
            },
        )
    )

    # --- Map images: only a real PNG within the size limit is shown ---
    big = const.MAX_MAP_BYTES + 1
    for label, response, want in (
        ("a PNG", (PNG, "image/png"), PNG),
        ("HTML labelled image/png", (b"<html>hi</html>", "image/png"), None),
        ("another image type", (PNG, "image/svg+xml"), None),
        ("too large, by its Content-Length", (PNG, "image/png", 200, big), None),
        ("too large, without a Content-Length", (PNG + b"\0" * big, "image/png"), None),
        ("a server error", (b"<ServiceException>Bad layer</ServiceException>", "text/xml", 500), None),
    ):
        results.append(
            await scenario(
                f"Map image: {label}",
                day,
                {"fires": [], "last_year": [], "map": response},
                expect={"map_fire_danger": want, "map_fire_danger_tomorrow": want},
            )
        )
    message = image.server_errors(
        b"<ServiceException code='x'>Layer <b>bad</b>\x1b[31m\n  gone</ServiceException>" + b"A" * 1000
    )
    problems = [] if message == "Layer bbad/b[31m gone" else [f"logged error text is {message!r}"]
    long = image.server_errors(b"<ServiceException>" + b"x" * 5000 + b"</ServiceException>")
    problems += [] if len(long) == image.MAX_ERROR_TEXT else [f"logged error text is {len(long)} characters"]
    print(("PASS  " if not problems else "FAIL  ") + "Map errors: only GeoServer's message is logged, short and plain")
    print("".join(f"      - {p}\n" for p in problems), end="")
    results.append(not problems)

    # --- Fire alert baseline survives a restart ---
    before = {"fires": [fire("2026_QC_1", "OC", 50), fire("2026_QC_2", "UC", 5)], "last_year": []}
    after = {
        "fires": [
            fire("2026_QC_1", "BH", 80),
            fire("2026_QC_2", "EX", 5),
            fire("2026_QC_8", lat=near(3.98, 0.11)[0], lon=near(3.98, 0.11)[1]),
        ],
        "last_year": [],
    }
    results.append(
        await scenario(
            "Restart: what changed while Home Assistant was stopped is still reported",
            day,
            before,
            restart=(day + timedelta(hours=1), after),
            expect_events=[("new_fire_nearby", "2026_QC_8")] * 2
            + [("stage_changed", "2026_QC_1")] * 2
            + [("fire_grew", "2026_QC_1")] * 2
            + [("fire_out", "2026_QC_2")] * 2,
        )
    )
    slow = {"fires": [fire("2026_QC_1", "OC", 100)], "last_year": []}
    results.append(
        await scenario(
            "Restart: slow growth keeps adding up from the last alert's size",
            day,
            slow,
            then=(day + timedelta(minutes=30), {**slow, "fires": [fire("2026_QC_1", "OC", 115)]}),
            restart=(day + timedelta(hours=1), {**slow, "fires": [fire("2026_QC_1", "OC", 130)]}),
            expect_events=[("fire_grew", "2026_QC_1")] * 2,  # 100 -> 130 ha is 30 %, though no step was 25 %
        )
    )
    results.append(
        await scenario(
            "Restart after a long time off: starts afresh instead of a burst of old news",
            day,
            before,
            restart=(day + const.ALERT_BASELINE_MAX_AGE + timedelta(hours=1), after),
            expect_events=[],
        )
    )
    key = const.ALERT_STORAGE_KEY.format(entry_id="E")
    junk = {
        "saved": (day - timedelta(minutes=5)).isoformat(),
        "fires": [
            "x",
            {"zone_id": "home", "zone": "Home", "fire": {"national_fire_id": "2026_QC_1"}},  # no distance/bearing
            {"zone_id": None, "fire": fire("2026_QC_1", distance=1, bearing=1)},
            {"zone_id": "home", "zone": "Home", "fire": fire("2026_QC_1", distance=nan, bearing=1)},
            {"zone_id": "home", "zone": ["x"], "fire": fire("2026_QC_9", distance=5.0, bearing=90)},
        ],
    }
    for label, saved, events in (
        (
            "unreadable entries are skipped one by one",
            {"version": 1, "data": json.dumps(junk)},
            # Only QC_9's entry holds up, so QC_1 is new to the baseline, and QC_9 has gone out.
            [("new_fire_nearby", "2026_QC_1")] * 2 + [("fire_out", "2026_QC_9")],
        ),
        ("not a baseline at all", {"version": 1, "data": json.dumps(["x"])}, []),
        ("an older layout with no migration", {"version": 0, "data": json.dumps(junk)}, []),
    ):
        results.append(
            await scenario(
                f"Saved baseline: {label}",
                day,
                {"fires": [fire("2026_QC_1")], "last_year": []},
                storage={key: saved},
                expect_events=events,
            )
        )
    await cwfis.async_remove_entry(hass, types.SimpleNamespace(entry_id="E"))
    print(("PASS  " if key not in STORAGE else "FAIL  ") + "Removing the integration deletes its saved baseline")
    results.append(key not in STORAGE)

    problems = helper_problems()
    print(("PASS  " if not problems else "FAIL  ") + "Value checks" + "".join(f"\n      - {p}" for p in problems))
    results.append(not problems)

    problems = level_problems() + blueprint_problems()
    print(
        ("PASS  " if not problems else "FAIL  ")
        + "Air quality levels and blueprint"
        + "".join(f"\n      - {p}" for p in problems)
    )
    results.append(not problems)

    problems = selector_problems()
    print(
        ("PASS  " if not problems else "FAIL  ") + "Configure form labels" + "".join(f"\n      - {p}" for p in problems)
    )
    results.append(not problems)

    print(f"\n{sum(results)}/{len(results)} scenarios passed (Home at {HOME}, CWFIS_TEST_SEED={SEED})")
    return all(results)


if __name__ == "__main__":
    sys.exit(0 if asyncio.run(main()) else 1)
