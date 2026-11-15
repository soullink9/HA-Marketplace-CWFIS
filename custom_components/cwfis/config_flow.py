"""Config flow: one-click setup, and the Configure (options) form for everything else.

Saving the options form reloads the integration automatically (OptionsFlowWithReload),
so new zones, provinces or maps appear straight away.
"""

from typing import Any

from homeassistant.components.sensor import SensorDeviceClass
from homeassistant.config_entries import ConfigFlow, ConfigFlowResult, OptionsFlowWithReload
from homeassistant.core import callback
from homeassistant.helpers.selector import (
    EntitySelector,
    EntitySelectorConfig,
    NumberSelector,
    NumberSelectorConfig,
    NumberSelectorMode,
    SelectOptionDict,
    SelectSelector,
    SelectSelectorConfig,
)
import probatio

from .const import (
    CONF_MAP_FIRES,
    CONF_MAP_IMAGES,
    CONF_PM25,
    CONF_PM25_THRESHOLD,
    CONF_PROVINCES,
    CONF_RADIUS,
    CONF_SMOKE_RADIUS,
    CONF_WIND,
    CONF_ZONES,
    DEFAULT_MAP_FIRES,
    DEFAULT_PM25,
    DEFAULT_RADIUS,
    DEFAULT_SMOKE_RADIUS,
    DOMAIN,
    MAP_FIRES_MODES,
    MAPS,
    PROVINCES,
)
from .coordinator import CwfisConfigEntry


def _number(low: float, high: float, step: float, unit: str) -> NumberSelector:
    """A number input box with a unit label."""
    return NumberSelector(
        NumberSelectorConfig(min=low, max=high, step=step, unit_of_measurement=unit, mode=NumberSelectorMode.BOX)
    )


def _multi_select(options: dict[str, str]) -> SelectSelector:
    """A multi-select list from a {value: label} dict."""
    return SelectSelector(
        SelectSelectorConfig(
            options=[SelectOptionDict(value=value, label=label) for value, label in options.items()], multiple=True
        )
    )


# Field labels and help text live in translations/en.json under options.step.init.
OPTIONS_SCHEMA = probatio.Schema(
    {
        probatio.Required(CONF_RADIUS, default=DEFAULT_RADIUS): _number(10, 5000, 10, "km"),
        probatio.Optional(CONF_ZONES): EntitySelector(EntitySelectorConfig(domain="zone", multiple=True)),
        probatio.Required(CONF_SMOKE_RADIUS, default=DEFAULT_SMOKE_RADIUS): _number(50, 5000, 50, "km"),
        probatio.Optional(CONF_WIND): EntitySelector(EntitySelectorConfig(domain="sensor")),
        probatio.Optional(CONF_PM25): EntitySelector(
            EntitySelectorConfig(domain="sensor", device_class=SensorDeviceClass.PM25)
        ),
        probatio.Required(CONF_PM25_THRESHOLD, default=DEFAULT_PM25): _number(1, 500, 1, "µg/m³"),
        probatio.Optional(CONF_PROVINCES): _multi_select(PROVINCES),
        probatio.Required(CONF_MAP_FIRES, default=DEFAULT_MAP_FIRES): SelectSelector(
            SelectSelectorConfig(options=MAP_FIRES_MODES, translation_key=CONF_MAP_FIRES)
        ),
        probatio.Optional(CONF_MAP_IMAGES): SelectSelector(
            SelectSelectorConfig(options=list(MAPS), multiple=True, translation_key=CONF_MAP_IMAGES)
        ),
    }
)


class CwfisConfigFlow(ConfigFlow, domain=DOMAIN):
    """Setup needs no input: everything uses Home Assistant's Home location and sensible defaults."""

    VERSION = 1

    async def async_step_user(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        """Create the entry straight away; no questions needed."""
        # Only one CWFIS entry is allowed ("single_config_entry" in manifest.json).
        return self.async_create_entry(title="CWFIS", data={})

    @staticmethod
    @callback
    def async_get_options_flow(config_entry: CwfisConfigEntry) -> CwfisOptionsFlow:
        """The Configure form (alert radius, smoke radius, watch zones, sensors, provinces and maps)."""
        return CwfisOptionsFlow()


class CwfisOptionsFlow(OptionsFlowWithReload):
    """The Configure form."""

    async def async_step_init(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        """Show the form, or save the submitted settings."""
        if user_input is not None:
            return self.async_create_entry(data=user_input)
        # Pre-fill the form with the current settings.
        return self.async_show_form(
            step_id="init", data_schema=self.add_suggested_values_to_schema(OPTIONS_SCHEMA, self.config_entry.options)
        )
