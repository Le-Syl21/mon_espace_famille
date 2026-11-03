"""The weekly planning: what a card shows, and what a set of changes means.

Pure functions over the model (no I/O) so they can be tested on their own.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, timedelta
from typing import Any

from .const import (
    CANCELLABLE_STATUSES,
    KIND_HOURS,
    KIND_NAMES,
    PLANNING_ORDER,
    RESERVED_STATUSES,
    STATUS_ABSENT,
    STATUS_ABSENT_JUSTIFIED,
    STATUS_BOOKED,
    STATUS_CANCEL_PENDING,
    STATUS_FAILING,
)
from .model import Child, Service, monday_of

# A day counts as booked for the card in these states; the last two are days
# the child was booked for and missed.
_BOOKED_STATES = RESERVED_STATUSES | {STATUS_ABSENT, STATUS_ABSENT_JUSTIFIED}
# Days that have an answer already on the way: not touchable.
_BUSY_STATES = frozenset({STATUS_CANCEL_PENDING, STATUS_FAILING})

BOOK = "book"
CANCEL = "cancel"


def service_of(child: Child, kind: str) -> Service | None:
    found = child.services_of_kind(kind)
    return found[0] if found else None


def shown_kinds(child: Child) -> list[str]:
    """The services the child is registered to, in the card's order."""
    return [k for k in PLANNING_ORDER if service_of(child, k) is not None]


@dataclass(frozen=True, slots=True)
class Calendar:
    """What the window tells about the school's rhythm."""

    # Weekdays on which each kind of service has ever been seen open.
    weekdays: dict[str, frozenset[int]]
    # First day that can still be booked: earlier days are past or too late.
    first_open: date | None

    @classmethod
    def of(cls, children: list[Child], today: date) -> Calendar:
        days: dict[str, set[int]] = {}
        first: date | None = None
        for child in children:
            for service in child.services.values():
                if service.kind is None:
                    continue
                seen = days.setdefault(service.kind, set())
                for day in list(service.open_days) + list(service.days):
                    seen.add(day.weekday())
                for day in service.open_days:
                    if day >= today and (first is None or day < first):
                        first = day
        return cls({k: frozenset(v) for k, v in days.items()}, first)


def cell(
    service: Service, day: date, today: date, cal: Calendar, week_active: bool
) -> dict[str, Any]:
    """One child, one service, one day: can it be touched and what is it now?"""
    entry = service.days.get(day)
    status = entry.status if entry else None
    out: dict[str, Any] = {
        "registered": True,
        "open": service.bookable(day),
        "booked": status in _BOOKED_STATES,
        "locked": True,
        "deadline": entry.deadline.isoformat() if entry and entry.deadline else None,
        "reason": "",
        "status": status,
    }
    if out["booked"]:
        if day < today:
            out["reason"] = "past"
        elif status in CANCELLABLE_STATUSES and entry.cancellable(today):
            out["locked"] = False
        elif status == STATUS_BOOKED:
            out["reason"] = "deadline"
        else:
            out["reason"] = "attended" if status not in RESERVED_STATUSES else "pending"
        return out
    if status in _BUSY_STATES:
        out["reason"] = "pending" if status == STATUS_CANCEL_PENDING else "failing"
        return out
    if out["open"] and day >= today:
        out["locked"] = False
        return out
    seen = service.kind in cal.weekdays and day.weekday() in cal.weekdays[service.kind]
    bound = cal.first_open or today
    if seen and week_active and day < bound:
        out["reason"] = "past" if day < today else "deadline"
    else:
        out["reason"] = "not_offered"
    return out


def build_week(
    week: dict[int, Child], names: dict[int, str], monday: date, today: date, cal: Calendar
) -> dict[str, Any]:
    """The card's data for the week of `monday`; `week` holds only that week's days."""
    end = monday + timedelta(days=7)
    week_active = any(
        monday <= d < end
        for child in week.values()
        for s in child.services.values()
        for d in list(s.open_days) + list(s.days)
    )
    children = []
    visible: set[date] = set()
    for child_id, child in week.items():
        kinds = shown_kinds(child)
        if not kinds:
            continue
        cells: dict[str, dict[str, dict]] = {}
        for n in range(7):
            day = monday + timedelta(days=n)
            row = {}
            for kind in kinds:
                c = cell(service_of(child, kind), day, today, cal, week_active)  # type: ignore[arg-type]
                row[kind] = c
                if c["reason"] != "not_offered":
                    visible.add(day)
            cells[day.isoformat()] = row
        children.append(
            {
                "id": child_id,
                "name": names.get(child_id, child.first_name),
                "services": kinds,
                "cells": cells,
            }
        )
    days = sorted(visible)
    for c in children:
        c["cells"] = {d.isoformat(): c["cells"][d.isoformat()] for d in days}
    iso = monday.isocalendar()
    return {
        "monday": monday.isoformat(),
        "week": iso.week,
        "year": iso.year,
        "today": today.isoformat(),
        "first_day": days[0].isoformat() if days else None,
        "last_day": days[-1].isoformat() if days else None,
        "days": [{"date": d.isoformat(), "weekday": d.weekday()} for d in days],
        "children": children,
        "services": {
            k: {
                "name": KIND_NAMES[k],
                "start": KIND_HOURS[k][0].strftime("%H:%M"),
                "end": KIND_HOURS[k][1].strftime("%H:%M"),
            }
            for k in PLANNING_ORDER
        },
    }


