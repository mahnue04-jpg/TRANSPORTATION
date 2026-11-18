"""Owner-only, default-off Nova Central journey readiness endpoint.

No customer data store, agent dispatcher, background worker, payload references,
paid providers or synthetic fixtures are connected to this HTTP route.
"""
from __future__ import annotations

import os

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

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
    return CentralJourneyReadiness()
