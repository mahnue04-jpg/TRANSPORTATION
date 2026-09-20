"""Nova V3 Phase 2 — synthetic live-infrastructure lab. Canonical integration on V2.

Keep package imports lazy so utility modules (capability matching, work packets,
application review) can be imported from Work & Revenue startup/migrations
without pulling the full V3 kernel back through Work & Revenue and creating a
circular import.
"""
from __future__ import annotations

from typing import Any

__all__ = ["NovaV3Kernel", "get_kernel", "reset_kernel", "live_flags"]


def __getattr__(name: str) -> Any:
    if name == "live_flags":
        from app.core.nova.v3.flags import live_flags
        return live_flags
    if name in {"NovaV3Kernel", "get_kernel", "reset_kernel"}:
        from app.core.nova.v3.kernel import NovaV3Kernel, get_kernel, reset_kernel
        return {
            "NovaV3Kernel": NovaV3Kernel,
            "get_kernel": get_kernel,
            "reset_kernel": reset_kernel,
        }[name]
    raise AttributeError(name)
