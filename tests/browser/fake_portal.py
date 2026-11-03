"""A stand-in for the Mon Espace Famille portal, for the browser test.

Serves the anonymised fixtures of ../fixtures over HTTP, shifted so that the
fixtures' first week is the current week, and applies the carts it receives.
Developer tooling only: Home Assistant is pointed at it with MEF_API_BASE.

    python fake_portal.py 8099
"""

from __future__ import annotations

import copy
import json
import sys
from datetime import date, datetime, timedelta
from pathlib import Path
from urllib.parse import parse_qsl

from aiohttp import web

FIXTURES = Path(__file__).resolve().parent.parent / "fixtures"
FIXTURE_MONDAY = date(2026, 11, 2)
EMAIL, PASSWORD = "parent@example.com", "secret"
ALICE, BOB = 101, 102
DATE_KEYS = ("date", "dteLimiteSupp")


def _d(text: str) -> date:
    return datetime.strptime(text, "%Y%m%d").date()


def _s(day: date) -> str:
    return day.strftime("%Y%m%d")


class Portal:
    def __init__(self) -> None:
        today = date.today()
        self.delta = timedelta(
            days=((today - timedelta(days=today.weekday())) - FIXTURE_MONDAY).days
        )
        self.reset()

    def reset(self) -> None:
        self.weeks: dict[tuple[int, str], list[dict]] = {}
        for child, name in ((ALICE, "alice"), (BOB, "bob")):
            for monday in ("20261102", "20261109"):
                self.weeks[(child, monday)] = json.loads(
                    (FIXTURES / f"{name}_{monday}.json").read_text()
                )
        self.carts: list[dict] = []
        self.apply = True
        self.next_id = 9001

    # Fixture dates are the "stored" ones; the outside world sees them shifted.
    def out(self, value):
        if isinstance(value, dict):
            return {
                k: _s(_d(v) + self.delta) if k in DATE_KEYS and isinstance(v, str) else self.out(v)
                for k, v in value.items()
            }
        if isinstance(value, list):
            return [self.out(v) for v in value]
        return value

    def week(self, child: int, monday: str) -> list[dict]:
        if child not in (ALICE, BOB):  # a child with no registration
            return []
        if (child, monday) in self.weeks:
            return self.weeks[(child, monday)]
        first = _d(monday)
        template = self.weeks[(child, "20261109")]
        if first < FIXTURE_MONDAY:  # the past: nothing on offer, nothing booked
            week = [
                {k: v for k, v in s.items() if k in ("id", "paymentMode", "label", "idService")}
                | {"openDays": []}
                for s in template
            ]
        else:
            days = [first + timedelta(days=n) for n in (0, 1, 3, 4, 7)]
            week = [
                {
                    k: s[k]
                    for k in (
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
                    if k in s
                }
                | {"openDays": [{"date": _s(d)} for d in days]}
                for s in template
            ]
        self.weeks[(child, monday)] = week
        return week

    def service(self, child: int, sid: str, day: date) -> dict:
        monday = day - timedelta(days=day.weekday())
        return next(s for s in self.week(child, _s(monday)) if s["id"] == sid)

    def book(self, child: int, sid: str, day: date) -> None:
        service = self.service(child, sid, day)
        service.setdefault("validated", []).append(
            {"date": _s(day), "dteLimiteSupp": _s(day - timedelta(days=1)), "id": self.next_id}
        )
        self.next_id += 1

    def apply_cart(self, item: dict) -> None:
        child = item["childId"]
        for res in item["servicesReservations"]:
            for d in res["dates"]:
                self.book(child, res["serviceReservationId"], _d(d["date"]) - self.delta)
        for res in item["cancelationReservations"]:
            ids = set(res["reservationsIds"])
            for d in res["dates"]:
                service = self.service(
                    child, res["serviceReservationId"], _d(d["date"]) - self.delta
                )
                service["validated"] = [
                    v for v in service.get("validated", []) if v["id"] not in ids
                ]


def make_app() -> web.Application:
    portal = Portal()
    routes = web.RouteTableDef()

    def tokens() -> web.Response:
        return web.json_response(
            {"access_token": "a", "refresh_token": "r", "expires_in": 1800, "token_type": "Bearer"}
        )

    @routes.post("/api/v2/login")
    async def login(request):
        body = await request.json()
        if body.get("email") != EMAIL or body.get("password") != PASSWORD:
            return web.json_response({"error": "invalid_grant"}, status=400)
        return tokens()

    @routes.post("/api/v2/auth/token")
    async def refresh(request):
        return tokens()

    @routes.get("/api/v2/home/members")
    async def members(request):
        return web.json_response(json.loads((FIXTURES / "members.json").read_text()))

    @routes.get("/api/v2/me/entity/current")
    async def entity(request):
        return web.json_response({"type": "town", "name": "Exempleville"})

    @routes.get(r"/api/v2/family/children/{child:\d+}/servicesreservations")
    async def week(request):
        monday = _s(_d(request.query["start"]) - portal.delta)
        data = portal.week(int(request.match_info["child"]), monday)
        return web.json_response(portal.out(copy.deepcopy(data)))

    @routes.post("/api/v2/family/children/reservations")
    async def reservations(request):
        body = await request.text()
        pairs = parse_qsl(body, keep_blank_values=True)
        assert [k for k, _ in pairs] == ["cart"], pairs
        entries = json.loads(pairs[0][1])
        assert isinstance(entries, list) and len(entries) == 1
        portal.carts.append(entries[0])
        if portal.apply:
            portal.apply_cart(entries[0])
        return web.json_response({"status": "queued"})

    @routes.post("/api/v2/family/children/reservations/pricing")
    async def pricing(request):
        return web.json_response([])

    @routes.post("/api/v2/family/children/reservations/calculate")
    async def calculate(request):
        return web.json_response("")

    @routes.get(r"/api/v2/family/children/{child:\d+}/products/{pid:\d+}")
    async def products(request):
        rates = {1: 5.2, 6: 4.28, 7: 5.92, 8: 0, 3: 1.99}
        return web.json_response(
            {"products": [{"id": k, "services": [{"rate": v}]} for k, v in rates.items()]}
        )

    # Test control.
    @routes.get("/__admin/state")
    async def state(request):
        return web.json_response({"carts": portal.carts, "delta_days": portal.delta.days})

    @routes.post("/__admin/reset")
    async def reset(request):
        portal.reset()
        return web.json_response({})

    @routes.post("/__admin/book")
    async def other_parent(request):
        body = await request.json()  # {child, sid, date: YYYYMMDD as shown to clients}
        portal.book(body["child"], body["sid"], _d(body["date"]) - portal.delta)
        return web.json_response({})

    @routes.post("/__admin/open")
    async def set_open(request):
        body = await request.json()  # {sid, date, open, children?}: change a service's open days
        day = _d(body["date"]) - portal.delta
        for child in body.get("children", [ALICE, BOB]):
            service = portal.service(child, body["sid"], day)
            days = [d for d in service["openDays"] if d["date"] != _s(day)]
            if body["open"]:
                days.append({"date": _s(day)})
            service["openDays"] = days
        return web.json_response({})

    @routes.post("/__admin/apply")
    async def apply_mode(request):
        portal.apply = bool((await request.json())["apply"])
        return web.json_response({})

    app = web.Application()
    app.add_routes(routes)
    return app


if __name__ == "__main__":
    web.run_app(make_app(), host="0.0.0.0", port=int(sys.argv[1]) if len(sys.argv) > 1 else 8099)
