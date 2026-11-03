"""Drive the planning card in a real browser against Home Assistant.

Developer tooling (see run.sh), not part of the pytest suite: Home Assistant
runs in a container pointed at fake_portal.py, and Chromium (Playwright)
clicks through the card. Asserts the carts the fake portal receives.
"""

from __future__ import annotations

import json
import os
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import date, timedelta
from pathlib import Path

from playwright.sync_api import Page, expect, sync_playwright

HA = os.environ.get("HA_URL", "http://mef-ha:8123")
PORTAL = os.environ.get("PORTAL_URL", "http://mef-portal:8099")
OUT = Path(os.environ.get("OUT", "/out"))
CLIENT_ID = HA + "/"
ALICE, BOB = 101, 102
SHOTS = {"390": (390, 844), "1280": (1280, 900)}


def call(url, data=None, token=None, form=False, method=None):
    headers = {}
    body = None
    if data is not None:
        if form:
            body = urllib.parse.urlencode(data).encode()
            headers["Content-Type"] = "application/x-www-form-urlencoded"
        else:
            body = json.dumps(data).encode()
            headers["Content-Type"] = "application/json"
    if token:
        headers["Authorization"] = f"Bearer {token}"
    req = urllib.request.Request(url, data=body, headers=headers, method=method)
    with urllib.request.urlopen(req, timeout=60) as resp:
        raw = resp.read()
        return json.loads(raw) if raw else None


def wait_for(url, seconds=240):
    end = time.time() + seconds
    while time.time() < end:
        try:
            urllib.request.urlopen(url, timeout=5)
            return
        except urllib.error.HTTPError:
            return
        except Exception:  # noqa: BLE001 - any failure just means "not up yet"
            time.sleep(3)
    raise SystemExit(f"{url} did not come up")


def onboard() -> dict:
    """Create the user, finish onboarding, add the integration; return the tokens."""
    wait_for(HA + "/api/onboarding")
    steps = call(HA + "/api/onboarding")
    done = {s["step"] for s in steps if s["done"]}
    if "user" not in done:
        code = call(
            HA + "/api/onboarding/users",
            {
                "client_id": CLIENT_ID,
                "name": "Test",
                "username": "test",
                "password": "test-pass-1",
                "language": "fr",
            },
        )["auth_code"]
        tokens = call(
            HA + "/auth/token",
            {"grant_type": "authorization_code", "code": code, "client_id": CLIENT_ID},
            form=True,
        )
        token = tokens["access_token"]
        for step, body in (
            ("core_config", {}),
            ("analytics", {}),
            (
                "integration",
                {"client_id": CLIENT_ID, "redirect_uri": CLIENT_ID + "?auth_callback=1"},
            ),
        ):
            try:
                call(f"{HA}/api/onboarding/{step}", body, token=token)
            except urllib.error.HTTPError as err:
                print("onboarding", step, err.code)
        flow = call(
            HA + "/api/config/config_entries/flow",
            {"handler": "mon_espace_famille", "show_advanced_options": False},
            token=token,
        )
        result = call(
            f"{HA}/api/config/config_entries/flow/{flow['flow_id']}",
            {"email": "parent@example.com", "password": "secret"},
            token=token,
        )
        assert result["type"] == "create_entry", result
        tokens["expires"] = int((time.time() + 1700) * 1000)
        (OUT / "tokens.json").write_text(json.dumps(tokens))
    return json.loads((OUT / "tokens.json").read_text())


def new_context(browser, tokens, size, dark):
    ctx = browser.new_context(
        viewport={"width": size[0], "height": size[1]},
        color_scheme="dark" if dark else "light",
        locale="fr-FR",
        timezone_id="Europe/Paris",
        device_scale_factor=2 if size[0] < 600 else 1,
        has_touch=size[0] < 600,
    )
    hass_tokens = {
        "access_token": tokens["access_token"],
        "token_type": "Bearer",
        "expires_in": 1800,
        "hassUrl": HA,
        "clientId": CLIENT_ID,
        "expires": tokens["expires"],
        "refresh_token": tokens["refresh_token"],
    }
    tokens_js = json.dumps(json.dumps(hass_tokens))
    ctx.add_init_script(
        f"localStorage.setItem('hassTokens', {tokens_js}); "
        "localStorage.setItem('selectedLanguage', '\"fr\"');"
    )
    return ctx


