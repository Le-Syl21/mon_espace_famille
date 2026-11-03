"""The planning card's WebSocket commands, against the fake server."""

import json
from urllib.parse import parse_qsl

import pytest
from homeassistant.core import HomeAssistant

from .conftest import ALICE, BOB, FakeMef


class _Client:
    """A WebSocket client connected on first use, once the test's clock is set."""

    def __init__(self, hass, user, credential, hass_ws_client) -> None:
        self._args = (hass, user, credential, hass_ws_client)
        self._client = None

    async def _connect(self):
        hass, user, credential, hass_ws_client = self._args
        refresh = await hass.auth.async_create_refresh_token(
            user, "https://example.com/", credential=credential
        )
        return await hass_ws_client(hass, hass.auth.async_create_access_token(refresh))

    async def send_json_auto_id(self, payload):
        if self._client is None:
            self._client = await self._connect()
        return await self._client.send_json_auto_id(payload)

    async def receive_json(self):
        return await self._client.receive_json()


@pytest.fixture
def ws(hass, hass_admin_user, hass_admin_credential, hass_access_token, hass_ws_client):
    return _Client(hass, hass_admin_user, hass_admin_credential, hass_ws_client)


async def _ask(ws, payload):
    await ws.send_json_auto_id(payload)
    return await ws.receive_json()


async def _planning(ws, start="2026-11-04", **extra):
    reply = await _ask(ws, {"type": "mon_espace_famille/planning", "start": start} | extra)
    assert reply["success"], reply
    return reply["result"]


def _cart_of(body: str) -> list:
    pairs = parse_qsl(body, keep_blank_values=True)
    assert [k for k, _ in pairs][:1] == ["cart"]
    return json.loads(pairs[0][1])


async def test_current_week(hass: HomeAssistant, ws, setup, fake: FakeMef) -> None:
    await setup()
    plan = await _planning(ws, start="2026-11-04")  # a Wednesday
    assert plan["monday"] == "2026-11-02"
    assert plan["week"] == 45
    # No Wednesday: nobody has a service open (or booked) that day.
    assert [d["date"] for d in plan["days"]] == [
        "2026-11-02",
        "2026-11-03",
        "2026-11-05",
        "2026-11-06",
    ]
    assert plan["first_day"] == "2026-11-02"
    assert plan["last_day"] == "2026-11-06"
    alice = next(c for c in plan["children"] if c["id"] == ALICE)
    assert alice["services"] == ["repas", "accueil_soir", "etude"]
    meals = {d: alice["cells"][d]["repas"] for d in alice["cells"]}
    # Monday: past and attended.
    assert meals["2026-11-02"]["locked"] and meals["2026-11-02"]["reason"] == "past"
    assert meals["2026-11-02"]["booked"] and meals["2026-11-02"]["status"] == "present"
    # Thursday: booked, but the cancellation deadline (Tuesday) is behind us.
    assert meals["2026-11-05"]["booked"] and meals["2026-11-05"]["locked"]
    assert meals["2026-11-05"]["reason"] == "deadline"
    assert meals["2026-11-05"]["deadline"] == "2026-11-03"
    # Friday: booked and still cancellable until Thursday.
    assert meals["2026-11-06"] == {
        "registered": True,
        "open": True,
        "booked": True,
        "locked": False,
        "deadline": "2026-11-05",
        "reason": "",
        "status": "reserve",
    }
    evening = alice["cells"]["2026-11-06"]["accueil_soir"]
    assert evening["open"] and not evening["booked"] and not evening["locked"]
    # Thursday's evening care is still open to booking; Monday's is long gone.
    thursday = alice["cells"]["2026-11-05"]["accueil_soir"]
    assert thursday["open"] and not thursday["locked"]
    gone = alice["cells"]["2026-11-02"]["accueil_soir"]
    assert not gone["booked"] and gone["locked"] and gone["reason"] == "past"
    # The portal lists no study hall at all in this week's data: nothing to show.
    assert all(alice["cells"][d]["etude"]["reason"] == "not_offered" for d in alice["cells"])
    assert plan["services"]["etude"] == {"name": "Étude", "start": "17:00", "end": "18:30"}
    assert plan["services"]["accueil_matin"]["end"] == "08:20"
    assert plan["services"]["repas"]["end"] == "13:20"
    assert plan["services"]["accueil_soir"] == {
        "name": "Accueil du soir",
        "start": "16:30",
        "end": "18:45",
    }


