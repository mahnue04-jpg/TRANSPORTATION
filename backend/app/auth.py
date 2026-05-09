"""
Auth system: JWT access tokens, refresh tokens, password hashing, in-memory rate limiting.

Endpoints (all under /api/auth):
  POST /register   — create account
  POST /login      — password login → {access_token, refresh_token}
  POST /refresh    — exchange refresh token → new access token
  POST /logout     — revoke refresh token
  GET  /me         — return current user info (requires Bearer token)
"""
import hashlib
import logging
import os
import re
import secrets
import time
from collections import defaultdict
from datetime import datetime, timedelta, timezone
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Request, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from pydantic import BaseModel, field_validator
from sqlalchemy.orm import Session

logger = logging.getLogger("amicor.auth")

# ── Configuration ──────────────────────────────────────────────────────────────
SECRET_KEY = os.getenv("SECRET_KEY", "")
_ALGORITHM = "HS256"
ACCESS_TOKEN_EXPIRE_MINUTES = int(os.getenv("ACCESS_TOKEN_EXPIRE_MINUTES", "60"))
REFRESH_TOKEN_EXPIRE_DAYS = int(os.getenv("REFRESH_TOKEN_EXPIRE_DAYS", "7"))

# Warn if no secret key configured
if not SECRET_KEY:
    _fallback = secrets.token_hex(32)
    SECRET_KEY = _fallback
    logger.warning(
        "SECRET_KEY not set — using ephemeral key. Tokens will be invalid after restart. "
        "Set SECRET_KEY env var in production."
    )

# ── JWT (pure stdlib — no extra deps) ─────────────────────────────────────────
import base64
import hmac
import json as _json


