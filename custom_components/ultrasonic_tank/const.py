"""Constants for the Ultrasonic Tank integration."""
from __future__ import annotations

from .model import TankParameters

DOMAIN = "ultrasonic_tank"
PLATFORMS = ["sensor", "binary_sensor"]

CONF_RAW_ENTITY = "raw_entity"
CONF_CAPACITY_L = "capacity_l"
CONF_FLOOR_M = "floor_m"
CONF_FULL_M = "full_m"
CONF_DRAIN_COEFFICIENT = "drain_coefficient"
CONF_MAX_FILL_PCT_PER_MIN = "max_fill_pct_per_min"
CONF_NOISE_M = "noise_m"
CONF_MAX_ACCEL_PCT_PER_MIN2 = "max_accel_pct_per_min2"
CONF_VELOCITY_TAU_MIN = "velocity_tau_min"
CONF_REFLECTOR_M = "reflector_m"
CONF_REFLECTOR_HALF_WIDTH_M = "reflector_half_width_m"
CONF_LOW_WATER_PCT = "low_water_pct"
CONF_LOW_WATER_MAX_COAST_MIN = "low_water_max_coast_min"
CONF_LOW_WATER_DELAY_MIN = "low_water_delay_min"
CONF_BOOTSTRAP_HOURS = "bootstrap_hours"

_DEFAULTS = TankParameters()

# Keys that map 1:1 onto TankParameters fields.
MODEL_KEYS = {
    CONF_CAPACITY_L: _DEFAULTS.capacity_l,
    CONF_FLOOR_M: _DEFAULTS.floor_m,
    CONF_FULL_M: _DEFAULTS.full_m,
    CONF_DRAIN_COEFFICIENT: _DEFAULTS.drain_coefficient,
    CONF_MAX_FILL_PCT_PER_MIN: _DEFAULTS.max_fill_pct_per_min,
    CONF_NOISE_M: _DEFAULTS.noise_m,
    CONF_MAX_ACCEL_PCT_PER_MIN2: _DEFAULTS.max_accel_pct_per_min2,
    CONF_VELOCITY_TAU_MIN: _DEFAULTS.velocity_tau_min,
    CONF_REFLECTOR_M: _DEFAULTS.reflector_m,
    CONF_REFLECTOR_HALF_WIDTH_M: _DEFAULTS.reflector_half_width_m,
}

DEFAULT_NAME = "Water tank"
DEFAULT_LOW_WATER_PCT = 25.0
DEFAULT_LOW_WATER_MAX_COAST_MIN = 30.0
DEFAULT_LOW_WATER_DELAY_MIN = 15.0
DEFAULT_BOOTSTRAP_HOURS = 12.0      # first install: replay this much recorder history from "empty"

TICK_SECONDS = 10
SAVE_DELAY_SECONDS = 60
STORAGE_VERSION = 1
