"""The JSON summary of a replay and the optional per-tick CSV."""
from __future__ import annotations

import csv
from datetime import datetime
from pathlib import Path

from .models import parameter_values
from .scoring import inflow_events, score, value_at

REFERENCE_AFTER_INFLOW_S = 1800     # inflow events report the reference this long after they end


def build_summary(*, series, frames, readings, errors, days, reference, truth, params, overrides, utc_offset, local) -> dict:
    ref_times = [t for t, _ in reference]
    ref_values = [v for _, v in reference]

    def local_text(when: float) -> str:
        return datetime.fromtimestamp(when, local).strftime("%Y-%m-%d %H:%M")

    def reference_near(when: float):
        value = value_at(ref_times, ref_values, when)
        return None if value is None else round(value, 1)

    return {
        "files": series["files"],
        "start": local_text(frames[0][0]),
        "end": local_text(frames[-1][0]),
        "utc_offset_h": utc_offset,
        "frames": len(frames),
        "ticks": len(readings),
        "reference_samples": len(reference),
        "annotation_samples": len(truth) - len(reference),
        "parameters": parameter_values(params),
        "overrides": overrides,
        "score": score([e for _, e in errors]),
        "days": days,
        "surface_locked_pct": round(sum(1 for r in readings if r.surface_locked) / len(readings) * 100.0, 1),
        "final_level_pct": round(readings[-1].level_pct, 2),
        "inflows": [
            {
                "start": local_text(start),
                "end": local_text(stop),
                "peak_lpm": round(peak, 1),
                "reference_before": reference_near(start),
                "reference_after": reference_near(stop + REFERENCE_AFTER_INFLOW_S),
            }
            for start, stop, peak in inflow_events(readings)
        ],
    }


def write_ticks(path: Path, readings, reference, local) -> None:
    """Every published tick, in local time, with the reference in force at that moment."""
    ref_times = [t for t, _ in reference]
    ref_values = [v for _, v in reference]
    with open(path, "w", newline="", encoding="utf-8") as handle:
        writer = csv.writer(handle)
        writer.writerow(["Time", "LevelPct", "VolumeL", "NetFlowLpm", "FlowChangeLpm2", "SurfaceM", "SurfaceLocked", "ReferencePct"])
        for r in readings:
            ref = value_at(ref_times, ref_values, r.time)
            writer.writerow([
                datetime.fromtimestamp(r.time, local).isoformat(timespec="seconds"),
                round(r.level_pct, 3), round(r.volume_l, 1), round(r.net_flow_lpm, 2), round(r.flow_change_lpm2, 3),
                round(r.surface_m, 4), int(r.surface_locked), "" if ref is None else round(ref, 2),
            ])
