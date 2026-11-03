"""What a household can change: prices, the monthly cap and the hours.

The defaults are Orgerus 2026-27 (const.py). The per-day rates still come from
the portal unless overridden here.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from datetime import time
from typing import Any

from .const import (
    KIND_ACCUEIL_MATIN,
    KIND_ACCUEIL_SOIR,
    KIND_HOURS,
    KINDS,
    MONTHLY_DAYS_CAP,
    MONTHLY_FLAT,
)

CONF_CAP_DAYS = "cap_days"
FLAT_KINDS = (KIND_ACCUEIL_MATIN, KIND_ACCUEIL_SOIR)


def flat_key(kind: str) -> str:
    return f"flat_{kind}"


def price_key(kind: str) -> str:
    return f"price_{kind}"


def start_key(kind: str) -> str:
    return f"start_{kind}"


def end_key(kind: str) -> str:
    return f"end_{kind}"


def parse_time(value: Any) -> time | None:
    """ "HH:MM" or "HH:MM:SS" to a time, None if it is neither."""
    if isinstance(value, time):
        return value.replace(second=0, microsecond=0)
    if not isinstance(value, str):
        return None
    parts = value.strip().split(":")
    if len(parts) not in (2, 3) or not all(p.isdigit() for p in parts):
        return None
    try:
        return time(int(parts[0]), int(parts[1]))
    except ValueError:
        return None


def _money(value: Any) -> float | None:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if number >= 0 else None


@dataclass(frozen=True, slots=True)
class Settings:
    cap_days: int = MONTHLY_DAYS_CAP  # 0: no monthly flat fee ever
    flat: dict[str, float] = field(default_factory=lambda: dict(MONTHLY_FLAT))
    prices: dict[str, float | None] = field(default_factory=dict)  # None: the portal's rate
    hours: dict[str, tuple[time, time]] = field(default_factory=lambda: dict(KIND_HOURS))

    @classmethod
    def from_options(cls, options: Mapping[str, Any]) -> Settings:
        """The settings of an entry's options; anything missing or invalid is the default."""
        cap = options.get(CONF_CAP_DAYS)
        cap_days = int(cap) if isinstance(cap, (int, float)) and cap >= 0 else MONTHLY_DAYS_CAP
        flat = dict(MONTHLY_FLAT)
        for kind in FLAT_KINDS:
            if flat_key(kind) in options:
                value = _money(options[flat_key(kind)])
                if value:  # 0 or blank: no flat fee
                    flat[kind] = value
                else:
                    flat.pop(kind, None)
        prices = {}
        for kind in KINDS:
            value = _money(options.get(price_key(kind)))
            prices[kind] = value
        hours = dict(KIND_HOURS)
        for kind in KINDS:
            start = parse_time(options.get(start_key(kind)))
            end = parse_time(options.get(end_key(kind)))
            if start and end and end > start:
                hours[kind] = (start, end)
        return cls(cap_days, flat, prices, hours)

    def flat_applies(self, kind: str, days: int) -> float | None:
        """The monthly flat fee when `days` days exceed the cap, else None."""
        fee = self.flat.get(kind)
        if fee and self.cap_days and days > self.cap_days:
            return fee
        return None

    @property
    def customised(self) -> bool:
        """Whether any price or fee differs from the Orgerus 2026-27 defaults."""
        return (
            any(v is not None for v in self.prices.values())
            or self.cap_days != MONTHLY_DAYS_CAP
            or self.flat != MONTHLY_FLAT
        )

    @property
    def school_end(self) -> time:
        """Classes end when the evening care starts."""
        return self.hours[KIND_ACCUEIL_SOIR][0]

    @property
    def evening_end(self) -> time:
        return self.hours[KIND_ACCUEIL_SOIR][1]

    @property
    def morning_start(self) -> time:
        return self.hours[KIND_ACCUEIL_MATIN][0]
