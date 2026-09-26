"""Public marketing lead-capture API — isolated from ride / dispatch / billing."""
from __future__ import annotations

import logging
import time
from collections import defaultdict, deque
from datetime import timedelta
from threading import Lock

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.auth import ROLE_ADMIN, ROLE_SUPER_ADMIN_SUPPORT, require_any_role
from app.core.nova.signup.isolation import is_nova_saas_customer_org
from app.db.session import get_db
from app.helpers import now
from app.modules.marketing.models import MarketingWebsiteLead, ensure_marketing_schema
from app.modules.marketing.notify import send_lead_notification
from app.modules.marketing.schemas import MarketingLeadCreate
from app.responses import normalize_success

logger = logging.getLogger("amicor.marketing.routes")

router = APIRouter(prefix="/api/marketing", tags=["marketing"])

_RATE_LOCK = Lock()
_RATE_HITS: dict[str, deque[float]] = defaultdict(deque)
_RATE_LIMIT = 8
_RATE_WINDOW_SEC = 600
_DUPLICATE_WINDOW = timedelta(minutes=10)


class MarketingLeadStatusUpdate(BaseModel):
    status: str


def _require_internal_marketing_admin(
    user=Depends(require_any_role(ROLE_ADMIN, ROLE_SUPER_ADMIN_SUPPORT)),
    db: Session = Depends(get_db),
):
    organization_id = str(getattr(user, "organization_id", "") or "").strip()
    if organization_id and is_nova_saas_customer_org(db, organization_id):
        raise HTTPException(status_code=403, detail="Internal marketing access required")
    return user


def _lead_out(row: MarketingWebsiteLead) -> dict:
    return {
        "lead_id": row.id,
        "lead_type": row.lead_type,
        "status": row.status,
        "organization_name": row.organization_name,
        "contact_name": row.contact_name,
        "work_email": row.work_email,
        "phone": row.phone,
        "preferred_contact_method": row.preferred_contact_method,
        "subject": row.subject,
        "message": row.message,
        "service_plan": row.service_plan,
        "lead_source": row.lead_source,
        "notify_status": row.notify_status,
        "created_at": row.created_at.isoformat() if row.created_at else None,
    }


def _client_ip(request: Request) -> str:
    forwarded = (request.headers.get("x-forwarded-for") or "").split(",")[0].strip()
    if forwarded:
        return forwarded[:128]
    if request.client and request.client.host:
        return request.client.host[:128]
    return "unknown"


def _rate_limited(ip: str) -> bool:
    current = time.time()
    with _RATE_LOCK:
        bucket = _RATE_HITS[ip]
        while bucket and current - bucket[0] > _RATE_WINDOW_SEC:
            bucket.popleft()
        if len(bucket) >= _RATE_LIMIT:
            return True
        bucket.append(current)
        return False


def _find_recent_duplicate(db: Session, payload: MarketingLeadCreate) -> MarketingWebsiteLead | None:
    cutoff = now() - _DUPLICATE_WINDOW
    query = (
        db.query(MarketingWebsiteLead)
        .filter(MarketingWebsiteLead.work_email == payload.work_email)
        .filter(MarketingWebsiteLead.lead_type == payload.lead_type)
        .filter(MarketingWebsiteLead.created_at >= cutoff)
        .order_by(MarketingWebsiteLead.created_at.desc())
    )
    return query.first()