async def test_other_weeks(hass: HomeAssistant, ws, setup, fake: FakeMef) -> None:
    await setup()
    # Past week the portal knows nothing of (no open day, no entry): no column.
    fake.weeks[(ALICE, "20261026")] = [
        {**s, "openDays": [], "validated": [], "attendances": []}
        for s in fake.weeks[(ALICE, "20261102")]
    ]
    fake.weeks[(BOB, "20261026")] = fake.weeks[(ALICE, "20261026")]
    past = await _planning(ws, start="2026-10-26")
    assert past["days"] == [] and past["week"] == 44
    # A week outside the polled window, fetched on demand.
    requests = len(fake.carts)
    far = await _planning(ws, start="2026-12-07")
    assert far["week"] == 50 and len(far["days"]) == 4
    assert len(fake.carts) == requests


async def test_unknown_entry_and_bad_date(hass: HomeAssistant, ws, setup) -> None:
    await setup()
    reply = await _ask(
        ws,
        {"type": "mon_espace_famille/planning", "start": "2026-11-04", "entry_id": "nope"},
    )
    assert not reply["success"] and reply["error"]["code"] == "not_found"
    reply = await _ask(ws, {"type": "mon_espace_famille/planning", "start": "soon"})
    assert not reply["success"] and reply["error"]["code"] == "invalid_format"


async def test_planning_portal_down(hass: HomeAssistant, ws, setup, fake: FakeMef):
    await setup()
    fake.unauthorized = 99
    fake.server_error = True
    fake.refresh_works = False
    fake.password = "changed"
    reply = await _ask(
        ws,
        {"type": "mon_espace_famille/planning", "start": "2026-12-14"},
    )
    assert not reply["success"] and reply["error"]["code"] in {"portal_error", "auth_failed"}


def _change(child, service, date, action):
    return {"child": child, "service": service, "date": date, "action": action}


async def test_quote_falls_back_to_counts(hass: HomeAssistant, ws, setup, fake: FakeMef) -> None:
    await setup()
    fake.rates = None  # the portal gives no rates: counts only
    reply = await _ask(
        ws,
        {
            "type": "mon_espace_famille/quote",
            "changes": [
                _change(ALICE, "accueil_soir", "2026-11-12", "book"),
                _change(ALICE, "repas", "2026-11-13", "cancel"),
                _change(BOB, "accueil_soir", "2026-11-12", "book"),
                _change(BOB, "accueil_soir", "2026-11-02", "book"),  # past
            ],
        },
    )
    result = reply["result"]
    assert result["cost"] == {
        "mode": "counts",
        "amount": None,
        "currency": "EUR",
        "post_paid": True,
        "estimate": {"available": False, "total": None, "currency": "EUR", "lines": []},
        "counts": [
            {"service": "accueil_soir", "name": "Accueil du soir", "book": 2, "cancel": 0},
            {"service": "repas", "name": "Cantine", "book": 0, "cancel": 1},
        ],
    }
    assert [i["valid"] for i in result["items"]] == [True, True, True, False]
    assert result["items"][3]["reason"] == "past"
    assert result["items"][1]["cancel_deadline"] == "2026-11-12"
    assert not result["valid"]
    # Both checks ran for each child, with the cart and the week's services.
    kinds = [k for k, _ in fake.checks]
    assert kinds == ["pricing", "calculate"] * 2
    cart = _cart_of(fake.checks[0][1])
    assert cart[0]["childId"] == ALICE and len(cart[0]["servicesReservations"]) == 1
    assert fake.carts == [] and fake.bodies == []  # nothing was booked


async def test_quote_with_amounts(hass: HomeAssistant, ws, setup, fake: FakeMef) -> None:
    await setup()
    fake.pricing = [
        {"serviceId": 7, "cart": [], "presta": [{"id": 1, "amount": 2.5}, {"id": 2, "amount": 1}]}
    ]
    fake.calculate = {
        "panierLigneErreur": {"reservations": [{"identifiantEnfant": ALICE, "date": "20261112"}]}
    }
    reply = await _ask(
        ws,
        {
            "type": "mon_espace_famille/quote",
            "changes": [_change(ALICE, "accueil_soir", "2026-11-12", "book")],
        },
    )
    result = reply["result"]
    assert result["cost"]["mode"] == "amount" and result["cost"]["amount"] == 3.5
    assert result["portal_errors"][0]["date"] == "20261112" and not result["valid"]


def _base(child, service, date, booked):
    return {"child": child, "service": service, "date": date, "booked": booked}


