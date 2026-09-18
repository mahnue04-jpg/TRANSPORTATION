"""V2 revenue/billing preparation. V1 ledger remains authoritative. No Stripe."""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.auth import UserContext
from app.core.nova.work_revenue.materials import sanitize_untrusted
from app.core.nova.work_revenue.models import (
    NovaWorkEngagement,
    NovaWorkHistoricalCorrection,
    NovaWorkPaymentEvent,
    NovaWorkRevenueEntry,
)
from app.core.nova.work_revenue.ops import get_revenue_entry
from app.core.nova.work_revenue.service import (
    NovaWorkError,
    _ensure,
    _new_id,
    _owner_filter,
    _record_audit,
    _validate_amount,
)
from app.core.nova.work_revenue.v2_freeze import FROZEN_ENGAGEMENT, assert_ref_not_frozen
from app.core.nova.work_revenue.v2_idempotency import lookup_canonical, redact_secrets, replay_without_mutation
from app.helpers import now

PROCESSOR_STATUSES = (
    "RECORDED",
    "DUPLICATE",
    "STALE",
    "IGNORED",
    "REJECTED",
    "HISTORICAL_CORRECTION",
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
        "historical": bool(getattr(row, "historical", False)),
        "applied_to_ledger": False,
        "owner_user_id": row.owner_user_id,
        "organization_id": row.organization_id,
        "notes": row.notes,
        "created_at": _iso(row.created_at),
        "stripe_object_created": False,
    }


def _archived_engagement_ids(db: Session, organization_id: str, user: UserContext) -> set[str]:
    rows = _owner_filter(
        db.query(NovaWorkEngagement).filter(NovaWorkEngagement.organization_id == organization_id),
        NovaWorkEngagement,
        user,
    ).all()
    return {row.engagement_id for row in rows if row.status in FROZEN_ENGAGEMENT}


def record_payment_event(
    db: Session,
    payload: dict[str, Any],
    *,
    organization_id: str,
    user: UserContext,
) -> dict[str, Any]:
    """Record a processor-shaped event without changing AMICOR received cash."""
    _ensure()
    if not organization_id:
        raise NovaWorkError("organization_id is required", status_code=400)
    if not user.user_id:
        raise NovaWorkError("owner is required", status_code=400)
    idempotency_key = sanitize_untrusted(str(payload.get("idempotency_key") or "")).strip()
    if not idempotency_key or len(idempotency_key) > 120:
        raise NovaWorkError("idempotency_key is required")
    amount = float(_validate_amount(payload.get("amount") or 0, label="amount") or 0)
    entry_id = sanitize_untrusted(str(payload.get("entry_id") or ""))[:32] or None
    engagement_id = sanitize_untrusted(str(payload.get("engagement_id") or ""))[:32] or None
    occurred_at = payload.get("occurred_at")
    stale = False
    entry = None
    if entry_id:
        entry = get_revenue_entry(db, entry_id, organization_id=organization_id, user=user)
        if entry.owner_user_id != user.user_id and not getattr(user, "role", None):
            raise NovaWorkError("Payment event owner does not match ledger entry", status_code=404)
        if engagement_id and entry.engagement_id and engagement_id != entry.engagement_id:
            raise NovaWorkError("Payment event engagement does not match ledger entry")
        engagement_id = engagement_id or entry.engagement_id
        if occurred_at and entry.updated_at:
            event_time = occurred_at if getattr(occurred_at, "tzinfo", None) else occurred_at.replace(tzinfo=timezone.utc)
            entry_time = entry.updated_at if entry.updated_at.tzinfo else entry.updated_at.replace(tzinfo=timezone.utc)
            stale = event_time < entry_time
        assert_ref_not_frozen(
            db,
            organization_id=organization_id,
            user=user,
            engagement_id=engagement_id,
            entry=entry,
        )
    elif engagement_id:
        assert_ref_not_frozen(
            db,
            organization_id=organization_id,
            user=user,
            engagement_id=engagement_id,
        )
    existing = lookup_canonical(
        db.query(NovaWorkPaymentEvent),
        organization_id=organization_id,
        owner_user_id=user.user_id,
        idempotency_key=idempotency_key,
    )
    if existing is not None:
        replay = replay_without_mutation(existing)
        payload_out = event_out(replay)
        payload_out["duplicate"] = True
        payload_out["processor_status"] = "DUPLICATE"
        payload_out["applied_to_ledger"] = False
        return payload_out
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
        historical=False,
        applied_to_ledger=False,
        notes=redact_secrets(
            sanitize_untrusted(str(payload.get("notes") or "Processor event recorded. Not owner-confirmed received."))
        ),
    )
    db.add(row)
    try:
        db.flush()
    except IntegrityError:
        db.rollback()
        existing = lookup_canonical(
            db.query(NovaWorkPaymentEvent),
            organization_id=organization_id,
            owner_user_id=user.user_id,
            idempotency_key=idempotency_key,
        )
        if existing is None:
            raise NovaWorkError("Duplicate payment event could not be loaded", status_code=409)
        payload_out = event_out(replay_without_mutation(existing))
        payload_out["duplicate"] = True
        payload_out["processor_status"] = "DUPLICATE"
        return payload_out
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
        idempotency_key=idempotency_key,
        source="v2_revenue",
    )
    db.commit()
    db.refresh(row)
    return event_out(row)


