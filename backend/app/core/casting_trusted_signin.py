"""Staging-only RS256 verification for a future Casting sign-in.

Password login stays on this process's HS256 secret. This module never reads
DATABASE_URL, JWT_SECRET, or SECRET_KEY, never queries platform_users, and
never activates the production Nova origin. A synthetic ``.test`` issuer can
be verified in staging tests. Main Nova still has to publish a JWKS before a
real token can be accepted, and that production change is not in this branch.
"""
from __future__ import annotations

import base64
import json
import logging
import os
import re
import sqlite3
import threading
import time
import uuid
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from urllib.parse import urlsplit

from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.asymmetric import padding, rsa
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

logger = logging.getLogger("amicor.casting_trusted_signin")

# Live Nova origin. Signup and password reset use this public URL, and the
# production health check is served here. Access tokens do not set iss or aud
# unless JWT_ISSUER / JWT_AUDIENCE are configured; both default to empty.
# These two values are documented only. This module refuses to activate them.
PROPOSED_ISSUER = "https://amicor-health-isf-py.onrender.com"
PROPOSED_AUDIENCE = "https://amicor-health-isf-py.onrender.com"
AUDIENCE_BASIS = (
    "JWT_AUDIENCE is unset. The stable public Nova origin is the production host, "
    "so the proposed audience is that same origin until the owner confirms it."
)
ISSUER_SIDE_DECISION = (
    "Main Nova at https://amicor-health-isf-py.onrender.com still signs access "
    "tokens with HS256 and a server-side secret. It does not publish "
    "/.well-known/openid-configuration or a JWKS. Approve a separate change on "
    "main Nova to publish an RS256 key and a JWKS at that origin, with issuer "
    "and audience both set to https://amicor-health-isf-py.onrender.com. This "
    "branch does not change production signing, and the preview will not accept "
    "that issuer until that approval."
)
BLOCKER = (
    "No supported shared-auth path for main Nova. Preview login checks platform_users in "
    "this database and verifies HS256 with this service's signing secret. "
    "Main Nova does not publish a JWKS or OIDC discovery document. "
    "This service can verify RS256 tokens only for a synthetic staging issuer in tests. "
    "Accepting real main Nova tokens needs a separate owner approval to change production signing."
)
OWNER_DECISIONS = (
    "Approve a separate main Nova change that publishes an RS256 JWKS at https://amicor-health-isf-py.onrender.com. This branch does not change production signing.",
    "Confirm the proposed issuer and audience, both the production origin, because JWT_AUDIENCE is unset.",
    "Keep casting reads, writes, media, email, SMS, WhatsApp, and payments off until a separate approval.",
    "Leave the preview database and production services unchanged. Do not import account rows.",
)
PROPOSED_ENV_NAMES = (
    "NOVA_CASTING_TRUSTED_SIGNIN",
    "NOVA_CASTING_TRUSTED_ISSUER",
    "NOVA_CASTING_TRUSTED_AUDIENCE",
    "NOVA_CASTING_TRUSTED_JWKS_URL",
)
_ENV_NAMES = ("AMICOR_ENVIRONMENT", "ENVIRONMENT", "APP_ENV")
_ALLOWLIST = frozenset({
    "development", "dev", "test", "testing", "local", "staging", "disposable",
})
_PRODUCTION_ENV = frozenset({"production", "prod"})
PRODUCTION_ISSUER_HOSTS = frozenset({
    "amicor-health-isf-py.onrender.com",
    "amicor-health-isf.onrender.com",
})
MAX_TOKEN_LIFETIME_SECONDS = 3600
CLOCK_SKEW_SECONDS = 60
KEY_CACHE_SECONDS = 600
_KID = re.compile(r"[A-Za-z0-9._-]{1,128}")
_SUBJECT = re.compile(r"[A-Za-z0-9._:-]{1,200}")
_VERIFIED = object()

router = APIRouter(tags=["Nova Casting trusted sign-in"])


class TrustedSigninRejected(Exception):
    def __init__(self, reason: str) -> None:
        self.reason = reason
        super().__init__(reason)


@dataclass(frozen=True)
class VerifiedToken:
    issuer: str
    audience: str
    subject: str
    expires_at: int
    kid: str
    proof: object

    def __post_init__(self) -> None:
        if self.proof is not _VERIFIED:
            raise TrustedSigninRejected("subject")


