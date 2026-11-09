"""The PREV vs NEXT chart: a header with the result, tank level with pressure on its own axis,
optional zoom, and the hours whose direction disagrees with pressure."""
from __future__ import annotations

from datetime import datetime, timedelta
from pathlib import Path

from .chart_style import (BACKGROUND, BASELINE, BASELINE_OFFSET_PTS, CANDIDATE, DASHED, PRESSURE_MARKER, RAW_DOTS,
                          SAVE_METADATA, VERDICT_MARKERS, apply_theme, labels, time_axis, to_dt)
from .scoring import DIRECTION_WINDOW_S, DISAGREEMENTS, compare

PANEL_RATIOS = {"level": 1.0, "zoom": 1.2, "hours": 0.45}
ERROR_BAR_EVERY_S = 1800            # one +/- bar every 30 min
POINTS_PER_MINUTE = 60              # readings are thinned to one per minute for drawing


def draw_day_charts(folder: Path, readings, hours, baseline, pressure, annotations, frames, params, local, summary,
                    last: int | None = None, suffix: str = ".png") -> list[str]:
    """One chart per local day (the ``last`` days only, when given), all cut from the same continuous replay,
    so no day starts from empty."""
    folder.mkdir(parents=True, exist_ok=True)
    base_days = {d["day"]: d for d in summary["baseline"]["days"]} if baseline else {}
    written = []
    scored = {d["day"]: d for d in summary["days"]}
    files = summary["files"][-last:] if last else summary["files"]
    for day in (scored.get(f[:-4], {"day": f[:-4]}) for f in files):   # a day with no pressure still gets a chart
        start = datetime.fromisoformat(day["day"]).replace(tzinfo=local)
        end = start + timedelta(days=1)
        lo, hi = start.timestamp(), end.timestamp()
        day_hours = [h for h in hours if lo <= h["time"] < hi]
        day_summary = {**summary, "correlation": day, "files": [f"{day['day']}.csv"]}
        day_baseline = None
        if baseline:
            base_hours = [h for h in baseline["hours"] if lo <= h["time"] < hi]
            day_baseline = {**baseline, "hours": base_hours}
            day_summary["baseline"] = {**summary["baseline"], "correlation": base_days.get(day["day"]),
                                       **compare(base_hours, day_hours)}
        path = folder / f"day-{day['day']}{suffix}"
        draw_chart(path, readings, day_hours, day_baseline, pressure, annotations, frames, params, local, day_summary,
                   (start, end), day_only=True)
        written.append(str(path))
    return written


def draw_chart(path: Path, readings, hours, baseline, pressure, annotations, frames, params, local, summary, zoom,
               day_only: bool = False) -> None:
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.dates as mdates
    import matplotlib.pyplot as plt

    apply_theme(plt)
    text = labels(summary, baseline is not None)
    panels = ["zoom", "hours"] if day_only else ["level"] + (["zoom"] if zoom else []) + ["hours"]
    fig, axes = plt.subplots(len(panels), 1, figsize=(14, 3.6 * len(panels) + 1.6),
                             gridspec_kw={"height_ratios": [PANEL_RATIOS[p] for p in panels]})
    _header(fig, summary, text, baseline is not None)
    step = max(1, int(POINTS_PER_MINUTE / (readings[1].time - readings[0].time))) if len(readings) > 1 else 1
    span = (zoom[0].timestamp(), zoom[1].timestamp()) if day_only else (readings[0].time, readings[-1].time)

    for ax, panel in zip(axes, panels):
        ax.grid(alpha=0.25)
        if panel == "hours":
            _hours_panel(ax, hours, baseline, text)
            time_axis(ax, mdates, local, *span)
            continue
        twin = _level_panel(ax, readings, baseline, pressure, annotations, frames, params, text, step,
                            zoom if panel == "zoom" else None)
        if panel == "zoom":
            ax.set_xlim(*zoom)
            title = (f"{zoom[0]:%A %b %d}: tank level (left axis) and pressure (right axis, hPa)" if day_only
                     else f"Zoom: {zoom[0]:%b %d %H:%M} to {zoom[1]:%b %d %H:%M} local")
            ax.set_title(title, loc="left", fontsize=12 if day_only else None, fontweight="bold" if day_only else None)
            if day_only:
                time_axis(ax, mdates, local, *span)
            else:
                ax.xaxis.set_major_formatter(mdates.DateFormatter("%b %d %H:%M", tz=local))
        else:
            time_axis(ax, mdates, local, *span)
            if zoom:
                ax.axvspan(*zoom, color="white", alpha=0.07)
        handles, names = ax.get_legend_handles_labels()
        more, more_names = twin.get_legend_handles_labels()
        legend = ax.legend(handles + more, names + more_names, loc="lower left", fontsize=8.5, framealpha=0.85)
        for handle in legend.legend_handles:
            if hasattr(handle, "set_sizes"):    # the raw scatter: its 2 pt dots are unreadable in a legend
                handle.set_sizes([18.0])
    fig.tight_layout(rect=(0, 0, 1, 0.91))
    fig.savefig(path, dpi=110, metadata=SAVE_METADATA)
    plt.close(fig)


