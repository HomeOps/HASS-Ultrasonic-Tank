"""Read the recorded data: daily CSVs (one per local day) and the owner's level spans."""
from __future__ import annotations

import csv
from datetime import date, datetime, timezone
from pathlib import Path

# The only two inputs, both raw instrument readings. Nothing derived (no % made from
# pressure) is ever read: pressure and distance are different physics, and a % made
# from pressure was once mistaken for the true level (2026-11-08).
RAW_ENTITY = "sensor.driveway_water_tank_sensor_tank_distance_raw"       # m, the model input
REFERENCE_ENTITY = "sensor.aboveground_water_tank_pressure"              # hPa, correlation only
PLAUSIBLE = {RAW_ENTITY: (0.0, 10.0), REFERENCE_ENTITY: (-50.0, 600.0)}  # a value outside is the wrong unit
LEGACY_TIME_FORMAT = "%Y-%m-%dT%H:%M:%S.%fZ"    # the old TimeUtc column
DAILY_FILE_GLOB = "????-??-??.csv"              # annotations and other files differ in format
ANNOTATIONS_FILE = "reference-annotations.csv"


def parse_time(row: dict) -> float:
    """Epoch seconds of a recorded row: ``Time`` is local ISO 8601 with offset; ``TimeUtc`` is the old UTC form."""
    if "Time" in row:
        return datetime.fromisoformat(row["Time"]).timestamp()
    return datetime.strptime(row["TimeUtc"], LEGACY_TIME_FORMAT).replace(tzinfo=timezone.utc).timestamp()


def load_series(folder: Path, from_day: date | None, to_day: date | None, entities: dict[str, str]) -> dict:
    """{role: [(time, value)]} for each role -> entity, numeric states only, plus "files".

    Only the raw distance (m) and the raw pressure (hPa) may be read."""
    for entity in entities.values():
        if entity not in PLAUSIBLE:
            raise SystemExit(f"{entity}: only {RAW_ENTITY} (m) and {REFERENCE_ENTITY} (hPa) may be read")
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
    for role, points in series.items():
        points.sort()
        low, high = PLAUSIBLE[entities[role]]
        bad = [v for _, v in points if not low <= v <= high]
        if bad:
            raise SystemExit(f"{entities[role]}: {len(bad)} values outside {low}..{high}, e.g. {bad[0]}; wrong unit?")
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
