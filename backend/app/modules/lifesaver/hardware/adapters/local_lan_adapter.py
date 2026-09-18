"""Local-LAN adapter. In-process mock only unless an allowlisted loopback host is set."""
from __future__ import annotations

from typing import Any

from app.modules.lifesaver.hardware.adapters import simulated_car_hub, simulated_home_hub
from app.modules.lifesaver.hardware.mock_pi import handle_in_process
from app.modules.lifesaver.hardware.network_safety import reject_public_device_host
from app.modules.lifesaver.hardware.registry import DEVICE_HOME_HUB


def apply_command(
    state: dict[str, Any],
    command: str,
    extra: dict[str, Any] | None,
    *,
    device_type: str,
    local_ip: str | None,
) -> tuple[dict[str, Any], str, str]:
    host = reject_public_device_host(local_ip or "127.0.0.1")
    extra = extra or {}
    extra["lan_host"] = host
    if device_type == DEVICE_HOME_HUB:
        handle_in_process(command, extra)
        if command == "SIMULATE_FALL_EVENT":
            return state, "ONLINE", "COMPLETED"
        next_state, status = simulated_home_hub.apply_command(state, command, extra)
        return next_state, status, "COMPLETED"
    next_state, status = simulated_car_hub.apply_command(state, command, extra)
    return next_state, status, "COMPLETED"
