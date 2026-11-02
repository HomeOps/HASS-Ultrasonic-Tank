"""Replay the shipped model over recorded raw data and score it against a reference.

Feeds every raw distance frame in ``data/<site>/*.csv`` to ``TankModel`` from
empty, publishes a tick every ``--tick`` seconds, and scores the published
level against the hydrostatic reference. The reference is used for scoring
only; it never reaches the model.

With ``--compare`` it also replays a baseline (the shipped defaults plus any
``--baseline-param`` overrides) and reports, sample by sample, where the
candidate is better or worse.

Prints a JSON summary on stdout. Optional outputs: a per-tick CSV (``--ticks``)
and a chart (``--chart``, needs matplotlib). Charts are dark mode and
colour-blind safe: series differ by line style, marker and brightness.

    python tools/replay.py --site cr
    python tools/replay.py --site cr --param full_m=0.23 --chart replay.png
    python tools/replay.py --compare --baseline-param max_rise_gap_s=0 --chart compare.png
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
SAME_WITHIN_PTS = 1.0               # a comparison closer than this counts as "same"
BIG_ERROR_PTS = 20.0                # reported as "off by more than"
REFERENCE_GAP_S = 3 * 3600          # charts do not draw a line across a reference gap this long


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
    parser.add_argument("--compare", action="store_true", help="also replay a baseline and compare")
    parser.add_argument("--baseline-param", action="append", default=[], metavar="NAME=VALUE", help="override a field for the baseline only (repeatable)")
    parser.add_argument("--zoom-from", type=datetime.fromisoformat, help="chart: local start of a zoom panel (YYYY-MM-DDTHH:MM)")
    parser.add_argument("--zoom-to", type=datetime.fromisoformat, help="chart: local end of the zoom panel")
    parser.add_argument("--ticks", type=Path, help="write every published tick to this CSV")
    parser.add_argument("--chart", type=Path, help="write a PNG (or .svg) chart (needs matplotlib)")
    return parser.parse_args(argv)


def build_parameters(model_module, overrides: list[str]):
    params = model_module.TankParameters()
    known = {f.name for f in fields(params)}
    changes = {}
    for item in overrides:
        name, sep, value = item.partition("=")
        name = name.strip()
        if not sep or name not in known:
            raise SystemExit(f"--param {item!r}: expected NAME=VALUE with NAME one of {', '.join(sorted(known))}")
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
        f"over_{int(BIG_ERROR_PTS)}": sum(1 for e in absolute if e > BIG_ERROR_PTS),
    }


def evaluate(model_module, params, frames, reference, tick_s, local):
    """Replay once; return the readings and (time, signed error) at every reference sample."""
    readings = replay(model_module, params, frames, tick_s)
    tick_times = [r.time for r in readings]
    errors = []
    for when, ref_pct in reference:
        reading = value_at(tick_times, readings, when)
        if reading is not None:
            errors.append((when, reading.level_pct - ref_pct))
    by_day: dict[str, list[float]] = {}
    for when, error in errors:
        by_day.setdefault(datetime.fromtimestamp(when, local).date().isoformat(), []).append(error)
    days = [{"day": day, **(score(errs) or {})} for day, errs in sorted(by_day.items())]
    return readings, errors, days


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
    local = timezone(timedelta(hours=args.utc_offset))

    readings, errors, days = evaluate(model_module, params, frames, reference, args.tick, local)

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
        "score": score([e for _, e in errors]),
        "days": days,
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

    baseline = None
    if args.compare:
        base_params = build_parameters(model_module, args.baseline_param)
        base_readings, base_errors, base_days = evaluate(model_module, base_params, frames, reference, args.tick, local)
        better = worse = 0
        for (_, b), (_, c) in zip(base_errors, errors):
            if abs(c) < abs(b) - SAME_WITHIN_PTS:
                better += 1
            elif abs(c) > abs(b) + SAME_WITHIN_PTS:
                worse += 1
        baseline = {"readings": base_readings, "errors": base_errors}
        summary["baseline"] = {
            "overrides": args.baseline_param,
            "score": score([e for _, e in base_errors]),
            "days": base_days,
            "better": better,
            "worse": worse,
            "same": len(errors) - better - worse,
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
        zoom = None
        if args.zoom_from and args.zoom_to:
            zoom = (args.zoom_from.replace(tzinfo=local), args.zoom_to.replace(tzinfo=local))
        draw_chart(args.chart, readings, errors, baseline, reference, frames, params, local, summary, zoom)
        summary["chart"] = str(args.chart)

    json.dump(summary, sys.stdout, indent=2)
    sys.stdout.write("\n")
    return 0


# --------------------------------------------------------------------- chart
BACKGROUND = "#111418"
CANDIDATE = "#56B4E9"               # Okabe-Ito sky blue, bright on dark
BASELINE = "#9a9a9a"
RAW_DOTS = "#3a3f47"
DASHED = (0, (6, 3))


def with_gaps(points: list[tuple[float, float]]) -> list[tuple[float, float]]:
    """Insert a NaN where the reference had no data for a long time, so no line is drawn across it."""
    out = []
    for i, (t, v) in enumerate(points):
        if i and t - points[i - 1][0] > REFERENCE_GAP_S:
            out.append((t - 1, float("nan")))
        out.append((t, v))
    return out


def draw_chart(path: Path, readings, errors, baseline, reference, frames, params, local, summary, zoom) -> None:
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.dates as mdates
    import matplotlib.pyplot as plt

    plt.style.use("dark_background")
    plt.rcParams.update({"font.size": 10, "figure.facecolor": BACKGROUND, "axes.facecolor": BACKGROUND, "savefig.facecolor": BACKGROUND})

    def to_dt(when: float) -> datetime:
        return datetime.fromtimestamp(when, timezone.utc)

    s = summary["score"]
    cand_label = "AFTER (thick bright solid)" if baseline else "model.py replay (thick solid)"
    if summary["overrides"]:
        cand_label += " [" + ", ".join(summary["overrides"]) + "]"
    base_label = "BEFORE (grey dashed)"
    if baseline and summary["baseline"]["overrides"]:
        base_label += " [" + ", ".join(summary["baseline"]["overrides"]) + "]"
    truth_label = "TRUTH, pressure (hollow diamonds, scoring only)"

    panels = ["level"] + (["zoom"] if zoom else []) + ["error"]
    ratios = {"level": 1.0, "zoom": 1.2, "error": 0.9}
    fig, axes = plt.subplots(len(panels), 1, figsize=(14, 4.2 * len(panels)), gridspec_kw={"height_ratios": [ratios[p] for p in panels]})
    step = max(1, int(60 / (readings[1].time - readings[0].time))) if len(readings) > 1 else 1

    for ax, panel in zip(axes, panels):
        ax.grid(alpha=0.25)
        if panel in ("level", "zoom"):
            if panel == "zoom":
                lo, hi = (z.timestamp() for z in zoom)
                raw = [(t, (params.floor_m - d) / params.span_m * 100.0) for t, d in frames[::2] if lo <= t <= hi]
                ax.scatter([to_dt(t) for t, _ in raw], [v for _, v in raw], s=1.0, color=RAW_DOTS, label="raw ultrasonic (dim dots, the only model input)", rasterized=True)
            if baseline:
                b = baseline["readings"][::step]
                ax.plot([to_dt(r.time) for r in b], [r.level_pct for r in b], color=BASELINE, lw=2.0, ls=DASHED, label=base_label)
            c = readings[::step]
            ax.plot([to_dt(r.time) for r in c], [r.level_pct for r in c], color=CANDIDATE, lw=2.6, label=cand_label)
            ax.plot([to_dt(t) for t, _ in reference], [v for _, v in reference], "D", color="white", mfc=BACKGROUND, mew=1.1, ms=4, label=truth_label)
            ax.set_ylim(-5, 110)
            ax.set_ylabel("level %")
            if panel == "zoom":
                ax.set_xlim(*zoom)
                ax.set_title(f"Zoom: {zoom[0]:%b %d %H:%M} to {zoom[1]:%b %d %H:%M} local", loc="left")
                ax.xaxis.set_major_formatter(mdates.DateFormatter("%b %d %H:%M", tz=local))
            else:
                title = f"Level, replayed from empty over {summary['frames']:,} raw frames ({summary['start']} to {summary['end']} local)"
                ax.set_title(title, loc="left")
                ax.xaxis.set_major_locator(mdates.DayLocator(tz=local))
                ax.xaxis.set_major_formatter(mdates.DateFormatter("%b %d", tz=local))
                if zoom:
                    ax.axvspan(*zoom, color="white", alpha=0.07)
            ax.legend(loc="upper left", fontsize=8.5, framealpha=0.85)
        else:
            if baseline:
                be = with_gaps([(t, abs(e)) for t, e in baseline["errors"]])
                ax.plot([to_dt(t) for t, _ in be], [e for _, e in be], color=BASELINE, lw=2.0, ls=DASHED, marker="o", mfc=BACKGROUND, ms=4, label=base_label)
            ce = with_gaps([(t, abs(e)) for t, e in errors])
            ax.plot([to_dt(t) for t, _ in ce], [e for _, e in ce], color=CANDIDATE, lw=2.6, marker="s", ms=3.5, label=cand_label)
            ax.axhline(BIG_ERROR_PTS, color="white", lw=0.8, ls=":")
            ax.set_ylim(0, 100)
            ax.set_ylabel("error vs truth (pts)\nlower is better")
            ax.xaxis.set_major_locator(mdates.DayLocator(tz=local))
            ax.xaxis.set_major_formatter(mdates.DateFormatter("%b %d", tz=local))
            ax.set_xlabel("local time (no line = no reference data)")
            key = f"over_{int(BIG_ERROR_PTS)}"
            if baseline:
                bs = summary["baseline"]["score"]
                bl = summary["baseline"]
                title = (f"How wrong at each of the {s['samples']} truth readings:  better at {bl['better']}, worse at {bl['worse']}, same at {bl['same']}.  "
                         f"Mean error {bs['mean']} -> {s['mean']},  off by >{int(BIG_ERROR_PTS)} pts: {bs[key]} -> {s[key]}")
            else:
                title = f"How wrong at each of the {s['samples']} truth readings: mean {s['mean']}, p90 {s['p90']}, off by >{int(BIG_ERROR_PTS)} pts: {s[key]}"
            ax.set_title(title, loc="left", fontsize=10)
            ax.legend(loc="upper left", fontsize=8.5, framealpha=0.85)
    fig.tight_layout()
    fig.savefig(path, dpi=110)
    plt.close(fig)


if __name__ == "__main__":
    sys.exit(main())
