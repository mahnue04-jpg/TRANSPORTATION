"""Public marketing lead-capture API — isolated from ride / dispatch / billing."""
from __future__ import annotations

import logging
import time
from collections import defaultdict, deque
from threading import Lock

from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy.orm import Session

from app.db.session import get_db
from app.modules.marketing.models import MarketingWebsiteLead, ensure_marketing_schema
from app.modules.marketing.schemas import MarketingLeadCreate
from app.responses import normalize_success

logger = logging.getLogger("amicor.marketing.routes")

router = APIRouter(prefix="/api/marketing", tags=["marketing"])

_RATE_LOCK = Lock()
_RATE_HITS: dict[str, deque[float]] = defaultdict(deque)
_RATE_LIMIT = 8
_RATE_WINDOW_SEC = 600


def _client_ip(request: Request) -> str:
    forwarded = (request.headers.get("x-forwarded-for") or "").split(",")[0].strip()
    if forwarded:
        return forwarded[:128]
    if request.client and request.client.host:
        return request.client.host[:128]
    return "unknown"


def _rate_limited(ip: str) -> bool:
    now = time.time()
    with _RATE_LOCK:
        bucket = _RATE_HITS[ip]
        while bucket and now - bucket[0] > _RATE_WINDOW_SEC:
            bucket.popleft()
        if len(bucket) >= _RATE_LIMIT:
            return True
        bucket.append(now)
        return False


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

    ip = _client_ip(request)
    if _rate_limited(ip):
        raise HTTPException(status_code=429, detail="Too many submissions. Please try again later.")

    try:
        lead = MarketingWebsiteLead(
            lead_type=payload.lead_type,
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
            source_path=payload.source_path or str(request.headers.get("referer") or "")[:256],
            user_agent=(request.headers.get("user-agent") or "")[:512],
        )
        db.add(lead)
        db.commit()
        db.refresh(lead)
    except Exception as exc:
        logger.exception("marketing lead persist failed: %s", exc)
        db.rollback()
        raise HTTPException(status_code=500, detail="Unable to save your request right now.") from exc

    return normalize_success(
        data={
            "accepted": True,
            "lead_id": lead.id,
            "lead_type": lead.lead_type,
        },
    )
