"""Explicit customer-specific delivery grants for paid Nova Starter CSV jobs.

Requires separately reviewed schema migration, customer identity and consent,
and private artifact storage. Disabled by default; never sends notifications.
"""
from __future__ import annotations

import os
from datetime import datetime, timedelta, timezone

import sqlalchemy as sa
from fastapi import APIRouter, Depends, Header, HTTPException
from fastapi.responses import JSONResponse, Response
from app.auth import UserContext, get_current_user_context
from app.core.nova.router import require_nova_access
from app.core.nova.work_revenue.owner_auth import require_work_revenue_owner
from app.db.session import get_db
from sqlalchemy.orm import Session

from app.db.models import User as PlatformUser
from app.modules.marketing.models import MarketingWebsiteLead
from .operations_starter_payment_binding import require_paid_starter, starter_bindings
from . import operations_customer_csv_jobs as csv_jobs

metadata = sa.MetaData()
grants = sa.Table(
    "nova_operations_customer_delivery_grants", metadata,
    sa.Column("job_id", sa.String(36), primary_key=True),
    sa.Column("organization_id", sa.String(36), nullable=False),
    sa.Column("owner_user_id", sa.String(36), nullable=False),
    sa.Column("engagement_id", sa.String(32), nullable=False),
    sa.Column("task_id", sa.String(32), nullable=False),
    sa.Column("lead_id", sa.String(36), nullable=False),
    sa.Column("recipient_user_id", sa.String(36), nullable=False),
    sa.Column("recipient_organization_id", sa.String(36), nullable=False),
    sa.Column("output_sha256", sa.String(64), nullable=False),
    sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
    sa.Column("revoked_at", sa.DateTime(timezone=True)),
)


def _guard(db: Session) -> None:
    if (os.getenv("NOVA_OPERATIONS_CUSTOMER_DELIVERY_ENABLED", "").lower() != "true"
            or os.getenv("APP_ENV") != "staging"
            or os.getenv("AMICOR_ENVIRONMENT") != "staging"
            or os.getenv("NOVA_STRIPE_LIVE_ENABLED", "").lower() == "true"
            or os.getenv("NOVA_OPERATIONS_CUSTOMER_SALES_ENABLED", "").lower() == "true"):
        raise HTTPException(503, "Customer delivery disabled")
    try:
        csv_jobs.require_runtime(db)
    except csv_jobs.CustomerCSVBlocked as exc:
        raise HTTPException(503, "Private customer delivery runtime unavailable") from exc
    if db.get_bind().dialect.name != "postgresql":
        raise HTTPException(503, "Isolated PostgreSQL required")
    try:
        if not sa.inspect(db.get_bind()).has_table(grants.name):
            raise HTTPException(503, "Customer delivery migration required")
    except sa.exc.SQLAlchemyError as exc:
        raise HTTPException(503, "Customer delivery schema unavailable") from exc


def _exact_paid_lead(db: Session, *, org: str, owner: str, eng: str, task: str):
    require_paid_starter(
        db, organization_id=org, owner_user_id=owner,
        engagement_id=eng, task_id=task,
    )
    row = db.execute(sa.select(starter_bindings.c.lead_id).where(
        starter_bindings.c.organization_id == org,
        starter_bindings.c.owner_user_id == owner,
        starter_bindings.c.engagement_id == eng,
        starter_bindings.c.task_id == task,
    )).one()
    lead = db.get(MarketingWebsiteLead, row.lead_id)
    if not lead or lead.payment_status != "paid" or not lead.work_email:
        raise HTTPException(409, "Paid customer record unavailable")
    return lead


