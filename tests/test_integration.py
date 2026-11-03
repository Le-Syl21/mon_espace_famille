"""Entities in a running Home Assistant, the server faked."""

import json
from datetime import date

from homeassistant.config_entries import SOURCE_REAUTH, ConfigEntryState
from homeassistant.core import HomeAssistant
from homeassistant.helpers import device_registry as dr
from pytest_homeassistant_custom_component.test_util.aiohttp import AiohttpClientMocker

from custom_components.mon_espace_famille.calendar import child_events
from custom_components.mon_espace_famille.const import DOMAIN
from custom_components.mon_espace_famille.diagnostics import (
    async_get_config_entry_diagnostics,
)
from custom_components.mon_espace_famille.model import Child, Day, Service

from .conftest import EMAIL, PASSWORD, FakeMef


def state(hass: HomeAssistant, entity_id: str):
    st = hass.states.get(entity_id)
    assert st is not None, entity_id
    return st


async def test_entities(hass: HomeAssistant, setup, aioclient_mock: AiohttpClientMocker) -> None:
    await setup()
    # Wednesday 4 November: no canteen today, Thursday's meal booked.
    today = state(hass, "binary_sensor.alice_cantine_aujourd_hui")
    assert today.state == "off" and today.attributes["date"] == "2026-11-04"
    tomorrow = state(hass, "binary_sensor.alice_cantine_demain")
    assert tomorrow.state == "on"
    assert tomorrow.attributes["statut"] == "reserve"
    # Its deadline (3 November) has passed.
    assert tomorrow.attributes["annulable_jusqu_au"] is None
    nxt = state(hass, "sensor.alice_prochain_repas")
    assert nxt.state == "2026-11-05" and nxt.attributes["dans_jours"] == 1
    # Monday and Tuesday attended, Thursday and Friday booked.
    meals = state(hass, "sensor.alice_repas_cette_semaine")
    assert meals.state == "4"
    assert meals.attributes["jours"] == ["2026-11-02", "2026-11-03", "2026-11-05", "2026-11-06"]
    # Wednesday 4: no meal today, Thursday's is booked.
    assert meals.attributes["aujourd_hui"] is False and meals.attributes["demain"] is True
    assert state(hass, "sensor.alice_accueil_soir_cette_semaine").state == "0"
    assert state(hass, "sensor.alice_etude_cette_semaine").state == "0"
    assert state(hass, "binary_sensor.alice_reservation_manquante").state == "off"
    # Bob has no meal on Thursday 12 next week, though the canteen is open.
    missing = state(hass, "binary_sensor.bob_reservation_manquante")
    assert missing.state == "on" and missing.attributes["jours"] == ["2026-11-12"]

    # Chloé is registered to nothing, Dan is archived: no entities, and Dan
    # is not even asked for.
    assert hass.states.get("calendar.chloe_periscolaire") is None
    assert hass.states.get("sensor.chloe_prochain_repas") is None
    assert not [c for c in aioclient_mock.mock_calls if "/children/104/" in str(c[1])]
    devices = dr.async_entries_for_config_entry(
        dr.async_get(hass), hass.config_entries.async_entries(DOMAIN)[0].entry_id
    )
    assert sorted(d.name for d in devices) == ["Alice", "Bob"]
    assert {d.model for d in devices} == {"Périscolaire · Exempleville"}

    # The current week and three more, for each child.
    starts = sorted(
        {c[1].query["start"] for c in aioclient_mock.mock_calls if "/children/101/" in str(c[1])}
    )
    assert starts == ["20261102", "20261109", "20261116", "20261123"]
    # Every call but the login carries the token.
    calls = [c for c in aioclient_mock.mock_calls if not str(c[1]).endswith("/login")]
    assert all(c[3]["Authorization"] == "Bearer access-1" for c in calls)


async def test_calendar(hass: HomeAssistant, setup) -> None:
    await setup()
    cal = state(hass, "calendar.alice_periscolaire")
    assert cal.attributes["message"] == "Cantine"
    assert cal.attributes["start_time"] == "2026-11-05 11:30:00"
    events = await hass.services.async_call(
        "calendar",
        "get_events",
        {
            "entity_id": "calendar.alice_periscolaire",
            "start_date_time": "2026-11-02 00:00:00",
            "end_date_time": "2026-11-14 00:00:00",
        },
        blocking=True,
        return_response=True,
    )
    got = [
        (e["start"], e["end"], e["summary"], e["description"])
        for e in events["calendar.alice_periscolaire"]["events"]
    ]
    assert got[0] == (
        "2026-11-02T11:30:00+01:00",
        "2026-11-02T13:20:00+01:00",
        "Cantine",
        "Présent.",
    )
    assert got[2] == (
        "2026-11-05T11:30:00+01:00",
        "2026-11-05T13:20:00+01:00",
        "Cantine",
        "Réservé. Date limite d'annulation dépassée (03/11/2026).",
    )
    assert (
        "2026-11-13T16:30:00+01:00",
        "2026-11-13T18:45:00+01:00",
        "Accueil du soir",
        "Réservé. Annulable jusqu'au 12/11/2026 inclus.",
    ) in got
    assert [g[0][:10] for g in got if g[2] == "Cantine"] == [
        "2026-11-02",
        "2026-11-03",
        "2026-11-05",
        "2026-11-06",
        "2026-11-09",
        "2026-11-10",
        "2026-11-12",
        "2026-11-13",
    ]


