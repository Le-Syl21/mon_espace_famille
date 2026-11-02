"""The reserver and annuler actions, against the fake server."""

import json
from urllib.parse import quote

import pytest
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError, ServiceValidationError
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers import entity_registry as er

from custom_components.mon_espace_famille.const import DOMAIN

from .conftest import ALICE, FakeMef


def _device(hass: HomeAssistant, name: str) -> str:
    entry = hass.config_entries.async_entries(DOMAIN)[0]
    devices = dr.async_entries_for_config_entry(dr.async_get(hass), entry.entry_id)
    return next(d.id for d in devices if d.name == name)


def _form(item: dict) -> str:
    """What the web app sends: cart=<URL-encoded JSON>."""
    text = json.dumps(item, ensure_ascii=False, separators=(",", ":"))
    return "cart=" + quote(text, safe="!'()*~")


async def _call(hass: HomeAssistant, action: str, **data):
    return await hass.services.async_call(DOMAIN, action, data, blocking=True, return_response=True)


async def test_book(hass: HomeAssistant, setup, fake: FakeMef) -> None:
    await setup()
    # Thursday 12 next week, Monday 16 the week after: two weeks, one cart.
    response = await _call(
        hass,
        "reserver",
        enfant=_device(hass, "Alice"),
        service="accueil_soir",
        dates=["2026-11-16", "12/11/2026"],
    )
    assert response == {"dates": ["2026-11-12", "2026-11-16"]}
    cart = {
        "childId": ALICE,
        "servicesReservations": [
            {
                "dates": [{"date": "20261112"}, {"date": "20261116"}],
                "serviceReservationId": "7_7",
                "serviceId": 1,
            }
        ],
        "cancelationReservations": [],
    }
    assert fake.carts == [cart]
    assert fake.bodies == [_form(cart)]
    assert fake.bodies[0].startswith(
        "cart=%7B%22childId%22%3A101%2C%22servicesReservations%22%3A%5B%7B%22dates%22%3A%5B"
    )
    # The entities follow without waiting for the next poll.
    week = hass.states.get("sensor.alice_accueil_soir_cette_semaine")
    assert week.state == "0"
    events = await hass.services.async_call(
        "calendar",
        "get_events",
        {
            "entity_id": "calendar.alice_periscolaire",
            "start_date_time": "2026-11-12 00:00:00",
            "end_date_time": "2026-11-13 00:00:00",
        },
        blocking=True,
        return_response=True,
    )
    assert [e["summary"] for e in events["calendar.alice_periscolaire"]["events"]] == [
        "Cantine",
        "Accueil du soir",
    ]


async def test_book_skips_booked_days(hass: HomeAssistant, setup, fake: FakeMef) -> None:
    await setup()
    entity = er.async_get(hass).async_get("calendar.alice_periscolaire")
    response = await _call(
        hass, "reserver", enfant=entity.entity_id, service="repas", dates=["2026-11-09"]
    )
    assert response == {"dates": []} and fake.carts == []


async def test_book_closed_day(hass: HomeAssistant, setup, fake: FakeMef) -> None:
    await setup()
    # 11 November is a public holiday: not an open day.
    with pytest.raises(ServiceValidationError) as err:
        await _call(
            hass,
            "reserver",
            enfant=_device(hass, "Alice"),
            service="accueil_soir",
            dates=["2026-11-10", "2026-11-11"],
        )
    assert err.value.translation_key == "not_open"
    assert err.value.translation_placeholders["dates"] == "11/11/2026"
    assert fake.carts == []


async def test_book_unregistered(hass: HomeAssistant, setup, fake: FakeMef) -> None:
    await setup()
    with pytest.raises(ServiceValidationError) as err:
        await _call(
            hass,
            "reserver",
            enfant=_device(hass, "Alice"),
            service="accueil_matin",
            dates=["2026-11-12"],
        )
    assert err.value.translation_key == "not_registered"
    with pytest.raises(ServiceValidationError) as err:
        await _call(hass, "reserver", enfant="nobody", service="repas", dates=["2026-11-12"])
    assert err.value.translation_key == "unknown_child"
    assert fake.carts == []


async def test_book_not_applied(hass: HomeAssistant, setup, fake: FakeMef) -> None:
    await setup()
    fake.apply_carts = False
    with pytest.raises(HomeAssistantError) as err:
        await _call(
            hass,
            "reserver",
            enfant=_device(hass, "Alice"),
            service="etude",
            dates=["2026-11-12"],
        )
    assert err.value.translation_key == "not_confirmed"
    assert len(fake.carts) == 1


async def test_cancel(hass: HomeAssistant, setup, fake: FakeMef) -> None:
    await setup()
    response = await _call(
        hass,
        "annuler",
        enfant=_device(hass, "Alice"),
        service="7_7",
        dates=["2026-11-13"],
    )
    assert response == {"dates": ["2026-11-13"]}
    cart = {
        "childId": ALICE,
        "servicesReservations": [],
        "cancelationReservations": [
            {
                "dates": [{"date": "20261113"}],
                "serviceReservationId": "7_7",
                "serviceId": 1,
                "reservationsIds": [5011],
            }
        ],
    }
    assert fake.carts == [cart]
    assert fake.bodies == [_form(cart)]


async def test_cancel_errors(hass: HomeAssistant, setup, fake: FakeMef) -> None:
    await setup()
    alice = _device(hass, "Alice")
    # Thursday 5's meal could be cancelled until Tuesday 3.
    with pytest.raises(ServiceValidationError) as err:
        await _call(hass, "annuler", enfant=alice, service="repas", dates=["2026-11-05"])
    assert err.value.translation_key == "too_late"
    # Tuesday 3 is marked attended: no longer a booking that can go.
    with pytest.raises(ServiceValidationError) as err:
        await _call(hass, "annuler", enfant=alice, service="repas", dates=["2026-11-03"])
    assert err.value.translation_key == "too_late"
    with pytest.raises(ServiceValidationError) as err:
        await _call(hass, "annuler", enfant=alice, service="accueil_soir", dates=["2026-11-12"])
    assert err.value.translation_key == "not_booked"
    assert fake.carts == []


async def test_cancel_not_applied(hass: HomeAssistant, setup, fake: FakeMef) -> None:
    await setup()
    fake.apply_carts = False
    with pytest.raises(HomeAssistantError) as err:
        await _call(
            hass, "annuler", enfant=_device(hass, "Alice"), service="repas", dates=["2026-11-13"]
        )
    assert err.value.translation_key == "not_confirmed"
    assert fake.carts[0]["cancelationReservations"][0]["reservationsIds"] == [5009]


async def test_bad_date(hass: HomeAssistant, setup) -> None:
    await setup()
    with pytest.raises(Exception, match="invalid date"):
        await _call(
            hass, "reserver", enfant=_device(hass, "Alice"), service="repas", dates=["demain"]
        )
