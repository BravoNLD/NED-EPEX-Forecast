"""Sensors for NED EPEX Forecast."""
import logging
from homeassistant.components.sensor import SensorEntity, SensorStateClass
from homeassistant.helpers.update_coordinator import CoordinatorEntity
from homeassistant.util import dt as dt_util

from .const import DOMAIN

_LOGGER = logging.getLogger(__name__)


async def async_setup_entry(hass, entry, async_add_entities):
    """Set up NED EPEX sensors."""
    coordinator = hass.data[DOMAIN][entry.entry_id]

    sensors = [
        NEDRestlastSensor(coordinator, entry),
        NEDPriceForecastSensor(coordinator, entry),
        NEDChargeAdviceSensor(coordinator, entry),
        NEDModelAccuracySensor(coordinator, entry),
        NEDConsumptionSensor(coordinator, entry),
        NEDWindOnshoreSensor(coordinator, entry),
        NEDWindOffshoreSensor(coordinator, entry),
        NEDSolarSensor(coordinator, entry),
    ]

    async_add_entities(sensors)


class NEDRestlastSensor(CoordinatorEntity, SensorEntity):
    """Sensor for current restlast (residual load)."""

    def __init__(self, coordinator, entry):
        super().__init__(coordinator)
        self._entry = entry
        self._attr_unique_id = f"{entry.entry_id}_restlast"
        self._attr_name = "NED Restlast"
        self._attr_icon = "mdi:transmission-tower"
        self._attr_native_unit_of_measurement = "GW"
        self._attr_state_class = SensorStateClass.MEASUREMENT

    @property
    def native_value(self):
        """Return current restlast."""
        forecast = self.coordinator.data.get("ned_data", {}).get("forecast", [])
        if not forecast:
            return None

        # Return closest to now
        now = dt_util.now()
        closest = min(forecast, key=lambda x: abs((x["timestamp"] - now).total_seconds()))
        return closest.get("restlast_gw")

    @property
    def extra_state_attributes(self):
        """Return forecast data."""
        forecast = self.coordinator.data.get("ned_data", {}).get("forecast", [])

        return {
            "forecast": [
                {
                    "timestamp": f["timestamp"].isoformat(),
                    "restlast_gw": f["restlast_gw"],
                }
                for f in forecast[:24]  # Next 24 hours
            ]
        }


class NEDPriceForecastSensor(CoordinatorEntity, SensorEntity):
    """Sensor for current EPEX price forecast."""

    def __init__(self, coordinator, entry):
        super().__init__(coordinator)
        self._entry = entry
        self._attr_unique_id = f"{entry.entry_id}_price_forecast"
        self._attr_name = "NED Price Forecast"
        self._attr_icon = "mdi:cash"
        self._attr_native_unit_of_measurement = "ct/kWh"
        self._attr_state_class = SensorStateClass.MEASUREMENT

    @property
    def native_value(self):
        """Return current price forecast."""
        forecast = self.coordinator.data.get("price_forecast", [])
        if not forecast:
            return None

        now = dt_util.now()
        closest = min(forecast, key=lambda x: abs((x["timestamp"] - now).total_seconds()))
        return closest.get("price")

    @property
    def extra_state_attributes(self):
        """Return full forecast."""
        forecast = self.coordinator.data.get("price_forecast", [])

        return {
            "forecast": [
                {
                    "timestamp": f["timestamp"].isoformat(),
                    "price": f["price"],
                    "price_low": f["price_low"],
                    "price_high": f["price_high"],
                    "confidence_std": f["confidence_std"],
                }
                for f in forecast
            ]
        }


class NEDChargeAdviceSensor(CoordinatorEntity, SensorEntity):
    """Sensor providing charging advice."""

    def __init__(self, coordinator, entry):
        super().__init__(coordinator)
        self._entry = entry
        self._attr_unique_id = f"{entry.entry_id}_charge_advice"
        self._attr_name = "NED Charge Advice"
        self._attr_icon = "mdi:ev-station"

    @property
    def native_value(self):
        """Return advice state."""
        advice = self.coordinator.data.get("charge_advice", {})
        return advice.get("advice", "unknown")

    @property
    def extra_state_attributes(self):
        """Return detailed advice."""
        advice = self.coordinator.data.get("charge_advice", {})
        best_window = advice.get("best_window", {})

        attrs = {
            "savings_ct_per_kwh": advice.get("savings_ct_per_kwh", 0),
        }

        if best_window:
            attrs.update({
                "best_start": best_window["start"].isoformat(),
                "best_end": best_window["end"].isoformat(),
                "best_avg_price": best_window["avg_price"],
                "best_min_price": best_window.get("min_price"),
                "best_max_price": best_window.get("max_price"),
            })

        # Add all windows for comparison
        for key in ["window_now", "window_later", "window_much_later"]:
            window = advice.get(key)
            if window:
                attrs[key] = {
                    "start": window["start"].isoformat(),
                    "end": window["end"].isoformat(),
                    "avg_price": window["avg_price"],
                }

        return attrs


