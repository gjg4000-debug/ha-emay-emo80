"""Sensors for the EMAY EMO-80 pulse oximeter integration."""

from __future__ import annotations

from homeassistant.components.sensor import SensorEntity, SensorStateClass
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity import DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from . import Emay80Coordinator
from .const import CONF_ADDRESS, DOMAIN
from .download import DownloadReport


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
    odi_sensor = Emo80OdiSensor(address, device_info)
    coordinator.odi_sensor = odi_sensor
    desat_sensor = Emo80DesatEventsSensor(address, device_info)
    coordinator.desat_sensor = desat_sensor
    async_add_entities(
        [
            Emo80Spo2Sensor(coordinator, address, device_info),
            Emo80PulseSensor(coordinator, address, device_info),
            Emo80LogSensor(coordinator, address, device_info),
            Emo80SummarySensor(coordinator, address, device_info),
            Emo80MeasurementsSensor(coordinator, address, device_info),
            odi_sensor,
            desat_sensor,
        ]
    )


class _Emo80SensorBase(CoordinatorEntity[Emay80Coordinator], SensorEntity):
    _attr_has_entity_name = True

    def __init__(
        self, coordinator: Emay80Coordinator, address: str, device_info: DeviceInfo
    ) -> None:
        super().__init__(coordinator)
        self._address = address
        self._attr_device_info = device_info
        self._attr_unique_id = f"{address}_{self._key}"
        self._attr_name = self._label

    _key = "base"
    _label = "Base"

    @property
    def _report(self) -> DownloadReport | None:
        return self.coordinator.data


class Emo80Spo2Sensor(_Emo80SensorBase):
    _key = "spo2"
    _label = "SpO2"
    _attr_native_unit_of_measurement = "%"
    _attr_state_class = SensorStateClass.MEASUREMENT
    _attr_icon = "mdi:blood-bag"

    @property
    def native_value(self) -> float | None:
        report = self._report
        return report.last_spo2 if report and report.last_spo2 else None


class Emo80PulseSensor(_Emo80SensorBase):
    _key = "pulse_rate"
    _label = "Pulse Rate"
    _attr_native_unit_of_measurement = "bpm"
    _attr_state_class = SensorStateClass.MEASUREMENT
    _attr_icon = "mdi:heart-pulse"

    @property
    def native_value(self) -> float | None:
        report = self._report
        return report.last_bpm if report and report.last_bpm else None


class Emo80LogSensor(_Emo80SensorBase):
    _key = "download_log"
    _label = "Download Log"
    _attr_icon = "mdi:file-document"
    _attr_entity_registry_enabled_default = False

    @property
    def native_value(self) -> str | None:
        report = self._report
        if not report:
            return None
        return report.log[-255:]

    @property
    def extra_state_attributes(self) -> dict:
        report = self._report
        return {"full_log": report.log} if report else {}


class Emo80SummarySensor(_Emo80SensorBase):
    _key = "download_summary"
    _label = "Download Summary"
    _attr_icon = "mdi:clipboard-text-multiple"

    @property
    def native_value(self) -> str | None:
        report = self._report
        if not report:
            return None
        return f"{len(report.sessions)} session(s)"

    @property
    def extra_state_attributes(self) -> dict:
        report = self._report
        return {"summary": report.summary} if report else {}


class Emo80OdiSensor(SensorEntity):
    """Latest night's estimated Oxygen Desaturation Index (4% threshold).

    This is a hobbyist approximation of the standard clinical scoring
    method, not a certified diagnostic value -- see odi.py. Full hourly
    history lives in long-term statistics (sensor.emo_80_desat_events);
    this entity shows the latest night's summary as a live state."""

    _attr_has_entity_name = True
    _attr_icon = "mdi:lungs"
    _attr_state_class = SensorStateClass.MEASUREMENT
    _attr_native_unit_of_measurement = "events/h"

    def __init__(self, address: str, device_info: DeviceInfo) -> None:
        self._attr_device_info = device_info
        self._attr_unique_id = f"{address}_odi"
        self._attr_name = "Estimated ODI"
        self._attr_native_value: float | None = None
        self._attr_extra_state_attributes: dict = {}

    def set_summary(self, odi3: dict, odi4: dict) -> None:
        self._attr_native_value = odi4["odi"]
        self._attr_extra_state_attributes = {
            "odi_3pct": odi3["odi"],
            "odi_3pct_event_count": odi3["event_count"],
            "odi_4pct": odi4["odi"],
            "odi_4pct_event_count": odi4["event_count"],
            "valid_hours": odi4["valid_hours"],
        }
        self.async_write_ha_state()


class Emo80DesatEventsSensor(SensorEntity):
    """Last imported night's desaturation-event count (4% threshold).

    Gives the sensor.emo_80_desat_events statistic_id a real registered
    entity so the graph card and other entity pickers can resolve it."""

    _attr_has_entity_name = True
    _attr_icon = "mdi:lungs"
    _attr_state_class = SensorStateClass.MEASUREMENT
    _attr_native_unit_of_measurement = "events"

    def __init__(self, address: str, device_info: DeviceInfo) -> None:
        self._attr_device_info = device_info
        self._attr_unique_id = f"{address}_desat_events"
        self._attr_name = "Desat Events"
        self._attr_native_value: int | None = None

    def set_value(self, event_count: int) -> None:
        self._attr_native_value = event_count
        self.async_write_ha_state()


class Emo80MeasurementsSensor(_Emo80SensorBase):
    _key = "measurements"
    _label = "Measurements"
    _attr_icon = "mdi:heart-pulse"

    @property
    def native_value(self) -> str | None:
        report = self._report
        if not report or not report.sessions:
            return None
        last = report.sessions[-1]
        return f"serial={last.serial} datetime={last.datetime_str}"

    @property
    def extra_state_attributes(self) -> dict:
        report = self._report
        if not report or not report.sessions:
            return {}
        last = report.sessions[-1]
        return {
            "serial": last.serial,
            "datetime": last.datetime_str,
            "duration_s": last.duration_s,
            "spo2_points": last.spo2_points,
            "bpm_points": last.bpm_points,
        }
