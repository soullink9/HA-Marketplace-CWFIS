"""Stand-ins for Home Assistant and aiohttp, so the CWFIS integration runs with plain Python.

Importing this module registers them under the real names. The clock is CLOCK["now"] (a UTC datetime the test moves
forward), with "local" time a fixed UTC-5 to keep the maths simple; EVENTS collects every event the Fire alert entity
fires. Home Assistant's client session is whatever SESSION["factory"]() returns: the test points it at its fake servers.
"""

from datetime import timedelta, timezone
import enum
import math
import sys
import types


def stub(name, **attrs):
    """Register a fake module under `name` so the integration's imports resolve to it."""
    module = types.ModuleType(name)
    module.__dict__.update(attrs)
    sys.modules[name] = module
    return module


class Generic:
    """Lets stand-in classes be subscripted like the real ones, e.g. DataUpdateCoordinator[dict]."""

    def __class_getitem__(cls, _item):
        return cls


# ---------------------------------------------------------------------------
# Stand-ins for Home Assistant and aiohttp
# ---------------------------------------------------------------------------
class ClientError(Exception):
    pass


stub("aiohttp", ClientError=ClientError, ClientTimeout=lambda total: None)
stub("voluptuous")
for pkg in ("homeassistant", "homeassistant.helpers", "homeassistant.util", "homeassistant.components"):
    stub(pkg)
stub("homeassistant.config_entries", ConfigEntry=Generic)
stub(
    "homeassistant.const",
    Platform=enum.Enum("Platform", "BINARY_SENSOR EVENT GEO_LOCATION IMAGE SENSOR"),
    UnitOfLength=types.SimpleNamespace(KILOMETERS="km"),
    PERCENTAGE="%",
    UnitOfDensity=types.SimpleNamespace(MICROGRAMS_PER_CUBIC_METER="µg/m³"),
)
stub("homeassistant.core", HomeAssistant=object, callback=lambda f: f)
stub("homeassistant.helpers.device_registry", DeviceInfo=dict, DeviceEntryType=types.SimpleNamespace(SERVICE="service"))


class UpdateFailed(Exception):
    pass


class DataUpdateCoordinator(Generic):
    """Minimal coordinator: refresh() runs the update and notifies listeners, like the real one."""

    def __init__(self, hass, logger, *, config_entry, name, update_interval):
        self.hass, self.listeners, self.last_update_success = hass, [], True

    async def async_config_entry_first_refresh(self):
        self.data = await self._async_update_data()

    async def refresh(self):
        self.data = await self._async_update_data()
        for listener in list(self.listeners):
            listener()

    def async_add_listener(self, listener):
        self.listeners.append(listener)
        return lambda: None


class CoordinatorEntity(Generic):
    def __init__(self, coordinator):
        self.coordinator = coordinator
        coordinator.listeners.append(self._handle_coordinator_update)

    @property
    def available(self):
        return self.coordinator.last_update_success

    def _handle_coordinator_update(self):
        self.async_write_ha_state()

    def async_write_ha_state(self):
        pass

    async def async_remove(self, force_remove=False):
        pass


stub(
    "homeassistant.helpers.update_coordinator",
    DataUpdateCoordinator=DataUpdateCoordinator,
    CoordinatorEntity=CoordinatorEntity,
    UpdateFailed=UpdateFailed,
)
# The test sets SESSION["factory"] to its fake servers' session class.
SESSION = {"factory": None}
stub("homeassistant.helpers.aiohttp_client", async_get_clientsession=lambda hass: SESSION["factory"]())
stub("homeassistant.helpers.event", async_track_state_change_event=lambda *args: None)

# Controllable clock. "Local" time is a fixed UTC-5 to keep the maths simple.
CLOCK = {"now": None}
LOCAL = timezone(timedelta(hours=-5))
stub(
    "homeassistant.util.dt",
    now=lambda: CLOCK["now"].astimezone(LOCAL),
    utcnow=lambda: CLOCK["now"],
    start_of_local_day=lambda: CLOCK["now"].astimezone(LOCAL).replace(hour=0, minute=0, second=0, microsecond=0),
    as_utc=lambda d: d.astimezone(timezone.utc),
    as_local=lambda d: d.astimezone(LOCAL),
)
sys.modules["homeassistant.util"].dt = sys.modules["homeassistant.util.dt"]


def haversine_m(lat1, lon1, lat2, lon2):
    p1, p2 = math.radians(lat1), math.radians(lat2)
    h = math.sin((p2 - p1) / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(math.radians(lon2 - lon1) / 2) ** 2
    return 2 * 6371000 * math.asin(math.sqrt(h))


stub("homeassistant.util.location", distance=haversine_m)
stub(
    "homeassistant.components.sensor",
    SensorEntity=object,
    SensorDeviceClass=types.SimpleNamespace(DISTANCE="distance", PM25="pm25"),
    SensorStateClass=types.SimpleNamespace(MEASUREMENT="measurement"),
)
stub(
    "homeassistant.components.binary_sensor",
    BinarySensorEntity=object,
    BinarySensorDeviceClass=types.SimpleNamespace(SMOKE="smoke"),
)

EVENTS = []  # every (event_type, fire id) the Fire alert entity fires


class EventEntity:
    def _trigger_event(self, event_type, attributes):
        EVENTS.append((event_type, attributes["fire"]))


stub("homeassistant.components.event", EventEntity=EventEntity)
stub("homeassistant.components.geo_location", GeolocationEvent=object)


class ImageEntity:
    def __init__(self, hass, verify_ssl=False):
        self.hass = hass


stub("homeassistant.components.image", ImageEntity=ImageEntity)
