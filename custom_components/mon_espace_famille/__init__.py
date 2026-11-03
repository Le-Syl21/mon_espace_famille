"""Mon Espace Famille: the children's canteen, before- and after-school bookings."""

from __future__ import annotations

from homeassistant.const import Platform
from homeassistant.core import HomeAssistant
from homeassistant.helpers import config_validation as cv
from homeassistant.helpers.typing import ConfigType

from .const import DOMAIN
from .coordinator import MefConfigEntry, MefCoordinator
from .frontend import async_register_card
from .model import Family
from .services import async_setup_services
from .websocket import async_setup_websocket

PLATFORMS = [Platform.BINARY_SENSOR, Platform.CALENDAR, Platform.SENSOR]
CONFIG_SCHEMA = cv.config_entry_only_config_schema(DOMAIN)


async def async_setup(hass: HomeAssistant, config: ConfigType) -> bool:
    async_setup_services(hass)
    async_setup_websocket(hass)
    await async_register_card(hass)
    return True


def _layout(family: Family) -> frozenset[tuple[int, str]]:
    """The entities' shape: which child has which service."""
    return frozenset(
        (child.id, sid) for child in family.children.values() for sid in child.services
    )


async def async_setup_entry(hass: HomeAssistant, entry: MefConfigEntry) -> bool:
    coordinator = MefCoordinator(hass, entry)
    await coordinator.async_config_entry_first_refresh()
    entry.runtime_data = coordinator
    coordinator.start_midnight_tick()
    layout = _layout(coordinator.data)

    def _check_layout() -> None:
        # A child registered to a new service (or a new child) needs new
        # entities: reload rather than track them one by one.
        if coordinator.last_update_success and _layout(coordinator.data) != layout:
            hass.config_entries.async_schedule_reload(entry.entry_id)

    entry.async_on_unload(coordinator.async_add_listener(_check_layout))
    entry.async_on_unload(entry.add_update_listener(_async_reload))
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    return True


async def async_unload_entry(hass: HomeAssistant, entry: MefConfigEntry) -> bool:
    unloaded = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
    if unloaded:
        await entry.runtime_data.async_shutdown()
    return unloaded


async def _async_reload(hass: HomeAssistant, entry: MefConfigEntry) -> None:
    await hass.config_entries.async_reload(entry.entry_id)
