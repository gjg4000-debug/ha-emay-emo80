"""The EMAY EMO-80 pulse oximeter integration."""

from __future__ import annotations

from datetime import datetime
import logging

from bleak_retry_connector import BleakClientWithServiceCache, establish_connection

from homeassistant.components import bluetooth
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed
from homeassistant.util import dt as dt_util

from .const import CONF_ADDRESS, DOMAIN
from .download import DownloadReport, Emay80Client
from .odi import compute_odi
from .statistics_import import import_odi_events, import_session_statistics

_LOGGER = logging.getLogger(__name__)

PLATFORMS = ["sensor", "button"]


class Emay80Coordinator(DataUpdateCoordinator[DownloadReport]):
    """Push-only coordinator: data only changes when async_request_download() runs."""

    def __init__(self, hass: HomeAssistant, address: str) -> None:
        super().__init__(hass, _LOGGER, name=DOMAIN, update_interval=None)
        # bluetooth.async_ble_device_from_address/async_last_service_info key
        # their internal maps off the uppercase address bleak/BlueZ scanners
        # report, not the lowercase form the device registry (format_mac)
        # normalizes to; entry.data stores the lowercase form.
        self.address = address.upper()
        self.busy = False
        self.odi_sensor = None
        self.desat_sensor = None

    async def _async_update_data(self) -> DownloadReport:
        # Never called on a timer (update_interval=None); only via
        # async_request_download below, which calls async_set_updated_data
        # directly instead of going through the coordinator's refresh path.
        raise UpdateFailed("not used")

    def _score_odi(self, session) -> None:
        """CPU-only + recorder-import work -- must run on the event loop
        (async_import_statistics is not safe to call from a worker thread)."""
        start_local = datetime.strptime(session.datetime_str, "%Y-%m-%d %H:%M:%S").replace(
            tzinfo=dt_util.DEFAULT_TIME_ZONE
        )
        start_utc = dt_util.as_utc(start_local)

        odi3 = compute_odi(session.spo2_points, session.duration_s, threshold_pct=3)
        odi4 = compute_odi(session.spo2_points, session.duration_s, threshold_pct=4)
        n = import_odi_events(self.hass, start_utc, odi4["events"])
        _LOGGER.info(
            "emay_emo80: session serial=%d ODI3=%.1f (%d events) ODI4=%.1f (%d events) "
            "over %.2fh valid data, imported %d hourly desat buckets",
            session.serial, odi3["odi"], odi3["event_count"],
            odi4["odi"], odi4["event_count"], odi4["valid_hours"], n,
        )

        if self.odi_sensor is not None:
            self.odi_sensor.set_summary(odi3, odi4)
        if self.desat_sensor is not None:
            self.desat_sensor.set_value(odi4["event_count"])

    async def async_request_download(self) -> None:
        if self.busy:
            _LOGGER.warning("emay_emo80: download already in progress, ignoring request")
            return
        self.busy = True
        try:
            ble_device = bluetooth.async_ble_device_from_address(
                self.hass, self.address, connectable=True
            )
            if ble_device is None:
                raise HomeAssistantError(
                    f"EMO-80 ({self.address}) is not currently advertising / not seen by "
                    "any connectable Bluetooth adapter or proxy. Wake it (finger in, or "
                    "its button) and try again."
                )
            client = await establish_connection(
                BleakClientWithServiceCache, ble_device, f"EMO-80 ({self.address})"
            )
            try:
                emay = Emay80Client(client)
                await emay.start()
                try:
                    report = await emay.run_full_download()
                finally:
                    await emay.stop()
            finally:
                await client.disconnect()
            for session in report.sessions:
                import_session_statistics(self.hass, session)
                self._score_odi(session)
            self.async_set_updated_data(report)
        finally:
            self.busy = False


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    coordinator = Emay80Coordinator(hass, entry.data[CONF_ADDRESS])
    hass.data.setdefault(DOMAIN, {})[entry.entry_id] = coordinator
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    return True


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    unload_ok = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
    if unload_ok:
        hass.data[DOMAIN].pop(entry.entry_id)
    return unload_ok
