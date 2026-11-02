"""Kinematic level model for an ultrasonic sensor looking down into a gravity-drained tank.

Pure Python, no Home Assistant imports, so it can be unit-tested and replayed
against recorded raw frames.

Physics
-------
An ultrasonic sensor in a tank returns many echoes: the water surface, fixed
reflectors (a ladder, a fitting), and multipath that is always *deeper* than the
surface.  No single statistic of a window of readings picks the surface in every
regime.  The surface, however, obeys kinematics:

* it can FALL no faster than gravity drains the tank (Torricelli:
  ``dL/dt = -2 * b * sqrt(L)``),
* it can RISE no faster than the fastest fill,
* its acceleration is always small.

Every frame is checked against the LAST VALID frame (position, velocity and
timestamp).  A frame that breaks the velocity or the acceleration cap is a
reflection and is discarded.  The rise allowance stops growing after
``max_rise_gap_s`` unseen: a larger rise is accepted only when recent frames
cover the distances in between (a fill sweeps through them, a near echo does
not), or after ``rise_support_timeout_s`` blind, so a missed fill never latches.
The published level integrates a velocity clamped
to the same envelope, so it never teleports.  While the surface is not visible
the estimate coasts along the last *drain* velocity; it never invents a fill.

Units: distances in metres, times in seconds (epoch), level in percent of the
usable span, volume in litres, flow in L/min, change in flow in L/min^2.
"""
from __future__ import annotations

from collections import deque
from dataclasses import asdict, dataclass, field
import math
from typing import Any


@dataclass(frozen=True)
class TankParameters:
    """Geometry and kinematic caps.  Defaults are the v9 fit (2026-11-01)."""

    floor_m: float = 2.05                   # sensor-to-water distance when empty
    full_m: float = 0.15                    # sensor-to-water distance at 100 %
    capacity_l: float = 5000.0              # litres at 100 %
    drain_coefficient: float = 0.002        # b in dL/dt = -2 b sqrt(L), L as a fraction
    max_fill_pct_per_min: float = 2.5       # fastest rise; higher latches the top reflector
    noise_m: float = 0.02                   # per-frame tolerance
    max_accel_pct_per_min2: float = 1.0     # largest change in velocity
    velocity_tau_min: float = 2.0           # velocity smoothing
    reflector_m: float = 0.245              # the stationary reflector; <= 0 disables
    reflector_half_width_m: float = 0.05
    min_valid_m: float = 0.15               # closer = splash at the sensor
    max_valid_m: float = 3.0                # farther = the sensor's no-target code
    lock_window_s: float = 120.0            # a frame this recent = surface locked
    flow_window_s: float = 120.0            # trailing mean for net flow
    change_window_s: float = 300.0          # trailing mean for change in flow
    max_rise_gap_s: float = 120.0           # rise allowance stops growing after this long unseen; <= 0 = unlimited
    rise_support_window_s: float = 1800.0   # a larger rise needs frames between, seen this recently
    rise_support_bin_m: float = 0.05        # the gap is checked in bins this wide
    rise_support_fraction: float = 0.6      # share of bins that must hold a frame
    rise_support_timeout_s: float = 3600.0  # blind longer than this: the support rule is lifted, so a missed fill cannot latch

    @property
    def span_m(self) -> float:
        return self.floor_m - self.full_m

    @property
    def litres_per_pct(self) -> float:
        return self.capacity_l / 100.0

    @property
    def max_inflow_lpm(self) -> float:
        return self.max_fill_pct_per_min * self.litres_per_pct

    def max_fall_pct_per_min(self, level_pct: float) -> float:
        """Torricelli drain limit at this level, with a small floor so an empty tank still settles."""
        floor = 0.002 / self.span_m * 100.0
        return max(2.0 * self.drain_coefficient * math.sqrt(max(level_pct / 100.0, 0.0)) * 100.0, floor)


@dataclass(frozen=True)
class TankReading:
    """One published model state."""

    time: float
    level_pct: float
    volume_l: float
    net_flow_lpm: float
    flow_change_lpm2: float
    surface_m: float
    surface_locked: bool
    seconds_since_surface: float | None
    max_outflow_lpm: float
    max_inflow_lpm: float


