"""Internal staging-only subscription grant, download and revocation adapters.

No HTTP route is registered here. The Starter delivery endpoints retain their
existing one-time-payment checks. Callers must use dedicated sessions.
"""
from datetime import datetime, timedelta, timezone

import sqlalchemy as sa
from fastapi import HTTPException
from sqlalchemy.orm import Session

from app.db.models import User as PlatformUser
from . import operations_customer_csv_jobs as csv
from .operations_customer_delivery import grants, _guard, revoke_grant
from .operations_package_usage_ledger import AllowanceBlocked
from .operations_subscription_delivery_guard import require_subscription_delivery


def issue_subscription_grant(db: Session, *, authenticated_owner, job_id: str,
                             recipient_user_id: str, explicit_approval: bool) -> dict:
    org = str(getattr(authenticated_owner, "organization_id", "") or "")
    owner = str(getattr(authenticated_owner, "user_id", "") or "")
    role = str(getattr(authenticated_owner, "role", "") or "").lower()
    if (explicit_approval is not True or not org or org.lower() == "global"
            or not owner or role not in {"admin", "super_admin_support"}):
        raise AllowanceBlocked("explicit_authenticated_owner_required")
    try:
        _guard(db)
        job = csv._owned(db, job_id, org, owner, lock=True)
        from .operations_delivery_authorization import _check_saved_csv_assignment, _reject_queued_job_in_legacy_path
        _check_saved_csv_assignment(db, owner=authenticated_owner,
                                    engagement_id=job["engagement_id"], task_id=job["task_id"])
        _reject_queued_job_in_legacy_path(db, job_id=job_id, owner=authenticated_owner)
        recipient = db.get(PlatformUser, recipient_user_id, populate_existing=True)
        proof = require_subscription_delivery(db, job=job, recipient=recipient)
        csv.download_review(db, org=org, owner=owner, job_id=job_id)
        now = datetime.now(timezone.utc)
        values = dict(organization_id=org, owner_user_id=owner,
                      engagement_id=job["engagement_id"], task_id=job["task_id"],
                      lead_id=proof["lead_id"], recipient_user_id=proof["recipient_user_id"],
                      recipient_organization_id=proof["recipient_organization_id"],
                      output_sha256=proof["output_sha256"])
        existing = db.execute(sa.select(grants).where(
            grants.c.job_id == job_id).with_for_update()).mappings().one_or_none()
        if existing is not None:
            if any(existing[k] != v for k, v in values.items()):
                raise AllowanceBlocked("existing_grant_identity_mismatch")
            if existing["revoked_at"] is None and existing["expires_at"] > now:
                raise AllowanceBlocked("active_grant_exists")
        values.update(created_at=now, expires_at=now+timedelta(hours=24), revoked_at=None)
        if existing is None:
            db.execute(sa.insert(grants).values(job_id=job_id, **values))
        else:
            db.execute(sa.update(grants).where(grants.c.job_id == job_id).values(**values))
        db.commit()
        return {"job_id": job_id, "grant_status": "issued", "delivered": False}
    finally:
        db.rollback()


def download_subscription_grant(db: Session, *, authenticated_recipient, job_id: str) -> bytes:
    """Resolve recipient from authenticated session; never accept caller email."""
    try:
        _guard(db)
        uid = str(getattr(authenticated_recipient, "user_id", "") or "")
        org = str(getattr(authenticated_recipient, "organization_id", "") or "")
        if not uid or not org:
            raise HTTPException(403, "Verified customer required")
        recipient = db.get(PlatformUser, uid, populate_existing=True)
        if recipient is None or recipient.organization_id != org:
            raise HTTPException(403, "Verified customer required")
        predicate = (
            grants.c.job_id == job_id, grants.c.recipient_user_id == uid,
            grants.c.recipient_organization_id == org, grants.c.revoked_at.is_(None),
            grants.c.expires_at > datetime.now(timezone.utc),
        )
        row = db.execute(sa.select(grants).where(*predicate)).mappings().one_or_none()
        if row is None:
            raise HTTPException(404, "Delivery unavailable")
        job = csv._owned(db, job_id, row["organization_id"], row["owner_user_id"], lock=True)
        proof = require_subscription_delivery(db, job=job, recipient=recipient)
        # Lock in the same order as issuance, then refresh the grant to detect
        # revocation that occurred while obtaining job and approval locks.
        current = db.execute(sa.select(grants).where(
            *predicate, grants.c.expires_at > datetime.now(timezone.utc)
        ).with_for_update()).mappings().one_or_none()
        if current is None or any(current[k] != proof[k] for k in (
            "lead_id", "recipient_user_id", "recipient_organization_id", "output_sha256"
        )) or any(current[k] != job[k] for k in (
            "organization_id", "owner_user_id", "engagement_id", "task_id"
        )):
            raise HTTPException(404, "Delivery unavailable")
        content = csv.download_review(db, org=job["organization_id"],
                                      owner=job["owner_user_id"], job_id=job_id)
        if current["expires_at"] <= datetime.now(timezone.utc):
            raise HTTPException(404, "Delivery unavailable")
        return content
    finally:
        db.rollback()


def revoke_subscription_grant(db: Session, *, authenticated_owner, job_id: str) -> dict:
    """Revocation must remain possible even after subscription cancellation."""
    org = str(getattr(authenticated_owner, "organization_id", "") or "")
    owner = str(getattr(authenticated_owner, "user_id", "") or "")
    role = str(getattr(authenticated_owner, "role", "") or "").lower()
    if not org or org.lower() == "global" or not owner or role not in {"admin", "super_admin_support"}:
        raise AllowanceBlocked("authenticated_owner_required")
    try:
        return revoke_grant(db, job_id=job_id, owner_org=org, owner_id=owner)
    finally:
        db.rollback()
