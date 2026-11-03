"""Replay a model over raw frames and score the published level against the truth."""
from __future__ import annotations

from datetime import datetime

SAME_WITHIN_PTS = 1.0               # a comparison closer than this counts as "same"
BIG_ERROR_PTS = 20.0                # reported as "off by more than"
INFLOW_THRESHOLD_LPM = 20.0
INFLOW_MERGE_GAP_S = 300.0


def replay(model_module, params, frames: list[tuple[float, float]], tick_s: float):
    """Feed every frame to a fresh TankModel (from empty) and tick every ``tick_s``, as HA does."""
    model = model_module.TankModel(params)
    readings = []
    index = 0
    now = frames[0][0]
    end = frames[-1][0]
    while now <= end:
        while index < len(frames) and frames[index][0] <= now:
            model.add_frame(*frames[index])
            index += 1
        readings.append(model.tick(now))
        now += tick_s
    return readings


def value_at(times: list[float], values: list, when: float):
    """Last value at or before ``when`` (binary search), or None."""
    lo, hi = 0, len(times)
    while lo < hi:
        mid = (lo + hi) // 2
        if times[mid] <= when:
            lo = mid + 1
        else:
            hi = mid
    return values[lo - 1] if lo else None


def score(errors: list[float]) -> dict | None:
    if not errors:
        return None
    absolute = sorted(abs(e) for e in errors)
    count = len(absolute)
    return {
        "samples": count,
        "mean": round(sum(absolute) / count, 2),
        "median": round(absolute[count // 2], 2),
        "p90": round(absolute[min(count - 1, int(count * 0.9))], 2),
        "max": round(absolute[-1], 2),
        "bias": round(sum(errors) / count, 2),
        f"over_{int(BIG_ERROR_PTS)}": sum(1 for e in absolute if e > BIG_ERROR_PTS),
    }


def evaluate(model_module, params, frames, truth, tick_s, local):
    """Replay once; return the readings, (time, signed error) at every truth sample, and per-day scores.

    The error is the distance from the published level to the truth range (zero inside it)."""
    readings = replay(model_module, params, frames, tick_s)
    tick_times = [r.time for r in readings]
    errors = []
    for when, low, high in truth:
        reading = value_at(tick_times, readings, when)
        if reading is not None:
            level = reading.level_pct
            errors.append((when, level - min(max(level, low), high)))
    by_day: dict[str, list[float]] = {}
    for when, error in errors:
        by_day.setdefault(datetime.fromtimestamp(when, local).date().isoformat(), []).append(error)
    days = [{"day": day, **(score(errs) or {})} for day, errs in sorted(by_day.items())]
    return readings, errors, days


def compare(base_errors, errors) -> dict:
    """How many truth samples the candidate got better, worse or the same as the baseline."""
    better = worse = 0
    for (_, base), (_, cand) in zip(base_errors, errors):
        if abs(cand) < abs(base) - SAME_WITHIN_PTS:
            better += 1
        elif abs(cand) > abs(base) + SAME_WITHIN_PTS:
            worse += 1
    return {"better": better, "worse": worse, "same": len(errors) - better - worse}


def inflow_events(readings) -> list[list[float]]:
    """[start, end, peak L/min] spans where the published net flow exceeds the threshold."""
    inflows = []
    for reading in readings:
        if reading.net_flow_lpm > INFLOW_THRESHOLD_LPM:
            if inflows and reading.time - inflows[-1][1] <= INFLOW_MERGE_GAP_S:
                inflows[-1][1] = reading.time
                inflows[-1][2] = max(inflows[-1][2], reading.net_flow_lpm)
            else:
                inflows.append([reading.time, reading.time, reading.net_flow_lpm])
    return inflows
