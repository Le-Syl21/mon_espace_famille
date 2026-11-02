"""Evening care today, expected return home and "away from home", the server faked."""

import copy
import itertools
from datetime import datetime

from homeassistant.core import HomeAssistant
from pytest_homeassistant_custom_component.common import async_fire_time_changed

from custom_components.mon_espace_famille import binary_sensor

from .conftest import ALICE, BOB, NOW, PARIS, FakeMef
from .test_integration import state

_IDS = itertools.count(7000)
TODAY = "20261104"  # NOW is that Wednesday, 10:00 in Paris (UTC+1)


def at(hour: int, minute: int = 0, second: int = 0) -> datetime:
    return NOW.replace(hour=hour, minute=minute, second=second)


def book(fake: FakeMef, child: int, sid: str, day: str = TODAY) -> None:
    """Book a day of a service on the fake server (adding the service if need be)."""
    monday = "20261102"
    for week in (monday, "20261109"):
        services = fake.week(child, week)
        if not any(s["id"] == sid for s in services):
            model = copy.deepcopy(services[1])  # ACCUEIL SOIR, without its days
            model.update(id=sid, label="ACCUEIL MATIN")
            services.append(model)
    service = next(s for s in fake.week(child, monday) if s["id"] == sid)
    service.setdefault("validated", []).append(
        {"date": day, "dteLimiteSupp": "20261103", "id": next(_IDS)}
    )


async def test_evening_care_booked(hass: HomeAssistant, setup, fake: FakeMef) -> None:
    book(fake, ALICE, "7_7")
    book(fake, ALICE, "1_1")
    await setup()
    evening = state(hass, "binary_sensor.alice_accueil_du_soir_aujourd_hui")
    assert evening.state == "on"
    assert evening.attributes["service"] == "accueil_soir"
    assert evening.attributes["friendly_name"] == "Alice Evening care today"
    # Deadline of the fake booking was yesterday: not cancellable any more.
    assert evening.attributes["annulable_jusqu_au"] is None
    back = state(hass, "sensor.alice_retour_prevu")
    # 18:45 plus the 10 minutes of travel, Paris time (17:55 UTC).
    assert back.state == "2026-11-04T17:55:00+00:00"
    assert back.attributes["device_class"] == "timestamp"
    assert back.attributes["service_du_soir"] is True


async def test_evening_deadline_attribute(hass: HomeAssistant, setup, fake: FakeMef) -> None:
    book(fake, ALICE, "7_7")
    service = next(s for s in fake.week(ALICE, "20261102") if s["id"] == "7_7")
    service["validated"][0]["dteLimiteSupp"] = "20261104"
    await setup()
    evening = state(hass, "binary_sensor.alice_accueil_du_soir_aujourd_hui")
    assert evening.attributes["annulable_jusqu_au"] == "2026-11-04"


async def test_study_hall_counts_as_evening(hass: HomeAssistant, setup, fake: FakeMef) -> None:
    book(fake, BOB, "8_8")
    await setup()
    evening = state(hass, "binary_sensor.bob_accueil_du_soir_aujourd_hui")
    assert evening.state == "on" and evening.attributes["service"] == "etude"
    back = state(hass, "sensor.bob_retour_prevu")
    assert back.state == "2026-11-04T17:55:00+00:00"
    assert back.attributes["service_du_soir"] is True


async def test_school_only_returns_after_school(hass: HomeAssistant, setup, fake: FakeMef) -> None:
    book(fake, BOB, "1_1")  # a canteen meal and nothing in the evening
    await setup()
    assert state(hass, "binary_sensor.bob_accueil_du_soir_aujourd_hui").state == "off"
    assert (
        state(hass, "binary_sensor.bob_accueil_du_soir_aujourd_hui").attributes["service"] is None
    )
    back = state(hass, "sensor.bob_retour_prevu")
    assert back.state == "2026-11-04T15:40:00+00:00"  # 16:30 + 10 min, Paris
    assert back.attributes["service_du_soir"] is False


async def test_nothing_booked_today(hass: HomeAssistant, setup) -> None:
    await setup()
    # Alice has meals on Thursday and Friday, but nothing on Wednesday.
    assert state(hass, "binary_sensor.alice_accueil_du_soir_aujourd_hui").state == "off"
    assert state(hass, "sensor.alice_retour_prevu").state == "unknown"
    assert state(hass, "sensor.alice_retour_prevu").attributes["service_du_soir"] is False
    assert state(hass, "binary_sensor.alice_hors_de_la_maison").state == "off"


async def test_children_without_service_have_none(hass: HomeAssistant, setup) -> None:
    await setup()
    for entity in (
        "binary_sensor.chloe_accueil_du_soir_aujourd_hui",
        "sensor.chloe_retour_prevu",
        "binary_sensor.chloe_hors_de_la_maison",
        "binary_sensor.dan_hors_de_la_maison",
    ):
        assert hass.states.get(entity) is None, entity