CONSOLE: list[str] = []


def card(page: Page):
    return page.locator("mon-espace-famille-planning-card")


def pill(page: Page, child: int, service: str, day: date):
    return card(page).locator(
        f'.pill[data-child="{child}"][data-service="{service}"][data-date="{day.isoformat()}"]'
    )


def open_view(page: Page, view: str):
    page.goto(f"{HA}/lovelace/{view}")
    try:
        card(page).locator(".table").wait_for(timeout=45000)
    except Exception:
        OUT.joinpath("shots").mkdir(exist_ok=True)
        page.screenshot(path=str(OUT / "shots" / "debug.png"))
        errors = page.locator("hui-error-card").all_inner_texts()
        print("URL", page.url, "console:", CONSOLE[-8:], "error cards:", errors)
        raise
    page.wait_for_timeout(400)


def shot(page: Page, name: str):
    OUT.joinpath("shots").mkdir(exist_ok=True)
    page.screenshot(path=str(OUT / "shots" / f"{name}.png"))


def page_overflow(page: Page) -> int:
    return page.evaluate(
        "() => { const c = document.querySelector('home-assistant')"
        ".shadowRoot; return Math.max(document.documentElement.scrollWidth - window.innerWidth, 0); }"
    )


def admin(path, data=None):
    return call(
        PORTAL + path,
        data if data is not None else {},
        method="POST" if data is not None or path.endswith("reset") else "GET",
    )


def ws_call(page: Page, message: dict):
    return page.evaluate(
        "message => document.querySelector('home-assistant').hass.callWS(message)", message
    )


def delayed_context(browser, tokens, seconds: float):
    """A phone-sized context where the card's JavaScript arrives late (slow network)."""
    ctx = new_context(browser, tokens, SHOTS["390"], False)
    page = ctx.new_page()

    def slow(route):
        page.wait_for_timeout(int(seconds * 1000))
        route.continue_()

    page.route("**/mon-espace-famille-planning-card.js*", slow)
    return ctx, page


def race_check(browser, tokens, failures: list[str]) -> None:
    """The card must render on the first paint even when its file is slow.

    As an extra module only, the dashboard can render before the card is
    defined and show "Custom element doesn't exist"; as a Lovelace resource
    (created by the integration) the dashboard waits for it.
    """
    ctx = new_context(browser, tokens, SHOTS["390"], False)
    page = ctx.new_page()
    open_view(page, "planning")
    found = [
        r
        for r in ws_call(page, {"type": "lovelace/resources"})
        if r["url"].split("?")[0].endswith("mon-espace-famille-planning-card.js")
    ]
    print("resources created by the integration:", [r["url"] for r in found])
    if len(found) != 1 or found[0]["type"] != "module":
        failures.append(f"expected one module resource, got {found}")
        ctx.close()
        return
    resource = found[0]
    ctx.close()
    # 1. Without the resource (extra module alone) and a slow file.
    ws_ctx = new_context(browser, tokens, SHOTS["390"], False)
    admin_page = ws_ctx.new_page()
    open_view(admin_page, "planning")
    ws_call(admin_page, {"type": "lovelace/resources/delete", "resource_id": resource["id"]})
    ws_ctx.close()
    ctx, page = delayed_context(browser, tokens, 5)
    page.goto(f"{HA}/lovelace/planning")
    try:
        page.wait_for_selector("hui-error-card", timeout=4500)
        print("race reproduced with the extra module alone: error card shown")
        shot(page, "race-extra-module-only")
    except Exception:  # noqa: BLE001
        print("race NOT reproduced with the extra module alone")
        failures.append("the slow-network race was not reproduced without the resource")
    page.unroute_all(behavior="wait")
    ctx.close()
    # 2. With the resource again, the same slow file: first paint is the card.
    ws_ctx = new_context(browser, tokens, SHOTS["390"], False)
    admin_page = ws_ctx.new_page()
    open_view(admin_page, "planning")
    ws_call(
        admin_page,
        {"type": "lovelace/resources/create", "res_type": "module", "url": resource["url"]},
    )
    ws_ctx.close()
    ctx, page = delayed_context(browser, tokens, 5)
    page.goto(f"{HA}/lovelace/planning")
    card(page).locator(".table").wait_for(timeout=60000)
    errors = page.locator("hui-error-card").count()
    print("with the resource and a slow file: card rendered, error cards:", errors)
    if errors:
        failures.append("an error card showed although the card is a resource")
    shot(page, "race-resource")
    page.unroute_all(behavior="wait")
    ctx.close()


