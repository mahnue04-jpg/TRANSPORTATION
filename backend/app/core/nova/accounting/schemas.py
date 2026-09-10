"""Read-only Nova accounting summary contracts."""
from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field


class NovaAccountingMetric(BaseModel):
    key: str
    label: str
    definition: str
    state: Literal["confirmed", "pending", "calculated", "unavailable"]
    amount_usd: float | None = None
    count: int | None = None
    currency: str = "USD"
    status: Literal["ok", "unavailable"]


class NovaAccountingSummaryOut(BaseModel):
    organization_id: str
    stripe_mode: str = "TEST"
    metrics: list[NovaAccountingMetric] = Field(default_factory=list)
    disclaimer: str = (
        "Read-only aggregates from existing ledgers. Confirmed, pending, and calculated "
        "completion totals are never combined. Stripe remains TEST. This is not a general ledger."
    )
