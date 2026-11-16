"""Transactional owner notification outbox — mock email only, separate from marketing."""

from __future__ import annotations

import logging
from datetime import datetime, timedelta
from typing import Any
from uuid import uuid4

from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.nova.growth_agent.errors import GrowthAgentError
from app.core.nova.growth_agent.flags import REAL_EMAIL_SEND
from app.core.nova.growth_agent.models import GaOwnerNotification
from app.core.nova.growth_agent.providers.base import ProviderAdapter
from app.core.nova.growth_agent.redact import redact_mapping

logger = logging.getLogger("amicor.nova.growth_agent.owner_notifications")

DEFAULT_LEASE_SECONDS = 30
DEFAULT_MAX_ATTEMPTS = 5
TERMINAL_STATUSES = frozenset({"provider_accepted", "failed", "suppressed"})


def _utcnow() -> datetime:
    return datetime.utcnow()


def _backoff_seconds(attempt_number: int) -> int:
    return min(300, 2 ** max(1, int(attempt_number)))


def _row_dict(row: GaOwnerNotification) -> dict[str, Any]:
    return {
        "id": row.id,
        "organization_id": row.organization_id,
        "channel": row.channel,
        "purpose": row.purpose,
        "event_type": row.event_type,
        "idempotency_key": row.idempotency_key,
        "status": row.status,
        "provider": row.provider,
        "attempt_number": row.attempt_number,
        "error_code": row.error_code,
        "provider_message_id": row.provider_message_id,
        "payload_redacted_json": dict(row.payload_redacted_json or {}),
        "created_at": row.created_at.isoformat() + "Z" if row.created_at else None,
        "updated_at": row.updated_at.isoformat() + "Z" if row.updated_at else None,
    }


def _reject_marketing_purpose(payload: dict[str, Any], *, explicit_purpose: str | None = None) -> None:
    for candidate in (explicit_purpose, payload.get("purpose")):
        if candidate is not None and str(candidate).strip().lower() == "marketing":
            raise GrowthAgentError(
                "MARKETING_NOT_ALLOWED",
                "Owner appointment notifications are transactional only",
                http_status=403,
            )


def enqueue_owner_notification(
    db: Session,
    *,
    org_id: str,
    event_type: str,
    idempotency_key: str,
    channel: str = "email",
    payload_redacted: dict[str, Any],
    purpose: str | None = None,
) -> dict[str, Any]:
    """Queue a transactional owner notification. Idempotent on (org_id, idempotency_key)."""
    _reject_marketing_purpose(payload_redacted, explicit_purpose=purpose)

    existing = (
        db.query(GaOwnerNotification)
        .filter_by(organization_id=org_id, idempotency_key=idempotency_key)
        .one_or_none()
    )
    if existing:
        return {**_row_dict(existing), "idempotent": True}

    redacted = redact_mapping(dict(payload_redacted or {}))
    redacted.pop("purpose", None)

    row = GaOwnerNotification(
        id=str(uuid4()),
        organization_id=org_id,
        channel=channel,
        purpose="transactional",
        event_type=event_type,
        idempotency_key=idempotency_key,
        status="queued",
        provider="mock_email",
        payload_redacted_json=redacted,
    )
    db.add(row)
    try:
        db.flush()
    except IntegrityError:
        db.rollback()
        dup = (
            db.query(GaOwnerNotification)
            .filter_by(organization_id=org_id, idempotency_key=idempotency_key)
            .one()
        )
        return {**_row_dict(dup), "idempotent": True}
    return _row_dict(row)


def list_owner_notifications(db: Session, org_id: str, limit: int = 50) -> list[dict[str, Any]]:
    """List notifications with honest statuses (provider_accepted is not inbox proof)."""
    lim = max(1, min(int(limit), 200))
    rows = (
        db.query(GaOwnerNotification)
        .filter_by(organization_id=org_id)
        .order_by(GaOwnerNotification.created_at.desc())
        .limit(lim)
        .all()
    )
    return [_row_dict(r) for r in rows]


