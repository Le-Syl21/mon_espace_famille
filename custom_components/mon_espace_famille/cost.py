"""What a set of changes costs, estimated: the portal announces nothing for a
post-paid commune, so the monthly bill is rebuilt from its per-day rates."""

from __future__ import annotations

from calendar import monthrange
from datetime import date

from .const import MONTHLY_DAYS_CAP, MONTHLY_FLAT


def month_cost(kind: str, days: int, rate: float) -> tuple[float, bool]:
    """(amount, flat fee applied) of `days` booked days of a service in a month.

    Morning and evening care cost the per-day rate up to MONTHLY_DAYS_CAP days
    and the monthly flat fee beyond; the other services are charged per day.
    """
    flat = MONTHLY_FLAT.get(kind)
    if flat is not None and days > MONTHLY_DAYS_CAP:
        return flat, True
    return round(days * rate, 2), False


def month_bounds(year: int, month: int) -> tuple[date, date]:
    return date(year, month, 1), date(year, month, monthrange(year, month)[1])


def estimate(
    counts: dict[tuple[int, str, str], int],
    changes: list[tuple[int, str, date, str]],
    rates: dict[tuple[int, str], float | None],
    names: dict[int, str],
) -> dict:
    """The monthly difference the changes make, per child, service and month.

    `counts` are the days already booked, by (child, kind, "YYYY-MM"); `changes`
    are (child, kind, day, "book"|"cancel"); `rates` the per-day rate of each
    (child, kind), None when the portal did not give it (then no estimate).
    """
    touched: dict[tuple[int, str, str], list[int]] = {}
    for child, kind, day, action in changes:
        line = touched.setdefault((child, kind, f"{day.year}-{day.month:02d}"), [0, 0])
        line[0 if action == "book" else 1] += 1
    if any(rates.get((child, kind)) is None for child, kind, _ in touched):
        return {"available": False, "total": None, "currency": "EUR", "lines": []}
    lines = []
    total = 0.0
    for (child, kind, month), (book, cancel) in sorted(touched.items(), key=lambda kv: kv[0][2]):
        rate = float(rates[(child, kind)])  # type: ignore[arg-type]
        days = counts.get((child, kind, month), 0)
        after = max(days + book - cancel, 0)
        amount_before, flat_before = month_cost(kind, days, rate)
        amount_after, flat_after = month_cost(kind, after, rate)
        delta = round(amount_after - amount_before, 2)
        total += delta
        lines.append(
            {
                "child": child,
                "child_name": names.get(child, ""),
                "service": kind,
                "month": month,
                "book": book,
                "cancel": cancel,
                "rate": rate,
                "cap": MONTHLY_DAYS_CAP,
                "flat_fee": MONTHLY_FLAT.get(kind),
                "before": {"days": days, "amount": amount_before, "flat": flat_before},
                "after": {"days": after, "amount": amount_after, "flat": flat_after},
                "delta": delta,
            }
        )
    return {"available": True, "total": round(total, 2), "currency": "EUR", "lines": lines}
