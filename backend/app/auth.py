"""
Auth system: JWT access tokens, refresh tokens, password hashing, in-memory rate limiting.

Endpoints (all under /api/auth):
  POST /register   — create account
  POST /login      — password login → {access_token, refresh_token}
  POST /refresh    — exchange refresh token → new access token
  POST /logout     — revoke refresh token
  POST /switch-role — validate and issue JWT for an authorized workspace role
  GET  /me         — return current user info (requires Bearer token)
  GET  /session    — return active JWT session role claims (requires Bearer token)
"""
import hashlib
import json
import logging
import os
import re
import secrets
import time
from collections import defaultdict
from datetime import datetime, timedelta, timezone
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Request, Response, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from pydantic import BaseModel, field_validator
from sqlalchemy import func, inspect, or_, text
from sqlalchemy.orm import Session

from app.db.session import get_db

logger = logging.getLogger("amicor.auth")

ROLE_ADMIN = "admin"
ROLE_DISPATCHER = "dispatcher"
ROLE_DRIVER = "driver"
ROLE_PROVIDER = "provider"
ROLE_RIDER = "rider"
ROLE_STAFF = "staff"
ROLE_ANALYTICS_READONLY = "analytics_readonly"
ROLE_SUPER_ADMIN_SUPPORT = "super_admin_support"
ROLE_COMPLIANCE_OFFICER = "compliance_officer"
ROLE_SUPERVISOR = "supervisor"
ROLE_DRIVER_SUPPORT = "driver_support"
ROLE_MEDICAL_COORDINATOR = "medical_coordinator"
VALID_ROLES = {
    ROLE_ADMIN,
    ROLE_DISPATCHER,
    ROLE_DRIVER,
    ROLE_PROVIDER,
    ROLE_RIDER,
    ROLE_STAFF,
    ROLE_ANALYTICS_READONLY,
    ROLE_SUPER_ADMIN_SUPPORT,
    ROLE_COMPLIANCE_OFFICER,
    ROLE_SUPERVISOR,
    ROLE_DRIVER_SUPPORT,
    ROLE_MEDICAL_COORDINATOR,
}
DEFAULT_ROLE = ROLE_STAFF

DEFAULT_ORGANIZATION_NAME = os.getenv("DEFAULT_ORGANIZATION_NAME", "Amicor Health")
SEED_PASSWORD = os.getenv("AMICOR_SEED_PASSWORD", "Amicor123!")
SEED_USERS: tuple[dict[str, str], ...] = (
    {
        "email": "admin@amicor.local",
        "display_name": "Amicor Admin",
        "role": ROLE_ADMIN,
    },
    {
        "email": "dispatcher@amicor.local",
        "display_name": "Amicor Dispatcher",
        "role": ROLE_DISPATCHER,
    },
    {
        "email": "driver@amicor.local",
        "display_name": "Amicor Driver",
        "role": ROLE_DRIVER,
    },
    {
        "email": "rider@amicor.local",
        "display_name": "Amicor Rider",
        "role": ROLE_RIDER,
    },
    {
        "email": "provider@amicor.local",
        "display_name": "Amicor Provider",
        "role": ROLE_PROVIDER,
    },
    {
        "email": "compliance@amicor.local",
        "display_name": "Amicor Compliance Officer",
        "role": ROLE_COMPLIANCE_OFFICER,
    },
    {
        "email": "supervisor@amicor.local",
        "display_name": "Amicor Supervisor",
        "role": ROLE_SUPERVISOR,
    },
    {
        "email": "driversupport@amicor.local",
        "display_name": "Amicor Driver Support",
        "role": ROLE_DRIVER_SUPPORT,
    },
    {
        "email": "medical@amicor.local",
        "display_name": "Amicor Medical Coordinator",
        "role": ROLE_MEDICAL_COORDINATOR,
    },
    {
        "email": "staff@amicor.local",
        "display_name": "Amicor Staff",
        "role": ROLE_STAFF,
        "authorized_roles": (ROLE_STAFF,),
    },
)

OPERATOR_ACCOUNT_GRANTS: tuple[dict[str, Any], ...] = (
    {
        "display_name": "saye monibah",
        "email": "mahnue04@gmail.com",
        "primary_role": ROLE_ADMIN,
        "authorized_roles": (ROLE_ADMIN, ROLE_DISPATCHER, ROLE_STAFF),
    },
)

WORKSPACE_SWITCHABLE_ROLES = frozenset(
    {
        ROLE_ADMIN,
        ROLE_DISPATCHER,
        ROLE_STAFF,
        ROLE_SUPERVISOR,
        ROLE_DRIVER,
        ROLE_PROVIDER,
        ROLE_RIDER,
        ROLE_COMPLIANCE_OFFICER,
        ROLE_DRIVER_SUPPORT,
        ROLE_MEDICAL_COORDINATOR,
        ROLE_ANALYTICS_READONLY,
    }
)

ROLE_DEFAULT_AUTHORIZED: dict[str, tuple[str, ...]] = {
    ROLE_ADMIN: (ROLE_ADMIN, ROLE_DISPATCHER, ROLE_STAFF, ROLE_SUPERVISOR, ROLE_ANALYTICS_READONLY),
    ROLE_SUPER_ADMIN_SUPPORT: (ROLE_ADMIN, ROLE_DISPATCHER, ROLE_STAFF, ROLE_SUPERVISOR, ROLE_ANALYTICS_READONLY),
    ROLE_DISPATCHER: (ROLE_DISPATCHER, ROLE_STAFF),
    ROLE_SUPERVISOR: (ROLE_SUPERVISOR, ROLE_DISPATCHER, ROLE_STAFF),
    ROLE_STAFF: (ROLE_STAFF,),
    ROLE_DRIVER: (ROLE_DRIVER,),
    ROLE_PROVIDER: (ROLE_PROVIDER,),
    ROLE_RIDER: (ROLE_RIDER,),
    ROLE_COMPLIANCE_OFFICER: (ROLE_COMPLIANCE_OFFICER, ROLE_STAFF),
    ROLE_DRIVER_SUPPORT: (ROLE_DRIVER_SUPPORT, ROLE_STAFF),
    ROLE_MEDICAL_COORDINATOR: (ROLE_MEDICAL_COORDINATOR, ROLE_STAFF),
    ROLE_ANALYTICS_READONLY: (ROLE_ANALYTICS_READONLY,),
}


