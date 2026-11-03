"""The monthly cost estimate of Orgerus: per day up to 9 days, then a flat fee."""

from datetime import date

import pytest

from custom_components.mon_espace_famille.cost import estimate, month_cost

RATES = {(1, "accueil_soir"): 5.92, (1, "accueil_matin"): 4.28, (2, "accueil_soir"): 5.92}
NAMES = {1: "Alice", 2: "Bob"}


@pytest.mark.parametrize(
    ("kind", "days", "amount", "flat"),
    [
        ("accueil_soir", 0, 0.0, False),
        ("accueil_soir", 9, 53.28, False),
        ("accueil_soir", 10, 55.59, True),
        ("accueil_soir", 20, 55.59, True),
        ("accueil_matin", 9, 38.52, False),
        ("accueil_matin", 10, 42.53, True),
        ("repas", 20, 104.0, False),  # a meal has no flat fee
    ],
)
def test_month_cost(kind, days, amount, flat) -> None:
    assert month_cost(kind, days, 5.2 if kind == "repas" else RATES[(1, kind)]) == (amount, flat)


def _day(d: int) -> date:
    return date(2026, 11, d)


def test_three_evenings_cost_per_day() -> None:
    changes = [(1, "accueil_soir", _day(d), "book") for d in (5, 6, 9)]
    result = estimate({}, changes, RATES, NAMES)
    assert result["available"] and result["total"] == 17.76
    (line,) = result["lines"]
    assert (line["book"], line["cancel"], line["delta"]) == (3, 0, 17.76)
    assert line["after"] == {"days": 3, "amount": 17.76, "flat": False}


def test_crossing_nine_days_switches_to_the_flat_fee() -> None:
    counts = {(1, "accueil_soir", "2026-11"): 9}
    result = estimate(counts, [(1, "accueil_soir", _day(12), "book")], RATES, NAMES)
    (line,) = result["lines"]
    # 9 days cost 53.28; the 10th makes it 55.59: only 2.31 more.
    assert line["after"]["flat"] and not line["before"]["flat"]
    assert line["delta"] == 2.31 and line["flat_fee"] == 55.59


def test_cancelling_lowers_the_bill_and_can_leave_the_flat_fee() -> None:
    counts = {(1, "accueil_soir", "2026-11"): 10}
    result = estimate(counts, [(1, "accueil_soir", _day(12), "cancel")], RATES, NAMES)
    (line,) = result["lines"]
    assert line["before"]["flat"] and not line["after"]["flat"]
    assert line["delta"] == round(53.28 - 55.59, 2) == -2.31
    # Below the cap a cancellation saves a day's rate.
    result = estimate(
        {(1, "accueil_soir", "2026-11"): 4}, [(1, "accueil_soir", _day(12), "cancel")], RATES, NAMES
    )
    assert result["total"] == -5.92


def test_morning_and_evening_are_counted_apart() -> None:
    counts = {(1, "accueil_soir", "2026-11"): 9, (1, "accueil_matin", "2026-11"): 2}
    changes = [(1, "accueil_matin", _day(12), "book"), (1, "accueil_soir", _day(12), "book")]
    result = estimate(counts, changes, RATES, NAMES)
    by_kind = {line["service"]: line for line in result["lines"]}
    assert (
        by_kind["accueil_matin"]["delta"] == 4.28 and not by_kind["accueil_matin"]["after"]["flat"]
    )
    assert by_kind["accueil_soir"]["after"]["flat"]


def test_children_and_months_are_not_mixed() -> None:
    counts = {(1, "accueil_soir", "2026-11"): 9, (2, "accueil_soir", "2026-11"): 0}
    changes = [
        (1, "accueil_soir", _day(12), "book"),
        (2, "accueil_soir", _day(12), "book"),
        (2, "accueil_soir", date(2026, 12, 3), "book"),
    ]
    result = estimate(counts, changes, RATES, NAMES)
    lines = {(line["child"], line["month"]): line for line in result["lines"]}
    assert lines[(1, "2026-11")]["delta"] == 2.31
    assert lines[(2, "2026-11")]["delta"] == 5.92
    assert lines[(2, "2026-12")]["delta"] == 5.92
    assert result["total"] == 14.15


def test_missing_rate_means_no_estimate() -> None:
    result = estimate({}, [(1, "repas", _day(5), "book")], RATES, NAMES)
    assert result == {"available": False, "total": None, "currency": "EUR", "lines": []}