async def test_apply_one_cart_per_child(hass: HomeAssistant, ws, setup, fake: FakeMef) -> None:
    await setup()
    reply = await _ask(
        ws,
        {
            "type": "mon_espace_famille/apply",
            "changes": [
                _change(ALICE, "accueil_soir", "2026-11-16", "book"),
                _change(ALICE, "accueil_soir", "2026-11-12", "book"),
                _change(ALICE, "repas", "2026-11-13", "cancel"),
                _change(BOB, "repas", "2026-11-12", "book"),
            ],
            "base": [
                _base(ALICE, "accueil_soir", "2026-11-16", False),
                _base(ALICE, "accueil_soir", "2026-11-12", False),
                _base(ALICE, "repas", "2026-11-13", True),
                _base(BOB, "repas", "2026-11-12", False),
            ],
        },
    )
    assert reply["success"], reply
    result = reply["result"]
    assert result["status"] == "applied"
    assert {r["result"] for r in result["results"]} == {"applied"}
    assert fake.carts == [
        {
            "childId": ALICE,
            "servicesReservations": [
                {
                    "dates": [{"date": "20261112"}, {"date": "20261116"}],
                    "serviceReservationId": "7_7",
                    "serviceId": 7,
                }
            ],
            "cancelationReservations": [
                {
                    "dates": [{"date": "20261113"}],
                    "serviceReservationId": "1_1",
                    "serviceId": 1,
                    "reservationsIds": [5009],  # the booking of Friday 13 in the fixture
                }
            ],
        },
        {
            "childId": BOB,
            "servicesReservations": [
                {
                    "dates": [{"date": "20261112"}],
                    "serviceReservationId": "1_1",
                    "serviceId": 1,
                }
            ],
            "cancelationReservations": [],
        },
    ]
    # Every body is the proven shape: cart=<JSON list of one entry>.
    assert [len(_cart_of(b)) for b in fake.bodies] == [1, 1]
    # The planning now shows the new state.
    plan = await _planning(ws, start="2026-11-12", fresh=True)
    alice = next(c for c in plan["children"] if c["id"] == ALICE)
    assert alice["cells"]["2026-11-12"]["accueil_soir"]["booked"]
    assert not alice["cells"]["2026-11-13"]["repas"]["booked"]


async def test_apply_conflict_applies_nothing(
    hass: HomeAssistant, ws, setup, fake: FakeMef
) -> None:
    await setup()
    # The card saw the evening care of Thursday 12 unbooked; another parent booked it.
    fake.week(ALICE, "20261109")[1].setdefault("validated", []).append(
        {"date": "20261112", "dteLimiteSupp": "20261111", "id": 7777}
    )
    reply = await _ask(
        ws,
        {
            "type": "mon_espace_famille/apply",
            "changes": [
                _change(ALICE, "accueil_soir", "2026-11-12", "book"),
                _change(BOB, "accueil_soir", "2026-11-12", "book"),
            ],
            "base": [
                _base(ALICE, "accueil_soir", "2026-11-12", False),
                _base(BOB, "accueil_soir", "2026-11-12", False),
            ],
        },
    )
    result = reply["result"]
    assert result["status"] == "conflict"
    assert result["conflicts"] == [
        {
            "child": ALICE,
            "service": "accueil_soir",
            "date": "2026-11-12",
            "expected": False,
            "actual": True,
        }
    ]
    assert fake.carts == []  # Bob's change was not applied either


async def test_apply_refuses_locked_closed_and_unregistered(
    hass: HomeAssistant, ws, setup, fake: FakeMef
) -> None:
    await setup()
    reply = await _ask(
        ws,
        {
            "type": "mon_espace_famille/apply",
            "changes": [
                _change(ALICE, "repas", "2026-11-05", "cancel"),  # deadline passed
                _change(ALICE, "accueil_soir", "2026-11-03", "book"),  # past, closed day
                _change(ALICE, "repas", "2026-11-02", "cancel"),  # past
                _change(ALICE, "accueil_matin", "2026-11-12", "book"),  # not registered
                _change(ALICE, "etude", "2026-11-10", "book"),  # not offered on Tuesdays
                _change(ALICE, "repas", "2026-11-12", "cancel"),  # not booked by Alice? booked
                _change(BOB, "repas", "2026-11-13", "book"),  # booked already
            ],
            "base": [],
        },
    )
    result = reply["result"]
    assert result["status"] == "refused"
    reasons = {(r["child"], r["service"], r["date"]): r["reason"] for r in result["refused"]}
    assert reasons[(ALICE, "repas", "2026-11-05")] == "deadline"
    assert reasons[(ALICE, "accueil_soir", "2026-11-03")] == "past"
    assert reasons[(ALICE, "repas", "2026-11-02")] == "past"
    assert reasons[(ALICE, "accueil_matin", "2026-11-12")] == "not_registered"
    assert reasons[(ALICE, "etude", "2026-11-10")] == "not_offered"
    assert reasons[(BOB, "repas", "2026-11-13")] == "unchanged"
    assert fake.carts == []


