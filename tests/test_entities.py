"""Units, device classes and config-flow validation."""
from __future__ import annotations

import json
from pathlib import Path

from homeassistant.components.sensor import SensorDeviceClass, SensorStateClass
from homeassistant.const import PERCENTAGE, UnitOfLength, UnitOfVolume, UnitOfVolumeFlowRate

from custom_components.ultrasonic_tank.config_flow import _geometry_errors
from custom_components.ultrasonic_tank.const import CONF_FLOOR_M, CONF_FULL_M, MODEL_KEYS
from custom_components.ultrasonic_tank.hub import build_parameters
from custom_components.ultrasonic_tank.model import TankParameters
from custom_components.ultrasonic_tank.sensor import SENSORS

COMPONENT = Path(__file__).parent.parent / "custom_components" / "ultrasonic_tank"


def sensor(key: str):
    return next(description for description in SENSORS if description.key == key)


def test_volume_is_stored_litres():
    volume = sensor("volume")
    assert volume.device_class == SensorDeviceClass.VOLUME_STORAGE
    assert volume.native_unit_of_measurement == UnitOfVolume.LITERS
    assert volume.state_class == SensorStateClass.MEASUREMENT


def test_net_flow_is_litres_per_minute():
    flow = sensor("net_flow")
    assert flow.device_class == SensorDeviceClass.VOLUME_FLOW_RATE
    assert flow.native_unit_of_measurement == UnitOfVolumeFlowRate.LITERS_PER_MINUTE


def test_flow_change_and_level_and_distance_units():
    assert sensor("flow_change").native_unit_of_measurement == "L/min²"
    assert sensor("level").native_unit_of_measurement == PERCENTAGE
    assert sensor("surface_distance").native_unit_of_measurement == UnitOfLength.METERS


def test_every_entity_has_a_translated_name():
    strings = json.loads((COMPONENT / "strings.json").read_text(encoding="utf-8"))
    for description in SENSORS:
        assert description.key in strings["entity"]["sensor"]
    assert {"surface_locked", "level_uncertain", "low_water"} <= set(strings["entity"]["binary_sensor"])


def test_translations_match_strings():
    strings = (COMPONENT / "strings.json").read_text(encoding="utf-8")
    english = (COMPONENT / "translations" / "en.json").read_text(encoding="utf-8")
    assert json.loads(strings) == json.loads(english)


def test_defaults_build_the_fitted_parameters():
    assert build_parameters({}) == TankParameters()


def test_geometry_must_leave_a_usable_span():
    assert _geometry_errors({CONF_FLOOR_M: 2.0, CONF_FULL_M: 1.95}) == {"base": "floor_not_below_full"}
    assert _geometry_errors({CONF_FLOOR_M: MODEL_KEYS[CONF_FLOOR_M], CONF_FULL_M: MODEL_KEYS[CONF_FULL_M]}) == {}
