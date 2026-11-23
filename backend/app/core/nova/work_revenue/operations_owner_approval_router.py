"""Private, disabled-by-default Operations subscription owner decisions.

Mounts beneath the existing Work & Revenue router, inheriting Nova access and
owner dependencies. Only synthetic staging lead/task decisions; no execution,
Stripe checkout, delivery, or public endpoints.
"""
from __future__ import annotations

import os
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.auth import UserContext, get_current_user_context
from app.db.session import get_db
from .operations_package_usage_ledger import AllowanceBlocked
from .operations_subscription_approvals import record_staging_owner_scope_decision

router = APIRouter(prefix="/operations/subscription-approvals", tags=["operations-staging-owner"])


class OwnerScopeDecision(BaseModel):
    engagement_id: str = Field(min_length=1, max_length=32)
    task_id: str = Field(min_length=1, max_length=32)
    lead_id: str = Field(min_length=1, max_length=36)
    task_fingerprint: str = Field(pattern=r"^[0-9a-f]{64}$")
    decision: Literal["APPROVED", "REJECTED", "REVOKED"]


def record_owner_scope_decision_endpoint(
    payload: OwnerScopeDecision,
    *,
    user: UserContext,
    db: Session,
) -> dict:
    """Internal handler, accepts authenticated context from FastAPI only.

    Explicit request/feature gate ensures importing the route is harmless.
    """
    if (
        os.getenv("NOVA_OPERATIONS_SUBSCRIPTION_OWNER_API_STAGING_ENABLED") != "true"
        or os.getenv("APP_ENV") != "staging"
        or os.getenv("AMICOR_ENVIRONMENT") != "staging"
        or os.getenv("NOVA_OPERATIONS_CUSTOMER_SALES_ENABLED", "").lower() == "true"
        or os.getenv("NOVA_STRIPE_LIVE_ENABLED", "").lower() == "true"
    ):
        raise HTTPException(503, "Operations owner approval API is disabled")
    organization_id = str(user.organization_id or "")
    if not organization_id or str(user.role or "").lower() not in {"admin", "super_admin_support"}:
        raise HTTPException(403, "Authenticated owner required")
    try:
        result = record_staging_owner_scope_decision(
            db, authenticated_user=user, organization_id=organization_id,
            engagement_id=payload.engagement_id, task_id=payload.task_id,
            lead_id=payload.lead_id,
            task_fingerprint=payload.task_fingerprint,
            decision=payload.decision,
        )
    except AllowanceBlocked as exc:
        raise HTTPException(409, "Owner scope decision unavailable or not authorized") from exc
    return {"decision": result["decision"], "event_id": result["event_id"],
            "task_id": result["task_id"], "executed": False, "delivered": False}


@router.post("/decision")
def owner_subscription_scope_decision(
    payload: OwnerScopeDecision,
    user: UserContext = Depends(get_current_user_context),
    db: Session = Depends(get_db),
):
    return record_owner_scope_decision_endpoint(payload, user=user, db=db)
