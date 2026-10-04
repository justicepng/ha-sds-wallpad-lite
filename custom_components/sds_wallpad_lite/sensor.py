"""Sensor platform for Samsung SDS Wallpad Lite."""
from __future__ import annotations

import logging

from homeassistant.components.sensor import (
    SensorDeviceClass,
    SensorEntity,
    SensorStateClass,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import UnitOfPower
from homeassistant.core import HomeAssistant
from homeassistant.helpers.restore_state import RestoreEntity
from homeassistant.helpers.entity import DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import DOMAIN
from .hub import SDSWallpadHub

_LOGGER = logging.getLogger(__name__)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up the Samsung SDS Wallpad Lite sensor entities."""
    hub: SDSWallpadHub = hass.data[DOMAIN][entry.entry_id]

    async_add_entities([SDSPowerConsumptionSensor(hub, entry)])


class SDSPowerConsumptionSensor(RestoreEntity, SensorEntity):
    """Representation of the SDS Wallpad Real-time Power Consumption Sensor."""

    _attr_has_entity_name = False
    _attr_device_class = SensorDeviceClass.POWER
    _attr_state_class = SensorStateClass.MEASUREMENT
    _attr_native_unit_of_measurement = UnitOfPower.WATT

    def __init__(self, hub: SDSWallpadHub, entry: ConfigEntry) -> None:
        """Initialize the power consumption sensor."""
        self._hub = hub
        self._entry = entry

        self._attr_name = "SDS월패드 전기 사용량"
        self._attr_unique_id = "sds_wallpad_sds_power_consumption"
        self.entity_id = "sensor.sds_wallpad_sds_power_consumption"
        self._attr_native_value = self._hub.power_consumption

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
        """Register callback when added to Home Assistant."""
        await super().async_added_to_hass()
        last_state = await self.async_get_last_state()
        if last_state and last_state.state not in (None, "unknown", "unavailable"):
            try:
                val = float(last_state.state)
                if val > 0.0:
                    self._attr_native_value = val
                    self._hub.power_consumption = val
            except ValueError:
                pass
        self._hub.register_power_callback(self._on_power_update)

    def _on_power_update(self, watt: float) -> None:
        """Handle power update from hub."""
        self._attr_native_value = watt
        self.async_write_ha_state()
