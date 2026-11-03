"""Prices and hours editable in the options flow, and reaching the code."""

from datetime import date

import pytest
from homeassistant.core import HomeAssistant
from homeassistant.data_entry_flow import InvalidData

from custom_components.mon_espace_famille.calendar import child_events
from custom_components.mon_espace_famille.settings import Settings

from .conftest import ALICE, FakeMef
from .test_planning import _ask, _change, _planning


async def _run_flow(hass, entry, tarifs: dict, horaires: dict, weeks: int = 3):
    result = await hass.config_entries.options.async_init(entry.entry_id)
    assert result["step_id"] == "init"
    result = await hass.config_entries.options.async_configure(
        result["flow_id"], {"semaines": weeks}
    )
    assert result["step_id"] == "tarifs"
    result = await hass.config_entries.options.async_configure(result["flow_id"], tarifs)
    if result.get("errors"):
        return result
    assert result["step_id"] == "horaires"
    return await hass.config_entries.options.async_configure(result["flow_id"], horaires)


HOURS = {
    "start_accueil_matin": "07:00:00",
    "end_accueil_matin": "08:20:00",
    "start_repas": "11:30:00",
    "end_repas": "13:20:00",
    "start_accueil_soir": "16:30:00",
    "end_accueil_soir": "18:45:00",
    "start_etude": "17:00:00",
    "end_etude": "18:30:00",
}


async def test_defaults_are_orgerus() -> None:
    settings = Settings.from_options({})
    assert settings.cap_days == 9 and settings.flat == {
        "accueil_matin": 42.53,
        "accueil_soir": 55.59,
    }
    assert not settings.customised and settings.evening_end.hour == 18


async def test_options_flow_saves_and_reloads(hass: HomeAssistant, setup, fake: FakeMef) -> None:
    entry = await setup()
    result = await _run_flow(
        hass,
        entry,
        {"cap_days": 5, "flat_accueil_soir": 30, "price_repas": 4.5},
        HOURS | {"end_accueil_matin": "08:15:00"},
    )
    assert result["type"] == "create_entry"
    assert entry.options["cap_days"] == 5 and entry.options["flat_accueil_soir"] == 30.0
    assert entry.options["price_repas"] == 4.5 and "price_accueil_soir" not in entry.options
    # A blank flat fee is stored as 0 (none); the hours are stored as HH:MM.
    assert entry.options["flat_accueil_matin"] == 0.0
    assert entry.options["end_accueil_matin"] == "08:15"
    settings = Settings.from_options(entry.options)
    assert settings.customised and settings.prices["repas"] == 4.5
    assert settings.prices["accueil_soir"] is None  # the portal's rate stays the default
    assert "accueil_matin" not in settings.flat


async def test_options_flow_validates(hass: HomeAssistant, setup, fake: FakeMef) -> None:
    entry = await setup()
    # The number fields refuse negatives before the step even runs.
    with pytest.raises(InvalidData):
        await _run_flow(hass, entry, {"cap_days": 9, "price_repas": -1}, HOURS)
    result = await _run_flow(hass, entry, {"cap_days": 9}, HOURS | {"end_etude": "16:00:00"})
    assert result["type"] == "form" and result["errors"] == {"end_etude": "end_before_start"}
    with pytest.raises(InvalidData):  # the time selector refuses what is not a time
        await _run_flow(hass, entry, {"cap_days": 9}, HOURS | {"start_repas": "noon"})
    assert entry.options.get("cap_days") is None  # nothing was saved


async def test_changed_hours_reach_calendar_and_card(
    hass: HomeAssistant,
    ws,
    setup,
    fake: FakeMef,
) -> None:
    entry = await setup()
    await _run_flow(
        hass,
        entry,
        {"cap_days": 9},
        HOURS | {"start_accueil_matin": "06:45:00", "end_repas": "13:00:00"},
    )
    await hass.async_block_till_done()
    settings = entry.runtime_data.settings
    child = entry.runtime_data.data.children[ALICE]
    events = child_events(
        child, date(2026, 11, 5), date(2026, 11, 6), date(2026, 11, 4), settings.hours
    )
    meal = next(e for e in events if e.summary == "Cantine")
    assert (meal.end.hour, meal.end.minute) == (13, 0)
    plan = await _planning(ws, start="2026-11-04")
    assert plan["services"]["repas"]["end"] == "13:00"
    assert plan["services"]["accueil_matin"]["start"] == "06:45"


async def test_price_override_feeds_the_estimate(
    hass: HomeAssistant,
    ws,
    setup,
    fake: FakeMef,
) -> None:
    entry = await setup()
    await _run_flow(hass, entry, {"cap_days": 9, "price_accueil_soir": 7.0}, HOURS)
    await hass.async_block_till_done()
    reply = await _ask(
        ws,
        {
            "type": "mon_espace_famille/quote",
            "changes": [_change(ALICE, "accueil_soir", "2026-11-12", "book")],
        },
    )
    cost = reply["result"]["cost"]
    assert cost["amount"] == 7.0 and cost["estimate"]["custom"] is True
    assert cost["estimate"]["lines"][0]["rate"] == 7.0
