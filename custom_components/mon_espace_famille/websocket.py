"""WebSocket commands behind the planning card: planning, quote and apply."""

from __future__ import annotations

import asyncio
import logging
from datetime import date, timedelta
from typing import Any

import voluptuous as vol
from homeassistant.components import websocket_api
from homeassistant.config_entries import ConfigEntryState
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers import config_validation as cv
from homeassistant.util import dt as dt_util

from .api import MefAuthError, MefError
from .const import DOMAIN, KIND_NAMES, KINDS, VERIFY_ATTEMPTS, VERIFY_DELAY
from .coordinator import MefCoordinator, action_lock
from .cost import estimate, month_bounds
from .model import Child, monday_of
from .planning import (
    BOOK,
    BOOKED_STATES,
    CANCEL,
    Calendar,
    Change,
    build_week,
    carts,
    check,
    is_done,
    service_of,
)

_LOGGER = logging.getLogger(__name__)

_CHANGE = vol.Schema(
    {
        vol.Required("child"): vol.Coerce(int),
        vol.Required("service"): vol.In(KINDS),
        vol.Required("date"): cv.date,
        vol.Required("action"): vol.In([BOOK, CANCEL]),
    }
)
_BASE = vol.Schema(
    {
        vol.Required("child"): vol.Coerce(int),
        vol.Required("service"): vol.In(KINDS),
        vol.Required("date"): cv.date,
        vol.Required("booked"): cv.boolean,
    }
)
_CHANGES = vol.All(cv.ensure_list, vol.Length(min=1, max=200), [_CHANGE])


@callback
def async_setup_websocket(hass: HomeAssistant) -> None:
    websocket_api.async_register_command(hass, ws_planning)
    websocket_api.async_register_command(hass, ws_quote)
    websocket_api.async_register_command(hass, ws_apply)


def _entry(hass: HomeAssistant, entry_id: str | None) -> MefCoordinator:
    for entry in hass.config_entries.async_entries(DOMAIN):
        if entry.state is not ConfigEntryState.LOADED:
            continue
        if entry_id in (None, entry.entry_id):
            return entry.runtime_data
    raise _Error("not_found", "No such Mon Espace Famille account")


class _Error(Exception):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code


def _handler(func):
    """Turn the portal's and the card's errors into WebSocket errors."""

    async def wrapper(hass: HomeAssistant, connection, msg: dict) -> None:
        try:
            connection.send_result(msg["id"], await func(hass, msg))
        except _Error as err:
            connection.send_error(msg["id"], err.code, str(err))
        except MefAuthError as err:
            coordinator = _entry(hass, msg.get("entry_id"))
            coordinator.config_entry.async_start_reauth(hass)
            connection.send_error(msg["id"], "auth_failed", str(err))
        except MefError as err:
            connection.send_error(msg["id"], "portal_error", str(err))

    return wrapper


def _names(coordinator: MefCoordinator) -> dict[int, str]:
    return {c.id: c.first_name for c in coordinator.data.children.values()}


def _window(coordinator: MefCoordinator) -> list[Child]:
    return list(coordinator.data.children.values())


async def _planning(hass: HomeAssistant, msg: dict) -> dict:
    coordinator = _entry(hass, msg.get("entry_id"))
    monday = monday_of(msg["start"])
    today = dt_util.now().date()
    week = await coordinator.async_week(monday, fresh=msg.get("fresh", False))
    cal = Calendar.of(_window(coordinator) + list(week.values()), today)
    out = build_week(week, _names(coordinator), monday, today, cal, coordinator.settings.hours)
    out["entry_id"] = coordinator.config_entry.entry_id
    out["commune"] = coordinator.data.commune
    return out


@websocket_api.websocket_command(
    {
        vol.Required("type"): "mon_espace_famille/planning",
        vol.Required("start"): cv.date,
        vol.Optional("entry_id"): str,
        vol.Optional("fresh"): bool,
    }
)
@websocket_api.async_response
async def ws_planning(hass: HomeAssistant, connection, msg: dict) -> None:
    await _handler(_planning)(hass, connection, msg)


async def _weeks_for(
    coordinator: MefCoordinator, changes: list[Change], *, fresh: bool
) -> dict[tuple[int, date], Child]:
    """Each child's weeks touched by the changes, as the portal has them."""
    mondays = sorted({monday_of(c.day) for c in changes})
    found: dict[tuple[int, date], Child] = {}
    for monday in mondays:
        for child_id, child in (await coordinator.async_week(monday, fresh=fresh)).items():
            found[(child_id, monday)] = child
    return found


def _amount(pricing: list) -> float | None:
    """The total of a pricing answer, None when the portal announces nothing.

    The web app keeps the lines whose `presta` has an `amount` above zero.
    """
    seen: set[Any] = set()
    total = 0.0
    for line in pricing:
        for presta in (line or {}).get("presta") or []:
            amount = presta.get("amount")
            if isinstance(amount, (int, float)) and amount > 0 and presta.get("id") not in seen:
                seen.add(presta.get("id"))
                total += float(amount)
    return round(total, 2) if seen else None


