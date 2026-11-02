"""Diagnostics: the parsed weeks, without credentials, tokens or names."""

from __future__ import annotations

from typing import Any

from homeassistant.components.diagnostics import async_redact_data
from homeassistant.const import CONF_EMAIL, CONF_PASSWORD
from homeassistant.core import HomeAssistant

from .coordinator import MefConfigEntry

TO_REDACT = {CONF_EMAIL, CONF_PASSWORD, "access_token", "refresh_token"}


async def async_get_config_entry_diagnostics(
    hass: HomeAssistant, entry: MefConfigEntry
) -> dict[str, Any]:
    coordinator = entry.runtime_data
    family = coordinator.data
    children = []
    # Children are numbered rather than named; reservation ids are left out.
    for number, child in enumerate(family.children.values(), start=1):
        children.append(
            {
                "child": f"child {number}",
                "services": [
                    {
                        "id": s.id,
                        "service_id": s.service_id,
                        "label": s.label,
                        "kind": s.kind,
                        "open_days": {d.isoformat(): late for d, late in s.open_days.items()},
                        "days": {
                            d.isoformat(): {
                                "status": e.status,
                                "deadline": e.deadline.isoformat() if e.deadline else None,
                            }
                            for d, e in sorted(s.days.items())
                        },
                    }
                    for s in child.services.values()
                ],
            }
        )
    return {
        "entry": {
            "data": async_redact_data(dict(entry.data), TO_REDACT),
            "options": dict(entry.options),
        },
        "last_update_success": coordinator.last_update_success,
        "weeks": [m.isoformat() for m in family.weeks],
        "children": children,
    }
