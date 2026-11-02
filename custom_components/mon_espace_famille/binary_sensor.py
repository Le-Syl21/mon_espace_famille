"""Binary sensors: meal booked today and tomorrow, a meal missing next week,
evening care today, and the child being out of the house."""

from __future__ import annotations

from datetime import date, datetime, timedelta
from typing import Any

from homeassistant.components.binary_sensor import BinarySensorEntity
from homeassistant.core import CALLBACK_TYPE, HomeAssistant, callback
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback
from homeassistant.helpers.event import async_track_point_in_time
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
        if child.services:
            entities += [EveningCareSensor(coordinator, child), AwaySensor(coordinator, child)]
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


class EveningCareSensor(ChildEntity, BinarySensorEntity):
    """On when an evening service (evening care or study hall) is booked today."""

    def __init__(self, coordinator: MefCoordinator, child: Child) -> None:
        super().__init__(
            coordinator, child, "evening_care_today", "binary_sensor", "accueil_du_soir_aujourd_hui"
        )

    @property
    def is_on(self) -> bool:
        return self.today_plan().evening is not None

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        plan = self.today_plan()
        today = dt_util.now().date()
        evening = plan.evening
        return {
            "service": plan.evening_kind,
            "annulable_jusqu_au": (
                evening.deadline.isoformat() if evening and evening.cancellable(today) else None
            ),
        }


class AwaySensor(ChildEntity, BinarySensorEntity):
    """On from the child's departure to the expected return, on days with a booking.

    Both times are known from the data, so a timer flips the sensor on the
    spot rather than at the next poll.
    """

    def __init__(self, coordinator: MefCoordinator, child: Child) -> None:
        super().__init__(coordinator, child, "away", "binary_sensor", "hors_de_la_maison")
        self._unsub_timer: CALLBACK_TYPE | None = None

    @property
    def is_on(self) -> bool:
        plan = self.today_plan()
        return plan.booked and plan.leaves_at <= dt_util.now() < plan.back_at

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        plan = self.today_plan()
        return {
            "depart": plan.leaves_at.isoformat() if plan.leaves_at else None,
            "retour_prevu": plan.back_at.isoformat() if plan.back_at else None,
        }

    def _cancel_timer(self) -> None:
        if self._unsub_timer is not None:
            self._unsub_timer()
            self._unsub_timer = None

    def _schedule(self) -> None:
        """Wake up at the next of today's two boundaries still to come."""
        self._cancel_timer()
        plan = self.today_plan()
        now = dt_util.now()
        upcoming = [t for t in (plan.leaves_at, plan.back_at) if t is not None and t > now]
        if upcoming:
            self._unsub_timer = async_track_point_in_time(self.hass, self._boundary, min(upcoming))

    @callback
    def _boundary(self, _now: datetime) -> None:
        self._unsub_timer = None
        self._schedule()
        self.async_write_ha_state()

    async def async_added_to_hass(self) -> None:
        await super().async_added_to_hass()
        self.async_on_remove(self._cancel_timer)
        self._schedule()

    @callback
    def _handle_coordinator_update(self) -> None:
        # New data (or midnight) can move the boundaries.
        self._schedule()
        super()._handle_coordinator_update()