async def test_apply_not_confirmed_and_error(hass: HomeAssistant, ws, setup, fake: FakeMef) -> None:
    await setup()
    changes = {
        "changes": [
            _change(ALICE, "accueil_soir", "2026-11-12", "book"),
            _change(BOB, "accueil_soir", "2026-11-12", "book"),
        ],
        "base": [
            _base(ALICE, "accueil_soir", "2026-11-12", False),
            _base(BOB, "accueil_soir", "2026-11-12", False),
        ],
        "type": "mon_espace_famille/apply",
    }
    # The portal says "queued" and drops it: bounded retries, then "not confirmed".
    fake.apply_carts = False
    result = (await _ask(ws, changes))["result"]
    assert result["status"] == "failed"
    assert {r["result"] for r in result["results"]} == {"not_confirmed"}
    # The portal refuses the cart outright.
    fake.reservations_status = 500
    result = (await _ask(ws, changes))["result"]
    assert result["status"] == "failed"
    assert {r["result"] for r in result["results"]} == {"error"}


async def test_apply_partial(hass: HomeAssistant, ws, setup, fake: FakeMef) -> None:
    await setup()
    original = fake._apply

    def only_alice(item):
        if item["childId"] == ALICE:
            original(item)

    fake._apply = only_alice
    reply = await _ask(
        ws,
        {
            "type": "mon_espace_famille/apply",
            "changes": [
                _change(ALICE, "accueil_soir", "2026-11-12", "book"),
                _change(BOB, "accueil_soir", "2026-11-12", "book"),
            ],
            "base": [],
        },
    )
    result = reply["result"]
    assert result["status"] == "partial"
    assert [r["result"] for r in result["results"]] == ["applied", "not_confirmed"]


async def test_apply_validation(hass: HomeAssistant, ws, setup, fake: FakeMef) -> None:
    await setup()
    twice = [
        _change(ALICE, "accueil_soir", "2026-11-12", "book"),
        _change(ALICE, "accueil_soir", "2026-11-12", "cancel"),
    ]
    reply = await _ask(
        ws,
        {"type": "mon_espace_famille/apply", "changes": twice, "base": []},
    )
    assert reply["error"]["code"] == "invalid_format"
    reply = await _ask(
        ws,
        {"type": "mon_espace_famille/apply", "changes": [], "base": []},
    )
    assert reply["error"]["code"] == "invalid_format"
    reply = await _ask(
        ws,
        {
            "type": "mon_espace_famille/apply",
            "changes": [_change(ALICE, "garderie", "2026-11-12", "book")],
            "base": [],
        },
    )
    assert reply["error"]["code"] == "invalid_format"


async def test_quote_estimates_the_month(hass: HomeAssistant, ws, setup, fake: FakeMef) -> None:
    await setup()
    reply = await _ask(
        ws,
        {
            "type": "mon_espace_famille/quote",
            "changes": [
                _change(ALICE, "accueil_soir", "2026-11-12", "book"),
                _change(ALICE, "accueil_soir", "2026-11-16", "book"),
                _change(ALICE, "repas", "2026-11-13", "cancel"),
            ],
        },
    )
    cost = reply["result"]["cost"]
    assert cost["mode"] == "estimate" and cost["amount"] == round(2 * 5.92 - 5.2, 2)
    lines = {(line["service"], line["month"]): line for line in cost["estimate"]["lines"]}
    evening = lines[("accueil_soir", "2026-11")]
    assert (evening["book"], evening["rate"], evening["delta"]) == (2, 5.92, 11.84)
    assert evening["before"]["days"] == 1 and evening["cap"] == 9 and evening["flat_fee"] == 55.59
    meals = lines[("repas", "2026-11")]
    assert meals["cancel"] == 1 and meals["delta"] == -5.2


