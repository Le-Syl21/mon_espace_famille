"""A small client for the Mon Espace Famille API (the one its web app uses)."""

from __future__ import annotations

import json
import logging
import time
from datetime import date
from typing import Any
from urllib.parse import quote

import aiohttp

from .const import API_BASE, CLIENT_ID, USER_AGENT

_LOGGER = logging.getLogger(__name__)
_TIMEOUT = aiohttp.ClientTimeout(total=30)
# Refresh a little before the access token runs out.
_EXPIRY_MARGIN = 60
# The characters JavaScript's encodeURIComponent leaves alone, besides
# letters, digits and "-._" that quote() never escapes.
_URI_SAFE = "!'()*~"


class MefError(Exception):
    """The server could not be reached or answered something unexpected."""


class MefAuthError(MefError):
    """The email or the password is refused."""


def api_date(day: date) -> str:
    """The API's date format, YYYYMMDD."""
    return day.strftime("%Y%m%d")


def encode_form(fields: dict[str, Any]) -> str:
    """Encode a form the way the web app's HTTP library (wretch's formUrl) does.

    Objects and lists are sent as JSON, and a list field repeats its key once
    per element: {"cart": [item]} becomes `cart=<URL-encoded JSON of item>`.
    The reservations endpoint wants that item to be a list of per-child
    entries, so `send_cart` sends {"cart": [[entry]]}.
    """

    def one(key: str, value: Any) -> str:
        if isinstance(value, (dict, list)) or value is None:
            text = json.dumps(value, ensure_ascii=False, separators=(",", ":"))
        else:
            text = str(value)
        return f"{quote(key, safe='')}={quote(text, safe=_URI_SAFE)}"

    parts = []
    for key, value in fields.items():
        if isinstance(value, list):
            parts.extend(one(key, item) for item in value)
        else:
            parts.append(one(key, value))
    return "&".join(parts)


