"""The PREV vs NEXT chart: a header with the result, tank level, optional zoom, error vs truth."""
from __future__ import annotations

from pathlib import Path

from .chart_style import (BACKGROUND, BASELINE, BASELINE_OFFSET_PTS, CANDIDATE, DASHED, RAW_DOTS, SAVE_METADATA,
                          apply_theme, labels, time_axis, to_dt, with_gaps)
from .scoring import BIG_ERROR_PTS

PANEL_RATIOS = {"level": 1.0, "zoom": 1.2, "error": 0.9}
POINTS_PER_MINUTE = 60              # readings are thinned to one per minute for drawing


def draw_chart(path: Path, readings, errors, baseline, reference, annotations, frames, params, local, summary, zoom) -> None:
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.dates as mdates
    import matplotlib.pyplot as plt

    apply_theme(plt)
    text = labels(summary, baseline is not None)
    panels = ["level"] + (["zoom"] if zoom else []) + ["error"]
    fig, axes = plt.subplots(len(panels), 1, figsize=(14, 4.2 * len(panels) + 0.8),
                             gridspec_kw={"height_ratios": [PANEL_RATIOS[p] for p in panels]})
    _header(fig, summary, text, baseline is not None, len(panels))
    step = max(1, int(POINTS_PER_MINUTE / (readings[1].time - readings[0].time))) if len(readings) > 1 else 1
    span = (readings[0].time, readings[-1].time)

    for ax, panel in zip(axes, panels):
        ax.grid(alpha=0.25)
        if panel == "error":
            _error_panel(ax, errors, baseline, text)
            time_axis(ax, mdates, local, *span)
        else:
            _level_panel(ax, readings, baseline, reference, annotations, frames, params, text, step,
                         zoom if panel == "zoom" else None)
            if panel == "zoom":
                ax.set_xlim(*zoom)
                ax.set_title(f"Zoom: {zoom[0]:%b %d %H:%M} to {zoom[1]:%b %d %H:%M} local", loc="left")
                ax.xaxis.set_major_formatter(mdates.DateFormatter("%b %d %H:%M", tz=local))
            else:
                time_axis(ax, mdates, local, *span)
                if zoom:
                    ax.axvspan(*zoom, color="white", alpha=0.07)
        ax.legend(loc="upper left", fontsize=8.5, framealpha=0.85)
    fig.tight_layout(rect=(0, 0, 1, 0.9 if len(panels) == 2 else 0.93))
    fig.savefig(path, dpi=110, metadata=SAVE_METADATA)
    plt.close(fig)


def _header(fig, summary, text, has_baseline, panel_count) -> None:
    s = summary["score"]
    if not has_baseline:
        fig.suptitle(f"model.py: mean error {s['mean']:.1f} pts ({summary['start']} to {summary['end']} Costa Rica time)",
                     x=0.01, ha="left", fontsize=15, fontweight="bold")
        return
    bs, bl = summary["baseline"]["score"], summary["baseline"]
    fig.suptitle(f"PREV ({text['baseline_ref'] or 'baseline'}) vs NEXT (this change): mean error {bs['mean']:.1f} -> {s['mean']:.1f} pts",
                 x=0.01, y=0.995, ha="left", fontsize=15, fontweight="bold")
    days = [f[:-4] for f in summary["files"]]
    fig.text(0.99, 0.995, f"Days {days[0]} to {days[-1]}" if len(days) > 1 else f"Day {days[0]}",
             ha="right", va="top", fontsize=13, fontweight="bold")
    fig.text(0.01, 0.948 if panel_count == 2 else 0.962,
             f"At the {s['samples']} truth points, NEXT is better at {bl['better']}, worse at {bl['worse']}, the same at {bl['same']}.  "
             f"Where the dashed line runs parallel, {BASELINE_OFFSET_PTS:.0f} pts above the solid one, both versions agree.\n"
             f"Replayed from empty over {summary['start']} to {summary['end']} Costa Rica time.",
             ha="left", va="top", fontsize=10.5)


def _level_panel(ax, readings, baseline, reference, annotations, frames, params, text, step, zoom) -> None:
    if zoom:
        lo, hi = (z.timestamp() for z in zoom)
        raw = [(t, (params.floor_m - d) / params.span_m * 100.0) for t, d in frames[::2] if lo <= t <= hi]
        ax.scatter([to_dt(t) for t, _ in raw], [v for _, v in raw], s=1.0, color=RAW_DOTS,
                   label="raw ultrasonic (dim dots, the only model input)", rasterized=True)
    for i, span in enumerate(annotations):
        ax.fill_between([to_dt(span["start"]), to_dt(span["end"])], span["min"], span["max"] + 2, facecolor="none",
                        edgecolor="white", hatch="////", lw=0.8, alpha=0.8, zorder=1,
                        label=f"TRUTH: {span['source']} says {span['min']:.0f}-{span['max']:.0f} % (hatched band)" if i == 0 else None)
    if baseline:
        b = baseline["readings"][::step]
        ax.plot([to_dt(r.time) for r in b], [r.level_pct + BASELINE_OFFSET_PTS for r in b],
                color=BASELINE, lw=1.6, ls=DASHED, label=text["baseline"], zorder=5)
    c = readings[::step]
    ax.plot([to_dt(r.time) for r in c], [r.level_pct for r in c], color=CANDIDATE, lw=3.0, label=text["candidate"], zorder=4)
    ax.plot([to_dt(t) for t, _ in reference], [v for _, v in reference], "D", ls="none", color="white",
            mfc=BACKGROUND, mew=1.1, ms=4, label=text["truth"], zorder=6)
    ax.set_ylim(-5, 115)
    ax.set_ylabel("level %")
    if not zoom:
        ax.set_title("Tank level", loc="left", fontsize=12, fontweight="bold")


def _error_panel(ax, errors, baseline, text) -> None:
    if baseline:
        be = with_gaps([(t, abs(e)) for t, e in baseline["errors"]])
        ax.plot([to_dt(t) for t, _ in be], [e + BASELINE_OFFSET_PTS for _, e in be],
                color=BASELINE, lw=1.6, ls=DASHED, label=text["baseline"], zorder=5)
    ce = with_gaps([(t, abs(e)) for t, e in errors])
    ax.plot([to_dt(t) for t, _ in ce], [e for _, e in ce], color=CANDIDATE, lw=3.0, label=text["candidate"], zorder=4)
    ax.axhline(BIG_ERROR_PTS, color="white", lw=0.8, ls=":")
    ax.set_ylim(0, 100)
    ax.set_ylabel("error vs truth (pts)\nlower is better")
    ax.set_xlabel("Costa Rica time (no line = no truth data)")
    ax.set_title("How wrong vs the truth (lower is better)", loc="left", fontsize=12, fontweight="bold")