@dataclass
class _State:
    surface_m: float
    velocity_m_per_min: float = 0.0     # + = draining (distance growing)
    last_valid: float | None = None     # epoch of the last accepted frame
    has_lock: bool = False              # a frame has been accepted
    level_pct: float | None = None      # published level
    last_tick: float | None = None
    prev_flow_lpm: float | None = None
    flow_samples: list[float] = field(default_factory=list)
    change_samples: list[float] = field(default_factory=list)


class TankModel:
    """Streaming model: feed every raw frame with ``add_frame``, publish with ``tick``."""

    def __init__(self, params: TankParameters | None = None, state: dict[str, Any] | None = None) -> None:
        self.params = params or TankParameters()
        self._s = _State(surface_m=self.params.floor_m)
        if state:
            self._restore(state)
        self._flow: deque[float] = deque(self._s.flow_samples, maxlen=self._window(self.params.flow_window_s))
        self._change: deque[float] = deque(self._s.change_samples, maxlen=self._window(self.params.change_window_s))
        self._recent: deque[tuple[float, float]] = deque()   # (time, distance) of valid frames, for rise support

    # ------------------------------------------------------------------ frames
    def add_frame(self, time: float, distance_m: float) -> bool:
        """Gate one raw frame.  Returns True when it was accepted as the surface."""
        p, s = self.params, self._s
        if not (p.min_valid_m <= distance_m <= p.max_valid_m):
            return False
        if s.last_valid is None:            # first frame only starts the clock
            s.last_valid = time
            return False
        x = min(distance_m, p.floor_m)      # beyond-floor echoes are the floor
        if p.max_rise_gap_s > 0:
            self._recent.append((time, x))
            while self._recent and self._recent[0][0] < time - p.rise_support_window_s:
                self._recent.popleft()
        if (p.reflector_m > 0
                and s.surface_m > p.reflector_m + p.reflector_half_width_m + 0.05
                and abs(x - p.reflector_m) < p.reflector_half_width_m):
            return False                    # the stationary reflector, unless already near full
        dt = (time - s.last_valid) / 60.0
        if dt <= 0:
            return False

        span = p.span_m
        fill_max = p.max_fill_pct_per_min / 100.0 * span
        accel_max = p.max_accel_pct_per_min2 / 100.0 * span
        level_frac = max((p.floor_m - s.surface_m) / span, 0.0)
        drain_max = max(2.0 * p.drain_coefficient * math.sqrt(level_frac) * span, 0.002)

        if not (s.surface_m - fill_max * dt - p.noise_m <= x <= s.surface_m + drain_max * dt + p.noise_m):
            return False                    # velocity cap
        if (p.max_rise_gap_s > 0
                and dt * 60.0 < p.rise_support_timeout_s    # blind this long: fall back, never latch
                and x < s.surface_m - fill_max * min(dt, p.max_rise_gap_s / 60.0) - p.noise_m
                and not self._rise_supported(x, s.surface_m)):
            return False                    # a rise after a long gap must have been seen on the way
        predicted = s.surface_m + s.velocity_m_per_min * dt
        if abs(x - predicted) > p.noise_m + 0.5 * accel_max * dt * dt:
            return False                    # acceleration cap

        new_surface = min(max(x, s.surface_m - fill_max * dt), s.surface_m + drain_max * dt)
        velocity = s.velocity_m_per_min + ((new_surface - s.surface_m) / dt - s.velocity_m_per_min) * min(1.0, dt / p.velocity_tau_min)
        s.velocity_m_per_min = min(max(velocity, -fill_max), drain_max)
        s.surface_m = min(max(new_surface, p.full_m), p.floor_m)
        s.last_valid = time
        s.has_lock = True
        return True

    # ------------------------------------------------------------------- ticks
    def tick(self, time: float) -> TankReading:
        """Advance the published level to ``time`` and return it."""
        p, s = self.params, self._s
        since_min = 0.0 if s.last_valid is None else max(time - s.last_valid, 0.0) / 60.0
        projected = s.surface_m + max(s.velocity_m_per_min, 0.0) * since_min      # coast only along a drain
        projected = min(max(projected, p.full_m), p.floor_m)
        belief = (p.floor_m - projected) / p.span_m * 100.0

        velocity_pct = 0.0
        if s.level_pct is None or s.last_tick is None:
            level = belief
        else:
            dt = max(time - s.last_tick, 0.0) / 60.0
            level = s.level_pct
            if dt > 0:
                velocity_pct = min(max((belief - level) / dt, -p.max_fall_pct_per_min(level)), p.max_fill_pct_per_min)
                level = min(max(level + velocity_pct * dt, 0.0), 100.0)
        tick_min = None if s.last_tick is None else max(time - s.last_tick, 0.0) / 60.0
        s.level_pct, s.last_tick = level, time

        self._flow.append(velocity_pct * p.litres_per_pct)
        flow = sum(self._flow) / len(self._flow)
        change = 0.0 if s.prev_flow_lpm is None or not tick_min else (flow - s.prev_flow_lpm) / tick_min
        s.prev_flow_lpm = flow
        self._change.append(change)

        seconds_since = None if not s.has_lock or s.last_valid is None else max(time - s.last_valid, 0.0)
        return TankReading(
            time=time,
            level_pct=level,
            volume_l=level * p.litres_per_pct,
            net_flow_lpm=flow,
            flow_change_lpm2=sum(self._change) / len(self._change),
            surface_m=p.floor_m - level / 100.0 * p.span_m,
            surface_locked=seconds_since is not None and seconds_since <= p.lock_window_s,
            seconds_since_surface=seconds_since,
            max_outflow_lpm=p.max_fall_pct_per_min(level) * p.litres_per_pct,
            max_inflow_lpm=p.max_inflow_lpm,
        )

    # ------------------------------------------------------------ persistence
    def to_dict(self) -> dict[str, Any]:
        """Serialisable state, for Home Assistant's storage."""
        self._s.flow_samples = list(self._flow)
        self._s.change_samples = list(self._change)
        return asdict(self._s)

    def _restore(self, state: dict[str, Any]) -> None:
        known = {k: v for k, v in state.items() if k in _State.__dataclass_fields__}
        self._s = _State(**{"surface_m": self.params.floor_m, **known})
        self._s.surface_m = min(max(self._s.surface_m, self.params.full_m), self.params.floor_m)

    def _rise_supported(self, target_m: float, surface_m: float) -> bool:
        """True when recent frames cover the distances between the surface and a closer target.

        A real fill sweeps the surface through every distance on the way up, so
        frames land in between.  A multipath echo appears at its own distance
        with nothing in between.
        """
        p = self.params
        bins = max(1, int(math.ceil((surface_m - target_m) / p.rise_support_bin_m)))
        seen = set()
        for _, x in self._recent:
            if target_m < x < surface_m:
                seen.add(min(int((surface_m - x) / p.rise_support_bin_m), bins - 1))
        return len(seen) / bins >= p.rise_support_fraction

    def _window(self, seconds: float, tick_s: float = 10.0) -> int:
        return max(1, int(round(seconds / tick_s)))

    @property
    def has_lock(self) -> bool:
        return self._s.has_lock


class LowWaterAlarm:
    """Low-water flag that a coasted estimate can neither raise nor clear.

    ON once the level has stayed below ``threshold_pct`` for ``delay_s`` while
    the surface was seen within ``max_coast_s``.  While the model is coasting
    longer than that, the flag holds its last value: a blind estimate must never
    announce an empty tank (or hide one).
    """

    def __init__(self, threshold_pct: float = 25.0, max_coast_s: float = 1800.0, delay_s: float = 900.0) -> None:
        self.threshold_pct, self.max_coast_s, self.delay_s = threshold_pct, max_coast_s, delay_s
        self.is_on: bool | None = None
        self._low_since: float | None = None

    def update(self, reading: TankReading) -> bool | None:
        seen = reading.seconds_since_surface
        if seen is None or seen > self.max_coast_s:
            return self.is_on                       # blind: hold
        if reading.level_pct < self.threshold_pct:
            if self._low_since is None:
                self._low_since = reading.time
            if reading.time - self._low_since >= self.delay_s:
                self.is_on = True
            elif self.is_on is None:
                self.is_on = False
        else:
            self._low_since = None
            self.is_on = False
        return self.is_on
