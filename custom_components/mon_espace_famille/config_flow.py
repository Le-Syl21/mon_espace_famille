"""Config flow: the Mon Espace Famille account, checked by logging in."""

from __future__ import annotations

from collections.abc import Mapping
from datetime import time
from typing import Any

import voluptuous as vol
from homeassistant.config_entries import ConfigEntry, ConfigFlow, ConfigFlowResult, OptionsFlow
from homeassistant.const import CONF_EMAIL, CONF_PASSWORD
from homeassistant.core import callback
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.helpers.selector import (
    NumberSelector,
    NumberSelectorConfig,
    NumberSelectorMode,
    TextSelector,
    TextSelectorConfig,
    TextSelectorType,
    TimeSelector,
)

from .api import MefAuthError, MefClient, MefError
from .const import CONF_WEEKS, DOMAIN, KINDS, WEEKS_DEFAULT, WEEKS_MAX
from .settings import (
    CONF_CAP_DAYS,
    FLAT_KINDS,
    Settings,
    end_key,
    flat_key,
    parse_time,
    price_key,
    start_key,
)

_PASSWORD = TextSelector(TextSelectorConfig(type=TextSelectorType.PASSWORD))


class MefConfigFlow(ConfigFlow, domain=DOMAIN):
    VERSION = 1

    async def _check(self, email: str, password: str) -> str | None:
        """None if the account logs in, else the error key."""
        client = MefClient(async_get_clientsession(self.hass), email, password)
        try:
            await client.login()
        except MefAuthError:
            return "invalid_auth"
        except MefError:
            return "cannot_connect"
        return None

    async def async_step_user(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        errors: dict[str, str] = {}
        if user_input is not None:
            email = user_input[CONF_EMAIL].strip()
            await self.async_set_unique_id(email.lower())
            self._abort_if_unique_id_configured()
            if (error := await self._check(email, user_input[CONF_PASSWORD])) is None:
                return self.async_create_entry(
                    title=email,
                    data={CONF_EMAIL: email, CONF_PASSWORD: user_input[CONF_PASSWORD]},
                )
            errors["base"] = error
        return self.async_show_form(
            step_id="user",
            data_schema=vol.Schema(
                {
                    vol.Required(
                        CONF_EMAIL, default=(user_input or {}).get(CONF_EMAIL, "")
                    ): TextSelector(TextSelectorConfig(type=TextSelectorType.EMAIL)),
                    vol.Required(CONF_PASSWORD): _PASSWORD,
                }
            ),
            errors=errors,
        )

    async def async_step_reauth(self, entry_data: Mapping[str, Any]) -> ConfigFlowResult:
        return await self.async_step_reauth_confirm()

    async def async_step_reauth_confirm(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        entry = self._get_reauth_entry()
        errors: dict[str, str] = {}
        if user_input is not None:
            email = entry.data[CONF_EMAIL]
            if (error := await self._check(email, user_input[CONF_PASSWORD])) is None:
                return self.async_update_reload_and_abort(
                    entry, data_updates={CONF_PASSWORD: user_input[CONF_PASSWORD]}
                )
            errors["base"] = error
        return self.async_show_form(
            step_id="reauth_confirm",
            data_schema=vol.Schema({vol.Required(CONF_PASSWORD): _PASSWORD}),
            description_placeholders={"email": entry.data[CONF_EMAIL]},
            errors=errors,
        )

    @staticmethod
    @callback
    def async_get_options_flow(config_entry: ConfigEntry) -> OptionsFlow:
        return MefOptionsFlow()


class MefOptionsFlow(OptionsFlow):
    """Weeks read, then the prices, then the hours; saved together."""

    def __init__(self) -> None:
        self._data: dict[str, Any] = {}

    async def async_step_init(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        if user_input is not None:
            self._data = dict(self.config_entry.options) | {CONF_WEEKS: int(user_input[CONF_WEEKS])}
            return await self.async_step_tarifs()
        current = self.config_entry.options.get(CONF_WEEKS, WEEKS_DEFAULT)
        return self.async_show_form(
            step_id="init",
            data_schema=vol.Schema(
                {
                    vol.Required(CONF_WEEKS, default=current): NumberSelector(
                        NumberSelectorConfig(
                            min=0, max=WEEKS_MAX, step=1, mode=NumberSelectorMode.BOX
                        )
                    )
                }
            ),
        )

    async def async_step_tarifs(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        errors: dict[str, str] = {}
        if user_input is not None:
            for key in (CONF_CAP_DAYS, *map(flat_key, FLAT_KINDS), *map(price_key, KINDS)):
                value = user_input.get(key)
                if value is not None and value < 0:
                    errors[key] = "negative"
            if not errors:
                # A blank flat fee means none; a blank price means the portal's rate.
                self._data[CONF_CAP_DAYS] = int(user_input.get(CONF_CAP_DAYS) or 0)
                for kind in FLAT_KINDS:
                    self._data[flat_key(kind)] = float(user_input.get(flat_key(kind)) or 0)
                for kind in KINDS:
                    self._data.pop(price_key(kind), None)
                    if (price := user_input.get(price_key(kind))) is not None:
                        self._data[price_key(kind)] = float(price)
                return await self.async_step_horaires()
        current = Settings.from_options(self._data | (user_input or {}))
        box = NumberSelector(NumberSelectorConfig(min=0, step=0.01, mode=NumberSelectorMode.BOX))
        fields: dict[Any, Any] = {
            vol.Required(
                CONF_CAP_DAYS,
                default=user_input.get(CONF_CAP_DAYS, current.cap_days)
                if user_input
                else current.cap_days,
            ): NumberSelector(NumberSelectorConfig(min=0, step=1, mode=NumberSelectorMode.BOX))
        }
        for kind in FLAT_KINDS:
            fields[
                vol.Optional(
                    flat_key(kind), description={"suggested_value": current.flat.get(kind)}
                )
            ] = box
        for kind in KINDS:
            fields[
                vol.Optional(
                    price_key(kind), description={"suggested_value": current.prices.get(kind)}
                )
            ] = box
        return self.async_show_form(step_id="tarifs", data_schema=vol.Schema(fields), errors=errors)

    async def async_step_horaires(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        errors: dict[str, str] = {}
        if user_input is not None:
            parsed: dict[str, tuple[time, time]] = {}
            for kind in KINDS:
                start = parse_time(user_input.get(start_key(kind)))
                end = parse_time(user_input.get(end_key(kind)))
                if start is None:
                    errors[start_key(kind)] = "invalid_time"
                elif end is None:
                    errors[end_key(kind)] = "invalid_time"
                elif end <= start:
                    errors[end_key(kind)] = "end_before_start"
                else:
                    parsed[kind] = (start, end)
            if not errors:
                for kind, (start, end) in parsed.items():
                    self._data[start_key(kind)] = start.strftime("%H:%M")
                    self._data[end_key(kind)] = end.strftime("%H:%M")
                return self.async_create_entry(data=self._data)
        current = Settings.from_options(self._data).hours
        fields: dict[Any, Any] = {}
        for kind in KINDS:
            start, end = current[kind]
            fields[vol.Required(start_key(kind), default=start.strftime("%H:%M"))] = TimeSelector()
            fields[vol.Required(end_key(kind), default=end.strftime("%H:%M"))] = TimeSelector()
        return self.async_show_form(
            step_id="horaires", data_schema=vol.Schema(fields), errors=errors
        )
