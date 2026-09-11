"""Local Raspberry Pi Home Hub adapter foundation. No cloud or public internet."""
from __future__ import annotations

from typing import Any, Callable

from fastapi import HTTPException

from app.modules.lifesaver.hardware.adapters import simulated_home_hub
from app.modules.lifesaver.hardware.hardware_mode import configured_pi_host, local_pi_enabled
from app.modules.lifesaver.hardware.mock_pi import handle_in_process
from app.modules.lifesaver.hardware.network_safety import reject_public_device_host, retry_ceiling, timeout_ms

Transport = Callable[[dict[str, Any], str], dict[str, Any]]

_TRANSPORT: Transport | None = None
_ATTEMPTS = 0


def set_transport(transport: Transport | None) -> None:
    global _TRANSPORT
    _TRANSPORT = transport


def attempts() -> int:
    return _ATTEMPTS


def reset_attempts() -> None:
    global _ATTEMPTS
    _ATTEMPTS = 0


def _default_transport(payload: dict[str, Any], host: str) -> dict[str, Any]:
    reject_public_device_host(host)
    result = handle_in_process(payload.get("command") or "DEVICE_PING", payload.get("extra") or {})
    return {"status": result.get("status") or "COMPLETED", "device_status": result.get("device_status"), "ack": True}


def apply_command(
    state: dict[str, Any],
    command: str,
    extra: dict[str, Any] | None,
    *,
    device_type: str,
    local_ip: str | None,
    pairing_state: str | None = None,
    pairing_token: str | None = None,
) -> tuple[dict[str, Any], str, str]:
    extra = extra or {}
    if command == "ROTATE_STOP":
        next_state, status = simulated_home_hub.apply_command(state, command, extra)
        return next_state, status, "COMPLETED"
    if not local_pi_enabled():
        raise HTTPException(status_code=409, detail="Local Pi mode is disabled. Default hardware mode is mock.")
    if pairing_state not in {"PAIRED", "ONLINE", "DEGRADED"}:
        raise HTTPException(status_code=409, detail="Unpaired devices cannot receive Pi commands.")
    presented = extra.get("device_token")
    if not pairing_token or presented != pairing_token:
        raise HTTPException(status_code=403, detail="A valid paired device token is required.")
    host = reject_public_device_host(local_ip or configured_pi_host())
    extra["lan_host"] = host
    extra["timeout_ms"] = timeout_ms()
    transport = _TRANSPORT or _default_transport
    global _ATTEMPTS
    _ATTEMPTS = 0
    last_status = "FAILED"
    ceiling = retry_ceiling()
    for _ in range(ceiling + 1):
        _ATTEMPTS += 1
        result = transport({"command": command, "extra": extra, "device_type": device_type}, host)
        last_status = str((result or {}).get("status") or "FAILED")
        if last_status in {"COMPLETED", "ACKNOWLEDGED"}:
            next_state, status = simulated_home_hub.apply_command(state, command, extra)
            return next_state, status, "COMPLETED" if last_status == "COMPLETED" else "ACKNOWLEDGED"
        if last_status != "TIMED_OUT":
            break
    next_state, status = simulated_home_hub.apply_command(state, "ROTATE_STOP" if command == "ROTATE_STOP" else "GET_STATUS", extra)
    lifecycle = "TIMED_OUT" if last_status == "TIMED_OUT" else "FAILED"
    if lifecycle == "TIMED_OUT":
        status = "OFFLINE"
    return next_state, status, lifecycle
