"""Small pure helper functions (no Home Assistant state, easy to test on their own)."""

from math import atan2, cos, degrees, radians, sin

from homeassistant.util.location import distance

from .const import STAGES


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


def has_xy(lat, lon) -> bool:
    """True when both coordinates are real numbers inside the valid latitude/longitude range."""
    return isinstance(lat, (int, float)) and isinstance(lon, (int, float)) and -90 <= lat <= 90 and -180 <= lon <= 180


def points(coords):
    """Yield every [lon, lat] pair from GeoJSON coordinates of any nesting depth.

    Polygons and MultiPolygons nest coordinate lists several levels deep; this walks them all
    and silently skips empty or malformed parts instead of raising.
    """
    if not coords:
        return
    if isinstance(coords[0], (int, float)):  # reached a single [lon, lat(, z)] position
        if len(coords) >= 2 and has_xy(coords[1], coords[0]):
            yield coords
    else:
        for part in coords:
            yield from points(part)


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
    """Fire size in hectares; missing or negative ("unknown") sizes count as 0."""
    value = fire.get("fire_size")
    return max(value, 0) if isinstance(value, (int, float)) else 0


def pct_change(now: float, before: float | None) -> int | None:
    """Whole-number percent change from `before` to `now`, or None when there's no baseline."""
    return round((now - before) / before * 100) if before else None


def state_as_float(hass, entity_id: str) -> float | None:
    """Numeric state of another Home Assistant entity, or None if it's missing/unknown/non-numeric."""
    try:
        return float(hass.states.get(entity_id).state)
    except (AttributeError, TypeError, ValueError):
        return None


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