async def test_away_boundaries(hass: HomeAssistant, setup, fake: FakeMef, freezer) -> None:
    book(fake, ALICE, "7_7")
    await setup()
    away = "binary_sensor.alice_hors_de_la_maison"
    assert state(hass, away).state == "on"  # 10:00

    async def go(when: datetime) -> str:
        freezer.move_to(when)
        async_fire_time_changed(hass, when)
        await hass.async_block_till_done()
        return state(hass, away).state

    # No poll happens in between: only the timer flips the sensor.
    assert await go(at(18, 54, 59)) == "on"
    assert await go(at(18, 55, 1)) == "off"
    assert await go(at(23, 0)) == "off"


async def test_away_starts_with_school(hass: HomeAssistant, setup, fake: FakeMef, freezer) -> None:
    book(fake, ALICE, "7_7")
    await setup(now=at(7, 30))
    away = "binary_sensor.alice_hors_de_la_maison"
    assert state(hass, away).state == "off"
    for when, expected in (
        (at(7, 59, 59), "off"),
        (at(8, 10, 1), "on"),
        (at(18, 54, 59), "on"),
        (at(18, 55, 1), "off"),
    ):
        freezer.move_to(when)
        async_fire_time_changed(hass, when)
        await hass.async_block_till_done()
        assert state(hass, away).state == expected, when
    attrs = state(hass, away).attributes
    assert attrs["depart"] == "2026-11-04T08:10:00+01:00"
    assert attrs["retour_prevu"] == "2026-11-04T18:55:00+01:00"


async def test_away_with_morning_care(hass: HomeAssistant, setup, fake: FakeMef, freezer) -> None:
    book(fake, ALICE, "6_6")
    book(fake, ALICE, "1_1")
    await setup(now=at(6, 30))
    away = "binary_sensor.alice_hors_de_la_maison"
    assert state(hass, away).attributes["depart"] == "2026-11-04T07:00:00+01:00"
    assert state(hass, away).attributes["retour_prevu"] == "2026-11-04T16:40:00+01:00"
    assert state(hass, "sensor.alice_retour_prevu").state == "2026-11-04T15:40:00+00:00"
    assert state(hass, away).state == "off"
    for when, expected in (
        (at(6, 59, 59), "off"),
        (at(7, 0, 1), "on"),
        (at(16, 39, 59), "on"),
        (at(16, 40, 1), "off"),
    ):
        freezer.move_to(when)
        async_fire_time_changed(hass, when)
        await hass.async_block_till_done()
        assert state(hass, away).state == expected, when


async def test_midnight_rollover(hass: HomeAssistant, setup, fake: FakeMef, freezer) -> None:
    # Alice: evening care on Wednesday, only meals (no evening) on Thursday.
    book(fake, ALICE, "7_7")
    await setup()
    away = "binary_sensor.alice_hors_de_la_maison"
    back = "sensor.alice_retour_prevu"
    evening = "binary_sensor.alice_accueil_du_soir_aujourd_hui"
    assert state(hass, back).state == "2026-11-04T17:55:00+00:00"

    # Thursday 5 November, just after the midnight tick (00:00:05): the
    # sensors follow without the 30-minute poll.
    when = datetime(2026, 11, 5, 0, 0, 6, tzinfo=PARIS)
    freezer.move_to(when)
    async_fire_time_changed(hass, when)
    await hass.async_block_till_done()
    assert state(hass, evening).state == "off"
    assert state(hass, back).state == "2026-11-05T15:40:00+00:00"  # the meal: 16:30 + 10
    assert state(hass, away).state == "off"  # not yet 8:10
    assert state(hass, away).attributes["depart"] == "2026-11-05T08:10:00+01:00"

    # And the new day's timers are armed: 8:10 flips it on.
    when = datetime(2026, 11, 5, 8, 10, 1, tzinfo=PARIS)
    freezer.move_to(when)
    async_fire_time_changed(hass, when)
    await hass.async_block_till_done()
    assert state(hass, away).state == "on"


async def test_timer_cleaned_up_on_unload(
    hass: HomeAssistant, setup, fake: FakeMef, monkeypatch
) -> None:
    live: set[int] = set()
    real = binary_sensor.async_track_point_in_time

    def tracking(hass_, action, point):
        unsub = real(hass_, action, point)
        key = len(live) + 1000 * len(fake.carts) + id(unsub)
        live.add(key)

        def cancel():
            live.discard(key)
            unsub()

        return cancel

    monkeypatch.setattr(binary_sensor, "async_track_point_in_time", tracking)
    book(fake, ALICE, "7_7")
    book(fake, BOB, "1_1")
    entry = await setup()
    assert len(live) == 2  # one pending boundary for each child
    assert await hass.config_entries.async_unload(entry.entry_id)
    await hass.async_block_till_done()
    assert not live
