"""Button to trigger an EMO-80 download."""

from __future__ import annotations

from homeassistant.components.button import ButtonEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity import DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from . import Emay80Coordinator
from .const import CONF_ADDRESS, DOMAIN


async def async_setup_entry(
    hass: HomeAssistant, entry: ConfigEntry, async_add_entities: AddEntitiesCallback
) -> None:
    coordinator: Emay80Coordinator = hass.data[DOMAIN][entry.entry_id]
    address = entry.data[CONF_ADDRESS]
    device_info = DeviceInfo(
        identifiers={(DOMAIN, address)},
        name="EMO-80",
        manufacturer="EMAY",
        model="EMO-80",
    )
    async_add_entities([Emo80DownloadAllButton(coordinator, address, device_info)])


class Emo80DownloadAllButton(ButtonEntity):
    _attr_has_entity_name = True
    _attr_name = "Download All"
    _attr_icon = "mdi:bluetooth-transfer"

    def __init__(
        self, coordinator: Emay80Coordinator, address: str, device_info: DeviceInfo
    ) -> None:
        self._coordinator = coordinator
        self._attr_device_info = device_info
        self._attr_unique_id = f"{address}_download_all"

    async def async_press(self) -> None:
        await self._coordinator.async_request_download()
