"""Sensors: national summary, season comparison, smoke forecast, provinces, per-zone proximity and local impact."""

from homeassistant.components.sensor import SensorDeviceClass, SensorEntity, SensorStateClass
from homeassistant.const import PERCENTAGE, UnitOfDensity, UnitOfLength
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from .const import (
    CA_AQHI,
    CONF_AQ_SCALE,
    CONF_DANGER_DISTANCE,
    CONF_PM25,
    CONF_PROVINCES,
    CONF_WARNING_DISTANCE,
    DEFAULT_AQ_SCALE,
    DEFAULT_DANGER_DISTANCE,
    DEFAULT_WARNING_DISTANCE,
    FIRE_THREAT,
    MAX_LISTED_FIRES,
    US_AQI,
)
from .coordinator import CwfisConfigEntry
from .entity import CwfisEntity, WatchingEntity
from .helpers import air_quality, fire_info, fire_threat, state_as_float

# Every entity reads the coordinator's data, so Home Assistant needn't limit how many update at once.
PARALLEL_UPDATES = 0

MEASUREMENT = SensorStateClass.MEASUREMENT
KM, DISTANCE = UnitOfLength.KILOMETERS, SensorDeviceClass.DISTANCE

# Sensor tables: key -> (unit, device class, state class). Names and icons are in translations/en.json and
# icons.json under the same key (with "_province" or "_zone" added for those sensors).
# National sensors read coordinator.data[key]; attributes come from coordinator.data[f"{key}_attrs"].
NATIONAL = {
    "reported_today": ("fires", None, MEASUREMENT),
    "active": ("fires", None, MEASUREMENT),
    "out": ("fires", None, MEASUREMENT),
    "total": ("fires", None, MEASUREMENT),
    "area": ("ha", None, MEASUREMENT),
    "fires_vs_last_year": (PERCENTAGE, None, MEASUREMENT),
    "area_vs_last_year": (PERCENTAGE, None, MEASUREMENT),
    "smoke_forecast": (UnitOfDensity.MICROGRAMS_PER_CUBIC_METER, SensorDeviceClass.PM25, MEASUREMENT),
}
# One pair per province picked under Configure -> Province sensors.
PROVINCE = {
    "active": ("fires", None, MEASUREMENT),
    "area": ("ha", None, MEASUREMENT),
}
# One set for Home and for every extra watch zone.
PER_ZONE = {
    "nearest": (KM, DISTANCE, MEASUREMENT),
    "nearby": ("fires", None, MEASUREMENT),
    "perimeter": (KM, DISTANCE, MEASUREMENT),
    "hotspots": ("hotspots", None, MEASUREMENT),
    "prescribed": ("burns", None, MEASUREMENT),
    "danger": (None, None, None),  # text state: Low ... Extreme
}


async def async_setup_entry(
    hass: HomeAssistant, entry: CwfisConfigEntry, async_add_entities: AddConfigEntryEntitiesCallback
) -> None:
    """Create national, province and per-zone sensors, and each zone's Smoke impact and Fire threat."""
    entities: list[SensorEntity] = [NationalSensor(entry, key) for key in NATIONAL]
    for code in entry.options.get(CONF_PROVINCES, []):
        entities += [ProvinceSensor(entry, key, code) for key in PROVINCE]
    scale = entry.options.get(CONF_AQ_SCALE, DEFAULT_AQ_SCALE)
    if scale == "auto":  # Canada's AQHI for a Home in Canada, the US AQI anywhere else
        scale = "ca_aqhi" if hass.config.country == "CA" else "us_aqi"
    for zone in entry.runtime_data.data["zones"]:
        entities += [ZoneSensor(entry, key, zone) for key in PER_ZONE]
        entities += [SmokeImpact(entry, zone, scale), FireThreat(entry, zone)]
    async_add_entities(entities)


class CwfisSensor(CwfisEntity, SensorEntity):
    """Common setup: unpack one row of the tables above."""

    def __init__(self, entry, key, spec, **where):
        """Apply the unit, device class and state class from the table row."""
        unit, self._attr_device_class, self._attr_state_class = spec
        super().__init__(entry, key, **where)
        self._attr_native_unit_of_measurement = unit


class NationalSensor(CwfisSensor):
    """Canada-wide numbers (not tied to a zone)."""

    def __init__(self, entry, key):
        """Create the national sensor for `key`, from its row in NATIONAL."""
        super().__init__(entry, key, NATIONAL[key])

    @property
    def available(self):
        """Available whenever the last update worked (a national number isn't tied to a zone)."""
        return self.coordinator.last_update_success  # no zone involved

    @property
    def native_value(self):
        """The national number, as calculated by the coordinator."""
        return self.coordinator.data[self._key]

    @property
    def extra_state_attributes(self):
        """Its details from the coordinator (the "<key>_attrs" entry), if it has any."""
        return self.coordinator.data.get(f"{self._key}_attrs")