def swipe(page: Page, cdp, x0: float, y0: float, x1: float, y1: float, steps: int = 8) -> None:
    """A finger drag, with real touch events (Chromium DevTools protocol)."""

    def send(kind: str, x: float, y: float) -> None:
        points = [] if kind == "touchEnd" else [{"x": x, "y": y}]
        cdp.send("Input.dispatchTouchEvent", {"type": kind, "touchPoints": points})

    send("touchStart", x0, y0)
    for i in range(1, steps + 1):
        send("touchMove", x0 + (x1 - x0) * i / steps, y0 + (y1 - y0) * i / steps)
        page.wait_for_timeout(15)
    send("touchEnd", x1, y1)
    page.wait_for_timeout(500)


def swipe_check(browser, tokens, failures: list[str]) -> None:
    """Swiping the card changes week; vertical drags, table scrolls and the dashboard are left alone."""
    admin("/__admin/reset", {})
    nxt = date.today() - timedelta(days=date.today().weekday()) + timedelta(days=7)
    ctx = new_context(browser, tokens, SHOTS["390"], False)
    page = ctx.new_page()
    cdp = ctx.new_cdp_session(page)
    open_view(page, "planning")
    c = card(page)
    label = c.locator(".head .label")
    url = page.url

    def box():
        b = c.locator(".table").bounding_box()
        return b["x"] + b["width"] / 2, b["y"] + 40

    def week() -> str:
        return label.inner_text().split("\n")[0]

    first = week()
    x, y = box()
    swipe(page, cdp, x + 100, y, x - 100, y)  # left: next week
    if week() == first:
        failures.append("swipe left did not change the week")
    second = week()
    shot(page, "swipe-next")
    swipe(page, cdp, x - 100, y, x + 100, y)  # right: back
    if week() != first:
        failures.append("swipe right did not come back")
    swipe(page, cdp, x, y, x, y + 120)  # vertical: nothing
    swipe(page, cdp, x + 20, y, x - 20, y)  # too short: nothing
    if week() != first:
        failures.append("a vertical or short drag changed the week")
    if page.url != url:
        failures.append(f"the dashboard changed view: {url} -> {page.url}")
    print("swipe: weeks", first, "->", second, "->", week(), "view unchanged:", page.url == url)
    # Keyboard: arrows move the week when the card has focus.
    c.locator(".wrap").focus()
    page.keyboard.press("ArrowRight")
    page.wait_for_timeout(600)
    if week() == first:
        failures.append("ArrowRight did not change the week")
    page.keyboard.press("ArrowLeft")
    page.wait_for_timeout(600)
    # A draft survives swipes.
    pill_el = c.locator(".pill:not([aria-disabled])").first
    pill_el.click()
    swipe(page, cdp, x + 100, y, x - 100, y)
    swipe(page, cdp, x - 100, y, x + 100, y)
    if "1 modification" not in c.locator(".foot .count").inner_text():
        failures.append("the draft did not survive the swipes")
    ctx.close()

    # A 5-day week overflows the table on a phone: it scrolls first, then swipes change week.
    for sid in ("1_1", "7_7", "8_8"):
        admin(
            "/__admin/open",
            {"sid": sid, "date": (nxt + timedelta(days=2)).strftime("%Y%m%d"), "open": True},
        )
    ctx = new_context(browser, tokens, SHOTS["390"], False)
    page = ctx.new_page()
    cdp = ctx.new_cdp_session(page)
    open_view(page, "planning")
    c = card(page)
    label = c.locator(".head .label")
    c.locator('[data-act="next"]').click()
    try:
        c.locator(".table.scrolls").wait_for(timeout=8000)
    except Exception:
        print(
            "DEBUG table:",
            c.locator(".table").evaluate(
                "e => ({sw: e.scrollWidth, cw: e.clientWidth, days: e.style.cssText, cls: e.className, cols: getComputedStyle(e).gridTemplateColumns})"
            ),
        )
        shot(page, "debug-overflow")
        raise
    shot(page, "swipe-overflow")
    x, y = box()
    wk = week()
    scroll = lambda: c.locator(".table").evaluate("e => e.scrollLeft")
    swipe(page, cdp, x + 120, y, x - 120, y)
    if scroll() <= 0 or week() != wk:
        failures.append(
            f"a drag in the overflowing table should scroll it (scroll {scroll()}, {week()})"
        )
    swipe(page, cdp, x + 150, y, x - 150, y)  # now at the right edge: change week
    if week() == wk:
        failures.append("a swipe at the table's edge did not change the week")
    print("overflow: scrolled then changed week:", wk, "->", week())
    ctx.close()


