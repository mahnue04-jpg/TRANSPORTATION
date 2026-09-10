"""Stripe Connect webhook for driver-onboarding payout readiness.

Verifies a dedicated Connect signing secret. Updates only existing Connect
onboarding/readiness fields. Does not approve, activate, pay, or payout.
"""
from __future__ import annotations

import json
import logging
import os
from typing import Any

from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.helpers import now
from app.modules.platform_ops.models import (
    PlatformDriverOnboardingApplication,
    PlatformDriverOnboardingStripeEvent,
)
from app.modules.platform_ops.onboarding.stripe_connect import map_account_to_payout_status
from app.modules.platform_ops.onboarding.work_setup import _record_work_setup_audit

logger = logging.getLogger("amicor.platform_ops.connect_webhook")

CONNECT_WEBHOOK_PATH = "/api/platform-ops/driver-onboarding/stripe/webhook"
SUPPORTED_EVENT_TYPES = frozenset({"account.updated", "v2.core.account.updated"})

RESULT_APPLIED = "applied"
RESULT_IGNORED = "ignored"
RESULT_UNRELATED = "unrelated"
RESULT_DUPLICATE = "duplicate"


class ConnectWebhookNotConfigured(RuntimeError):
    pass


def connect_webhook_secret() -> str:
    return (os.getenv("STRIPE_WEBHOOK_SECRET") or "").strip()


def _safe_response(*, handled: bool, result: str, duplicate: bool) -> dict[str, Any]:
    return {
        "received": True,
        "handled": handled,
        "duplicate": duplicate,
        "result": result,
    }


def verify_and_parse_connect_webhook(payload: bytes, signature: str | None) -> dict[str, Any]:
    secret = connect_webhook_secret()
    if not secret:
        logger.warning("connect_webhook_not_configured")
        raise ConnectWebhookNotConfigured()
    if not signature:
        raise ValueError("invalid")
    import stripe

    try:
        stripe.Webhook.construct_event(payload, signature, secret)
    except Exception:
        logger.warning("connect_webhook_signature_rejected")
        raise ValueError("invalid") from None
    raw = payload.decode("utf-8") if isinstance(payload, (bytes, bytearray)) else str(payload)
    parsed = json.loads(raw)
    if not isinstance(parsed, dict):
        raise ValueError("invalid")
    return parsed


def _lookup_event(db: Session, event_id: str) -> PlatformDriverOnboardingStripeEvent | None:
    return (
        db.query(PlatformDriverOnboardingStripeEvent)
        .filter(PlatformDriverOnboardingStripeEvent.stripe_event_id == event_id)
        .one_or_none()
    )


def _account_from_event(event: dict[str, Any]) -> tuple[str | None, dict[str, Any] | None]:
    event_type = str(event.get("type") or "").strip()
    data = event.get("data")
    obj = data.get("object") if isinstance(data, dict) else None
    snapshot: dict[str, Any] | None = obj if isinstance(obj, dict) else None
    object_type = str((snapshot or {}).get("object") or "").strip().lower()
    object_id = str((snapshot or {}).get("id") or "").strip() or None

    if event_type == "account.updated":
        if object_id and object_type in {"", "account"}:
            return object_id, snapshot
        return None, None

    if event_type == "v2.core.account.updated":
        related = event.get("related_object")
        related_id = None
        related_type = ""
        if isinstance(related, dict):
            related_id = str(related.get("id") or "").strip() or None
            related_type = str(related.get("type") or "").strip().lower()
        if related_id and related_type in {"", "account", "v2.core.account"}:
            usable = snapshot if object_type in {"", "account", "v2.core.account"} else None
            return related_id, usable
        if object_id and object_type in {"", "account", "v2.core.account"}:
            return object_id, snapshot
        return None, None

    return None, None


def _snapshot_has_status_fields(snapshot: dict[str, Any] | None) -> bool:
    if not isinstance(snapshot, dict):
        return False
    return any(
        key in snapshot
        for key in ("details_submitted", "payouts_enabled", "configuration", "requirements")
    )


def _record_event(
    db: Session,
    *,
    event_id: str,
    event_type: str,
    result: str,
    application: PlatformDriverOnboardingApplication | None = None,
) -> PlatformDriverOnboardingStripeEvent:
    row = PlatformDriverOnboardingStripeEvent(
        stripe_event_id=event_id,
        event_type=(event_type or "unknown")[:128],
        processing_result=result,
        application_id=application.id if application is not None else None,
        organization_id=application.organization_id if application is not None else None,
    )
    db.add(row)
    return row


