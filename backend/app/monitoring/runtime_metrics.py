from __future__ import annotations

import time
from datetime import datetime, timezone
from typing import Any

_PROCESS_START_MONOTONIC = time.monotonic()


def get_runtime_metrics() -> dict[str, Any]:
    return {
        "uptime_seconds": round(max(0.0, time.monotonic() - _PROCESS_START_MONOTONIC), 3),
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }
