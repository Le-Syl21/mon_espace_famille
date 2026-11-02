"""Actions: book and cancel days of a service for a child."""

from __future__ import annotations

import asyncio
import logging
from datetime import date, datetime
from typing import Any

import voluptuous as vol
from homeassistant.config_entries import ConfigEntryState
from homeassistant.core import HomeAssistant, ServiceCall, ServiceResponse, SupportsResponse
from homeassistant.exceptions import HomeAssistantError, ServiceValidationError
from homeassistant.helpers import config_validation as cv
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers import entity_registry as er
from homeassistant.util import dt as dt_util

from .api import MefAuthError, MefError, api_date
from .const import (
    ATTR_CHILD,
    ATTR_DATES,
    ATTR_SERVICE,
    DOMAIN,
    KIND_NAMES,
    KINDS,
    SERVICE_BOOK,
    SERVICE_CANCEL,
    STATUS_BOOKED,
    STATUS_BOOKING_PENDING,
    STATUS_PRESENT,
    VERIFY_ATTEMPTS,
    VERIFY_DELAY,
)
from .coordinator import MefConfigEntry, MefCoordinator
from .model import Child, Service, monday_of

_LOGGER = logging.getLogger(__name__)
# A booking shows up as validated (or pending, where the commune validates by
# hand); "present" covers a commune that marks it attended straight away.
_BOOKED_NOW = frozenset({STATUS_BOOKED, STATUS_BOOKING_PENDING, STATUS_PRESENT})


def _date(value: Any) -> date:
    """A date, as a date, "YYYY-MM-DD" or "DD/MM/YYYY"."""
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    if isinstance(value, str):
        text = value.strip()
        for fmt in ("%Y-%m-%d", "%d/%m/%Y"):
            try:
                return datetime.strptime(text, fmt).date()
            except ValueError:
                pass
    raise vol.Invalid(f"invalid date: {value!r}")


SCHEMA = vol.Schema(
    {
        vol.Required(ATTR_CHILD): cv.string,
        vol.Required(ATTR_SERVICE): cv.string,
        vol.Required(ATTR_DATES): vol.All(cv.ensure_list, vol.Length(min=1), [_date]),
    }
)


def _fr_list(days: list[date]) -> str:
    return ", ".join(d.strftime("%d/%m/%Y") for d in days)


def _resolve_child(hass: HomeAssistant, ref: str) -> tuple[MefCoordinator, int]:
    """The coordinator and child id of a device id or of one of its entities."""
    devices = dr.async_get(hass)
    device = devices.async_get(ref)
    if device is None and (entity := er.async_get(hass).async_get(ref)) and entity.device_id:
        device = devices.async_get(entity.device_id)
    if device is not None:
        for domain, ident in device.identifiers:
            if domain != DOMAIN:
                continue
            entry_id, _, child_id = ident.rpartition("_")
            entry: MefConfigEntry | None = hass.config_entries.async_get_entry(entry_id)
            if (
                entry is not None
                and entry.state is ConfigEntryState.LOADED
                and child_id.isdigit()
                and int(child_id) in entry.runtime_data.data.children
            ):
                return entry.runtime_data, int(child_id)
    raise ServiceValidationError(
        translation_domain=DOMAIN,
        translation_key="unknown_child",
        translation_placeholders={"child": ref},
    )


def _resolve_service(child: Child, ref: str) -> Service:
    """A service of the child, by kind ("repas") or by the API's id ("1_1")."""
    if ref in child.services:
        return child.services[ref]
    if ref in KINDS and (found := child.services_of_kind(ref)):
        return found[0]
    raise ServiceValidationError(
        translation_domain=DOMAIN,
        translation_key="not_registered",
        translation_placeholders={
            "child": child.first_name,
            "service": KIND_NAMES.get(ref, ref),
        },
    )


async def _fresh(coordinator: MefCoordinator, child_id: int, days: list[date]) -> Child:
    try:
        return await coordinator.async_refresh_child(child_id, [monday_of(d) for d in days])
    except MefAuthError as err:
        coordinator.config_entry.async_start_reauth(coordinator.hass)
        raise HomeAssistantError(translation_domain=DOMAIN, translation_key="auth_failed") from err
    except MefError as err:
        raise HomeAssistantError(
            translation_domain=DOMAIN,
            translation_key="api_error",
            translation_placeholders={"error": str(err)},
        ) from err


async def _send(coordinator: MefCoordinator, cart_item: dict) -> None:
    _LOGGER.debug("Sending cart %s", cart_item)
    try:
        await coordinator.client.send_cart(cart_item)
    except MefAuthError as err:
        coordinator.config_entry.async_start_reauth(coordinator.hass)
        raise HomeAssistantError(translation_domain=DOMAIN, translation_key="auth_failed") from err
    except MefError as err:
        raise HomeAssistantError(
            translation_domain=DOMAIN,
            translation_key="api_error",
            translation_placeholders={"error": str(err)},
        ) from err


async def _verify(coordinator: MefCoordinator, child_id: int, sid: str, days: list[date], done):
    """Read the weeks again until `done(service)` holds; bounded."""
    for _ in range(VERIFY_ATTEMPTS):
        await asyncio.sleep(VERIFY_DELAY)
        child = await _fresh(coordinator, child_id, days)
        service = child.services.get(sid)
        if service is not None and done(service):
            return
    raise HomeAssistantError(
        translation_domain=DOMAIN,
        translation_key="not_confirmed",
        translation_placeholders={"dates": _fr_list(days)},
    )


async def _prepare(hass: HomeAssistant, call: ServiceCall):
    coordinator, child_id = _resolve_child(hass, call.data[ATTR_CHILD])
    days = sorted(set(call.data[ATTR_DATES]))
    # The registration is checked on the cached data first (a clear error
    # without a request), then everything else on the weeks read again now.
    _resolve_service(coordinator.data.children[child_id], call.data[ATTR_SERVICE])
    child = await _fresh(coordinator, child_id, days)
    service = _resolve_service(child, call.data[ATTR_SERVICE])
    return coordinator, child, service, days


def _response(call: ServiceCall, days: list[date]) -> ServiceResponse:
    if not call.return_response:
        return None
    return {"dates": [d.isoformat() for d in days]}


async def _book(hass: HomeAssistant, call: ServiceCall) -> ServiceResponse:
    coordinator, child, service, days = await _prepare(hass, call)
    todo = [d for d in days if not (d in service.days and service.days[d].reserved)]
    if closed := [d for d in todo if not service.bookable(d)]:
        raise ServiceValidationError(
            translation_domain=DOMAIN,
            translation_key="not_open",
            translation_placeholders={"service": service.label, "dates": _fr_list(closed)},
        )
    if not todo:
        return _response(call, [])
    await _send(
        coordinator,
        {
            "childId": child.id,
            "servicesReservations": [
                {
                    "dates": [{"date": api_date(d)} for d in todo],
                    "serviceReservationId": service.id,
                    "serviceId": service.service_id,
                }
            ],
            "cancelationReservations": [],
        },
    )
    await _verify(
        coordinator,
        child.id,
        service.id,
        todo,
        lambda s: all(d in s.days and s.days[d].status in _BOOKED_NOW for d in todo),
    )
    return _response(call, todo)


async def _cancel(hass: HomeAssistant, call: ServiceCall) -> ServiceResponse:
    coordinator, child, service, days = await _prepare(hass, call)
    today = dt_util.now().date()
    if missing := [d for d in days if d not in service.days or not service.days[d].reserved]:
        raise ServiceValidationError(
            translation_domain=DOMAIN,
            translation_key="not_booked",
            translation_placeholders={"service": service.label, "dates": _fr_list(missing)},
        )
    if late := [d for d in days if not service.days[d].cancellable(today)]:
        raise ServiceValidationError(
            translation_domain=DOMAIN,
            translation_key="too_late",
            translation_placeholders={"service": service.label, "dates": _fr_list(late)},
        )
    await _send(
        coordinator,
        {
            "childId": child.id,
            "servicesReservations": [],
            "cancelationReservations": [
                {
                    "dates": [{"date": api_date(d)} for d in days],
                    "serviceReservationId": service.id,
                    "serviceId": service.service_id,
                    "reservationsIds": [service.days[d].reservation_id for d in days],
                }
            ],
        },
    )
    await _verify(
        coordinator,
        child.id,
        service.id,
        days,
        lambda s: all(d not in s.days or s.days[d].status != STATUS_BOOKED for d in days),
    )
    return _response(call, days)


def async_setup_services(hass: HomeAssistant) -> None:
    lock = asyncio.Lock()

    async def book(call: ServiceCall) -> ServiceResponse:
        async with lock:
            return await _book(hass, call)

    async def cancel(call: ServiceCall) -> ServiceResponse:
        async with lock:
            return await _cancel(hass, call)

    hass.services.async_register(
        DOMAIN, SERVICE_BOOK, book, schema=SCHEMA, supports_response=SupportsResponse.OPTIONAL
    )
    hass.services.async_register(
        DOMAIN, SERVICE_CANCEL, cancel, schema=SCHEMA, supports_response=SupportsResponse.OPTIONAL
    )
