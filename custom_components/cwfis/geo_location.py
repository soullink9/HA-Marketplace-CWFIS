"""Map markers: one geo_location entity per active fire (shown by the built-in Map card).

Markers are created and removed as fires start and go out. They are not stored in the entity
registry (Home Assistant's design for geo_location), so they never leave orphaned entities behind.
"""

from __future__ import annotations

from homeassistant.components.geo_location import GeolocationEvent
from homeassistant.const import UnitOfLength
from homeassistant.core import callback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import CONF_MAP_FIRES, DEFAULT_MAP_FIRES, DOMAIN
from .coordinator import CwfisCoordinator
from .helpers import fire_info


def marker_name(fire_id: str) -> str:
    """'2026_BC_2026_K71668' -> 'CWFIS BC K71668', which gives entity_id geo_location.cwfis_bc_k71668."""
    year, _, rest = fire_id.partition("_")
    return "CWFIS " + (rest.replace(f"_{year}_", "_") if rest else year).replace("_", " ")


async def async_setup_entry(hass, entry, async_add_entities):
    """Keep the set of marker entities in sync with the fires after every update."""
    coordinator: CwfisCoordinator = entry.runtime_data
    mode = entry.options.get(CONF_MAP_FIRES, DEFAULT_MAP_FIRES)  # "all", "nearby" or "none"
    markers: dict[str, FireMarker] = {}

    @callback
    def sync():
        """Add markers for new fires and remove markers for fires that are gone."""
        data = coordinator.data
        if mode == "none":
            wanted = {}
        elif mode == "all":
            wanted = data["fires"]
        else:  # "nearby": fires inside any zone's alert radius
            # The marker shows the fire as measured from Home (data["fires"]), even when it's near another zone.
            wanted = {}
            for zone in data["zones"].values():
                for fire in zone["nearby"]:
                    fire_id = fire["national_fire_id"]
                    wanted[fire_id] = data["fires"][fire_id]

        for fire_id in markers.keys() - wanted.keys():
            hass.async_create_task(markers.pop(fire_id).async_remove(force_remove=True))
        new = [FireMarker(coordinator, fire_id) for fire_id in wanted.keys() - markers.keys()]
        markers.update((marker.fire_id, marker) for marker in new)
        async_add_entities(new)

    sync()
    entry.async_on_unload(coordinator.async_add_listener(sync))


class FireMarker(CoordinatorEntity[CwfisCoordinator], GeolocationEvent):
    """One active fire. Distance is measured from Home."""

    _attr_source = DOMAIN  # lets a Map card show only these markers: geo_location_sources: [cwfis]
    _attr_icon = "mdi:fire"
    _attr_unit_of_measurement = UnitOfLength.KILOMETERS

    def __init__(self, coordinator: CwfisCoordinator, fire_id: str):
        """Keep a copy of this fire's data; it's refreshed on every update."""
        super().__init__(coordinator)
        self.fire_id = fire_id
        self._attr_name = marker_name(fire_id)
        self._fire = coordinator.data["fires"][fire_id]

    @callback
    def _handle_coordinator_update(self):
        """Pick up this fire's latest data."""
        # If the fire is gone, sync() above removes this marker; until then keep the last data.
        if fire := self.coordinator.data["fires"].get(self.fire_id):
            self._fire = fire
            super()._handle_coordinator_update()

    @property
    def latitude(self):
        """The fire's latitude."""
        return self._fire["latitude"]

    @property
    def longitude(self):
        """The fire's longitude."""
        return self._fire["longitude"]

    @property
    def distance(self):
        """Distance from Home in km (the marker's state)."""
        return self._fire["distance"]

    @property
    def extra_state_attributes(self):
        """The fire's details, without the distance: it's already the entity's state."""
        return {k: v for k, v in fire_info(self._fire).items() if k != "distance_km"}
