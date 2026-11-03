"""Shared fixtures: a fake Mon Espace Famille server behind aioclient_mock."""

from __future__ import annotations

import copy
import json
import re
from datetime import date, datetime, timedelta
from pathlib import Path
from urllib.parse import parse_qsl
from zoneinfo import ZoneInfo

import pytest
from homeassistant.core import HomeAssistant
from pytest_homeassistant_custom_component.common import MockConfigEntry
from pytest_homeassistant_custom_component.test_util.aiohttp import (
    AiohttpClientMocker,
    AiohttpClientMockResponse,
)

from custom_components.mon_espace_famille import services, websocket
from custom_components.mon_espace_famille.const import API_BASE, DOMAIN

FIXTURES = Path(__file__).parent / "fixtures"
PARIS = ZoneInfo("Europe/Paris")
EMAIL = "parent@example.com"
PASSWORD = "secret"
# Wednesday: no school, and the week's first days are already past.
NOW = datetime(2026, 11, 4, 10, 0, tzinfo=PARIS)

ALICE, BOB, CHLOE = 101, 102, 103

# Keys of a service that do not depend on the week.
_SERVICE_KEYS = (
    "id",
    "paymentMode",
    "label",
    "labelService",
    "idService",
    "weekDaysOpen",
    "amontCredit",
    "registrationPending",
    "hidden",
)


def load(name: str):
    """A recorded answer of the API, anonymised (names, ids and commune changed)."""
    return json.loads((FIXTURES / name).read_text(encoding="utf-8"))


def _api(day: date) -> str:
    return day.strftime("%Y%m%d")


