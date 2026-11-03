"""Serve the planning card and load it on every dashboard."""

from __future__ import annotations

import hashlib
import logging
from pathlib import Path

from homeassistant.core import HomeAssistant
from homeassistant.helpers.storage import Store
from homeassistant.setup import async_when_setup_or_start

from .const import CARD_FILE, CARD_URL, DOMAIN

_LOGGER = logging.getLogger(__name__)


STORE_KEY = f"{DOMAIN}_resource"


async def async_register_card(hass: HomeAssistant) -> None:
    """Serve the card, load it on every dashboard, and make it a Lovelace resource.

    Two ways to load it, both harmless together (the card guards its own
    definition):
    - `add_extra_js_url` works in storage and YAML mode, but the module loads
      asynchronously and can arrive after the dashboard rendered (slow
      mobile network), which shows "Custom element doesn't exist";
    - a Lovelace resource is awaited before the dashboard renders, which is
      why custom cards installed through HACS are reliable in the mobile app.
      It is created automatically in storage mode (YAML mode users add it by
      hand, see the README).
    The address carries a hash of the file so a new version is never cached.
    """
    if "http" not in hass.config.components:
        return
    from homeassistant.components.http import StaticPathConfig

    path = Path(__file__).parent / "www" / CARD_FILE
    if not await hass.async_add_executor_job(path.is_file):
        return
    digest = await hass.async_add_executor_job(lambda: hashlib.md5(path.read_bytes()).hexdigest())
    url = f"{CARD_URL}?v={digest[:12]}"
    await hass.http.async_register_static_paths([StaticPathConfig(CARD_URL, str(path), False)])
    if "frontend" in hass.config.components:
        from homeassistant.components.frontend import add_extra_js_url

        add_extra_js_url(hass, url)
    else:
        _LOGGER.debug("No frontend: the card is served but not loaded")

    async def ensure(_hass: HomeAssistant, _component: str) -> None:
        await async_ensure_resource(hass, url)

    async_when_setup_or_start(hass, "lovelace", ensure)


def _path_of(url: str) -> str:
    return url.split("?", 1)[0]


async def async_ensure_resource(hass: HomeAssistant, url: str) -> bool:
    """Make sure a module resource exists for the card, at its current address.

    Matches on the path (ignoring `?v=`), never duplicates, leaves other
    resources alone, and does nothing in YAML mode or when the collection is
    not there. Returns whether a storage collection was handled.
    """
    from homeassistant.components.lovelace.const import LOVELACE_DATA

    data = hass.data.get(LOVELACE_DATA)
    resources = getattr(data, "resources", None)
    if resources is None or not hasattr(resources, "async_create_item"):
        _LOGGER.debug("Lovelace resources are not editable (YAML mode?): leaving them alone")
        return False
    try:
        await resources.async_get_info()  # loads the collection from storage
        store = Store[dict](hass, 1, STORE_KEY)
        mine = [i for i in resources.async_items() if _path_of(i.get("url", "")) == CARD_URL]
        if mine:
            first = mine[0]
            if first.get("url") != url or first.get("type") != "module":
                await resources.async_update_item(first["id"], {"res_type": "module", "url": url})
            for extra in mine[1:]:  # duplicates of ours (same path): keep one
                await resources.async_delete_item(extra["id"])
            return True
        item = await resources.async_create_item({"res_type": "module", "url": url})
        await store.async_save({"id": item["id"]})
    except Exception:
        _LOGGER.warning("Could not register the card as a Lovelace resource", exc_info=True)
        return False
    return True


async def async_remove_resource(hass: HomeAssistant) -> None:
    """Remove the resource this integration created (and only that one)."""
    from homeassistant.components.lovelace.const import LOVELACE_DATA

    store = Store[dict](hass, 1, STORE_KEY)
    saved = await store.async_load()
    resources = getattr(hass.data.get(LOVELACE_DATA), "resources", None)
    if not saved or resources is None or not hasattr(resources, "async_delete_item"):
        return
    try:
        await resources.async_get_info()
        if any(i.get("id") == saved["id"] for i in resources.async_items()):
            await resources.async_delete_item(saved["id"])
    except Exception:
        _LOGGER.debug("Could not remove the card resource", exc_info=True)
    await store.async_remove()
