"""Look of the PREV vs NEXT chart: dark mode, colour-blind safe (line style and marker, not hue)."""
from __future__ import annotations

from datetime import datetime, timezone

BACKGROUND = "#111418"
CANDIDATE = "#56B4E9"               # Okabe-Ito sky blue, bright on dark
BASELINE = "#9a9a9a"
BASELINE_OFFSET_PTS = 4.0           # PREV is drawn this much higher, so it never hides NEXT
RAW_DOTS = "#7d8590"               # mid grey: visible on the background, dimmer than PREV's line
DASHED = (0, (6, 3))
REFERENCE_GAP_S = 3 * 3600          # no line is drawn across a truth gap this long
DAY_TICKS_ABOVE_DAYS = 4            # longer replays get one tick per day, shorter ones hours


def to_dt(when: float) -> datetime:
    return datetime.fromtimestamp(when, timezone.utc)


def with_gaps(points: list[tuple[float, float]]) -> list[tuple[float, float]]:
    """Insert a NaN where the truth had no data for a long time, so no line is drawn across it."""
    out = []
    for i, (t, v) in enumerate(points):
        if i and t - points[i - 1][0] > REFERENCE_GAP_S:
            out.append((t - 1, float("nan")))
        out.append((t, v))
    return out


def labels(summary: dict, has_baseline: bool) -> dict:
    """Legend text for each series. The style is named in words, so no colour is needed to read it."""
    candidate = "NEXT: this change, not released yet (thick bright solid)" if has_baseline else "model.py (thick bright solid)"
    if summary["overrides"]:
        candidate += " [" + ", ".join(summary["overrides"]) + "]"
    ref = has_baseline and summary["baseline"]["ref"]
    baseline = f"PREV: {ref}, the release installed now (grey dashed)" if ref else "PREV (grey dashed)"
    baseline += f", drawn {BASELINE_OFFSET_PTS:.0f} pts higher so it never hides NEXT"
    if has_baseline and summary["baseline"]["overrides"]:
        baseline += " [" + ", ".join(summary["baseline"]["overrides"]) + "]"
    return {"candidate": candidate, "baseline": baseline, "baseline_ref": ref,
            "truth": "TRUTH: pressure sensor (hollow diamonds)"}


def apply_theme(plt) -> None:
    plt.style.use("dark_background")
    plt.rcParams.update({"font.size": 10, "figure.facecolor": BACKGROUND, "axes.facecolor": BACKGROUND, "savefig.facecolor": BACKGROUND,
                         # Deterministic SVG ids, so a chart file changes only when the model or data does
                         # and its git history stays readable.
                         "svg.hashsalt": "hass-ultrasonic-tank"})


# No creation date in the file, for the same reason.
SAVE_METADATA = {"Date": None}


def time_axis(ax, mdates, local, start: float, end: float) -> None:
    """Day ticks for long replays, every 3-6 hours (with the date) for a window of a few days."""
    span_days = (end - start) / 86400.0
    if span_days > DAY_TICKS_ABOVE_DAYS:
        ax.xaxis.set_major_locator(mdates.DayLocator(tz=local))
        ax.xaxis.set_major_formatter(mdates.DateFormatter("%b %d", tz=local))
    else:
        ax.xaxis.set_major_locator(mdates.HourLocator(byhour=range(0, 24, 3 if span_days <= 1.5 else 6), tz=local))
        ax.xaxis.set_major_formatter(mdates.DateFormatter("%b %d\n%H:%M", tz=local))
    ax.set_xlim(to_dt(start), to_dt(end))
