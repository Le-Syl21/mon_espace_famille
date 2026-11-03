"""What the API says about the children, turned into plain data."""

from __future__ import annotations

import unicodedata
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta

from .const import (
    CANCELLABLE_STATUSES,
    KIND_KEYWORDS,
    KIND_REPAS,
    RESERVED_STATUSES,
    STATUS_LISTS,
)


def parse_api_date(value: object) -> date | None:
    """YYYYMMDD (the API's format) to a date, None if it is not one."""
    if not isinstance(value, str):
        return None
    try:
        return datetime.strptime(value, "%Y%m%d").date()
    except ValueError:
        return None


def monday_of(day: date) -> date:
    return day - timedelta(days=day.weekday())


def service_kind(label: str) -> str | None:
    """The kind of a service from its label ("REPAS PERMANENT" -> "repas")."""
    plain = unicodedata.normalize("NFKD", label).encode("ascii", "ignore").decode().upper()
    for kind, words in KIND_KEYWORDS:
        if any(word in plain for word in words):
            return kind
    return None


@dataclass(frozen=True, slots=True)
class Day:
    """One day of a service the child has an entry for."""

    status: str
    reservation_id: int | None = None
    # Last day the booking can be cancelled (inclusive), as the web app reads it.
    deadline: date | None = None

    @property
    def reserved(self) -> bool:
        return self.status in RESERVED_STATUSES

    def cancellable(self, today: date) -> bool:
        return (
            self.status in CANCELLABLE_STATUSES
            and self.reservation_id is not None
            and (self.deadline is None or today <= self.deadline)
        )


@dataclass(slots=True)
class Service:
    """A service the child is registered to, over the weeks fetched."""

    id: str  # "1_1": the API's serviceReservationId
    service_id: int  # the cart's serviceId: the number before "_" in the id
    label: str
    kind: str | None
    # "POST": billed afterwards, so the portal has no amount to show up front.
    payment_mode: str | None = None
    # Days that can be booked (holidays and closed days are not listed), and
    # whether they are already past the booking deadline.
    open_days: dict[date, bool] = field(default_factory=dict)
    days: dict[date, Day] = field(default_factory=dict)

    def bookable(self, day: date) -> bool:
        return day in self.open_days and not self.open_days[day]

    def reserved_days(self, first: date, end: date) -> list[date]:
        """Days in [first, end) the child has a place for."""
        return sorted(d for d, e in self.days.items() if first <= d < end and e.reserved)


@dataclass(slots=True)
class Child:
    id: int
    first_name: str
    services: dict[str, Service] = field(default_factory=dict)

    def services_of_kind(self, kind: str) -> list[Service]:
        return [s for s in self.services.values() if s.kind == kind]

    @property
    def meals(self) -> Service | None:
        found = self.services_of_kind(KIND_REPAS)
        return found[0] if found else None

    def within(self, first: date, end: date) -> Child:
        """A copy keeping only the days in [first, end)."""
        child = Child(id=self.id, first_name=self.first_name)
        for sid, s in self.services.items():
            child.services[sid] = Service(
                id=s.id,
                service_id=s.service_id,
                label=s.label,
                kind=s.kind,
                payment_mode=s.payment_mode,
                open_days={d: v for d, v in s.open_days.items() if first <= d < end},
                days={d: v for d, v in s.days.items() if first <= d < end},
            )
        return child


@dataclass(slots=True)
class Family:
    children: dict[int, Child]
    commune: str | None = None
    # The weeks fetched: their Mondays.
    weeks: list[date] = field(default_factory=list)


def parse_children(members: dict) -> list[tuple[int, str]]:
    """(id, first name) of the children still followed (archived ones left out)."""
    found = []
    for child in members.get("children") or []:
        if not isinstance(child, dict) or not isinstance(child.get("id"), int):
            continue
        if (child.get("archived") or {}).get("value"):
            continue
        name = ((child.get("firstName") or {}).get("value") or "").strip()
        found.append((child["id"], name or f"Enfant {child['id']}"))
    return found


def merge_week(child: Child, monday: date, services: list[dict]) -> None:
    """Add one week's answer to the child's services.

    A week asked from its Monday also lists the next Monday; only the seven
    days of that week are taken so weeks never overlap.
    """
    end = monday + timedelta(days=7)
    for raw in services:
        if not isinstance(raw, dict) or raw.get("hidden") or not raw.get("id"):
            continue
        sid = str(raw["id"])
        service = child.services.get(sid)
        if service is None:
            label = str(raw.get("label") or sid).strip()
            # The cart wants the service's own number, the one before "_" in
            # "7_7"; "idService" is the régie (1 for every service here), and
            # a cart carrying it is queued by the server and then dropped.
            try:
                service_id = int(sid.split("_", 1)[0])
            except ValueError:
                service_id = 0
            service = child.services[sid] = Service(
                id=sid,
                service_id=service_id,
                label=label,
                kind=service_kind(label),
                payment_mode=raw.get("paymentMode"),
            )
        for item in raw.get("openDays") or []:
            day = parse_api_date((item or {}).get("date"))
            if day is not None and monday <= day < end:
                service.open_days[day] = bool(item.get("isOutOftime"))
        for key, status in STATUS_LISTS:
            for item in raw.get(key) or []:
                if not isinstance(item, dict):
                    continue
                day = parse_api_date(item.get("date"))
                if day is None or not monday <= day < end:
                    continue
                rid = item.get("id")
                service.days[day] = Day(
                    status=status,
                    reservation_id=rid if isinstance(rid, int) else None,
                    deadline=parse_api_date(item.get("dteLimiteSupp")),
                )
