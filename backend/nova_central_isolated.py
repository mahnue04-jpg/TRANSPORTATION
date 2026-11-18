"""Isolated Nova Central *readiness-only* ASGI factory. Not a deployment entrypoint yet.

Never import app.main or the app.core.nova package: both contain application
wiring unsuitable for the dedicated zero-write validation service.
No startup hooks, migrations, account seeding, workers or provider transports.
"""
from __future__ import annotations

import os
import re
from urllib.parse import urlsplit

# FastAPI request/response annotation classes must be module globals, because
# FastAPI resolves postponed annotations from the endpoint's global namespace.
from fastapi import Request, Response


def _config() -> None:
    """Validate identifiers before importing database/auth modules."""
    test_mode = os.getenv("NOVA_CENTRAL_ISOLATED_TEST") == "1"
    if test_mode and (os.getenv("AMICOR_ENVIRONMENT") != "test"
                      or os.getenv("APP_ENV") != "test"
                      or os.getenv("RENDER", "").lower() in {"true", "1", "yes"}
                      or bool(os.getenv("RENDER_SERVICE_ID", "").strip())):
        raise RuntimeError("Disposable test mode cannot run on staging/Render")
    if os.getenv("AMICOR_ENVIRONMENT") != "staging" or os.getenv("APP_ENV") != "staging":
        # Only isolated unit tests may opt into the test environment.
        if not (os.getenv("NOVA_CENTRAL_ISOLATED_TEST") == "1"
                and os.getenv("AMICOR_ENVIRONMENT") == "test"
                and os.getenv("APP_ENV") == "test"):
            raise RuntimeError("Nova Central requires isolated staging environment")
    expected = os.getenv("NOVA_CENTRAL_APPROVED_COMMIT", "")
    actual = os.getenv("RENDER_GIT_COMMIT", "")
    if not re.fullmatch(r"[0-9a-f]{40}", expected) or expected != actual:
        raise RuntimeError("Nova Central commit pin missing or mismatched")
    if os.getenv("NOVA_CENTRAL_JOURNEY_READONLY_ENABLED", "").lower() == "true":
        raise RuntimeError("Nova Central readiness feature must start disabled")
    if os.getenv("NOVA_CENTRAL_JOURNEY_DATA_READ_ENABLED", "").lower() == "true":
        raise RuntimeError("Nova Central data preview must start disabled")

    database_url = os.getenv("DATABASE_URL", "")
    if test_mode:
        if not database_url.startswith("sqlite:///"):
            raise RuntimeError("test mode requires disposable SQLite")
        return

    # Allow only an independently provisioned PostgreSQL host/database.
    expected_host = os.getenv("NOVA_CENTRAL_EXPECTED_DB_HOST", "")
    expected_name = os.getenv("NOVA_CENTRAL_EXPECTED_DB_NAME", "")
    if not expected_host or not expected_name or expected_name != "nova_central_542_dispos":
        raise RuntimeError("approved isolated database identity is required")
    value = database_url.replace("postgresql+psycopg2://", "postgresql://", 1)
    p = urlsplit(value)
    if p.scheme != "postgresql" or p.hostname != expected_host or p.path != "/" + expected_name:
        raise RuntimeError("database target is not the isolated Nova Central database")


def create_app():
    """Build a minimal GET-only app with the real persisted-user auth dependencies.

    This first slice intentionally does NOT mount the journey preview or any
    generic Nova router. It cannot report active coordination or real journeys.
    """
    _config()
    from fastapi import Depends, FastAPI, HTTPException
    from app import auth
    from app.auth import ROLE_ADMIN, get_current_user_context, require_any_role

    app = FastAPI(title="Nova Central isolated readiness", docs_url=None, redoc_url=None,
                  openapi_url=None)

    @app.get("/health/live")
    def live():
        return {"status": "alive", "mode": "isolated_readiness"}

    @app.get("/api/nova/workspace/central/journeys",
             dependencies=[Depends(require_any_role(ROLE_ADMIN))])
    def readiness(request: Request, response: Response,
                  user=Depends(get_current_user_context)):
        if os.getenv("NOVA_CENTRAL_JOURNEY_READONLY_ENABLED", "").lower() != "true":
            raise HTTPException(status_code=404, detail="Nova Central journey view unavailable")
        if not user.user_id or not user.organization_id or user.organization_id == "global" or user.role != ROLE_ADMIN:
            raise HTTPException(status_code=403, detail="Organization owner required")
        authorization = request.headers.get("authorization", "")
        if authorization:
            if not authorization.lower().startswith("bearer ") or not authorization[7:].strip():
                raise HTTPException(status_code=401, detail="Invalid authorization header")
            token = authorization[7:].strip()
        else:
            token = request.cookies.get(auth.ADMIN_SESSION_COOKIE)
        if not token:
            raise HTTPException(status_code=401, detail="Authenticated session required")
        if auth._jwt_verify(token).get("organization_id") != user.organization_id:
            raise HTTPException(status_code=403, detail="Session organization mismatch")
        response.headers["Cache-Control"] = "private, no-store"
        response.headers["Vary"] = "Authorization, Cookie"
        return {"mode": "read_only", "integration_status": "not_connected",
                "journeys": [], "approval_actions_enabled": False,
                "customer_data_connected": False}

    return app
