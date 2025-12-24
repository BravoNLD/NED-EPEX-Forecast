"""Config flow for NED EPEX Forecast integration."""
from __future__ import annotations

import logging
from typing import Any

import voluptuous as vol
from homeassistant import config_entries
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers import selector

from .const import (
    DOMAIN,
    CONF_API_TOKEN,
    CONF_PRICE_SENSOR,
    CONF_EPEX_MULTIPLIER,
    CONF_EPEX_OFFSET,
    CONF_CALIBRATION_DAYS,
    CONF_CALIBRATION_INTERVAL,
    CONF_CHARGE_WINDOW_HOURS,
    DEFAULT_MULTIPLIER,
    DEFAULT_OFFSET,
    DEFAULT_CALIBRATION_DAYS,
    DEFAULT_CALIBRATION_INTERVAL,
    DEFAULT_CHARGE_WINDOW_HOURS,
    NED_API_BASE,
)

_LOGGER = logging.getLogger(__name__)


async def validate_api_token(_hass: HomeAssistant, api_token: str) -> bool:
    """Validate the API token by making a test request."""
    import aiohttp  # pylint: disable=import-outside-toplevel

    headers = {"X-AUTH-TOKEN": api_token}

    # Test met een simpele call naar de utilizations endpoint
    params = {
        "point": 0,
        "type": 5,
        "granularity": 5,
        "classification": 2,
        "validfrom[after]": "2025-12-22",
        "validfrom[strictly_before]": "2025-12-24",
    }

    try:
        timeout = aiohttp.ClientTimeout(total=10)
        async with aiohttp.ClientSession() as session:
            async with session.get(
                f"{NED_API_BASE}/utilizations",
                headers=headers,
                params=params,
                timeout=timeout,
            ) as response:
                if response.status in (401, 403):
                    _LOGGER.error(
                        "Authentication failed with status %d",
                        response.status
                    )
                    return False

                if response.status == 200:
                    return True

                _LOGGER.error(
                    "Unexpected response status %d",
                    response.status
                )
                return False

    except aiohttp.ClientError:
        _LOGGER.exception("Connection error during API token validation")
        return False
    except Exception:  # pylint: disable=broad-exception-caught
        _LOGGER.exception("Unexpected error during API token validation")
        return False


class NEDEPEXConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    """Handle a config flow for NED EPEX Forecast."""

    VERSION = 1

    async def async_step_user(
        self,
        user_input: dict[str, Any] | None = None
    ) -> config_entries.FlowResult:
        """Handle the initial step."""
        errors: dict[str, str] = {}

        if user_input is not None:
            api_token = user_input[CONF_API_TOKEN]

            # Valideer de API token
            if await validate_api_token(self.hass, api_token):
                await self.async_set_unique_id(api_token[:8])
                self._abort_if_unique_id_configured()

                return self.async_create_entry(
                    title="NED EPEX Forecast",
                    data=user_input,
                )

            errors["base"] = "invalid_auth"

        # Schema met alle velden inclusief price sensor selector
        data_schema = vol.Schema({
            vol.Required(CONF_PRICE_SENSOR): selector.EntitySelector(
                selector.EntitySelectorConfig(domain="sensor")
            ),
            vol.Required(CONF_API_TOKEN): str,
            vol.Optional(
                CONF_EPEX_MULTIPLIER,
                default=DEFAULT_MULTIPLIER
            ): vol.All(vol.Coerce(float), vol.Range(min=-100, max=100)),
            vol.Optional(
                CONF_EPEX_OFFSET,
                default=DEFAULT_OFFSET
            ): vol.All(vol.Coerce(float), vol.Range(min=-100, max=100)),
            vol.Optional(
                CONF_CALIBRATION_DAYS,
                default=DEFAULT_CALIBRATION_DAYS
            ): vol.All(vol.Coerce(int), vol.Range(min=1, max=30)),
            vol.Optional(
                CONF_CALIBRATION_INTERVAL,
                default=DEFAULT_CALIBRATION_INTERVAL
            ): vol.All(vol.Coerce(int), vol.Range(min=1, max=168)),
            vol.Optional(
                CONF_CHARGE_WINDOW_HOURS,
                default=DEFAULT_CHARGE_WINDOW_HOURS
            ): vol.All(vol.Coerce(int), vol.Range(min=1, max=24)),
        })

        return self.async_show_form(
            step_id="user",
            data_schema=data_schema,
            errors=errors,
            description_placeholders={
                "info": "Configure NED EPEX price forecasting. Select your EPEX/day-ahead price sensor (e.g., Nordpool)."
            }
        )

    @staticmethod
    @callback
    def async_get_options_flow(
        config_entry: config_entries.ConfigEntry,
    ) -> NEDEPEXOptionsFlow:
        """Get the options flow for this handler."""
        return NEDEPEXOptionsFlow(config_entry)


class NEDEPEXOptionsFlow(config_entries.OptionsFlow):
    """Handle options flow for NED EPEX Forecast."""

    def __init__(self, config_entry: config_entries.ConfigEntry) -> None:
        """Initialize options flow."""
        self.config_entry = config_entry

    async def async_step_init(
        self,
        user_input: dict[str, Any] | None = None
    ) -> config_entries.FlowResult:
        """Manage the options."""
        if user_input is not None:
            # Update de config entry data
            self.hass.config_entries.async_update_entry(
                self.config_entry,
                data={
                    **self.config_entry.data,
                    **user_input,
                }
            )

            # Reload de integratie om de nieuwe waarden te gebruiken
            await self.hass.config_entries.async_reload(
                self.config_entry.entry_id
            )

            return self.async_create_entry(title="", data={})

        # Haal huidige waarden op
        data = self.config_entry.data
        current_price_sensor = data.get(CONF_PRICE_SENSOR, "")
        current_multiplier = data.get(CONF_EPEX_MULTIPLIER, DEFAULT_MULTIPLIER)
        current_offset = data.get(CONF_EPEX_OFFSET, DEFAULT_OFFSET)
        current_cal_days = data.get(CONF_CALIBRATION_DAYS, DEFAULT_CALIBRATION_DAYS)
        current_cal_interval = data.get(CONF_CALIBRATION_INTERVAL, DEFAULT_CALIBRATION_INTERVAL)
        current_window = data.get(CONF_CHARGE_WINDOW_HOURS, DEFAULT_CHARGE_WINDOW_HOURS)

        options_schema = vol.Schema({
            vol.Required(
                CONF_PRICE_SENSOR,
                default=current_price_sensor
            ): selector.EntitySelector(
                selector.EntitySelectorConfig(domain="sensor")
            ),
            vol.Required(
                CONF_EPEX_MULTIPLIER,
                default=current_multiplier
            ): vol.All(vol.Coerce(float), vol.Range(min=-100, max=100)),
            vol.Required(
                CONF_EPEX_OFFSET,
                default=current_offset
            ): vol.All(vol.Coerce(float), vol.Range(min=-100, max=100)),
            vol.Required(
                CONF_CALIBRATION_DAYS,
                default=current_cal_days
            ): vol.All(vol.Coerce(int), vol.Range(min=1, max=30)),
            vol.Required(
                CONF_CALIBRATION_INTERVAL,
                default=current_cal_interval
            ): vol.All(vol.Coerce(int), vol.Range(min=1, max=168)),
            vol.Required(
                CONF_CHARGE_WINDOW_HOURS,
                default=current_window
            ): vol.All(vol.Coerce(int), vol.Range(min=1, max=24)),
        })

        return self.async_show_form(
            step_id="init",
            data_schema=options_schema,
        )
