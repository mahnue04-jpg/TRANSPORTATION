"""V2 revenue/billing preparation. V1 ledger remains authoritative. No Stripe."""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.auth import UserContext
from app.core.nova.work_revenue.materials import sanitize_untrusted
from app.core.nova.work_revenue.models import NovaWorkEngagement, NovaWorkPaymentEvent, NovaWorkRevenueEntry
from app.core.nova.work_revenue.ops import get_revenue_entry
from app.core.nova.work_revenue.service import NovaWorkError, _ensure, _new_id, _owner_filter, _record_audit, _validate_amount
from app.helpers import now

PROCESSOR_STATUSES = (
    "RECORDED",
    "DUPLICATE",
    "STALE",
    "IGNORED",
    "REJECTED",
)


def _iso(value: datetime | None) -> str | None:
    if value is None:
        return None
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc).isoformat()
    return value.astimezone(timezone.utc).isoformat()


def event_out(row: NovaWorkPaymentEvent) -> dict[str, Any]:
    return {
        "event_id": row.event_id,
        "entry_id": row.entry_id,
        "engagement_id": row.engagement_id,
        "processor_status": row.processor_status,
        "amount": round(float(row.amount or 0), 2),
        "currency": row.currency,
        "occurred_at": _iso(row.occurred_at),
        "idempotency_key": row.idempotency_key,
        "stale": bool(row.stale),
        "duplicate": bool(row.duplicate),
        "applied_to_ledger": False,
        "notes": row.notes,
        "created_at": _iso(row.created_at),
        "stripe_object_created": False,
    }


def record_payment_event(
    db: Session,
    payload: dict[str, Any],
    *,
    organization_id: str,
    user: UserContext,
) -> dict[str, Any]:
    """Record a processor-shaped event without changing AMICOR received cash."""
    _ensure()
    idempotency_key = sanitize_untrusted(str(payload.get("idempotency_key") or "")).strip()
    if not idempotency_key or len(idempotency_key) > 120:
        raise NovaWorkError("idempotency_key is required")
    amount = float(_validate_amount(payload.get("amount") or 0, label="amount") or 0)
    entry_id = sanitize_untrusted(str(payload.get("entry_id") or ""))[:32] or None
    engagement_id = sanitize_untrusted(str(payload.get("engagement_id") or ""))[:32] or None
    occurred_at = payload.get("occurred_at")
    stale = False
    if entry_id:
        entry = get_revenue_entry(db, entry_id, organization_id=organization_id, user=user)
        if engagement_id and entry.engagement_id and engagement_id != entry.engagement_id:
            raise NovaWorkError("Payment event engagement does not match ledger entry")
        engagement_id = engagement_id or entry.engagement_id
        if occurred_at and entry.updated_at:
            event_time = occurred_at if getattr(occurred_at, "tzinfo", None) else occurred_at.replace(tzinfo=timezone.utc)
            entry_time = entry.updated_at if entry.updated_at.tzinfo else entry.updated_at.replace(tzinfo=timezone.utc)
            stale = event_time < entry_time
        if entry.engagement_id:
            engagement = (
                _owner_filter(
                    db.query(NovaWorkEngagement).filter(
                        NovaWorkEngagement.organization_id == organization_id,
                        NovaWorkEngagement.engagement_id == entry.engagement_id,
                    ),
                    NovaWorkEngagement,
                    user,
                ).first()
            )
            if engagement is not None and engagement.status in {"ARCHIVED", "CANCELLED"}:
                stale = True
    existing = (
        db.query(NovaWorkPaymentEvent)
        .filter(
            NovaWorkPaymentEvent.organization_id == organization_id,
            NovaWorkPaymentEvent.idempotency_key == idempotency_key,
        )
        .first()
    )
    if existing is not None:
        existing.duplicate = True
        existing.processor_status = "DUPLICATE"
        existing.applied_to_ledger = False
        db.commit()
        db.refresh(existing)
        return event_out(existing)
    status = "STALE" if stale else "RECORDED"
    row = NovaWorkPaymentEvent(
        event_id=_new_id("NWP-"),
        organization_id=organization_id,
        owner_user_id=user.user_id,
        entry_id=entry_id,
        engagement_id=engagement_id,
        processor_status=status,
        amount=amount,
        currency=sanitize_untrusted(str(payload.get("currency") or "USD"))[:12] or "USD",
        occurred_at=occurred_at or now(),
        idempotency_key=idempotency_key,
        stale=stale,
        duplicate=False,
        applied_to_ledger=False,
        notes=sanitize_untrusted(str(payload.get("notes") or "Processor event recorded. Not owner-confirmed received.")),
    )
    db.add(row)
    try:
        db.flush()
    except IntegrityError:
        db.rollback()
        return record_payment_event(db, payload, organization_id=organization_id, user=user)
    _record_audit(
        db,
        organization_id=organization_id,
        user=user,
        event_type="PAYMENT_EVENT_RECORDED",
        summary="Processor-shaped event stored. Ledger cash was not changed. Owner confirmation remains required.",
        ref_id=row.event_id,
        entity_type="payment_event",
        actor_category="NOVA",
        new_state=status,
    )
    db.commit()
    db.refresh(row)
    return event_out(row)


def revenue_preparation(
    db: Session, *, organization_id: str, user: UserContext, reconciliation: dict[str, Any]
) -> dict[str, Any]:
    entries = (
        _owner_filter(
            db.query(NovaWorkRevenueEntry).filter(NovaWorkRevenueEntry.organization_id == organization_id),
            NovaWorkRevenueEntry,
            user,
        ).all()
    )
    remaining = round(
        sum(float(getattr(item, "remaining_amount", 0) or 0) for item in entries if item.stage == "PARTIALLY_PAID"),
        2,
    )
    events = (
        _owner_filter(
            db.query(NovaWorkPaymentEvent).filter(NovaWorkPaymentEvent.organization_id == organization_id),
            NovaWorkPaymentEvent,
            user,
        )
        .order_by(NovaWorkPaymentEvent.created_at.desc())
        .limit(50)
        .all()
    )
    invoice_status = {
        "draft": "CLIENT_CONTEXT billed draft. Not sent.",
        "approved": "Internal APPROVED. Not a real invoice and not paid.",
        "archived": "Historical invoice-support only.",
    }
    return {
        "expected_revenue": reconciliation.get("estimated_pipeline"),
        "contracted_revenue": reconciliation.get("contracted"),
        "client_billed": reconciliation.get("invoice_support_amount"),
        "amicor_received": reconciliation.get("owner_confirmed_received"),
        "partially_paid": remaining > 0,
        "remaining_balance": remaining,
        "archived_historical_revenue": (reconciliation.get("historical_archived") or {}).get("owner_confirmed_received"),
        "processor_status": "NOT_CONNECTED",
        "invoice_support_status": invoice_status,
        "processor_confirmed_payment": False,
        "stripe_confirmed_payment": False,
        "owner_confirmation_authoritative": True,
        "ledger_authority": "nova_work_revenue_entries",
        "payment_events": [event_out(item) for item in events],
        "can_auto_mark_received": False,
    }
