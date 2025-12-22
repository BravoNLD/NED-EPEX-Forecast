"""Config flow for NED EPEX Forecast."""
import logging
import voluptuous as vol

from homeassistant import config_entries
from homeassistant.core import callback
from homeassistant.helpers import selector
import homeassistant.helpers.config_validation as cv

from .const import (
    DOMAIN,
    CONF_PRICE_ENTITY,
    CONF_CALIBRATION_DAYS,
    CONF_CALIBRATION_INTERVAL,
    CONF_CHARGE_WINDOW_HOURS,
    DEFAULT_CALIBRATION_DAYS,
    DEFAULT_CALIBRATION_INTERVAL,
    DEFAULT_CHARGE_WINDOW_HOURS,
)

_LOGGER = logging.getLogger(__name__)


class NEDEPEXConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    """Handle a config flow for NED EPEX Forecast."""

    VERSION = 1

    async def async_step_user(self, user_input=None):
        """Handle the initial step."""
        errors = {}

        if user_input is not None:
            # Validate price entity exists
            price_entity = user_input[CONF_PRICE_ENTITY]
            if not self.hass.states.get(price_entity):
                errors[CONF_PRICE_ENTITY] = "entity_not_found"
            else:
                # Create entry
                await self.async_set_unique_id(f"ned_epex_{price_entity}")
                self._abort_if_unique_id_configured()
                
                return self.async_create_entry(
                    title=f"NED EPEX ({price_entity.split('.')[-1]})",
                    data=user_input,
                )

        data_schema = vol.Schema(
            {
                vol.Required(CONF_PRICE_ENTITY): selector.EntitySelector(
                    selector.EntitySelectorConfig(domain="sensor")
                ),
                vol.Optional(
                    CONF_CALIBRATION_DAYS,
                    default=DEFAULT_CALIBRATION_DAYS
                ): vol.All(vol.Coerce(int), vol.Range(min=7, max=90)),
                vol.Optional(
                    CONF_CALIBRATION_INTERVAL,
                    default=DEFAULT_CALIBRATION_INTERVAL
                ): vol.All(vol.Coerce(int), vol.Range(min=1, max=168)),
                vol.Optional(
                    CONF_CHARGE_WINDOW_HOURS,
                    default=DEFAULT_CHARGE_WINDOW_HOURS
                ): vol.All(vol.Coerce(int), vol.Range(min=1, max=24)),
            }
        )

        return self.async_show_form(
            step_id="user",
            data_schema=data_schema,
            errors=errors,
        )

    @staticmethod
    @callback
    def async_get_options_flow(config_entry):
        """Get the options flow for this handler."""
        return NEDEPEXOptionsFlow(config_entry)


class NEDEPEXOptionsFlow(config_entries.OptionsFlow):
    """Handle options flow."""

    def __init__(self, config_entry):
        """Initialize options flow."""
        self.config_entry = config_entry

    async def async_step_init(self, user_input=None):
        """Manage the options."""
        if user_input is not None:
            return self.async_create_entry(title="", data=user_input)

        return self.async_show_form(
            step_id="init",
            data_schema=vol.Schema(
                {
                    vol.Optional(
                        CONF_CALIBRATION_DAYS,
                        default=self.config_entry.options.get(
                            CONF_CALIBRATION_DAYS, DEFAULT_CALIBRATION_DAYS
                        ),
                    ): vol.All(vol.Coerce(int), vol.Range(min=7, max=90)),
                    vol.Optional(
                        CONF_CALIBRATION_INTERVAL,
                        default=self.config_entry.options.get(
                            CONF_CALIBRATION_INTERVAL, DEFAULT_CALIBRATION_INTERVAL
                        ),
                    ): vol.All(vol.Coerce(int), vol.Range(min=1, max=168)),
                    vol.Optional(
                        CONF_CHARGE_WINDOW_HOURS,
                        default=self.config_entry.options.get(
                            CONF_CHARGE_WINDOW_HOURS, DEFAULT_CHARGE_WINDOW_HOURS
                        ),
                    ): vol.All(vol.Coerce(int), vol.Range(min=1, max=24)),
                }
            ),
        )
