"""Record verified Operations package revenue without card data or secrets.

Uses the existing NovaBillingRevenueEvent table. Marketing Operations packages
are not SaaS tenants; lead_id is stored in tenant_id for durable correlation.
Disabled unless an explicit commercial mode is active.
"""
from __future__ import annotations

from typing import Any

from sqlalchemy.orm import Session

from app.core.nova.billing.models import NovaBillingRevenueEvent
from app.helpers import uuid4
from app.modules.marketing.operations_billing import AGENT_PLANS
from .operations_commercial_mode import resolve_operations_mode


REVENUE_EVENT_TYPES = frozenset({
    "checkout.session.completed",
    "invoice.paid",
    "charge.refunded",
    "charge.dispute.created",
    "refund.created",
    "refund.updated",
})


def operations_revenue_mode() -> str | None:
    return resolve_operations_mode(
        staging_flags=("NOVA_OPERATIONS_REVENUE_RECORDING_ENABLED",),
        live_flags=("NOVA_OPERATIONS_REVENUE_RECORDING_LIVE_ENABLED",),
    )


def _id(value: Any) -> str | None:
    if isinstance(value, dict):
        value = value.get("id")
    if isinstance(value, str) and value.strip():
        return value.strip()
    return None


def record_operations_revenue_event(
    db: Session, *,
    event_id: str,
    event_type: str,
    lead_id: str,
    plan: str,
    obj: dict[str, Any],
    amount_cents: int | None = None,
) -> bool:
    """Persist one verified Operations payment/refund. Idempotent on event_id.

    Caller must already verify Stripe signature, lead identity, plan, and amount.
    Returns True when a new row is written; False when skipped or already stored.
    """
    if operations_revenue_mode() is None:
        return False
    if event_type not in REVENUE_EVENT_TYPES or plan not in AGENT_PLANS:
        return False
    if not event_id or not lead_id or not event_id.startswith("evt_"):
        return False
    existing = (
        db.query(NovaBillingRevenueEvent)
        .filter(NovaBillingRevenueEvent.stripe_event_id == event_id)
        .first()
    )
    if existing is not None:
        return False

    plan_amount = int(AGENT_PLANS[plan]["amount_cents"])
    if amount_cents is None:
        if event_type in {"checkout.session.completed"}:
            amount_cents = obj.get("amount_total")
        elif event_type == "invoice.paid":
            amount_cents = obj.get("amount_paid")
        elif event_type in {"charge.refunded", "refund.created", "refund.updated"}:
            amount_cents = obj.get("amount_refunded", obj.get("amount"))
        elif event_type == "charge.dispute.created":
            amount_cents = obj.get("amount")
    try:
        cents = int(amount_cents) if amount_cents is not None else plan_amount
    except (TypeError, ValueError):
        cents = plan_amount
    if event_type in {"charge.refunded", "charge.dispute.created", "refund.created", "refund.updated"}:
        cents = -abs(cents)
    elif cents != plan_amount and event_type in {"checkout.session.completed", "invoice.paid"}:
        # Never record a mismatched paid amount as Operations revenue.
        return False

    customer_id = _id(obj.get("customer"))
    subscription_id = _id(obj.get("subscription"))
    invoice_id = _id(obj.get("invoice") if event_type != "invoice.paid" else obj.get("id"))
    charge_id = _id(obj.get("charge") or (obj.get("id") if "charge" in event_type else None))
    currency = str(obj.get("currency") or "usd").lower() or "usd"

    db.add(NovaBillingRevenueEvent(
        id=uuid4(),
        stripe_event_id=event_id,
        event_type=f"operations.{plan}.{event_type}",
        tenant_id=lead_id,
        stripe_customer_id=customer_id,
        stripe_subscription_id=subscription_id,
        stripe_invoice_id=invoice_id,
        stripe_charge_id=charge_id,
        amount_cents=cents,
        currency=currency,
    ))
    return True
