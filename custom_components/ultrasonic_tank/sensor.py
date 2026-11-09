"""Volume, level, net flow, change in flow and surface distance."""
from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from homeassistant.components.sensor import (
    SensorDeviceClass,
    SensorEntity,
    SensorEntityDescription,
    SensorStateClass,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import PERCENTAGE, EntityCategory, UnitOfLength, UnitOfVolume, UnitOfVolumeFlowRate
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import DOMAIN
from .entity import TankEntity
from .hub import TankHub
from .model import TankReading


@dataclass(frozen=True, kw_only=True)
class TankSensorDescription(SensorEntityDescription):
    value: Callable[[TankReading], float]


SENSORS: tuple[TankSensorDescription, ...] = (
    TankSensorDescription(
        key="volume",
        translation_key="volume",
        device_class=SensorDeviceClass.VOLUME_STORAGE,
        native_unit_of_measurement=UnitOfVolume.LITERS,
        state_class=SensorStateClass.MEASUREMENT,
        suggested_display_precision=0,
        value=lambda r: r.volume_l,
    ),
    TankSensorDescription(
        key="level",
        translation_key="level",
        native_unit_of_measurement=PERCENTAGE,
        state_class=SensorStateClass.MEASUREMENT,
        suggested_display_precision=1,
        icon="mdi:water-percent",
        value=lambda r: r.level_pct,
    ),
    TankSensorDescription(
        key="net_flow",
        translation_key="net_flow",
        device_class=SensorDeviceClass.VOLUME_FLOW_RATE,
        native_unit_of_measurement=UnitOfVolumeFlowRate.LITERS_PER_MINUTE,
        state_class=SensorStateClass.MEASUREMENT,
        suggested_display_precision=1,
        value=lambda r: r.net_flow_lpm,
    ),
    TankSensorDescription(
        key="flow_change",
        translation_key="flow_change",
        native_unit_of_measurement="L/min²",
        state_class=SensorStateClass.MEASUREMENT,
        suggested_display_precision=2,
        entity_category=EntityCategory.DIAGNOSTIC,
        icon="mdi:chart-bell-curve-cumulative",
        value=lambda r: r.flow_change_lpm2,
    ),
    TankSensorDescription(
        key="surface_distance",
        translation_key="surface_distance",
        device_class=SensorDeviceClass.DISTANCE,
        native_unit_of_measurement=UnitOfLength.METERS,
        state_class=SensorStateClass.MEASUREMENT,
        suggested_display_precision=3,
        entity_category=EntityCategory.DIAGNOSTIC,
        value=lambda r: r.surface_m,
    ),
)


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry, async_add_entities: AddEntitiesCallback) -> None:
    hub: TankHub = hass.data[DOMAIN][entry.entry_id]
    async_add_entities(TankSensor(hub, description) for description in SENSORS)


class TankSensor(TankEntity, SensorEntity):
    entity_description: TankSensorDescription

    def __init__(self, hub: TankHub, description: TankSensorDescription) -> None:
        super().__init__(hub, description.key)
        self.entity_description = description

    @property
    def native_value(self) -> float | None:
        reading = self.hub.reading
        return None if reading is None else round(self.entity_description.value(reading), 4)

    @property
    def extra_state_attributes(self) -> dict[str, Any] | None:
        reading = self.hub.reading
        if reading is None:
            return None
        if self.entity_description.key == "level":
            return {"certain": reading.level_certain}
        if self.entity_description.key != "net_flow":
            return None
        return {
            "max_outflow_lpm": round(reading.max_outflow_lpm, 2),
            "max_inflow_lpm": round(reading.max_inflow_lpm, 2),
        }
