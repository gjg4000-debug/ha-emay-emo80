"""Config flow for the EMAY EMO-80 pulse oximeter integration."""

from __future__ import annotations

import re
from typing import Any

import voluptuous as vol

from homeassistant import config_entries
from homeassistant.helpers.device_registry import format_mac

from .const import CONF_ADDRESS, DEFAULT_NAME, DOMAIN

MAC_RE = re.compile(r"^([0-9A-Fa-f]{2}[:-]){5}[0-9A-Fa-f]{2}$")

STEP_USER_SCHEMA = vol.Schema({vol.Required(CONF_ADDRESS): str})


class EmayEmo80ConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    VERSION = 1

    async def async_step_user(self, user_input: dict[str, Any] | None = None):
        errors: dict[str, str] = {}
        if user_input is not None:
            raw = user_input[CONF_ADDRESS].strip()
            if not MAC_RE.match(raw):
                errors[CONF_ADDRESS] = "invalid_address"
            else:
                address = format_mac(raw)
                await self.async_set_unique_id(address)
                self._abort_if_unique_id_configured()
                return self.async_create_entry(
                    title=DEFAULT_NAME,
                    data={CONF_ADDRESS: address},
                )

        return self.async_show_form(
            step_id="user", data_schema=STEP_USER_SCHEMA, errors=errors
        )