def issue_grant(
    db: Session, *, job_id: str, owner_org: str, owner_id: str,
    recipient_user_id: str,
) -> dict:
    """Grant exactly one verified account access to one approved artifact."""
    _guard(db)
    row = csv_jobs._owned(db, job_id, owner_org, owner_id, lock=True)
    if row["status"] != "APPROVED_FOR_DOWNLOAD" or not row["output_sha256"]:
        raise HTTPException(409, "Approved CSV output required")
    lead = _exact_paid_lead(
        db, org=owner_org, owner=owner_id,
        eng=row["engagement_id"], task=row["task_id"],
    )
    recipient = db.get(PlatformUser, recipient_user_id)
    if (
        recipient is None or not recipient.is_active or not recipient.is_verified
        or not recipient.organization_id
        or recipient.organization_id == owner_org
        or recipient.email.strip().casefold() != lead.work_email.strip().casefold()
    ):
        raise HTTPException(409, "Verified matching customer account required")
    # Integrity must be checked BEFORE granting customer access.
    csv_jobs.download_review(db, org=owner_org, owner=owner_id, job_id=job_id)
    now = datetime.now(timezone.utc)
    existing = db.execute(
        sa.select(grants).where(grants.c.job_id == job_id).with_for_update()
    ).mappings().first()
    values = dict(
        organization_id=owner_org, owner_user_id=owner_id,
        engagement_id=row["engagement_id"], task_id=row["task_id"],
        lead_id=lead.id, recipient_user_id=recipient.id,
        recipient_organization_id=recipient.organization_id,
        output_sha256=row["output_sha256"],
        created_at=now, expires_at=now + timedelta(hours=24), revoked_at=None,
    )
    if existing:
        # Reissue is permitted ONLY for the original verified recipient and
        # original paid task after explicit revoke or time expiry. Never
        # silently redirect an already issued grant to a different account.
        if any(existing[key] != values[key] for key in (
            "organization_id", "owner_user_id", "engagement_id",
            "task_id", "lead_id", "recipient_user_id",
            "recipient_organization_id", "output_sha256",
        )):
            raise HTTPException(409, "Existing grant identity or artifact mismatch")
        expires = existing["expires_at"]
        if expires.tzinfo is None:
            expires = expires.replace(tzinfo=timezone.utc)
        if existing["revoked_at"] is None and expires > now:
            raise HTTPException(409, "An active delivery grant already exists")
    try:
        if existing:
            db.execute(sa.update(grants).where(
                grants.c.job_id == job_id,
                grants.c.organization_id == owner_org,
                grants.c.owner_user_id == owner_id,
            ).values(**values))
        else:
            db.execute(sa.insert(grants).values(job_id=job_id, **values))
        db.commit()
    except sa.exc.SQLAlchemyError as exc:
        db.rollback()
        raise HTTPException(409, "Delivery grant could not be created") from exc
    return {"job_id": job_id, "grant_status": "issued", "expires_in_hours": 24,
            "delivered": False, "customer_notified": False}


def recipient_download(db: Session, *, job_id: str, user: PlatformUser) -> bytes:
    """Authenticated verified recipient only; no public bearer links."""
    _guard(db)
    if not user.is_active or not user.is_verified or not user.organization_id:
        raise HTTPException(403, "Verified customer account required")
    row = db.execute(sa.select(grants).where(
        grants.c.job_id == job_id,
        grants.c.recipient_user_id == user.id,
        grants.c.recipient_organization_id == user.organization_id,
        grants.c.revoked_at.is_(None),
        grants.c.expires_at > datetime.now(timezone.utc),
    )).mappings().first()
    if row is None:
        raise HTTPException(404, "Delivery unavailable")
    paid = _exact_paid_lead(
        db, org=row["organization_id"], owner=row["owner_user_id"],
        eng=row["engagement_id"], task=row["task_id"],
    )
    if paid.id != row["lead_id"] or paid.work_email.strip().casefold() != user.email.strip().casefold():
        raise HTTPException(403, "Recipient authorization changed")
    job = csv_jobs._owned(db, job_id, row["organization_id"], row["owner_user_id"])
    if (
        job["status"] != "APPROVED_FOR_DOWNLOAD"
        or job["engagement_id"] != row["engagement_id"]
        or job["task_id"] != row["task_id"]
        or job["output_sha256"] != row["output_sha256"]
    ):
        raise HTTPException(409, "Approved artifact no longer matches grant")
    return csv_jobs.download_review(
        db, org=row["organization_id"], owner=row["owner_user_id"], job_id=job_id,
    )


def revoke_grant(db: Session, *, job_id: str, owner_org: str, owner_id: str) -> dict:
    _guard(db)
    now = datetime.now(timezone.utc)
    try:
        changed = db.execute(sa.update(grants).where(
            grants.c.job_id == job_id,
            grants.c.organization_id == owner_org,
            grants.c.owner_user_id == owner_id,
            grants.c.revoked_at.is_(None),
        ).values(revoked_at=now))
        if changed.rowcount != 1:
            db.rollback()
            raise HTTPException(404, "Active delivery grant not found")
        db.commit()
    except sa.exc.SQLAlchemyError as exc:
        db.rollback()
        raise HTTPException(503, "Delivery revocation unavailable") from exc
    return {"job_id": job_id, "grant_status": "revoked", "delivered": False}