class TrustedSigninRequest(BaseModel):
    token: str = Field(min_length=20, max_length=8000)


def _source(env: Mapping[str, str] | None) -> Mapping[str, str]:
    return os.environ if env is None else env


def _environment_allows_staging(source: Mapping[str, str]) -> bool:
    values = []
    for name in _ENV_NAMES:
        raw = source.get(name)
        if raw is None:
            continue
        text = str(raw).strip().lower()
        if text:
            values.append(text)
    if not values or any(value in _PRODUCTION_ENV for value in values):
        return False
    if any(value not in _ALLOWLIST for value in values):
        return False
    return len(set(values)) == 1


def _https_parts(value: str):
    if not value or any(char.isspace() for char in value) or value.endswith("/"):
        return None
    parts = urlsplit(value)
    host = (parts.hostname or "").lower()
    if (
        parts.scheme != "https"
        or not host
        or parts.username
        or parts.password
        or parts.query
        or parts.fragment
    ):
        return None
    return parts


def _synthetic_issuer(value: str) -> bool:
    parts = _https_parts(value)
    if parts is None:
        return False
    host = parts.hostname.lower()
    if host in PRODUCTION_ISSUER_HOSTS or host.endswith(".onrender.com"):
        return False
    return host.endswith(".test")


def _same_host(url: str, issuer: str) -> bool:
    left = _https_parts(url)
    right = _https_parts(issuer)
    if left is None or right is None:
        return False
    return left.hostname.lower() == right.hostname.lower() and left.port == right.port


def _acceptable_audience(value: str) -> bool:
    if not isinstance(value, str) or not value or len(value) > 200:
        return False
    return not any(char.isspace() for char in value)


def trusted_signin_decision(env: Mapping[str, str] | None = None) -> dict:
    """Decide whether synthetic staging verification is on.

    The production origin cannot be activated here. This function does not
    connect, fetch a JWKS, or read database and signing secrets.
    """
    source = _source(env)
    recorded = {name: str(source.get(name, "")).strip() for name in PROPOSED_ENV_NAMES}
    issuer = recorded["NOVA_CASTING_TRUSTED_ISSUER"]
    audience = recorded["NOVA_CASTING_TRUSTED_AUDIENCE"]
    jwks_url = recorded["NOVA_CASTING_TRUSTED_JWKS_URL"]
    mode = recorded["NOVA_CASTING_TRUSTED_SIGNIN"]
    staging_ok = _environment_allows_staging(source)
    issuer_ok = _synthetic_issuer(issuer)
    audience_ok = _acceptable_audience(audience)
    jwks_ok = not jwks_url or _same_host(jwks_url, issuer)
    enabled = bool(
        mode == "staging" and staging_ok and issuer_ok and audience_ok and jwks_ok
    )
    return {
        "supported": False,
        "enabled": enabled,
        "staging_tests_enabled": enabled,
        "imports_accounts": False,
        "shares_database": False,
        "shares_signing_key": False,
        "shares_passwords": False,
        "validates_remote_token": enabled,
        "workflows_enabled": False,
        "applications_enabled": False,
        "media_uploads_enabled": False,
        "outbound_enabled": False,
        "payments_enabled": False,
        "production_integration": False,
        "production_issuer_activated": False,
        "issuer_side_change_required": True,
        "algorithm": "HS256",
        "verifier": "local-hmac",
        "trusted_algorithm": "RS256",
        "trusted_verifier": "rs256-jwks",
        "proposed_issuer": PROPOSED_ISSUER,
        "proposed_audience": PROPOSED_AUDIENCE,
        "active_issuer": issuer if enabled else "",
        "active_audience": audience if enabled else "",
        "blocker": BLOCKER,
        "issuer_side_decision": ISSUER_SIDE_DECISION,
        "owner_decisions": list(OWNER_DECISIONS),
        "proposed_env_ignored": recorded,
    }


