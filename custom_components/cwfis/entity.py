"""Base entity shared by every CWFIS sensor, binary sensor, event and image."""

from __future__ import annotations

from homeassistant.helpers.device_registry import DeviceEntryType, DeviceInfo
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import DOMAIN, PROVINCES
from .coordinator import CwfisCoordinator


class CwfisEntity(CoordinatorEntity[CwfisCoordinator]):
    """Groups all entities under one "CWFIS" service device and handles naming.

    Naming rules (kept stable so entity IDs never change between versions):
      * national and Home entities: plain name, e.g. "Active fires nearby"
      * extra watch zones:          "Active fires nearby (Cottage)"
      * provinces:                  "Active fires (Quebec)"
    """

    _attr_has_entity_name = True

    def __init__(self, entry, key: str, name: str, icon: str, zone: str = "home", province: str | None = None):
        """Work out the name, unique ID and device for this entity."""
        super().__init__(entry.runtime_data)
        self._key, self._zone, self._province, self._attr_icon = key, zone, province, icon

        if province:
            label, uid = PROVINCES.get(province, province), f"{province.lower()}_{key}"
        elif zone != "home":
            label, uid = entry.runtime_data.data["zones"][zone]["name"], f"{zone}_{key}"
        else:
            label, uid = None, key
        self._attr_name = f"{name} ({label})" if label else name
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
