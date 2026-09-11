"""Push metadata-only status cards onto the Home Hub digital twin."""
from __future__ import annotations

from typing import Any


def publish(cards: list[str]) -> None:
    try:
        from app.modules.lifesaver.hardware.home_hub_host import emulator

        hub = emulator()
        if hasattr(hub, "set_connected_health_display"):
            hub.set_connected_health_display(cards[:8])
    except Exception:
        return


def cards_from_rows(*, devices: list[dict[str, Any]], kits: list[dict[str, Any]], results: list[dict[str, Any]]) -> list[str]:
    out: list[str] = []
    for row in devices[:3]:
        alias = (row.get("device_type") or "device").replace("_", " ")
        out.append(f"{alias} connected — simulated.")
    for row in kits[:2]:
        if row.get("status") in {"COLLECTED", "PACKAGED", "PICKUP_REQUESTED"}:
            out.append("Home test kit collection recorded.")
        elif row.get("status") == "RESULT_AVAILABLE":
            out.append("Result document received — provider review available.")
        else:
            out.append(f"Home test kit {row.get('status', 'ORDERED')} — simulated.")
    if results:
        out.append("Result document received — provider review available.")
    return out[:8]
