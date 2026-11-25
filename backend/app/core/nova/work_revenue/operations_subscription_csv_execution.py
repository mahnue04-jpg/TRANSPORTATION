"""Internal supervised subscription CSV execution; synthetic staging only."""
from __future__ import annotations

import hashlib
from datetime import datetime, timezone

from sqlalchemy.orm import Session

from .operations_package_usage_ledger import AllowanceBlocked
from .operations_subscription_csv_binding import request_key_for_task
from .operations_subscription_execution_guard import require_current_bound_subscription


def execute_reserved_subscription_csv(
    db: Session, *, authenticated_user, engagement_id: str, task_id: str,
    raw: bytes,
) -> dict:
    """Process only an already reserved task; never reserve or deliver here.

    The caller must supply trusted session-derived owner identity. A dedicated
    session is required because the durable CSV engine commits its own work.
    """
    owner = str(getattr(authenticated_user, "user_id", "") or "")
    org = str(getattr(authenticated_user, "organization_id", "") or "")
    role = str(getattr(authenticated_user, "role", "") or "").lower()
    if not owner or not org or org.lower() == "global" or role not in {"admin", "super_admin_support"}:
        raise AllowanceBlocked("authenticated_owner_required")
    if not isinstance(raw, bytes) or not 0 < len(raw) <= 1_000_000:
        raise AllowanceBlocked("invalid_csv_input")
    from .operations_delivery_authorization import _check_saved_csv_assignment
    from .operations_customer_csv_jobs import submit_review_job

    scope = dict(organization_id=org, owner_user_id=owner,
                 engagement_id=engagement_id, task_id=task_id)
    fingerprint = hashlib.sha256(raw).hexdigest()
    expected = None

    def authorize():
        _check_saved_csv_assignment(db, owner=authenticated_user,
                                    engagement_id=engagement_id, task_id=task_id)
        proof = require_current_bound_subscription(
            db, **scope, input_sha256=fingerprint, now=datetime.now(timezone.utc),
        )
        if expected is not None and any(proof[k] != expected[k] for k in (
            "reservation_id", "lead_id", "plan",
        )):
            raise AllowanceBlocked("subscription_execution_binding_changed")
        return proof

    try:
        expected = authorize()
        key = request_key_for_task(**scope, lead_id=expected["lead_id"])
        result = submit_review_job(
            db, org=org, owner=owner, engagement_id=engagement_id, task_id=task_id,
            request_key=key, raw=raw, authorize=authorize,
        )
        return dict(**result, reservation_id=expected["reservation_id"],
                    plan=expected["plan"], delivered=False)
    finally:
        # Release any read/approval locks left by idempotent replay or denial.
        # This adapter owns its session boundary; no unrelated pending work.
        db.rollback()
