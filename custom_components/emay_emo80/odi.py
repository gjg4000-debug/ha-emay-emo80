"""Oxygen Desaturation Index (ODI) estimation from raw per-sample SpO2 data.

This is a hobbyist approximation of the standard clinical scoring method
(AASM-style: an event is a drop of >= threshold_pct from a local rolling
baseline, sustained for at least min_event_s seconds), NOT a certified
diagnostic algorithm. It requires the full per-sample SpO2 stream -- the
hourly min/mean/max statistics saved for graphing are not sufficient,
since a single hour's min/max can't distinguish one big dip from several
small ones.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass
class DesatEvent:
    start_s: float
    end_s: float
    baseline: float
    nadir: float

    @property
    def drop_pct(self) -> float:
        return self.baseline - self.nadir


def compute_odi(
    spo2_points: list[float],
    duration_s: float,
    threshold_pct: float = 4.0,
    baseline_window_s: float = 100.0,
    min_event_s: float = 10.0,
) -> dict:
    n = len(spo2_points)
    if n < 2 or duration_s <= 0:
        return {"odi": 0.0, "event_count": 0, "valid_hours": 0.0, "events": []}

    interval_s = duration_s / (n - 1)
    baseline_window_n = max(int(baseline_window_s / interval_s), 1)

    # Rolling baseline = max valid SpO2 over the trailing window (a dip
    # can't lower its own baseline; the ceiling just before a drop is
    # what a desaturation is measured against).
    baselines: list[float] = []
    window: list[float] = []
    for v in spo2_points:
        if v > 0:
            window.append(v)
        if len(window) > baseline_window_n:
            window.pop(0)
        baselines.append(max(window) if window else 0.0)

    events: list[DesatEvent] = []
    in_event = False
    event_start_i = 0
    event_baseline = 0.0
    event_nadir = 100.0
    valid_samples = 0

    def _close_event(end_i: int) -> None:
        duration = (end_i - event_start_i) * interval_s
        if duration >= min_event_s:
            events.append(
                DesatEvent(
                    start_s=event_start_i * interval_s,
                    end_s=end_i * interval_s,
                    baseline=event_baseline,
                    nadir=event_nadir,
                )
            )

    for i, v in enumerate(spo2_points):
        if v <= 0:
            continue
        valid_samples += 1
        baseline = baselines[i]
        if baseline <= 0:
            continue
        is_low = (baseline - v) >= threshold_pct
        if is_low and not in_event:
            in_event = True
            event_start_i = i
            event_baseline = baseline
            event_nadir = v
        elif is_low and in_event:
            event_nadir = min(event_nadir, v)
        elif not is_low and in_event:
            _close_event(i)
            in_event = False

    if in_event:
        _close_event(n - 1)

    valid_hours = (valid_samples * interval_s) / 3600.0
    odi = len(events) / valid_hours if valid_hours > 0 else 0.0

    return {
        "odi": round(odi, 1),
        "event_count": len(events),
        "valid_hours": round(valid_hours, 2),
        "events": [
            {
                "start_s": round(e.start_s, 1),
                "end_s": round(e.end_s, 1),
                "baseline": e.baseline,
                "nadir": e.nadir,
                "drop_pct": round(e.drop_pct, 1),
            }
            for e in events
        ],
    }
