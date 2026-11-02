"""Replay the shipped model over recorded raw data and score it against a reference.

Feeds every raw distance frame in ``data/<site>/*.csv`` to ``TankModel`` from
empty, publishes a tick every ``--tick`` seconds, and scores the published
level against the hydrostatic reference. The reference is used for scoring
only; it never reaches the model.

Prints a JSON summary on stdout. Optional outputs: a per-tick CSV (``--ticks``)
and a chart (``--chart``, needs matplotlib).

    python tools/replay.py --site cr
    python tools/replay.py --site cr --param full_m=0.23 --chart replay.png
"""
from __future__ import annotations

import argparse
import csv
from dataclasses import fields, replace
from datetime import date, datetime, timedelta, timezone
import importlib.util
import json
from pathlib import Path
import sys

REPO = Path(__file__).resolve().parent.parent
MODEL_PATH = REPO / "custom_components" / "ultrasonic_tank" / "model.py"

RAW_ENTITY = "sensor.driveway_water_tank_sensor_tank_distance_raw"
REFERENCE_ENTITY = "sensor.aboveground_water_tank_level"
LIVE_ENTITY = "sensor.water_tank_level"
TIME_FORMAT = "%Y-%m-%dT%H:%M:%S.%fZ"
INFLOW_THRESHOLD_LPM = 20.0
INFLOW_MERGE_GAP_S = 300.0


def load_model():
    """Import model.py on its own, so the package __init__ (Home Assistant) is not needed."""
    spec = importlib.util.spec_from_file_location("ultrasonic_tank_model", MODEL_PATH)
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--site", default="cr", help="folder under data/ (default: cr)")
    parser.add_argument("--data", type=Path, help="CSV folder; overrides --site")
    parser.add_argument("--from", dest="from_day", type=date.fromisoformat, help="first UTC day file to load (YYYY-MM-DD)")
    parser.add_argument("--to", dest="to_day", type=date.fromisoformat, help="last UTC day file to load (YYYY-MM-DD)")
    parser.add_argument("--tick", type=float, default=10.0, help="seconds between published ticks (default: 10, as in HA)")
    parser.add_argument("--utc-offset", type=float, default=-6.0, help="site local time offset in hours, for per-day scores (default: -6, Costa Rica)")
    parser.add_argument("--raw-entity", default=RAW_ENTITY)
    parser.add_argument("--reference-entity", default=REFERENCE_ENTITY)
    parser.add_argument("--live-entity", default=LIVE_ENTITY)
    parser.add_argument("--reference-empty", type=float, default=5.0, help="reference reading at 0 %% (default: 5)")
    parser.add_argument("--reference-full", type=float, default=80.0, help="reference reading at 100 %% (default: 80)")
    parser.add_argument("--param", action="append", default=[], metavar="NAME=VALUE", help="override a TankParameters field, e.g. full_m=0.23 (repeatable)")
    parser.add_argument("--ticks", type=Path, help="write every published tick to this CSV")
    parser.add_argument("--chart", type=Path, help="write a PNG chart (needs matplotlib)")
    return parser.parse_args(argv)


def build_parameters(model_module, overrides: list[str]):
    params = model_module.TankParameters()
    known = {f.name: f.type for f in fields(params)}
    changes = {}
    for item in overrides:
        name, sep, value = item.partition("=")
        name = name.strip()
        if not sep or name not in known:
            raise SystemExit(f"--param {item!r}: expected NAME=VALUE with NAME one of {', '.join(known)}")
        changes[name] = float(value)
    return replace(params, **changes)


def load_series(folder: Path, from_day: date | None, to_day: date | None, entities: dict[str, str]) -> dict[str, list[tuple[float, float]]]:
    files = sorted(folder.glob("*.csv"))
    if from_day:
        files = [f for f in files if f.stem >= from_day.isoformat()]
    if to_day:
        files = [f for f in files if f.stem <= to_day.isoformat()]
    if not files:
        raise SystemExit(f"no CSV files in {folder} for the requested days")
    wanted = {entity: role for role, entity in entities.items()}
    series: dict[str, list[tuple[float, float]]] = {role: [] for role in entities}
    for path in files:
        with open(path, newline="", encoding="utf-8") as handle:
            for row in csv.DictReader(handle):
                role = wanted.get(row["EntityId"])
                if role is None:
                    continue
                try:
                    value = float(row["State"])
                except ValueError:
                    continue            # unavailable / unknown
                when = datetime.strptime(row["TimeUtc"], TIME_FORMAT).replace(tzinfo=timezone.utc).timestamp()
                series[role].append((when, value))
    for points in series.values():
        points.sort()
    series["files"] = [f.name for f in files]  # type: ignore[assignment]
    return series


