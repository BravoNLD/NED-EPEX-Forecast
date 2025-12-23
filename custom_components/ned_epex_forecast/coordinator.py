"""Data coordinator for NED EPEX Forecast."""
import asyncio
import logging
from datetime import datetime, timedelta
from typing import Any

import aiohttp
from homeassistant.core import HomeAssistant
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed
from homeassistant.util import dt as dt_util
from homeassistant.components.recorder import history

from .const import (
    DOMAIN,
    UPDATE_INTERVAL,
    NED_API_BASE,
    NED_API_TIMEOUT,
    DATA_TYPE_WIND_ONSHORE,
    DATA_TYPE_SOLAR,
    DATA_TYPE_WIND_OFFSHORE,
    DATA_TYPE_CONSUMPTION,
    DEFAULT_MULTIPLIER,
    DEFAULT_OFFSET,
    CONF_PRICE_ENTITY,
    CONF_CALIBRATION_DAYS,
    CONF_CALIBRATION_INTERVAL,
    CONF_CHARGE_WINDOW_HOURS,
    DEFAULT_CALIBRATION_DAYS,
    DEFAULT_CALIBRATION_INTERVAL,
    DEFAULT_CHARGE_WINDOW_HOURS,
    ADVICE_CHARGE_NOW,
    ADVICE_WAIT_2_3_DAYS,
    ADVICE_WAIT_4_7_DAYS,
    ADVICE_NO_DATA,
    ADVICE_UNCERTAIN,
)

_LOGGER = logging.getLogger(__name__)


