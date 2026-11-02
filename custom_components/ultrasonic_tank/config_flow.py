"""Config and options flow."""
from __future__ import annotations

from typing import Any

import voluptuous as vol

from homeassistant.config_entries import ConfigEntry, ConfigFlow, ConfigFlowResult, OptionsFlow
from homeassistant.const import CONF_NAME
from homeassistant.core import callback
from homeassistant.helpers import selector

from .const import (
    CONF_BOOTSTRAP_HOURS,
    CONF_CAPACITY_L,
    CONF_DRAIN_COEFFICIENT,
    CONF_FLOOR_M,
    CONF_FULL_M,
    CONF_LOW_WATER_DELAY_MIN,
    CONF_LOW_WATER_MAX_COAST_MIN,
    CONF_LOW_WATER_PCT,
    CONF_MAX_ACCEL_PCT_PER_MIN2,
    CONF_MAX_FILL_PCT_PER_MIN,
    CONF_NOISE_M,
    CONF_RAW_ENTITY,
    CONF_REFLECTOR_HALF_WIDTH_M,
    CONF_REFLECTOR_M,
    CONF_VELOCITY_TAU_MIN,
    DEFAULT_BOOTSTRAP_HOURS,
    DEFAULT_LOW_WATER_DELAY_MIN,
    DEFAULT_LOW_WATER_MAX_COAST_MIN,
    DEFAULT_LOW_WATER_PCT,
    DEFAULT_NAME,
    DOMAIN,
    MODEL_KEYS,
)


def _number(minimum: float, maximum: float, step: float, unit: str | None = None) -> selector.NumberSelector:
    return selector.NumberSelector(
        selector.NumberSelectorConfig(min=minimum, max=maximum, step=step, unit_of_measurement=unit, mode=selector.NumberSelectorMode.BOX)
    )


def _geometry_errors(values: dict[str, Any]) -> dict[str, str]:
    floor = float(values.get(CONF_FLOOR_M, MODEL_KEYS[CONF_FLOOR_M]))
    full = float(values.get(CONF_FULL_M, MODEL_KEYS[CONF_FULL_M]))
    return {} if floor - full >= 0.1 else {"base": "floor_not_below_full"}


class UltrasonicTankConfigFlow(ConfigFlow, domain=DOMAIN):
    """One entry per raw distance sensor."""

    VERSION = 1

    async def async_step_user(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        errors: dict[str, str] = {}
        if user_input is not None:
            await self.async_set_unique_id(user_input[CONF_RAW_ENTITY])
            self._abort_if_unique_id_configured()
            errors = _geometry_errors(user_input)
            if not errors:
                name = user_input.pop(CONF_NAME)
                return self.async_create_entry(title=name, data=user_input)

        schema = vol.Schema(
            {
                vol.Required(CONF_NAME, default=DEFAULT_NAME): str,
                vol.Required(CONF_RAW_ENTITY): selector.EntitySelector(selector.EntitySelectorConfig(domain="sensor")),
                vol.Required(CONF_CAPACITY_L, default=MODEL_KEYS[CONF_CAPACITY_L]): _number(1, 1_000_000, 1, "L"),
                vol.Required(CONF_FLOOR_M, default=MODEL_KEYS[CONF_FLOOR_M]): _number(0.2, 10, 0.001, "m"),
                vol.Required(CONF_FULL_M, default=MODEL_KEYS[CONF_FULL_M]): _number(0.0, 9, 0.001, "m"),
            }
        )
        return self.async_show_form(step_id="user", data_schema=schema, errors=errors)

    @staticmethod
    @callback
    def async_get_options_flow(config_entry: ConfigEntry) -> OptionsFlow:
        return UltrasonicTankOptionsFlow()


class UltrasonicTankOptionsFlow(OptionsFlow):
    """Geometry, kinematic caps and the low-water alarm."""

    async def async_step_init(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        errors: dict[str, str] = {}
        if user_input is not None:
            errors = _geometry_errors(user_input)
            if not errors:
                return self.async_create_entry(title="", data=user_input)

        current = {**self.config_entry.data, **self.config_entry.options}

        def default(key: str, fallback: float) -> float:
            return float(current.get(key, fallback))

        fields: list[tuple[str, float, selector.NumberSelector]] = [
            (CONF_CAPACITY_L, MODEL_KEYS[CONF_CAPACITY_L], _number(1, 1_000_000, 1, "L")),
            (CONF_FLOOR_M, MODEL_KEYS[CONF_FLOOR_M], _number(0.2, 10, 0.001, "m")),
            (CONF_FULL_M, MODEL_KEYS[CONF_FULL_M], _number(0.0, 9, 0.001, "m")),
            (CONF_DRAIN_COEFFICIENT, MODEL_KEYS[CONF_DRAIN_COEFFICIENT], _number(0.00001, 1, 0.00001)),
            (CONF_MAX_FILL_PCT_PER_MIN, MODEL_KEYS[CONF_MAX_FILL_PCT_PER_MIN], _number(0.1, 100, 0.1, "%/min")),
            (CONF_NOISE_M, MODEL_KEYS[CONF_NOISE_M], _number(0.001, 0.5, 0.001, "m")),
            (CONF_MAX_ACCEL_PCT_PER_MIN2, MODEL_KEYS[CONF_MAX_ACCEL_PCT_PER_MIN2], _number(0.01, 100, 0.01, "%/min²")),
            (CONF_VELOCITY_TAU_MIN, MODEL_KEYS[CONF_VELOCITY_TAU_MIN], _number(0.1, 60, 0.1, "min")),
            (CONF_REFLECTOR_M, MODEL_KEYS[CONF_REFLECTOR_M], _number(0.0, 10, 0.001, "m")),
            (CONF_REFLECTOR_HALF_WIDTH_M, MODEL_KEYS[CONF_REFLECTOR_HALF_WIDTH_M], _number(0.0, 1, 0.001, "m")),
            (CONF_LOW_WATER_PCT, DEFAULT_LOW_WATER_PCT, _number(0, 100, 1, "%")),
            (CONF_LOW_WATER_MAX_COAST_MIN, DEFAULT_LOW_WATER_MAX_COAST_MIN, _number(1, 1440, 1, "min")),
            (CONF_LOW_WATER_DELAY_MIN, DEFAULT_LOW_WATER_DELAY_MIN, _number(0, 1440, 1, "min")),
            (CONF_BOOTSTRAP_HOURS, DEFAULT_BOOTSTRAP_HOURS, _number(0, 240, 1, "h")),
        ]
        schema = vol.Schema({vol.Required(key, default=default(key, fallback)): sel for key, fallback, sel in fields})
        return self.async_show_form(step_id="init", data_schema=schema, errors=errors)