def main() -> None:
    OUT.mkdir(exist_ok=True)
    wait_for(PORTAL + "/__admin/state")
    tokens = onboard()
    today = date.today()
    monday = today - timedelta(days=today.weekday())
    nxt = monday + timedelta(days=7)
    failures = []

    with sync_playwright() as pw:
        browser = pw.chromium.launch()
        race_check(browser, tokens, failures)
        swipe_check(browser, tokens, failures)
        # 1. Layouts and themes: the week view in every combination.
        for sname, size in SHOTS.items():
            for dark in (False, True):
                theme = "dark" if dark else "light"
                ctx = new_context(browser, tokens, size, dark)
                page = ctx.new_page()
                page.on("pageerror", lambda e: failures.append(f"pageerror {e}"))
                page.on("console", lambda m: CONSOLE.append(m.text[:200]))
                for view, layout in (("planning", "grid"), ("row", "row"), ("wide", "row-wide")):
                    admin("/__admin/reset", {})
                    open_view(page, view)
                    shot(page, f"week-{layout}-{sname}-{theme}")
                    over = page_overflow(page)
                    print(f"layout={layout} {sname}px {theme}: page overflow {over}px")
                    if over:
                        failures.append(
                            f"horizontal page scroll {over}px ({layout} {sname} {theme})"
                        )
                    # Touch targets of the pastilles.
                    sizes = (
                        card(page)
                        .locator(".table .pill")
                        .evaluate_all(
                            "els => els.map(e => { const r = e.getBoundingClientRect(); return Math.min(r.width, r.height); })"
                        )
                    )
                    print(f"  pastilles: {len(sizes)}, smallest {min(sizes):.0f}px")
                    if min(sizes) < 32:
                        failures.append(f"touch target {min(sizes)}px")
                    # Does a row of the table scroll sideways inside the card?
                    inner = (
                        card(page).locator(".table").evaluate("e => e.scrollWidth - e.clientWidth")
                    )
                    print(f"  inner table overflow: {inner}px")
                ctx.close()

        # 2. The flow, on the phone in the light theme and on the desktop in the dark one.
        for sname, dark in (("390", False), ("1280", True)):
            theme = "dark" if dark else "light"
            tag = f"{sname}-{theme}"
            ctx = new_context(browser, tokens, SHOTS[sname], dark)
            page = ctx.new_page()
            page.on("pageerror", lambda e: failures.append(f"pageerror {e}"))
            admin("/__admin/reset", {})
            open_view(page, "planning")
            c = card(page)

            # Locked cells: past Monday, booked or not, cannot be toggled.
            if today > monday:
                locked = pill(page, ALICE, "repas", monday)
                expect(locked).to_have_attribute("aria-disabled", "true")
                locked.click(force=True)
                expect(c.locator(".foot")).to_have_count(0)
                shot(page, f"locked-{tag}")
            else:
                print("today is Monday: no past cell to check")

            # A draft across two weeks.
            fri = monday + timedelta(days=4)
            thu_n, fri_n = nxt + timedelta(days=3), nxt + timedelta(days=4)
            pill(page, ALICE, "accueil_soir", fri).click()
            expect(c.locator(".foot .count")).to_contain_text("1 modification")
            c.locator('[data-act="next"]').click()
            expect(pill(page, ALICE, "accueil_soir", thu_n)).to_be_visible()
            expect(c.locator(".foot .count")).to_contain_text("1 modification")  # survives
            pill(page, ALICE, "accueil_soir", thu_n).click()
            pill(page, ALICE, "repas", fri_n).click()  # booked: cancel
            pill(page, BOB, "accueil_soir", nxt).click()
            expect(c.locator(".foot .count")).to_contain_text("6 modifications")
            shot(page, f"draft-{tag}")

            # Validate, look at the confirmation, confirm.
            c.locator('[data-act="validate"]').click()
            dialog = c.locator(".dialog")
            expect(dialog).to_be_visible()
            expect(dialog.locator(".block.cost")).to_contain_text("Estimation, facturé après coup")
            expect(dialog.locator(".block.cost")).to_contain_text("accueil du soir à")
            expect(dialog.locator(".block.risk")).to_contain_text("pas de repas à la cantine")
            shot(page, f"confirm-{tag}")
            c.locator('[data-act="confirm"]').click()
            expect(c.locator(".msg.ok")).to_be_visible(timeout=60000)
            shot(page, f"applied-{tag}")
            state = admin("/__admin/state")
            carts = state["carts"]
            print("carts:", json.dumps(carts))
            d = lambda day: {"date": day.strftime("%Y%m%d")}
            fixture = json.loads(
                (
                    Path(__file__).resolve().parent.parent / "fixtures" / "alice_20261109.json"
                ).read_text()
            )
            cancel_id = next(v["id"] for v in fixture[0]["validated"] if v["date"] == "20261113")
            expected = [
                {
                    "childId": ALICE,
                    "servicesReservations": [
                        {
                            "dates": [d(fri), d(thu_n)],
                            "serviceReservationId": "7_7",
                            "serviceId": 7,
                        },
                        {"dates": [d(thu_n)], "serviceReservationId": "8_8", "serviceId": 8},
                    ],
                    "cancelationReservations": [
                        {
                            "dates": [d(fri_n)],
                            "serviceReservationId": "1_1",
                            "serviceId": 1,
                            "reservationsIds": [cancel_id],
                        }
                    ],
                },
                {
                    "childId": BOB,
                    "servicesReservations": [
                        {"dates": [d(nxt)], "serviceReservationId": "7_7", "serviceId": 7},
                        {"dates": [d(nxt)], "serviceReservationId": "8_8", "serviceId": 8},
                    ],
                    "cancelationReservations": [],
                },
            ]
            if carts != expected:
                failures.append(f"carts differ: {json.dumps(carts)}")
            # The UI refreshed: the cells show the new state.
            expect(pill(page, ALICE, "accueil_soir", thu_n)).to_have_attribute(
                "aria-pressed", "true", timeout=20000
            )
            expect(pill(page, ALICE, "repas", fri_n)).to_have_attribute("aria-pressed", "false")
            expect(c.locator(".foot")).to_have_count(0)

            # The study hall goes with the evening care (Mondays and Thursdays only).
            admin("/__admin/reset", {})
            page.reload()
            c.locator(".table").wait_for()
            c.locator('[data-act="next"]').click()
            expect(pill(page, ALICE, "accueil_soir", nxt)).to_be_visible()
            count = c.locator(".foot .count")
            tue = nxt + timedelta(days=1)
            pill(page, ALICE, "accueil_soir", nxt).click()  # Monday: study offered
            expect(count).to_contain_text("2 modifications")
            expect(pill(page, ALICE, "etude", nxt)).to_have_attribute("aria-pressed", "true")
            pill(page, ALICE, "etude", nxt).click()  # unticking the study keeps the evening care
            expect(count).to_contain_text("1 modification")
            expect(pill(page, ALICE, "accueil_soir", nxt)).to_have_attribute("aria-pressed", "true")
            pill(page, ALICE, "accueil_soir", nxt).click()  # off: nothing left
            expect(c.locator(".foot")).to_have_count(0)
            pill(page, ALICE, "accueil_soir", nxt).click()  # off then on again: both again
            expect(count).to_contain_text("2 modifications")
            pill(page, ALICE, "accueil_soir", tue).click()  # Tuesday: no study hall to add
            expect(count).to_contain_text("3 modifications")
            expect(pill(page, ALICE, "etude", tue)).to_have_count(0)
            shot(page, f"study-{tag}")
            c.locator('[data-act="validate"]').click()
            expect(c.locator(".dialog")).to_contain_text("étude incluse, gratuite")
            c.locator('[data-act="back"]').click()
            c.locator('[data-act="undo"]').click()
            # Study days come from the portal: move the study hall to another day of
            # the week, then remove it altogether (the start of a school year).
            admin("/__admin/reset", {})
            for day, on in ((nxt, False), (tue, True)):
                admin("/__admin/open", {"sid": "8_8", "date": day.strftime("%Y%m%d"), "open": on})
            page.reload()
            c.locator(".table").wait_for()
            c.locator('[data-act="next"]').click()
            expect(pill(page, ALICE, "accueil_soir", nxt)).to_be_visible()
            pill(page, ALICE, "accueil_soir", nxt).click()  # no study offered that day any more
            expect(count).to_contain_text("1 modification")
            pill(page, ALICE, "accueil_soir", tue).click()  # the new study day
            expect(count).to_contain_text("3 modifications")
            expect(pill(page, ALICE, "etude", tue)).to_have_attribute("aria-pressed", "true")
            c.locator('[data-act="undo"]').click()
            admin("/__admin/open", {"sid": "8_8", "date": tue.strftime("%Y%m%d"), "open": False})
            page.reload()
            c.locator(".table").wait_for()
            c.locator('[data-act="next"]').click()
            expect(pill(page, ALICE, "accueil_soir", tue)).to_be_visible()
            pill(page, ALICE, "accueil_soir", tue).click()  # no study hall in that week's data
            expect(count).to_contain_text("1 modification")
            c.locator('[data-act="undo"]').click()
            admin("/__admin/reset", {})
            page.reload()
            c.locator(".table").wait_for()
            c.locator('[data-act="next"]').click()
            # Unticking the evening care removes a booked study hall too.
            for sid in ("7_7", "8_8"):
                admin("/__admin/book", {"child": BOB, "sid": sid, "date": thu_n.strftime("%Y%m%d")})
            page.reload()
            c.locator(".table").wait_for()
            c.locator('[data-act="next"]').click()
            expect(pill(page, BOB, "etude", thu_n)).to_have_attribute("aria-pressed", "true")
            pill(page, BOB, "accueil_soir", thu_n).click()
            expect(count).to_contain_text("2 modifications")
            expect(pill(page, BOB, "etude", thu_n)).to_have_attribute("aria-pressed", "false")

            # A conflict: the other parent books the cell while the draft waits.
            admin("/__admin/reset", {})
            page.reload()
            c.locator(".table").wait_for()
            c.locator('[data-act="next"]').click()
            expect(pill(page, ALICE, "accueil_soir", thu_n)).to_be_visible()
            pill(page, ALICE, "accueil_soir", thu_n).click()
            pill(page, BOB, "accueil_soir", thu_n).click()
            c.locator('[data-act="validate"]').click()
            expect(c.locator(".dialog .block.cost")).to_contain_text("Estimation", timeout=30000)
            # The other parent books while the confirmation is open.
            admin("/__admin/book", {"child": ALICE, "sid": "7_7", "date": thu_n.strftime("%Y%m%d")})
            try:
                c.locator('[data-act="confirm"]').click(timeout=10000)
            except Exception:
                shot(page, f"debug-confirm-{tag}")
                print("DIALOG:", c.locator(".dialog").inner_text())
                raise
            expect(c.locator(".dialog h2")).to_contain_text("a changé", timeout=60000)
            shot(page, f"conflict-{tag}")
            if admin("/__admin/state")["carts"]:
                failures.append("a cart was sent despite the conflict")
            c.locator('[data-act="review"]').click()
            expect(pill(page, ALICE, "accueil_soir", thu_n)).to_have_attribute(
                "aria-pressed", "true", timeout=20000
            )
            # Bob's draft is kept (it did not conflict).
            expect(c.locator(".foot .count")).to_contain_text("2 modifications")
            shot(page, f"after-conflict-{tag}")
            ctx.close()
        browser.close()

    if failures:
        print("FAILURES:\n" + "\n".join(failures))
        sys.exit(1)
    print("browser test OK")


if __name__ == "__main__":
    main()
