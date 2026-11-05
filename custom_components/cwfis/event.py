"""Fire alert event entity.

Fires an event when, for any fire inside any zone's alert radius:
  * new_fire_nearby - a fire appears inside the radius
  * stage_changed   - its stage of control changes (e.g. Being held -> Out of control)
  * fire_grew       - it grows by GROWTH_FACTOR and at least GROWTH_MIN_HA since the last alert
  * fire_out        - it disappears from the active list (declared out)

The entity's state is the time of the last event; use it as an automation trigger.
"""

from __future__ import annotations

from homeassistant.components.event import EventEntity
from homeassistant.core import callback

from .const import GROWTH_FACTOR, GROWTH_MIN_HA, STAGES
from .entity import CwfisEntity
from .helpers import fire_info


async def async_setup_entry(hass, entry, async_add_entities):
    """A single Fire alert entity covers every zone."""
    async_add_entities([FireAlert(entry)])


class FireAlert(CwfisEntity, EventEntity):
    """Compares each update with the previous one and fires the matching events."""

    _attr_translation_key = "fire_alert"
    _attr_event_types = ["new_fire_nearby", "stage_changed", "fire_grew", "fire_out"]

    def __init__(self, entry):
        """Take a first snapshot of nearby fires to compare future updates against."""
        super().__init__(entry, "fire_alert", "Fire alert", "mdi:bell-alert")
        # Start from what's already nearby so a restart doesn't announce every fire as "new".
        self._seen = self._snapshot()

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
        """Compare this update with the previous one and fire the matching events."""
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
        super()._handle_coordinator_update()
