"""Runs one TankModel against a raw distance entity and persists its state."""
from __future__ import annotations

from collections.abc import Callable
from datetime import datetime, timedelta
import logging
from typing import Any

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import EVENT_HOMEASSISTANT_STOP, STATE_UNAVAILABLE, STATE_UNKNOWN
from homeassistant.core import Event, EventStateChangedData, HomeAssistant, State, callback
from homeassistant.helpers.dispatcher import async_dispatcher_send
from homeassistant.helpers.event import async_track_state_change_event, async_track_time_interval
from homeassistant.helpers.storage import Store
from homeassistant.util import dt as dt_util

from .const import (
    CONF_BOOTSTRAP_HOURS,
    CONF_LOW_WATER_DELAY_MIN,
    CONF_LOW_WATER_MAX_COAST_MIN,
    CONF_LOW_WATER_PCT,
    CONF_RAW_ENTITY,
    DEFAULT_BOOTSTRAP_HOURS,
    DEFAULT_LOW_WATER_DELAY_MIN,
    DEFAULT_LOW_WATER_MAX_COAST_MIN,
    DEFAULT_LOW_WATER_PCT,
    DOMAIN,
    MODEL_KEYS,
    SAVE_DELAY_SECONDS,
    STORAGE_VERSION,
    TICK_SECONDS,
)
from .model import LowWaterAlarm, TankModel, TankParameters, TankReading

_LOGGER = logging.getLogger(__name__)


def entry_settings(entry: ConfigEntry) -> dict[str, Any]:
    """Setup data overlaid with options."""
    return {**entry.data, **entry.options}


def build_parameters(settings: dict[str, Any]) -> TankParameters:
    return TankParameters(**{key: float(settings.get(key, default)) for key, default in MODEL_KEYS.items()})


def _parse_distance(state: State | None) -> float | None:
    if state is None or state.state in (STATE_UNAVAILABLE, STATE_UNKNOWN):
        return None
    try:
        return float(state.state)
    except ValueError:
        return None


class TankHub:
    """Feeds raw frames to the model, ticks it, and publishes readings to the entities."""

    def __init__(self, hass: HomeAssistant, entry: ConfigEntry) -> None:
        self.hass = hass
        self.entry = entry
        settings = entry_settings(entry)
        self.raw_entity: str = settings[CONF_RAW_ENTITY]
        self.params = build_parameters(settings)
        self.bootstrap_hours = float(settings.get(CONF_BOOTSTRAP_HOURS, DEFAULT_BOOTSTRAP_HOURS))
        self.alarm = LowWaterAlarm(
            threshold_pct=float(settings.get(CONF_LOW_WATER_PCT, DEFAULT_LOW_WATER_PCT)),
            max_coast_s=60.0 * float(settings.get(CONF_LOW_WATER_MAX_COAST_MIN, DEFAULT_LOW_WATER_MAX_COAST_MIN)),
            delay_s=60.0 * float(settings.get(CONF_LOW_WATER_DELAY_MIN, DEFAULT_LOW_WATER_DELAY_MIN)),
        )
        self.model = TankModel(self.params)
        self.reading: TankReading | None = None
        self.signal = f"{DOMAIN}_{entry.entry_id}_update"
        self._store: Store[dict[str, Any]] = Store(hass, STORAGE_VERSION, f"{DOMAIN}.{entry.entry_id}")
        self._unsubscribers: list[Callable[[], None]] = []

    async def async_start(self) -> None:
        stored = await self._store.async_load()
        if stored and stored.get("model"):
            self.model = TankModel(self.params, stored["model"])
            self.alarm.is_on = stored.get("low_water")
            _LOGGER.debug("%s: restored model state", self.raw_entity)
        else:
            await self._async_bootstrap()

        self._unsubscribers.append(async_track_state_change_event(self.hass, [self.raw_entity], self._async_raw_changed))
        self._unsubscribers.append(async_track_time_interval(self.hass, self._async_tick, timedelta(seconds=TICK_SECONDS)))
        self._unsubscribers.append(self.hass.bus.async_listen_once(EVENT_HOMEASSISTANT_STOP, self._async_save_now))
        self._async_tick(dt_util.utcnow())

    async def async_stop(self) -> None:
        for unsubscribe in self._unsubscribers:
            unsubscribe()
        self._unsubscribers.clear()
        await self._store.async_save(self._data_to_store())

    async def _async_bootstrap(self) -> None:
        """No stored state (first install): replay recent recorder history from an empty tank.

        A few minutes of frames cannot seed the model (they can be 100 % reflector on
        an empty tank), but replaying hours of history converges: measured mean error
        2 % at 12 h, the same as the continuously running model.
        """
        if self.bootstrap_hours <= 0 or "recorder" not in self.hass.config.components:
            _LOGGER.info("%s: no stored state and no history replay; starting from empty", self.raw_entity)
            return
        from homeassistant.components.recorder import get_instance, history

        end = dt_util.utcnow()
        start = end - timedelta(hours=self.bootstrap_hours)
        states = await get_instance(self.hass).async_add_executor_job(
            lambda: history.state_changes_during_period(
                self.hass, start, end, self.raw_entity, no_attributes=True, include_start_time_state=False
            )
        )
        frames = [
            (state.last_changed.timestamp(), value)
            for state in states.get(self.raw_entity, [])
            if (value := _parse_distance(state)) is not None
        ]
        frames.sort()
        if not frames:
            _LOGGER.info("%s: no history to replay; starting from empty", self.raw_entity)
            return
        tick = frames[0][0] + 60
        index = 0
        while tick < end.timestamp():
            while index < len(frames) and frames[index][0] <= tick:
                self.model.add_frame(*frames[index])
                index += 1
            self.alarm.update(self.model.tick(tick))
            tick += TICK_SECONDS
        _LOGGER.info("%s: bootstrapped from %d frames over %.0f h", self.raw_entity, len(frames), self.bootstrap_hours)

    @callback
    def _async_raw_changed(self, event: Event[EventStateChangedData]) -> None:
        new_state = event.data["new_state"]
        value = _parse_distance(new_state)
        if value is not None:
            self.model.add_frame(new_state.last_changed.timestamp(), value)

    @callback
    def _async_tick(self, now: datetime) -> None:
        self.reading = self.model.tick(now.timestamp())
        self.alarm.update(self.reading)
        async_dispatcher_send(self.hass, self.signal)
        self._store.async_delay_save(self._data_to_store, SAVE_DELAY_SECONDS)

    async def _async_save_now(self, _event: Event) -> None:
        await self._store.async_save(self._data_to_store())

    @callback
    def _data_to_store(self) -> dict[str, Any]:
        return {"model": self.model.to_dict(), "low_water": self.alarm.is_on}
