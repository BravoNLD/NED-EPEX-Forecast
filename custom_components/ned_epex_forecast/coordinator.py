"""Config flow for NED EPEX Forecast integration."""
from __future__ import annotations

import logging
from typing import Any
from datetime import datetime, timedelta

import aiohttp
import asyncio
import voluptuous as vol

from homeassistant import config_entries
from homeassistant.core import HomeAssistant, callback
from homeassistant.data_entry_flow import FlowResult
from homeassistant.exceptions import HomeAssistantError
import homeassistant.helpers.config_validation as cv

from .const import (
    DOMAIN,
    CONF_API_TOKEN,
    NED_API_BASE,
    CONF_EPEX_MULTIPLIER,  # Als je deze al hebt toegevoegd
    CONF_EPEX_OFFSET,      # Als je deze al hebt toegevoegd
)

_LOGGER = logging.getLogger(__name__)


async def validate_api_token(api_token: str) -> bool:
    """Test if NED API token is valid."""
    url = f"{NED_API_BASE}/utilizations"
    
    # ✅ Use datetime range for test (24 hours ahead like working version)
    now = datetime.now()
    start_date = now.strftime("%Y-%m-%d")
    end_date = (now + timedelta(hours=24)).strftime("%Y-%m-%d")
    
    headers = {
        "X-AUTH-TOKEN": api_token,
        "accept": "application/ld+json",
    }
    
    # ✅ Parameters met INTEGERS zoals in werkende versie!
    params = {
        "point": 0,
        "type": 1,  # Wind onshore voor test
        "granularity": 5,  # ✅ HOURLY (integer!)
        "granularitytimezone": 1,  # ✅ CET (integer!)
        "classification": 1,  # ✅ FORECAST (integer!)
        "activity": 1,  # PRODUCTION
        "validfrom[after]": start_date,
        "validfrom[strictly_before]": end_date,
    }
    
    try:
        async with aiohttp.ClientSession() as session:
            async with session.get(
                url, headers=headers, params=params, timeout=aiohttp.ClientTimeout(total=30)
            ) as response:
                _LOGGER.info(f"NED API validation status: {response.status}")
                
                if response.status == 401:
                    _LOGGER.error("Invalid API token (401 Unauthorized)")
                    return False
                
                if response.status == 403:
                    _LOGGER.error("API access forbidden (403 Forbidden)")
                    return False
                
                if response.status != 200:
                    error_text = await response.text()
                    _LOGGER.error(f"NED API error {response.status}: {error_text}")
                    return False
                
                # ✅ Check of we data terugkrijgen
                data = await response.json()
                records = data.get("hydra:member", [])
                
                if not records:
                    _LOGGER.warning("API test returned no data, but API is accessible")
                    # Sommige tokens hebben geen toegang tot alle data types
                    # maar de API is wel geldig
                    return True
                
                _LOGGER.info(f"API test successful, got {len(records)} records")
                return True
                
    except asyncio.TimeoutError:
        _LOGGER.error("API validation timed out")
        return False
    except aiohttp.ClientError as err:
        _LOGGER.error(f"Connection error during API test: {err}")
        return False
    except Exception as err:
        _LOGGER.exception(f"Unexpected error during API test: {err}")
        return False


class NEDEPEXConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    """Handle a config flow for NED EPEX Forecast."""

    VERSION = 1

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        """Handle the initial step."""
        errors: dict[str, str] = {}

        if user_input is not None:
            try:
                api_token = user_input[CONF_API_TOKEN]
                
                # Validate API token
                _LOGGER.info("Validating NED API token...")
                is_valid = await validate_api_token(api_token)
                
                if not is_valid:
                    _LOGGER.error("API token validation failed")
                    errors["base"] = "invalid_auth"
                else:
                    _LOGGER.info("API token validation successful")
                    
                    # Create entry
                    return self.async_create_entry(
                        title="NED EPEX Forecast",
                        data={
                            CONF_API_TOKEN: api_token,
                            # Als je de multiplier/offset wilt toevoegen:
                            # CONF_EPEX_MULTIPLIER: user_input.get(CONF_EPEX_MULTIPLIER, 1.27),
                            # CONF_EPEX_OFFSET: user_input.get(CONF_EPEX_OFFSET, 1.5),
                        },
                    )
                    
            except Exception as err:
                _LOGGER.exception(f"Unexpected exception: {err}")
                errors["base"] = "unknown"

        # Schema voor het formulier
        data_schema = vol.Schema(
            {
                vol.Required(CONF_API_TOKEN): cv.string,
                # Als je multiplier/offset wilt toevoegen:
                # vol.Optional(CONF_EPEX_MULTIPLIER, default=1.27): vol.Coerce(float),
                # vol.Optional(CONF_EPEX_OFFSET, default=1.5): vol.Coerce(float),
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
        return NEDEPEXOptionsFlowHandler(config_entry)


class NEDEPEXOptionsFlowHandler(config_entries.OptionsFlow):
    """Handle options flow for NED EPEX Forecast."""

    def __init__(self, config_entry: config_entries.ConfigEntry) -> None:
        """Initialize options flow."""
        self.config_entry = config_entry

    async def async_step_init(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        """Manage the options."""
        if user_input is not None:
            # Update config entry data
            self.hass.config_entries.async_update_entry(
                self.config_entry,
                data={
                    **self.config_entry.data,
                    CONF_EPEX_MULTIPLIER: user_input.get(
                        CONF_EPEX_MULTIPLIER, 
                        self.config_entry.data.get(CONF_EPEX_MULTIPLIER, 1.27)
                    ),
                    CONF_EPEX_OFFSET: user_input.get(
                        CONF_EPEX_OFFSET,
                        self.config_entry.data.get(CONF_EPEX_OFFSET, 1.5)
                    ),
                },
            )
            return self.async_create_entry(title="", data={})

        # Schema voor options
        return self.async_show_form(
            step_id="init",
            data_schema=vol.Schema(
                {
                    vol.Optional(
                        CONF_EPEX_MULTIPLIER,
                        default=self.config_entry.data.get(CONF_EPEX_MULTIPLIER, 1.27),
                    ): vol.Coerce(float),
                    vol.Optional(
                        CONF_EPEX_OFFSET,
                        default=self.config_entry.data.get(CONF_EPEX_OFFSET, 1.5),
                    ): vol.Coerce(float),
                }
            ),
        )


class CannotConnect(HomeAssistantError):
    """Error to indicate we cannot connect."""


class InvalidAuth(HomeAssistantError):
    """Error to indicate there is invalid auth."""