customer_delivery_router = APIRouter(
    prefix="/api/nova/work/operations/customer", tags=["nova-operations-customer-delivery"],
)


@customer_delivery_router.get("/deliveries")
def list_my_approved_deliveries(
    user: UserContext = Depends(get_current_user_context),
    db: Session = Depends(get_db),
):
    """Discover only current account's eligible files, never public URLs."""
    _guard(db)
    db_user = db.get(PlatformUser, user.user_id)
    if (
        db_user is None or not db_user.is_active or not db_user.is_verified
        or not db_user.organization_id
        or db_user.organization_id != user.organization_id
    ):
        raise HTTPException(403, "Verified customer account required")
    now = datetime.now(timezone.utc)
    rows = db.execute(sa.select(
        grants.c.job_id, grants.c.organization_id, grants.c.owner_user_id,
        grants.c.engagement_id, grants.c.task_id, grants.c.lead_id,
        grants.c.output_sha256, grants.c.expires_at,
    ).where(
        grants.c.recipient_user_id == db_user.id,
        grants.c.recipient_organization_id == db_user.organization_id,
        grants.c.revoked_at.is_(None),
        grants.c.expires_at > now,
    ).limit(50)).mappings().all()
    available = []
    for row in rows:
        # A valid delivery grant may become invalid if payment was revoked
        # or the owner rejects/replaces the previously approved artifact.
        try:
            paid = _exact_paid_lead(
                db, org=row["organization_id"], owner=row["owner_user_id"],
                eng=row["engagement_id"], task=row["task_id"],
            )
            if (
                paid.id != row["lead_id"]
                or paid.work_email.strip().casefold() != db_user.email.strip().casefold()
            ):
                continue
            job = csv_jobs._owned(
                db, row["job_id"], row["organization_id"], row["owner_user_id"],
            )
            if (
                job["status"] != "APPROVED_FOR_DOWNLOAD"
                or job["output_sha256"] != row["output_sha256"]
                or job["engagement_id"] != row["engagement_id"]
                or job["task_id"] != row["task_id"]
            ):
                continue
        except (HTTPException, csv_jobs.CustomerCSVBlocked):
            continue
        available.append({
            "job_id": row["job_id"],
            "expires_at": row["expires_at"].isoformat(),
            "download_path": (
                "/api/nova/work/operations/customer/deliveries/" + row["job_id"]
            ),
        })
    return JSONResponse(
        content={"deliveries": available},
        headers={"Cache-Control": "private, no-store", "X-Content-Type-Options": "nosniff"},
    )


@customer_delivery_router.get("/deliveries/{job_id}")
def authenticated_customer_csv_download(
    job_id: str,
    user: UserContext = Depends(get_current_user_context),
    db: Session = Depends(get_db),
):
    """Account-bound download; access does not imply customer receipt."""
    db_user = db.get(PlatformUser, user.user_id)
    if db_user is None or db_user.organization_id != user.organization_id:
        raise HTTPException(403, "Customer session invalid")
    try:
        content = recipient_download(db, job_id=job_id, user=db_user)
    except csv_jobs.CustomerCSVBlocked as exc:
        raise HTTPException(getattr(exc, "code", 503), "Customer delivery unavailable") from exc
    return Response(content=content, media_type="text/csv", headers={
        "Content-Disposition": 'attachment; filename="nova-completed-task.csv"',
        "Cache-Control": "private, no-store",
        "X-Content-Type-Options": "nosniff",
        "X-Nova-Delivery-Status": "download-offered-not-receipt-confirmed",
    })


owner_delivery_router = APIRouter(
    prefix="/api/nova/work/operations/owner", tags=["nova-operations-owner-delivery"],
    dependencies=[Depends(require_nova_access), Depends(require_work_revenue_owner)],
)