@router.post("/leads")
def create_marketing_lead(
    payload: MarketingLeadCreate,
    request: Request,
    db: Session = Depends(get_db),
):
    """Accept provider/contact interest leads from the public website."""
    ensure_marketing_schema()

    # Silent honeypot acceptance (no DB write) to avoid teaching bots.
    if (payload.website or "").strip():
        return normalize_success(
            data={"accepted": True, "lead_id": None, "spam_filtered": True},
        )

    if payload.lead_type == "provider_interest":
        if not payload.organization_name:
            raise HTTPException(status_code=422, detail="Organization name is required")
        if not payload.organization_type:
            raise HTTPException(status_code=422, detail="Organization type is required")
        if not payload.consent:
            raise HTTPException(status_code=422, detail="Consent is required")
        if not (payload.transportation_needs or "").strip():
            raise HTTPException(status_code=422, detail="Transportation needs are required")

    if payload.lead_type == "contact":
        if not payload.consent:
            raise HTTPException(status_code=422, detail="Consent is required")
        if not (payload.message or "").strip():
            raise HTTPException(status_code=422, detail="Message is required")

    if payload.lead_type == "anonymous_operations":
        if not payload.consent:
            raise HTTPException(status_code=422, detail="Consent is required")
        if not (payload.message or "").strip():
            raise HTTPException(status_code=422, detail="Work description is required")
        if not payload.service_plan:
            raise HTTPException(status_code=422, detail="Choose a starting service option")

    ip = _client_ip(request)
    if _rate_limited(ip):
        raise HTTPException(status_code=429, detail="Too many submissions. Please try again later.")

    try:
        duplicate = _find_recent_duplicate(db, payload)
        if duplicate is not None:
            logger.info(
                "marketing_lead_duplicate lead_id=%s lead_type=%s",
                duplicate.id,
                duplicate.lead_type,
            )
            return normalize_success(
                data={
                    "accepted": True,
                    "lead_id": duplicate.id,
                    "lead_type": duplicate.lead_type,
                    "status": duplicate.status,
                    "duplicate": True,
                    "email_notification": {"attempted": False, "sent": False, "reason": "duplicate"},
                },
            )

        lead_source = (payload.lead_source or payload.source_path or "website").strip()[:128]
        lead = MarketingWebsiteLead(
            lead_type=payload.lead_type,
            status="new",
            organization_name=payload.organization_name,
            contact_name=payload.contact_name,
            work_email=payload.work_email,
            phone=payload.phone,
            organization_type=payload.organization_type,
            estimated_monthly_rides=payload.estimated_monthly_rides,
            service_area=payload.service_area,
            transportation_needs=payload.transportation_needs,
            preferred_contact_method=payload.preferred_contact_method,
            subject=payload.subject,
            message=payload.message,
            consent=bool(payload.consent),
            lead_source=lead_source or "website",
            service_plan=payload.service_plan,
            source_path=payload.source_path or str(request.headers.get("referer") or "")[:256],
            user_agent=(request.headers.get("user-agent") or "")[:512],
            notify_status="pending",
        )
        db.add(lead)
        db.commit()
        db.refresh(lead)
    except Exception as exc:
        logger.exception("marketing lead persist failed: %s", type(exc).__name__)
        db.rollback()
        raise HTTPException(status_code=500, detail="Unable to save your request right now.") from exc

    # Email is best-effort and must never fail the form after a successful save.
    notify_result = send_lead_notification(lead)
    try:
        lead.notify_status = "sent" if notify_result.get("sent") else str(notify_result.get("reason") or "skipped")[:32]
        db.add(lead)
        db.commit()
    except Exception:
        db.rollback()
        logger.warning("marketing_lead_notify_status_update_failed lead_id=%s", lead.id)

    return normalize_success(
        data={
            "accepted": True,
            "lead_id": lead.id,
            "lead_type": lead.lead_type,
            "status": lead.status,
            "duplicate": False,
            "email_notification": {
                "attempted": bool(notify_result.get("attempted")),
                "sent": bool(notify_result.get("sent")),
                "reason": notify_result.get("reason"),
            },
        },
    )


@router.get("/admin/leads")
def list_marketing_leads(
    lead_type: str | None = Query(default=None),
    status: str | None = Query(default=None),
    limit: int = Query(default=50, ge=1, le=200),
    _admin=Depends(_require_internal_marketing_admin),
    db: Session = Depends(get_db),
):
    """Internal lead inbox. Never exposed to Nova SaaS customer tenants."""
    ensure_marketing_schema()
    query = db.query(MarketingWebsiteLead)
    if lead_type:
        query = query.filter(MarketingWebsiteLead.lead_type == lead_type)
    if status:
        query = query.filter(MarketingWebsiteLead.status == status)
    rows = query.order_by(MarketingWebsiteLead.created_at.desc()).limit(limit).all()
    return {"count": len(rows), "leads": [_lead_out(row) for row in rows]}


@router.get("/admin/leads/{lead_id}")
def get_marketing_lead(
    lead_id: str,
    _admin=Depends(require_any_role(ROLE_ADMIN, ROLE_SUPER_ADMIN_SUPPORT)),
    db: Session = Depends(get_db),
):
    ensure_marketing_schema()
    row = db.get(MarketingWebsiteLead, lead_id)
    if row is None:
        raise HTTPException(status_code=404, detail="Lead not found")
    return _lead_out(row)


@router.patch("/admin/leads/{lead_id}/status")
def update_marketing_lead_status(
    lead_id: str,
    payload: MarketingLeadStatusUpdate,
    _admin=Depends(require_any_role(ROLE_ADMIN, ROLE_SUPER_ADMIN_SUPPORT)),
    db: Session = Depends(get_db),
):
    ensure_marketing_schema()
    status = str(payload.status or "").strip().lower()
    if status not in {"new", "contacted", "qualified", "closed"}:
        raise HTTPException(status_code=422, detail="Unsupported lead status")
    row = db.get(MarketingWebsiteLead, lead_id)
    if row is None:
        raise HTTPException(status_code=404, detail="Lead not found")
    row.status = status
    db.commit()
    db.refresh(row)
    return _lead_out(row)
