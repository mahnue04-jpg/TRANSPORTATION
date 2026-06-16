from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Literal

from pydantic import BaseModel, Field

OperationalEventSeverity = Literal["critical", "high", "medium", "low", "info"]


class NovaOperationalEvent(BaseModel):
    event_id: str
    event_type: str
    severity: OperationalEventSeverity = "info"
    source: str = "nova.detector"
    timestamp: str
    correlation_id: str | None = None
    operational_context: dict[str, Any] = Field(default_factory=dict)
    recommended_action: str | None = None
    recovery_hint: str | None = None
    replay_safe: bool = True
    websocket_compatible: bool = True

    @property
    def dedupe_key(self) -> str:
        corr = str(self.correlation_id or "")
        return "|".join([str(self.event_id), str(self.event_type), corr])


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()
