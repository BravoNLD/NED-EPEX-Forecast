"""Constants for the NED EPEX Forecast integration."""
from typing import Final

DOMAIN: Final = "ned_epex_forecast"

# API Configuration
NED_API_BASE: Final = "https://api.ned.nl/v1"
NED_API_TIMEOUT: Final = 30

# NED API Type IDs
TYPE_WIND_ONSHORE: Final = 1
TYPE_SOLAR: Final = 2
TYPE_RESTLAST: Final = 5
TYPE_WIND_OFFSHORE: Final = 17
TYPE_CONSUMPTION: Final = 18

# Update intervals
UPDATE_INTERVAL_MINUTES: Final = 15

# Configuration keys
CONF_API_TOKEN: Final = "api_token"
CONF_CHARGE_HOURS: Final = "charge_hours"
CONF_FORECAST_HOURS: Final = "forecast_hours"

# Default values
DEFAULT_CHARGE_HOURS: Final = 8
DEFAULT_FORECAST_HOURS: Final = 144

# Sensor attributes
ATTR_FORECAST: Final = "forecast"
ATTR_CHARGE_WINDOWS: Final = "charge_windows"
ATTR_NEXT_WINDOW: Final = "next_window"
ATTR_CURRENT_PRICE: Final = "current_price"
ATTR_AVERAGE_PRICE: Final = "average_price"
