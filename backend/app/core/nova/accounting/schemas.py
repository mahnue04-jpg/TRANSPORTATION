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


AgingBucketKey = Literal["0_7", "8_30", "31_60", "61_plus"]


class NovaAgingBucket(BaseModel):
    key: AgingBucketKey
    label: str
    count: int = 0
    amount: float | None = None


class NovaAgingCurrencySlice(BaseModel):
    currency: str
    count: int = 0
    amount: float | None = None
    oldest_age_days: int | None = None
    unaged_count: int = 0
    missing_amount_count: int = 0
    buckets: list[NovaAgingBucket] = Field(default_factory=list)


class NovaAgingGroup(BaseModel):
    key: str
    label: str
    status: Literal["ok", "unavailable"] = "ok"
    measurement: str = "Age since created"
    timestamp_field: str
    due_date_field: str | None = None
    uses_due_date: bool = False
    collectible: bool = False
    stripe_mode: str = "TEST"
    source_note: str = ""
    currencies: list[NovaAgingCurrencySlice] = Field(default_factory=list)


class NovaAgingSection(BaseModel):
    key: str
    label: str
    status: Literal["ok", "unavailable"] = "ok"
    groups: list[NovaAgingGroup] = Field(default_factory=list)


class NovaAccountingAgingOut(BaseModel):
    organization_id: str
    calculated_as_of_utc: str
    stripe_mode: str = "TEST"
    customer_payment_pipeline: NovaAgingSection
    freight_invoice_pipeline: NovaAgingSection
    disclaimer: str = (
        "Read-only pending-funds aging. Customer payments and Freight invoices stay separate. "
        "No canonical due date exists, so age since created is shown. Stripe remains TEST."
    )