def replay(model_module, params, frames: list[tuple[float, float]], tick_s: float):
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
    }


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    model_module = load_model()
    params = build_parameters(model_module, args.param)
    folder = args.data or REPO / "data" / args.site
    series = load_series(folder, args.from_day, args.to_day, {"raw": args.raw_entity, "reference": args.reference_entity, "live": args.live_entity})
    frames = series["raw"]
    if not frames:
        raise SystemExit(f"no numeric frames for {args.raw_entity}")
    span = args.reference_full - args.reference_empty
    reference = [(t, (v - args.reference_empty) / span * 100.0) for t, v in series["reference"]]

    readings = replay(model_module, params, frames, args.tick)
    tick_times = [r.time for r in readings]
    local = timezone(timedelta(hours=args.utc_offset))

    errors_by_day: dict[str, list[float]] = {}
    all_errors = []
    for when, ref_pct in reference:
        reading = value_at(tick_times, readings, when)
        if reading is None:
            continue
        error = reading.level_pct - ref_pct
        all_errors.append(error)
        errors_by_day.setdefault(datetime.fromtimestamp(when, local).date().isoformat(), []).append(error)

    inflows = []
    for reading in readings:
        if reading.net_flow_lpm > INFLOW_THRESHOLD_LPM:
            if inflows and reading.time - inflows[-1][1] <= INFLOW_MERGE_GAP_S:
                inflows[-1][1] = reading.time
                inflows[-1][2] = max(inflows[-1][2], reading.net_flow_lpm)
            else:
                inflows.append([reading.time, reading.time, reading.net_flow_lpm])
    ref_times = [t for t, _ in reference]
    ref_values = [v for _, v in reference]

    def local_text(when: float) -> str:
        return datetime.fromtimestamp(when, local).strftime("%Y-%m-%d %H:%M")

    summary = {
        "files": series["files"],
        "start": local_text(frames[0][0]),
        "end": local_text(frames[-1][0]),
        "utc_offset_h": args.utc_offset,
        "frames": len(frames),
        "ticks": len(readings),
        "reference_samples": len(reference),
        "parameters": {f.name: getattr(params, f.name) for f in fields(params)},
        "overrides": args.param,
        "score": score(all_errors),
        "days": [{"day": day, **(score(errs) or {})} for day, errs in sorted(errors_by_day.items())],
        "surface_locked_pct": round(sum(1 for r in readings if r.surface_locked) / len(readings) * 100.0, 1),
        "final_level_pct": round(readings[-1].level_pct, 2),
        "inflows": [
            {
                "start": local_text(start),
                "end": local_text(stop),
                "peak_lpm": round(peak, 1),
                "reference_before": None if (v := value_at(ref_times, ref_values, start)) is None else round(v, 1),
                "reference_after": None if (v := value_at(ref_times, ref_values, stop + 1800)) is None else round(v, 1),
            }
            for start, stop, peak in inflows
        ],
    }

    if args.ticks:
        with open(args.ticks, "w", newline="", encoding="utf-8") as handle:
            writer = csv.writer(handle)
            writer.writerow(["TimeUtc", "LevelPct", "VolumeL", "NetFlowLpm", "FlowChangeLpm2", "SurfaceM", "SurfaceLocked", "ReferencePct"])
            for r in readings:
                ref = value_at(ref_times, ref_values, r.time)
                writer.writerow([
                    datetime.fromtimestamp(r.time, timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
                    round(r.level_pct, 3), round(r.volume_l, 1), round(r.net_flow_lpm, 2), round(r.flow_change_lpm2, 3),
                    round(r.surface_m, 4), int(r.surface_locked), "" if ref is None else round(ref, 2),
                ])
        summary["ticks_file"] = str(args.ticks)

    if args.chart:
        draw_chart(args.chart, readings, reference, series["live"], local, summary)
        summary["chart"] = str(args.chart)

    json.dump(summary, sys.stdout, indent=2)
    sys.stdout.write("\n")
    return 0


def draw_chart(path: Path, readings, reference, live, local, summary) -> None:
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.dates as mdates
    import matplotlib.pyplot as plt

    def to_dt(when: float) -> datetime:
        return datetime.fromtimestamp(when, timezone.utc)

    fig, (ax, axf) = plt.subplots(2, 1, figsize=(15, 8), sharex=True, gridspec_kw={"height_ratios": [3, 1.2]})
    ax.plot([to_dt(r.time) for r in readings], [r.level_pct for r in readings], color="#1f6feb", lw=1.4, label="model.py replay (raw only, from empty)")
    if live:
        ax.plot([to_dt(t) for t, _ in live], [v for _, v in live], color="#8250df", lw=1.0, ls="--", label="live integration")
    ax.plot([to_dt(t) for t, _ in reference], [v for _, v in reference], ".", color="#d1242f", ms=4, label="reference, adjusted (validation only)")
    ax.set_ylim(-5, 110)
    ax.set_ylabel("level %")
    ax.grid(alpha=0.3)
    ax.legend(loc="upper left", fontsize=9)
    s = summary["score"]
    title = f"Replay {summary['start']} .. {summary['end']} (local)"
    if s:
        title += f": mean err {s['mean']}, median {s['median']}, max {s['max']}, bias {s['bias']:+} pts"
    if summary["overrides"]:
        title += "  [" + ", ".join(summary["overrides"]) + "]"
    ax.set_title(title, fontsize=10)
    axf.plot([to_dt(r.time) for r in readings], [r.net_flow_lpm for r in readings], color="#1f6feb", lw=0.8)
    axf.axhline(0, color="#888", lw=0.8)
    axf.set_ylabel("net flow L/min")
    axf.grid(alpha=0.3)
    axf.xaxis.set_major_formatter(mdates.DateFormatter("%m-%d %H:%M", tz=local))
    axf.set_xlabel("local time")
    fig.tight_layout()
    fig.savefig(path, dpi=110)
    plt.close(fig)


if __name__ == "__main__":
    sys.exit(main())
