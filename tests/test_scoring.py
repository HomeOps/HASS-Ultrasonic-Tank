"""The replay's correlation scoring: pressure is compared by direction and rank, never as a level."""
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "tools"))

from tank_replay.recordings import RAW_ENTITY, REFERENCE_ENTITY, load_series  # noqa: E402
from tank_replay.scoring import (AGREE, FALSE_MOVE, LEVEL_FLAT_PTS, LEVEL_MOVE_PTS, MISSED_MOVE,  # noqa: E402
                                 PRESSURE_FLAT_HPA, PRESSURE_MOVE_HPA, WRONG_WAY, classify, compare, spearman)

CLEAR_PRESSURE_RISE_HPA = PRESSURE_MOVE_HPA * 2
CLEAR_LEVEL_RISE_PTS = LEVEL_MOVE_PTS * 2
STILL_PRESSURE_HPA = PRESSURE_FLAT_HPA / 2
STILL_LEVEL_PTS = LEVEL_FLAT_PTS / 2
SMALL_LEVEL_RISE_PTS = (LEVEL_FLAT_PTS + LEVEL_MOVE_PTS) / 2      # in the gap: too small to call
DERIVED_PERCENT_ENTITY = "sensor.aboveground_water_tank_level"
ONE_HOUR_S = 3600.0


def test_both_rising_agree():
    assert classify(CLEAR_PRESSURE_RISE_HPA, CLEAR_LEVEL_RISE_PTS) == AGREE


def test_level_moving_while_pressure_holds_is_a_false_move():
    assert classify(STILL_PRESSURE_HPA, CLEAR_LEVEL_RISE_PTS) == FALSE_MOVE


def test_pressure_moving_while_level_holds_is_a_missed_move():
    assert classify(-CLEAR_PRESSURE_RISE_HPA, STILL_LEVEL_PTS) == MISSED_MOVE


def test_opposite_directions_are_wrong_way():
    assert classify(-CLEAR_PRESSURE_RISE_HPA, CLEAR_LEVEL_RISE_PTS) == WRONG_WAY


def test_a_change_too_small_to_call_agrees():
    assert classify(CLEAR_PRESSURE_RISE_HPA, SMALL_LEVEL_RISE_PTS) == AGREE


def test_rank_correlation_ignores_units_and_scale():
    pressure_hpa = [10.0, 40.0, 90.0, 200.0]
    level_pct = [1.0, 2.0, 3.0, 99.0]           # same order, unrelated scale
    assert spearman(pressure_hpa, level_pct) == pytest.approx(1.0)
    assert spearman(pressure_hpa, list(reversed(level_pct))) == pytest.approx(-1.0)


def test_compare_counts_hours_fixed_and_broken():
    base = [{"time": 0.0, "verdict": FALSE_MOVE}, {"time": ONE_HOUR_S, "verdict": AGREE}]
    candidate = [{"time": 0.0, "verdict": AGREE}, {"time": ONE_HOUR_S, "verdict": WRONG_WAY}]
    assert compare(base, candidate) == {"better": 1, "worse": 1, "same": 0}


def test_only_raw_distance_and_hpa_may_be_read(tmp_path):
    with pytest.raises(SystemExit):
        load_series(tmp_path, None, None, {"reference": DERIVED_PERCENT_ENTITY})


def test_a_value_in_the_wrong_unit_is_refused(tmp_path):
    distance_in_mm = "845"
    (tmp_path / "2026-11-08.csv").write_text(
        f'"Time","EntityId","State"\n"2026-11-08T00:00:00.000-06:00","{RAW_ENTITY}","{distance_in_mm}"\n', encoding="utf-8")
    with pytest.raises(SystemExit):
        load_series(tmp_path, None, None, {"raw": RAW_ENTITY, "reference": REFERENCE_ENTITY})
