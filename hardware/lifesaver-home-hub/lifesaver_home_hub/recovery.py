"""Recovery helpers. Privacy is never silently overridden."""
from __future__ import annotations

from lifesaver_home_hub.dispatcher import apply_fault, recover_agent
from lifesaver_home_hub.emulator import HomeHubEmulator


def recover(hub: HomeHubEmulator, kind: str) -> dict:
    if kind in {"agent_restart", "device_reboot"}:
        return recover_agent(hub)
    if kind == "network_reconnect":
        return apply_fault(hub, "network_reconnect")
    if kind == "stale_command":
        hub.queue.cancel_pending("stale")
        return hub.digital_twin()
    return recover_agent(hub)
