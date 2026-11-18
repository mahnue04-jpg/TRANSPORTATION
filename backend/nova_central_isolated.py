"""Isolated Nova Central *readiness-only* ASGI factory. Not a deployment entrypoint yet.

Never import app.main or the app.core.nova package: both contain application
wiring unsuitable for the dedicated zero-write validation service.
No startup hooks, migrations, account seeding, workers or provider transports.
"""
from __future__ import annotations

import os
import re
import time
from urllib.parse import unquote, urlsplit

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

    # Staging must never silently use auth.py's ephemeral JWT key.
    # The signing key, issuer and audience must be separately provisioned
    # for the isolated service, with no production/shared secret reuse.
    jwt_secret = os.getenv("JWT_SECRET", "")
    legacy_secret = os.getenv("SECRET_KEY", "")
    if (len(jwt_secret) < 32 or jwt_secret != jwt_secret.strip()
            or legacy_secret and legacy_secret != jwt_secret
            or not os.getenv("JWT_ISSUER", "").strip()
            or not os.getenv("JWT_AUDIENCE", "").strip()):
        raise RuntimeError("Isolated staging JWT settings are missing or inconsistent")

    # Allow only an independently provisioned PostgreSQL host/database.
    expected_host = os.getenv("NOVA_CENTRAL_EXPECTED_DB_HOST", "").strip()
    expected_name = os.getenv("NOVA_CENTRAL_EXPECTED_DB_NAME", "").strip()
    expected_user = os.getenv("NOVA_CENTRAL_EXPECTED_DB_USER", "").strip()
    if (not expected_host or expected_name != "nova_central_542_dispos"
            or not expected_user):
        raise RuntimeError("approved isolated database identity is required")
    value = database_url.replace("postgresql+psycopg2://", "postgresql://", 1)
    try:
        p = urlsplit(value)
        actual_user = unquote(p.username or "")
        actual_host = p.hostname
        actual_port = p.port
    except ValueError as exc:
        raise RuntimeError("invalid isolated database address") from exc
    if (p.scheme != "postgresql" or actual_host != expected_host
            or p.path != "/" + expected_name or actual_user != expected_user
            or not p.password or p.query or p.fragment
            or (actual_port is not None and actual_port != 5432)):
        raise RuntimeError("database account or target is not the isolated Nova Central database")


def create_app():
    """Build a minimal GET-only app with the real persisted-user auth dependencies.

    This first slice intentionally does NOT mount the journey preview or any
    generic Nova router. It cannot report active coordination or real journeys.
    """
    _config()
    from types import SimpleNamespace

    from fastapi import Depends, FastAPI, HTTPException
    from sqlalchemy import select
    from app import auth
    from app.db.models import User
    from app.db.session import get_db

    app = FastAPI(title="Nova Central isolated readiness", docs_url=None, redoc_url=None,
                  openapi_url=None)

    @app.get("/health/live")
    def live():
        return {"status": "alive", "mode": "isolated_readiness"}

    def authenticated_owner(request: Request, db=Depends(get_db)):
        # Use the real signed JWT and persisted account/revocation model, but
        # SELECT only the eight columns needed for this read-only boundary.
        # This allows PostgreSQL column-level SELECT privileges and excludes
        # hashed_password, email, display_name and other private account data.
        authorization = request.headers.get("authorization", "")
        if authorization:
            if not authorization.lower().startswith("bearer ") or not authorization[7:].strip():
                raise HTTPException(status_code=401, detail="Invalid authorization header")
            token = authorization[7:].strip()
        else:
            token = request.cookies.get(auth.ADMIN_SESSION_COOKIE)
        if not token:
            raise HTTPException(status_code=401, detail="Authentication required")
        payload = auth._jwt_verify(token)
        # The shared verifier tolerates tokens without an expiry. The isolated
        # owner boundary must require an actual finite future expiration.
        exp = payload.get("exp")
        if isinstance(exp, bool) or not isinstance(exp, (int, float)) or not (
            time.time() < exp < time.time() + 86400
        ):
            raise HTTPException(status_code=401, detail="Session expiration invalid")
        uid = payload.get("sub")
        if not uid:
            raise HTTPException(status_code=401, detail="Token missing subject")
        fields = (
            User.id, User.role, User.authorized_roles, User.session_role,
            User.organization_id, User.auth_version, User.is_active,
        )
        row = db.execute(select(*fields).where(User.id == uid)).first()
        if row is None or not row.is_active:
            raise HTTPException(status_code=401, detail="Invalid or inactive user")
        if int(payload.get("auth_version", 0) or 0) != int(row.auth_version or 0):
            raise HTTPException(status_code=401, detail="Session invalidated")
        principal = SimpleNamespace(**row._mapping)
        authorized = auth.get_user_authorized_roles(principal)
        token_role = auth.normalize_role(payload.get("role"))
        role = auth.resolve_session_role(principal, payload)
        if token_role not in authorized or role not in authorized or role != auth.ROLE_ADMIN:
            raise HTTPException(status_code=403, detail="Organization owner required")
        if not row.organization_id or row.organization_id == "global":
            raise HTTPException(status_code=403, detail="Organization owner required")
        if payload.get("organization_id") != row.organization_id:
            raise HTTPException(status_code=403, detail="Session organization mismatch")
        return principal

    @app.get("/api/nova/workspace/central/journeys")
    def readiness(response: Response, user=Depends(authenticated_owner)):
        if os.getenv("NOVA_CENTRAL_JOURNEY_READONLY_ENABLED", "").lower() != "true":
            raise HTTPException(status_code=404, detail="Nova Central journey view unavailable")
        response.headers["Cache-Control"] = "private, no-store"
        response.headers["Vary"] = "Authorization, Cookie"
        return {"mode": "read_only", "integration_status": "not_connected",
                "journeys": [], "approval_actions_enabled": False,
                "customer_data_connected": False}

    return app
