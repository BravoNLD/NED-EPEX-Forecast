"""Config flow for NED EPEX Forecast integration."""
from __future__ import annotations

import logging
from typing import Any

import voluptuous as vol
from homeassistant import config_entries
from homeassistant.core import callback
from homeassistant.helpers import selector
import homeassistant.helpers.config_validation as cv

from .const import (
    DOMAIN,
    CONF_API_TOKEN,
    CONF_PRICE_ENTITY,
    CONF_CALIBRATION_DAYS,
    CONF_CALIBRATION_INTERVAL,
    CONF_CHARGE_WINDOW_HOURS,
    CONF_EPEX_MULTIPLIER,
    CONF_EPEX_OFFSET,
    DEFAULT_CALIBRATION_DAYS,
    DEFAULT_CALIBRATION_INTERVAL,
    DEFAULT_CHARGE_WINDOW_HOURS,
    DEFAULT_MULTIPLIER,
    DEFAULT_OFFSET,
    NED_API_BASE,
)

_LOGGER = logging.getLogger(__name__)


class NEDEPEXConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    """Handle a config flow for NED EPEX Forecast."""

    VERSION = 1

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> config_entries.FlowResult:
        """Handle the initial step."""
        errors: dict[str, str] = {}

        if user_input is not None:
            # Validate API token by making a test request
            api_token = user_input[CONF_API_TOKEN]
            
            try:
                import aiohttp
                async with aiohttp.ClientSession() as session:
                    headers = {"Authorization": f"Bearer {api_token}"}
                    async with session.get(
                        f"{NED_API_BASE}/forecast/renewable_nl",
                        headers=headers,
                        timeout=aiohttp.ClientTimeout(total=10)
                    ) as response:
                        if response.status == 401:
                            errors["base"] = "invalid_auth"
                        elif response.status != 200:
                            errors["base"] = "cannot_connect"
                        else:
                            # API token is valid, create entry
                            await self.async_set_unique_id(user_input[CONF_API_TOKEN])
                            self._abort_if_unique_id_configured()
                            
                            return self.async_create_entry(
                                title="NED EPEX Forecast",
                                data=user_input,
                            )
            except Exception:
                _LOGGER.exception("Unexpected exception during validation")
                errors["base"] = "unknown"

        data_schema = vol.Schema(
            {
                vol.Required(CONF_API_TOKEN): str,
                vol.Required(CONF_PRICE_ENTITY): selector.EntitySelector(
                    selector.EntitySelectorConfig(domain="sensor")
                ),
                vol.Optional(
                    CONF_CALIBRATION_DAYS, 
                    default=DEFAULT_CALIBRATION_DAYS
                ): vol.All(vol.Coerce(int), vol.Range(min=1, max=365)),
                vol.Optional(
                    CONF_CALIBRATION_INTERVAL, 
                    default=DEFAULT_CALIBRATION_INTERVAL
                ): vol.All(vol.Coerce(int), vol.Range(min=1, max=24)),
                vol.Optional(
                    CONF_CHARGE_WINDOW_HOURS, 
                    default=DEFAULT_CHARGE_WINDOW_HOURS
                ): vol.All(vol.Coerce(int), vol.Range(min=1, max=12)),
                vol.Optional(
                    CONF_EPEX_MULTIPLIER,
                    default=DEFAULT_MULTIPLIER
                ): vol.All(vol.Coerce(float), vol.Range(min=0.1, max=10.0)),
                vol.Optional(
                    CONF_EPEX_OFFSET,
                    default=DEFAULT_OFFSET
                ): vol.All(vol.Coerce(float), vol.Range(min=-20.0, max=20.0)),
            }
        )

        return self.async_show_form(
            step_id="user",
            data_schema=data_schema,
            errors=errors,
        )

    @staticmethod
    @callback
    def async_get_options_flow(
        config_entry: config_entries.ConfigEntry,
    ) -> config_entries.OptionsFlow:
        """Get the options flow for this handler."""
        return OptionsFlowHandler(config_entry)


class OptionsFlowHandler(config_entries.OptionsFlow):
    """Handle options flow for NED EPEX Forecast."""

    def __init__(self, config_entry: config_entries.ConfigEntry) -> None:
        """Initialize options flow."""
        self.config_entry = config_entry

    async def async_step_init(
        self, user_input: dict[str, Any] | None = None
    ) -> config_entries.FlowResult:
        """Manage the options."""
        if user_input is not None:
            return self.async_create_entry(title="", data=user_input)

        # Get current values
        current_calibration_days = self.config_entry.options.get(
            CONF_CALIBRATION_DAYS,
            self.config_entry.data.get(CONF_CALIBRATION_DAYS, DEFAULT_CALIBRATION_DAYS)
        )
        current_calibration_interval = self.config_entry.options.get(
            CONF_CALIBRATION_INTERVAL,
            self.config_entry.data.get(CONF_CALIBRATION_INTERVAL, DEFAULT_CALIBRATION_INTERVAL)
        )
        current_window = self.config_entry.options.get(
            CONF_CHARGE_WINDOW_HOURS,
            self.config_entry.data.get(CONF_CHARGE_WINDOW_HOURS, DEFAULT_CHARGE_WINDOW_HOURS)
        )
        current_multiplier = self.config_entry.options.get(
            CONF_EPEX_MULTIPLIER,
            self.config_entry.data.get(CONF_EPEX_MULTIPLIER, DEFAULT_MULTIPLIER)
        )
        current_offset = self.config_entry.options.get(
            CONF_EPEX_OFFSET,
            self.config_entry.data.get(CONF_EPEX_OFFSET, DEFAULT_OFFSET)
        )

        options_schema = vol.Schema(
            {
                vol.Optional(CONF_CALIBRATION_DAYS, default=current_calibration_days): vol.All(
                    vol.Coerce(int), vol.Range(min=1, max=365)
                ),
                vol.Optional(CONF_CALIBRATION_INTERVAL, default=current_calibration_interval): vol.All(
                    vol.Coerce(int), vol.Range(min=1, max=24)
                ),
                vol.Optional(CONF_CHARGE_WINDOW_HOURS, default=current_window): vol.All(
                    vol.Coerce(int), vol.Range(min=1, max=12)
                ),
                vol.Optional(CONF_EPEX_MULTIPLIER, default=current_multiplier): vol.All(
                    vol.Coerce(float), vol.Range(min=0.1, max=10.0)
                ),
                vol.Optional(CONF_EPEX_OFFSET, default=current_offset): vol.All(
                    vol.Coerce(float), vol.Range(min=-20.0, max=20.0)
                ),
            }
        )

        return self.async_show_form(step_id="init", data_schema=options_schema)
