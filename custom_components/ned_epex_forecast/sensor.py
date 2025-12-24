"""Sensor platform for NED EPEX Forecast."""
from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime
import logging
from typing import Any

from homeassistant.components.sensor import (
    SensorDeviceClass,
    SensorEntity,
    SensorEntityDescription,
    SensorStateClass,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import UnitOfEnergy, UnitOfPower
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity
from homeassistant.util import dt as dt_util

from .const import ATTR_FORECAST, DOMAIN
from .coordinator import NEDEPEXCoordinator

_LOGGER = logging.getLogger(__name__)


@dataclass
class NEDEPEXSensorEntityDescription(SensorEntityDescription):
    """Describes NED EPEX sensor entity."""

    value_fn: Callable[[dict[str, Any]], Any] | None = None
    attr_fn: Callable[[dict[str, Any]], dict[str, Any]] | None = None


def _get_latest_value(data_key: str, value_key: str = "capacity") -> Callable:
    """Get the latest value from a sensor's data list."""

    def _get_value(data: dict[str, Any]) -> float | None:
        sensor_data = data.get(data_key, [])
        if not sensor_data:
            return None
        # Neem de nieuwste waarde (dichtst bij nu)
        now = dt_util.now()
        closest = min(sensor_data, key=lambda x: abs(x["timestamp"] - now))
        return round(closest.get(value_key, 0), 2)

    return _get_value


def _get_forecast_attr(data_key: str) -> Callable:
    """Get forecast attributes for a sensor."""

    def _get_attrs(data: dict[str, Any]) -> dict[str, Any]:
        sensor_data = data.get(data_key, [])
        if not sensor_data:
            return {}
        
        # Limiteer tot forecast_hours (max 144)
        forecast_list = [
            {
                "timestamp": record["timestamp"].isoformat(),
                "value": round(record.get("capacity", 0), 2),
            }
            for record in sensor_data[:144]  # Max 144 uur
        ]
        
        return {ATTR_FORECAST: forecast_list}

    return _get_attrs


def _get_combined_value(value_key: str) -> Callable:
    """Get a value from the combined ned_data forecast."""

    def _get_value(data: dict[str, Any]) -> float | None:
        ned_data = data.get("ned_data", {})
        forecast = ned_data.get("forecast", [])
        if not forecast:
            return None
        
        # Neem de waarde die het dichtst bij nu ligt
        now = dt_util.now()
        closest = min(forecast, key=lambda x: abs(x["timestamp"] - now))
        return round(closest.get(value_key, 0), 2)

    return _get_value


def _get_combined_forecast(value_key: str) -> Callable:
    """Get forecast for a combined value."""

    def _get_attrs(data: dict[str, Any]) -> dict[str, Any]:
        ned_data = data.get("ned_data", {})
        forecast = ned_data.get("forecast", [])
        if not forecast:
            return {}
        
        forecast_list = [
            {
                "timestamp": record["timestamp"].isoformat(),
                "value": round(record.get(value_key, 0), 2),
            }
            for record in forecast[:144]
        ]
        
        return {ATTR_FORECAST: forecast_list}

    return _get_attrs


def _get_epex_price(data: dict[str, Any]) -> float | None:
    """Get current EPEX price."""
    price_forecast = data.get("price_forecast", [])
    if not price_forecast:
        return None
    
    now = dt_util.now()
    closest = min(price_forecast, key=lambda x: abs(x["timestamp"] - now))
    return round(closest.get("price", 0), 2)


def _get_epex_forecast(data: dict[str, Any]) -> dict[str, Any]:
    """Get EPEX price forecast attributes."""
    price_forecast = data.get("price_forecast", [])
    if not price_forecast:
        return {}
    
    forecast_list = [
        {
            "timestamp": record["timestamp"].isoformat(),
            "price": round(record["price"], 2),
            "restlast_gw": round(record.get("restlast_gw", 0), 2),
        }
        for record in price_forecast[:144]
    ]
    
    # Bereken ook wat stats
    prices = [r["price"] for r in price_forecast[:24]]  # Volgende 24 uur
    
    attrs = {
        ATTR_FORECAST: forecast_list,
        "min_price_24h": round(min(prices), 2) if prices else None,
        "max_price_24h": round(max(prices), 2) if prices else None,
        "avg_price_24h": round(sum(prices) / len(prices), 2) if prices else None,
    }
    
    return attrs


def _get_charge_advice(data: dict[str, Any]) -> str | None:
    """Get charge advice status."""
    charge_advice = data.get("charge_advice", {})
    next_window = charge_advice.get("next_window")
    
    if not next_window:
        return "no_window"
    
    now = dt_util.now()
    start = next_window["start"]
    end = next_window["end"]
    
    if start <= now < end:
        return "charging"
    elif now < start:
        return "waiting"
    else:
        return "no_window"


def _get_charge_attrs(data: dict[str, Any]) -> dict[str, Any]:
    """Get charge advice attributes."""
    charge_advice = data.get("charge_advice", {})
    
    windows = charge_advice.get("windows", [])
    next_window = charge_advice.get("next_window")
    
    # Converteer timestamps naar ISO strings
    windows_serialized = []
    for window in windows:
        windows_serialized.append({
            "start": window["start"].isoformat(),
            "end": window["end"].isoformat(),
            "duration_hours": window["duration_hours"],
            "average_price": window["average_price"],
            "prices": window["prices"],
        })
    
    next_window_serialized = None
    if next_window:
        next_window_serialized = {
            "start": next_window["start"].isoformat(),
            "end": next_window["end"].isoformat(),
            "duration_hours": next_window["duration_hours"],
            "average_price": next_window["average_price"],
        }
    
    return {
        "windows": windows_serialized,
        "next_window": next_window_serialized,
        "average_price": charge_advice.get("average_price"),
        "total_windows": len(windows),
    }


SENSOR_TYPES: tuple[NEDEPEXSensorEntityDescription, ...] = (
    # Wind Onshore
    NEDEPEXSensorEntityDescription(
        key="wind_onshore",
        translation_key="wind_onshore",
        name="Wind Onshore",
        native_unit_of_measurement="GW",
        device_class=SensorDeviceClass.POWER,
        state_class=SensorStateClass.MEASUREMENT,
        suggested_display_precision=2,
        value_fn=_get_latest_value("wind_onshore"),
        attr_fn=_get_forecast_attr("wind_onshore"),
    ),
    # Wind Offshore
    NEDEPEXSensorEntityDescription(
        key="wind_offshore",
        translation_key="wind_offshore",
        name="Wind Offshore",
        native_unit_of_measurement="GW",
        device_class=SensorDeviceClass.POWER,
        state_class=SensorStateClass.MEASUREMENT,
        suggested_display_precision=2,
        value_fn=_get_latest_value("wind_offshore"),
        attr_fn=_get_forecast_attr("wind_offshore"),
    ),
    # Solar
    NEDEPEXSensorEntityDescription(
        key="solar",
        translation_key="solar",
        name="Solar",
        native_unit_of_measurement="GW",
        device_class=SensorDeviceClass.POWER,
        state_class=SensorStateClass.MEASUREMENT,
        suggested_display_precision=2,
        value_fn=_get_latest_value("solar"),
        attr_fn=_get_forecast_attr("solar"),
    ),
    # Consumption
    NEDEPEXSensorEntityDescription(
        key="consumption",
        translation_key="consumption",
        name="Consumption",
        native_unit_of_measurement="GW",
        device_class=SensorDeviceClass.POWER,
        state_class=SensorStateClass.MEASUREMENT,
        suggested_display_precision=2,
        value_fn=_get_latest_value("consumption"),
        attr_fn=_get_forecast_attr("consumption"),
    ),
    # Restlast
    NEDEPEXSensorEntityDescription(
        key="restlast",
        translation_key="restlast",
        name="Restlast",
        native_unit_of_measurement="GW",
        device_class=SensorDeviceClass.POWER,
        state_class=SensorStateClass.MEASUREMENT,
        suggested_display_precision=2,
        value_fn=_get_combined_value("restlast_gw"),
        attr_fn=_get_combined_forecast("restlast_gw"),
    ),
    # EPEX Price
    NEDEPEXSensorEntityDescription(
        key="epex_price",
        translation_key="epex_price",
        name="EPEX Price",
        native_unit_of_measurement="€/MWh",
        device_class=SensorDeviceClass.MONETARY,
        state_class=SensorStateClass.MEASUREMENT,
        suggested_display_precision=2,
        value_fn=_get_epex_price,
        attr_fn=_get_epex_forecast,
    ),
    # Charge Advice
    NEDEPEXSensorEntityDescription(
        key="charge_advice",
        translation_key="charge_advice",
        name="Charge Advice",
        device_class=SensorDeviceClass.ENUM,
        options=["charging", "waiting", "no_window"],
        value_fn=_get_charge_advice,
        attr_fn=_get_charge_attrs,
    ),
)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up NED EPEX Forecast sensors."""
    coordinator: NEDEPEXCoordinator = hass.data[DOMAIN][entry.entry_id]

    entities = [
        NEDEPEXSensor(coordinator, description) for description in SENSOR_TYPES
    ]

    async_add_entities(entities)


class NEDEPEXSensor(CoordinatorEntity[NEDEPEXCoordinator], SensorEntity):
    """Representation of a NED EPEX Forecast sensor."""

    entity_description: NEDEPEXSensorEntityDescription
    _attr_has_entity_name = True

    def __init__(
        self,
        coordinator: NEDEPEXCoordinator,
        description: NEDEPEXSensorEntityDescription,
    ) -> None:
        """Initialize the sensor."""
        super().__init__(coordinator)
        self.entity_description = description
        self._attr_unique_id = f"{DOMAIN}_{description.key}"
        self._attr_device_info = {
            "identifiers": {(DOMAIN, coordinator.config_entry.entry_id)},
            "name": "NED EPEX Forecast",
            "manufacturer": "NED",
            "model": "EPEX Forecast",
            "sw_version": "1.0.0",
        }

    @property
    def native_value(self) -> Any:
        """Return the state of the sensor."""
        if self.coordinator.data is None:
            return None

        if self.entity_description.value_fn:
            return self.entity_description.value_fn(self.coordinator.data)

        return None

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        """Return the state attributes."""
        if self.coordinator.data is None:
            return {}

        if self.entity_description.attr_fn:
            return self.entity_description.attr_fn(self.coordinator.data)

        return {}