class ProvinceSensor(CwfisSensor):
    """Active fires or area burned for one reporting agency."""

    def __init__(self, entry, key, code):
        """Create the sensor for `key` (from PROVINCE) for one reporting agency's code."""
        super().__init__(entry, key, PROVINCE[key], province=code)

    @property
    def available(self):
        """Available whenever the last update worked (a province number isn't tied to a zone)."""
        return self.coordinator.last_update_success  # no zone involved

    @property
    def native_value(self):
        """This agency's number. An agency with no fires this season isn't in the data at all, so that's 0."""
        return self.coordinator.data["provinces"].get(self._province, {}).get(self._key, 0)


class ZoneSensor(CwfisSensor):
    """Proximity numbers for Home or one extra watch zone."""

    def __init__(self, entry, key, zone):
        """Create the sensor for `key` (from PER_ZONE) for Home or one watch zone."""
        super().__init__(entry, key, PER_ZONE[key], zone=zone)

    @property
    def native_value(self):
        """Distance, count or rating for this zone."""
        value = self.zone_data[self._key]
        if self._key == "nearest":
            return value and value["distance"]  # None when there are no fires at all
        return len(value) if self._key == "nearby" else value

    @property
    def extra_state_attributes(self):
        """Details of the nearest fire, or the list of fires inside the radius."""
        if self._key == "nearest" and self.zone_data["nearest"]:
            return fire_info(self.zone_data["nearest"])
        if self._key == "nearby":
            return {"fires": [fire_info(f) for f in self.zone_data["nearby"][:MAX_LISTED_FIRES]]}
        return None


class SmokeImpact(WatchingEntity, SensorEntity):
    """How smoky the air is or will be at a zone, as a US AQI or Canadian AQHI level with advice.

    The state is the worse of "now" and the forecast peak over the next 24 hours, so it gives warning before smoke
    arrives. "Now" is your own PM2.5 sensor for Home when one is set, otherwise the forecast for the current hour.
    """

    _attr_device_class = SensorDeviceClass.ENUM

    def __init__(self, entry, zone, scale):
        """Use the given scale's levels; watch the PM2.5 sensor for Home so the level follows it straight away."""
        super().__init__(entry, "smoke_impact", zone)
        self._scale = scale
        self._attr_options = [level[0] for level in (CA_AQHI if scale == "ca_aqhi" else US_AQI)]
        self._pm25 = entry.options.get(CONF_PM25) if zone == "home" else None
        self._watch = [self._pm25] if self._pm25 else []

    def _assess(self) -> dict | None:
        """The level details for now and the next 24 hours, or None when there's nothing to go on."""
        forecast = self.zone_data["smoke"] or {}
        measured = state_as_float(self.hass, self._pm25) if self._pm25 else None
        now = measured if measured is not None else forecast.get("now")
        readings = [pm for pm in (now, forecast.get("max_24h")) if pm is not None]
        if not readings:
            return None
        worst = air_quality(max(readings), self._scale)
        return {
            **worst,
            "now": air_quality(now, self._scale) if now is not None else None,
            "pm25_now": now,
            "pm25_now_source": "sensor" if measured is not None else "forecast",
            "pm25_max_24h": forecast.get("max_24h"),
            "peak_time_24h": forecast.get("peak_time_24h"),
        }

    @property
    def native_value(self):
        """The worse level of now and the next 24 hours."""
        assessment = self._assess()
        return assessment and assessment["level"]

    @property
    def extra_state_attributes(self):
        """The index, what to do, and the PM2.5 readings behind it."""
        a = self._assess()
        if a is None:
            return {"scale": self._scale}
        return {
            "scale": self._scale,
            "index": a["index"],
            "severity": a["severity"],
            "advice": a["advice"],
            "level_now": a["now"] and a["now"]["level"],
            "pm25_now": a["pm25_now"],
            "pm25_now_source": a["pm25_now_source"],
            "pm25_max_24h": a["pm25_max_24h"],
            "peak_time_24h": a["peak_time_24h"],
        }


class FireThreat(CwfisEntity, SensorEntity):
    """How directly fire threatens a zone: none, watch, warning or danger, with the reason and advice."""

    _attr_device_class = SensorDeviceClass.ENUM
    _attr_options = list(FIRE_THREAT)

    def __init__(self, entry, zone):
        """Read the danger and warning distances from the options."""
        super().__init__(entry, "fire_threat", zone)
        self._danger_km = entry.options.get(CONF_DANGER_DISTANCE, DEFAULT_DANGER_DISTANCE)
        self._warning_km = entry.options.get(CONF_WARNING_DISTANCE, DEFAULT_WARNING_DISTANCE)

    @property
    def native_value(self):
        """The threat level."""
        return fire_threat(self.zone_data, self._danger_km, self._warning_km)[0]

    @property
    def extra_state_attributes(self):
        """Why, what to do, and the nearest fire."""
        level, reason = fire_threat(self.zone_data, self._danger_km, self._warning_km)
        nearest = self.zone_data["nearest"]
        return {
            "severity": list(FIRE_THREAT).index(level),
            "reason": reason,
            "advice": FIRE_THREAT[level],
            "danger_distance_km": self._danger_km,
            "warning_distance_km": self._warning_km,
            "nearest_fire": fire_info(nearest) if nearest else None,
            "nearest_perimeter_km": self.zone_data["perimeter"],
            "nearest_hotspot_km": self.zone_data["hotspot_distance"],
            "fire_danger": self.zone_data["danger"],
        }
