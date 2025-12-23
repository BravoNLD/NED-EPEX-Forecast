# custom_components/ned_epex_forecast/config_flow.py

"""Config flow for NED EPEX Forecast."""
import logging
import aiohttp
import voluptuous as vol

from homeassistant import config_entries
from homeassistant.core import callback
from homeassistant.helpers import selector

from .const import (
    DOMAIN,
    CONF_API_TOKEN,
    CONF_PRICE_ENTITY,
    CONF_CALIBRATION_DAYS,
    CONF_CALIBRATION_INTERVAL,
    CONF_CHARGE_WINDOW_HOURS,
    DEFAULT_CALIBRATION_DAYS,
    DEFAULT_CALIBRATION_INTERVAL,
    DEFAULT_CHARGE_WINDOW_HOURS,
    NED_API_BASE,
)

_LOGGER = logging.getLogger(__name__)


async def validate_api_token(api_token: str) -> bool:
    """Test if NED API token is valid."""
    url = f"{NED_API_BASE}/utilizations/1/values"
    headers = {
        "X-AUTH-TOKEN": api_token,
        "accept": "application/ld+json",
    }
    params = {
        "granularity": "hour",
        "classification": "TenneT",
    }
    
    try:
        async with aiohttp.ClientSession() as session:
            async with session.get(
                url, headers=headers, params=params, timeout=10
            ) as response:
                if response.status == 401:
                    return False
                if response.status == 403:
                    return False
                return response.status == 200
    except Exception as err:
        _LOGGER.error(f"Token validation failed: {err}")
        return False


class NEDEPEXConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    """Handle config flow for NED EPEX Forecast."""

    VERSION = 1

    async def async_step_user(self, user_input=None):
        """Handle initial setup step."""
        errors = {}

        if user_input is not None:
            # Validate API token
            if not await validate_api_token(user_input[CONF_API_TOKEN]):
                errors["base"] = "invalid_auth"
            else:
                # Check if price entity exists
                price_entity = user_input.get(CONF_PRICE_ENTITY)
                if price_entity and not self.hass.states.get(price_entity):
                    errors["price_entity_id"] = "entity_not_found"
                else:
                    # All good, create entry
                    return self.async_create_entry(
                        title="NED EPEX Forecast",
                        data=user_input,
                    )

        # Show form
        data_schema = vol.Schema({
            vol.Required(CONF_API_TOKEN): str,
            vol.Optional(CONF_PRICE_ENTITY): selector.EntitySelector(
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
            ): vol.All(vol.Coerce(int), vol.Range(min=1, max=12)),
        })

        return self.async_show_form(
            step_id="user",
            data_schema=data_schema,
            errors=errors,
        )

    @staticmethod
    @callback
    def async_get_options_flow(config_entry):
        """Get options flow handler."""
        return NEDEPEXOptionsFlow(config_entry)


class NEDEPEXOptionsFlow(config_entries.OptionsFlow):
    """Handle options flow."""

    def __init__(self, config_entry):
        """Initialize options flow."""
        self.config_entry = config_entry

    async def async_step_init(self, user_input=None):
        """Manage options."""
        errors = {}
        
        if user_input is not None:
            # ✅ FIX 1: Valideer token als deze is gewijzigd
            new_token = user_input.get(CONF_API_TOKEN)
            current_token = self.config_entry.data.get(CONF_API_TOKEN)
            
            if new_token and new_token != current_token:
                # Token is gewijzigd, valideer deze
                if not await validate_api_token(new_token):
                    errors["base"] = "invalid_auth"
                else:
                    # ✅ FIX 2: Update entry.data met nieuwe token
                    new_data = {**self.config_entry.data}
                    new_data[CONF_API_TOKEN] = new_token
                    
                    self.hass.config_entries.async_update_entry(
                        self.config_entry,
                        data=new_data,
                    )
                    
                    _LOGGER.info("API token updated successfully")
            
            # ✅ FIX 3: Check price entity als deze is opgegeven
            price_entity = user_input.get(CONF_PRICE_ENTITY)
            if price_entity and not self.hass.states.get(price_entity):
                errors["price_entity_id"] = "entity_not_found"
            
            # Als er geen errors zijn, sla options op
            if not errors:
                return self.async_create_entry(title="", data=user_input)

        # Get current values
        current_api_token = self.config_entry.data.get(CONF_API_TOKEN, "")
        current_price_entity = self.config_entry.options.get(
            CONF_PRICE_ENTITY, 
            self.config_entry.data.get(CONF_PRICE_ENTITY)
        )
        current_cal_days = self.config_entry.options.get(
            CONF_CALIBRATION_DAYS,
            self.config_entry.data.get(CONF_CALIBRATION_DAYS, DEFAULT_CALIBRATION_DAYS)
        )
        current_cal_interval = self.config_entry.options.get(
            CONF_CALIBRATION_INTERVAL,
            self.config_entry.data.get(CONF_CALIBRATION_INTERVAL, DEFAULT_CALIBRATION_INTERVAL)
        )
        current_window = self.config_entry.options.get(
            CONF_CHARGE_WINDOW_HOURS,
            self.config_entry.data.get(CONF_CHARGE_WINDOW_HOURS, DEFAULT_CHARGE_WINDOW_HOURS)
        )

        options_schema = vol.Schema({
            vol.Optional(CONF_API_TOKEN, default=current_api_token): str,
            vol.Optional(CONF_PRICE_ENTITY, default=current_price_entity): selector.EntitySelector(
                selector.EntitySelectorConfig(domain="sensor")
            ),
            vol.Optional(CONF_CALIBRATION_DAYS, default=current_cal_days): vol.All(
                vol.Coerce(int), vol.Range(min=7, max=90)
            ),
            vol.Optional(CONF_CALIBRATION_INTERVAL, default=current_cal_interval): vol.All(
                vol.Coerce(int), vol.Range(min=1, max=168)
            ),
            vol.Optional(CONF_CHARGE_WINDOW_HOURS, default=current_window): vol.All(
                vol.Coerce(int), vol.Range(min=1, max=12)
            ),
        })

        return self.async_show_form(
            step_id="init",
            data_schema=options_schema,
            errors=errors,  # ✅ FIX 4: Errors meegeven aan form
        )
