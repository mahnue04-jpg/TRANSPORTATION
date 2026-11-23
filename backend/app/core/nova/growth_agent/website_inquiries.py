"""Read-only owner inbox interface for website-originated inquiries.

No Cloudflare credentials or live source are configured here. A reviewed
server-side adapter must be supplied before this endpoint can show real data.
Never source credentials or a role from the browser request.
"""
from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field
from sqlalchemy.orm import Session
from app.db.session import get_db
from app.core.nova.growth_agent.flags import customer_inquiry_handoff_enabled, synthetic_inquiry_handoff_enabled
from app.core.nova.growth_agent.service import GrowthAgentService

from fastapi import APIRouter, Depends, HTTPException

from app.auth import UserContext
from app.core.nova.growth_agent.errors import GrowthAgentError
from app.core.nova.growth_agent.tenant import require_growth_owner, resolve_org

router = APIRouter(tags=["nova-growth-agent"])

# Deliberately disconnected until a tenant-scoped, server-side KV adapter
# has passed isolated staging acceptance. The dependency is replaceable in
# tests; no public input can select a data source.
def get_website_inquiry_source() -> Any:
    from app.core.nova.growth_agent.website_kv_source import configured_website_source

    # Explicit environment gate; unconfigured instances return None.
    return configured_website_source()


def website_inquiries(
    organization_id: str | None = None,
    user: UserContext = Depends(require_growth_owner),
    source: Any = Depends(get_website_inquiry_source),
) -> dict[str, Any]:
    try:
        organization = resolve_org(user, organization_id)
    except GrowthAgentError as exc:
        raise HTTPException(status_code=exc.http_status, detail=exc.message) from exc

    if source is None:
        return {"state": "unavailable", "source_system": "cloudflare_amicor_leads",
                "inquiries": [], "complete": False}
    try:
        result = source.read(organization)
    except Exception:
        # No third-party exception, tokens, or customer fields in responses.
        return {"state": "unavailable", "source_system": "cloudflare_amicor_leads",
                "inquiries": [], "complete": False}
    if not isinstance(result, dict) or result.get("state") != "available" or result.get("complete") is not True:
        return {"state": "stale", "source_system": "cloudflare_amicor_leads",
                "inquiries": [], "complete": False}
    rows = result.get("inquiries")
    if not isinstance(rows, list) or len(rows) > 100:
        return {"state": "stale", "source_system": "cloudflare_amicor_leads",
                "inquiries": [], "complete": False}
    output = []
    seen = set()
    for row in rows:
        if not isinstance(row, dict) or row.get("source_system") != "cloudflare_amicor_leads":
            return {"state": "stale", "source_system": "cloudflare_amicor_leads",
                    "inquiries": [], "complete": False}
        source_key = row.get("source_key")
        if not isinstance(source_key, str) or not source_key.startswith("lead:") or source_key in seen:
            if isinstance(source_key, str) and source_key in seen:
                continue
            return {"state": "stale", "source_system": "cloudflare_amicor_leads",
                    "inquiries": [], "complete": False}
        seen.add(source_key)
        # Explicit projection: never return adapter secrets, raw response,
        # webhook metadata, or arbitrary user-supplied fields.
        output.append({
            "source_system": "cloudflare_amicor_leads",
            "source_key": source_key,
            "reference_id": row.get("reference_id") if isinstance(row.get("reference_id"), str) else None,
            "received_at": str(row.get("received_at", ""))[:40],
            "name": str(row.get("name", ""))[:120],
            "company": str(row.get("company", ""))[:160],
            "email": str(row.get("email", ""))[:254],
            "product": str(row.get("product", ""))[:80],
            "message": str(row.get("message", ""))[:2000],
            "consent": row.get("consent") is True,
            "is_synthetic": row.get("is_synthetic") is True,
            "status": "needs_review",
        })
    return {"synthetic_handoff_enabled": synthetic_inquiry_handoff_enabled(),
            "customer_handoff_enabled": customer_inquiry_handoff_enabled(),
            "state": "available", "source_system": "cloudflare_amicor_leads",
            "inquiries": output, "complete": True}


router.add_api_route("/website-inquiries", website_inquiries, methods=["GET"])


class InquiryHandoff(BaseModel):
    source_key: str = Field(min_length=6, max_length=512)


@router.post("/website-inquiries/handoff")
def approve_inquiry_handoff(
    body: InquiryHandoff,
    user: UserContext = Depends(require_growth_owner),
    source: Any = Depends(get_website_inquiry_source),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    synthetic_enabled = synthetic_inquiry_handoff_enabled()
    customer_enabled = customer_inquiry_handoff_enabled()
    if not (synthetic_enabled or customer_enabled):
        raise HTTPException(404, "Website inquiry handoff is disabled")
    snapshot = website_inquiries(None, user, source)
    if not snapshot["complete"]:
        raise HTTPException(503, "Inquiry source unavailable")
    row = next((r for r in snapshot["inquiries"] if r["source_key"] == body.source_key), None)
    if row is None:
        raise HTTPException(404, "Inquiry not found")
    eligible = synthetic_enabled if row["is_synthetic"] else customer_enabled
    if not eligible or not row["consent"]:
        raise HTTPException(409, "Handoff requires an enabled inquiry type and recorded consent")
    return GrowthAgentService(db).handoff_website_inquiry(resolve_org(user), row, user.user_id)