async def test_study_needs_the_evening_care(hass: HomeAssistant, ws, setup, fake: FakeMef) -> None:
    await setup()
    study = "etude"
    book = {"type": "mon_espace_famille/apply"}
    # Study alone on Monday 9 (open, evening care not booked): refused.
    reply = await _ask(
        ws,
        book
        | {
            "changes": [_change(ALICE, study, "2026-11-09", "book")],
            "base": [_base(ALICE, study, "2026-11-09", False)],
        },
    )
    result = reply["result"]
    assert result["status"] == "refused"
    assert result["refused"] == [
        {"child": ALICE, "service": study, "date": "2026-11-09", "reason": "needs_evening"}
    ]
    assert fake.carts == []
    # With the evening care in the same change set: one cart, both booked.
    reply = await _ask(
        ws,
        book
        | {
            "changes": [
                _change(ALICE, study, "2026-11-09", "book"),
                _change(ALICE, "accueil_soir", "2026-11-09", "book"),
            ],
            "base": [],
        },
    )
    assert reply["result"]["status"] == "applied"
    (cart,) = fake.carts
    assert {r["serviceReservationId"] for r in cart["servicesReservations"]} == {"7_7", "8_8"}
    # Now the study stays booked: cancelling only the evening care is refused...
    reply = await _ask(
        ws, book | {"changes": [_change(ALICE, "accueil_soir", "2026-11-09", "cancel")], "base": []}
    )
    assert reply["result"]["refused"][0]["reason"] == "needs_evening"
    # ...unless the study is cancelled with it.
    reply = await _ask(
        ws,
        book
        | {
            "changes": [
                _change(ALICE, "accueil_soir", "2026-11-09", "cancel"),
                _change(ALICE, study, "2026-11-09", "cancel"),
            ],
            "base": [],
        },
    )
    assert reply["result"]["status"] == "applied"


async def test_study_is_locked_without_a_bookable_evening(
    hass: HomeAssistant, ws, setup, fake: FakeMef
) -> None:
    await setup()
    # Monday 9: the study is still open but the evening care no longer is.
    evening = fake.week(ALICE, "20261109")[1]
    evening["openDays"] = [d for d in evening["openDays"] if d["date"] != "20261109"]
    plan = await _planning(ws, start="2026-11-09", fresh=True)
    alice = next(c for c in plan["children"] if c["id"] == ALICE)
    cells = alice["cells"]["2026-11-09"]
    assert cells["accueil_soir"]["locked"]
    assert cells["etude"]["locked"] and cells["etude"]["reason"] == "needs_evening"
    # A booked study that is locked keeps its evening care locked as well.
    fake.week(ALICE, "20261109")[2]["validated"] = [
        {"date": "20261112", "dteLimiteSupp": "20261103", "id": 8001}
    ]
    fake.week(ALICE, "20261109")[1].setdefault("validated", []).append(
        {"date": "20261112", "dteLimiteSupp": "20261111", "id": 8002}
    )
    plan = await _planning(ws, start="2026-11-09", fresh=True)
    alice = next(c for c in plan["children"] if c["id"] == ALICE)
    thursday = alice["cells"]["2026-11-12"]
    assert thursday["etude"]["locked"] and thursday["accueil_soir"]["reason"] == "has_study"


async def test_study_days_come_from_the_portal_not_the_weekday(
    hass: HomeAssistant, ws, setup, fake: FakeMef
) -> None:
    await setup()
    # A commune whose study hall is on Tuesdays (and none the week after).
    for child in (ALICE, BOB):
        fake.week(child, "20261109")[2]["openDays"] = [{"date": "20261110"}]
        fake.week(child, "20261116")  # generated
        for service in fake.week(child, "20261116"):
            if service["id"] == "8_8":
                service["openDays"] = []
    plan = await _planning(ws, start="2026-11-09", fresh=True)
    alice = next(c for c in plan["children"] if c["id"] == ALICE)
    cells = alice["cells"]
    assert not cells["2026-11-10"]["etude"]["locked"] and cells["2026-11-10"]["etude"]["open"]
    assert cells["2026-11-09"]["etude"]["reason"] == "not_offered"
    assert cells["2026-11-12"]["etude"]["reason"] == "not_offered"
    # The rule follows: a Tuesday study alone is refused, with its evening care it passes.
    reply = await _ask(
        ws,
        {
            "type": "mon_espace_famille/apply",
            "changes": [_change(ALICE, "etude", "2026-11-10", "book")],
            "base": [],
        },
    )
    assert reply["result"]["refused"][0]["reason"] == "needs_evening"
    # A week with no study hall in the data at all (the start of the school year).
    plan = await _planning(ws, start="2026-11-16", fresh=True)
    alice = next(c for c in plan["children"] if c["id"] == ALICE)
    assert all(alice["cells"][d]["etude"]["reason"] == "not_offered" for d in alice["cells"])
    assert any(not alice["cells"][d]["accueil_soir"]["locked"] for d in alice["cells"])