def _b64url_encode(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode()


def _b64url_decode(s: str) -> bytes:
    pad = 4 - len(s) % 4
    return base64.urlsafe_b64decode(s + "=" * (pad % 4))


def _jwt_sign(payload: dict) -> str:
    header = _b64url_encode(_json.dumps({"alg": "HS256", "typ": "JWT"}).encode())
    body   = _b64url_encode(_json.dumps(payload).encode())
    sig = hmac.new(SECRET_KEY.encode(), f"{header}.{body}".encode(), hashlib.sha256).digest()
    return f"{header}.{body}.{_b64url_encode(sig)}"


def _jwt_verify(token: str) -> dict:
    try:
        header_b64, body_b64, sig_b64 = token.split(".")
    except ValueError:
        raise HTTPException(status_code=401, detail="Invalid token format")
    expected_sig = hmac.new(
        SECRET_KEY.encode(), f"{header_b64}.{body_b64}".encode(), hashlib.sha256
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
    return payload


def create_access_token(data: dict) -> str:
    payload = {**data, "exp": time.time() + ACCESS_TOKEN_EXPIRE_MINUTES * 60}
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


def get_current_user_id(
    creds: HTTPAuthorizationCredentials | None = Depends(_bearer),
) -> str | None:
    """Return user_id from JWT Bearer token, or None if not provided."""
    if not creds:
        return None
    payload = _jwt_verify(creds.credentials)
    return payload.get("sub")


def require_auth(user_id: str | None = Depends(get_current_user_id)) -> str:
    """Strict auth: raises 401 if no valid token."""
    if not user_id:
        raise HTTPException(status_code=401, detail="Authentication required")
    return user_id


# ── Input validation ───────────────────────────────────────────────────────────
_EMAIL_RE = re.compile(r"^[a-zA-Z0-9._%+\-]+@[a-zA-Z0-9.\-]+\.[a-zA-Z]{2,}$")
_MAX_PASSWORD_LEN = 128
_MIN_PASSWORD_LEN = 8


def _validate_email(email: str) -> str:
    email = email.strip().lower()
    if not _EMAIL_RE.match(email):
        raise HTTPException(status_code=422, detail="Invalid email address")
    return email


def _validate_password(password: str) -> None:
    if len(password) < _MIN_PASSWORD_LEN:
        raise HTTPException(status_code=422, detail=f"Password must be ≥{_MIN_PASSWORD_LEN} chars")
    if len(password) > _MAX_PASSWORD_LEN:
        raise HTTPException(status_code=422, detail=f"Password must be ≤{_MAX_PASSWORD_LEN} chars")


# ── Pydantic schemas ───────────────────────────────────────────────────────────

class RegisterRequest(BaseModel):
    email: str
    password: str
    display_name: str | None = None

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


class LoginRequest(BaseModel):
    email: str
    password: str


class RefreshRequest(BaseModel):
    refresh_token: str


class TokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    expires_in: int = ACCESS_TOKEN_EXPIRE_MINUTES * 60


class LoginResponse(TokenResponse):
    refresh_token: str
    user_id: str
    email: str
    display_name: str | None


# ── Router ─────────────────────────────────────────────────────────────────────
router = APIRouter(prefix="/api/auth", tags=["auth"])


@router.post("/register", status_code=201)
def register(req: RegisterRequest, request: Request):
    """Create a new account. Returns 409 if email already exists."""
    from app.db.session import get_db as _get_db
    from app.db.models import User as UserModel

    check_rate_limit(
        f"register:{request.client.host if request.client else 'unknown'}",
        limit=5, window_s=300,  # 5 registrations per 5 minutes per IP
    )

    db: Session = next(_get_db())
    try:
        existing = db.query(UserModel).filter(UserModel.email == req.email).first()
        if existing:
            raise HTTPException(status_code=409, detail="Email already registered")

        user = UserModel(
            email=req.email,
            hashed_password=hash_password(req.password),
            display_name=req.display_name,
        )
        db.add(user)
        db.commit()
        db.refresh(user)
        logger.info("New user registered: %s (id=%s)", user.email, user.id)
        return {"user_id": user.id, "email": user.email, "status": "created"}
    finally:
        db.close()


@router.post("/login", response_model=LoginResponse)
def login(req: LoginRequest, request: Request):
    """Password login — returns access + refresh tokens."""
    from app.db.session import get_db as _get_db
    from app.db.models import User as UserModel, RefreshToken as RefreshTokenModel

    ip = request.headers.get("X-Forwarded-For", request.client.host if request.client else "anon")
    check_rate_limit(f"login:{ip}", limit=_RATE_LIMIT_AUTH)

    db: Session = next(_get_db())
    try:
        user = db.query(UserModel).filter(
            UserModel.email == req.email.strip().lower()
        ).first()
        if not user or not verify_password(req.password, user.hashed_password):
            # Constant-time-ish rejection
            time.sleep(0.2)
            raise HTTPException(status_code=401, detail="Invalid email or password")
        if not user.is_active:
            raise HTTPException(status_code=403, detail="Account disabled")

        # Access token
        access = create_access_token({"sub": user.id, "email": user.email})
        # Refresh token
        raw_refresh = create_refresh_token()
        hashed = _hash_token(raw_refresh)
        expires = datetime.now(timezone.utc) + timedelta(days=REFRESH_TOKEN_EXPIRE_DAYS)
        rt = RefreshTokenModel(user_id=user.id, token_hash=hashed, expires_at=expires)
        db.add(rt)
        user.last_login = datetime.now(timezone.utc)
        db.commit()

        logger.info("Login: user_id=%s ip=%s", user.id, ip)
        return LoginResponse(
            access_token=access,
            refresh_token=raw_refresh,
            user_id=user.id,
            email=user.email,
            display_name=user.display_name,
        )
    finally:
        db.close()


@router.post("/refresh", response_model=TokenResponse)
def refresh_token(req: RefreshRequest, request: Request):
    """Exchange a valid refresh token for a new access token."""
    from app.db.session import get_db as _get_db
    from app.db.models import RefreshToken as RefreshTokenModel, User as UserModel

    ip = request.headers.get("X-Forwarded-For", request.client.host if request.client else "anon")
    check_rate_limit(f"refresh:{ip}", limit=30)

    hashed = _hash_token(req.refresh_token)
    db: Session = next(_get_db())
    try:
        rt = db.query(RefreshTokenModel).filter(RefreshTokenModel.token_hash == hashed).first()
        if not rt or rt.revoked:
            raise HTTPException(status_code=401, detail="Refresh token invalid or revoked")
        if rt.expires_at.replace(tzinfo=timezone.utc) < datetime.now(timezone.utc):
            raise HTTPException(status_code=401, detail="Refresh token expired")

        user = db.query(UserModel).filter(UserModel.id == rt.user_id).first()
        if not user or not user.is_active:
            raise HTTPException(status_code=401, detail="User not found or inactive")

        access = create_access_token({"sub": user.id, "email": user.email})
        return TokenResponse(access_token=access)
    finally:
        db.close()


@router.post("/logout")
def logout(req: RefreshRequest):
    """Revoke a refresh token."""
    from app.db.session import get_db as _get_db
    from app.db.models import RefreshToken as RefreshTokenModel

    hashed = _hash_token(req.refresh_token)
    db: Session = next(_get_db())
    try:
        rt = db.query(RefreshTokenModel).filter(RefreshTokenModel.token_hash == hashed).first()
        if rt:
            rt.revoked = True
            db.commit()
        return {"status": "logged out"}
    finally:
        db.close()


@router.get("/me")
def me(user_id: str = Depends(require_auth)):
    """Return the current authenticated user's profile."""
    from app.db.session import get_db as _get_db
    from app.db.models import User as UserModel

    db: Session = next(_get_db())
    try:
        user = db.query(UserModel).filter(UserModel.id == user_id).first()
        if not user:
            raise HTTPException(status_code=404, detail="User not found")
        return {
            "user_id": user.id,
            "email": user.email,
            "display_name": user.display_name,
            "is_verified": user.is_verified,
            "created_at": user.created_at.isoformat(),
            "last_login": user.last_login.isoformat() if user.last_login else None,
        }
    finally:
        db.close()
