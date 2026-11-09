"""Surface locked (diagnostic), level uncertain and low water (problem)."""
from __future__ import annotations

from typing import Any

from homeassistant.components.binary_sensor import BinarySensorDeviceClass, BinarySensorEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import EntityCategory
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.util import dt as dt_util

from .const import DOMAIN
from .entity import TankEntity
from .hub import TankHub


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry, async_add_entities: AddEntitiesCallback) -> None:
    hub: TankHub = hass.data[DOMAIN][entry.entry_id]
    async_add_entities([SurfaceLockedSensor(hub), LevelUncertainSensor(hub), LowWaterSensor(hub)])


class SurfaceLockedSensor(TankEntity, BinarySensorEntity):
    """ON: a raw frame was accepted as the water surface recently. OFF: coasting."""

    _attr_entity_category = EntityCategory.DIAGNOSTIC

    def __init__(self, hub: TankHub) -> None:
        super().__init__(hub, "surface_locked")

    @property
    def is_on(self) -> bool | None:
        return None if self.hub.reading is None else self.hub.reading.surface_locked

    @property
    def extra_state_attributes(self) -> dict[str, Any] | None:
        reading = self.hub.reading
        if reading is None or reading.seconds_since_surface is None:
            return None
        return {"minutes_since_surface": round(reading.seconds_since_surface / 60.0, 1)}


class LevelUncertainSensor(TankEntity, BinarySensorEntity):
    """ON: another echo competes with the surface the level follows, so the level is a guess.

    The attributes keep the last level published while certain, and when."""

    def __init__(self, hub: TankHub) -> None:
        super().__init__(hub, "level_uncertain")

    @property
    def is_on(self) -> bool | None:
        return None if self.hub.reading is None else not self.hub.reading.level_certain

    @property
    def icon(self) -> str:
        return "mdi:help-circle-outline" if self.is_on else "mdi:check-circle-outline"

    @property
    def extra_state_attributes(self) -> dict[str, Any] | None:
        reading = self.hub.reading
        if reading is None:
            return None
        attributes: dict[str, Any] = {}
        if reading.rival_m is not None:
            attributes["competing_echo_m"] = round(reading.rival_m, 3)
        if reading.last_certain_level_pct is not None and reading.last_certain_time is not None:
            attributes["last_certain_level_pct"] = round(reading.last_certain_level_pct, 1)
            attributes["last_certain_at"] = dt_util.utc_from_timestamp(reading.last_certain_time).isoformat()
        return attributes or None


class LowWaterSensor(TankEntity, BinarySensorEntity):
    """Low water, only ever decided while the surface has been seen recently and the level is certain."""

    _attr_device_class = BinarySensorDeviceClass.PROBLEM

    def __init__(self, hub: TankHub) -> None:
        super().__init__(hub, "low_water")

    @property
    def is_on(self) -> bool | None:
        return self.hub.alarm.is_on
