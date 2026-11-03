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


async def _lovelace(hass: HomeAssistant):
    from homeassistant.components.lovelace.const import LOVELACE_DATA

    assert await async_setup_component(hass, "http", {})
    assert await async_setup_component(hass, "lovelace", {})
    return hass.data[LOVELACE_DATA].resources


def _ours(resources) -> list[dict]:
    return [i for i in resources.async_items() if i["url"].split("?")[0] == CARD_URL]


async def test_card_resource_is_created_updated_and_removed(hass: HomeAssistant, setup) -> None:
    from custom_components.mon_espace_famille.frontend import async_ensure_resource

    resources = await _lovelace(hass)
    await resources.async_get_info()
    other = await resources.async_create_item({"res_type": "module", "url": "/local/other.js"})
    entry = await setup()
    await hass.async_block_till_done()
    (mine,) = _ours(resources)
    assert mine["type"] == "module" and "?v=" in mine["url"]
    # Same address again: nothing changes, nothing is duplicated.
    assert await async_ensure_resource(hass, mine["url"])
    assert len(_ours(resources)) == 1
    # A new file hash updates the one resource (a user's own ?v= is ignored when matching).
    assert await async_ensure_resource(hass, CARD_URL + "?v=newhash")
    (mine,) = _ours(resources)
    assert mine["url"].endswith("?v=newhash")
    # The other resource is never touched.
    assert any(
        i["id"] == other["id"] and i["url"] == "/local/other.js" for i in resources.async_items()
    )
    # Removing the account removes ours only.
    assert await hass.config_entries.async_remove(entry.entry_id)
    await hass.async_block_till_done()
    assert _ours(resources) == []
    assert [i["url"] for i in resources.async_items()] == ["/local/other.js"]


async def test_card_resource_left_alone_in_yaml_mode(hass: HomeAssistant) -> None:
    from homeassistant.components.lovelace.const import LOVELACE_DATA
    from homeassistant.components.lovelace.resources import ResourceYAMLCollection

    from custom_components.mon_espace_famille.frontend import async_ensure_resource

    await _lovelace(hass)
    hass.data[LOVELACE_DATA].resources = ResourceYAMLCollection([{"url": "/x.js", "type": "js"}])
    assert not await async_ensure_resource(hass, CARD_URL + "?v=1")
    assert hass.data[LOVELACE_DATA].resources.async_items() == [{"url": "/x.js", "type": "js"}]


async def test_card_resource_without_lovelace_is_a_no_op(hass: HomeAssistant) -> None:
    from custom_components.mon_espace_famille.frontend import async_ensure_resource

    assert not await async_ensure_resource(hass, CARD_URL + "?v=1")
