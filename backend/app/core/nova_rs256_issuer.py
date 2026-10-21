"""Disabled-by-default RS256 issuer for a later Nova review.

Customer sign-in stays on HS256. This module does not read a database, a
password, or the HMAC signing secret. It cannot activate the production
origin. Synthetic tests may publish a JWKS and issue RS256 tokens for a
``.test`` issuer only.
"""
from __future__ import annotations

import base64
import hashlib
import json
import os
import re
import threading
import time
from collections.abc import Mapping
from urllib.parse import urlsplit

from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.asymmetric import padding, rsa
from fastapi import APIRouter, HTTPException
from fastapi.responses import JSONResponse

PROPOSED_ISSUER = "https://amicor-health-isf-py.onrender.com"
PROPOSED_AUDIENCE = "https://amicor-health-isf-py.onrender.com"
PROPOSED_AUDIENCE_BASIS = (
    "JWT_AUDIENCE is unset on current Nova access tokens. The stable public "
    "origin is the proposed audience until a separate production release says otherwise."
)
ROLLBACK = (
    "Set NOVA_RS256_PHASE to publish-only to stop new RS256 tokens while the "
    "JWKS still verifies tokens already issued. Then set the phase to off. "
    "HS256 sessions and opaque refresh tokens stay valid. Outstanding RS256 "
    "access tokens last at most 60 minutes."
)
MAX_TOKEN_LIFETIME_SECONDS = 3600
CLOCK_SKEW_SECONDS = 60
_ENV_NAMES = ("AMICOR_ENVIRONMENT", "ENVIRONMENT", "APP_ENV")
_ALLOWLIST = frozenset({
    "development", "dev", "test", "testing", "local", "staging", "disposable",
})
_PRODUCTION_ENV = frozenset({"production", "prod"})
_PRODUCTION_HOSTS = frozenset({
    "amicor-health-isf-py.onrender.com",
    "amicor-health-isf.onrender.com",
})
_KID = re.compile(r"[A-Za-z0-9._-]{1,128}")
_SUBJECT = re.compile(r"[A-Za-z0-9._:-]{1,200}")
_PHASES = {"off", "publish-only", "issue"}

router = APIRouter(tags=["Nova RS256 issuer"])


class IssuerRejected(Exception):
    def __init__(self, detail: str) -> None:
        self.detail = detail
        super().__init__(detail)


