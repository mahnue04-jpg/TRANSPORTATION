"""Internal authorization for subscription-specific private delivery.

No public routes or grant issuance. The existing Starter route is unchanged.
Callers must hold the transaction until the grant or download decision ends.
"""
from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy.orm import Session

from .operations_commercial_mode import resolve_operations_mode
from .operations_package_usage_ledger import AllowanceBlocked
from .operations_subscription_csv_binding import request_key_for_task
from .operations_subscription_execution_guard import require_current_bound_subscription


def subscription_delivery_mode() -> str | None:
    return resolve_operations_mode(
        staging_flags=("NOVA_OPERATIONS_SUBSCRIPTION_DELIVERY_STAGING_ENABLED",),
        live_flags=("NOVA_OPERATIONS_SUBSCRIPTION_DELIVERY_LIVE_ENABLED",),
    )


def require_subscription_delivery(db: Session, *, job, recipient) -> dict:
    """Authorize the exact approved artifact for a verified paid buyer.

    Job and recipient must be loaded from trusted database records by the
    authenticated delivery caller, not supplied by an HTTP request body.
    """
    mode = subscription_delivery_mode()
    if mode is None:
        raise AllowanceBlocked("subscription_delivery_disabled")
    live = mode == "live"
    if (
        job["status"] != "APPROVED_FOR_DOWNLOAD"
        or not job["output_ref"] or not job["output_sha256"]
        or job["reviewer_user_id"] != job["owner_user_id"]
    ):
        raise AllowanceBlocked("approved_subscription_artifact_required")
    scope = dict(organization_id=job["organization_id"],
                 owner_user_id=job["owner_user_id"],
                 engagement_id=job["engagement_id"], task_id=job["task_id"])
    proof = require_current_bound_subscription(
        db, **scope, input_sha256=job["input_sha256"],
        now=datetime.now(timezone.utc),
    )
    if job["request_key"] != request_key_for_task(**scope, lead_id=proof["lead_id"]):
        raise AllowanceBlocked("subscription_job_request_mismatch")
    from app.modules.marketing.models import MarketingWebsiteLead
    lead = db.get(MarketingWebsiteLead, proof["lead_id"], populate_existing=True)
    email = str(getattr(recipient, "email", "") or "").strip().casefold()
    lead_email = str(lead.work_email or "").strip().casefold() if lead is not None else ""
    if (
        lead is None or recipient is None
        or not getattr(recipient, "id", None)
        or getattr(recipient, "is_active", False) is not True
        or getattr(recipient, "is_verified", False) is not True
        or not getattr(recipient, "organization_id", None)
        or recipient.organization_id == job["organization_id"]
        or not email
        or email != lead_email
    ):
        raise AllowanceBlocked("verified_subscription_recipient_required")
    if live and email.endswith(".invalid"):
        raise AllowanceBlocked("verified_subscription_recipient_required")
    if not live and not email.endswith(".invalid"):
        raise AllowanceBlocked("verified_subscription_recipient_required")
    # proof already carries mode from the execution guard; do not pass it twice.
    if proof.get("mode") not in {None, mode}:
        raise AllowanceBlocked("subscription_delivery_mode_mismatch")
    return {
        **proof,
        "recipient_user_id": recipient.id,
        "recipient_organization_id": recipient.organization_id,
        "output_sha256": job["output_sha256"],
        "mode": mode,
    }