def process_connect_webhook_event(db: Session, event: dict[str, Any]) -> dict[str, Any]:
    event_id = str(event.get("id") or "").strip()
    event_type = str(event.get("type") or "").strip()
    if not event_id:
        logger.info("connect_webhook result=%s type=%s", RESULT_IGNORED, event_type or "unknown")
        return _safe_response(handled=False, result=RESULT_IGNORED, duplicate=False)

    existing = _lookup_event(db, event_id)
    if existing is not None:
        logger.info("connect_webhook result=%s type=%s", RESULT_DUPLICATE, event_type or "unknown")
        return _safe_response(handled=False, result=RESULT_DUPLICATE, duplicate=True)

    try:
        if event_type not in SUPPORTED_EVENT_TYPES:
            _record_event(db, event_id=event_id, event_type=event_type, result=RESULT_IGNORED)
            db.commit()
            logger.info("connect_webhook result=%s type=%s", RESULT_IGNORED, event_type or "unknown")
            return _safe_response(handled=False, result=RESULT_IGNORED, duplicate=False)

        account_id, snapshot = _account_from_event(event)
        if not account_id:
            _record_event(db, event_id=event_id, event_type=event_type, result=RESULT_UNRELATED)
            db.commit()
            logger.info("connect_webhook result=%s type=%s", RESULT_UNRELATED, event_type)
            return _safe_response(handled=False, result=RESULT_UNRELATED, duplicate=False)

        matches = (
            db.query(PlatformDriverOnboardingApplication)
            .filter(PlatformDriverOnboardingApplication.stripe_account_id == account_id)
            .all()
        )
        if len(matches) != 1:
            _record_event(db, event_id=event_id, event_type=event_type, result=RESULT_UNRELATED)
            db.commit()
            logger.info("connect_webhook result=%s type=%s", RESULT_UNRELATED, event_type)
            return _safe_response(handled=False, result=RESULT_UNRELATED, duplicate=False)

        application = matches[0]
        metadata = snapshot.get("metadata") if isinstance(snapshot, dict) else None
        meta_org = ""
        if isinstance(metadata, dict):
            meta_org = str(metadata.get("organization_id") or "").strip()
        if meta_org and meta_org != str(application.organization_id):
            _record_event(db, event_id=event_id, event_type=event_type, result=RESULT_UNRELATED)
            db.commit()
            logger.info("connect_webhook result=%s type=%s", RESULT_UNRELATED, event_type)
            return _safe_response(handled=False, result=RESULT_UNRELATED, duplicate=False)

        if not _snapshot_has_status_fields(snapshot):
            _record_event(db, event_id=event_id, event_type=event_type, result=RESULT_IGNORED)
            db.commit()
            logger.info("connect_webhook result=%s type=%s", RESULT_IGNORED, event_type)
            return _safe_response(handled=False, result=RESULT_IGNORED, duplicate=False)

        mapped = map_account_to_payout_status(snapshot)
        application.stripe_onboarding_status = mapped["stripe_onboarding_status"]
        application.stripe_payouts_enabled = bool(mapped["stripe_payouts_enabled"])
        application.stripe_details_submitted = bool(mapped["stripe_details_submitted"])
        application.stripe_connect_updated_at = now()
        application.updated_at = now()
        _record_event(
            db,
            event_id=event_id,
            event_type=event_type,
            result=RESULT_APPLIED,
            application=application,
        )
        _record_work_setup_audit(
            db,
            application=application,
            event_type="stripe_connect_webhook_applied",
            metadata={
                "result": RESULT_APPLIED,
                "event_type": event_type,
                "stripe_onboarding_status": application.stripe_onboarding_status,
                "stripe_payouts_enabled": application.stripe_payouts_enabled,
            },
        )
        db.commit()
        logger.info("connect_webhook result=%s type=%s", RESULT_APPLIED, event_type)
        return _safe_response(handled=True, result=RESULT_APPLIED, duplicate=False)
    except IntegrityError:
        db.rollback()
        duplicate = _lookup_event(db, event_id)
        if duplicate is not None:
            logger.info("connect_webhook result=%s type=%s", RESULT_DUPLICATE, event_type or "unknown")
            return _safe_response(handled=False, result=RESULT_DUPLICATE, duplicate=True)
        logger.warning("connect_webhook_failed")
        return _safe_response(handled=False, result=RESULT_IGNORED, duplicate=False)
    except Exception:
        db.rollback()
        logger.warning("connect_webhook_failed")
        return _safe_response(handled=False, result=RESULT_IGNORED, duplicate=False)
