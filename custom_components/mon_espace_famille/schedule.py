"""When a child is out of the house on a given day, from what is booked."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, tzinfo

from .const import (
    DEPARTURE_MORNING_CARE,
    DEPARTURE_SCHOOL,
    EVENING_KINDS,
    EVENING_SERVICE_END,
    KIND_ACCUEIL_MATIN,
    SCHOOL_END,
    TRAVEL_MARGIN,
)
from .model import Child, Day


@dataclass(frozen=True, slots=True)
class DayPlan:
    """What the bookings of one day say about the child's whereabouts."""

    # The evening service booked ("accueil_soir" or "etude"), if any.
    evening_kind: str | None
    evening: Day | None
    # When the child leaves and is expected back, None if nothing is booked.
    leaves_at: datetime | None
    back_at: datetime | None

    @property
    def booked(self) -> bool:
        return self.back_at is not None


NO_PLAN = DayPlan(None, None, None, None)


def day_plan(child: Child, day: date, tz: tzinfo) -> DayPlan:
    """The plan of `day`, times in the time zone `tz`.

    Away from 7:00 when a morning care is booked, else from 8:10; back one
    travel margin after the evening service (18:45) when one is booked, else
    after school (16:30). A day with nothing booked has no plan.
    """
    booked: dict[str, Day] = {}
    any_service = False
    for service in child.services.values():
        entry = service.days.get(day)
        if entry is None or not entry.reserved:
            continue
        any_service = True
        if service.kind is not None:
            booked.setdefault(service.kind, entry)
    if not any_service:
        return NO_PLAN
    kind = next((k for k in EVENING_KINDS if k in booked), None)
    start = DEPARTURE_MORNING_CARE if KIND_ACCUEIL_MATIN in booked else DEPARTURE_SCHOOL
    end = EVENING_SERVICE_END if kind else SCHOOL_END
    return DayPlan(
        evening_kind=kind,
        evening=booked[kind] if kind else None,
        leaves_at=datetime.combine(day, start, tzinfo=tz),
        back_at=datetime.combine(day, end, tzinfo=tz) + TRAVEL_MARGIN,
    )
