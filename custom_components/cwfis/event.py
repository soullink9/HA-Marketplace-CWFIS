"""Fire alert event entity.

Fires an event when, for any fire inside any zone's alert radius:
  * new_fire_nearby - a fire appears inside the radius
  * stage_changed   - its stage of control changes (e.g. Being held -> Out of control)
  * fire_grew       - it grows by GROWTH_FACTOR and at least GROWTH_MIN_HA since the last alert
  * fire_out        - it disappears from the active list (declared out)

The entity's state is the time of the last event; use it as an automation trigger.

What it last saw is saved (Home Assistant's .storage/, one file per config entry), so after a restart it carries on
from there: changes made while Home Assistant was stopped are reported, and slow growth keeps adding up. A saved
baseline older than ALERT_BASELINE_MAX_AGE, or one that can't be read, is dropped and it starts afresh.
"""

from datetime import datetime, timedelta
import logging

from homeassistant.components.event import EventEntity
from homeassistant.core import HomeAssistant, callback
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback
from homeassistant.helpers.storage import Store
from homeassistant.util import dt as dt_util

from .const import (
    ALERT_BASELINE_MAX_AGE,
    ALERT_STORAGE_KEY,
    ALERT_STORAGE_VERSION,
    GROWTH_FACTOR,
    GROWTH_MIN_HA,
    STAGES,
)
from .coordinator import CwfisConfigEntry
from .entity import CwfisEntity
from .helpers import clean_fire, fire_info, number, text

_LOGGER = logging.getLogger(__name__)

# How long to wait before saving after a change; Home Assistant also saves on shutdown.
SAVE_DELAY = 10  # seconds
MAX_SAVED_FIRES = 10_000  # entries read back from a saved baseline

# Every entity reads the coordinator's data, so Home Assistant needn't limit how many update at once.
PARALLEL_UPDATES = 0


async def async_setup_entry(
    hass: HomeAssistant, entry: CwfisConfigEntry, async_add_entities: AddConfigEntryEntitiesCallback
) -> None:
    """A single Fire alert entity covers every zone."""
    async_add_entities([FireAlert(entry)])


type Baseline = dict[tuple[str, str], tuple[str, dict]]


def dump_baseline(seen: Baseline, now: datetime) -> dict:
    """The baseline as JSON-friendly data for the store."""
    return {
        "saved": now.isoformat(),
        "fires": [{"zone_id": zone_id, "zone": zone, "fire": fire} for (zone_id, _), (zone, fire) in seen.items()],
    }


def load_baseline(data, now: datetime) -> Baseline | None:
    """The baseline read back from the store, or None when there's none, it's too old, or it isn't valid.

    The file is checked as carefully as server data: entries that don't hold up are skipped one by one.
    """
    if not isinstance(data, dict) or not isinstance(data.get("fires"), list) or not isinstance(data.get("saved"), str):
        return None
    try:
        saved = datetime.fromisoformat(data["saved"])
    except ValueError:
        return None
    if saved.tzinfo is None or not timedelta(minutes=-5) <= now - saved <= ALERT_BASELINE_MAX_AGE:
        return None

    seen: Baseline = {}
    for item in data["fires"][:MAX_SAVED_FIRES]:
        if not isinstance(item, dict) or not isinstance(item.get("fire"), dict):
            continue
        fire, raw = clean_fire(item["fire"]), item["fire"]
        zone_id, zone = text(item.get("zone_id")), text(item.get("zone"))
        distance, direction = number(raw.get("distance"), 0, 20_100), number(raw.get("bearing"), 0, 359)
        if not zone_id or not fire["national_fire_id"] or distance is None or direction is None:
            continue
        fire.update(distance=distance, bearing=round(direction))
        seen[(zone_id, fire["national_fire_id"])] = (zone or zone_id, fire)
    return seen


class FireAlert(CwfisEntity, EventEntity):
    """Compares each update with the previous one and fires the matching events."""

    _attr_event_types = ["new_fire_nearby", "stage_changed", "fire_grew", "fire_out"]

    def __init__(self, entry):
        """Take a first snapshot of nearby fires to compare future updates against."""
        super().__init__(entry, "fire_alert")
        self._entry_id = entry.entry_id
        self._store: Store | None = None
        # Start from what's already nearby so a first start doesn't announce every fire as "new". A saved baseline,
        # if there's a usable one, replaces it in async_added_to_hass.
        self._seen = self._snapshot()

    async def async_added_to_hass(self) -> None:
        """Pick up the saved baseline, report what changed since it was saved, and save the current one."""
        await super().async_added_to_hass()
        self._store = Store(self.hass, ALERT_STORAGE_VERSION, ALERT_STORAGE_KEY.format(entry_id=self._entry_id))
        try:
            saved = load_baseline(await self._store.async_load(), dt_util.utcnow())
        except (HomeAssistantError, NotImplementedError, ValueError) as err:
            _LOGGER.warning("Couldn't read the saved fire alert baseline, starting afresh: %s", err)
            saved = None
        if saved is not None:
            self._seen = saved
            self._compare()
        self._save()

    def _save(self) -> None:
        """Save the baseline a little later (Home Assistant also writes it on shutdown)."""
        if self._store is not None:
            self._store.async_delay_save(lambda: dump_baseline(self._seen, dt_util.utcnow()), SAVE_DELAY)

    def _snapshot(self) -> dict:
        """(zone id, fire id) -> (zone name, fire) for every fire inside any zone's alert radius."""
        snapshot = {}
        for zone_id, zone in self.coordinator.data["zones"].items():
            for fire in zone["nearby"]:
                snapshot[(zone_id, fire["national_fire_id"])] = (zone["name"], fire)
        return snapshot

    def _alert(self, event_type: str, zone: str, fire: dict, **extra):
        """Fire one event with the fire's details and the zone it's near."""
        self._trigger_event(event_type, {"zone": zone, **fire_info(fire), **extra})
        self.async_write_ha_state()

    @callback
    def _handle_coordinator_update(self):
        """Compare this update with the previous one, fire the matching events, and save the new baseline."""
        self._compare()
        self._save()
        super()._handle_coordinator_update()

    def _compare(self) -> None:
        """Fire an event for each change since the baseline, then make the current fires the baseline."""
        now = self._snapshot()
        for key, (zone, fire) in now.items():
            if key not in self._seen:
                self._alert("new_fire_nearby", zone, fire)
                continue

            old = self._seen[key][1]
            old_stage = old.get("stage_of_control_status")
            if fire.get("stage_of_control_status") != old_stage:
                self._alert("stage_changed", zone, fire, previous_stage=STAGES.get(old_stage, old_stage))

            size, old_size = fire.get("fire_size") or 0, old.get("fire_size") or 0
            if size >= max(old_size * GROWTH_FACTOR, old_size + GROWTH_MIN_HA):
                self._alert("fire_grew", zone, fire, previous_size_ha=old_size)
            else:
                # Keep the size from the last alert as the baseline, so slow steady growth
                # still adds up to an alert eventually.
                now[key] = (zone, {**fire, "fire_size": old.get("fire_size")})

        for key in self._seen.keys() - now.keys():
            # Left the radius list. Only "out" if it's gone from the active fires entirely
            # (a fire can also leave because a zone was removed).
            if key[1] not in self.coordinator.data["fires"]:
                zone, fire = self._seen[key]
                self._alert("fire_out", zone, fire)

        self._seen = now