def _counts(changes: list[Change]) -> list[dict]:
    counts: dict[str, dict[str, int]] = {}
    for ch in changes:
        counts.setdefault(ch.service, {BOOK: 0, CANCEL: 0})[ch.action] += 1
    return [
        {"service": k, "name": KIND_NAMES[k], "book": v[BOOK], "cancel": v[CANCEL]}
        for k, v in counts.items()
    ]


async def _portal_check(
    coordinator: MefCoordinator,
    changes: list[Change],
    week_of: dict[tuple[int, date], Child],
    entries: list[dict],
) -> tuple[float | None, bool, list[dict]]:
    """(amount, post_paid, lines the portal refuses) for the carts, read-only."""
    amount_total: float | None = None
    refused: list[dict] = []
    for entry in entries:
        child_id = entry["childId"]
        raw = []
        for monday in sorted({monday_of(c.day) for c in changes if c.child == child_id}):
            for service in await coordinator.client.services_raw(child_id, monday):
                raw.append(dict(service, childId=child_id))
        try:
            amount = _amount(await coordinator.client.pricing([entry], raw))
            answer = await coordinator.client.calculate([entry], raw)
        except MefAuthError:
            raise
        except MefError as err:
            _LOGGER.debug("Pricing unavailable: %s", err)
            continue
        if amount is not None:
            amount_total = (amount_total or 0.0) + amount
        errors = answer.get("panierLigneErreur") or {}
        for key in ("reservations", "annulations"):
            for line in errors.get(key) or []:
                refused.append(
                    {
                        "child": line.get("identifiantEnfant", child_id),
                        "date": str(line.get("date", "")),
                        "kind": key,
                    }
                )
    post_paid = all(
        s.payment_mode == "POST"
        for (cid, _), child in week_of.items()
        for s in child.services.values()
        if cid in {c.child for c in changes} and s.kind in {c.service for c in changes}
    )
    return amount_total, post_paid, refused


async def _estimate(
    coordinator: MefCoordinator, valid: list[Change], week_of: dict[tuple[int, date], Child]
) -> dict:
    """The monthly cost difference of the changes, from the portal's rates."""
    settings = coordinator.settings
    unavailable = {
        "available": False,
        "total": None,
        "currency": "EUR",
        "lines": [],
        "custom": settings.customised,
    }
    names = _names(coordinator)
    try:
        rates: dict[tuple[int, str], float | None] = {}
        for ch in valid:
            if (ch.child, ch.service) in rates:
                continue
            service = service_of(week_of[(ch.child, monday_of(ch.day))], ch.service)
            if (price := settings.prices.get(ch.service)) is not None:
                rates[(ch.child, ch.service)] = price  # the household's own price
                continue
            by_id = await coordinator.async_rates(ch.child)
            rates[(ch.child, ch.service)] = by_id.get(service.service_id) if service else None
        # Every week of the touched months, to count what is booked already.
        months = {(c.day.year, c.day.month) for c in valid}
        mondays = set()
        for year, month in months:
            first, last = month_bounds(year, month)
            candidates = (monday_of(first) + timedelta(weeks=n) for n in range(6))
            mondays.update(m for m in candidates if m <= last)
        counts: dict[tuple[int, str, str], int] = {}
        for monday in sorted(mondays):
            for child_id, child in (await coordinator.async_week(monday)).items():
                for service in child.services.values():
                    for day, entry in service.days.items():
                        if (day.year, day.month) in months and entry.status in BOOKED_STATES:
                            key = (child_id, service.kind or "", f"{day.year}-{day.month:02d}")
                            counts[key] = counts.get(key, 0) + 1
    except MefAuthError:
        raise
    except MefError as err:
        _LOGGER.debug("Rates unavailable: %s", err)
        return unavailable
    return estimate(
        counts, [(c.child, c.service, c.day, c.action) for c in valid], rates, names, settings
    )