def normalize_role(role: str | None) -> str:
    value = str(role or DEFAULT_ROLE).strip().lower()
    return value if value in VALID_ROLES else DEFAULT_ROLE


def get_effective_role(role: str | None) -> str:
    """Return the runtime role, allowing an explicit test override via env vars.

    Override is enabled only when AMICOR_ENABLE_TEST_ROLE_OVERRIDE=1 and a valid
    AMICOR_FORCE_TEST_ROLE is provided.
    """
    base_role = normalize_role(role)
    if os.getenv("AMICOR_ENABLE_TEST_ROLE_OVERRIDE", "0").strip() != "1":
        return base_role

    forced_role = normalize_role(os.getenv("AMICOR_FORCE_TEST_ROLE", ""))
    return forced_role if forced_role in VALID_ROLES else base_role


def _serialize_authorized_roles(roles: set[str] | list[str] | tuple[str, ...]) -> str:
    normalized = sorted({normalize_role(role) for role in roles if normalize_role(role) in VALID_ROLES})
    return json.dumps(normalized)


def _deserialize_authorized_roles(raw: str | None) -> list[str]:
    if not raw:
        return []
    try:
        parsed = json.loads(raw)
    except Exception:
        return []
    if not isinstance(parsed, list):
        return []
    return sorted({normalize_role(item) for item in parsed if normalize_role(item) in VALID_ROLES})


def get_user_authorized_roles(user: Any) -> set[str]:
    stored = _deserialize_authorized_roles(getattr(user, "authorized_roles", None))
    if stored:
        return set(stored)
    primary = normalize_role(getattr(user, "role", None))
    return {primary}


def resolve_session_role(user: Any, token_payload: dict[str, Any] | None = None) -> str:
    authorized = get_user_authorized_roles(user)
    token_role = normalize_role((token_payload or {}).get("role"))
    if token_role in authorized:
        return token_role
    persisted = normalize_role(getattr(user, "session_role", None))
    if persisted in authorized:
        return persisted
    primary = normalize_role(getattr(user, "role", None))
    if primary in authorized:
        return primary
    return DEFAULT_ROLE


def _access_token_payload(user: Any, session_role: str | None = None) -> dict[str, Any]:
    role = normalize_role(session_role or getattr(user, "session_role", None) or getattr(user, "role", None))
    authorized = get_user_authorized_roles(user)
    if role not in authorized:
        role = normalize_role(getattr(user, "role", None))
    return {
        "sub": user.id,
        "email": user.email,
        "role": role,
        "organization_id": getattr(user, "organization_id", None),
    }


def apply_operator_role_grants() -> list[dict[str, str]]:
    """Grant authorized workspace roles to existing production operator accounts."""
    from app.db.models import User as UserModel
    from app.db.session import SessionLocal

    ensure_auth_schema()
    db: Session = SessionLocal()
    updated: list[dict[str, str]] = []
    try:
        for grant in OPERATOR_ACCOUNT_GRANTS:
            display_name = str(grant.get("display_name") or "").strip().lower()
            email_hint = str(grant.get("email") or "").strip().lower()
            query = db.query(UserModel)
            filters = []
            if display_name:
                filters.append(func.lower(UserModel.display_name) == display_name)
                filters.append(func.lower(UserModel.display_name).like(f"%{display_name}%"))
            if email_hint:
                filters.append(func.lower(UserModel.email) == email_hint)
            if not filters:
                continue
            rows = query.filter(or_(*filters)).all()
            for user in rows:
                primary_role = normalize_role(grant.get("primary_role") or getattr(user, "role", None))
                authorized = {
                    normalize_role(item)
                    for item in (grant.get("authorized_roles") or ())
                    if normalize_role(item) in VALID_ROLES
                }
                authorized.add(primary_role)
                user.role = primary_role
                user.authorized_roles = _serialize_authorized_roles(authorized)
                current_session = normalize_role(getattr(user, "session_role", None))
                if current_session not in authorized:
                    user.session_role = primary_role
                updated.append(
                    {
                        "email": user.email,
                        "display_name": user.display_name or "",
                        "primary_role": primary_role,
                        "authorized_roles": ",".join(sorted(authorized)),
                    }
                )
        if updated:
            db.commit()
        return updated
    finally:
        db.close()


def ensure_auth_schema() -> None:
    """Apply lightweight auth schema upgrades for existing deployments."""
    from app.db.session import engine

    inspector = inspect(engine)
    if "platform_users" not in inspector.get_table_names():
        return

    columns = {col["name"] for col in inspector.get_columns("platform_users")}
    with engine.begin() as conn:
        auth_columns = {
            "role": "VARCHAR(32) NOT NULL DEFAULT 'staff'",
            "organization_name": "VARCHAR(128)",
            "organization_id": "VARCHAR(36)",
            "authorized_roles": "VARCHAR(512)",
            "session_role": "VARCHAR(32)",
        }
        for column_name, column_type in auth_columns.items():
            if column_name in columns:
                continue
            savepoint = f"auth_schema_{column_name}"[:60]
            try:
                if conn.dialect.name == "postgresql":
                    conn.execute(text(f"SAVEPOINT {savepoint}"))
                conn.execute(text(f"ALTER TABLE platform_users ADD COLUMN {column_name} {column_type}"))
                if conn.dialect.name == "postgresql":
                    conn.execute(text(f"RELEASE SAVEPOINT {savepoint}"))
            except Exception:
                if conn.dialect.name == "postgresql":
                    conn.execute(text(f"ROLLBACK TO SAVEPOINT {savepoint}"))
                logger.exception("ensure_auth_schema_add_column_failed column=%s", column_name)