@owner_delivery_router.post("/jobs/{job_id}/delivery-grants/by-paid-order")
def owner_issue_customer_delivery_by_paid_order(
    job_id: str,
    owner_action: str | None = Header(default=None, alias="X-Nova-Owner-Action"),
    owner: UserContext = Depends(require_work_revenue_owner),
    db: Session = Depends(get_db),
):
    """Resolve the verified customer directly from the bound paid order.

    The owner does not need to know an internal customer UUID. The paid order
    email must map to exactly one active verified non-owner account.
    No email is accepted from caller input, and no invitation is sent.
    """
    if owner_action != "issue-approved-csv-delivery":
        raise HTTPException(403, "Explicit owner delivery approval required")
    _guard(db)
    try:
        from .operations_owner_csv_api import _check_saved_csv_assignment, _reject_queued_job_in_legacy_path
    except ImportError as exc:
        raise HTTPException(503, "Owner CSV authorization unavailable") from exc

    org, owner_id = str(owner.organization_id or ""), str(owner.user_id)
    _guard(db)
    job = csv_jobs._owned(db, job_id, org, owner_id)
    _check_saved_csv_assignment(
        db, owner=owner, engagement_id=job["engagement_id"], task_id=job["task_id"],
    )
    _reject_queued_job_in_legacy_path(db, job_id=job_id, owner=owner)
    if job["status"] != "APPROVED_FOR_DOWNLOAD":
        raise HTTPException(409, "Owner-approved CSV output required")
    lead = _exact_paid_lead(
        db, org=org, owner=owner_id, eng=job["engagement_id"], task=job["task_id"],
    )
    candidates = db.execute(sa.select(PlatformUser).where(
        sa.func.lower(PlatformUser.email) == lead.work_email.strip().lower(),
        PlatformUser.is_active.is_(True),
        PlatformUser.is_verified.is_(True),
        PlatformUser.organization_id.is_not(None),
        PlatformUser.organization_id != org,
    ).limit(2)).scalars().all()
    if len(candidates) != 1:
        raise HTTPException(409, "Exactly one verified customer account matching the paid order is required")
    try:
        return issue_grant(
            db, job_id=job_id, owner_org=org, owner_id=owner_id,
            recipient_user_id=candidates[0].id,
        )
    except csv_jobs.CustomerCSVBlocked as exc:
        raise HTTPException(getattr(exc, "code", 503), "Customer delivery unavailable") from exc


@owner_delivery_router.post("/jobs/{job_id}/delivery-grants/recipients/{recipient_user_id}")
def owner_issue_customer_delivery(
    job_id: str,
    recipient_user_id: str,
    owner_action: str | None = Header(default=None, alias="X-Nova-Owner-Action"),
    owner: UserContext = Depends(require_work_revenue_owner),
    db: Session = Depends(get_db),
):
    if owner_action != "issue-approved-csv-delivery":
        raise HTTPException(403, "Explicit owner delivery approval required")
    _guard(db)
    try:
        from .operations_owner_csv_api import _check_saved_csv_assignment, _reject_queued_job_in_legacy_path
    except ImportError as exc:
        raise HTTPException(503, "Owner CSV authorization unavailable") from exc
    org, owner_id = str(owner.organization_id or ""), str(owner.user_id)
    _guard(db)
    job = csv_jobs._owned(db, job_id, org, owner_id)
    _check_saved_csv_assignment(
        db, owner=owner, engagement_id=job["engagement_id"], task_id=job["task_id"],
    )
    _reject_queued_job_in_legacy_path(db, job_id=job_id, owner=owner)
    try:
        return issue_grant(
            db, job_id=job_id, owner_org=org, owner_id=owner_id,
            recipient_user_id=recipient_user_id,
        )
    except csv_jobs.CustomerCSVBlocked as exc:
        raise HTTPException(getattr(exc, "code", 503), "Customer delivery unavailable") from exc


@owner_delivery_router.post("/jobs/{job_id}/delivery-grants/revoke")
def owner_revoke_customer_delivery(
    job_id: str,
    owner_action: str | None = Header(default=None, alias="X-Nova-Owner-Action"),
    owner: UserContext = Depends(require_work_revenue_owner),
    db: Session = Depends(get_db),
):
    if owner_action != "revoke-csv-delivery":
        raise HTTPException(403, "Explicit owner revocation action required")
    return revoke_grant(
        db, job_id=job_id,
        owner_org=str(owner.organization_id or ""), owner_id=str(owner.user_id),
    )