def public_trusted_signin_status(env: Mapping[str, str] | None = None) -> dict:
    """Status safe to return on the preview. Configuration values are omitted."""
    decision = trusted_signin_decision(env)
    return {
        "supported": False,
        "enabled": decision["enabled"],
        "staging_tests_enabled": decision["staging_tests_enabled"],
        "production_integration": False,
        "production_issuer_activated": False,
        "issuer_side_change_required": True,
        "proposed_issuer": PROPOSED_ISSUER,
        "proposed_audience": PROPOSED_AUDIENCE,
        "proposed_audience_basis": AUDIENCE_BASIS,
        "issuer_side_decision": ISSUER_SIDE_DECISION,
        "active_verifier": "local-hmac",
        "trusted_verifier": "rs256-jwks",
        "trusted_verifier_active": decision["enabled"],
        "imports_accounts": False,
        "shares_database": False,
        "shares_signing_key": False,
        "shares_passwords": False,
        "workflows_enabled": False,
        "applications_enabled": False,
        "media_uploads_enabled": False,
        "outbound_enabled": False,
        "payments_enabled": False,
        "blocker": BLOCKER,
    }


def _b64url_decode(value: str) -> bytes:
    if not value or any(char.isspace() for char in value):
        raise TrustedSigninRejected("malformed")
    pad = "=" * (-len(value) % 4)
    try:
        return base64.urlsafe_b64decode(value + pad)
    except Exception as exc:
        raise TrustedSigninRejected("malformed") from exc


def _json_object(segment: str) -> dict:
    try:
        payload = json.loads(_b64url_decode(segment))
    except TrustedSigninRejected:
        raise
    except Exception as exc:
        raise TrustedSigninRejected("malformed") from exc
    if not isinstance(payload, dict):
        raise TrustedSigninRejected("malformed")
    return payload


def _require_whole_number(value: object, reason: str) -> int:
    if isinstance(value, bool) or isinstance(value, float):
        raise TrustedSigninRejected(reason)
    if not isinstance(value, int):
        raise TrustedSigninRejected(reason)
    return value


def _parse_jwks(document: object) -> dict[str, rsa.RSAPublicKey]:
    if not isinstance(document, dict):
        raise TrustedSigninRejected("key")
    keys = document.get("keys")
    if not isinstance(keys, list) or not keys:
        raise TrustedSigninRejected("key")
    parsed: dict[str, rsa.RSAPublicKey] = {}
    for item in keys:
        if not isinstance(item, dict):
            raise TrustedSigninRejected("key")
        if item.get("kty") != "RSA":
            continue
        if item.get("use") not in (None, "sig"):
            continue
        if item.get("alg") not in (None, "RS256"):
            continue
        kid = item.get("kid")
        if not isinstance(kid, str) or not _KID.fullmatch(kid):
            raise TrustedSigninRejected("key")
        if kid in parsed:
            raise TrustedSigninRejected("key")
        try:
            modulus = int.from_bytes(_b64url_decode(str(item.get("n") or "")), "big")
            exponent = int.from_bytes(_b64url_decode(str(item.get("e") or "")), "big")
            if modulus.bit_length() < 2048 or exponent < 3:
                raise TrustedSigninRejected("key")
            parsed[kid] = rsa.RSAPublicNumbers(exponent, modulus).public_key()
        except TrustedSigninRejected:
            raise
        except Exception as exc:
            raise TrustedSigninRejected("key") from exc
    if not parsed:
        raise TrustedSigninRejected("key")
    return parsed


class KeyRing:
    """JWKS cache. An unknown kid refreshes once. A failed fetch never falls back."""

    def __init__(
        self,
        fetch: Callable[[str], object],
        issuer: str,
        jwks_url: str = "",
        now: Callable[[], float] | None = None,
    ) -> None:
        if not _synthetic_issuer(issuer):
            raise TrustedSigninRejected("issuer")
        if jwks_url and not _same_host(jwks_url, issuer):
            raise TrustedSigninRejected("discovery")
        self.fetch = fetch
        self.issuer = issuer
        self.jwks_url = jwks_url
        self.now = now or time.time
        self.keys: dict[str, rsa.RSAPublicKey] = {}
        self.fetched_at = 0.0

    def public_key(self, kid: str):
        fresh = bool(self.keys) and (self.now() - self.fetched_at) < KEY_CACHE_SECONDS
        if fresh and kid in self.keys:
            return self.keys[kid]
        self._refresh()
        if kid in self.keys:
            return self.keys[kid]
        self._refresh()
        key = self.keys.get(kid)
        if key is None:
            raise TrustedSigninRejected("key")
        return key

    def _resolve_url(self) -> str:
        if self.jwks_url:
            if not _same_host(self.jwks_url, self.issuer):
                raise TrustedSigninRejected("discovery")
            return self.jwks_url
        discovery = self.issuer + "/.well-known/openid-configuration"
        try:
            document = self.fetch(discovery)
        except TrustedSigninRejected:
            raise
        except Exception as exc:
            raise TrustedSigninRejected("discovery") from exc
        if not isinstance(document, dict) or document.get("issuer") != self.issuer:
            raise TrustedSigninRejected("discovery")
        jwks_uri = document.get("jwks_uri")
        if not isinstance(jwks_uri, str) or not _same_host(jwks_uri, self.issuer):
            raise TrustedSigninRejected("discovery")
        self.jwks_url = jwks_uri
        return jwks_uri

    def _refresh(self) -> None:
        url = self._resolve_url()
        try:
            document = self.fetch(url)
        except TrustedSigninRejected:
            raise
        except Exception as exc:
            raise TrustedSigninRejected("key") from exc
        self.keys = _parse_jwks(document)
        self.fetched_at = self.now()


