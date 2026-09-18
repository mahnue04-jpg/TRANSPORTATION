"""Synthetic webhook ingestion. Not a public production endpoint. No Stripe."""
from __future__ import annotations

import hashlib
import hmac
import json
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any

from app.core.nova.v3.errors import V3Error
from app.core.nova.v3.flags import live_flags
from app.core.nova.v3.shared import WEBHOOK_REUSE_CONTRACT, secrets_rejected

LAB_SECRET = "v3-lab-local-mock-secret"


@dataclass
class WebhookEvent:
    event_id: str
    organization_id: str
    owner_user_id: str
    provider: str
    occurred_at: datetime
    payload_hash: str
    normalized: dict[str, Any]
    result: str
    retryable: bool
    duplicate: bool = False
    replayed: bool = False


def sign_lab_payload(payload: dict[str, Any], secret: str = LAB_SECRET) -> str:
    blob = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hmac.new(secret.encode("utf-8"), blob, hashlib.sha256).hexdigest()


def payload_hash(payload: dict[str, Any]) -> str:
    blob = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(blob).hexdigest()


def ingest_webhook(
    *,
    organization_id: str,
    owner_user_id: str,
    provider: str,
    event_id: str,
    payload: dict[str, Any],
    signature: str | None,
    occurred_at: datetime | None = None,
    existing_ids: set[str] | None = None,
) -> WebhookEvent:
    if live_flags()["EXTERNAL_WEBHOOK_PROCESSING_ENABLED"]:
        raise V3Error("LIVE_DISABLED", "public/live webhook processing is off")
    if not WEBHOOK_REUSE_CONTRACT["processor_events_never_apply_to_ledger_by_default"]:
        raise V3Error("STRIPE_FORBIDDEN", "processor events cannot apply to the ledger")
    if provider.lower() == "stripe" or secrets_rejected(json.dumps(payload)):
        raise V3Error("STRIPE_FORBIDDEN", "Stripe webhooks are out of scope")
    if not event_id or not isinstance(payload, dict):
        raise V3Error("MALFORMED_WEBHOOK", "event_id and object payload are required", http_status=400)
    expected = sign_lab_payload(payload)
    if signature != expected:
        raise V3Error("INVALID_SIGNATURE", "synthetic signature mismatch", http_status=400)
    digest = payload_hash(payload)
    duplicate = event_id in (existing_ids or set())
    normalized = {
        "provider": provider,
        "event_id": event_id,
        "amount": payload.get("amount"),
        "type": payload.get("type") or payload.get("event_type") or "unknown",
        "invoice_id": payload.get("invoice_id"),
    }
    return WebhookEvent(
        event_id=event_id,
        organization_id=organization_id,
        owner_user_id=owner_user_id,
        provider=provider,
        occurred_at=occurred_at or datetime.now(timezone.utc),
        payload_hash=digest,
        normalized=normalized,
        result="DUPLICATE" if duplicate else "ACCEPTED_SYNTHETIC",
        retryable=not duplicate,
        duplicate=duplicate,
        replayed=duplicate,
    )
