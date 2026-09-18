"""Future Raspberry Pi adapter label. Uses the local-LAN contract only."""
from __future__ import annotations

from typing import Any

from app.modules.lifesaver.hardware.adapters.local_lan_adapter import apply_command as lan_apply


def apply_command(
    state: dict[str, Any],
    command: str,
    extra: dict[str, Any] | None,
    *,
    device_type: str,
    local_ip: str | None,
) -> tuple[dict[str, Any], str, str]:
    return lan_apply(state, command, extra, device_type=device_type, local_ip=local_ip)
