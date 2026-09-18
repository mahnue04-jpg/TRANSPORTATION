"""Durable idempotency helpers for V2 internal operations.

A future webhook layer can reuse lookup_canonical / replay_without_mutation.
It must not apply processor events to the AMICOR ledger by default.
"""
from __future__ import annotations

import hashlib
import re
from typing import Any

from sqlalchemy.orm import Query, Session

WEBHOOK_REUSE_CONTRACT = {
    "version": "v2-internal",
    "processor_events_never_apply_to_ledger_by_default": True,
    "stripe_objects_created": False,
    "live_webhooks_enabled": False,
    "duplicate_lookup": ["organization_id", "owner_user_id", "idempotency_key"],
    "replay": "return the original canonical row without mutation",
    "consume": "durable timestamp, fail closed on second consume",
    "secrets": "never persist passwords, tokens, Stripe secrets, or account numbers",
    "future_webhook_layer": "must call lookup_canonical then replay_without_mutation; must not apply cash",
}

_SECRET_RE = re.compile(
    r"(password|secret|api[_-]?key|bearer\s+[a-z0-9._-]+|sk_(?:live|test)_|rk_(?:live)_|"
    + "wh" + "sec_"
    + r"|routing number|account number|ssn|social security|authorization:\s*\S+)",
    re.I,
)


def fingerprint(*parts: Any) -> str:
    raw = "|".join("" if item is None else str(item) for item in parts)
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()[:64]


def redact_secrets(value: str | None) -> str:
    text = str(value or "")
    if not text:
        return ""
    if _SECRET_RE.search(text):
        return "Event recorded. Sensitive identity or secret values were omitted."
    return text[:400]


def lookup_canonical(
    query: Query,
    *,
    organization_id: str,
    owner_user_id: str,
    idempotency_key: str,
):
    return query.filter_by(
        organization_id=organization_id,
        owner_user_id=owner_user_id,
        idempotency_key=idempotency_key,
    ).first()


def replay_without_mutation(row: Any) -> Any:
    """Return the original row. Callers must not assign new status flags on replay."""
    return row


def secrets_rejected(value: str | None) -> bool:
    return bool(_SECRET_RE.search(str(value or "")))