def record_historical_correction(
    db: Session,
    payload: dict[str, Any],
    *,
    organization_id: str,
    user: UserContext,
) -> dict[str, Any]:
    _ensure()
    idempotency_key = sanitize_untrusted(str(payload.get("idempotency_key") or "")).strip()
    if not idempotency_key:
        raise NovaWorkError("idempotency_key is required")
    reason = redact_secrets(sanitize_untrusted(str(payload.get("reason") or ""))).strip()
    if len(reason) < 8:
        raise NovaWorkError("Historical correction requires an audit reason")
    amount = float(_validate_amount(payload.get("amount") or 0, label="amount") or 0)
    entry_id = sanitize_untrusted(str(payload.get("entry_id") or ""))[:32] or None
    engagement_id = sanitize_untrusted(str(payload.get("engagement_id") or ""))[:32] or None
    if entry_id:
        entry = get_revenue_entry(db, entry_id, organization_id=organization_id, user=user)
        engagement_id = engagement_id or entry.engagement_id
    existing = lookup_canonical(
        db.query(NovaWorkHistoricalCorrection),
        organization_id=organization_id,
        owner_user_id=user.user_id,
        idempotency_key=idempotency_key,
    )
    if existing is not None:
        return correction_out(replay_without_mutation(existing), duplicate=True)
    row = NovaWorkHistoricalCorrection(
        correction_id=_new_id("NWHC-"),
        organization_id=organization_id,
        owner_user_id=user.user_id,
        entry_id=entry_id,
        engagement_id=engagement_id,
        amount=amount,
        currency=sanitize_untrusted(str(payload.get("currency") or "USD"))[:12] or "USD",
        reason=reason[:400],
        classification="HISTORICAL",
        applied_to_current_totals=False,
        idempotency_key=idempotency_key,
    )
    db.add(row)
    try:
        db.flush()
    except IntegrityError:
        db.rollback()
        existing = lookup_canonical(
            db.query(NovaWorkHistoricalCorrection),
            organization_id=organization_id,
            owner_user_id=user.user_id,
            idempotency_key=idempotency_key,
        )
        if existing is None:
            raise NovaWorkError("Duplicate historical correction could not be loaded", status_code=409)
        return correction_out(existing, duplicate=True)
    _record_audit(
        db,
        organization_id=organization_id,
        user=user,
        event_type="HISTORICAL_REVENUE_CORRECTION",
        summary="Historical correction recorded. Current/active totals were not changed.",
        ref_id=row.correction_id,
        entity_type="historical_correction",
        actor_category="OWNER",
        new_state="HISTORICAL",
        idempotency_key=idempotency_key,
        reason=reason,
        source="v2_revenue",
    )
    db.commit()
    db.refresh(row)
    return correction_out(row)


def correction_out(row: NovaWorkHistoricalCorrection, *, duplicate: bool = False) -> dict[str, Any]:
    return {
        "correction_id": row.correction_id,
        "entry_id": row.entry_id,
        "engagement_id": row.engagement_id,
        "amount": round(float(row.amount or 0), 2),
        "currency": row.currency,
        "reason": row.reason,
        "classification": "HISTORICAL",
        "applied_to_current_totals": False,
        "idempotency_key": row.idempotency_key,
        "duplicate": duplicate,
        "created_at": _iso(row.created_at),
        "owner_user_id": row.owner_user_id,
        "organization_id": row.organization_id,
    }


def list_historical_corrections(
    db: Session, *, organization_id: str, user: UserContext, limit: int = 100
) -> list[dict[str, Any]]:
    _ensure()
    rows = (
        _owner_filter(
            db.query(NovaWorkHistoricalCorrection).filter(
                NovaWorkHistoricalCorrection.organization_id == organization_id
            ),
            NovaWorkHistoricalCorrection,
            user,
        )
        .order_by(NovaWorkHistoricalCorrection.created_at.desc())
        .limit(max(1, min(int(limit or 100), 200)))
        .all()
    )
    return [correction_out(row) for row in rows]


def revenue_preparation(
    db: Session, *, organization_id: str, user: UserContext, reconciliation: dict[str, Any]
) -> dict[str, Any]:
    archived_ids = _archived_engagement_ids(db, organization_id, user)
    entries = (
        _owner_filter(
            db.query(NovaWorkRevenueEntry).filter(NovaWorkRevenueEntry.organization_id == organization_id),
            NovaWorkRevenueEntry,
            user,
        ).all()
    )
    current = [item for item in entries if item.engagement_id not in archived_ids]
    remaining = round(
        sum(float(getattr(item, "remaining_amount", 0) or 0) for item in current if item.stage == "PARTIALLY_PAID"),
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
    corrections = list_historical_corrections(db, organization_id=organization_id, user=user, limit=50)
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
        "historical_corrections": corrections,
        "processor_status": "NOT_CONNECTED",
        "invoice_support_status": invoice_status,
        "processor_confirmed_payment": False,
        "stripe_confirmed_payment": False,
        "owner_confirmation_authoritative": True,
        "ledger_authority": "nova_work_revenue_entries",
        "payment_events": [event_out(item) for item in events],
        "can_auto_mark_received": False,
        "categories_mixed": False,
    }