def verify_nova_token(
    token: str,
    *,
    issuer: str,
    audience: str,
    ring: KeyRing,
    now: float | None = None,
) -> VerifiedToken:
    """Validate one RS256 token. Claims are read only after the signature matches."""
    if not _synthetic_issuer(issuer) or ring.issuer != issuer:
        raise TrustedSigninRejected("issuer")
    if not _acceptable_audience(audience):
        raise TrustedSigninRejected("audience")
    if not isinstance(token, str) or token.count(".") != 2:
        raise TrustedSigninRejected("malformed")
    header_segment, _body, signature_segment = token.split(".")
    header = _json_object(header_segment)
    if header.get("alg") != "RS256" or header.get("typ", "JWT") not in (None, "JWT"):
        raise TrustedSigninRejected("algorithm")
    if any(name in header for name in ("crit", "jwk", "x5c")):
        raise TrustedSigninRejected("algorithm")
    kid = header.get("kid")
    if not isinstance(kid, str) or _KID.fullmatch(kid) is None:
        raise TrustedSigninRejected("key")
    signing_input = token.rsplit(".", 1)[0].encode("ascii", errors="strict")
    try:
        signature = _b64url_decode(signature_segment)
        ring.public_key(kid).verify(
            signature,
            signing_input,
            padding.PKCS1v15(),
            hashes.SHA256(),
        )
    except TrustedSigninRejected:
        raise
    except InvalidSignature as exc:
        raise TrustedSigninRejected("signature") from exc
    except Exception as exc:
        raise TrustedSigninRejected("signature") from exc

    payload = _json_object(token.split(".")[1])
    if payload.get("iss") != issuer:
        raise TrustedSigninRejected("issuer")
    if payload.get("aud") != audience or isinstance(payload.get("aud"), list):
        raise TrustedSigninRejected("audience")
    current = time.time() if now is None else now
    expires_at = _require_whole_number(payload.get("exp"), "expired")
    if current > expires_at + CLOCK_SKEW_SECONDS:
        raise TrustedSigninRejected("expired")
    if expires_at > current + MAX_TOKEN_LIFETIME_SECONDS + CLOCK_SKEW_SECONDS:
        raise TrustedSigninRejected("expired")
    if "nbf" in payload:
        not_before = _require_whole_number(payload.get("nbf"), "expired")
        if current + CLOCK_SKEW_SECONDS < not_before:
            raise TrustedSigninRejected("expired")
    if "iat" in payload:
        issued_at = _require_whole_number(payload.get("iat"), "expired")
        if issued_at > current + CLOCK_SKEW_SECONDS or expires_at - issued_at <= 0:
            raise TrustedSigninRejected("expired")
        if expires_at - issued_at > MAX_TOKEN_LIFETIME_SECONDS:
            raise TrustedSigninRejected("expired")
    subject = payload.get("sub")
    if not isinstance(subject, str) or _SUBJECT.fullmatch(subject) is None:
        raise TrustedSigninRejected("subject")
    return VerifiedToken(
        issuer=issuer,
        audience=audience,
        subject=subject,
        expires_at=expires_at,
        kid=kid,
        proof=_VERIFIED,
    )


