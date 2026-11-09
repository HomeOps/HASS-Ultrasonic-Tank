"""Command line: replay, correlate with pressure, optionally compare with PREV, print the JSON summary."""
from __future__ import annotations

import argparse
from datetime import date, datetime, timedelta, timezone
import json
from pathlib import Path
import sys

from .models import REPO, build_parameters, load_model
from .recordings import RAW_ENTITY, REFERENCE_ENTITY, load_annotations, load_series
from .report import build_summary, write_ticks
from .scoring import compare, evaluate

DESCRIPTION = """Replay model.py over recorded raw data and correlate it with the pressure sensor.

Feeds every raw distance frame in data/<site>/YYYY-MM-DD.csv to TankModel from
empty and publishes a tick every --tick seconds. The published level (%) is then
compared with the pressure sensor (hPa) by correlation only: rank correlation, and
hour by hour, whether both rise, fall or hold together. Pressure is a different
physical quantity and is never converted into a level. It never reaches the model.
The owner's reference-annotations.csv spans are a level in % and are checked as one.

With --baseline-ref (PREV, a release tag) or --compare it also replays a
baseline and reports, hour by hour, where NEXT agrees with pressure and PREV did
not (better), and the reverse (worse).

Prints a JSON summary on stdout. Optional: a per-tick CSV (--ticks) and a chart
(--chart, needs matplotlib).

    python tools/replay.py --site cr
    python tools/replay.py --site cr --param full_m=0.23 --chart replay.png
    python tools/replay.py --baseline-ref v0.2.0 --from 2026-11-01 --to 2026-11-02 --chart compare.svg
"""


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=DESCRIPTION, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--site", default="cr", help="folder under data/ (default: cr)")
    parser.add_argument("--data", type=Path, help="CSV folder; overrides --site")
    parser.add_argument("--from", dest="from_day", type=date.fromisoformat, help="first local day file to load (YYYY-MM-DD)")
    parser.add_argument("--to", dest="to_day", type=date.fromisoformat, help="last local day file to load (YYYY-MM-DD)")
    parser.add_argument("--tick", type=float, default=10.0, help="seconds between published ticks (default: 10, as in HA)")
    parser.add_argument("--utc-offset", type=float, default=-6.0, help="site local time offset in hours (default: -6, Costa Rica)")
    parser.add_argument("--param", action="append", default=[], metavar="NAME=VALUE", help="override a TankParameters field, e.g. full_m=0.23 (repeatable)")
    parser.add_argument("--compare", action="store_true", help="also replay a baseline and compare")
    parser.add_argument("--baseline-ref", metavar="TAG", help="PREV = model.py from this git tag/commit (implies --compare), e.g. v0.2.0")
    parser.add_argument("--baseline-param", action="append", default=[], metavar="NAME=VALUE", help="override a field for the baseline only (repeatable)")
    parser.add_argument("--no-annotations", action="store_true", help="ignore reference-annotations.csv (owner level spans)")
    parser.add_argument("--zoom-from", type=datetime.fromisoformat, help="chart: local start of a zoom panel (YYYY-MM-DDTHH:MM)")
    parser.add_argument("--zoom-to", type=datetime.fromisoformat, help="chart: local end of the zoom panel")
    parser.add_argument("--ticks", type=Path, help="write every published tick to this CSV")
    parser.add_argument("--chart", type=Path, help="write a PNG (or .svg) chart (needs matplotlib)")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    model_module = load_model()
    params = build_parameters(model_module, args.param, args.utc_offset)
    folder = args.data or REPO / "data" / args.site
    series = load_series(folder, args.from_day, args.to_day, {"raw": RAW_ENTITY, "reference": REFERENCE_ENTITY})
    frames = series["raw"]
    if not frames:
        raise SystemExit(f"no numeric frames for {RAW_ENTITY}")
    pressure = series["reference"]
    local = timezone(timedelta(hours=args.utc_offset))
    annotations = [] if args.no_annotations else load_annotations(folder, frames[0][0], frames[-1][0])

    readings, hours, result = evaluate(model_module, params, frames, pressure, annotations, args.tick, local)
    summary = build_summary(series=series, frames=frames, readings=readings, result=result, pressure=pressure,
                            params=params, overrides=args.param, utc_offset=args.utc_offset, local=local)

    baseline = None
    if args.compare or args.baseline_ref:
        base_module = load_model(args.baseline_ref) if args.baseline_ref else model_module
        base_params = build_parameters(base_module, args.baseline_param, args.utc_offset)
        base_readings, base_hours, base_result = evaluate(base_module, base_params, frames, pressure, annotations, args.tick, local)
        baseline = {"readings": base_readings, "hours": base_hours}
        summary["baseline"] = {"ref": args.baseline_ref, "overrides": args.baseline_param, **base_result,
                               **compare(base_hours, hours)}

    if args.ticks:
        write_ticks(args.ticks, readings, pressure, local)
        summary["ticks_file"] = str(args.ticks)

    if args.chart:
        from .chart import draw_chart      # matplotlib only when a chart is asked for
        zoom = None
        if args.zoom_from and args.zoom_to:
            zoom = (args.zoom_from.replace(tzinfo=local), args.zoom_to.replace(tzinfo=local))
        draw_chart(args.chart, readings, hours, baseline, pressure, annotations, frames, params, local, summary, zoom)
        summary["chart"] = str(args.chart)

    json.dump(summary, sys.stdout, indent=2)
    sys.stdout.write("\n")
    return 0
