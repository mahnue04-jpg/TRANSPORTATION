"""Heartbeat and offline detection. Configurable misses, no cloud calls."""
from __future__ import annotations

from typing import Any

from lifesaver_home_hub.audit import now_iso


class HeartbeatMonitor:
    def __init__(self, *, offline_after_misses: int = 3) -> None:
        self.offline_after_misses = offline_after_misses
        self.reset()

    def reset(self) -> None:
        self.state = "ONLINE"
        self.last_heartbeat = now_iso()
        self.last_seen = self.last_heartbeat
        self.latency_ms = 4
        self.missed = 0

    def beat(self, *, latency_ms: int = 4) -> dict[str, Any]:
        self.last_heartbeat = now_iso()
        self.last_seen = self.last_heartbeat
        self.latency_ms = max(0, latency_ms)
        self.missed = 0
        self.state = "ONLINE" if self.latency_ms < 400 else "DEGRADED"
        return self.snapshot()

    def miss(self) -> dict[str, Any]:
        self.missed += 1
        if self.missed >= self.offline_after_misses:
            self.state = "OFFLINE"
        elif self.missed >= 1:
            self.state = "DEGRADED"
        return self.snapshot()

    def recover(self) -> dict[str, Any]:
        self.state = "RECOVERING"
        return self.beat(latency_ms=12)

    def snapshot(self) -> dict[str, Any]:
        return {
            "heartbeat_state": self.state,
            "last_heartbeat": self.last_heartbeat,
            "last_seen": self.last_seen,
            "latency_ms": self.latency_ms,
            "missed_heartbeats": self.missed,
            "offline_after_misses": self.offline_after_misses,
        }