def _rho(result) -> str:
    rho = (result or {}).get("rank_correlation")
    return "n/a" if rho is None else f"{rho:.3f}"


def _header(fig, summary, text, has_baseline) -> None:
    c = summary["correlation"] or {}
    days = [f[:-4] for f in summary["files"]]
    fig.text(0.99, 0.995, f"Days {days[0]} to {days[-1]}" if len(days) > 1 else f"Day {days[0]}",
             ha="right", va="top", fontsize=13, fontweight="bold")
    if has_baseline:
        b = summary["baseline"]["correlation"] or {}
        title = (f"PREV ({text['baseline_ref'] or 'baseline'}) vs NEXT: hours wrong with a small +/- "
                 f"{b.get('disagree_certain', 0)} -> {c.get('disagree_certain', 0)} of {c.get('hours', 0)}")
        detail = (f"Hours against pressure: PREV {b.get('disagree', 0)}, NEXT {c.get('disagree', 0)}; NEXT's +/- was over its "
                  f"trust limit in {c.get('uncertain_hours', 0)} hours.  "
                  f"Rank correlation with pressure: PREV {_rho(b)}, NEXT {_rho(c)} (1 = always in the same order).\n")
    else:
        title = (f"model.py: hours wrong with a small +/- {c.get('disagree_certain', 0)} of {c.get('hours', 0)} "
                 f"(against pressure {c.get('disagree', 0)}), rank correlation {_rho(c)}")
        detail = ""
    fig.suptitle(title, x=0.01, y=0.995, ha="left", fontsize=15, fontweight="bold")
    fig.text(0.01, 0.958,
             detail + "Pressure (hPa) is a different quantity from the level (%): it is drawn on its own axis and used only "
             "for correlation, never as the level.\n"
             f"Replayed from empty over {summary['start']} to {summary['end']} Costa Rica time.",
             ha="left", va="top", fontsize=10.5)


