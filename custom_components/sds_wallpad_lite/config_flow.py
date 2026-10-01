"""Config flow for Samsung SDS Wallpad Lite integration."""
from __future__ import annotations

import asyncio
import logging
from typing import Any

import voluptuous as vol
from homeassistant import config_entries
from homeassistant.core import callback
from homeassistant.data_entry_flow import FlowResult

from .const import (
    CONF_HOST,
    CONF_PORT,
    CONF_POWER_DECIMAL,
    DEFAULT_HOST,
    DEFAULT_PORT,
    DEFAULT_POWER_DECIMAL,
    DOMAIN,
)

_LOGGER = logging.getLogger(__name__)


async def _validate_connection(host: str, port: int) -> bool:
    """Test TCP socket connection to EW11."""
    try:
        _, writer = await asyncio.wait_for(asyncio.open_connection(host, port), timeout=5.0)
        writer.close()
        await writer.wait_closed()
        return True
    except Exception as err:
        _LOGGER.warning("Connection test failed to %s:%s - %s", host, port, err)
        return False


class SDSWallpadConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    """Handle a config flow for Samsung SDS Wallpad Lite."""

    VERSION = 1

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        """Handle the initial step."""
        errors: dict[str, str] = {}

        if user_input is not None:
            # Check unique ID to prevent duplicate installations
            await self.async_set_unique_id(f"{user_input[CONF_HOST]}_{user_input[CONF_PORT]}")
            self._abort_if_unique_id_configured()

            # Test connection
            is_valid = await _validate_connection(user_input[CONF_HOST], user_input[CONF_PORT])
            if not is_valid:
                errors["base"] = "cannot_connect"
            else:
                return self.async_create_entry(
                    title=f"SDS Wallpad ({user_input[CONF_HOST]})",
                    data=user_input,
                )

        schema = vol.Schema(
            {
                vol.Required(CONF_HOST, default=DEFAULT_HOST): str,
                vol.Required(CONF_PORT, default=DEFAULT_PORT): int,
                vol.Required(CONF_POWER_DECIMAL, default=DEFAULT_POWER_DECIMAL): int,
            }
        )

        return self.async_show_form(
            step_id="user",
            data_schema=schema,
            errors=errors,
        )

    @staticmethod
    @callback
    def async_get_options_flow(
        config_entry: config_entries.ConfigEntry,
    ) -> config_entries.OptionsFlow:
        """Create options flow handler."""
        return SDSWallpadOptionsFlowHandler(config_entry)


class SDSWallpadOptionsFlowHandler(config_entries.OptionsFlow):
    """Handle options flow for Samsung SDS Wallpad Lite."""

    def __init__(self, config_entry: config_entries.ConfigEntry) -> None:
        """Initialize options flow."""
        self.config_entry = config_entry

    async def async_step_init(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        """Manage options."""
        if user_input is not None:
            # Update entry data
            self.hass.config_entries.async_update_entry(
                self.config_entry, data={**self.config_entry.data, **user_input}
            )
            return self.async_create_entry(title="", data=user_input)

        schema = vol.Schema(
            {
                vol.Required(
                    CONF_HOST,
                    default=self.config_entry.data.get(CONF_HOST, DEFAULT_HOST),
                ): str,
                vol.Required(
                    CONF_PORT,
                    default=self.config_entry.data.get(CONF_PORT, DEFAULT_PORT),
                ): int,
                vol.Required(
                    CONF_POWER_DECIMAL,
                    default=self.config_entry.data.get(
                        CONF_POWER_DECIMAL, DEFAULT_POWER_DECIMAL
                    ),
                ): int,
            }
        )

        return self.async_show_form(step_id="init", data_schema=schema)
