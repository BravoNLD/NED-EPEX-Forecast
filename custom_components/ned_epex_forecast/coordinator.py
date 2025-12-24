"""DataUpdateCoordinator for NED EPEX Forecast."""
from __future__ import annotations

import asyncio
from datetime import datetime, timedelta
import logging
from typing import Any

import aiohttp

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import CONF_API_TOKEN
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ConfigEntryAuthFailed
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed
from homeassistant.util import dt as dt_util

from .const import (
    CONF_CHARGE_HOURS,
    CONF_FORECAST_HOURS,
    DEFAULT_CHARGE_HOURS,
    DEFAULT_FORECAST_HOURS,
    DOMAIN,
    NED_API_BASE,
    NED_API_TIMEOUT,
    TYPE_CONSUMPTION,
    TYPE_SOLAR,
    TYPE_WIND_OFFSHORE,
    TYPE_WIND_ONSHORE,
    UPDATE_INTERVAL_MINUTES,
)

_LOGGER = logging.getLogger(__name__)


class NEDEPEXCoordinator(DataUpdateCoordinator[dict[str, Any]]):
    """Class to manage fetching NED and EPEX data."""

    def __init__(self, hass: HomeAssistant, entry: ConfigEntry) -> None:
        """Initialize the coordinator."""
        super().__init__(
            hass,
            _LOGGER,
            name=DOMAIN,
            update_interval=timedelta(minutes=UPDATE_INTERVAL_MINUTES),
        )
        self.api_token: str = entry.data[CONF_API_TOKEN]
        self.charge_hours: int = entry.options.get(
            CONF_CHARGE_HOURS, DEFAULT_CHARGE_HOURS
        )
        self.forecast_hours: int = entry.options.get(
            CONF_FORECAST_HOURS, DEFAULT_FORECAST_HOURS
        )
        self._session: aiohttp.ClientSession | None = None

    async def _async_update_data(self) -> dict[str, Any]:
        """Fetch data from NED API."""
        try:
            # Fetch alle sensor types parallel
            wind_onshore, wind_offshore, solar, consumption = await asyncio.gather(
                self._fetch_sensor_data(TYPE_WIND_ONSHORE, "Wind Onshore"),
                self._fetch_sensor_data(TYPE_WIND_OFFSHORE, "Wind Offshore"),
                self._fetch_sensor_data(TYPE_SOLAR, "Solar"),
                self._fetch_sensor_data(TYPE_CONSUMPTION, "Consumption"),
            )

            # Sla individuele sensor data op
            data: dict[str, Any] = {
                "wind_onshore": wind_onshore,
                "wind_offshore": wind_offshore,
                "solar": solar,
                "consumption": consumption,
            }

            # Combineer tot forecast met restlast
            ned_data = self._combine_to_forecast(
                wind_onshore, wind_offshore, solar, consumption
            )
            data["ned_data"] = ned_data

            # Bereken EPEX prijzen
            price_forecast = self._calculate_epex_prices(ned_data["forecast"])
            data["price_forecast"] = price_forecast

            # Bereken charge advice
            charge_advice = self._calculate_charge_advice(price_forecast)
            data["charge_advice"] = charge_advice

            _LOGGER.debug(
                "Successfully fetched NED data: %d forecast points, %d charge windows",
                len(ned_data["forecast"]),
                len(charge_advice.get("windows", [])),
            )

            return data

        except ConfigEntryAuthFailed:
            raise
        except aiohttp.ClientError as err:
            _LOGGER.exception("Connection error fetching NED data")
            raise UpdateFailed(f"Connection error: {err}") from err
        except Exception as err:
            _LOGGER.exception("Failed to fetch NED data")
            raise UpdateFailed(f"Failed to fetch NED data: {err}") from err

    async def _fetch_sensor_data(
        self, type_id: int, name: str
    ) -> list[dict[str, Any]]:
        """Fetch data for one sensor type volgens officiële NED API spec."""
        if self._session is None:
            self._session = aiohttp.ClientSession()

        headers = {"X-AUTH-TOKEN": self.api_token}
        now = datetime.now()
        start_date = now.strftime("%Y-%m-%d")
        
        # Bereken hoeveel dagen we nodig hebben
        days_ahead = max(2, (self.forecast_hours // 24) + 1)
        end_date = (now + timedelta(days=days_ahead)).strftime("%Y-%m-%d")

        # Parameters volgens officiële API spec
        params = {
            "point": 0,  # 0 = Nederland
            "type": type_id,
            "granularity": 5,  # 5 = Hourly
            "granularitytimezone": 1,  # 1 = Europe/Amsterdam
            "classification": 2,  # 2 = Forecast
            "activity": 1,  # 1 = Providing
            "validfrom[after]": start_date,
            "validfrom[strictly_before]": end_date,
            "itemsPerPage": 200,  # Max 200 volgens API spec
        }

        try:
            url = f"{NED_API_BASE}/utilizations"
            async with self._session.get(
                url,
                headers=headers,
                params=params,
                timeout=aiohttp.ClientTimeout(total=NED_API_TIMEOUT),
            ) as response:
                if response.status in (401, 403):
                    raise ConfigEntryAuthFailed(f"Authentication failed for {name}")
                if response.status != 200:
                    error_text = await response.text()
                    raise UpdateFailed(
                        f"Error fetching {name} data: {response.status}, {error_text}"
                    )

                data = await response.json()
                records = data.get("hydra:member", [])

                if not records:
                    _LOGGER.warning("No data returned for %s", name)
                    return []

                # Parse volgens API spec: capacity is in kW (kilowatts)
                parsed = []
                for record in records:
                    # API geeft capacity in kW, converteer naar GW
                    capacity_kw = float(record.get("capacity", 0))
                    capacity_gw = capacity_kw / 1_000_000.0  # kW → GW

                    timestamp_str = record.get("validfrom")
                    timestamp = dt_util.parse_datetime(timestamp_str)

                    if timestamp:
                        parsed.append({
                            "capacity": capacity_gw,
                            "timestamp": timestamp,
                        })

                # Sorteer op timestamp
                parsed.sort(key=lambda x: x["timestamp"])
                
                _LOGGER.debug(
                    "Fetched %d records for %s (current: %.2f GW)",
                    len(parsed),
                    name,
                    parsed[0]["capacity"] if parsed else 0,
                )
                
                return parsed

        except aiohttp.ClientError as err:
            raise UpdateFailed(f"Connection error fetching {name}: {err}") from err
        except Exception as err:
            raise UpdateFailed(f"Failed to parse {name} data: {err}") from err

    def _combine_to_forecast(
        self,
        wind_on: list[dict[str, Any]],
        wind_off: list[dict[str, Any]],
        solar: list[dict[str, Any]],
        consumption: list[dict[str, Any]],
    ) -> dict[str, Any]:
        """Combineer alle sensoren tot één forecast-dict."""
        # Maak dict met timestamp als key
        combined: dict[datetime, dict[str, Any]] = {}

        # Voeg wind onshore toe
        for record in wind_on:
            ts = record["timestamp"]
            combined[ts] = {
                "timestamp": ts,
                "wind_onshore_gw": record["capacity"],
            }

        # Voeg wind offshore toe
        for record in wind_off:
            ts = record["timestamp"]
            if ts in combined:
                combined[ts]["wind_offshore_gw"] = record["capacity"]
            else:
                combined[ts] = {
                    "timestamp": ts,
                    "wind_offshore_gw": record["capacity"],
                }

        # Voeg solar toe
        for record in solar:
            ts = record["timestamp"]
            if ts in combined:
                combined[ts]["solar_gw"] = record["capacity"]
            else:
                combined[ts] = {
                    "timestamp": ts,
                    "solar_gw": record["capacity"],
                }

        # Voeg consumption toe
        for record in consumption:
            ts = record["timestamp"]
            if ts in combined:
                combined[ts]["consumption_gw"] = record["capacity"]
            else:
                combined[ts] = {
                    "timestamp": ts,
                    "consumption_gw": record["capacity"],
                }

        # Bereken restlast (alleen voor complete records)
        forecast = []
        for ts, vals in sorted(combined.items()):
            # Check of alle waardes aanwezig zijn
            if all(
                k in vals
                for k in [
                    "wind_onshore_gw",
                    "wind_offshore_gw",
                    "solar_gw",
                    "consumption_gw",
                ]
            ):
                total_renewable = (
                    vals["wind_onshore_gw"]
                    + vals["wind_offshore_gw"]
                    + vals["solar_gw"]
                )
                vals["restlast_gw"] = vals["consumption_gw"] - total_renewable
                forecast.append(vals)

        _LOGGER.debug(
            "Combined forecast: %d complete records from %s to %s",
            len(forecast),
            forecast[0]["timestamp"] if forecast else "N/A",
            forecast[-1]["timestamp"] if forecast else "N/A",
        )

        return {"forecast": forecast}

    def _calculate_epex_prices(
        self, forecast: list[dict[str, Any]]
    ) -> list[dict[str, Any]]:
        """
        Bereken geschatte EPEX prijzen op basis van restlast.
        
        Simpele formule: hogere restlast = hogere prijs.
        """
        price_forecast = []

        # Basis prijs (€/MWh)
        base_price = 50.0

        # Factor: hoeveel de prijs stijgt per GW restlast
        price_per_gw = 10.0

        for record in forecast:
            restlast_gw = record.get("restlast_gw", 0)
            
            # Simpele lineaire formule
            estimated_price = base_price + (restlast_gw * price_per_gw)
            
            # Clamp tussen 0 en 200 €/MWh
            estimated_price = max(0, min(200, estimated_price))

            price_forecast.append({
                "timestamp": record["timestamp"],
                "price": round(estimated_price, 2),
                "restlast_gw": restlast_gw,
            })

        return price_forecast

    def _calculate_charge_advice(
        self, price_forecast: list[dict[str, Any]]
    ) -> dict[str, Any]:
        """Bereken de beste charge windows op basis van prijzen."""
        if not price_forecast:
            return {"windows": [], "next_window": None, "average_price": None}

        # Sorteer op prijs (laagste eerst)
        sorted_by_price = sorted(price_forecast, key=lambda x: x["price"])

        # Neem de goedkoopste N uren
        cheapest_hours = sorted_by_price[: self.charge_hours]

        # Sorteer terug op timestamp
        cheapest_hours.sort(key=lambda x: x["timestamp"])

        # Groepeer in aaneengesloten windows
        windows = []
        current_window = []

        for hour in cheapest_hours:
            if not current_window:
                current_window.append(hour)
            else:
                # Check of dit uur aansluit op het vorige
                last_ts = current_window[-1]["timestamp"]
                if hour["timestamp"] == last_ts + timedelta(hours=1):
                    current_window.append(hour)
                else:
                    # Start nieuw window
                    windows.append(self._window_summary(current_window))
                    current_window = [hour]

        # Voeg laatste window toe
        if current_window:
            windows.append(self._window_summary(current_window))

        # Bepaal next window (eerste window in de toekomst)
        now = dt_util.now()
        next_window = None
        for window in windows:
            if window["start"] > now:
                next_window = window
                break

        # Bereken gemiddelde prijs
        avg_price = sum(h["price"] for h in cheapest_hours) / len(cheapest_hours)

        return {
            "windows": windows,
            "next_window": next_window,
            "average_price": round(avg_price, 2),
        }

    def _window_summary(self, hours: list[dict[str, Any]]) -> dict[str, Any]:
        """Maak samenvatting van een charge window."""
        start = hours[0]["timestamp"]
        end = hours[-1]["timestamp"] + timedelta(hours=1)
        avg_price = sum(h["price"] for h in hours) / len(hours)

        return {
            "start": start,
            "end": end,
            "duration_hours": len(hours),
            "average_price": round(avg_price, 2),
            "prices": [h["price"] for h in hours],
        }

    async def async_close(self) -> None:
        """Close the aiohttp session."""
        if self._session:
            await self._session.close()
            self._session = None
