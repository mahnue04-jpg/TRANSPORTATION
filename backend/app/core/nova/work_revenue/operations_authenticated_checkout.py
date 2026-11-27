"""Authenticated checkout connector for the four Operations packages.

Public sales stay off unless both live-sales flags are exactly true. This
module never reads a price or email from the request body, and it does not
execute fulfillment.
"""

from __future__ import annotations

import os
import re

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.auth import UserContext, get_current_user_context
from app.core.nova.work_revenue.operations_customer_fulfillment import customer_fulfillment
from app.db.session import get_db

router = APIRouter(prefix="/api/nova/operations", tags=["nova-operations-checkout"])

AUTHENTICATED_PACKAGES = {
    "starter": {
        "label": "Starter Plan",
        "amount_cents": 999,
        "lane": "saas",
        "billing_plan_key": "starter",
    },
    "starter_49": {
        "label": "Starter Task",
        "amount_cents": 4900,
        "lane": "marketing",
        "billing_plan_key": "starter_49",
    },
    "launch_99": {
        "label": "Launch Operations",
        "amount_cents": 9900,
        "lane": "marketing",
        "billing_plan_key": "launch_99",
    },
    "business_299": {
        "label": "Business Operations",
        "amount_cents": 29900,
        "lane": "marketing",
        "billing_plan_key": "business_299",
    },
}

_ACCOUNT_ID = re.compile(r"^[A-Za-z0-9_-]{1,64}$")


class OperationsCheckoutRequest(BaseModel):
    package: str = Field(min_length=3, max_length=32)


def public_sales_enabled() -> bool:
    return (
        os.getenv("NOVA_STRIPE_LIVE_ENABLED") == "true"
        and os.getenv("NOVA_OPERATIONS_CUSTOMER_SALES_ENABLED") == "true"
    )


def require_verified_customer(db: Session, user: UserContext) -> UserContext:
    """Bind checkout to the signed-in account, never to a body field."""
    from app.db.models import User as PlatformUser

    user_id = str(getattr(user, "user_id", "") or "")
    email = str(getattr(user, "email", "") or "").strip()
    organization_id = str(getattr(user, "organization_id", "") or "")
    if (
        not _ACCOUNT_ID.fullmatch(user_id)
        or not _ACCOUNT_ID.fullmatch(organization_id)
        or "@" not in email
        or len(email) > 320
        or any(character.isspace() for character in email)
    ):
        raise HTTPException(status_code=403, detail="Verified customer account required")
    row = db.get(PlatformUser, user_id)
    row_email = str(getattr(row, "email", "") or "").strip()
    if (
        row is None
        or row.is_active is not True
        or row.is_verified is not True
        or row_email.casefold() != email.casefold()
        or str(getattr(row, "organization_id", "") or "") != organization_id
    ):
        raise HTTPException(status_code=403, detail="Verified customer account required")
    return user


def checkout_intent(package: str) -> dict:
    spec = AUTHENTICATED_PACKAGES.get(package)
    if spec is None:
        raise HTTPException(status_code=422, detail="Unknown Operations package")
    return {
        "package": package,
        "label": spec["label"],
        "amount_cents": spec["amount_cents"],
        "lane": spec["lane"],
        "authenticated": True,
        "sales_enabled": public_sales_enabled(),
        "stripe_session_created": False,
        "executes_work": False,
        "checkout_method": "POST",
        "checkout_path": "/api/nova/operations/checkout",
        "fulfillment": customer_fulfillment(package),
    }


def _with_session_flag(result: dict, package: str) -> dict:
    body = dict(result)
    body["stripe_session_created"] = bool(body.get("checkout_url") or body.get("checkout_session_id"))
    body["executes_work"] = False
    body["fulfillment"] = customer_fulfillment(package)
    return body


def start_saas_checkout(db: Session, user: UserContext):
    from app.core.nova.billing.service import BillingError, start_checkout

    try:
        result = start_checkout(db, user=user, plan_key="starter")
    except BillingError as exc:
        raise HTTPException(status_code=exc.status_code, detail=str(exc)) from exc
    return _with_session_flag(result, "starter")


def start_marketing_checkout(db: Session, user: UserContext, package: str, request: Request):
    from app.modules.marketing.models import MarketingWebsiteLead, ensure_marketing_schema
    from app.modules.marketing.routes import create_nova_agent_checkout

    email = str(user.email or "").strip()
    ensure_marketing_schema()
    lead = MarketingWebsiteLead(
        lead_type="anonymous_operations",
        status="new",
        contact_name=(email.split("@", 1)[0] or "Customer")[:128],
        work_email=email,
        consent=True,
        service_plan=package,
        message="Authenticated Operations checkout",
        lead_source="authenticated-checkout",
        source_path=f"nova-user:{user.user_id}"[:256],
        payment_status="pending",
    )
    db.add(lead)
    db.flush()
    try:
        created = create_nova_agent_checkout(lead.id, request, db)
    except HTTPException:
        db.rollback()
        raise
    return _with_session_flag(created, package)


def start_package_checkout(db: Session, user: UserContext, package: str, request: Request):
    if not public_sales_enabled():
        raise HTTPException(status_code=403, detail="Public Operations sales are disabled")
    spec = AUTHENTICATED_PACKAGES.get(package)
    if spec is None:
        raise HTTPException(status_code=422, detail="Unknown Operations package")
    if spec["lane"] == "saas":
        return start_saas_checkout(db, user)
    return start_marketing_checkout(db, user, package, request)


@router.get("/checkout")
def get_operations_checkout_intent(
    package: str,
    user: UserContext = Depends(get_current_user_context),
    db: Session = Depends(get_db),
):
    require_verified_customer(db, user)
    return checkout_intent(package)


@router.get("/fulfillment")
def get_operations_fulfillment(
    package: str,
    user: UserContext = Depends(get_current_user_context),
    db: Session = Depends(get_db),
):
    require_verified_customer(db, user)
    if package not in AUTHENTICATED_PACKAGES:
        raise HTTPException(status_code=422, detail="Unknown Operations package")
    report = customer_fulfillment(package)
    report["authenticated"] = True
    report["sales_enabled"] = public_sales_enabled()
    return report


@router.post("/checkout")
def post_operations_checkout(
    body: OperationsCheckoutRequest,
    request: Request,
    user: UserContext = Depends(get_current_user_context),
    db: Session = Depends(get_db),
):
    if body.package not in AUTHENTICATED_PACKAGES:
        raise HTTPException(status_code=422, detail="Unknown Operations package")
    require_verified_customer(db, user)
    if not public_sales_enabled():
        raise HTTPException(status_code=403, detail="Public Operations sales are disabled")
    return start_package_checkout(db, user, body.package, request)
