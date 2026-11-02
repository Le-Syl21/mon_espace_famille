"""Config and reauth flows, the login faked."""

from homeassistant import config_entries
from homeassistant.core import HomeAssistant
from homeassistant.data_entry_flow import FlowResultType

from custom_components.mon_espace_famille.const import DOMAIN

from .conftest import EMAIL, PASSWORD, FakeMef


async def _start(hass: HomeAssistant):
    return await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": config_entries.SOURCE_USER}
    )


async def test_login_checked(hass: HomeAssistant, fake: FakeMef, aioclient_mock) -> None:
    result = await _start(hass)
    assert result["type"] is FlowResultType.FORM and result["step_id"] == "user"
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {"email": f" {EMAIL} ", "password": PASSWORD}
    )
    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert result["title"] == EMAIL
    assert result["data"] == {"email": EMAIL, "password": PASSWORD}
    assert result["result"].unique_id == EMAIL
    login = aioclient_mock.mock_calls[0]
    assert str(login[1]) == "https://app.monespacefamille.fr/api/v2/login"
    assert login[2] == {
        "client_id": "963568d5-b3ca-4d91-8a73-9eebda59822b",
        "email": EMAIL,
        "password": PASSWORD,
    }


async def test_bad_password(hass: HomeAssistant, fake: FakeMef) -> None:
    result = await _start(hass)
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {"email": EMAIL, "password": "wrong"}
    )
    assert result["type"] is FlowResultType.FORM
    assert result["errors"] == {"base": "invalid_auth"}
    # The second try goes through.
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {"email": EMAIL, "password": PASSWORD}
    )
    assert result["type"] is FlowResultType.CREATE_ENTRY


async def test_server_down(hass: HomeAssistant, fake: FakeMef) -> None:
    fake.server_error = True
    result = await _start(hass)
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {"email": EMAIL, "password": PASSWORD}
    )
    assert result["errors"] == {"base": "cannot_connect"}


async def test_account_once(hass: HomeAssistant, setup) -> None:
    await setup()
    result = await _start(hass)
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {"email": EMAIL.upper(), "password": PASSWORD}
    )
    assert result["type"] is FlowResultType.ABORT and result["reason"] == "already_configured"


async def test_reauth(hass: HomeAssistant, setup, fake: FakeMef) -> None:
    entry = await setup()
    fake.password = "new-secret"
    result = await entry.start_reauth_flow(hass)
    assert result["step_id"] == "reauth_confirm"
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {"password": "still-wrong"}
    )
    assert result["errors"] == {"base": "invalid_auth"}
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {"password": "new-secret"}
    )
    assert result["type"] is FlowResultType.ABORT and result["reason"] == "reauth_successful"
    assert entry.data["password"] == "new-secret"
