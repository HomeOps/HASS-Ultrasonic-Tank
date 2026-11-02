"""Physics tests for the streaming tank model (no Home Assistant needed)."""
from __future__ import annotations

import math

import pytest

from custom_components.ultrasonic_tank.model import LowWaterAlarm, TankModel, TankParameters, TankReading

PARAMS = TankParameters()
FRAME_PERIOD_S = 0.5
TICK_S = 10.0
START_TIME = 1_000_000.0


def distance_for(level_pct: float, params: TankParameters = PARAMS) -> float:
    return params.floor_m - level_pct / 100.0 * params.span_m


def run(model: TankModel, start: float, seconds: float, distance_at) -> list[TankReading]:
    """Feed frames every FRAME_PERIOD_S and tick every TICK_S; distance_at(t) -> metres."""
    readings, time, next_tick = [], start, start + TICK_S
    while time < start + seconds:
        model.add_frame(time, distance_at(time))
        time += FRAME_PERIOD_S
        if time >= next_tick:
            readings.append(model.tick(next_tick))
            next_tick += TICK_S
    return readings


def torricelli_level(start_pct: float, minutes: float, params: TankParameters = PARAMS) -> float:
    root = math.sqrt(start_pct / 100.0) - params.drain_coefficient * minutes
    return 100.0 * max(root, 0.0) ** 2


def settled_model(level_pct: float, settle_s: float = 1800.0) -> tuple[TankModel, float]:
    """A model that has watched a steady surface long enough to publish it."""
    model = TankModel(PARAMS, {"surface_m": distance_for(level_pct), "level_pct": level_pct})
    target = distance_for(level_pct)
    run(model, START_TIME, settle_s, lambda t: target)
    return model, START_TIME + settle_s


def test_empty_tank_reads_empty():
    floor_echo = PARAMS.floor_m + 0.1           # beyond-floor echoes count as the floor
    readings = run(TankModel(), START_TIME, 600, lambda t: floor_echo)
    assert readings[-1].level_pct == pytest.approx(0.0, abs=0.01)
    assert readings[-1].volume_l == pytest.approx(0.0, abs=1)


def test_tracks_a_torricelli_drain():
    model, start = settled_model(80.0)
    minutes = 120.0
    readings = run(model, start, minutes * 60, lambda t: distance_for(torricelli_level(80.0, (t - start) / 60.0)))
    assert readings[-1].level_pct == pytest.approx(torricelli_level(80.0, minutes), abs=1.5)
    assert readings[-1].net_flow_lpm < 0


def test_published_flow_never_leaves_the_physical_envelope():
    model, start = settled_model(60.0)
    # garbage: alternating surface, reflector and deep multipath
    echoes = [distance_for(60.0), PARAMS.reflector_m, 1.2, 0.6, distance_for(60.0)]
    readings = run(model, start, 3600, lambda t: echoes[int(t / FRAME_PERIOD_S) % len(echoes)])
    for reading in readings:
        assert reading.net_flow_lpm >= -reading.max_outflow_lpm - 1e-6
        assert reading.net_flow_lpm <= reading.max_inflow_lpm + 1e-6


def test_deep_multipath_is_rejected():
    model, start = settled_model(70.0)
    multipath = distance_for(70.0) + 0.6       # always deeper than the surface
    readings = run(model, start, 600, lambda t: multipath)
    assert readings[-1].level_pct == pytest.approx(70.0, abs=1.0)


def test_reflector_is_ignored_on_a_low_tank():
    model, start = settled_model(10.0)
    readings = run(model, start, 3600, lambda t: PARAMS.reflector_m)
    assert readings[-1].level_pct < 12.0       # never jumps to "full"


TRUCK_PCT_PER_MIN = 6.0                         # Saturday's truck: empty -> full in ~15 min


def truck_fill(start: float, from_pct: float, to_pct: float):
    return lambda t: distance_for(min(from_pct + TRUCK_PCT_PER_MIN * (t - start) / 60.0, to_pct))


