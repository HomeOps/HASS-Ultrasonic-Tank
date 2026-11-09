"""Replay a model over raw frames and correlate the published level with the pressure sensor.

Pressure (hPa) and the published level (%) are different physical quantities. Pressure
is never converted into a level here; it is used only for what it can tell honestly:

- **rank correlation**: whenever pressure is higher, is the level higher too?
- **hour-by-hour direction**: when pressure rises, falls or holds, does the level do
  the same? Each hour is classed as agree, false move (the level moved, pressure did
  not), missed move (pressure moved, the level did not) or wrong way.

Each signal's "flat" and "moving" thresholds are noise bands in its own units, with a
gap between them: a change inside the gap is too small to call either way and counts
as agreeing. The owner's hand-entered spans in reference-annotations.csv are a level in
%, so those alone are scored as a level.
"""
from __future__ import annotations

from bisect import bisect_left
from datetime import datetime

INFLOW_THRESHOLD_LPM = 20.0
INFLOW_MERGE_GAP_S = 300.0

DIRECTION_WINDOW_S = 3600.0         # one direction check per local clock hour
PRESSURE_FLAT_HPA = 3.0             # hour-to-hour change under this is flat (the sensor reports whole hPa)
PRESSURE_MOVE_HPA = 8.0             # over this it is a real rise or fall
LEVEL_FLAT_PTS = 2.0
LEVEL_MOVE_PTS = 5.0
UNCERTAIN_SHARE = 0.25              # an hour check is "uncertain" when the model said so for this share of its ticks

AGREE = "agree"
FALSE_MOVE = "false_move"           # the level moved; pressure held
MISSED_MOVE = "missed_move"         # pressure moved; the level held
WRONG_WAY = "wrong_way"             # both moved, in opposite directions
DISAGREEMENTS = (FALSE_MOVE, MISSED_MOVE, WRONG_WAY)


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


def _ranks(values: list[float]) -> list[float]:
    """Ranks from 1, ties sharing their average rank."""
    order = sorted(range(len(values)), key=values.__getitem__)
    ranks = [0.0] * len(values)
    i = 0
    while i < len(order):
        j = i
        while j + 1 < len(order) and values[order[j + 1]] == values[order[i]]:
            j += 1
        for k in range(i, j + 1):
            ranks[order[k]] = (i + j) / 2.0 + 1.0
        i = j + 1
    return ranks


def spearman(xs: list[float], ys: list[float]) -> float | None:
    """Spearman rank correlation, or None when either side does not vary."""
    if len(xs) < 3:
        return None
    rx, ry = _ranks(xs), _ranks(ys)
    mx, my = sum(rx) / len(rx), sum(ry) / len(ry)
    sxy = sum((a - mx) * (b - my) for a, b in zip(rx, ry))
    sxx = sum((a - mx) ** 2 for a in rx)
    syy = sum((b - my) ** 2 for b in ry)
    if sxx == 0 or syy == 0:
        return None
    return sxy / (sxx * syy) ** 0.5


def _direction(change: float, flat: float, move: float) -> int | None:
    """+1 / -1 for a clear rise / fall, 0 for flat, None inside the gap (too small to call)."""
    if abs(change) < flat:
        return 0
    if abs(change) > move:
        return 1 if change > 0 else -1
    return None


def classify(pressure_change: float, level_change: float) -> str:
    p = _direction(pressure_change, PRESSURE_FLAT_HPA, PRESSURE_MOVE_HPA)
    m = _direction(level_change, LEVEL_FLAT_PTS, LEVEL_MOVE_PTS)
    if p is None or m is None:
        # One side is in its gap: it may be a small move. Only a clear move against a clear
        # opposite sign counts against the model.
        if p and m is None and level_change * p < -LEVEL_FLAT_PTS:
            return WRONG_WAY
        if m and p is None and pressure_change * m < -PRESSURE_FLAT_HPA:
            return WRONG_WAY
        return AGREE
    if p == m:
        return AGREE
    if p == 0:
        return FALSE_MOVE
    if m == 0:
        return MISSED_MOVE
    return WRONG_WAY


def _median(values: list[float]) -> float:
    ordered = sorted(values)
    mid = len(ordered) // 2
    return ordered[mid] if len(ordered) % 2 else (ordered[mid - 1] + ordered[mid]) / 2.0


