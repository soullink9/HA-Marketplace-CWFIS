"""Canadian Wildland Fire Information System (CWFIS) integration for Home Assistant.

File layout:
  const.py          URLs, layer names, option keys, defaults, lookup tables
  helpers.py        small pure functions (distance, bearing, data clean-up)
  coordinator.py    fetches all data once per update and does the calculations
  entity.py         base entity: shared device, naming and availability
  sensor.py / binary_sensor.py / event.py / geo_location.py / image.py   the entity platforms
  config_flow.py    one-click setup and the Configure (options) form
"""

from __future__ import annotations

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import Platform
from homeassistant.core import HomeAssistant

from .coordinator import CwfisCoordinator

PLATFORMS = [Platform.BINARY_SENSOR, Platform.EVENT, Platform.GEO_LOCATION, Platform.IMAGE, Platform.SENSOR]

type CwfisConfigEntry = ConfigEntry[CwfisCoordinator]


async def async_setup_entry(hass: HomeAssistant, entry: CwfisConfigEntry) -> bool:
    """Fetch the first batch of data, then create all entities."""
    coordinator = CwfisCoordinator(hass, entry)
    await coordinator.async_config_entry_first_refresh()  # raises ConfigEntryNotReady -> HA retries later
    entry.runtime_data = coordinator
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    return True


async def async_unload_entry(hass: HomeAssistant, entry: CwfisConfigEntry) -> bool:
    """Remove all entities (also called before a reload when options change)."""
    return await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
