"""Sensors: national summary, season comparison, smoke forecast, provinces and per-zone proximity."""

from __future__ import annotations

from homeassistant.components.sensor import SensorDeviceClass, SensorEntity, SensorStateClass
from homeassistant.const import PERCENTAGE, UnitOfDensity, UnitOfLength

from .const import CONF_PROVINCES, MAX_LISTED_FIRES
from .entity import CwfisEntity
from .helpers import fire_info

MEASUREMENT = SensorStateClass.MEASUREMENT
KM, DISTANCE = UnitOfLength.KILOMETERS, SensorDeviceClass.DISTANCE

# Sensor tables: key -> (name, unit, icon, device class, state class).
# National sensors read coordinator.data[key]; attributes come from coordinator.data[f"{key}_attrs"].
NATIONAL = {
    "reported_today": ("Reported today", "fires", "mdi:fire-alert", None, MEASUREMENT),
    "active": ("Active fires", "fires", "mdi:fire", None, MEASUREMENT),
    "out": ("Out fires", "fires", "mdi:fire-off", None, MEASUREMENT),
    "total": ("Total fires", "fires", "mdi:counter", None, MEASUREMENT),
    "area": ("Area burned", "ha", "mdi:texture-box", None, MEASUREMENT),
    "fires_vs_last_year": ("Fires vs last year", PERCENTAGE, "mdi:chart-line", None, MEASUREMENT),
    "area_vs_last_year": ("Area burned vs last year", PERCENTAGE, "mdi:chart-areaspline", None, MEASUREMENT),
    "smoke_forecast": (
        "Smoke forecast PM2.5 (24h max)",
        UnitOfDensity.MICROGRAMS_PER_CUBIC_METER,
        "mdi:weather-hazy",
        SensorDeviceClass.PM25,
        MEASUREMENT,
    ),
}
# One pair per province picked under Configure -> Province sensors.
PROVINCE = {
    "active": ("Active fires", "fires", "mdi:fire", None, MEASUREMENT),
    "area": ("Area burned", "ha", "mdi:texture-box", None, MEASUREMENT),
}
# One set for Home and for every extra watch zone.
PER_ZONE = {
    "nearest": ("Nearest active fire", KM, "mdi:map-marker-distance", DISTANCE, MEASUREMENT),
    "nearby": ("Active fires nearby", "fires", "mdi:fire-circle", None, MEASUREMENT),
    "perimeter": ("Nearest fire perimeter", KM, "mdi:vector-polygon", DISTANCE, MEASUREMENT),
    "hotspots": ("Hotspots nearby (24h)", "hotspots", "mdi:satellite-variant", None, MEASUREMENT),
    "prescribed": ("Prescribed burns nearby", "burns", "mdi:fire-truck", None, MEASUREMENT),
    "danger": ("Fire danger", None, "mdi:gauge", None, None),  # text state: Low ... Extreme
}


async def async_setup_entry(hass, entry, async_add_entities):
    """Create national, province and per-zone sensors."""
    entities: list[CwfisSensor] = [NationalSensor(entry, key) for key in NATIONAL]
    for code in entry.options.get(CONF_PROVINCES, []):
        entities += [ProvinceSensor(entry, key, code) for key in PROVINCE]
    for zone in entry.runtime_data.data["zones"]:
        entities += [ZoneSensor(entry, key, zone) for key in PER_ZONE]
    async_add_entities(entities)


class CwfisSensor(CwfisEntity, SensorEntity):
    """Common setup: unpack one row of the tables above."""

    def __init__(self, entry, key, spec, **where):
        """Apply the name, unit, icon, device class and state class from the table row."""
        name, unit, icon, self._attr_device_class, self._attr_state_class = spec
        super().__init__(entry, key, name, icon, **where)
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
