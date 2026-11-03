"""Fetch the children's weeks every 30 minutes."""

from __future__ import annotations

import asyncio
import logging
import time
from datetime import date, datetime, timedelta

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import CONF_EMAIL, CONF_PASSWORD
from homeassistant.core import HomeAssistant, callback
from homeassistant.exceptions import ConfigEntryAuthFailed
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.helpers.event import async_track_time_change
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed
from homeassistant.util import dt as dt_util

from .api import MefAuthError, MefClient, MefError
from .const import (
    CONF_WEEKS,
    DOMAIN,
    PLANNING_CACHE_SECONDS,
    RATES_CACHE_SECONDS,
    UPDATE_INTERVAL,
    WEEKS_DEFAULT,
)
from .model import Child, Family, merge_week, monday_of, parse_children

_LOGGER = logging.getLogger(__name__)


def action_lock(hass: HomeAssistant) -> asyncio.Lock:
    """One writer at a time: actions and the card's apply share it."""
    return hass.data.setdefault(f"{DOMAIN}_lock", asyncio.Lock())


type MefConfigEntry = ConfigEntry[MefCoordinator]


class MefCoordinator(DataUpdateCoordinator[Family]):
    """One coordinator per account: every child, the current week and the next ones."""

    config_entry: MefConfigEntry

    def __init__(self, hass: HomeAssistant, entry: MefConfigEntry) -> None:
        super().__init__(
            hass, _LOGGER, config_entry=entry, name=DOMAIN, update_interval=UPDATE_INTERVAL
        )
        self.client = MefClient(
            async_get_clientsession(hass), entry.data[CONF_EMAIL], entry.data[CONF_PASSWORD]
        )
        self._commune: str | None = None
        self._unsub_midnight = None
        self._weeks: dict[date, tuple[float, dict[int, Child]]] = {}
        self._rates: dict[int, tuple[float, dict[int, float]]] = {}

    @property
    def weeks_ahead(self) -> int:
        return int(self.config_entry.options.get(CONF_WEEKS, WEEKS_DEFAULT))

    def start_midnight_tick(self) -> None:
        # "Today" and "tomorrow" change at midnight, not with the data.
        self._unsub_midnight = async_track_time_change(
            self.hass, self._midnight, hour=0, minute=0, second=5
        )

    @callback
    def _midnight(self, _now: datetime) -> None:
        if self.data is not None:
            self.async_update_listeners()

    async def async_shutdown(self) -> None:
        if self._unsub_midnight:
            self._unsub_midnight()
            self._unsub_midnight = None
        await super().async_shutdown()

    async def fetch_child(self, child_id: int, first_name: str, mondays: list[date]) -> Child:
        child = Child(id=child_id, first_name=first_name)
        for monday in mondays:
            merge_week(child, monday, await self.client.services_reservations(child_id, monday))
        return child

    async def _async_update_data(self) -> Family:
        first = monday_of(dt_util.now().date())
        mondays = [first + timedelta(weeks=n) for n in range(self.weeks_ahead + 1)]
        try:
            if self._commune is None:
                # Only names the devices' model: not worth failing for.
                try:
                    self._commune = (await self.client.entity()).get("name") or ""
                except MefAuthError:
                    raise
                except MefError as err:
                    _LOGGER.debug("Commune unknown: %s", err)
            children = {}
            for child_id, name in parse_children(await self.client.members()):
                children[child_id] = await self.fetch_child(child_id, name, mondays)
        except MefAuthError as err:
            raise ConfigEntryAuthFailed(str(err)) from err
        except MefError as err:
            raise UpdateFailed(str(err)) from err
        return Family(children=children, commune=self._commune or None, weeks=mondays)

    async def async_refresh_child(self, child_id: int, extra_mondays: list[date]) -> Child:
        """Read a child's weeks again now (plus the given ones), and publish them.

        Weeks outside the usual window are only used to answer the caller.
        Raises the client's errors as they are: the caller is an action.
        """
        family = self.data
        old = family.children[child_id]
        mondays = sorted(set(family.weeks) | set(extra_mondays))
        fresh = await self.fetch_child(child_id, old.first_name, mondays)
        first, end = family.weeks[0], family.weeks[-1] + timedelta(days=7)
        published = fresh.within(first, end)
        children = dict(family.children)
        children[child_id] = published
        self.async_set_updated_data(
            Family(children=children, commune=family.commune, weeks=family.weeks)
        )
        return fresh

    async def async_week(self, monday: date, *, fresh: bool = False) -> dict[int, Child]:
        """Every child's week of `monday`, from the portal (kept a few seconds).

        Works for any week, past or future, not only the polled window. Raises
        the client's errors as they are: the caller answers a request.
        """
        cached = self._weeks.get(monday)
        if cached and not fresh and time.monotonic() - cached[0] < PLANNING_CACHE_SECONDS:
            return cached[1]
        week = {
            child.id: await self.fetch_child(child.id, child.first_name, [monday])
            for child in self.data.children.values()
        }
        self._weeks[monday] = (time.monotonic(), week)
        return week

    def forget_weeks(self) -> None:
        self._weeks.clear()

    async def async_rates(self, child_id: int) -> dict[int, float]:
        """The child's per-day rates by service number, kept for a few hours."""
        cached = self._rates.get(child_id)
        if cached and time.monotonic() - cached[0] < RATES_CACHE_SECONDS:
            return cached[1]
        rates = await self.client.rates(child_id)
        self._rates[child_id] = (time.monotonic(), rates)
        return rates
