"""The planning card is served by the integration."""

from homeassistant.core import HomeAssistant
from homeassistant.setup import async_setup_component

from custom_components.mon_espace_famille.const import CARD_URL


async def test_card_is_served(hass: HomeAssistant, hass_client, setup) -> None:
    # The HTTP server is there before the integration, as it is in a real start.
    assert await async_setup_component(hass, "http", {})
    assert await async_setup_component(hass, "mon_espace_famille", {})
    client = await hass_client()
    resp = await client.get(CARD_URL)
    assert resp.status == 200
    text = await resp.text()
    assert "mon-espace-famille-planning-card" in text
    assert "customElements.whenDefined" in text