async def _quote(hass: HomeAssistant, msg: dict) -> dict:
    coordinator = _entry(hass, msg.get("entry_id"))
    changes = [Change(c["child"], c["service"], c["date"], c["action"]) for c in msg["changes"]]
    today = dt_util.now().date()
    week_of = await _weeks_for(coordinator, changes, fresh=True)
    _, refused = check(changes, week_of, {}, today)
    blocked = {(r["child"], r["service"], r["date"]): r["reason"] for r in refused}
    names = _names(coordinator)
    items = []
    for ch in changes:
        service = (
            service_of(week_of[(ch.child, monday_of(ch.day))], ch.service)
            if ((ch.child, monday_of(ch.day)) in week_of)
            else None
        )
        entry = service.days.get(ch.day) if service else None
        reason = blocked.get((ch.child, ch.service, ch.day.isoformat()))
        items.append(
            {
                "child": ch.child,
                "child_name": names.get(ch.child, ""),
                "service": ch.service,
                "date": ch.day.isoformat(),
                "week": ch.day.isocalendar().week,
                "monday": monday_of(ch.day).isoformat(),
                "action": ch.action,
                "valid": reason is None,
                "reason": reason,
                "cancel_deadline": entry.deadline.isoformat() if entry and entry.deadline else None,
            }
        )
    valid = [ch for ch, item in zip(changes, items, strict=True) if item["valid"]]
    amount, post_paid, portal_errors = None, False, []
    est = {"available": False, "total": None, "currency": "EUR", "lines": [], "custom": False}
    if valid:
        amount, post_paid, portal_errors = await _portal_check(
            coordinator, valid, week_of, carts(valid, week_of)
        )
        if amount is None:
            est = await _estimate(coordinator, valid, week_of)
    return {
        "items": items,
        "valid": len(valid) == len(items) and not portal_errors,
        "portal_errors": portal_errors,
        "cost": {
            "mode": "amount"
            if amount is not None
            else "estimate"
            if est["available"]
            else "counts",
            "amount": amount if amount is not None else est["total"],
            "estimate": est,
            "currency": "EUR",
            "post_paid": post_paid,
            "counts": _counts(valid),
        },
    }


@websocket_api.websocket_command(
    {
        vol.Required("type"): "mon_espace_famille/quote",
        vol.Required("changes"): _CHANGES,
        vol.Optional("entry_id"): str,
    }
)
@websocket_api.async_response
async def ws_quote(hass: HomeAssistant, connection, msg: dict) -> None:
    await _handler(_quote)(hass, connection, msg)


async def _confirm(
    coordinator: MefCoordinator, child_id: int, changes: list[Change]
) -> dict[tuple[int, str, date], bool]:
    """Read the child's weeks until the changes show, a bounded number of times."""
    mondays = sorted({monday_of(c.day) for c in changes})
    done: dict[tuple[int, str, date], bool] = {}
    for _ in range(VERIFY_ATTEMPTS):
        await asyncio.sleep(VERIFY_DELAY)
        child = await coordinator.async_refresh_child(child_id, mondays)
        # The refreshed child holds every week fetched; look each change up in its own.
        week_of = {(child_id, monday_of(c.day)): child for c in changes}
        done = {c.key(): is_done(c, week_of) for c in changes}
        if all(done.values()):
            break
    return done


async def _apply(hass: HomeAssistant, msg: dict) -> dict:
    coordinator = _entry(hass, msg.get("entry_id"))
    changes = [Change(c["child"], c["service"], c["date"], c["action"]) for c in msg["changes"]]
    keys = [c.key() for c in changes]
    if len(set(keys)) != len(keys):
        raise _Error("invalid_format", "The same cell is changed twice")
    base = {(b["child"], b["service"], b["date"]): b["booked"] for b in msg["base"]}
    today = dt_util.now().date()
    async with action_lock(hass):
        week_of = await _weeks_for(coordinator, changes, fresh=True)
        conflicts, refused = check(changes, week_of, base, today)
        if conflicts or refused:
            return {
                "status": "conflict" if conflicts else "refused",
                "conflicts": conflicts,
                "refused": refused,
                "applied": [],
                "results": [],
            }
        names = _names(coordinator)
        results: dict[tuple[int, str, date], str] = {}
        for entry in carts(changes, week_of):
            child_id = entry["childId"]
            mine = [c for c in changes if c.child == child_id]
            try:
                _LOGGER.debug("Sending cart %s", entry)
                await coordinator.client.send_cart(entry)
            except MefAuthError:
                raise
            except MefError as err:
                _LOGGER.warning("Cart of %s refused: %s", names.get(child_id), err)
                results.update({c.key(): "error" for c in mine})
                continue
            done = await _confirm(coordinator, child_id, mine)
            results.update({k: "applied" if ok else "not_confirmed" for k, ok in done.items()})
        coordinator.forget_weeks()
    out = [
        {
            "child": c.child,
            "service": c.service,
            "date": c.day.isoformat(),
            "action": c.action,
            "result": results[c.key()],
        }
        for c in changes
    ]
    failed = [r for r in out if r["result"] != "applied"]
    return {
        "status": "applied" if not failed else ("partial" if len(failed) < len(out) else "failed"),
        "conflicts": [],
        "refused": [],
        "results": out,
    }


@websocket_api.websocket_command(
    {
        vol.Required("type"): "mon_espace_famille/apply",
        vol.Required("changes"): _CHANGES,
        vol.Required("base"): vol.All(cv.ensure_list, [_BASE]),
        vol.Optional("entry_id"): str,
    }
)
@websocket_api.async_response
async def ws_apply(hass: HomeAssistant, connection, msg: dict) -> None:
    await _handler(_apply)(hass, connection, msg)
