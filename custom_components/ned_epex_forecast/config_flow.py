"""Config flow for NED EPEX Forecast integration."""
from __future__ import annotations

import logging
from typing import Any

import voluptuous as vol
from homeassistant import config_entries
from homeassistant.core import HomeAssistant, callback

from .const import (
    DOMAIN,
    CONF_API_TOKEN,
    CONF_EPEX_MULTIPLIER,
    CONF_EPEX_OFFSET,
    DEFAULT_MULTIPLIER,
    DEFAULT_OFFSET,
    NED_API_BASE,
)

_LOGGER = logging.getLogger(__name__)


async def validate_api_token(hass: HomeAssistant, api_token: str) -> bool:
    """Validate the API token by making a test request."""
    import aiohttp  # pylint: disable=import-outside-toplevel

    headers = {"X-AUTH-TOKEN": api_token}

    # Test met een simpele call naar de utilizations endpoint
    params = {
        "point": 0,
        "type": 5,
        "granularity": 5,
        "classification": 2,
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

        # Schema met standaardwaarden
        data_schema = vol.Schema({
            vol.Required(CONF_API_TOKEN): str,
            vol.Optional(
                CONF_EPEX_MULTIPLIER,
                default=DEFAULT_MULTIPLIER
            ): vol.All(vol.Coerce(float), vol.Range(min=-100, max=100)),
            vol.Optional(
                CONF_EPEX_OFFSET,
                default=DEFAULT_OFFSET
            ): vol.All(vol.Coerce(float), vol.Range(min=-100, max=100)),
        })

        return self.async_show_form(
            step_id="user",
            data_schema=data_schema,
            errors=errors,
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
                    CONF_EPEX_MULTIPLIER: user_input[CONF_EPEX_MULTIPLIER],
                    CONF_EPEX_OFFSET: user_input[CONF_EPEX_OFFSET],
                }
            )

            # Reload de integratie om de nieuwe waarden te gebruiken
            await self.hass.config_entries.async_reload(
                self.config_entry.entry_id
            )

            return self.async_create_entry(title="", data={})

        # Haal huidige waarden op
        current_multiplier = self.config_entry.data.get(
            CONF_EPEX_MULTIPLIER,
            DEFAULT_MULTIPLIER
        )
        current_offset = self.config_entry.data.get(
            CONF_EPEX_OFFSET,
            DEFAULT_OFFSET
        )

        options_schema = vol.Schema({
            vol.Required(
                CONF_EPEX_MULTIPLIER,
                default=current_multiplier
            ): vol.All(vol.Coerce(float), vol.Range(min=-100, max=100)),
            vol.Required(
                CONF_EPEX_OFFSET,
                default=current_offset
            ): vol.All(vol.Coerce(float), vol.Range(min=-100, max=100)),
        })

        return self.async_show_form(
            step_id="init",
            data_schema=options_schema,
        )
