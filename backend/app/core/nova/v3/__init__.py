"""Nova V3 Phase 2 — synthetic live-infrastructure lab. Canonical integration on V2."""
from app.core.nova.v3.flags import live_flags
from app.core.nova.v3.kernel import NovaV3Kernel, get_kernel, reset_kernel

__all__ = ["NovaV3Kernel", "get_kernel", "reset_kernel", "live_flags"]
