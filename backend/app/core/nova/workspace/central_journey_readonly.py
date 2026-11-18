"""Owner-only, default-off Nova Central journey readiness endpoint.

No customer data store, agent dispatcher, background worker, payload references,
paid providers or synthetic fixtures are connected to this HTTP route.
"""
from __future__ import annotations

import os

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel

from app import auth
from app.auth import ROLE_ADMIN, UserContext, get_current_user_context, require_any_role

router = APIRouter(prefix="/central", tags=["nova-central-readonly"])


class CentralJourneyReadiness(BaseModel):
    mode: str = "read_only"
    integration_status: str = "not_connected"
    journeys: list = []
    approval_actions_enabled: bool = False
    customer_data_connected: bool = False


def _readiness_disabled() -> bool:
    # Exact true opt-in; never inherit a broad Nova or Growth Agent flag.
    return os.getenv("NOVA_CENTRAL_JOURNEY_READONLY_ENABLED", "").strip().lower() != "true"


@router.get("/journeys", response_model=CentralJourneyReadiness)
def list_central_journeys(
    request: Request,
    user: UserContext = Depends(get_current_user_context),
    _role_guard=Depends(require_any_role(ROLE_ADMIN)),
):
    """Expose only connection readiness, not fictional or actual journeys."""
    if _readiness_disabled():
        raise HTTPException(status_code=404, detail="Nova Central journey view unavailable")
    if (not user.user_id or not user.organization_id
            or user.organization_id == "global"
            or user.role != ROLE_ADMIN):
        raise HTTPException(status_code=403, detail="Organization owner required")
    # Defense in depth: a token issued before an organization transfer must
    # not silently gain access to a different organization's journey view.
    # Global auth already validated the signature, revocation and active role;
    # re-check signed tenant scope here before future journey reads are wired.
    authorization = request.headers.get("authorization", "")
    if authorization.lower().startswith("bearer "):
        token = authorization[7:].strip()
    else:
        token = request.cookies.get(auth.ADMIN_SESSION_COOKIE, "")
    if not token:
        raise HTTPException(status_code=401, detail="Authenticated session required")
    token_organization = auth._jwt_verify(token).get("organization_id")
    if not token_organization or token_organization != user.organization_id:
        raise HTTPException(status_code=403, detail="Session organization mismatch")
    return CentralJourneyReadiness()