def test_events_of_other_services() -> None:
    day = date(2026, 11, 9)
    child = Child(id=1, first_name="Alice")
    child.services["3_3"] = Service(
        id="3_3",
        service_id=3,
        label="MERCREDI LOISIRS",
        kind=None,
        days={day: Day("absence_justifiee"), date(2026, 11, 10): Day("present")},
    )
    child.services["6_6"] = Service(
        id="6_6",
        service_id=6,
        label="ACCUEIL MATIN",
        kind="accueil_matin",
        days={day: Day("absent")},
    )
    events = child_events(child, day, date(2026, 11, 11), today=date(2026, 11, 9))
    by = {(e.summary, e.start.isoformat()): e for e in events}
    # Unknown kinds are all-day, absences said in the summary.
    other = by[("Mercredi loisirs (absent)", "2026-11-09")]
    assert other.end == date(2026, 11, 10) and other.description == "Absence justifiée."
    # A day marked attended before it comes is a booking that can't be cancelled.
    assert by[("Mercredi loisirs", "2026-11-10")].description == "Réservé, plus annulable."
    morning = next(e for e in events if e.summary == "Accueil du matin (absent)")
    assert (morning.start.hour, morning.end.hour, morning.end.minute) == (7, 8, 20)


async def test_token_refreshed_on_401(
    hass: HomeAssistant, setup, fake: FakeMef, aioclient_mock: AiohttpClientMocker
) -> None:
    entry = await setup()
    fake.unauthorized = 1
    await entry.runtime_data.async_refresh()
    assert entry.runtime_data.last_update_success
    assert [c for c in aioclient_mock.mock_calls if str(c[1]).endswith("/auth/token")]
    form = next(c[2] for c in aioclient_mock.mock_calls if str(c[1]).endswith("/auth/token"))
    assert form == "client_id=963568d5-b3ca-4d91-8a73-9eebda59822b&refresh_token=refresh-1"


async def test_refresh_refused_logs_in_again(
    hass: HomeAssistant, setup, fake: FakeMef, aioclient_mock: AiohttpClientMocker
) -> None:
    entry = await setup()
    fake.unauthorized = 1
    fake.refresh_works = False
    await entry.runtime_data.async_refresh()
    assert entry.runtime_data.last_update_success
    logins = [c for c in aioclient_mock.mock_calls if str(c[1]).endswith("/login")]
    assert len(logins) == 2


async def test_password_changed_starts_reauth(hass: HomeAssistant, setup, fake: FakeMef) -> None:
    entry = await setup()
    fake.password = "changed"
    fake.unauthorized = 100
    fake.refresh_works = False
    await entry.runtime_data.async_refresh()
    await hass.async_block_till_done()
    flows = hass.config_entries.flow.async_progress()
    assert [f["context"]["source"] for f in flows] == [SOURCE_REAUTH]


async def test_server_down_at_start(hass: HomeAssistant, setup, fake: FakeMef, freezer) -> None:
    from pytest_homeassistant_custom_component.common import MockConfigEntry

    fake.server_error = True
    entry = MockConfigEntry(domain=DOMAIN, data={"email": EMAIL, "password": PASSWORD})
    entry.add_to_hass(hass)
    await hass.config_entries.async_setup(entry.entry_id)
    assert entry.state is ConfigEntryState.SETUP_RETRY


async def test_diagnostics_redacted(hass: HomeAssistant, setup) -> None:
    entry = await setup()
    diag = await async_get_config_entry_diagnostics(hass, entry)
    text = json.dumps(diag, ensure_ascii=False)
    for secret in (EMAIL, PASSWORD, "access-", "refresh-", "Alice", "Bob", "5011"):
        assert secret not in text, secret
    assert diag["entry"]["data"] == {"email": "**REDACTED**", "password": "**REDACTED**"}
    assert diag["children"][0]["services"][0]["days"]["2026-11-05"] == {
        "status": "reserve",
        "deadline": "2026-11-03",
    }


async def test_options_weeks(hass: HomeAssistant, setup, aioclient_mock) -> None:
    entry = await setup()
    result = await hass.config_entries.options.async_init(entry.entry_id)
    result = await hass.config_entries.options.async_configure(result["flow_id"], {"semaines": 1})
    assert entry.options == {"semaines": 1}
    await hass.async_block_till_done()
    aioclient_mock.mock_calls.clear()
    await entry.runtime_data.async_refresh()
    starts = {c[1].query["start"] for c in aioclient_mock.mock_calls if "/children/" in str(c[1])}
    assert starts == {"20261102", "20261109"}
