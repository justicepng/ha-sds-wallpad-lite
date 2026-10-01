"""The Samsung SDS Wallpad Lite integration."""
from __future__ import annotations

import logging

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import Platform
from homeassistant.core import HomeAssistant

from .const import CONF_HOST, CONF_PORT, CONF_POWER_DECIMAL, DEFAULT_HOST, DEFAULT_PORT, DEFAULT_POWER_DECIMAL, DOMAIN
from .hub import SDSWallpadHub

_LOGGER = logging.getLogger(__name__)

PLATFORMS: list[Platform] = [Platform.CLIMATE, Platform.SENSOR]


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Set up Samsung SDS Wallpad Lite from a config entry."""
    host = entry.data.get(CONF_HOST, DEFAULT_HOST)
    port = entry.data.get(CONF_PORT, DEFAULT_PORT)
    power_decimal = entry.data.get(CONF_POWER_DECIMAL, DEFAULT_POWER_DECIMAL)

    hub = SDSWallpadHub(host=host, port=port, power_decimal=power_decimal)
    await hub.start()

    hass.data.setdefault(DOMAIN, {})[entry.entry_id] = hub

    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)

    entry.async_on_unload(entry.add_update_listener(async_reload_entry))
    return True


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Unload a config entry."""
    unload_ok = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
    if unload_ok:
        hub: SDSWallpadHub = hass.data[DOMAIN].pop(entry.entry_id)
        await hub.stop()

    return unload_ok


async def async_reload_entry(hass: HomeAssistant, entry: ConfigEntry) -> None:
    """Reload config entry."""
    await async_unload_entry(hass, entry)
    await async_setup_entry(hass, entry)