class MemoryMembershipStore:
    """Process-local memberships. No password column and no account import."""

    def __init__(self) -> None:
        self.rows: dict[tuple[str, str], dict] = {}

    def get_or_create(self, issuer: str, subject: str) -> dict:
        key = (issuer, subject)
        existing = self.rows.get(key)
        if existing is not None:
            return {**existing, "created": False}
        row = {
            "local_id": str(uuid.uuid4()),
            "issuer": issuer,
            "subject": subject,
            "created": True,
        }
        self.rows[key] = {k: v for k, v in row.items() if k != "created"}
        return row


class SqliteMembershipStore:
    """Disposable sqlite memberships for staging tests. The table has no password."""

    def __init__(self, path: str) -> None:
        self.connection = sqlite3.connect(path, check_same_thread=False)
        self._lock = threading.Lock()
        self.connection.execute(
            """
            CREATE TABLE IF NOT EXISTS casting_trusted_memberships (
                local_id TEXT PRIMARY KEY,
                issuer TEXT NOT NULL,
                subject TEXT NOT NULL,
                created_at TEXT NOT NULL,
                UNIQUE (issuer, subject)
            )
            """
        )
        self.connection.commit()

    def get_or_create(self, issuer: str, subject: str) -> dict:
        with self._lock:
            return self._get_or_create(issuer, subject)

    def _get_or_create(self, issuer: str, subject: str) -> dict:
        found = self.connection.execute(
            "SELECT local_id, issuer, subject FROM casting_trusted_memberships WHERE issuer = ? AND subject = ?",
            (issuer, subject),
        ).fetchone()
        if found is not None:
            return {"local_id": found[0], "issuer": found[1], "subject": found[2], "created": False}
        local_id = str(uuid.uuid4())
        self.connection.execute(
            "INSERT INTO casting_trusted_memberships (local_id, issuer, subject, created_at) VALUES (?, ?, ?, ?)",
            (local_id, issuer, subject, time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())),
        )
        self.connection.commit()
        return {"local_id": local_id, "issuer": issuer, "subject": subject, "created": True}


def establish_staging_membership(store, verified: VerifiedToken) -> dict:
    if not isinstance(verified, VerifiedToken):
        raise TrustedSigninRejected("subject")
    row = store.get_or_create(verified.issuer, verified.subject)
    if not isinstance(row, dict):
        raise TrustedSigninRejected("membership")
    allowed = {"local_id", "issuer", "subject", "created"}
    if set(row) - allowed or row.get("issuer") != verified.issuer or row.get("subject") != verified.subject:
        raise TrustedSigninRejected("membership")
    if not row.get("local_id"):
        raise TrustedSigninRejected("membership")
    return {
        "local_id": str(row["local_id"]),
        "issuer": verified.issuer,
        "subject": verified.subject,
        "created": bool(row.get("created")),
        "imports_accounts": False,
        "workflows_enabled": False,
    }


def _default_fetch(url: str) -> dict:
    import httpx

    with httpx.Client(timeout=3.0, follow_redirects=False) as client:
        response = client.get(url)
        response.raise_for_status()
        body = response.json()
    if not isinstance(body, dict):
        raise TrustedSigninRejected("discovery")
    return body


def _unconfigured_store():
    raise TrustedSigninRejected("membership")


fetch_json = _default_fetch
store_factory = _unconfigured_store


def _active_ring(decision: dict) -> KeyRing:
    return KeyRing(
        fetch_json,
        decision["active_issuer"],
        decision["proposed_env_ignored"].get("NOVA_CASTING_TRUSTED_JWKS_URL", ""),
    )


@router.get("/trusted-signin")
def trusted_signin_status():
    return public_trusted_signin_status()


@router.post("/trusted-signin/session")
def trusted_signin_session(body: TrustedSigninRequest):
    decision = trusted_signin_decision()
    if not decision["enabled"]:
        raise HTTPException(status_code=403, detail="Trusted Nova sign-in is not enabled")
    try:
        verified = verify_nova_token(
            body.token,
            issuer=decision["active_issuer"],
            audience=decision["active_audience"],
            ring=_active_ring(decision),
        )
        membership = establish_staging_membership(store_factory(), verified)
    except TrustedSigninRejected as exc:
        logger.info("trusted sign-in rejected reason=%s", exc.reason)
        raise HTTPException(status_code=401, detail="Trusted sign-in was rejected") from exc
    return membership
