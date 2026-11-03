"""Physics tests for the streaming tank model (no Home Assistant needed)."""
from __future__ import annotations

import math

import pytest

from custom_components.ultrasonic_tank.model import LowWaterAlarm, TankModel, TankParameters, TankReading

DEFAULTS = TankParameters()
PARAMS = TankParameters(publish_median_s=0.0)   # the gate and kinematics, without the output median (tested below)
FRAME_PERIOD_S = 0.5
TICK_S = 10.0
START_TIME = 1_000_000.0                        # 13:46 UTC: outside the default fill window


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


def settled_model(level_pct: float, settle_s: float = 1800.0, params: TankParameters = PARAMS,
                  start: float = START_TIME) -> tuple[TankModel, float]:
    """A model that has watched a steady surface long enough to publish it."""
    model = TankModel(params, {"surface_m": distance_for(level_pct), "level_pct": level_pct})
    target = distance_for(level_pct)
    run(model, start, settle_s, lambda t: target)
    return model, start + settle_s


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


REFLECTOR_LEVEL_PCT = 95.0                      # puts the surface on the stationary reflector


def test_a_fill_that_sweeps_up_to_the_reflector_may_end_there():
    """2026-11-03 05:30: the city fill ended at 0.21-0.25 m, inside the reflector band, and
    v0.2.1 ignored it for 80 min.  The frames swept up to the band on the way, which a
    reflector seen over a low tank never does (see test_reflector_is_ignored_on_a_low_tank)."""
    model, start = settled_model(5.0)
    readings = run(model, start, 90 * 60, truck_fill(start, 5.0, REFLECTOR_LEVEL_PCT))
    assert readings[-1].level_pct == pytest.approx(REFLECTOR_LEVEL_PCT, abs=FILL_TOLERANCE_PCT)
    assert readings[-1].surface_locked


def test_without_the_sweep_rule_a_fill_ending_on_the_reflector_is_ignored():
    """Control for the test above: the v0.2.1 behaviour."""
    no_sweep = TankParameters(publish_median_s=0.0, reflector_fill_sweep=False)
    model = TankModel(no_sweep, {"surface_m": distance_for(5.0), "level_pct": 5.0})
    run(model, START_TIME, 1800, lambda t: distance_for(5.0))
    start = START_TIME + 1800
    readings = run(model, start, 90 * 60, truck_fill(start, 5.0, REFLECTOR_LEVEL_PCT))
    assert not readings[-1].surface_locked


TRUE_LEVEL_PCT = 40.0                           # 2026-11-02 night: pressure said ~41 %
ECHO_LEVEL_PCT = 74.0                           # ...while a steady near echo said 74 %
DEEP_MULTIPATH_M = 0.6                          # deeper than the surface: rejected, so the model is blind
BLIND_S = 20 * 60                               # shorter than rise_support_timeout_s
ECHO_S = 30 * 60
WALK_UP_TOLERANCE_PCT = 5.0


def blind_then_echo(start: float):
    deep = distance_for(TRUE_LEVEL_PCT) + DEEP_MULTIPATH_M
    echo = distance_for(ECHO_LEVEL_PCT)
    return lambda t: deep if t < start + BLIND_S else echo


def test_near_echo_after_a_blind_spell_does_not_walk_the_level_up():
    model, start = settled_model(TRUE_LEVEL_PCT)
    readings = run(model, start, BLIND_S + ECHO_S, blind_then_echo(start))
    assert readings[-1].level_pct < TRUE_LEVEL_PCT + WALK_UP_TOLERANCE_PCT


def test_without_the_rise_rule_the_same_echo_walks_the_level_up():
    """Control for the test above: the v0.2.0 gate let the rise allowance grow with blind time."""
    unlimited = TankParameters(max_rise_gap_s=0.0, publish_median_s=0.0)
    model = TankModel(unlimited, {"surface_m": distance_for(TRUE_LEVEL_PCT), "level_pct": TRUE_LEVEL_PCT})
    run(model, START_TIME, BLIND_S, lambda t: distance_for(TRUE_LEVEL_PCT))
    start = START_TIME + BLIND_S
    readings = run(model, start, BLIND_S + ECHO_S, blind_then_echo(start))
    assert readings[-1].level_pct > ECHO_LEVEL_PCT - WALK_UP_TOLERANCE_PCT


