"""Sensors: next meal, expected return home, booked days of each service this week."""

from __future__ import annotations

from datetime import date, datetime, timedelta
from typing import Any

from homeassistant.components.sensor import SensorDeviceClass, SensorEntity
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback
from homeassistant.util import dt as dt_util
from homeassistant.util import slugify

from .coordinator import MefConfigEntry, MefCoordinator
from .entity import ChildEntity
from .model import Child, Service, monday_of


async def async_setup_entry(
    hass: HomeAssistant,
    entry: MefConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    coordinator = entry.runtime_data
    entities: list[SensorEntity] = []
    for child in coordinator.data.children.values():
        if child.meals is not None:
            entities.append(NextMealSensor(coordinator, child))
        if child.services:
            entities.append(ReturnSensor(coordinator, child))
        entities += [WeekSensor(coordinator, child, s) for s in child.services.values()]
    async_add_entities(entities)


class NextMealSensor(ChildEntity, SensorEntity):
    """The next day, from today on, with a meal booked."""

    _attr_device_class = SensorDeviceClass.DATE

    def __init__(self, coordinator: MefCoordinator, child: Child) -> None:
        super().__init__(coordinator, child, "next_meal", "sensor", "prochain_repas")

    def _next(self) -> date | None:
        child = self.child
        meals = child.meals if child else None
        if meals is None:
            return None
        days = meals.reserved_days(dt_util.now().date(), date.max)
        return days[0] if days else None

    @property
    def native_value(self) -> date | None:
        return self._next()

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        day = self._next()
        return {"dans_jours": (day - dt_util.now().date()).days if day else None}


class ReturnSensor(ChildEntity, SensorEntity):
    """When the child is expected home today.

    The end of the evening service (or of school when there is none) plus a
    travel margin; unknown on a day with nothing booked. It only changes with
    the data and at midnight, so it needs no timer of its own.
    """

    _attr_device_class = SensorDeviceClass.TIMESTAMP

    def __init__(self, coordinator: MefCoordinator, child: Child) -> None:
        super().__init__(coordinator, child, "expected_return", "sensor", "retour_prevu")

    @property
    def native_value(self) -> datetime | None:
        return self.today_plan().back_at

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        return {"service_du_soir": self.today_plan().evening_kind is not None}


class WeekSensor(ChildEntity, SensorEntity):
    """How many days of this week the child has a place for in a service."""

    def __init__(self, coordinator: MefCoordinator, child: Child, service: Service) -> None:
        kind = service.kind or "other"
        suffix = service.kind or slugify(service.label)
        super().__init__(coordinator, child, f"week_{kind}", "sensor", f"{suffix}_cette_semaine")
        # Two services of one kind (or unknown ones) need their own ids.
        self._attr_unique_id = f"{coordinator.config_entry.entry_id}_{child.id}_{service.id}_week"
        self._attr_translation_placeholders = {"service": service.label.capitalize()}
        self.service_id = service.id

    def _days(self) -> list[date]:
        child = self.child
        service = child.services.get(self.service_id) if child else None
        if service is None:
            return []
        first = monday_of(dt_util.now().date())
        return service.reserved_days(first, first + timedelta(days=7))

    @property
    def native_value(self) -> int:
        return len(self._days())

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        service = self.child.services.get(self.service_id) if self.child else None
        today = dt_util.now().date()
        # Today and tomorrow are read from the days fetched, not from the
        # week above: on a Sunday, tomorrow belongs to next week.
        booked = service.reserved_days(today, today + timedelta(days=2)) if service else []
        return {
            "jours": [d.isoformat() for d in self._days()],
            "aujourd_hui": today in booked,
            "demain": today + timedelta(days=1) in booked,
        }
