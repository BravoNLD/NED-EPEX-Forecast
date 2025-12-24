"""The NED EPEX Forecast integration."""
from __future__ import annotations

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant

from .const import DOMAIN, CONF_API_TOKEN, CONF_EPEX_MULTIPLIER, CONF_EPEX_OFFSET
from .coordinator import NEDEPEXCoordinator

PLATFORMS: list[str] = ["sensor"]


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Set up NED EPEX Forecast from a config entry."""
    api_token = entry.data[CONF_API_TOKEN]
    multiplier = entry.data.get(CONF_EPEX_MULTIPLIER, 1.27)
    offset = entry.data.get(CONF_EPEX_OFFSET, 1.5)

    coordinator = NEDEPEXCoordinator(
        hass,
        api_token,
        multiplier,
        offset
    )

    await coordinator.async_config_entry_first_refresh()

    hass.data.setdefault(DOMAIN, {})
    hass.data[DOMAIN][entry.entry_id] = coordinator

    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)

    return True


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Unload a config entry."""
    unload_ok = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)

    if unload_ok:
        coordinator = hass.data[DOMAIN].pop(entry.entry_id)
        await coordinator.async_shutdown()

    return unload_ok