class FakeMef:
    """Answers like the server, and applies the carts it receives."""

    def __init__(self) -> None:
        self.password = PASSWORD
        self.members = load("members.json")
        self.weeks: dict[tuple[int, str], list[dict]] = {}
        for child, name in ((ALICE, "alice"), (BOB, "bob")):
            for monday in ("20261102", "20261109"):
                self.weeks[(child, monday)] = load(f"{name}_{monday}.json")
        self.apply_carts = True
        self.unauthorized = 0  # answer 401 to that many next calls
        self.refresh_works = True
        self.server_error = False
        self.reservations_status = 200
        self.pricing: list = []  # post-paid: the portal announces nothing
        self.calculate: object = ""
        self.rates: dict | None = {1: 5.2, 6: 4.28, 7: 5.92, 8: 0, 3: 1.99}
        self.checks: list[tuple[str, str]] = []  # (path, body) of the read-only checks
        self.carts: list[dict] = []
        self.bodies: list[str] = []
        self._next_id = 9001
        self._tokens = 0

    def _resp(self, method, url, status=200, json_body=None):
        return AiohttpClientMockResponse(method, url, status=status, json=json_body)

    def _tokens_body(self):
        self._tokens += 1
        return {
            "access_token": f"access-{self._tokens}",
            "refresh_token": f"refresh-{self._tokens}",
            "expires_in": 1800,
            "token_type": "Bearer",
        }

    async def _login(self, method, url, data):
        if self.server_error:
            return self._resp(method, url, 503)
        if data.get("email") != EMAIL or data.get("password") != self.password:
            return self._resp(method, url, 400, {"error": "invalid_grant"})
        return self._resp(method, url, json_body=self._tokens_body())

    async def _refresh(self, method, url, data):
        if not self.refresh_works:
            return self._resp(method, url, 400, {"error": "invalid_grant"})
        return self._resp(method, url, json_body=self._tokens_body())

    def _guard(self, method, url):
        if self.unauthorized:
            self.unauthorized -= 1
            return self._resp(method, url, 401, {"message": "Unauthorized"})
        return None

    async def _members(self, method, url, data):
        return self._guard(method, url) or self._resp(method, url, json_body=self.members)

    def week(self, child: int, monday: str) -> list[dict]:
        """The stored week, or an empty one: open Monday, Tuesday, Thursday, Friday."""
        if (child, monday) in self.weeks:
            return self.weeks[(child, monday)]
        if child == CHLOE:
            return []
        first = datetime.strptime(monday, "%Y%m%d").date()
        days = [first + timedelta(days=n) for n in (0, 1, 3, 4, 7)]
        template = self.weeks[(child, "20261109")]
        week = [
            {k: s[k] for k in _SERVICE_KEYS if k in s}
            | {"openDays": [{"date": _api(d)} for d in days]}
            for s in template
        ]
        self.weeks[(child, monday)] = week
        return week

    async def _week(self, method, url, data):
        if denied := self._guard(method, url):
            return denied
        child = int(re.search(r"/children/(\d+)/", url.path).group(1))
        return self._resp(
            method, url, json_body=copy.deepcopy(self.week(child, url.query["start"]))
        )

    async def _reservations(self, method, url, data):
        if self.reservations_status != 200:
            return self._resp(method, url, self.reservations_status)
        self.bodies.append(data)
        pairs = parse_qsl(data, keep_blank_values=True)
        assert [k for k, _ in pairs] == ["cart"]
        entries = json.loads(pairs[0][1])
        assert isinstance(entries, list) and len(entries) == 1
        item = entries[0]
        self.carts.append(item)
        if self.apply_carts:
            self._apply(item)
        return self._resp(method, url, json_body={"status": "queued"})

    async def _products(self, method, url, data):
        if self.rates is None:
            return self._resp(method, url, 404)
        products = [
            {"id": pid, "name": f"P{pid}", "services": [{"name": "X", "rate": rate}]}
            for pid, rate in self.rates.items()
        ]
        return self._resp(method, url, json_body={"products": products})

    async def _check(self, method, url, data):
        self.checks.append((url.path.rsplit("/", 1)[1], data))
        body = self.pricing if url.path.endswith("pricing") else self.calculate
        return self._resp(method, url, json_body=body)

    def _service(self, child: int, sid: str, day: date) -> dict:
        monday = day - timedelta(days=day.weekday())
        return next(s for s in self.week(child, _api(monday)) if s["id"] == sid)

    def _apply(self, item: dict) -> None:
        child = item["childId"]
        for res in item["servicesReservations"]:
            for d in res["dates"]:
                day = datetime.strptime(d["date"], "%Y%m%d").date()
                service = self._service(child, res["serviceReservationId"], day)
                service.setdefault("validated", []).append(
                    {
                        "date": d["date"],
                        "dteLimiteSupp": _api(day - timedelta(days=1)),
                        "id": self._next_id,
                    }
                )
                self._next_id += 1
        for res in item["cancelationReservations"]:
            ids = set(res["reservationsIds"])
            for d in res["dates"]:
                day = datetime.strptime(d["date"], "%Y%m%d").date()
                service = self._service(child, res["serviceReservationId"], day)
                service["validated"] = [v for v in service["validated"] if v["id"] not in ids]

    def register(self, mock: AiohttpClientMocker) -> None:
        mock.post(API_BASE + "login", side_effect=self._login)
        mock.post(API_BASE + "auth/token", side_effect=self._refresh)
        mock.get(API_BASE + "home/members", side_effect=self._members)
        mock.get(API_BASE + "me/entity/current", json={"type": "town", "name": "Exempleville"})
        mock.get(re.compile(r"/family/children/\d+/servicesreservations"), side_effect=self._week)
        mock.get(re.compile(r"/family/children/\d+/products/1"), side_effect=self._products)
        mock.post(API_BASE + "family/children/reservations/pricing", side_effect=self._check)
        mock.post(API_BASE + "family/children/reservations/calculate", side_effect=self._check)
        mock.post(API_BASE + "family/children/reservations", side_effect=self._reservations)


@pytest.fixture(autouse=True)
def auto_enable_custom_integrations(enable_custom_integrations):
    yield


@pytest.fixture(autouse=True)
def no_verify_delay(monkeypatch):
    monkeypatch.setattr(services, "VERIFY_DELAY", 0)
    monkeypatch.setattr(websocket, "VERIFY_DELAY", 0)


@pytest.fixture
def fake(aioclient_mock: AiohttpClientMocker) -> FakeMef:
    server = FakeMef()
    server.register(aioclient_mock)
    return server


@pytest.fixture
async def setup(hass: HomeAssistant, fake: FakeMef, freezer):
    """Set the account up on NOW (or the given time), with the given options."""

    async def _setup(options: dict | None = None, now: datetime = NOW) -> MockConfigEntry:
        freezer.move_to(now)
        await hass.config.async_set_time_zone("Europe/Paris")
        entry = MockConfigEntry(
            domain=DOMAIN,
            title=EMAIL,
            unique_id=EMAIL,
            data={"email": EMAIL, "password": PASSWORD},
            options=options or {},
        )
        entry.add_to_hass(hass)
        assert await hass.config_entries.async_setup(entry.entry_id)
        await hass.async_block_till_done()
        return entry

    return _setup