def _claim_notifications(
    db: Session,
    *,
    worker_id: str,
    limit: int,
    lease_seconds: int = DEFAULT_LEASE_SECONDS,
) -> list[GaOwnerNotification]:
    now = _utcnow()
    batch = max(1, min(int(limit), 100))
    claim_token = f"{worker_id}:{uuid4().hex[:8]}"
    lease_until = now + timedelta(seconds=max(5, lease_seconds))

    available = (GaOwnerNotification.available_at.is_(None)) | (GaOwnerNotification.available_at <= now)
    lease_free = (
        (GaOwnerNotification.claimed_by.is_(None))
        | (GaOwnerNotification.lease_expires_at.is_(None))
        | (GaOwnerNotification.lease_expires_at < now)
    )
    q = db.query(GaOwnerNotification.id).filter(
        GaOwnerNotification.provider == "mock_email",
        GaOwnerNotification.purpose == "transactional",
        available,
        lease_free,
        GaOwnerNotification.status.in_(["queued", "retrying", "running"]),
    )
    candidate_ids = [
        r[0] for r in q.order_by(GaOwnerNotification.created_at.asc()).limit(batch).all()
    ]
    if not candidate_ids:
        return []

    claimed_ids: list[str] = []
    for job_id in candidate_ids:
        row = (
            db.query(GaOwnerNotification)
            .filter(
                GaOwnerNotification.id == job_id,
                GaOwnerNotification.status.in_(["queued", "retrying", "running"]),
                available,
                lease_free,
            )
            .with_for_update(of=GaOwnerNotification)
            .one_or_none()
        )
        if row is None:
            continue
        row.status = "running"
        row.claimed_by = claim_token
        row.claimed_at = now
        row.lease_expires_at = lease_until
        claimed_ids.append(row.id)
    db.flush()
    if not claimed_ids:
        return []
    return (
        db.query(GaOwnerNotification)
        .filter(
            GaOwnerNotification.id.in_(claimed_ids),
            GaOwnerNotification.claimed_by == claim_token,
        )
        .all()
    )


def _fail_or_retry(row: GaOwnerNotification, *, error_code: str) -> dict[str, Any]:
    row.attempt_number = int(row.attempt_number or 0) + 1
    max_attempts = int(row.max_attempts or DEFAULT_MAX_ATTEMPTS)
    row.error_code = error_code
    row.claimed_by = None
    row.claimed_at = None
    row.lease_expires_at = None
    if row.attempt_number >= max_attempts:
        row.status = "failed"
        return _row_dict(row)
    delay = _backoff_seconds(row.attempt_number)
    row.status = "retrying"
    row.available_at = _utcnow() + timedelta(seconds=delay)
    return _row_dict(row)


def _process_one(
    db: Session,
    row: GaOwnerNotification,
    email_adapter: ProviderAdapter,
) -> dict[str, Any]:
    if row.status in TERMINAL_STATUSES:
        return {**_row_dict(row), "deduped": True}

    if row.purpose != "transactional":
        row.status = "suppressed"
        row.error_code = "MARKETING_NOT_ALLOWED"
        row.claimed_by = None
        row.claimed_at = None
        row.lease_expires_at = None
        return _row_dict(row)

    if REAL_EMAIL_SEND:
        row.status = "suppressed"
        row.error_code = "LIVE_EMAIL_DISABLED"
        row.claimed_by = None
        row.claimed_at = None
        row.lease_expires_at = None
        row.available_at = None
        return _row_dict(row)

    try:
        result = email_adapter.send(channel=row.channel, payload=dict(row.payload_redacted_json or {}))
    except Exception as exc:  # noqa: BLE001
        logger.exception("owner notification send failed id=%s", row.id)
        return _fail_or_retry(row, error_code=type(exc).__name__)

    if result.error_code == "LIVE_EMAIL_DISABLED" or result.status == "suppressed":
        row.status = "suppressed"
        row.error_code = result.error_code or "LIVE_EMAIL_DISABLED"
        row.claimed_by = None
        row.claimed_at = None
        row.lease_expires_at = None
        row.available_at = None
        return _row_dict(row)

    if result.status in {"sent_mock", "provider_accepted"}:
        row.status = "provider_accepted"
        row.provider_message_id = result.external_id
        row.error_code = None
        row.claimed_by = None
        row.claimed_at = None
        row.lease_expires_at = None
        row.available_at = None
        out = _row_dict(row)
        out["inbox_delivered"] = False
        out["provider_outcome"] = result.status
        return out

    error = result.error_code or result.status or "SEND_FAILED"
    return _fail_or_retry(row, error_code=error)


def process_owner_notifications(
    db: Session,
    *,
    worker_id: str,
    limit: int,
    email_adapter: ProviderAdapter,
    lease_seconds: int = DEFAULT_LEASE_SECONDS,
) -> dict[str, Any]:
    """Claim and process owner notification jobs (mock provider only)."""
    claimed = _claim_notifications(
        db,
        worker_id=worker_id,
        limit=limit,
        lease_seconds=lease_seconds,
    )
    results = [_process_one(db, row, email_adapter) for row in claimed]
    return {
        "worker_id": worker_id,
        "claimed": len(claimed),
        "processed": len(results),
        "results": results,
    }