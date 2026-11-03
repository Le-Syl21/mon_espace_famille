"""Serve the planning card and load it on every dashboard."""

from __future__ import annotations

import hashlib
import logging
from pathlib import Path

from homeassistant.core import HomeAssistant

from .const import CARD_FILE, CARD_URL

_LOGGER = logging.getLogger(__name__)


async def async_register_card(hass: HomeAssistant) -> None:
    """Make /mon_espace_famille/<card>.js available and add it to the frontend.

    `add_extra_js_url` loads the module in every dashboard, in storage mode
    and in YAML mode alike, so the card needs no resource entry. The address
    carries a hash of the file so a new version is never served from a cache.
    """
    if "http" not in hass.config.components:
        return
    from homeassistant.components.http import StaticPathConfig

    path = Path(__file__).parent / "www" / CARD_FILE
    if not await hass.async_add_executor_job(path.is_file):
        return
    digest = await hass.async_add_executor_job(lambda: hashlib.md5(path.read_bytes()).hexdigest())
    await hass.http.async_register_static_paths([StaticPathConfig(CARD_URL, str(path), False)])
    if "frontend" in hass.config.components:
        from homeassistant.components.frontend import add_extra_js_url

        add_extra_js_url(hass, f"{CARD_URL}?v={digest[:12]}")
    else:
        _LOGGER.debug("No frontend: the card is served but not loaded")
