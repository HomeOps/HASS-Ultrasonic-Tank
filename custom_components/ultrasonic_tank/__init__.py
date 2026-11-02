"""Ultrasonic Tank: a physics model that turns a raw ultrasonic distance sensor
into tank volume (L), net flow (L/min) and change in flow (L/min^2)."""
from __future__ import annotations

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant

from .const import DOMAIN, PLATFORMS
from .hub import TankHub


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Start the model for one tank."""
    hub = TankHub(hass, entry)
    await hub.async_start()
    hass.data.setdefault(DOMAIN, {})[entry.entry_id] = hub
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    entry.async_on_unload(entry.add_update_listener(_async_update_listener))
    return True


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Stop the model and save its state."""
    unloaded = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
    if unloaded:
        hub: TankHub = hass.data[DOMAIN].pop(entry.entry_id)
        await hub.async_stop()
    return unloaded


async def _async_update_listener(hass: HomeAssistant, entry: ConfigEntry) -> None:
    """Options changed: reload so the model picks up the new parameters (state is kept)."""
    await hass.config_entries.async_reload(entry.entry_id)
