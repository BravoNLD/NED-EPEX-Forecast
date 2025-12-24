"""DataUpdateCoordinator for NED EPEX Forecast."""
from __future__ import annotations

import logging
from datetime import datetime, timedelta
from typing import Any

import aiohttp
from homeassistant.core import HomeAssistant
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed
from homeassistant.exceptions import ConfigEntryAuthFailed

from .const import (
    DOMAIN,
    DEFAULT_MULTIPLIER,
    DEFAULT_OFFSET,
    NED_API_BASE,
    UPDATE_INTERVAL,
)

_LOGGER = logging.getLogger(__name__)


class NEDEPEXCoordinator(DataUpdateCoordinator):
    """Class to manage fetching NED data from the API."""

    def __init__(
        self,
        hass: HomeAssistant,
        api_token: str,
        epex_multiplier: float = DEFAULT_MULTIPLIER,
        epex_offset: float = DEFAULT_OFFSET,
    ) -> None:
        """Initialize the coordinator."""
        super().__init__(
            hass,
            _LOGGER,
            name=DOMAIN,
            update_interval=UPDATE_INTERVAL,
        )
        self.api_token = api_token
        self.epex_multiplier = epex_multiplier
        self.epex_offset = epex_offset
        self._session: aiohttp.ClientSession | None = None

    async def _async_update_data(self) -> dict[str, Any]:
        """Fetch data from NED API."""
        try:
            # Haal solar, wind en restlast data op
            solar_data = await self._fetch_ned_data(type_id=2, name="Solar")
            wind_data = await self._fetch_ned_data(type_id=1, name="Wind")
            restlast_data = await self._fetch_ned_data(type_id=5, name="Restlast")

            # Bereken EPEX prijzen op basis van restlast
            epex_prices = self._calculate_epex_prices(restlast_data)

            return {
                "solar": solar_data,
                "wind": wind_data,
                "restlast": restlast_data,
                "epex_prices": epex_prices,
                "last_update": datetime.now().isoformat(),
            }

        except ConfigEntryAuthFailed:
            raise
        except UpdateFailed:
            raise
        except aiohttp.ClientError as err:
            _LOGGER.exception("Connection error fetching NED data")
            raise UpdateFailed(f"Connection error: {err}") from err
        except Exception as err:
            _LOGGER.exception("Failed to fetch NED data")
            raise UpdateFailed(f"Failed to fetch NED data: {err}") from err

    # pylint: disable=too-many-locals
    async def _fetch_ned_data(
        self,
        type_id: int,
        name: str,
        days_ahead: int = 2,
    ) -> list[dict[str, Any]]:
        """Fetch data from NED API for a specific type.

        Args:
            type_id: NED type (1=Wind, 2=Solar, 5=Restlast)
            name: Name for logging
            days_ahead: Number of days to fetch
        """
        if self._session is None:
            self._session = aiohttp.ClientSession()

        headers = {"X-AUTH-TOKEN": self.api_token}

        # Datum range
        now = datetime.now()
        start_date = now.strftime("%Y-%m-%d")
        end_date = (now + timedelta(days=days_ahead)).strftime("%Y-%m-%d")

        params = {
            "point": 0,
            "type": type_id,
            "granularity": 5,
            "granularitytimezone": 1,
            "classification": 2,
            "activity": 1,
            "validfrom[after]": start_date,
            "validfrom[strictly_before]": end_date,
        }

        try:
            url = f"{NED_API_BASE}/utilizations"

            async with self._session.get(
                url,
                headers=headers,
                params=params,
                timeout=aiohttp.ClientTimeout(total=30),
            ) as response:
                if response.status in (401, 403):
                    raise ConfigEntryAuthFailed(f"Authentication failed for {name}")

                if response.status != 200:
                    error_text = await response.text()
                    raise UpdateFailed(
                        f"Error fetching {name} data: {response.status}, {error_text}"
                    )

                data = await response.json()

                # Verwerk de response
                records = data.get("hydra:member", [])

                _LOGGER.debug(
                    "Fetched %d records for %s from %s to %s",
                    len(records),
                    name,
                    start_date,
                    end_date,
                )

                # Converteer naar een handiger formaat
                processed_data = []
                for record in records:
                    processed_data.append({
                        "timestamp": record.get("validfrom"),
                        "value": float(record.get("volume", 0)),
                        "unit": record.get("unit", "MW"),
                    })

                return processed_data

        except aiohttp.ClientError as err:
            raise UpdateFailed(f"Connection error fetching {name} data: {err}") from err

    def _calculate_epex_prices(
        self,
        restlast_data: list[dict[str, Any]]
    ) -> list[dict[str, Any]]:
        """Calculate EPEX prices based on restlast data.

        Formula: EPEX = (multiplier * restlast_GW) + offset
        """
        epex_prices = []

        for record in restlast_data:
            restlast_mw = record["value"]
            restlast_gw = restlast_mw / 1000

            # Bereken EPEX prijs met configureerbare multiplier en offset
            epex_price = (self.epex_multiplier * restlast_gw) + self.epex_offset

            epex_prices.append({
                "timestamp": record["timestamp"],
                "price": round(epex_price, 2),
                "restlast_gw": round(restlast_gw, 3),
            })

        return epex_prices

    async def async_shutdown(self) -> None:
        """Close the session when shutting down."""
        if self._session:
            await self._session.close()
            self._session = None
