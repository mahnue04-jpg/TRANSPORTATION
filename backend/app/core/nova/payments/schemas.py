"""Read-only Nova payments readiness contracts."""
from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field

ReadinessStatus = Literal[
    "Configured",
    "Verified",
    "Missing",
    "Blocked",
    "Not verified",
    "Not applicable",
]


class NovaPaymentsReadinessCheck(BaseModel):
    key: str
    label: str
    status: ReadinessStatus
    classification: str | None = None
    explanation: str
    evidence_source: str


class NovaPaymentsReadinessSection(BaseModel):
    key: str
    label: str
    status: Literal["ok", "unavailable"] = "ok"
    checks: list[NovaPaymentsReadinessCheck] = Field(default_factory=list)


class NovaPaymentsReadinessBlocker(BaseModel):
    area: str
    current_status: ReadinessStatus
    evidence_source: str
    why_blocks_live: str
    required_action: str
    action_authorized_now: bool = False


class NovaPaymentsReadinessOut(BaseModel):
    organization_id: str
    stripe_mode: str = "Not verified"
    go_live_displayed: bool = False
    live_customer_payments_verified: bool = False
    live_driver_payouts_verified: bool = False
    sections: list[NovaPaymentsReadinessSection] = Field(default_factory=list)
    blockers: list[NovaPaymentsReadinessBlocker] = Field(default_factory=list)
    disclaimer: str = (
        "Read-only Stripe readiness. Configured is not verified. TEST is not LIVE. "
        "No setup, activation, payout, or webhook registration happens here."
    )