def seed_default_users() -> list[dict[str, str]]:
    """Ensure baseline test users exist and return seeded account metadata."""
    from app.db.models import User as UserModel
    from app.db.session import SessionLocal
    from app.modules.health_isf.models import ensure_health_isf_schema
    from app.modules.health_isf import service as health_isf_service

    ensure_auth_schema()
    ensure_health_isf_schema()
    db: Session = SessionLocal()
    created: list[dict[str, str]] = []
    synced = 0
    try:
        default_org = None
        try:
            default_org = health_isf_service._get_or_create_default_org(db)
            try:
                health_isf_service.ensure_operational_bootstrap(db, organization_id=default_org.id)
            except Exception as bootstrap_exc:
                logger.warning(
                    "Operational bootstrap skipped during auth seed: %s",
                    bootstrap_exc,
                    exc_info=True,
                )
        except Exception as org_exc:
            logger.warning("Default org lookup failed during auth seed: %s", org_exc, exc_info=True)

        for user_seed in SEED_USERS:
            email = user_seed["email"].strip().lower()
            existing = db.query(UserModel).filter(UserModel.email == email).first()
            if existing:
                existing.role = normalize_role(user_seed.get("role"))
                seed_role = normalize_role(user_seed.get("role"))
                seed_authorized = user_seed.get("authorized_roles") or ROLE_DEFAULT_AUTHORIZED.get(seed_role, (seed_role,))
                existing.authorized_roles = _serialize_authorized_roles(seed_authorized)
                existing.session_role = normalize_role(existing.session_role or seed_role)
                existing.organization_name = DEFAULT_ORGANIZATION_NAME
                if default_org is not None:
                    existing.organization_id = default_org.id
                existing.hashed_password = hash_password(SEED_PASSWORD)
                existing.is_active = True
                synced += 1
                continue

            user = UserModel(
                email=email,
                hashed_password=hash_password(SEED_PASSWORD),
                display_name=user_seed.get("display_name"),
                role=normalize_role(user_seed.get("role")),
                authorized_roles=_serialize_authorized_roles(
                    user_seed.get("authorized_roles")
                    or ROLE_DEFAULT_AUTHORIZED.get(normalize_role(user_seed.get("role")), (normalize_role(user_seed.get("role")),))
                ),
                session_role=normalize_role(user_seed.get("role")),
                organization_name=DEFAULT_ORGANIZATION_NAME,
                organization_id=default_org.id if default_org is not None else None,
                is_active=True,
                is_verified=True,
            )
            db.add(user)
            created.append({
                "email": email,
                "role": user.role,
            })

        db.commit()
        logger.info(
            "Auth seed complete: created=%s synced=%s password_source=AMICOR_SEED_PASSWORD",
            len(created),
            synced,
        )
        operator_updates = apply_operator_role_grants()
        if operator_updates:
            logger.info("Operator role grants applied: %s", operator_updates)
        return created
    finally:
        db.close()


def ensure_user_organization(db: Session, user: Any) -> str | None:
    """Backfill organization scope for legacy accounts missing tenant assignment."""
    current_org = getattr(user, "organization_id", None)
    try:
        from app.modules.health_isf import service as health_isf_service

        default_org = health_isf_service._get_or_create_default_org(db)
        if not str(current_org or "").strip():
            user.organization_id = default_org.id
        if not getattr(user, "organization_name", None):
            user.organization_name = DEFAULT_ORGANIZATION_NAME
        db.commit()
        db.refresh(user)
        return str(getattr(user, "organization_id", None) or default_org.id)
    except Exception as exc:
        logger.warning("Failed to ensure user organization for %s: %s", getattr(user, "id", "unknown"), exc)
        try:
            db.rollback()
        except Exception:
            pass
        return str(current_org) if current_org else None


def _build_org_code_base(name: str) -> str:
    raw = re.sub(r"[^A-Za-z0-9]+", "-", name.strip().upper()).strip("-")
    collapsed = re.sub(r"-+", "-", raw)
    if not collapsed:
        return "AMICOR-TENANT"
    return collapsed[:56]


def _resolve_registration_organization(db: Session, organization_name: str | None) -> tuple[str, str]:
    from app.modules.health_isf.models import HealthISFOrganization
    from app.modules.health_isf.models import ensure_health_isf_schema

    ensure_health_isf_schema()

    normalized_name = (organization_name or "").strip() or DEFAULT_ORGANIZATION_NAME
    existing = (
        db.query(HealthISFOrganization)
        .filter(func.lower(HealthISFOrganization.name) == normalized_name.lower())
        .first()
    )
    if existing:
        return str(existing.id), str(existing.name)

    if normalized_name.lower() == DEFAULT_ORGANIZATION_NAME.lower():
        default_org = db.query(HealthISFOrganization).filter(HealthISFOrganization.code == "AMICOR-DEFAULT").first()
        if default_org:
            return str(default_org.id), str(default_org.name)

    code_base = _build_org_code_base(normalized_name)
    code_candidate = code_base
    suffix = 1
    while db.query(HealthISFOrganization).filter(HealthISFOrganization.code == code_candidate).first() is not None:
        code_candidate = f"{code_base[:52]}-{suffix:03d}"
        suffix += 1

    org = HealthISFOrganization(
        name=normalized_name,
        code=code_candidate,
        is_active=True,
    )
    db.add(org)
    db.flush()
    return str(org.id), str(org.name)

# ── Configuration ──────────────────────────────────────────────────────────────
SECRET_KEY = os.getenv("SECRET_KEY", "")
JWT_SECRET = os.getenv("JWT_SECRET", "")
_ALGORITHM = "HS256"
ACCESS_TOKEN_EXPIRE_MINUTES = int(os.getenv("ACCESS_TOKEN_EXPIRE_MINUTES", "60"))
REFRESH_TOKEN_EXPIRE_DAYS = int(os.getenv("REFRESH_TOKEN_EXPIRE_DAYS", "7"))
JWT_ISSUER = os.getenv("JWT_ISSUER", "").strip()
JWT_AUDIENCE = os.getenv("JWT_AUDIENCE", "").strip()