LOW_LEVEL_PCT = 20.0
FILLED_LEVEL_PCT = 70.0
SPLASH_M = 0.05                                 # closer than min_valid_m: every frame is invalid
MISSED_FILL_BLIND_S = PARAMS.rise_support_timeout_s + 10 * 60
CATCH_UP_S = 40 * 60
FILL_TOLERANCE_PCT = 2.0


def test_a_fill_missed_while_blind_is_followed_once_the_timeout_passes():
    """The support rule must never latch: after rise_support_timeout_s blind, a far closer
    steady surface is accepted again (at the fill cap)."""
    model, start = settled_model(LOW_LEVEL_PCT)
    filled = distance_for(FILLED_LEVEL_PCT)
    readings = run(model, start, MISSED_FILL_BLIND_S + CATCH_UP_S,
                   lambda t: SPLASH_M if t < start + MISSED_FILL_BLIND_S else filled)
    assert readings[-1].level_pct == pytest.approx(FILLED_LEVEL_PCT, abs=FILL_TOLERANCE_PCT)
    assert readings[-1].surface_locked


STEADY_PCT = 60.0
EXCURSION_PCT = 70.0                            # a 15-min swing the gate accepts (an echo, or a splash)
EXCURSION_S = 15 * 60
SETTLE_S = 2 * 3600
DAMPED_PCT = 3.0


def excursion(start: float):
    """Ramps up at a fill's speed (so the gate accepts it), holds, then drops back."""
    def distance_at(t: float) -> float:
        if t >= start + EXCURSION_S:
            return distance_for(STEADY_PCT)
        return distance_for(min(STEADY_PCT + FILL_PCT_PER_MIN * (t - start) / 60.0, EXCURSION_PCT))
    return distance_at


def test_a_short_excursion_is_damped_by_the_published_median():
    model, start = settled_model(STEADY_PCT, SETTLE_S, DEFAULTS)
    readings = run(model, start, 2 * EXCURSION_S, excursion(start))
    assert max(r.level_pct for r in readings) < STEADY_PCT + DAMPED_PCT


def test_without_the_median_the_same_excursion_is_published():
    """Control for the test above."""
    model, start = settled_model(STEADY_PCT, SETTLE_S, PARAMS)
    readings = run(model, start, 2 * EXCURSION_S, excursion(start))
    assert max(r.level_pct for r in readings) > EXCURSION_PCT - DAMPED_PCT


DAY_S = 86400.0
CITY_FILL_START = START_TIME - START_TIME % DAY_S + 5.5 * 3600     # 05:30 local (UTC offset 0)
AFTERNOON_FILL_START = START_TIME - START_TIME % DAY_S + 14 * 3600
FILL_FROM_PCT, FILL_TO_PCT = 20.0, 70.0
FILL_PCT_PER_MIN = 2.0                          # under the fill cap
FILL_S = (FILL_TO_PCT - FILL_FROM_PCT) / FILL_PCT_PER_MIN * 60
AFTER_FILL_S = 10 * 60
FILL_SETTLE_S = 3600.0


def fill(start: float):
    return lambda t: distance_for(min(FILL_FROM_PCT + FILL_PCT_PER_MIN * max(t - start, 0.0) / 60.0, FILL_TO_PCT))


def fill_readings(fill_start: float) -> list[TankReading]:
    settle_start = fill_start - FILL_SETTLE_S
    model, start = settled_model(FILL_FROM_PCT, FILL_SETTLE_S, DEFAULTS, settle_start)
    return run(model, start, FILL_S + AFTER_FILL_S, fill(start))


def test_a_fill_in_the_usual_fill_hours_shows_promptly():
    readings = fill_readings(CITY_FILL_START)
    assert readings[-1].level_pct == pytest.approx(FILL_TO_PCT, abs=FILL_TOLERANCE_PCT)


def test_a_fill_outside_the_usual_hours_shows_late():
    """Accepted trade-off (owner, 2026-11-03): truck deliveries are rare, so they may lag."""
    readings = fill_readings(AFTERNOON_FILL_START)
    assert readings[-1].level_pct < FILL_TO_PCT - 10.0


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
