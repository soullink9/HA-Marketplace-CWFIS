"""Binary sensors: fire within alert radius, fire upwind, wildfire smoke."""

from __future__ import annotations

from homeassistant.components.binary_sensor import BinarySensorDeviceClass, BinarySensorEntity
from homeassistant.core import callback
from homeassistant.helpers.event import async_track_state_change_event

from .const import (
    CONF_PM25,
    CONF_PM25_THRESHOLD,
    CONF_RADIUS,
    CONF_WIND,
    DEFAULT_PM25,
    DEFAULT_RADIUS,
    MAX_LISTED_FIRES,
    UPWIND_SPREAD,
)
from .entity import CwfisEntity
from .helpers import fire_info, state_as_float


async def async_setup_entry(hass, entry, async_add_entities):
    """One "Fire within alert radius" per zone; upwind/smoke only when their source sensors are set."""
    opts = entry.options
    entities = [FireNearby(entry, zone) for zone in entry.runtime_data.data["zones"]]
    if wind := opts.get(CONF_WIND):
        entities.append(FireUpwind(entry, wind))
    if pm25 := opts.get(CONF_PM25):
        entities.append(WildfireSmoke(entry, pm25, wind, opts.get(CONF_PM25_THRESHOLD, DEFAULT_PM25)))
    async_add_entities(entities)


def upwind_fires(hass, coordinator, wind_entity: str) -> list[dict] | None:
    """Fires within the smoke radius that lie in the direction the wind is blowing FROM.

    Returns None when the wind sensor has no usable value.
    """
    wind = state_as_float(hass, wind_entity)
    if wind is None:
        return None
    # Smallest angle between the fire's bearing and the wind direction, in 0-180°.
    return [f for f in coordinator.data["smoke_pool"] if abs((f["bearing"] - wind + 180) % 360 - 180) <= UPWIND_SPREAD]


class FireNearby(CwfisEntity, BinarySensorEntity):
    """On when an agency-reported active fire is inside a zone's alert radius.

    Deliberately has no device class: it's a plain On/Off, not a "Safe/Unsafe" safety state.
    """

    def __init__(self, entry, zone):
        """Remember the alert radius so it can be shown as an attribute."""
        super().__init__(entry, "fire_nearby", "Fire within alert radius", "mdi:map-marker-radius", zone)
        self._radius = entry.options.get(CONF_RADIUS, DEFAULT_RADIUS)

    @property
    def is_on(self):
        """On while at least one active fire is inside the alert radius."""
        return bool(self.zone_data["nearby"])

    @property
    def extra_state_attributes(self):
        """Why it's on: radius, how many fires are inside it, and the nearest one."""
        nearby = self.zone_data["nearby"]
        return {
            "alert_radius_km": self._radius,
            "fires_in_radius": len(nearby),
            "nearest_fire": nearby[0]["national_fire_id"] if nearby else None,
            "nearest_distance_km": nearby[0]["distance"] if nearby else None,
        }


class WatchingEntity(CwfisEntity, BinarySensorEntity):
    """Base for binary sensors that also depend on other HA sensors (wind, PM2.5).

    They re-evaluate whenever a watched sensor changes, not only every 30 minutes.
    """

    _watch: list[str]

    async def async_added_to_hass(self):
        """Start listening to the watched sensors once the entity exists."""
        await super().async_added_to_hass()
        self.async_on_remove(async_track_state_change_event(self.hass, self._watch, self._watched_changed))

    @callback
    def _watched_changed(self, _event):
        """Re-evaluate as soon as a watched sensor changes, instead of waiting for the next 30-minute update."""
        self.async_write_ha_state()


class FireUpwind(WatchingEntity):
    """On when a fire within the smoke radius is upwind of Home (smoke likely drifting your way)."""

    _attr_device_class = BinarySensorDeviceClass.SMOKE

    def __init__(self, entry, wind):
        """Watch the wind sensor so the state updates as soon as the wind changes."""
        super().__init__(entry, "fire_upwind", "Fire upwind", "mdi:weather-windy")
        self._wind = wind
        self._watch = [wind]

    @property
    def is_on(self):
        """True if any fire in the smoke radius is upwind."""
        fires = upwind_fires(self.hass, self.coordinator, self._wind)
        return None if fires is None else bool(fires)  # None -> "unknown" while wind is unavailable

    @property
    def extra_state_attributes(self):
        """The upwind fires (nearest first)."""
        fires = upwind_fires(self.hass, self.coordinator, self._wind) or []
        return {"fires": [fire_info(f) for f in fires[:MAX_LISTED_FIRES]]}


class WildfireSmoke(WatchingEntity):
    """On when measured PM2.5 is high AND a likely fire source exists.

    The source is an upwind fire if a wind sensor is configured, otherwise any fire in the smoke radius.
    """

    _attr_device_class = BinarySensorDeviceClass.SMOKE

    def __init__(self, entry, pm25, wind, threshold):
        """Watch the PM2.5 sensor (and wind sensor, if any)."""
        super().__init__(entry, "wildfire_smoke", "Wildfire smoke", "mdi:smoke")
        self._pm25, self._wind, self._threshold = pm25, wind, threshold
        self._watch = [e for e in (pm25, wind) if e]

    def _sources(self):
        """Fires that could be causing the smoke (None while the wind is unknown)."""
        if self._wind:
            return upwind_fires(self.hass, self.coordinator, self._wind)
        return self.coordinator.data["smoke_pool"]

    @property
    def is_on(self):
        """True when PM2.5 is at/above the threshold and a likely source exists."""
        pm25, sources = state_as_float(self.hass, self._pm25), self._sources()
        if pm25 is None or sources is None:
            return None  # "unknown" while a source sensor is unavailable
        return pm25 >= self._threshold and bool(sources)

    @property
    def extra_state_attributes(self):
        """The PM2.5 reading and threshold, and the nearest fires that could be causing the smoke."""
        return {
            "pm25": state_as_float(self.hass, self._pm25),
            "threshold": self._threshold,
            "likely_sources": [fire_info(f) for f in (self._sources() or [])[:5]],
        }
