"""Parsing of the API's answers, without Home Assistant."""

from datetime import date

from custom_components.mon_espace_famille.api import encode_form
from custom_components.mon_espace_famille.model import (
    Child,
    merge_week,
    parse_children,
    service_kind,
)

from .conftest import load


def test_service_kinds() -> None:
    assert service_kind("REPAS PERMANENT") == "repas"
    assert service_kind("Restauration scolaire") == "repas"
    assert service_kind("ACCUEIL SOIR") == "accueil_soir"
    assert service_kind("Accueil du matin") == "accueil_matin"
    assert service_kind("ÉTUDE") == "etude"
    assert service_kind("Étude surveillée du soir") == "etude"
    assert service_kind("MERCREDI LOISIRS") is None


def test_children_skip_archived() -> None:
    assert parse_children(load("members.json")) == [(101, "Alice"), (102, "Bob"), (103, "Chloé")]


def test_week_keeps_its_own_seven_days() -> None:
    child = Child(id=101, first_name="Alice")
    merge_week(child, date(2026, 11, 2), load("alice_20261102.json"))
    meals = child.services["1_1"]
    assert meals.kind == "repas" and meals.service_id == 1
    # The answer also lists Monday 9: it belongs to the next week.
    assert sorted(meals.open_days) == [date(2026, 11, 5), date(2026, 11, 6)]
    assert {d: e.status for d, e in meals.days.items()} == {
        date(2026, 11, 2): "present",
        date(2026, 11, 3): "present",
        date(2026, 11, 5): "reserve",
        date(2026, 11, 6): "reserve",
    }
    booked = meals.days[date(2026, 11, 6)]
    assert booked.deadline == date(2026, 11, 5)
    assert booked.cancellable(date(2026, 11, 5)) and not booked.cancellable(date(2026, 11, 6))
    # Registered to the evening care and study hall, nothing booked.
    assert child.services["7_7"].days == {} and child.services["8_8"].kind == "etude"

    merge_week(child, date(2026, 11, 9), load("alice_20261109.json"))
    assert child.services["7_7"].days[date(2026, 11, 13)].reservation_id == 5011
    assert date(2026, 11, 16) not in child.services["1_1"].days


def test_form_like_the_web_app() -> None:
    body = encode_form({"cart": [{"childId": 1, "dates": [{"date": "20261113"}], "x": "é a"}]})
    assert body == (
        "cart=%7B%22childId%22%3A1%2C%22dates%22%3A%5B%7B%22date%22%3A%2220261113%22%7D%5D"
        "%2C%22x%22%3A%22%C3%A9%20a%22%7D"
    )
    assert encode_form({"client_id": "a-b", "refresh_token": "x/y+z"}) == (
        "client_id=a-b&refresh_token=x%2Fy%2Bz"
    )
