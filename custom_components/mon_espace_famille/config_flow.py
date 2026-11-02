"""Config flow: the Mon Espace Famille account, checked by logging in."""

from __future__ import annotations

from collections.abc import Mapping
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
)

from .api import MefAuthError, MefClient, MefError
from .const import CONF_WEEKS, DOMAIN, WEEKS_DEFAULT, WEEKS_MAX

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
    """How many weeks after the current one to read."""

    async def async_step_init(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        if user_input is not None:
            return self.async_create_entry(data={CONF_WEEKS: int(user_input[CONF_WEEKS])})
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