def test_truck_fill_is_rate_limited_then_reaches_the_level():
    model, start = settled_model(5.0)
    readings = run(model, start, 90 * 60, truck_fill(start, 5.0, 85.0))
    for before, after in zip(readings, readings[1:]):
        assert after.level_pct - before.level_pct <= PARAMS.max_fill_pct_per_min * TICK_S / 60.0 + 1e-6
    assert readings[-1].level_pct == pytest.approx(85.0, abs=2.0)
    assert readings[-1].surface_locked


def test_known_limit_fast_fill_ending_on_the_reflector_is_not_trusted():
    """95 % puts the surface on the stationary reflector.  A clean fill faster than the cap
    is never accepted, and no statistic separates "full" from "reflector over a low tank"
    (a reflector-only run lasted 78 min at 50 % in the field data).  The model must then
    report that it is NOT locked, so nothing downstream trusts the stale level."""
    model, start = settled_model(5.0)
    readings = run(model, start, 90 * 60, truck_fill(start, 5.0, 95.0))
    assert not readings[-1].surface_locked


def test_coasts_only_along_a_drain():
    model, start = settled_model(50.0)
    run(model, start, 1800, lambda t: distance_for(torricelli_level(50.0, (t - start) / 60.0)))
    before = model.tick(start + 1800)
    after = model.tick(start + 1800 + 3600)    # blind for an hour
    assert after.level_pct <= before.level_pct
    assert not after.surface_locked


def test_state_round_trip_restores_the_published_level():
    model, start = settled_model(42.0)
    restored = TankModel(PARAMS, model.to_dict())
    assert restored.tick(start + TICK_S).level_pct == pytest.approx(model.tick(start + TICK_S).level_pct, abs=1e-6)


def test_volume_and_level_agree():
    model, start = settled_model(37.0)
    reading = model.tick(start + TICK_S)
    assert reading.volume_l == pytest.approx(reading.level_pct * PARAMS.capacity_l / 100.0)


def test_out_of_range_frames_are_ignored():
    model = TankModel()
    assert not model.add_frame(START_TIME, 0.05)       # splash at the sensor
    assert not model.add_frame(START_TIME + 1, 6.5)    # no-target code
    assert not model.has_lock


class TestLowWaterAlarm:
    threshold = 25.0
    delay_s = 900.0
    max_coast_s = 1800.0

    def reading(self, time: float, level: float, seen: float | None) -> TankReading:
        return TankReading(time, level, level * 50, 0.0, 0.0, 1.0, seen is not None and seen < 120, seen, 10.0, 125.0)

    def alarm(self) -> LowWaterAlarm:
        return LowWaterAlarm(self.threshold, self.max_coast_s, self.delay_s)

    def test_turns_on_after_the_delay_while_seen(self):
        alarm = self.alarm()
        assert alarm.update(self.reading(0, 10, 5)) is False
        assert alarm.update(self.reading(self.delay_s, 10, 5)) is True

    def test_coasted_estimate_cannot_raise_it(self):
        alarm = self.alarm()
        alarm.update(self.reading(0, 50, 5))
        for minute in range(0, 120):
            alarm.update(self.reading(minute * 60, 5, self.max_coast_s + 60))
        assert alarm.is_on is False

    def test_coasted_estimate_cannot_clear_it(self):
        alarm = self.alarm()
        alarm.update(self.reading(0, 10, 5))
        alarm.update(self.reading(self.delay_s, 10, 5))
        assert alarm.update(self.reading(self.delay_s + 60, 90, self.max_coast_s + 60)) is True

    def test_clears_when_the_level_recovers(self):
        alarm = self.alarm()
        alarm.update(self.reading(0, 10, 5))
        alarm.update(self.reading(self.delay_s, 10, 5))
        assert alarm.update(self.reading(self.delay_s + 60, 60, 5)) is False
