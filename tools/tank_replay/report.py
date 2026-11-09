"""The JSON summary of a replay and the optional per-tick CSV."""
from __future__ import annotations

import csv
from datetime import datetime
from pathlib import Path

from .models import parameter_values
from .scoring import inflow_events, value_at

PRESSURE_AFTER_INFLOW_S = 1800      # inflow events report the pressure this long after they end


def build_summary(*, series, frames, readings, result, pressure, params, overrides, utc_offset, local) -> dict:
    p_times = [t for t, _ in pressure]
    p_values = [v for _, v in pressure]

    def local_text(when: float) -> str:
        return datetime.fromtimestamp(when, local).strftime("%Y-%m-%d %H:%M")

    def pressure_near(when: float):
        return value_at(p_times, p_values, when)

    return {
        "files": series["files"],
        "start": local_text(frames[0][0]),
        "end": local_text(frames[-1][0]),
        "utc_offset_h": utc_offset,
        "frames": len(frames),
        "ticks": len(readings),
        "pressure_samples": len(pressure),
        "parameters": parameter_values(params),
        "overrides": overrides,
        **result,
        "surface_locked_pct": round(sum(1 for r in readings if r.surface_locked) / len(readings) * 100.0, 1),
        "final_level_pct": round(readings[-1].level_pct, 2),
        "inflows": [
            {
                "start": local_text(start),
                "end": local_text(stop),
                "peak_lpm": round(peak, 1),
                "pressure_before_hpa": pressure_near(start),
                "pressure_after_hpa": pressure_near(stop + PRESSURE_AFTER_INFLOW_S),
            }
            for start, stop, peak in inflow_events(readings)
        ],
    }


def write_ticks(path: Path, readings, pressure, local) -> None:
    """Every published tick, in local time, with the pressure reading in force at that moment."""
    p_times = [t for t, _ in pressure]
    p_values = [v for _, v in pressure]
    with open(path, "w", newline="", encoding="utf-8") as handle:
        writer = csv.writer(handle)
        writer.writerow(["Time", "LevelPct", "VolumeL", "NetFlowLpm", "FlowChangeLpm2", "SurfaceM", "SurfaceLocked", "PressureHpa"])
        for r in readings:
            hpa = value_at(p_times, p_values, r.time)
            writer.writerow([
                datetime.fromtimestamp(r.time, local).isoformat(timespec="seconds"),
                round(r.level_pct, 3), round(r.volume_l, 1), round(r.net_flow_lpm, 2), round(r.flow_change_lpm2, 3),
                round(r.surface_m, 4), int(r.surface_locked), "" if hpa is None else hpa,
            ])