def _level_panel(ax, readings, baseline, pressure, annotations, frames, params, text, step, zoom):
    lo, hi = (z.timestamp() for z in zoom) if zoom else (readings[0].time, readings[-1].time)
    raw = [(t, (params.floor_m - d) / params.span_m * 100.0) for t, d in frames if lo <= t <= hi]
    ax.scatter([to_dt(t) for t, _ in raw], [v for _, v in raw], s=2.0, color=RAW_DOTS, linewidths=0,
               label="RAW: ultrasonic distance as level (small grey dots, the only model input)", rasterized=True, zorder=2)
    for i, span in enumerate(s for s in annotations if s["end"] >= lo and s["start"] <= hi):
        ax.fill_between([to_dt(span["start"]), to_dt(span["end"])], span["min"], span["max"] + 2, facecolor="none",
                        edgecolor="white", hatch="////", lw=0.8, alpha=0.8, zorder=1,
                        label=f"OWNER: {span['source']} says {span['min']:.0f}-{span['max']:.0f} % (hatched band)" if i == 0 else None)
    if baseline:
        b = baseline["readings"][::step]
        ax.plot([to_dt(r.time) for r in b], [r.level_pct + BASELINE_OFFSET_PTS for r in b],
                color=BASELINE, lw=1.6, ls=DASHED, label=text["baseline"], zorder=5)
    c = readings[::step]
    ax.plot([to_dt(r.time) for r in c], [r.level_pct for r in c], color=CANDIDATE, lw=3.0, label=text["candidate"], zorder=4)
    bars = [r for r in readings[::max(1, int(ERROR_BAR_EVERY_S / max(readings[1].time - readings[0].time, 1.0)))]
            if lo <= r.time <= hi and getattr(r, "uncertainty_pct", None) is not None] if len(readings) > 1 else []
    if bars:
        ax.errorbar([to_dt(r.time) for r in bars], [r.level_pct for r in bars], yerr=[r.uncertainty_pct for r in bars],
                    fmt="none", ecolor=CANDIDATE, elinewidth=1.3, capsize=4, capthick=1.3, alpha=0.9, zorder=4,
                    label="NEXT +/- uncertainty (I-bars every 30 min: |<- the level could be anywhere in here ->|)")
    ax.set_ylim(-5, 115)
    ax.set_ylabel("level %")
    if not zoom:
        ax.set_title("Tank level (left axis) and pressure (right axis, hPa)", loc="left", fontsize=12, fontweight="bold")

    twin = ax.twinx()
    shown = [(t, v) for t, v in pressure if lo <= t <= hi]
    twin.plot([to_dt(t) for t, _ in shown], [v for _, v in shown], PRESSURE_MARKER, ls="none", color="white",
              mfc=BACKGROUND, mew=1.1, ms=4, label=text["pressure"], zorder=6)
    if pressure:
        # One fixed scale for every panel, from zero: a zoom must not stretch pressure into a steeper slope.
        high = max(v for _, v in pressure)
        twin.set_ylim(min(0.0, min(v for _, v in pressure)) - high * 0.05, high * 1.15)
    twin.set_ylabel("pressure hPa (own scale, not a level)")
    return twin


def _hours_panel(ax, hours, baseline, text) -> None:
    rows = [("NEXT", hours, CANDIDATE, 1.0)]
    if baseline:
        rows.append(("PREV", baseline["hours"], BASELINE, 0.0))
    for name, row_hours, colour, y in rows:
        for i, h in enumerate(h for h in row_hours if h.get("uncertain")):
            ax.axvspan(to_dt(h["time"] - DIRECTION_WINDOW_S / 2), to_dt(h["time"] + DIRECTION_WINDOW_S / 2), ymin=(y + 0.6) / 2.2 - 0.18,
                       ymax=(y + 0.6) / 2.2 + 0.18, facecolor="none", edgecolor=RAW_DOTS, hatch="\\\\\\", lw=0, alpha=0.6,
                       label="hatched: the model's +/- was over its trust limit" if i == 0 and name == "NEXT" else None)
        for verdict in DISAGREEMENTS:
            marker, words = VERDICT_MARKERS[verdict]
            when = [to_dt(h["time"]) for h in row_hours if h["verdict"] == verdict]
            ax.plot(when, [y] * len(when), marker, ls="none", ms=9, mew=1.6, color=colour,
                    mfc=colour if marker != "o" else BACKGROUND,
                    label=f"{words}" if name == "NEXT" else None, zorder=4)
    ax.set_yticks([y for *_, y in rows], [n for n, *_ in rows])
    ax.set_ylim(-0.6, 1.6)
    ax.set_xlabel("Costa Rica time (each mark is one hour whose direction disagrees with pressure; no mark = agrees)")
    ax.set_title("Hours where the level moved differently from pressure (a mark on a hatched hour had a wide +/-)",
                 loc="left", fontsize=12, fontweight="bold")
    ax.legend(loc="upper left", fontsize=8.5, framealpha=0.85, ncols=4)