if SECRET_KEY and JWT_SECRET and SECRET_KEY != JWT_SECRET:
    logger.warning(
        "SECRET_KEY and JWT_SECRET differ; using JWT_SECRET for token signing and verification."
    )

TOKEN_SIGNING_SECRET = (JWT_SECRET or SECRET_KEY).strip()

# Warn if no secret key configured
if not TOKEN_SIGNING_SECRET:
    _fallback = secrets.token_hex(32)
    TOKEN_SIGNING_SECRET = _fallback # type: ignore
    logger.warning(
        "JWT_SECRET/SECRET_KEY not set — using ephemeral key. Tokens will be invalid after restart. "
        "Set JWT_SECRET (or SECRET_KEY) env var in production."
    )

# Keep SECRET_KEY aligned for compatibility with modules importing it directly.
SECRET_KEY = TOKEN_SIGNING_SECRET

# ── JWT (pure stdlib — no extra deps) ─────────────────────────────────────────
import base64
import hmac
import json as _json


def _b64url_encode(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode()


def _b64url_decode(s: str) -> bytes:
    pad = 4 - len(s) % 4
    return base64.urlsafe_b64decode(s + "=" * (pad % 4))


def _jwt_sign(payload: dict) -> str: # type: ignore
    header = _b64url_encode(_json.dumps({"alg": "HS256", "typ": "JWT"}).encode())
    body   = _b64url_encode(_json.dumps(payload).encode())
    sig = hmac.new(TOKEN_SIGNING_SECRET.encode(), f"{header}.{body}".encode(), hashlib.sha256).digest()
    return f"{header}.{body}.{_b64url_encode(sig)}"


def _jwt_verify(token: str) -> dict: # type: ignore
    try:
        header_b64, body_b64, sig_b64 = token.split(".")
    except ValueError:
        raise HTTPException(status_code=401, detail="Invalid token format")
    expected_sig = hmac.new(
        TOKEN_SIGNING_SECRET.encode(), f"{header_b64}.{body_b64}".encode(), hashlib.sha256
    ).digest()
    if not hmac.compare_digest(expected_sig, _b64url_decode(sig_b64)):
        raise HTTPException(status_code=401, detail="Token signature invalid")
    try:
        payload = _json.loads(_b64url_decode(body_b64))
    except Exception:
        raise HTTPException(status_code=401, detail="Token payload invalid")
    exp = payload.get("exp")
    if exp and time.time() > exp:
        raise HTTPException(status_code=401, detail="Token expired")
    if JWT_ISSUER and payload.get("iss") != JWT_ISSUER:
        raise HTTPException(status_code=401, detail="Token issuer invalid")
    if JWT_AUDIENCE and payload.get("aud") != JWT_AUDIENCE:
        raise HTTPException(status_code=401, detail="Token audience invalid")
    return payload


def create_access_token(data: dict) -> str: # type: ignore
    payload = {**data, "exp": time.time() + ACCESS_TOKEN_EXPIRE_MINUTES * 60} # type: ignore
    if JWT_ISSUER:
        payload["iss"] = JWT_ISSUER
    if JWT_AUDIENCE:
        payload["aud"] = JWT_AUDIENCE
    return _jwt_sign(payload)


def create_refresh_token() -> str:
    """Return a cryptographically random opaque refresh token."""
    return secrets.token_urlsafe(48)


def _hash_token(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


# ── Password hashing (PBKDF2-HMAC-SHA256, stdlib) ─────────────────────────────

def hash_password(password: str) -> str:
    salt = secrets.token_hex(16)
    dk = hashlib.pbkdf2_hmac("sha256", password.encode(), salt.encode(), 260_000)
    return f"pbkdf2$260000${salt}${dk.hex()}"


def verify_password(password: str, hashed: str) -> bool:
    try:
        _, iterations, salt, stored = hashed.split("$")
        dk = hashlib.pbkdf2_hmac("sha256", password.encode(), salt.encode(), int(iterations))
        return hmac.compare_digest(dk.hex(), stored)
    except Exception:
        return False


# ── Rate limiting: per-IP sliding window ──────────────────────────────────────
_RATE_WINDOW_S = 60
_RATE_LIMIT_AUTH = int(os.getenv("RATE_LIMIT_AUTH", "20"))   # auth endpoints / minute
_RATE_LIMIT_CHAT = int(os.getenv("RATE_LIMIT_CHAT", "60"))   # chat endpoints / minute
_rate_buckets: dict[str, list[float]] = defaultdict(list)


def check_rate_limit(key: str, limit: int, window_s: int = _RATE_WINDOW_S) -> None:
    now = time.monotonic()
    if os.getenv("TESTING"):
        return
    cutoff = now - window_s
    bucket = _rate_buckets[key]
    while bucket and bucket[0] < cutoff:
        bucket.pop(0)
    if len(bucket) >= limit:
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail=f"Rate limit exceeded — max {limit} requests per {window_s}s.",
            headers={"Retry-After": str(window_s)},
        )
    bucket.append(now)


def rate_limit_ip(request: Request, limit: int = _RATE_LIMIT_CHAT) -> None:
    ip = request.headers.get("X-Forwarded-For", request.client.host if request.client else "unknown")
    check_rate_limit(f"ip:{ip}", limit)


# ── Bearer token extractor ─────────────────────────────────────────────────────
_bearer = HTTPBearer(auto_error=False)
ADMIN_SESSION_COOKIE = "amicor_admin_session"


def _cookie_secure(request: Request) -> bool:
    forwarded = str(request.headers.get("x-forwarded-proto", "") or "").split(",")[0].strip().lower()
    return forwarded == "https" or str(request.url.scheme).lower() == "https"


def set_admin_session_cookie(response: Response, request: Request, token: str) -> None:
    response.set_cookie(
        key=ADMIN_SESSION_COOKIE,
        value=token,
        httponly=True,
        secure=_cookie_secure(request),
        samesite="lax",
        max_age=ACCESS_TOKEN_EXPIRE_MINUTES * 60,
        path="/",
    )


def clear_admin_session_cookie(response: Response) -> None:
    response.delete_cookie(key=ADMIN_SESSION_COOKIE, path="/")


def extract_access_token(
    creds: HTTPAuthorizationCredentials | None,
    request: Request | None = None,
) -> str | None:
    if creds and creds.credentials:
        return creds.credentials
    if request is not None:
        cookie = request.cookies.get(ADMIN_SESSION_COOKIE)
        if cookie:
            return cookie
    return None


def get_current_user_id(
    request: Request,
    creds: HTTPAuthorizationCredentials | None = Depends(_bearer),
) -> str | None:
    """Return user_id from JWT Bearer token or HttpOnly session cookie."""
    token = extract_access_token(creds, request)
    if not token:
        return None
    payload = _jwt_verify(token) # type: ignore
    return payload.get("sub") # type: ignore


def get_current_user(
    request: Request,
    creds: HTTPAuthorizationCredentials | None = Depends(_bearer),
    db: Session = Depends(get_db),
):
    """Strict auth: resolve and return the current active user object."""
    token = extract_access_token(creds, request)
    if not token:
        raise HTTPException(status_code=401, detail="Authentication required")

    from app.db.models import User as UserModel

    payload = _jwt_verify(token) # type: ignore
    user_id = payload.get("sub") # type: ignore
    if not user_id:
        raise HTTPException(status_code=401, detail="Token missing subject")

    user = db.query(UserModel).filter(UserModel.id == user_id).first() # type: ignore
    if not user or not user.is_active:
        raise HTTPException(status_code=401, detail="Invalid or inactive user")
    return user


def require_auth(user = Depends(get_current_user)) -> str: # type: ignore
    """Strict auth: raises 401 if no valid token."""
    return user.id


def require_any_role(*allowed_roles: str):
    expected = {normalize_role(role) for role in allowed_roles} or {DEFAULT_ROLE}

    def _dependency(
        request: Request,
        user = Depends(get_current_user),  # type: ignore
        creds: HTTPAuthorizationCredentials | None = Depends(_bearer),
    ):
        token = extract_access_token(creds, request)
        if not token:
            raise HTTPException(status_code=401, detail="Authentication required")
        payload = _jwt_verify(token)
        current_role = resolve_session_role(user, payload)
        authorized = get_user_authorized_roles(user)
        token_role = normalize_role(payload.get("role"))
        if token_role not in authorized or current_role not in authorized:
            raise HTTPException(status_code=403, detail="Invalid session role")
        if current_role not in expected:
            raise HTTPException(status_code=403, detail="Insufficient role permissions")
        return user

    return _dependency


# ── Input validation ───────────────────────────────────────────────────────────
_EMAIL_RE = re.compile(r"^[a-zA-Z0-9._%+\-]+@[a-zA-Z0-9.\-]+\.[a-zA-Z]{2,}$")
_MAX_PASSWORD_LEN = 128
_MIN_PASSWORD_LEN = 8


def _validate_email(email: str) -> str: # type: ignore
    email = email.strip().lower()
    if not _EMAIL_RE.match(email):
        raise HTTPException(status_code=422, detail="Invalid email address")
    return email


def _validate_password(password: str) -> None: # type: ignore
    if len(password) < _MIN_PASSWORD_LEN:
        raise HTTPException(status_code=422, detail=f"Password must be ≥{_MIN_PASSWORD_LEN} chars")
    if len(password) > _MAX_PASSWORD_LEN:
        raise HTTPException(status_code=422, detail=f"Password must be ≤{_MAX_PASSWORD_LEN} chars")


# ── Pydantic schemas ───────────────────────────────────────────────────────────

class RegisterRequest(BaseModel):
    email: str
    password: str
    display_name: str | None = None
    role: str = DEFAULT_ROLE
    organization_name: str | None = None

    @field_validator("email")
    @classmethod
    def email_format(cls, v: str) -> str:
        if not _EMAIL_RE.match(v.strip().lower()):
            raise ValueError("Invalid email address")
        return v.strip().lower()

    @field_validator("password")
    @classmethod
    def password_strength(cls, v: str) -> str:
        if len(v) < _MIN_PASSWORD_LEN:
            raise ValueError(f"Password must be ≥{_MIN_PASSWORD_LEN} characters")
        if len(v) > _MAX_PASSWORD_LEN:
            raise ValueError(f"Password must be ≤{_MAX_PASSWORD_LEN} characters")
        return v

    @field_validator("role")
    @classmethod
    def role_valid(cls, v: str) -> str:
        role = normalize_role(v)
        if role not in VALID_ROLES:
            raise ValueError("Invalid role")
        return role

    @field_validator("organization_name")
    @classmethod
    def org_trim(cls, v: str | None) -> str | None:
        if v is None:
            return None
        cleaned = v.strip()
        return cleaned or None


class LoginRequest(BaseModel):
    email: str
    password: str


class RefreshRequest(BaseModel):
    refresh_token: str | None = None


class TokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    expires_in: int = ACCESS_TOKEN_EXPIRE_MINUTES * 60
    role: str | None = None


class LoginResponse(TokenResponse):
    refresh_token: str
    user_id: str
    email: str
    display_name: str | None
    role: str
    session_role: str
    authorized_roles: list[str]
    organization_name: str | None
    organization_id: str | None


class SwitchRoleRequest(BaseModel):
    role: str

    @field_validator("role")
    @classmethod
    def role_valid(cls, v: str) -> str:
        role = normalize_role(v)
        if role not in WORKSPACE_SWITCHABLE_ROLES:
            raise ValueError("Invalid workspace role")
        return role


class SwitchRoleResponse(TokenResponse):
    role: str
    session_role: str
    authorized_roles: list[str]
    token_role: str


class UserContext(BaseModel):
    user_id: str
    email: str
    role: str
    organization_name: str | None = None
    organization_id: str | None = None


# ── Router ─────────────────────────────────────────────────────────────────────
router = APIRouter(prefix="/api/auth", tags=["auth"])


@router.post("/deployment/sync-seed-users")
def deployment_sync_seed_users(request: Request):
    """Re-sync pilot seed accounts after deploy. Requires X-Amicor-Deployment-Key header."""
    expected = os.getenv("AMICOR_DEPLOYMENT_SYNC_KEY", "").strip() or SEED_PASSWORD
    if not expected:
        raise HTTPException(status_code=503, detail="Deployment sync not configured")
    provided = request.headers.get("X-Amicor-Deployment-Key", "").strip()
    if not provided or not hmac.compare_digest(provided, expected):
        raise HTTPException(
            status_code=403,
            detail=(
                "Invalid deployment sync key. Set Render env AMICOR_DEPLOYMENT_SYNC_KEY to match "
                "X-Amicor-Deployment-Key, or unset it to fall back to AMICOR_SEED_PASSWORD."
            ),
        )
    created = seed_default_users()
    operator_updates = apply_operator_role_grants()
    from app.db.session import SessionLocal
    from app.modules.health_isf import service as health_isf_service

    db = SessionLocal()
    try:
        default_org = health_isf_service._get_or_create_default_org(db)
        bootstrap_summary = health_isf_service.sync_operational_bootstrap(db)
        provider_summary = {}
        driver_summary = {}
        for item in bootstrap_summary.get("summaries") or []:
            if isinstance(item, dict):
                provider_summary = item.get("providers") or provider_summary
                driver_summary = item.get("drivers") or driver_summary
    finally:
        db.close()
    return {
        "status": "ok",
        "created": created,
        "operator_role_grants": operator_updates,
        "seed_users_total": len(SEED_USERS),
        "password_env": "AMICOR_SEED_PASSWORD",
        "provider_seed": provider_summary,
        "driver_seed": driver_summary,
        "operational_bootstrap": bootstrap_summary,
    }


@router.post("/deployment/operator-workspace-token", response_model=SwitchRoleResponse)
def deployment_operator_workspace_token(
    request: Request,
    req: SwitchRoleRequest,
    db: Session = Depends(get_db),
):
    """Issue a real operator JWT for deployment verification (requires deployment sync key)."""
    expected = os.getenv("AMICOR_DEPLOYMENT_SYNC_KEY", "").strip() or SEED_PASSWORD
    if not expected:
        raise HTTPException(status_code=503, detail="Deployment sync not configured")
    provided = request.headers.get("X-Amicor-Deployment-Key", "").strip()
    if not provided or not hmac.compare_digest(provided, expected):
        raise HTTPException(status_code=403, detail="Invalid deployment sync key")

    from app.db.models import User as UserModel

    apply_operator_role_grants()
    target_email = ""
    for grant in OPERATOR_ACCOUNT_GRANTS:
        target_email = str(grant.get("email") or "").strip().lower()
        if target_email:
            break
    if not target_email:
        raise HTTPException(status_code=404, detail="Operator grant target not configured")

    user = db.query(UserModel).filter(func.lower(UserModel.email) == target_email).first()
    if not user:
        raise HTTPException(status_code=404, detail="Operator account not found")

    requested = normalize_role(req.role)
    authorized = get_user_authorized_roles(user)
    if requested not in authorized:
        raise HTTPException(status_code=403, detail="Role not authorized for operator account")

    user.session_role = requested
    db.add(user)
    db.commit()
    db.refresh(user)

    access = create_access_token(_access_token_payload(user, requested))
    payload = _jwt_verify(access)
    return SwitchRoleResponse(
        access_token=access,
        role=requested,
        session_role=requested,
        authorized_roles=sorted(authorized),
        token_role=normalize_role(payload.get("role")),
    )


@router.get("/deployment/operator-grants")
def deployment_operator_grants():
    """Report operator role grants applied at startup (no secrets)."""
    updated = apply_operator_role_grants()
    return {
        "status": "ok",
        "operator_role_grants": updated,
        "grant_targets": [
            {
                "display_name": item.get("display_name"),
                "email": item.get("email"),
            }
            for item in OPERATOR_ACCOUNT_GRANTS
        ],
    }


@router.get("/deployment/seed-status")
def deployment_seed_status(db: Session = Depends(get_db)):
    """Report whether baseline pilot accounts exist (no secrets exposed)."""
    from app.db.models import User as UserModel

    emails = [item["email"] for item in SEED_USERS]
    rows = db.query(UserModel.email).filter(UserModel.email.in_(emails)).all()
    present = sorted({str(row[0]).lower() for row in rows})
    present_set = set(present)
    seed_password_env = os.getenv("AMICOR_SEED_PASSWORD", "").strip()
    sync_key_env = os.getenv("AMICOR_DEPLOYMENT_SYNC_KEY", "").strip()
    return {
        "expected_accounts": len(emails),
        "present_accounts": len(present),
        "missing_accounts": [email for email in emails if email not in present],
        "deployment_sync_configured": bool(sync_key_env or seed_password_env or SEED_PASSWORD),
        "pilot_accounts": [
            {"email": item["email"], "role": item["role"], "present": item["email"].lower() in present_set}
            for item in SEED_USERS
        ],
        "login_note": (
            "Pilot account passwords are reset to the runtime AMICOR_SEED_PASSWORD on every "
            "deploy startup and after a successful POST /api/auth/deployment/sync-seed-users call."
        ),
        "sync_note": (
            "Send header X-Amicor-Deployment-Key matching runtime AMICOR_DEPLOYMENT_SYNC_KEY "
            "(or AMICOR_SEED_PASSWORD when the sync key env var is unset)."
        ),
    }


@router.post("/register", status_code=201)
def register(req: RegisterRequest, request: Request, db: Session = Depends(get_db)):
    """Create a new account. Returns 409 if email already exists."""
    from app.db.models import User as UserModel

    check_rate_limit(
        f"register:{request.client.host if request.client else 'unknown'}",
        limit=5, window_s=300,  # 5 registrations per 5 minutes per IP
    )

    existing = db.query(UserModel).filter(UserModel.email == req.email).first()
    if existing:
        raise HTTPException(status_code=409, detail="Email already registered")

    role = normalize_role(req.role)
    if role in {ROLE_ADMIN, ROLE_SUPER_ADMIN_SUPPORT}:
        raise HTTPException(status_code=403, detail="Privileged roles cannot self-register")

    organization_id, organization_name = _resolve_registration_organization(db, req.organization_name)
    authorized_roles = ROLE_DEFAULT_AUTHORIZED.get(role, (role,))

    user = UserModel(
        email=req.email,
        hashed_password=hash_password(req.password),
        display_name=req.display_name,
        role=role,
        authorized_roles=_serialize_authorized_roles(authorized_roles),
        session_role=role,
        organization_name=organization_name,
        organization_id=organization_id,
    )
    db.add(user)
    db.commit()
    db.refresh(user)
    logger.info("New user registered: %s (id=%s)", user.email, user.id)
    return {"user_id": user.id, "email": user.email, "status": "created"}


def _fetch_login_user(db: Session, email: str) -> Any | None:
    """Load a platform user for password login, with a raw-SQL fallback for schema drift."""
    from app.db.models import User as UserModel

    normalized = email.strip().lower()
    try:
        return (
            db.query(UserModel)
            .filter(UserModel.email == normalized)
            .first()
        )
    except Exception:
        db.rollback()
        logger.warning("ORM login lookup failed for email=%s; trying SQL fallback", normalized, exc_info=True)

    bind = db.get_bind()
    inspector = inspect(bind)
    if "platform_users" not in inspector.get_table_names():
        return None
    available = {col["name"] for col in inspector.get_columns("platform_users")}
    required = ["id", "email", "hashed_password", "is_active", "role"]
    if not all(col in available for col in required):
        return None
    optional = ["session_role", "authorized_roles", "organization_id", "organization_name", "display_name"]
    select_cols = required + [column for column in optional if column in available]
    sql = f"SELECT {', '.join(select_cols)} FROM platform_users WHERE lower(email) = :email LIMIT 1"
    row = db.execute(text(sql), {"email": normalized}).mappings().first()
    if not row:
        return None
    user = UserModel()
    for column in select_cols:
        setattr(user, column, row[column])
    for column in optional:
        if column not in select_cols and hasattr(UserModel, column):
            setattr(user, column, None)
    return user


@router.post("/login", response_model=LoginResponse)
def login(req: LoginRequest, request: Request, response: Response, db: Session = Depends(get_db)):
    """Password login — returns access + refresh tokens."""
    from app.db.models import User as UserModel, RefreshToken as RefreshTokenModel

    ip = request.headers.get("X-Forwarded-For", request.client.host if request.client else "anon")
    check_rate_limit(f"login:{ip}", limit=_RATE_LIMIT_AUTH)

    try:
        ensure_auth_schema()
    except Exception:
        logger.exception("ensure_auth_schema_failed_during_login")

    try:
        user = _fetch_login_user(db, req.email)
    except Exception as exc:
        db.rollback()
        logger.exception("Login user lookup failed for email=%s", req.email)
        raise HTTPException(status_code=503, detail="Login database unavailable") from exc
    if not user or not verify_password(req.password, user.hashed_password):
        # Constant-time-ish rejection
        time.sleep(0.2)
        raise HTTPException(status_code=401, detail="Invalid email or password")
    if not user.is_active:
        raise HTTPException(status_code=403, detail="Account disabled")

    ensure_user_organization(db, user)

    session_role = normalize_role(getattr(user, "session_role", None) or getattr(user, "role", None))
    authorized = get_user_authorized_roles(user)
    if session_role not in authorized:
        session_role = normalize_role(getattr(user, "role", None))
    user.session_role = session_role

    persisted_user = None
    try:
        persisted_user = db.get(UserModel, str(user.id))
    except Exception:
        db.rollback()
    if persisted_user is not None:
        persisted_user.session_role = session_role
        persisted_user.last_login = datetime.now(timezone.utc)
        db.add(persisted_user)
        user = persisted_user

    access = create_access_token(_access_token_payload(user, session_role))
    # Refresh token
    raw_refresh = create_refresh_token()
    hashed = _hash_token(raw_refresh)
    expires = datetime.now(timezone.utc) + timedelta(days=REFRESH_TOKEN_EXPIRE_DAYS)
    rt = RefreshTokenModel(user_id=user.id, token_hash=hashed, expires_at=expires)
    db.add(rt)
    try:
        db.commit()
    except Exception as exc:
        db.rollback()
        logger.exception("Login commit failed for user_id=%s: %s", user.id, exc)
        raise HTTPException(status_code=503, detail="Login persistence unavailable") from exc

    logger.info("Login: user_id=%s ip=%s", user.id, ip)
    try:
        from app.core.nova.assistant_execution_service import log_operational_event

        log_operational_event(
            user_id=str(user.id),
            role=session_role,
            event_type="auth",
            event_name="login",
            status="success",
            payload={
                "ip": ip,
                "organization_id": getattr(user, "organization_id", None),
                "organization_name": getattr(user, "organization_name", None),
            },
        )
    except Exception:
        logger.warning("Non-critical login telemetry failed for user_id=%s", user.id, exc_info=True)
    return LoginResponse(
        access_token=access,
        refresh_token=raw_refresh,
        user_id=user.id,
        email=user.email,
        display_name=user.display_name,
        role=session_role,
        session_role=session_role,
        authorized_roles=sorted(authorized),
        organization_name=getattr(user, "organization_name", None),
        organization_id=getattr(user, "organization_id", None),
    )


@router.post("/refresh", response_model=TokenResponse)
def refresh_token(req: RefreshRequest, request: Request, db: Session = Depends(get_db)):
    """Exchange a valid refresh token for a new access token."""
    from app.db.models import RefreshToken as RefreshTokenModel, User as UserModel

    ip = request.headers.get("X-Forwarded-For", request.client.host if request.client else "anon")
    check_rate_limit(f"refresh:{ip}", limit=30)

    if not req.refresh_token:
        raise HTTPException(status_code=401, detail="Refresh token invalid or revoked")
    hashed = _hash_token(req.refresh_token)
    rt = db.query(RefreshTokenModel).filter(RefreshTokenModel.token_hash == hashed).first()
    if not rt or rt.revoked:
        raise HTTPException(status_code=401, detail="Refresh token invalid or revoked")
    if rt.expires_at.replace(tzinfo=timezone.utc) < datetime.now(timezone.utc):
        raise HTTPException(status_code=401, detail="Refresh token expired")

    user = db.query(UserModel).filter(UserModel.id == rt.user_id).first()
    if not user or not user.is_active:
        raise HTTPException(status_code=401, detail="User not found or inactive")

    ensure_user_organization(db, user)

    session_role = resolve_session_role(user, None)
    access = create_access_token(_access_token_payload(user, session_role))
    return TokenResponse(access_token=access, role=session_role)


@router.post("/switch-role", response_model=SwitchRoleResponse)
def switch_role(
    req: SwitchRoleRequest,
    user = Depends(get_current_user),  # type: ignore
    creds: HTTPAuthorizationCredentials | None = Depends(_bearer),
    db: Session = Depends(get_db),
):
    """Validate and issue a new access token for an authorized workspace role."""
    if not creds:
        raise HTTPException(status_code=401, detail="Authentication required")

    requested = normalize_role(req.role)
    authorized = get_user_authorized_roles(user)
    if requested not in authorized:
        raise HTTPException(status_code=403, detail="Role not authorized for this account")

    user.session_role = requested
    db.add(user)
    db.commit()
    db.refresh(user)

    access = create_access_token(_access_token_payload(user, requested))
    payload = _jwt_verify(access)
    return SwitchRoleResponse(
        access_token=access,
        role=requested,
        session_role=requested,
        authorized_roles=sorted(authorized),
        token_role=normalize_role(payload.get("role")),
    )


@router.post("/logout")
def logout(
    response: Response,
    req: RefreshRequest | None = None,
    db: Session = Depends(get_db),
):
    """Revoke a refresh token and clear the HttpOnly admin session cookie."""
    from app.db.models import RefreshToken as RefreshTokenModel

    clear_admin_session_cookie(response)
    token = req.refresh_token if req is not None else None
    if token:
        hashed = _hash_token(token)
        rt = db.query(RefreshTokenModel).filter(RefreshTokenModel.token_hash == hashed).first()
        if rt:
            rt.revoked = True
            db.commit()
    return {"status": "logged out"}


@router.post("/admin-session")
def admin_session_login(req: LoginRequest, request: Request, response: Response, db: Session = Depends(get_db)):
    """Browser admin login: HttpOnly cookie only — JWT is not returned to JavaScript."""
    result = login(req, request, response, db)
    set_admin_session_cookie(response, request, result.access_token)
    return {
        "status": "ok",
        "session": "cookie",
        "user_id": result.user_id,
        "email": result.email,
        "display_name": result.display_name,
        "role": result.role,
        "session_role": result.session_role,
        "authorized_roles": result.authorized_roles,
        "organization_id": result.organization_id,
        "organization_name": result.organization_name,
    }


@router.post("/admin-session/logout")
def admin_session_logout(response: Response):
    clear_admin_session_cookie(response)
    return {"status": "logged out", "session": "cookie"}


@router.get("/me")
def me(
    request: Request,
    user = Depends(get_current_user),  # type: ignore
    creds: HTTPAuthorizationCredentials | None = Depends(_bearer),
):
    """Return the current authenticated user's profile."""
    token = extract_access_token(creds, request)
    payload = _jwt_verify(token) if token else {}
    session_role = resolve_session_role(user, payload)
    authorized = sorted(get_user_authorized_roles(user))
    return {
        "user_id": user.id,
        "email": user.email,
        "display_name": user.display_name,
        "role": session_role,
        "primary_role": normalize_role(getattr(user, "role", None)),
        "session_role": session_role,
        "authorized_roles": authorized,
        "token_role": normalize_role(payload.get("role")),
        "organization_name": getattr(user, "organization_name", None),
        "organization_id": getattr(user, "organization_id", None),
        "is_verified": user.is_verified,
        "created_at": user.created_at.isoformat(),
        "last_login": user.last_login.isoformat() if user.last_login else None,
    }


@router.get("/session")
def session_info(
    request: Request,
    user = Depends(get_current_user),  # type: ignore
    creds: HTTPAuthorizationCredentials | None = Depends(_bearer),
):
    """Return active JWT session role claims for workspace verification."""
    token = extract_access_token(creds, request)
    if not token:
        raise HTTPException(status_code=401, detail="Authentication required")
    payload = _jwt_verify(token)
    session_role = resolve_session_role(user, payload)
    return {
        "session_valid": True,
        "user_id": user.id,
        "email": user.email,
        "display_name": user.display_name,
        "role": session_role,
        "token_role": normalize_role(payload.get("role")),
        "primary_role": normalize_role(getattr(user, "role", None)),
        "session_role": normalize_role(getattr(user, "session_role", None) or getattr(user, "role", None)),
        "authorized_roles": sorted(get_user_authorized_roles(user)),
        "token_expires_at": payload.get("exp"),
    }


def decode_access_token(token: str) -> dict[str, Any]:
    """Public token decode helper used by middleware/websocket handshakes."""
    return _jwt_verify(token) # type: ignore


def get_current_user_context(
    user = Depends(get_current_user),  # type: ignore
    creds: HTTPAuthorizationCredentials | None = Depends(_bearer),
) -> UserContext:
    payload = _jwt_verify(creds.credentials) if creds else {}
    session_role = resolve_session_role(user, payload)
    return UserContext(
        user_id=user.id,
        email=user.email,
        role=session_role,
        organization_name=getattr(user, "organization_name", None),
        organization_id=getattr(user, "organization_id", None),
    )


def is_super_admin(user: UserContext) -> bool:
    return normalize_role(user.role) in {ROLE_ADMIN, ROLE_SUPER_ADMIN_SUPPORT}
