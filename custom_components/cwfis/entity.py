"""Base entity shared by every CWFIS sensor, binary sensor, event and image."""

from homeassistant.core import callback
from homeassistant.helpers.device_registry import DeviceEntryType, DeviceInfo
from homeassistant.helpers.event import async_track_state_change_event
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import DOMAIN, PROVINCES
from .coordinator import CwfisConfigEntry, CwfisCoordinator


class CwfisEntity(CoordinatorEntity[CwfisCoordinator]):
    """Groups all entities under one "CWFIS" service device and handles naming.

    Names and icons come from translations/en.json and icons.json, by translation key. The key is the entity's
    `key`, with a suffix for the entities that belong to a watch zone or a province, whose name has a placeholder:
      * national and Home entities: key "nearby"          -> "Active fires nearby"
      * extra watch zones:          key "nearby_zone"     -> "Active fires nearby (Cottage)"
      * provinces:                  key "active_province" -> "Active fires (Quebec)"
    The English names are the ones earlier versions hard-coded, so new installs get the same entity IDs.
    """

    _attr_has_entity_name = True

    def __init__(self, entry: CwfisConfigEntry, key: str, zone: str = "home", province: str | None = None) -> None:
        """Work out the translation key, unique ID and device for this entity."""
        super().__init__(entry.runtime_data)
        self._key, self._zone, self._province = key, zone, province

        if province:
            uid = f"{province.lower()}_{key}"
            self._attr_translation_key = f"{key}_province"
            self._attr_translation_placeholders = {"province": PROVINCES.get(province, province)}
        elif zone != "home":
            uid = f"{zone}_{key}"
            self._attr_translation_key = f"{key}_zone"
            self._attr_translation_placeholders = {"zone": entry.runtime_data.data["zones"][zone]["name"]}
        else:
            uid = key
            self._attr_translation_key = key
        self._attr_unique_id = f"{entry.entry_id}_{uid}"

        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, entry.entry_id)},
            name="CWFIS",
            manufacturer="Natural Resources Canada",
            entry_type=DeviceEntryType.SERVICE,
            configuration_url="https://cwfis.cfs.nrcan.gc.ca/en/",
        )

    @property
    def zone_data(self) -> dict | None:
        """This entity's zone results, or None if the zone has since been deleted."""
        return self.coordinator.data["zones"].get(self._zone)

    @property
    def available(self) -> bool:
        """Unavailable when the last update failed or this entity's zone no longer exists."""
        return super().available and self.zone_data is not None


class WatchingEntity(CwfisEntity):
    """Base for entities that also depend on other HA sensors (wind, PM2.5).

    They re-evaluate whenever a watched sensor changes, not only every 30 minutes. Subclasses set `_watch`.
    """

    _watch: list[str] = []

    async def async_added_to_hass(self) -> None:
        """Start listening to the watched sensors once the entity exists."""
        await super().async_added_to_hass()
        if self._watch:
            self.async_on_remove(async_track_state_change_event(self.hass, self._watch, self._watched_changed))

    @callback
    def _watched_changed(self, _event) -> None:
        """Re-evaluate as soon as a watched sensor changes, instead of waiting for the next 30-minute update."""
        self.async_write_ha_state()