def _hours(pairs: list[tuple[float, float, float]]) -> list[dict]:
    """Direction check between consecutive clock hours that both hold pressure samples.

    ``pairs`` is (time, pressure hPa, published level %) at each pressure sample, so both
    signals are read at the same instants."""
    buckets: dict[int, list[tuple[float, float, float]]] = {}
    for when, hpa, level in pairs:
        buckets.setdefault(int(when // DIRECTION_WINDOW_S), []).append((when, hpa, level))
    hours = []
    keys = sorted(buckets)
    for before, after in zip(keys, keys[1:]):
        if after != before + 1:
            continue
        a, b = buckets[before], buckets[after]
        p_change = _median([p for _, p, _ in b]) - _median([p for _, p, _ in a])
        m_change = _median([m for _, _, m in b]) - _median([m for _, _, m in a])
        hours.append({"time": after * DIRECTION_WINDOW_S, "pressure_change_hpa": p_change,
                      "level_change_pts": m_change, "verdict": classify(p_change, m_change)})
    return hours


def mark_uncertain(hours: list[dict], readings) -> None:
    """Flag each hour check whose two hours the model itself called uncertain for UNCERTAIN_SHARE of ticks or more.

    Models without a certainty flag (older releases) are always certain."""
    times = [r.time for r in readings]
    flags = [not getattr(r, "level_certain", True) for r in readings]
    for h in hours:
        lo = bisect_left(times, h["time"] - DIRECTION_WINDOW_S)
        hi = bisect_left(times, h["time"] + DIRECTION_WINDOW_S)
        span = flags[lo:hi]
        h["uncertain"] = bool(span) and sum(span) / len(span) >= UNCERTAIN_SHARE


def correlation(pairs: list[tuple[float, float, float]], hours: list[dict]) -> dict | None:
    if not pairs:
        return None
    rho = spearman([p for _, p, _ in pairs], [m for _, _, m in pairs])
    counts = {v: sum(1 for h in hours if h["verdict"] == v) for v in (AGREE, *DISAGREEMENTS)}
    return {
        "samples": len(pairs),
        "rank_correlation": None if rho is None else round(rho, 3),
        "hours": len(hours),
        **counts,
        "disagree": sum(counts[v] for v in DISAGREEMENTS),
        "uncertain_hours": sum(1 for h in hours if h.get("uncertain")),
        "disagree_certain": sum(1 for h in hours if h["verdict"] != AGREE and not h.get("uncertain")),
    }


def owner_misses(readings, annotations) -> dict | None:
    """Ticks outside an owner span's level range, and by how much at most (pts)."""
    ticks = misses = 0
    worst = 0.0
    for r in readings:
        for s in annotations:
            if s["start"] <= r.time <= s["end"]:
                ticks += 1
                off = max(s["min"] - r.level_pct, r.level_pct - s["max"], 0.0)
                if off > 0:
                    misses += 1
                    worst = max(worst, off)
    if not ticks:
        return None
    return {"ticks": ticks, "outside": misses, "max_off_pts": round(worst, 1)}


def evaluate(model_module, params, frames, pressure, annotations, tick_s, local):
    """Replay once; return the readings, the hourly direction checks, the overall correlation and per-day results."""
    readings = replay(model_module, params, frames, tick_s)
    tick_times = [r.time for r in readings]
    pairs = []
    for when, hpa in pressure:
        reading = value_at(tick_times, readings, when)
        if reading is not None:
            pairs.append((when, hpa, reading.level_pct))
    hours = _hours(pairs)
    mark_uncertain(hours, readings)

    def day_of(when: float) -> str:
        return datetime.fromtimestamp(when, local).date().isoformat()

    days = []
    for day in sorted({day_of(t) for t, _, _ in pairs}):
        day_pairs = [p for p in pairs if day_of(p[0]) == day]
        day_hours = [h for h in hours if day_of(h["time"]) == day]
        days.append({"day": day, **(correlation(day_pairs, day_hours) or {})})
    result = {"correlation": correlation(pairs, hours), "days": days, "owner": owner_misses(readings, annotations)}
    return readings, hours, result


def compare(base_hours: list[dict], hours: list[dict]) -> dict:
    """Hours where the candidate agrees with pressure and the baseline did not (better), and the reverse."""
    base = {h["time"]: h["verdict"] for h in base_hours}
    better = worse = 0
    for h in hours:
        was_ok = base.get(h["time"]) == AGREE
        is_ok = h["verdict"] == AGREE
        better += is_ok and not was_ok
        worse += was_ok and not is_ok
    return {"better": better, "worse": worse, "same": len(hours) - better - worse}


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