@dataclass(frozen=True, slots=True)
class Change:
    child: int
    service: str  # a kind
    day: date
    action: str  # BOOK or CANCEL

    def key(self) -> tuple[int, str, date]:
        return (self.child, self.service, self.day)


def check(
    changes: list[Change],
    week_of: dict[tuple[int, date], Child],
    base: dict[tuple[int, str, date], bool],
    today: date,
) -> tuple[list[dict], list[dict]]:
    """(conflicts, refusals) of a set of changes against the portal's state.

    A conflict: a cell is not in the state the card saw (`base`). A refusal:
    the change is not allowed now, whatever the card showed.
    """
    conflicts: list[dict] = []
    refused: list[dict] = []
    cal_children = [week_of[k] for k in week_of]
    cal = Calendar.of(cal_children, today)
    for ch in changes:
        base_info = {"child": ch.child, "service": ch.service, "date": ch.day.isoformat()}
        child = week_of.get((ch.child, monday_of(ch.day)))
        service = service_of(child, ch.service) if child else None
        if service is None:
            refused.append(base_info | {"reason": "not_registered"})
            continue
        # The week is checked on its own days only: nothing else is known.
        monday = monday_of(ch.day)
        active = any(
            monday <= d < monday + timedelta(days=7)
            for s in child.services.values()
            for d in list(s.open_days) + list(s.days)
        )
        now = cell(service, ch.day, today, cal, active)
        seen = base.get(ch.key())
        if seen is not None and seen != now["booked"]:
            conflicts.append(base_info | {"expected": seen, "actual": now["booked"]})
            continue
        if now["locked"] or (ch.action == BOOK) == now["booked"]:
            refused.append(base_info | {"reason": now["reason"] or "unchanged"})
    return conflicts, refused


def carts(changes: list[Change], week_of: dict[tuple[int, date], Child]) -> list[dict]:
    """One cart entry per child: bookings and cancellations together."""
    out = []
    for child_id in dict.fromkeys(c.child for c in changes):
        book: dict[str, list[date]] = {}
        cancel: dict[str, list[date]] = {}
        for ch in sorted((c for c in changes if c.child == child_id), key=lambda c: c.day):
            service = service_of(week_of[(child_id, monday_of(ch.day))], ch.service)
            (book if ch.action == BOOK else cancel).setdefault(service.id, []).append(ch.day)  # type: ignore[union-attr]
        entry: dict[str, Any] = {
            "childId": child_id,
            "servicesReservations": [],
            "cancelationReservations": [],
        }
        for sid, days in book.items():
            service = _by_id(week_of, child_id, sid)
            entry["servicesReservations"].append(
                {
                    "dates": [{"date": d.strftime("%Y%m%d")} for d in days],
                    "serviceReservationId": sid,
                    "serviceId": service.service_id,
                }
            )
        for sid, days in cancel.items():
            service = _by_id(week_of, child_id, sid)
            ids = []
            for d in days:
                owner = week_of[(child_id, monday_of(d))].services[sid]
                ids.append(owner.days[d].reservation_id)
            entry["cancelationReservations"].append(
                {
                    "dates": [{"date": d.strftime("%Y%m%d")} for d in days],
                    "serviceReservationId": sid,
                    "serviceId": service.service_id,
                    "reservationsIds": ids,
                }
            )
        out.append(entry)
    return out


def _by_id(week_of: dict[tuple[int, date], Child], child_id: int, sid: str) -> Service:
    for (cid, _), child in week_of.items():
        if cid == child_id and sid in child.services:
            return child.services[sid]
    raise KeyError(sid)


def is_done(change: Change, week_of: dict[tuple[int, date], Child]) -> bool:
    """Whether the portal now shows the change."""
    child = week_of.get((change.child, monday_of(change.day)))
    service = service_of(child, change.service) if child else None
    if service is None:
        return False
    entry = service.days.get(change.day)
    booked = entry is not None and entry.status in _BOOKED_STATES
    return booked if change.action == BOOK else not booked