class NEDModelAccuracySensor(CoordinatorEntity, SensorEntity):
    """Sensor for model accuracy metrics."""

    def __init__(self, coordinator, entry):
        super().__init__(coordinator)
        self._entry = entry
        self._attr_unique_id = f"{entry.entry_id}_model_accuracy"
        self._attr_name = "NED Model Accuracy"
        self._attr_icon = "mdi:chart-line"
        self._attr_native_unit_of_measurement = "R²"

    @property
    def native_value(self):
        """Return R² score."""
        calib = self.coordinator.data.get("calibration", {})
        r2 = calib.get("r2_score")
        return round(r2, 3) if r2 is not None else None

    @property
    def extra_state_attributes(self):
        """Return calibration details."""
        calib = self.coordinator.data.get("calibration", {})

        attrs = {
            "multiplier": calib.get("multiplier"),
            "offset": calib.get("offset"),
            "mae_ct_per_kwh": calib.get("mae"),
            "samples": calib.get("samples", 0),
        }

        if calib.get("last_update"):
            attrs["last_calibration"] = calib["last_update"].isoformat()

        return attrs


class NEDConsumptionSensor(CoordinatorEntity, SensorEntity):
    """Sensor for consumption forecast."""

    def __init__(self, coordinator, entry):
        super().__init__(coordinator)
        self._entry = entry
        self._attr_unique_id = f"{entry.entry_id}_consumption"
        self._attr_name = "NED Consumption"
        self._attr_icon = "mdi:flash"
        self._attr_native_unit_of_measurement = "GW"
        self._attr_state_class = SensorStateClass.MEASUREMENT

    @property
    def native_value(self):
        """Return current consumption."""
        forecast = self.coordinator.data.get("ned_data", {}).get("forecast", [])
        if not forecast:
            return None

        now = dt_util.now()
        closest = min(forecast, key=lambda x: abs((x["timestamp"] - now).total_seconds()))
        return closest.get("consumption_gw")


class NEDWindOnshoreSensor(CoordinatorEntity, SensorEntity):
    """Sensor for wind onshore generation."""

    def __init__(self, coordinator, entry):
        super().__init__(coordinator)
        self._entry = entry
        self._attr_unique_id = f"{entry.entry_id}_wind_onshore"
        self._attr_name = "NED Wind Onshore"
        self._attr_icon = "mdi:wind-turbine"
        self._attr_native_unit_of_measurement = "GW"
        self._attr_state_class = SensorStateClass.MEASUREMENT

    @property
    def native_value(self):
        """Return current wind onshore."""
        forecast = self.coordinator.data.get("ned_data", {}).get("forecast", [])
        if not forecast:
            return None

        now = dt_util.now()
        closest = min(forecast, key=lambda x: abs((x["timestamp"] - now).total_seconds()))
        return closest.get("wind_onshore_gw")


class NEDWindOffshoreSensor(CoordinatorEntity, SensorEntity):
    """Sensor for wind offshore generation."""

    def __init__(self, coordinator, entry):
        super().__init__(coordinator)
        self._entry = entry
        self._attr_unique_id = f"{entry.entry_id}_wind_offshore"
        self._attr_name = "NED Wind Offshore"
        self._attr_icon = "mdi:wind-turbine"
        self._attr_native_unit_of_measurement = "GW"
        self._attr_state_class = SensorStateClass.MEASUREMENT

    @property
    def native_value(self):
        """Return current wind offshore."""
        forecast = self.coordinator.data.get("ned_data", {}).get("forecast", [])
        if not forecast:
            return None

        now = dt_util.now()
        closest = min(forecast, key=lambda x: abs((x["timestamp"] - now).total_seconds()))
        return closest.get("wind_offshore_gw")


class NEDSolarSensor(CoordinatorEntity, SensorEntity):
    """Sensor for solar generation."""

    def __init__(self, coordinator, entry):
        super().__init__(coordinator)
        self._entry = entry
        self._attr_unique_id = f"{entry.entry_id}_solar"
        self._attr_name = "NED Solar"
        self._attr_icon = "mdi:solar-power"
        self._attr_native_unit_of_measurement = "GW"
        self._attr_state_class = SensorStateClass.MEASUREMENT

    @property
    def native_value(self):
        """Return current solar."""
        forecast = self.coordinator.data.get("ned_data", {}).get("forecast", [])
        if not forecast:
            return None

        now = dt_util.now()
        closest = min(forecast, key=lambda x: abs((x["timestamp"] - now).total_seconds()))
        return closest.get("solar_gw")
