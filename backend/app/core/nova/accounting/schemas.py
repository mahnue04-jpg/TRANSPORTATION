"""Read-only Nova accounting summary contracts."""
from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field

AccountingWindow = Literal["all", "30d", "7d"]
AccountingState = Literal["confirmed", "pending", "calculated", "unavailable"]


class NovaAccountingMetric(BaseModel):
    key: str
    label: str
    definition: str
    state: AccountingState
    amount_usd: float | None = None
    count: int | None = None
    currency: str = "USD"
    status: Literal["ok", "unavailable"]
    window: AccountingWindow = "all"
    window_supported: bool = True
    window_label: str = "All time"
    timestamp_field: str | None = None
    source_note: str = ""
    complete: bool = True


class NovaAccountingSummaryOut(BaseModel):
    organization_id: str
    stripe_mode: str = "TEST"
    window: AccountingWindow = "all"
    window_label: str = "All time"
    window_cutoff_utc: str | None = None
    metrics: list[NovaAccountingMetric] = Field(default_factory=list)
    disclaimer: str = (
        "Read-only aggregates from existing ledgers. Confirmed, pending, and calculated "
        "completion totals are never combined. Stripe remains TEST. This is not a general ledger."
    )
