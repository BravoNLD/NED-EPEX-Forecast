"""Config flow for NED EPEX Forecast integration."""
from __future__ import annotations

import logging
from typing import Any

import aiohttp
import voluptuous as vol

from homeassistant import config_entries
from homeassistant.const import CONF_API_TOKEN
from homeassistant.core import HomeAssistant, callback
from homeassistant.data_entry_flow import FlowResult
from homeassistant.helpers import config_validation as cv

from .const import (
    CONF_CHARGE_HOURS,
    CONF_FORECAST_HOURS,
    DEFAULT_CHARGE_HOURS,
    DEFAULT_FORECAST_HOURS,
    DOMAIN,
    NED_API_BASE,
)

_LOGGER = logging.getLogger(__name__)

STEP_USER_DATA_SCHEMA = vol.Schema(
    {
        vol.Required(CONF_API_TOKEN): cv.string,
    }
)


async def validate_api_token(hass: HomeAssistant, api_token: str) -> dict[str, Any]:
    """Validate the API token by making a test request."""
    headers = {"X-AUTH-TOKEN": api_token}
    
    # Test met een simpele query (wind onshore, 1 dag)
    params = {
        "point": 0,
        "type": 1,  # Wind onshore
        "granularity": 5,
        "classification": 2,
        "activity": 1,
        "validfrom[after]": "2024-01-01",
        "validfrom[strictly_before]": "2024-01-02",
    }

    try:
        async with aiohttp.ClientSession() as session:
            async with session.get(
                f"{NED_API_BASE}/utilizations",
                headers=headers,
                params=params,
                timeout=aiohttp.ClientTimeout(total=10),
            ) as response:
                if response.status in (401, 403):
                    return {"error": "invalid_auth"}
                if response.status != 200:
                    return {"error": "cannot_connect"}
                
                # Check of we data krijgen
                data = await response.json()
                if "hydra:member" not in data:
                    return {"error": "invalid_response"}
                
                return {"title": "NED EPEX Forecast"}

    except aiohttp.ClientError:
        return {"error": "cannot_connect"}
    except Exception:  # pylint: disable=broad-except
        _LOGGER.exception("Unexpected exception during validation")
        return {"error": "unknown"}


class NEDEPEXConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    """Handle a config flow for NED EPEX Forecast."""

    VERSION = 1

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        """Handle the initial step."""
        errors: dict[str, str] = {}

        if user_input is not None:
            # Valideer API token
            result = await validate_api_token(self.hass, user_input[CONF_API_TOKEN])
            
            if "error" in result:
                errors["base"] = result["error"]
            else:
                # Sla configuratie op
                await self.async_set_unique_id(user_input[CONF_API_TOKEN][:8])
                self._abort_if_unique_id_configured()

                return self.async_create_entry(
                    title=result["title"],
                    data=user_input,
                )

        return self.async_show_form(
            step_id="user",
            data_schema=STEP_USER_DATA_SCHEMA,
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
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        """Manage the options."""
        if user_input is not None:
            return self.async_create_entry(title="", data=user_input)

        return self.async_show_form(
            step_id="init",
            data_schema=vol.Schema(
                {
                    vol.Optional(
                        CONF_CHARGE_HOURS,
                        default=self.config_entry.options.get(
                            CONF_CHARGE_HOURS, DEFAULT_CHARGE_HOURS
                        ),
                    ): vol.All(vol.Coerce(int), vol.Range(min=1, max=24)),
                    vol.Optional(
                        CONF_FORECAST_HOURS,
                        default=self.config_entry.options.get(
                            CONF_FORECAST_HOURS, DEFAULT_FORECAST_HOURS
                        ),
                    ): vol.All(vol.Coerce(int), vol.Range(min=24, max=168)),
                }
            ),
        )