class MefClient:
    """Logs in with the email and password, keeps the tokens in memory only."""

    def __init__(self, session: aiohttp.ClientSession, email: str, password: str) -> None:
        self._session = session
        self._email = email
        self._password = password
        self._access: str | None = None
        self._refresh: str | None = None
        self._expires = 0.0

    async def _send(
        self,
        method: str,
        path: str,
        *,
        params: dict[str, str] | None = None,
        json_body: dict | None = None,
        form: str | None = None,
        token: str | None = None,
    ) -> tuple[int, Any]:
        headers = {"User-Agent": USER_AGENT, "Accept": "application/json"}
        if token:
            headers["Authorization"] = f"Bearer {token}"
        data = None
        if form is not None:
            headers["Content-Type"] = "application/x-www-form-urlencoded"
            data = form
        try:
            async with self._session.request(
                method,
                API_BASE + path,
                params=params,
                json=json_body,
                data=data,
                headers=headers,
                timeout=_TIMEOUT,
            ) as resp:
                text = await resp.text()
                status = resp.status
        except (aiohttp.ClientError, TimeoutError) as err:
            raise MefError(f"{method} {path}: {err}") from err
        try:
            body = json.loads(text) if text else None
        except ValueError:
            body = text
        return status, body

    def _store_tokens(self, body: Any) -> bool:
        if not isinstance(body, dict) or not body.get("access_token"):
            return False
        self._access = body["access_token"]
        self._refresh = body.get("refresh_token") or self._refresh
        try:
            lifetime = float(body.get("expires_in") or 1800)
        except (TypeError, ValueError):
            lifetime = 1800.0
        self._expires = time.monotonic() + lifetime - _EXPIRY_MARGIN
        return True

    async def login(self) -> None:
        """Log in; MefAuthError if the credentials are refused."""
        status, body = await self._send(
            "POST",
            "login",
            json_body={"client_id": CLIENT_ID, "email": self._email, "password": self._password},
        )
        if 400 <= status < 500:
            raise MefAuthError(f"login refused ({status})")
        if status != 200 or not self._store_tokens(body):
            raise MefError(f"login failed ({status})")

    async def _renew(self) -> None:
        """Refresh the access token, or log in again if that fails."""
        if self._refresh:
            try:
                status, body = await self._send(
                    "POST",
                    "auth/token",
                    form=encode_form({"client_id": CLIENT_ID, "refresh_token": self._refresh}),
                )
            except MefError:
                status, body = 0, None
            if status == 200 and self._store_tokens(body):
                return
            _LOGGER.debug("Token refresh failed (%s), logging in again", status)
        await self.login()

    async def request(
        self,
        method: str,
        path: str,
        *,
        params: dict[str, str] | None = None,
        form: str | None = None,
    ) -> Any:
        """An authenticated call; renews the token once on a 401."""
        if self._access is None or time.monotonic() >= self._expires:
            await self._renew()
        status, body = await self._send(method, path, params=params, form=form, token=self._access)
        if status == 401:
            await self._renew()
            status, body = await self._send(
                method, path, params=params, form=form, token=self._access
            )
            if status == 401:
                raise MefAuthError(f"{path}: still unauthorized after logging in again")
        if status != 200:
            raise MefError(f"{method} {path}: HTTP {status}")
        return body

    async def members(self) -> dict:
        body = await self.request("GET", "home/members")
        if not isinstance(body, dict):
            raise MefError("home/members: unexpected answer")
        return body

    async def entity(self) -> dict:
        body = await self.request("GET", "me/entity/current")
        return body if isinstance(body, dict) else {}

    async def services_reservations(self, child_id: int, monday: date) -> list[dict]:
        """The services of a child and their days for the week of `monday`."""
        body = await self.request(
            "GET",
            f"family/children/{child_id}/servicesreservations",
            params={"start": api_date(monday)},
        )
        if not isinstance(body, list):
            raise MefError(f"servicesreservations of {child_id}: unexpected answer")
        return body

    async def send_cart(self, cart_item: dict) -> None:
        """Send one child's bookings and cancellations; the server queues them.

        Checked against the server: `cart=<JSON list of entries>` is applied
        within seconds, while a bare entry is queued and silently dropped.
        """
        body = await self.request(
            "POST", "family/children/reservations", form=encode_form({"cart": [[cart_item]]})
        )
        if not isinstance(body, dict) or body.get("status") != "queued":
            raise MefError(f"reservations: unexpected answer {body!r}")

    async def pricing(self, entries: list[dict], prestas: list[dict]) -> list:
        """What the portal would charge now for a cart; nothing is booked.

        The web app asks this before sending a cart. A post-paid commune
        answers an empty list: there is no amount to announce.
        """
        body = await self.request(
            "POST",
            "family/children/reservations/pricing",
            form=encode_form({"cart": [entries], "prestas": [prestas]}),
        )
        return body if isinstance(body, list) else []

    async def calculate(self, entries: list[dict], prestas: list[dict]) -> dict:
        """The portal's check of a cart, without sending it.

        Answers an empty string when every line is fine, else an object whose
        `panierLigneErreur` lists the refused lines ({reservations, annulations}).
        """
        body = await self.request(
            "POST",
            "family/children/reservations/calculate",
            form=encode_form({"cart": [entries], "prestas": [prestas]}),
        )
        return body if isinstance(body, dict) else {}

    async def services_raw(self, child_id: int, monday: date) -> list[dict]:
        """The week's answer as the portal sent it (the pricing wants it back)."""
        return await self.services_reservations(child_id, monday)

    async def rates(self, child_id: int) -> dict[int, float]:
        """The per-day rate of each service, by the service's own number.

        `products/1` lists every product with its rate; a product whose rate
        is missing is left out.
        """
        body = await self.request("GET", f"family/children/{child_id}/products/1")
        found: dict[int, float] = {}
        for product in (body or {}).get("products") or [] if isinstance(body, dict) else []:
            rate = ((product.get("services") or [{}])[0] or {}).get("rate")
            if isinstance(product.get("id"), int) and isinstance(rate, (int, float)):
                found[product["id"]] = float(rate)
        return found
