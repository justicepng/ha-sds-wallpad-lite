"""Climate platform for Samsung SDS Wallpad Lite."""
from __future__ import annotations

import logging
from typing import Any

from homeassistant.components.climate import (
    ClimateEntity,
    ClimateEntityFeature,
    HVACMode,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import ATTR_TEMPERATURE, UnitOfTemperature
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity import DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import DOMAIN, ROOM_NAMES
from .hub import SDSWallpadHub

_LOGGER = logging.getLogger(__name__)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up the Samsung SDS Wallpad Lite climate entities."""
    hub: SDSWallpadHub = hass.data[DOMAIN][entry.entry_id]

    entities = [
        SDSThermostat(hub, room_id, entry)
        for room_id in range(1, 6)
    ]
    async_add_entities(entities)


class SDSThermostat(ClimateEntity):
    """Representation of a Samsung SDS Wallpad Thermostat."""

    _attr_has_entity_name = False
    _attr_temperature_unit = UnitOfTemperature.CELSIUS
    _attr_hvac_modes = [HVACMode.OFF, HVACMode.HEAT]
    _attr_min_temp = 10.0
    _attr_max_temp = 30.0
    _attr_target_temp_step = 1.0
    _attr_supported_features = (
        ClimateEntityFeature.TARGET_TEMPERATURE
        | ClimateEntityFeature.TURN_ON
        | ClimateEntityFeature.TURN_OFF
    )

    def __init__(self, hub: SDSWallpadHub, room_id: int, entry: ConfigEntry) -> None:
        """Initialize the thermostat entity."""
        self._hub = hub
        self._room_id = room_id
        self._entry = entry

        room_name = ROOM_NAMES.get(room_id, f"방 {room_id}")
        self._attr_name = f"{room_name} 난방"
        self._attr_unique_id = f"sds_wallpad_sds_thermostat_{room_id}"
        self.entity_id = f"climate.sds_wallpad_sds_thermostat_{room_id}"

        # Initial state from hub
        state = self._hub.thermostat_states.get(room_id, {})
        self._attr_hvac_mode = HVACMode.HEAT if state.get("power", False) else HVACMode.OFF
        self._attr_target_temperature = state.get("target", 22.0)
        self._attr_current_temperature = state.get("current", 22.0)

    @property
    def device_info(self) -> DeviceInfo:
        """Return device information."""
        return DeviceInfo(
            identifiers={(DOMAIN, "sds_wallpad")},
            name="SDS월패드",
            manufacturer="Samsung SDS",
            model="Samsung SDS Wallpad",
        )

    async def async_added_to_hass(self) -> None:
        """Register callbacks when added to Home Assistant."""
        self._hub.register_thermostat_callback(self._room_id, self._on_state_update)

    def _on_state_update(self, power_on: bool, target_temp: float, current_temp: float) -> None:
        """Handle state update from hub."""
        self._attr_hvac_mode = HVACMode.HEAT if power_on else HVACMode.OFF
        self._attr_target_temperature = target_temp
        self._attr_current_temperature = current_temp
        self.async_write_ha_state()

    async def async_set_hvac_mode(self, hvac_mode: HVACMode) -> None:
        """Set new target hvac mode."""
        if hvac_mode == HVACMode.HEAT:
            await self._hub.async_send_thermostat_power(self._room_id, True)
            self._attr_hvac_mode = HVACMode.HEAT
        elif hvac_mode == HVACMode.OFF:
            await self._hub.async_send_thermostat_power(self._room_id, False)
            self._attr_hvac_mode = HVACMode.OFF
        self.async_write_ha_state()

    async def async_set_temperature(self, **kwargs: Any) -> None:
        """Set new target temperature."""
        target_temp = kwargs.get(ATTR_TEMPERATURE)
        if target_temp is not None:
            await self._hub.async_send_thermostat_target_temp(self._room_id, target_temp)
            self._attr_target_temperature = target_temp
            self.async_write_ha_state()
