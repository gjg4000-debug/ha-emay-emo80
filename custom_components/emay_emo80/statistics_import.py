"""Backfill long-term statistics for each downloaded session.

The download gives us a full array of per-sample SpO2/BPM readings with a
known start time and duration, but recorder statistics only support hourly
buckets. We bucket each session's points by hour and import them via
async_import_statistics so the sensors' native history graphs (including the
"Show more" expand dialog) show the actual overnight trend, not just the
single latest-reading state.
"""

from __future__ import annotations

from datetime import datetime, timedelta
import logging

from homeassistant.components.recorder.statistics import (
    StatisticData,
    StatisticMetaData,
    async_import_statistics,
)
from homeassistant.core import HomeAssistant
from homeassistant.util import dt as dt_util

from .download import SessionResult

_LOGGER = logging.getLogger(__name__)


def _hourly_buckets(
    points: list[float], start_utc: datetime, duration_s: int
) -> list[StatisticData]:
    n = len(points)
    if n < 2 or duration_s <= 0:
        return []
    interval_s = duration_s / (n - 1)
    buckets: dict[datetime, list[float]] = {}
    for i, v in enumerate(points):
        if v <= 0:
            continue
        t = start_utc + timedelta(seconds=i * interval_s)
        bucket_start = t.replace(minute=0, second=0, microsecond=0)
        buckets.setdefault(bucket_start, []).append(v)
    return [
        StatisticData(
            start=bucket_start,
            mean=sum(vals) / len(vals),
            min=min(vals),
            max=max(vals),
        )
        for bucket_start, vals in sorted(buckets.items())
    ]


def import_hourly_series(
    hass: HomeAssistant,
    statistic_id: str,
    name: str,
    unit: str,
    hourly_data: list[tuple[datetime, float]],
) -> int:
    """Import a pre-bucketed (hour_start_utc, value) series as recorder statistics."""
    if not hourly_data:
        return 0
    stats = [
        StatisticData(start=start_utc, mean=value, min=value, max=value)
        for start_utc, value in sorted(hourly_data)
    ]
    async_import_statistics(
        hass,
        StatisticMetaData(
            has_mean=True,
            has_sum=False,
            name=name,
            source="recorder",
            statistic_id=statistic_id,
            unit_of_measurement=unit,
        ),
        stats,
    )
    return len(stats)


def import_odi_events(
    hass: HomeAssistant, start_utc: datetime, events: list[dict]
) -> int:
    """Bucket desaturation events by hour and import as recorder statistics."""
    hourly: dict[datetime, int] = {}
    for ev in events:
        t = start_utc + timedelta(seconds=ev["start_s"])
        bucket_start = t.replace(minute=0, second=0, microsecond=0)
        hourly[bucket_start] = hourly.get(bucket_start, 0) + 1
    return import_hourly_series(
        hass, "sensor.emo_80_desat_events", "Desaturation Events", "events",
        list(hourly.items()),
    )


def import_session_statistics(hass: HomeAssistant, session: SessionResult) -> None:
    """Import one session's SpO2/BPM points as hourly recorder statistics."""
    start_local = datetime.strptime(session.datetime_str, "%Y-%m-%d %H:%M:%S").replace(
        tzinfo=dt_util.DEFAULT_TIME_ZONE
    )
    start_utc = dt_util.as_utc(start_local)

    spo2_stats = _hourly_buckets(session.spo2_points, start_utc, session.duration_s)
    if spo2_stats:
        async_import_statistics(
            hass,
            StatisticMetaData(
                has_mean=True,
                has_sum=False,
                name="EMO-80 SpO2",
                source="recorder",
                statistic_id="sensor.emo_80_spo2",
                unit_of_measurement="%",
            ),
            spo2_stats,
        )
        _LOGGER.debug(
            "emay_emo80: imported %d hourly SpO2 stat buckets for session serial=%d",
            len(spo2_stats), session.serial,
        )

    bpm_stats = _hourly_buckets(session.bpm_points, start_utc, session.duration_s)
    if bpm_stats:
        async_import_statistics(
            hass,
            StatisticMetaData(
                has_mean=True,
                has_sum=False,
                name="EMO-80 Pulse Rate",
                source="recorder",
                statistic_id="sensor.emo_80_pulse_rate",
                unit_of_measurement="bpm",
            ),
            bpm_stats,
        )
        _LOGGER.debug(
            "emay_emo80: imported %d hourly BPM stat buckets for session serial=%d",
            len(bpm_stats), session.serial,
        )