class NEDEPEXCoordinator(DataUpdateCoordinator):
    """Coordinator to fetch NED data and calculate price forecasts."""

    def __init__(self, hass: HomeAssistant, entry) -> None:
        """Initialize coordinator."""
        super().__init__(
            hass,
            _LOGGER,
            name=DOMAIN,
            update_interval=UPDATE_INTERVAL,
        )
        self.entry = entry
        self.session = aiohttp.ClientSession()

        # API Token
        self.api_token = entry.data[CONF_API_TOKEN]
        
        # Configuration
        self.price_entity = entry.data[CONF_PRICE_ENTITY]
        self.calibration_days = entry.options.get(
            CONF_CALIBRATION_DAYS, 
            entry.data.get(CONF_CALIBRATION_DAYS, DEFAULT_CALIBRATION_DAYS)
        )
        self.calibration_interval = entry.options.get(
            CONF_CALIBRATION_INTERVAL,
            entry.data.get(CONF_CALIBRATION_INTERVAL, DEFAULT_CALIBRATION_INTERVAL)
        )
        self.charge_window_hours = entry.options.get(
            CONF_CHARGE_WINDOW_HOURS,
            entry.data.get(CONF_CHARGE_WINDOW_HOURS, DEFAULT_CHARGE_WINDOW_HOURS)
        )
        
        # Calibration state
        self.multiplier = DEFAULT_MULTIPLIER
        self.offset = DEFAULT_OFFSET
        self.last_calibration = None
        self.calibration_r2 = None
        self.calibration_mae = None
        self.calibration_samples = 0

    async def _async_update_data(self):
        """Fetch data from NED API and calculate forecasts."""
        try:
            # 1. Fetch NED forecast data
            ned_data = await self._fetch_ned_forecast()
            
            # 2. Auto-calibrate if needed
            if self._should_calibrate():
                await self._calibrate_model()
            
            # 3. Calculate price forecast
            price_forecast = self._calculate_price_forecast(ned_data)
            
            # 4. Generate charge advice
            charge_advice = self._calculate_charge_advice(price_forecast)
            
            return {
                "ned_data": ned_data,
                "price_forecast": price_forecast,
                "charge_advice": charge_advice,
                "calibration": {
                    "multiplier": self.multiplier,
                    "offset": self.offset,
                    "r2_score": self.calibration_r2,
                    "mae": self.calibration_mae,
                    "last_update": self.last_calibration,
                    "samples": self.calibration_samples,
                },
            }
            
        except Exception as err:
            raise UpdateFailed(f"Error fetching data: {err}")

    async def _fetch_ned_forecast(self) -> dict:
        """Fetch forecast data from NED API."""
        try:
            # Fetch all data types in parallel
            tasks = [
                self._fetch_ned_data_type(DATA_TYPE_CONSUMPTION),
                self._fetch_ned_data_type(DATA_TYPE_WIND_ONSHORE),
                self._fetch_ned_data_type(DATA_TYPE_WIND_OFFSHORE),
                self._fetch_ned_data_type(DATA_TYPE_SOLAR),
            ]
            
            results = await asyncio.gather(*tasks, return_exceptions=True)
            
            consumption, wind_onshore, wind_offshore, solar = results
            
            # Check for errors
            for idx, result in enumerate(results):
                if isinstance(result, Exception):
                    _LOGGER.error(f"Error fetching data type {idx}: {result}")
                    raise result
            
            # Combine into forecast with restlast
            forecast = self._combine_ned_data(
                consumption, wind_onshore, wind_offshore, solar
            )
            
            return {
                "consumption": consumption,
                "wind_onshore": wind_onshore,
                "wind_offshore": wind_offshore,
                "solar": solar,
                "forecast": forecast,
            }
            
        except Exception as err:
            _LOGGER.error(f"Failed to fetch NED data: {err}")
            raise

    async def _fetch_ned_data_type(self, data_type: int) -> dict:
        """Fetch a specific data type from NED API."""
        url = f"{NED_API_BASE}/utilizations/{data_type}/values"
        params = {
            "granularity": "fifteen_minutes",
            "classification": "TenneT",
        }
        
        try:
            async with self.session.get(
                url, 
                params=params, 
                timeout=NED_API_TIMEOUT
            ) as response:
                response.raise_for_status()
                data = await response.json()
                return data
                
        except asyncio.TimeoutError:
            raise UpdateFailed(f"Timeout fetching NED data type {data_type}")
        except aiohttp.ClientError as err:
            raise UpdateFailed(f"Error fetching NED data type {data_type}: {err}")

    def _combine_ned_data(self, consumption, wind_onshore, wind_offshore, solar) -> list:
        """Combine NED data into hourly forecast with restlast."""
        forecast = []
        
        # Get values arrays
        cons_values = consumption.get("values", [])
        wind_on_values = wind_onshore.get("values", [])
        wind_off_values = wind_offshore.get("values", [])
        solar_values = solar.get("values", [])
        
        # Group by hour (NED gives 15-min intervals)
        hourly_data = {}
        
        for idx, cons_point in enumerate(cons_values):
            timestamp_str = cons_point.get("validfrom")
            if not timestamp_str:
                continue
                
            # Parse timestamp
            timestamp = dt_util.parse_datetime(timestamp_str)
            if not timestamp:
                continue
            
            # Round to hour
            hour_key = timestamp.replace(minute=0, second=0, microsecond=0)
            
            if hour_key not in hourly_data:
                hourly_data[hour_key] = {
                    "consumption": [],
                    "wind_onshore": [],
                    "wind_offshore": [],
                    "solar": [],
                }
            
            # Add values (in MW)
            hourly_data[hour_key]["consumption"].append(
                cons_point.get("value", 0)
            )
            
            if idx < len(wind_on_values):
                hourly_data[hour_key]["wind_onshore"].append(
                    wind_on_values[idx].get("value", 0)
                )
            
            if idx < len(wind_off_values):
                hourly_data[hour_key]["wind_offshore"].append(
                    wind_off_values[idx].get("value", 0)
                )
            
            if idx < len(solar_values):
                hourly_data[hour_key]["solar"].append(
                    solar_values[idx].get("value", 0)
                )
        
        # Calculate hourly averages and restlast
        for timestamp in sorted(hourly_data.keys()):
            data = hourly_data[timestamp]
            
            # Average MW over the hour
            avg_consumption = sum(data["consumption"]) / len(data["consumption"]) if data["consumption"] else 0
            avg_wind_on = sum(data["wind_onshore"]) / len(data["wind_onshore"]) if data["wind_onshore"] else 0
            avg_wind_off = sum(data["wind_offshore"]) / len(data["wind_offshore"]) if data["wind_offshore"] else 0
            avg_solar = sum(data["solar"]) / len(data["solar"]) if data["solar"] else 0
            
            # Convert MW to GW
            consumption_gw = avg_consumption / 1000
            wind_on_gw = avg_wind_on / 1000
            wind_off_gw = avg_wind_off / 1000
            solar_gw = avg_solar / 1000
            
            # Calculate restlast (consumption - renewable generation)
            restlast_gw = consumption_gw - (wind_on_gw + wind_off_gw + solar_gw)
            
            forecast.append({
                "timestamp": timestamp,
                "consumption_gw": round(consumption_gw, 3),
                "wind_onshore_gw": round(wind_on_gw, 3),
                "wind_offshore_gw": round(wind_off_gw, 3),
                "solar_gw": round(solar_gw, 3),
                "restlast_gw": round(restlast_gw, 3),
            })
        
        return forecast

    def _should_calibrate(self) -> bool:
        """Check if calibration should run."""
        if self.last_calibration is None:
            return True
        
        time_since = dt_util.now() - self.last_calibration
        return time_since >= timedelta(hours=self.calibration_interval)

    async def _calibrate_model(self):
        """Calibrate pricing model using historical data."""
        _LOGGER.info("Starting model calibration...")
        
        try:
            # 1. Get historical price data
            historical_prices = await self._get_historical_prices()
            
            if len(historical_prices) < 50:
                _LOGGER.warning(
                    f"Insufficient price data for calibration: {len(historical_prices)} hours"
                )
                return
            
            # 2. Get historical NED restlast
            timestamps = [p["timestamp"] for p in historical_prices]
            historical_restlast = await self._get_historical_restlast(timestamps)
            
            # 3. Match data points
            matched_data = []
            for price_point in historical_prices:
                ts = price_point["timestamp"]
                
                # Find closest restlast (within 1 hour)
                restlast = None
                for restlast_ts, restlast_val in historical_restlast.items():
                    if abs((ts - restlast_ts).total_seconds()) < 3600:
                        restlast = restlast_val
                        break
                
                if restlast is not None and price_point["price"] is not None:
                    matched_data.append({
                        "restlast": restlast,
                        "price": price_point["price"],
                    })
            
            if len(matched_data) < 50:
                _LOGGER.warning(
                    f"Insufficient matched data for calibration: {len(matched_data)} points"
                )
                return
            
            # 4. Fit linear model
            xs = [d["restlast"] for d in matched_data]
            ys = [d["price"] for d in matched_data]
            
            new_mult, new_offset = self._fit_linear(xs, ys)
            
            # 5. Calculate metrics
            predictions = [new_mult * x + new_offset for x in xs]
            r2 = self._calculate_r2(ys, predictions)
            mae = sum(abs(y - p) for y, p in zip(ys, predictions)) / len(ys)
            
            # 6. Validate and update
            if 0.0 < new_mult < 10.0 and -20.0 < new_offset < 20.0 and r2 > 0.2:
                _LOGGER.info(
                    f"Calibration successful: multiplier {self.multiplier:.3f} → {new_mult:.3f}, "
                    f"offset {self.offset:.2f} → {new_offset:.2f} "
                    f"(R²={r2:.3f}, MAE={mae:.2f}ct, n={len(matched_data)})"
                )
                
                self.multiplier = new_mult
                self.offset = new_offset
                self.calibration_r2 = r2
                self.calibration_mae = mae
                self.calibration_samples = len(matched_data)
                self.last_calibration = dt_util.now()
            else:
                _LOGGER.warning(
                    f"Calibration rejected (unrealistic values): "
                    f"mult={new_mult:.3f}, offset={new_offset:.2f}, R²={r2:.3f}"
                )
                
        except Exception as err:
            _LOGGER.error(f"Calibration failed: {err}", exc_info=True)

    async def _get_historical_prices(self) -> list:
        """Get historical prices from configured sensor."""
        prices = []
        
        try:
            end_time = dt_util.now()
            start_time = end_time - timedelta(days=self.calibration_days)
            
            # Fetch from recorder
            states = await self.hass.async_add_executor_job(
                history.state_changes_during_period,
                self.hass,
                start_time,
                end_time,
                self.price_entity,
            )
            
            if self.price_entity not in states:
                _LOGGER.warning(f"No history found for {self.price_entity}")
                return prices
            
            for state in states[self.price_entity]:
                try:
                    # Try to parse state value
                    price = float(state.state)
                    timestamp = state.last_changed
                    
                    # Price should be in ct/kWh or €/kWh
                    # Normalize to ct/kWh
                    if price < 1.0:  # Likely €/kWh
                        price = price * 100
                    
                    prices.append({
                        "timestamp": timestamp,
                        "price": price,
                    })
                    
                except (ValueError, TypeError):
                    # Check if price is in attributes (Nordpool style)
                    raw_today = state.attributes.get("raw_today", [])
                    for entry in raw_today:
                        if "start" in entry and "value" in entry:
                            start = dt_util.parse_datetime(entry["start"])
                            value = entry["value"] * 100  # €/kWh → ct/kWh
                            prices.append({
                                "timestamp": start,
                                "price": value,
                            })
                    
                    raw_tomorrow = state.attributes.get("raw_tomorrow", [])
                    for entry in raw_tomorrow:
                        if "start" in entry and "value" in entry:
                            start = dt_util.parse_datetime(entry["start"])
                            value = entry["value"] * 100
                            prices.append({
                                "timestamp": start,
                                "price": value,
                            })
            
            _LOGGER.debug(f"Retrieved {len(prices)} historical price points")
            return prices
            
        except Exception as err:
            _LOGGER.error(f"Error fetching historical prices: {err}")
            return []

    async def _get_historical_restlast(self, timestamps: list) -> dict:
        """Get historical restlast values."""
        # Try to fetch from existing NED sensors if available
        restlast_sensor = f"sensor.{DOMAIN}_restlast"
        restlast_data = {}
        
        try:
            if len(timestamps) == 0:
                return restlast_data
            
            start_time = min(timestamps)
            end_time = max(timestamps)
            
            # Check if we have a restlast sensor with history
            states = await self.hass.async_add_executor_job(
                history.state_changes_during_period,
                self.hass,
                start_time,
                end_time,
                restlast_sensor,
            )
            
            if restlast_sensor in states:
                for state in states[restlast_sensor]:
                    try:
                        value = float(state.state)
                        restlast_data[state.last_changed] = value
                    except (ValueError, TypeError):
                        continue
            
            _LOGGER.debug(f"Retrieved {len(restlast_data)} historical restlast points")
            
        except Exception as err:
            _LOGGER.debug(f"Could not fetch historical restlast: {err}")
        
        return restlast_data

    def _fit_linear(self, xs: list, ys: list) -> tuple:
        """Least squares linear regression without numpy."""
        n = len(xs)
        if n < 2:
            return self.multiplier, self.offset
        
        mean_x = sum(xs) / n
        mean_y = sum(ys) / n
        
        s_xy = sum((x - mean_x) * (y - mean_y) for x, y in zip(xs, ys))
        s_xx = sum((x - mean_x) ** 2 for x in xs)
        
        if s_xx < 0.001:
            return self.multiplier, self.offset
        
        a = s_xy / s_xx
        b = mean_y - a * mean_x
        
        return a, b

    def _calculate_r2(self, actuals: list, predictions: list) -> float:
        """Calculate R² score."""
        n = len(actuals)
        if n == 0:
            return 0.0
        
        mean_actual = sum(actuals) / n
        ss_tot = sum((y - mean_actual) ** 2 for y in actuals)
        ss_res = sum((y - p) ** 2 for y, p in zip(actuals, predictions))
        
        if ss_tot < 0.0001:
            return 0.0
        
        return max(0.0, 1.0 - (ss_res / ss_tot))

    def _calculate_price_forecast(self, ned_data: dict) -> list:
        """Calculate price forecast from NED restlast."""
        forecast = []
        
        for hour_data in ned_data.get("forecast", []):
            restlast = hour_data["restlast_gw"]
            timestamp = hour_data["timestamp"]
            
            # Linear price model
            price = (self.multiplier * restlast) + self.offset
            
            # Confidence interval (wider for future)
            hours_ahead = (timestamp - dt_util.now()).total_seconds() / 3600
            confidence_std = 0.5 + (hours_ahead / 48) * 1.5
            
            forecast.append({
                "timestamp": timestamp,
                "price": round(price, 2),
                "price_low": round(price - confidence_std, 2),
                "price_high": round(price + confidence_std, 2),
                "confidence_std": round(confidence_std, 2),
                "restlast_gw": restlast,
            })
        
        return forecast

    def _calculate_charge_advice(self, price_forecast: list) -> dict:
        """Calculate charging advice based on price forecast."""
        if not price_forecast:
            return {
                "advice": ADVICE_NO_DATA,
                "best_window": None,
                "savings_ct_per_kwh": 0,
            }
        
        # Split into time windows
        now = dt_util.now()
        
        window_now = [
            p for p in price_forecast
            if 0 <= (p["timestamp"] - now).total_seconds() / 3600 < 48
        ]
        window_later = [
            p for p in price_forecast
            if 48 <= (p["timestamp"] - now).total_seconds() / 3600 < 96
        ]
        window_much_later = [
            p for p in price_forecast
            if 96 <= (p["timestamp"] - now).total_seconds() / 3600 < 168
        ]
        
        # Find best charging windows
        best_now = self._find_best_window(window_now, self.charge_window_hours)
        best_later = self._find_best_window(window_later, self.charge_window_hours)
        best_much_later = self._find_best_window(window_much_later, self.charge_window_hours)
        
        # Determine advice
        if not best_now:
            advice = ADVICE_NO_DATA
            best_option = None
            savings = 0
        elif best_later and best_later["avg_price"] < best_now["avg_price"] * 0.90:
            advice = ADVICE_WAIT_2_3_DAYS
            best_option = best_later
            savings = best_now["avg_price"] - best_later["avg_price"]
        elif best_much_later and best_much_later["avg_price"] < best_now["avg_price"] * 0.85:
            advice = ADVICE_WAIT_4_7_DAYS
            best_option = best_much_later
            savings = best_now["avg_price"] - best_much_later["avg_price"]
        else:
            advice = ADVICE_CHARGE_NOW
            best_option = best_now
            savings = 0
        
        return {
            "advice": advice,
            "best_window": best_option,
            "savings_ct_per_kwh": round(savings, 2) if savings else 0,
            "window_now": best_now,
            "window_later": best_later,
            "window_much_later": best_much_later,
        }

    def _find_best_window(self, prices: list, hours: int) -> dict | None:
        """Find cheapest consecutive window."""
        if not prices or len(prices) < hours:
            return None
        
        best = None
        
        for i in range(len(prices) - hours + 1):
            window = prices[i:i + hours]
            avg_price = sum(p["price"] for p in window) / hours
            
            if best is None or avg_price < best["avg_price"]:
                best = {
                    "start": window[0]["timestamp"],
                    "end": window[-1]["timestamp"],
                    "avg_price": round(avg_price, 2),
                    "min_price": round(min(p["price"] for p in window), 2),
                    "max_price": round(max(p["price"] for p in window), 2),
                }
        
        return best

    async def async_shutdown(self):
        """Close session on shutdown."""
        await self.session.close()
