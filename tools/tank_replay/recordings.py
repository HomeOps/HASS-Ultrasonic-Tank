"""Read the recorded data: daily CSVs (one per local day) and the owner's truth spans."""
from __future__ import annotations

import csv
from datetime import date, datetime, timezone
from pathlib import Path

RAW_ENTITY = "sensor.driveway_water_tank_sensor_tank_distance_raw"
REFERENCE_ENTITY = "sensor.aboveground_water_tank_level"
LIVE_ENTITY = "sensor.water_tank_level"
LEGACY_TIME_FORMAT = "%Y-%m-%dT%H:%M:%S.%fZ"    # the old TimeUtc column
DAILY_FILE_GLOB = "????-??-??.csv"              # annotations and other files differ in format
ANNOTATIONS_FILE = "reference-annotations.csv"
ANNOTATION_STEP_S = 15 * 60                     # an owner truth span is scored every 15 min


def parse_time(row: dict) -> float:
    """Epoch seconds of a recorded row: ``Time`` is local ISO 8601 with offset; ``TimeUtc`` is the old UTC form."""
    if "Time" in row:
        return datetime.fromisoformat(row["Time"]).timestamp()
    return datetime.strptime(row["TimeUtc"], LEGACY_TIME_FORMAT).replace(tzinfo=timezone.utc).timestamp()


def load_series(folder: Path, from_day: date | None, to_day: date | None, entities: dict[str, str]) -> dict:
    """{role: [(time, value)]} for each role -> entity, numeric states only, plus "files"."""
    files = sorted(folder.glob(DAILY_FILE_GLOB))
    if from_day:
        files = [f for f in files if f.stem >= from_day.isoformat()]
    if to_day:
        files = [f for f in files if f.stem <= to_day.isoformat()]
    if not files:
        raise SystemExit(f"no CSV files in {folder} for the requested days")
    wanted = {entity: role for role, entity in entities.items()}
    series: dict = {role: [] for role in entities}
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
                series[role].append((parse_time(row), value))
    for points in series.values():
        points.sort()
    series["files"] = [f.name for f in files]
    return series


def load_annotations(folder: Path, first: float, last: float) -> list[dict]:
    """Owner truth spans from reference-annotations.csv, clipped to the replayed frames."""
    path = folder / ANNOTATIONS_FILE
    if not path.exists():
        return []
    spans = []
    with open(path, newline="", encoding="utf-8-sig") as handle:
        for row in csv.DictReader(handle):
            start = datetime.fromisoformat(row["Start"]).timestamp()
            end = datetime.fromisoformat(row["End"]).timestamp()
            if end < first or start > last:
                continue
            spans.append({"start": max(start, first), "end": min(end, last),
                          "min": float(row["MinPct"]), "max": float(row["MaxPct"]), "source": row["Source"]})
    return spans


def truth_samples(reference: list[tuple[float, float]], annotations: list[dict]) -> list[tuple[float, float, float]]:
    """(time, low, high) truth: a pressure sample is a point; an owner span is sampled every ANNOTATION_STEP_S."""
    truth = [(t, v, v) for t, v in reference]
    for span in annotations:
        t = span["start"]
        while t <= span["end"]:
            truth.append((t, span["min"], span["max"]))
            t += ANNOTATION_STEP_S
    truth.sort()
    return truth
