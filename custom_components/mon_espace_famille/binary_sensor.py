"""Binary sensors: meal booked today and tomorrow, a meal missing next week."""

from __future__ import annotations

from datetime import date, timedelta
from typing import Any

from homeassistant.components.binary_sensor import BinarySensorEntity
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback
from homeassistant.util import dt as dt_util

from .coordinator import MefConfigEntry, MefCoordinator
from .entity import ChildEntity
from .model import Child, monday_of


async def async_setup_entry(
    hass: HomeAssistant,
    entry: MefConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    coordinator = entry.runtime_data
    entities: list[BinarySensorEntity] = []
    for child in coordinator.data.children.values():
        if child.meals is None:
            continue
        entities += [
            MealSensor(coordinator, child, "meal_today", "cantine_aujourd_hui", 0),
            MealSensor(coordinator, child, "meal_tomorrow", "cantine_demain", 1),
            MissingBookingSensor(coordinator, child),
        ]
    async_add_entities(entities)


class MealSensor(ChildEntity, BinarySensorEntity):
    """On when a meal is booked (or the child is down as attending) that day."""

    def __init__(
        self, coordinator: MefCoordinator, child: Child, key: str, object_id: str, offset: int
    ) -> None:
        super().__init__(coordinator, child, key, "binary_sensor", object_id)
        self._offset = offset

    def _day(self) -> date:
        return dt_util.now().date() + timedelta(days=self._offset)

    def _entry(self):
        child = self.child
        meals = child.meals if child else None
        return meals.days.get(self._day()) if meals else None

    @property
    def is_on(self) -> bool:
        entry = self._entry()
        return entry is not None and entry.reserved

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        entry = self._entry()
        today = dt_util.now().date()
        return {
            "date": self._day().isoformat(),
            "statut": entry.status if entry else None,
            "annulable_jusqu_au": (
                entry.deadline.isoformat() if entry and entry.cancellable(today) else None
            ),
        }


class MissingBookingSensor(ChildEntity, BinarySensorEntity):
    """On when next week has a day the canteen is open and no meal is booked."""

    def __init__(self, coordinator: MefCoordinator, child: Child) -> None:
        super().__init__(
            coordinator, child, "missing_booking", "binary_sensor", "reservation_manquante"
        )

    def _missing(self) -> list[date]:
        child = self.child
        meals = child.meals if child else None
        if meals is None:
            return []
        first = monday_of(dt_util.now().date()) + timedelta(days=7)
        end = first + timedelta(days=7)
        return sorted(
            day
            for day in meals.open_days
            if first <= day < end and meals.bookable(day) and day not in meals.days
        )

    @property
    def is_on(self) -> bool:
        return bool(self._missing())

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        return {"jours": [d.isoformat() for d in self._missing()]}
