"""Shared entity base."""
from __future__ import annotations

from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.dispatcher import async_dispatcher_connect
from homeassistant.helpers.entity import Entity

from .const import DOMAIN
from .hub import TankHub


class TankEntity(Entity):
    """Pushes on every model tick; no polling."""

    _attr_has_entity_name = True
    _attr_should_poll = False

    def __init__(self, hub: TankHub, key: str) -> None:
        self.hub = hub
        self._attr_translation_key = key
        self._attr_unique_id = f"{hub.entry.entry_id}_{key}"
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, hub.entry.entry_id)},
            name=hub.entry.title,
            manufacturer="HomeOps",
            model="Ultrasonic tank model",
        )

    @property
    def available(self) -> bool:
        return self.hub.reading is not None

    async def async_added_to_hass(self) -> None:
        self.async_on_remove(async_dispatcher_connect(self.hass, self.hub.signal, self.async_write_ha_state))
