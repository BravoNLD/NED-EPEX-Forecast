"""Constants for NED EPEX Forecast integration."""
from datetime import timedelta

DOMAIN = "ned_epex_forecast"
NAME = "NED EPEX Forecast"

# Configuration
CONF_API_TOKEN = "api_token"
CONF_PRICE_ENTITY = "price_entity_id"
CONF_CALIBRATION_DAYS = "calibration_days"
CONF_CALIBRATION_INTERVAL = "calibration_interval_hours"
CONF_CHARGE_WINDOW_HOURS = "charge_window_hours"

# Defaults
DEFAULT_CALIBRATION_DAYS = 14
DEFAULT_CALIBRATION_INTERVAL = 24
DEFAULT_CHARGE_WINDOW_HOURS = 4
DEFAULT_MULTIPLIER = 1.27
DEFAULT_OFFSET = 1.5

# Update interval
UPDATE_INTERVAL = timedelta(hours=1)

# NED API
NED_API_BASE = "https://api.ned.nl/v1"
API_ENDPOINT = "/utilizations"
NED_API_TIMEOUT = 30

# NED Data Types
DATA_TYPE_WIND_ONSHORE = 1
DATA_TYPE_SOLAR = 2
DATA_TYPE_WIND_OFFSHORE = 51
DATA_TYPE_CONSUMPTION = 59

# NED API Classifications
CLASSIFICATION_FORECAST = 1

# NED API Activities
ACTIVITY_PRODUCTION = 1
ACTIVITY_CONSUMPTION = 2

# NED API Granularity
GRANULARITY_HOURLY = 5
GRANULARITY_TIMEZONE_CET = 1

# Advice states
ADVICE_CHARGE_NOW = "charge_now"
ADVICE_WAIT_2_3_DAYS = "wait_2_3_days"
ADVICE_WAIT_4_7_DAYS = "wait_4_7_days"
ADVICE_NO_DATA = "no_data"
ADVICE_UNCERTAIN = "uncertain"
