"""Selects a hardware adapter without leaking adapter details into product UI."""
from __future__ import annotations

from typing import Any

from app.modules.lifesaver.hardware.adapters import simulated_car_hub, simulated_home_hub
from app.modules.lifesaver.hardware.adapters import local_lan_adapter, offline_adapter, raspberry_pi_adapter
from app.modules.lifesaver.hardware.registry import DEVICE_HOME_HUB


def adapter_type_for(device: Any, requested: str | None = None, command: str | None = None) -> str:
    pairing = getattr(device, "pairing_state", None) or (device if isinstance(device, dict) else {}).get("pairing_state")
    status = getattr(device, "status", None) or (device if isinstance(device, dict) else {}).get("status")
    named = (
        requested
        or getattr(device, "adapter_type", None)
        or getattr(device, "adapter_name", None)
        or "simulated"
    )
    named = str(named).lower()
    if pairing == "UNPAIRED":
        return "offline"
    if command in {"DEVICE_RESTART_SIMULATED", "SET_ONLINE"}:
        if named in {"local_lan", "lan"}:
            return "local_lan"
        if named in {"raspberry_pi", "pi", "mock_pi"}:
            return "raspberry_pi"
        return "simulated"
    if status == "OFFLINE" or named == "offline":
        return "offline"
    if named in {"local_lan", "lan"}:
        return "local_lan"
    if named in {"raspberry_pi", "pi", "mock_pi"}:
        return "raspberry_pi"
    return "simulated"


def execute(
    *,
    device: Any,
    command: str,
    state: dict[str, Any],
    extra: dict[str, Any] | None = None,
    adapter_type: str | None = None,
) -> tuple[dict[str, Any], str, str, str]:
    kind = adapter_type_for(device, adapter_type, command)
    device_type = getattr(device, "device_type", None) or "HOME_HUB"
    local_ip = getattr(device, "local_ip", None)
    if kind == "offline":
        next_state, status, lifecycle = offline_adapter.apply_command(state, command, extra)
        return next_state, status, lifecycle, kind
    if kind == "local_lan":
        next_state, status, lifecycle = local_lan_adapter.apply_command(
            state, command, extra, device_type=device_type, local_ip=local_ip or "127.0.0.1"
        )
        return next_state, status, lifecycle, kind
    if kind == "raspberry_pi":
        next_state, status, lifecycle = raspberry_pi_adapter.apply_command(
            state, command, extra, device_type=device_type, local_ip=local_ip or "127.0.0.1"
        )
        return next_state, status, lifecycle, kind
    if device_type == DEVICE_HOME_HUB:
        next_state, status = simulated_home_hub.apply_command(state, command, extra)
    else:
        next_state, status = simulated_car_hub.apply_command(state, command, extra)
    return next_state, status, "COMPLETED", "simulated"
