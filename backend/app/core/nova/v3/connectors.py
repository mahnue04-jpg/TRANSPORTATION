"""Synthetic connector simulation. No live network."""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from app.core.nova.v3.errors import V3Error
from app.core.nova.v3.flags import live_flags

CONNECTOR_KINDS = (
    "opportunity_source",
    "email",
    "crm",
    "invoice_delivery",
    "payment_processor",
    "calendar",
    "document_delivery",
    "webhook_receiver",
)

STATES = (
    "CONNECTED",
    "DISCONNECTED",
    "AUTH_EXPIRED",
    "RATE_LIMITED",
    "TEMPORARY_FAILURE",
    "PERMANENT_FAILURE",
    "HUMAN_ACTION_REQUIRED",
    "DISABLED",
)


@dataclass
class SimulatedConnector:
    connector_id: str
    kind: str
    organization_id: str
    owner_user_id: str
    state: str = "CONNECTED"
    attempts: int = 0
    last_error: str | None = None
    history: list[str] = field(default_factory=list)

    def call(self) -> dict[str, Any]:
        if live_flags()["LIVE_CONNECTORS_ENABLED"]:
            raise V3Error("LIVE_DISABLED", "real connectors cannot be enabled in Phase 2")
        self.attempts += 1
        self.history.append(self.state)
        if self.state == "CONNECTED":
            return {"ok": True, "synthetic": True, "kind": self.kind, "live": False}
        if self.state == "TEMPORARY_FAILURE":
            self.last_error = "temporary synthetic failure"
            raise V3Error("CONNECTOR_TEMPORARY_FAILURE", self.last_error)
        if self.state == "RATE_LIMITED":
            raise V3Error("HUMAN_ACTION_REQUIRED", "rate limits cannot be bypassed")
        if self.state in {"AUTH_EXPIRED", "HUMAN_ACTION_REQUIRED"}:
            raise V3Error("HUMAN_ACTION_REQUIRED", f"connector {self.state}")
        if self.state == "PERMANENT_FAILURE":
            raise V3Error("CONNECTOR_PERMANENT_FAILURE", "permanent synthetic failure")
        raise V3Error("CONNECTOR_DISABLED", f"connector is {self.state}")
