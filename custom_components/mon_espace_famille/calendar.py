"""Calendar: one event per booked day of each service of a child."""

from __future__ import annotations

from datetime import date, datetime, timedelta

from homeassistant.components.calendar import CalendarEntity, CalendarEvent
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback
from homeassistant.util import dt as dt_util

from .const import (
    KIND_HOURS,
    KIND_NAMES,
    STATUS_ABSENT,
    STATUS_ABSENT_JUSTIFIED,
    STATUS_BOOKED,
    STATUS_BOOKING_PENDING,
    STATUS_CANCEL_PENDING,
    STATUS_FAILING,
    STATUS_PRESENT,
    STATUS_PRESENT_UNBOOKED,
)
from .coordinator import MefConfigEntry, MefCoordinator
from .entity import ChildEntity
from .model import Child, Day, Service


async def async_setup_entry(
    hass: HomeAssistant,
    entry: MefConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    coordinator = entry.runtime_data
    async_add_entities(
        ChildCalendar(coordinator, child)
        for child in coordinator.data.children.values()
        if child.services
    )


def service_name(service: Service) -> str:
    """The name shown in the calendar: "Cantine", or the commune's label."""
    if service.kind in KIND_NAMES:
        return KIND_NAMES[service.kind]
    return service.label.capitalize()


def _fr(day: date) -> str:
    return day.strftime("%d/%m/%Y")


_TEXTS = {
    STATUS_BOOKING_PENDING: "Réservation en attente de validation.",
    STATUS_CANCEL_PENDING: "Annulation en attente de validation.",
    STATUS_PRESENT_UNBOOKED: "Présent sans réservation.",
    STATUS_ABSENT: "Absent.",
    STATUS_ABSENT_JUSTIFIED: "Absence justifiée.",
    STATUS_FAILING: "Signalé en défaut sur Mon Espace Famille.",
}


def describe(entry: Day, day: date, today: date) -> str:
    """What the day is, in the words of the web app's legend."""
    if entry.status == STATUS_BOOKED:
        if entry.deadline is None:
            return "Réservé."
        if today <= entry.deadline:
            return f"Réservé. Annulable jusqu'au {_fr(entry.deadline)} inclus."
        return f"Réservé. Date limite d'annulation dépassée ({_fr(entry.deadline)})."
    if entry.status == STATUS_PRESENT:
        # The commune marks the days it will no longer change as attended,
        # sometimes before they come.
        return "Présent." if day <= today else "Réservé, plus annulable."
    return _TEXTS.get(entry.status, entry.status)


def child_events(child: Child, first: date, end: date, today: date) -> list[CalendarEvent]:
    """The child's events on the days in [first, end)."""
    tz = dt_util.get_default_time_zone()
    events = []
    for service in child.services.values():
        name = service_name(service)
        hours = KIND_HOURS.get(service.kind)
        for day, entry in service.days.items():
            if not first <= day < end:
                continue
            summary = name
            if entry.status in (STATUS_ABSENT, STATUS_ABSENT_JUSTIFIED):
                summary = f"{name} (absent)"
            if hours:
                start: date | datetime = datetime.combine(day, hours[0], tzinfo=tz)
                stop: date | datetime = datetime.combine(day, hours[1], tzinfo=tz)
            else:
                start, stop = day, day + timedelta(days=1)
            events.append(
                CalendarEvent(
                    start=start,
                    end=stop,
                    summary=summary,
                    description=describe(entry, day, today),
                    uid=f"{child.id}_{service.id}_{day.isoformat()}",
                )
            )
    return sorted(events, key=lambda e: (e.start_datetime_local, e.summary))


class ChildCalendar(ChildEntity, CalendarEntity):
    def __init__(self, coordinator: MefCoordinator, child: Child) -> None:
        super().__init__(coordinator, child, "calendar", "calendar", "periscolaire")

    @property
    def event(self) -> CalendarEvent | None:
        if (child := self.child) is None:
            return None
        now = dt_util.now()
        today = now.date()
        for event in child_events(child, today, date.max, today):
            if event.end_datetime_local > now:
                return event
        return None

    async def async_get_events(
        self, hass: HomeAssistant, start_date: datetime, end_date: datetime
    ) -> list[CalendarEvent]:
        if (child := self.child) is None:
            return []
        today = dt_util.now().date()
        events = child_events(
            child,
            dt_util.as_local(start_date).date(),
            dt_util.as_local(end_date).date() + timedelta(days=1),
            today,
        )
        return [
            e
            for e in events
            if e.end_datetime_local > start_date and e.start_datetime_local < end_date
        ]