def _b64url(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode("ascii")


def _b64url_decode(value: str) -> bytes:
    if not value or any(char.isspace() for char in value):
        raise IssuerRejected("Invalid token format")
    pad = "=" * (-len(value) % 4)
    try:
        return base64.urlsafe_b64decode(value + pad)
    except Exception as exc:
        raise IssuerRejected("Invalid token format") from exc


def _whole_number(value: object, detail: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise IssuerRejected(detail)
    return value


def _environment_reason(source: Mapping[str, str]) -> str:
    values = []
    for name in _ENV_NAMES:
        raw = source.get(name)
        if raw is None:
            continue
        text = str(raw).strip().lower()
        if text:
            values.append(text)
    if not values:
        return "environment_required"
    if any(value in _PRODUCTION_ENV for value in values):
        return "production_environment_refused"
    if any(value not in _ALLOWLIST for value in values):
        return "environment_rejected"
    if len(set(values)) != 1:
        return "environment_conflict"
    return ""


def _https_origin(value: str):
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
        or parts.path not in ("",)
    ):
        return None
    return parts


def _blocked_identity(value: str) -> bool:
    if not value:
        return False
    if value.rstrip("/") in {PROPOSED_ISSUER, PROPOSED_AUDIENCE}:
        return True
    parts = urlsplit(value)
    host = (parts.hostname or "").lower()
    return bool(host) and (host in _PRODUCTION_HOSTS or host.endswith(".onrender.com"))


def _synthetic_issuer(value: str) -> bool:
    parts = _https_origin(value)
    if parts is None:
        return False
    host = parts.hostname.lower()
    if host in _PRODUCTION_HOSTS or host.endswith(".onrender.com"):
        return False
    return host.endswith(".test")


def _acceptable_audience(value: str) -> bool:
    if not isinstance(value, str) or not value or len(value) > 200:
        return False
    return not any(char.isspace() for char in value)


def _blank_decision(reason: str, *, accepted: bool = False, phase: str = "off") -> dict:
    return {
        "live_issuer_enabled": False,
        "production_activation": False,
        "production_release_approval_required": True,
        "configuration_accepted": accepted,
        "synthetic_tests_enabled": False,
        "phase": phase,
        "reason": reason,
        "accepts_hs256": True,
        "publishes_jwks": False,
        "issues_rs256": False,
        "verifies_rs256": False,
        "active_issuer": "",
        "active_audience": "",
        "proposed_issuer": PROPOSED_ISSUER,
        "proposed_audience": PROPOSED_AUDIENCE,
        "proposed_audience_basis": PROPOSED_AUDIENCE_BASIS,
        "issuance_algorithm": "HS256",
        "max_access_token_lifetime_seconds": MAX_TOKEN_LIFETIME_SECONDS,
        "imports_accounts": False,
        "reads_signing_secret": False,
        "reads_database": False,
        "casting_workflows_enabled": False,
        "payments_enabled": False,
        "outbound_enabled": False,
        "casting_verifier_accepts_production_issuer": False,
        "rollback": ROLLBACK,
    }


class _SyntheticKeys:
    def __init__(self) -> None:
        self._lock = threading.Lock()
        self.active: rsa.RSAPrivateKey | None = None
        self.previous: rsa.RSAPrivateKey | None = None

    def has_active(self) -> bool:
        with self._lock:
            return self.active is not None

    def install(self, active: rsa.RSAPrivateKey, previous: rsa.RSAPrivateKey | None) -> str:
        _require_rsa(active)
        if previous is not None:
            _require_rsa(previous)
            if _kid(previous) == _kid(active):
                raise ValueError("duplicate kid")
        with self._lock:
            self.active = active
            self.previous = previous
        return _kid(active)

    def rotate(self, new_key: rsa.RSAPrivateKey) -> str:
        _require_rsa(new_key)
        new_kid = _kid(new_key)
        with self._lock:
            if self.active is None:
                raise ValueError("no active key")
            existing = {_kid(self.active)}
            if self.previous is not None:
                existing.add(_kid(self.previous))
            if new_kid in existing:
                raise ValueError("duplicate kid")
            self.previous = self.active
            self.active = new_key
        return new_kid

    def retire_previous(self) -> None:
        with self._lock:
            self.previous = None

    def clear(self) -> None:
        with self._lock:
            self.active = None
            self.previous = None

    def signing_key(self) -> rsa.RSAPrivateKey | None:
        with self._lock:
            return self.active

    def public_key(self, kid: str):
        with self._lock:
            keys = [self.active, self.previous]
        for key in keys:
            if key is not None and _kid(key) == kid:
                return key.public_key()
        return None

    def jwks(self) -> dict:
        with self._lock:
            keys = [key for key in (self.active, self.previous) if key is not None]
        return {"keys": [_public_jwk(key) for key in keys]}


_KEYS = _SyntheticKeys()


def _require_rsa(key: object) -> None:
    if not isinstance(key, rsa.RSAPrivateKey) or key.key_size < 2048:
        raise ValueError("rsa key must be at least 2048 bits")


def _jwk_int(value: int) -> str:
    length = max(1, (value.bit_length() + 7) // 8)
    return _b64url(value.to_bytes(length, "big"))


def _public_jwk(private_key: rsa.RSAPrivateKey) -> dict:
    numbers = private_key.public_key().public_numbers()
    modulus = _jwk_int(numbers.n)
    exponent = _jwk_int(numbers.e)
    return {
        "kty": "RSA",
        "use": "sig",
        "alg": "RS256",
        "kid": _thumbprint(modulus, exponent),
        "n": modulus,
        "e": exponent,
    }


def _thumbprint(modulus: str, exponent: str) -> str:
    encoded = json.dumps(
        {"e": exponent, "kty": "RSA", "n": modulus},
        separators=(",", ":"),
        sort_keys=True,
    )
    return _b64url(hashlib.sha256(encoded.encode("utf-8")).digest())


def _kid(private_key: rsa.RSAPrivateKey) -> str:
    return str(_public_jwk(private_key)["kid"])


def issuer_decision(env: Mapping[str, str] | None = None) -> dict:
    """Return the public issuer gate. This never enables the production origin."""
    source = os.environ if env is None else env
    mode = str(source.get("NOVA_RS256_ISSUER", "")).strip().lower()
    if mode in ("", "off", "disabled"):
        return _blank_decision("off")
    if mode != "synthetic":
        return _blank_decision("production_release_approval_required")

    environment_reason = _environment_reason(source)
    if environment_reason:
        return _blank_decision(environment_reason)

    issuer = str(source.get("NOVA_RS256_ISSUER_URL", "")).strip()
    audience = str(source.get("NOVA_RS256_AUDIENCE", "")).strip()
    if _blocked_identity(issuer) or not _synthetic_issuer(issuer):
        reason = "production_issuer_refused" if _blocked_identity(issuer) else "issuer_invalid"
        return _blank_decision(reason)
    if _blocked_identity(audience) or not _acceptable_audience(audience):
        reason = "production_audience_refused" if _blocked_identity(audience) else "audience_invalid"
        return _blank_decision(reason)

    phase_raw = str(source.get("NOVA_RS256_PHASE", "")).strip().lower().replace("_", "-")
    if phase_raw in ("", "off", "disabled"):
        phase = "off"
    elif phase_raw == "publish-only":
        phase = "publish-only"
    elif phase_raw == "issue":
        phase = "issue"
    else:
        return _blank_decision("unknown_phase")

    decision = _blank_decision("synthetic_phase_off" if phase == "off" else "synthetic", accepted=True, phase=phase)
    decision["active_issuer"] = issuer
    decision["active_audience"] = audience
    if phase == "off":
        return decision
    if not _KEYS.has_active():
        decision["reason"] = "signing_keys_not_installed"
        return decision
    decision["synthetic_tests_enabled"] = True
    decision["publishes_jwks"] = True
    decision["verifies_rs256"] = True
    if phase == "issue":
        decision["issues_rs256"] = True
        decision["issuance_algorithm"] = "RS256"
    return decision


def install_synthetic_keys(
    active: rsa.RSAPrivateKey,
    previous: rsa.RSAPrivateKey | None = None,
) -> str:
    if not issuer_decision()["configuration_accepted"]:
        raise RuntimeError("synthetic issuer configuration is not accepted")
    return _KEYS.install(active, previous)


def rotate_synthetic_key(new_key: rsa.RSAPrivateKey) -> str:
    if not issuer_decision()["configuration_accepted"]:
        raise RuntimeError("synthetic issuer configuration is not accepted")
    return _KEYS.rotate(new_key)


def retire_previous_synthetic_key() -> None:
    if not issuer_decision()["configuration_accepted"]:
        raise RuntimeError("synthetic issuer configuration is not accepted")
    _KEYS.retire_previous()


def clear_synthetic_keys() -> None:
    _KEYS.clear()


def _bounded_lifetime(lifetime_seconds: int) -> int:
    if isinstance(lifetime_seconds, bool) or not isinstance(lifetime_seconds, int) or lifetime_seconds <= 0:
        raise IssuerRejected("Token payload invalid")
    return min(lifetime_seconds, MAX_TOKEN_LIFETIME_SECONDS)


def _token_payload(claims: Mapping, issuer: str, audience: str, lifetime: int, now: float) -> dict:
    if not isinstance(claims, Mapping):
        raise IssuerRejected("Token payload invalid")
    subject = claims.get("sub")
    if not isinstance(subject, str) or _SUBJECT.fullmatch(subject) is None or "@" in subject:
        raise IssuerRejected("Token payload invalid")
    issued_at = int(now)
    payload = {
        key: value
        for key, value in claims.items()
        if key not in {"iss", "aud", "iat", "exp", "nbf"}
    }
    payload["sub"] = subject
    payload["iss"] = issuer
    payload["aud"] = audience
    payload["iat"] = issued_at
    payload["exp"] = issued_at + lifetime
    try:
        json.dumps(payload, separators=(",", ":"))
    except TypeError as exc:
        raise IssuerRejected("Token payload invalid") from exc
    return payload


def _sign(private_key: rsa.RSAPrivateKey, payload: dict) -> str:
    header = {"alg": "RS256", "typ": "JWT", "kid": _kid(private_key)}
    head = _b64url(json.dumps(header, separators=(",", ":")).encode("utf-8"))
    body = _b64url(json.dumps(payload, separators=(",", ":")).encode("utf-8"))
    signing = f"{head}.{body}".encode("ascii")
    signature = private_key.sign(signing, padding.PKCS1v15(), hashes.SHA256())
    return f"{head}.{body}.{_b64url(signature)}"


def issue_if_enabled(claims: Mapping, lifetime_seconds: int, now: float | None = None) -> str | None:
    """Return an RS256 token only while the synthetic issue phase is fully armed."""
    decision = issuer_decision()
    if not decision["issues_rs256"]:
        return None
    private_key = _KEYS.signing_key()
    if private_key is None:
        raise IssuerRejected("Token signature invalid")
    current = time.time() if now is None else float(now)
    payload = _token_payload(
        claims,
        decision["active_issuer"],
        decision["active_audience"],
        _bounded_lifetime(lifetime_seconds),
        current,
    )
    return _sign(private_key, payload)


def _json_object(segment: str) -> dict:
    try:
        value = json.loads(_b64url_decode(segment))
    except IssuerRejected:
        raise
    except Exception as exc:
        raise IssuerRejected("Invalid token format") from exc
    if not isinstance(value, dict):
        raise IssuerRejected("Invalid token format")
    return value


def verify_local_rs256(token: str, now: float | None = None) -> dict:
    """Verify one locally issued RS256 token. HS256 is not handled here."""
    decision = issuer_decision()
    if not decision["verifies_rs256"]:
        raise IssuerRejected("Token signature invalid")
    if not isinstance(token, str) or token.count(".") != 2:
        raise IssuerRejected("Invalid token format")
    header_segment, body_segment, signature_segment = token.split(".")
    header = _json_object(header_segment)
    if header.get("alg") != "RS256" or header.get("typ", "JWT") not in (None, "JWT"):
        raise IssuerRejected("Token signature invalid")
    if any(name in header for name in ("crit", "jwk", "x5c")):
        raise IssuerRejected("Token signature invalid")
    kid = header.get("kid")
    if not isinstance(kid, str) or _KID.fullmatch(kid) is None:
        raise IssuerRejected("Token signature invalid")
    public_key = _KEYS.public_key(kid)
    if public_key is None:
        raise IssuerRejected("Token signature invalid")
    try:
        signature = _b64url_decode(signature_segment)
        signing_input = token.rsplit(".", 1)[0].encode("ascii")
        public_key.verify(signature, signing_input, padding.PKCS1v15(), hashes.SHA256())
    except IssuerRejected:
        raise
    except InvalidSignature as exc:
        raise IssuerRejected("Token signature invalid") from exc
    except Exception as exc:
        raise IssuerRejected("Token signature invalid") from exc

    payload = _json_object(body_segment)
    if payload.get("iss") != decision["active_issuer"]:
        raise IssuerRejected("Token issuer invalid")
    audience = payload.get("aud")
    if isinstance(audience, list) or audience != decision["active_audience"]:
        raise IssuerRejected("Token audience invalid")
    current = time.time() if now is None else float(now)
    expires_at = _whole_number(payload.get("exp"), "Token payload invalid")
    if current > expires_at + CLOCK_SKEW_SECONDS:
        raise IssuerRejected("Token expired")
    if "nbf" in payload:
        not_before = _whole_number(payload.get("nbf"), "Token payload invalid")
        if current + CLOCK_SKEW_SECONDS < not_before:
            raise IssuerRejected("Token expired")
    if "iat" in payload:
        issued_at = _whole_number(payload.get("iat"), "Token payload invalid")
        if issued_at > current + CLOCK_SKEW_SECONDS or expires_at - issued_at <= 0:
            raise IssuerRejected("Token expired")
        if expires_at - issued_at > MAX_TOKEN_LIFETIME_SECONDS:
            raise IssuerRejected("Token expired")
    elif expires_at > current + MAX_TOKEN_LIFETIME_SECONDS + CLOCK_SKEW_SECONDS:
        raise IssuerRejected("Token expired")
    subject = payload.get("sub")
    if not isinstance(subject, str) or _SUBJECT.fullmatch(subject) is None or "@" in subject:
        raise IssuerRejected("Token payload invalid")
    return payload


def _document(body: dict, status_code: int = 200) -> JSONResponse:
    return JSONResponse(body, status_code=status_code, headers={"Cache-Control": "no-store"})


@router.get("/.well-known/jwks.json")
def jwks():
    decision = issuer_decision()
    if not decision["publishes_jwks"]:
        raise HTTPException(status_code=404, detail="Not found")
    document = _KEYS.jwks()
    if not document["keys"]:
        raise HTTPException(status_code=404, detail="Not found")
    return _document(document)


@router.get("/.well-known/openid-configuration")
def openid_configuration():
    decision = issuer_decision()
    if not decision["publishes_jwks"]:
        raise HTTPException(status_code=404, detail="Not found")
    issuer = decision["active_issuer"]
    return _document({
        "issuer": issuer,
        "jwks_uri": issuer + "/.well-known/jwks.json",
        "id_token_signing_alg_values_supported": ["RS256"],
        "response_types_supported": ["token"],
        "subject_types_supported": ["public"],
    })


@router.get("/api/auth/rs256-issuer")
def rs256_issuer_status():
    return _document(issuer_decision())
