"""Owner-only, default-off Nova Central journey readiness endpoint.

No customer data store, agent dispatcher, background worker, payload references,
paid providers or synthetic fixtures are connected to this HTTP route.
"""
from __future__ import annotations

import os

from fastapi import APIRouter, Depends, HTTPException, Request, Response
from sqlalchemy import inspect
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session
from pydantic import BaseModel, Field

from app import auth
from app.auth import ROLE_ADMIN, UserContext, get_current_user_context, require_any_role
from app.db.session import get_db
from app.core.nova.workspace.central_read_model import JOURNEY_READ_ROWS, list_journeys

router = APIRouter(prefix="/central", tags=["nova-central-readonly"])


class CentralJourneyStatus(BaseModel):
    correlation_id: str
    state: str
    assigned_agent: str
    owner_action: str
    revision: int


class CentralJourneyReadiness(BaseModel):
    mode: str = "read_only"
    integration_status: str = "not_connected"
    journeys: list[CentralJourneyStatus] = Field(default_factory=list)
    approval_actions_enabled: bool = False
    customer_data_connected: bool = False


def _readiness_disabled() -> bool:
    # Exact true opt-in; never inherit a broad Nova or Growth Agent flag.
    return os.getenv("NOVA_CENTRAL_JOURNEY_READONLY_ENABLED", "").strip().lower() != "true"


@router.get("/journeys", response_model=CentralJourneyReadiness)
def list_central_journeys(
    request: Request,
    response: Response,
    user: UserContext = Depends(get_current_user_context),
    _role_guard=Depends(require_any_role(ROLE_ADMIN)),
    db: Session = Depends(get_db),
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
    # Treat future journey metadata as private, even while the current response
    # intentionally has no connected customer records.
    response.headers["Cache-Control"] = "private, no-store"
    response.headers["Vary"] = "Authorization, Cookie"

    # An independent, default-off switch allows a disposable read-model
    # acceptance on STAGING/TEST only; production cannot opt in accidentally.
    if os.getenv("NOVA_CENTRAL_JOURNEY_DATA_READ_ENABLED", "").lower() != "true":
        return CentralJourneyReadiness()
    configured_environments = [
        value.strip().lower() for value in (
            os.getenv("AMICOR_ENVIRONMENT"), os.getenv("APP_ENV"),
        ) if value is not None
    ]
    # Any conflicting non-staging/test environment indicator blocks preview.
    if not configured_environments or any(
        value not in {"staging", "test"} for value in configured_environments
    ):
        raise HTTPException(status_code=503, detail="Journey read model unavailable")
    try:
        if not inspect(db.get_bind()).has_table(JOURNEY_READ_ROWS.name):
            raise HTTPException(status_code=503, detail="Journey read model unavailable")
        rows = list_journeys(
            db, authenticated_organization_id=user.organization_id,
            authenticated_role=user.role, limit=20,
        )
    except SQLAlchemyError as exc:
        raise HTTPException(status_code=503, detail="Journey read model unavailable") from exc
    return CentralJourneyReadiness(
        integration_status="read_model_preview",
        journeys=[CentralJourneyStatus(**row.__dict__) for row in rows],
        customer_data_connected=False,
    )
