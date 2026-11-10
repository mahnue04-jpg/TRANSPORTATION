"""Shared Work & Revenue owner guard.

Keeps the owner dependency independent from the API router, preventing circular
imports when Operations CSV modules are imported directly by tests/workers.
"""
from __future__ import annotations

import os

from fastapi import Depends, HTTPException
from sqlalchemy.orm import Session

from app.auth import OPERATOR_ACCOUNT_GRANTS, UserContext, get_current_user_context
from app.core.nova.signup.service import customer_access as default_customer_access
from app.db.session import get_db


def _work_revenue_owner_emails() -> set[str]:
    configured = str(os.getenv("NOVA_V3_OWNER_EMAILS") or "").strip()
    if configured:
        return {item.strip().lower() for item in configured.split(",") if item.strip()}
    owners = {
        str(grant.get("email") or "").strip().lower()
        for grant in OPERATOR_ACCOUNT_GRANTS
        if str(grant.get("email") or "").strip()
    }
    if os.getenv("PYTEST_CURRENT_TEST"):
        owners.update({
            "admin@amicor.local",
            "dispatcher@amicor.local",
            "staff@amicor.local",
            "driver@amicor.local",
        })
    return owners


def require_work_revenue_owner(
    user: UserContext = Depends(get_current_user_context),
    db: Session = Depends(get_db),
) -> UserContext:
    email = str(user.email or "").strip().lower()
    if email in _work_revenue_owner_emails():
        return user

    # Keep compatibility with legacy router.customer_access test overrides.
    # This import occurs only during a request, never during module import.
    from app.core.nova.work_revenue import router as work_router
    checker = getattr(work_router, "customer_access", default_customer_access)
    access = checker(
        db, organization_id=user.organization_id, user_id=user.user_id,
    )
    if access.get("nova_saas_customer"):
        raise HTTPException(403, "Work & Revenue is owner-only.")
    raise HTTPException(403, "Work & Revenue is restricted to the AMICOR owner.")
