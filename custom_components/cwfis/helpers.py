"""Small pure helper functions (no Home Assistant state, easy to test on their own)."""

from math import atan2, ceil, cos, degrees, floor, isfinite, radians, sin

from homeassistant.util.location import distance

from .const import (
    CA_AQHI,
    FIRE_YEARS,
    MAX_FIRE_SIZE_HA,
    MAX_GEOMETRY_DEPTH,
    MAX_TEXT,
    STAGES,
    US_AQI,
    WATCH_DANGER_LEVELS,
)


def km(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """Great-circle distance between two points in kilometres."""
    return distance(lat1, lon1, lat2, lon2) / 1000


def bearing(lat1: float, lon1: float, lat2: float, lon2: float) -> int:
    """Initial compass bearing (0-359°) from point 1 towards point 2 (standard forward-azimuth formula)."""
    p1, p2, dl = radians(lat1), radians(lat2), radians(lon2 - lon1)
    x = sin(dl) * cos(p2)
    y = cos(p1) * sin(p2) - sin(p1) * cos(p2) * cos(dl)
    return round(degrees(atan2(x, y))) % 360


def compass(deg: float) -> str:
    """Turn a bearing in degrees into a 16-point compass direction, e.g. 337 -> 'NNW'."""
    return ["N", "NNE", "NE", "ENE", "E", "ESE", "SE", "SSE", "S", "SSW", "SW", "WSW", "W", "WNW", "NW", "NNW"][
        round(deg / 22.5) % 16
    ]


def number(value, low: float, high: float) -> float | None:
    """`value` as a float when it's a finite number from `low` to `high`, else None.

    Server data is untrusted: JSON can carry NaN, Infinity, huge integers or true/false where a number belongs.
    """
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    try:
        value = float(value)
    except OverflowError:  # an integer too big for a float
        return None
    return value if isfinite(value) and low <= value <= high else None


def has_xy(lat, lon) -> bool:
    """True when both coordinates are finite numbers inside the valid latitude/longitude range."""
    return number(lat, -90, 90) is not None and number(lon, -180, 180) is not None


def text(value) -> str | None:
    """A text field from the server, trimmed and length-capped, or None when it's empty or not text.

    A whole-number ID (some agencies send numbers) is kept as text, so it can be compared and used as a key.
    """
    if isinstance(value, int) and not isinstance(value, bool):
        value = str(value)
    if not isinstance(value, str):
        return None
    return value.strip()[:MAX_TEXT] or None


def clean_fire(properties) -> dict | None:
    """One fire record from the server with every field checked, or None when it isn't a record at all.

    A field with the wrong type or an impossible value becomes None, as if the server had left it out: the fire is
    kept, and whatever uses that field treats it as missing.
    """
    if not isinstance(properties, dict):
        return None
    year = number(properties.get("fire_year"), *FIRE_YEARS)
    return {
        "national_fire_id": text(properties.get("national_fire_id")),
        "agency_code": text(properties.get("agency_code")),
        "stage_of_control_status": text(properties.get("stage_of_control_status")),
        "fire_size": number(properties.get("fire_size"), 0, MAX_FIRE_SIZE_HA),
        "latitude": number(properties.get("latitude"), -90, 90),
        "longitude": number(properties.get("longitude"), -180, 180),
        "status_date": text(properties.get("status_date")),
        "fire_year": int(year) if year is not None and year.is_integer() else None,
    }


def points(coords, depth: int = 0):
    """Yield every [lon, lat] pair from GeoJSON coordinates of any nesting depth.

    Polygons and MultiPolygons nest coordinate lists several levels deep; this walks them all
    and silently skips empty, malformed or implausibly deep parts instead of raising.
    """
    if not coords or not isinstance(coords, list) or depth > MAX_GEOMETRY_DEPTH:
        return
    if isinstance(coords[0], (int, float)):  # reached a single [lon, lat(, z)] position
        if len(coords) >= 2 and has_xy(coords[1], coords[0]):
            yield coords
    else:
        for part in coords:
            yield from points(part, depth + 1)


def dedupe(fires: list[dict]) -> list[dict]:
    """Keep one record per fire ID (the one with the newest status date).

    Records without an ID can't be matched, so each one is kept as-is.
    """
    best: dict = {}
    for index, fire in enumerate(fires):
        key = fire.get("national_fire_id") or index
        newest = (best[key].get("status_date") or "") if key in best else None
        if newest is None or (fire.get("status_date") or "") >= newest:
            best[key] = fire
    return list(best.values())


def fire_size(fire: dict) -> float:
    """Fire size in hectares; missing, negative ("unknown") or impossible sizes count as 0."""
    return number(fire.get("fire_size"), 0, MAX_FIRE_SIZE_HA) or 0


def pct_change(now: float, before: float | None) -> int | None:
    """Whole-number percent change from `before` to `now`, or None when there's no baseline."""
    return round((now - before) / before * 100) if before else None


def state_as_float(hass, entity_id: str) -> float | None:
    """Numeric state of another Home Assistant entity, or None if it's missing/unknown/non-numeric/not finite."""
    try:
        value = float(hass.states.get(entity_id).state)
    except AttributeError, TypeError, ValueError:
        return None
    return value if isfinite(value) else None


def fire_info(fire: dict) -> dict:
    """Human-readable attributes for one fire.

    Distance and direction are relative to whichever zone the fire was measured from.
    """
    stage = fire.get("stage_of_control_status")
    return {
        "fire": fire["national_fire_id"],
        "agency": fire.get("agency_code"),
        "stage_of_control": STAGES.get(stage, stage),
        "size_ha": fire.get("fire_size"),
        "distance_km": fire["distance"],
        "direction": compass(fire["bearing"]),
        "status_date": fire.get("status_date"),
    }


def air_quality(pm25: float, scale: str) -> dict:
    """Air quality level for a PM2.5 value (µg/m³) on the US AQI ("us_aqi") or Canada's AQHI-Plus ("ca_aqhi").

    Returns the level key, the index number, its severity (the level's position, 0 = best) and the advice.
    """
    if scale == "ca_aqhi":
        index = max(1, ceil(pm25 / 10))
        for severity, (level, highest, advice) in enumerate(CA_AQHI):
            if highest is None or index <= highest:
                return {
                    "level": level,
                    "index": index if index <= 10 else "10+",
                    "severity": severity,
                    "advice": advice,
                }

    pm25 = floor(max(pm25, 0) * 10) / 10  # the EPA truncates PM2.5 to one decimal before looking it up
    low = 0.0
    for severity, (level, high, aqi_low, aqi_high, advice) in enumerate(US_AQI):
        if pm25 <= high or severity == len(US_AQI) - 1:
            index = round(aqi_low + (aqi_high - aqi_low) * (min(pm25, high) - low) / (high - low))
            return {"level": level, "index": index, "severity": severity, "advice": advice}
        low = high + 0.1
    raise AssertionError("unreachable")  # the last level catches everything


def fire_threat(zone: dict, danger_km: float, warning_km: float) -> tuple[str, str]:
    """Fire threat level for one zone's data, and the reason for it.

    danger:  a fire that isn't under control, or a fire perimeter, within danger_km.
    warning: any active fire, perimeter or satellite hotspot within warning_km (or a controlled fire in danger_km).
    watch:   an active fire or hotspot inside the alert radius, or a Very high / Extreme fire danger rating.
    """
    nearest, perimeter, hotspot = zone["nearest"], zone["perimeter"], zone.get("hotspot_distance")
    uncontrolled = next((f for f in zone["nearby"] if f.get("stage_of_control_status") != "UC"), None)

    def fire_text(fire):
        stage = fire.get("stage_of_control_status")
        return (
            f"{STAGES.get(stage, stage or 'Active').lower().capitalize()} fire {fire['national_fire_id']} "
            f"{fire['distance']} km {compass(fire['bearing'])}"
        )

    if uncontrolled and uncontrolled["distance"] <= danger_km:
        return "danger", fire_text(uncontrolled)
    if perimeter is not None and perimeter <= danger_km:
        return "danger", f"Fire perimeter {perimeter} km away"
    if nearest and nearest["distance"] <= warning_km:
        return "warning", fire_text(nearest)
    if perimeter is not None and perimeter <= warning_km:
        return "warning", f"Fire perimeter {perimeter} km away"
    if hotspot is not None and hotspot <= warning_km:
        return "warning", f"Satellite hotspot {hotspot} km away (possibly an unreported fire)"
    if zone["nearby"]:
        return "watch", f"{len(zone['nearby'])} active fire(s) in the alert radius, nearest {fire_text(nearest)}"
    if zone["hotspots"]:
        return "watch", f"{zone['hotspots']} satellite hotspot(s) in the alert radius"
    if zone["danger"] in WATCH_DANGER_LEVELS:
        return "watch", f"Fire danger is {zone['danger']}"
    return "none", "No active fires or hotspots in the alert radius"
