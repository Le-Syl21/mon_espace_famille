"""What every entity of a child shares."""

from __future__ import annotations

from homeassistant.helpers.device_registry import DeviceEntryType, DeviceInfo
from homeassistant.helpers.update_coordinator import CoordinatorEntity
from homeassistant.util import dt as dt_util
from homeassistant.util import slugify

from .const import DOMAIN
from .coordinator import MefCoordinator
from .model import Child
from .schedule import NO_PLAN, DayPlan, day_plan


def child_device_id(entry_id: str, child_id: int) -> str:
    """The device registry identifier of a child."""
    return f"{entry_id}_{child_id}"


class ChildEntity(CoordinatorEntity[MefCoordinator]):
    _attr_has_entity_name = True

    def __init__(
        self, coordinator: MefCoordinator, child: Child, key: str, platform: str, object_id: str
    ) -> None:
        super().__init__(coordinator)
        entry = coordinator.config_entry
        self.child_id = child.id
        self._attr_translation_key = key
        self._attr_unique_id = f"{entry.entry_id}_{child.id}_{key}"
        # Fixed French ids, the same whatever the language of Home Assistant,
        # prefixed by the child's first name.
        self.entity_id = f"{platform}.{slugify(child.first_name)}_{object_id}"
        commune = coordinator.data.commune
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, child_device_id(entry.entry_id, child.id))},
            name=child.first_name,
            manufacturer="Mon Espace Famille",
            model=f"Périscolaire · {commune}" if commune else "Périscolaire",
            entry_type=DeviceEntryType.SERVICE,
        )

    @property
    def child(self) -> Child | None:
        return self.coordinator.data.children.get(self.child_id)

    @property
    def available(self) -> bool:
        return super().available and self.child is not None

    def today_plan(self) -> DayPlan:
        """What today's bookings say about the child being out, in local time."""
        child = self.child
        if child is None:
            return NO_PLAN
        return day_plan(
            child,
            dt_util.now().date(),
            dt_util.get_default_time_zone(),
            self.coordinator.settings,
        )
