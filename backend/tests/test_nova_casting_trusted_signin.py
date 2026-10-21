"""Synthetic staging RS256 sign-in. These tests do not contact main Nova or import accounts."""
from __future__ import annotations

import base64
import hashlib
import hmac
import inspect
import json
import time
from pathlib import Path

import pytest
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.asymmetric import padding, rsa
from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient

from app.auth import TOKEN_SIGNING_SECRET, _b64url_encode, _jwt_sign, _jwt_verify
from app.core import casting_trusted_signin as signin
from app.core.casting_trusted_signin import (
    BLOCKER,
    OWNER_DECISIONS,
    PROPOSED_AUDIENCE,
    PROPOSED_ENV_NAMES,
    PROPOSED_ISSUER,
    KeyRing,
    SqliteMembershipStore,
    TrustedSigninRejected,
    VerifiedToken,
    establish_staging_membership,
    trusted_signin_decision,
    verify_nova_token,
)

ISSUER = "https://signin.nova-staging.test"
AUDIENCE = "https://signin.nova-staging.test"
SUBJECT = "11111111-1111-4111-8111-111111111111"
OTHER_SUBJECT = "22222222-2222-4222-8222-222222222222"
JWKS_URL = ISSUER + "/jwks"
DRAFT = Path(__file__).resolve().parents[1] / "app" / "core" / "nova" / "creative_studio" / "casting_router_draft.py"

_PRIMARY = rsa.generate_private_key(public_exponent=65537, key_size=2048)
_SECONDARY = rsa.generate_private_key(public_exponent=65537, key_size=2048)
_SMALL = rsa.generate_private_key(public_exponent=65537, key_size=1024)


def _b64(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode()


def _public_jwk(private_key, kid: str) -> dict:
    numbers = private_key.public_key().public_numbers()

    def enc(value: int) -> str:
        length = (value.bit_length() + 7) // 8
        return _b64(value.to_bytes(length, "big"))

    return {
        "kty": "RSA",
        "use": "sig",
        "alg": "RS256",
        "kid": kid,
        "n": enc(numbers.n),
        "e": enc(numbers.e),
    }


def _sign(private_key, kid: str, payload: dict, *, alg: str = "RS256", header: dict | None = None) -> str:
    token_header = {"alg": alg, "typ": "JWT", "kid": kid}
    if header:
        token_header.update(header)
    head = _b64(json.dumps(token_header, separators=(",", ":")).encode())
    body = _b64(json.dumps(payload, separators=(",", ":")).encode())
    signing = f"{head}.{body}".encode()
    if alg == "none":
        return f"{head}.{body}."
    signature = private_key.sign(signing, padding.PKCS1v15(), hashes.SHA256())
    return f"{head}.{body}.{_b64(signature)}"


def _payload(**overrides) -> dict:
    now = int(time.time())
    body = {
        "iss": ISSUER,
        "aud": AUDIENCE,
        "sub": SUBJECT,
        "iat": now,
        "exp": now + 600,
        "email": "person@example.com",
        "role": "owner",
    }
    body.update(overrides)
    return body


def _ring(fetch, jwks_url: str = JWKS_URL, now=None) -> KeyRing:
    return KeyRing(fetch, ISSUER, jwks_url, now=now)


def _keys(jwk: dict):
    def fetch(url: str):
        assert url == JWKS_URL
        return {"keys": [jwk]}

    return fetch


def _assert_stays_off(decision: dict) -> None:
    assert decision["supported"] is False
    assert decision["enabled"] is False
    assert decision["staging_tests_enabled"] is False
    assert decision["imports_accounts"] is False
    assert decision["shares_database"] is False
    assert decision["shares_signing_key"] is False
    assert decision["shares_passwords"] is False
    assert decision["validates_remote_token"] is False
    assert decision["workflows_enabled"] is False
    assert decision["applications_enabled"] is False
    assert decision["media_uploads_enabled"] is False
    assert decision["outbound_enabled"] is False
    assert decision["payments_enabled"] is False
    assert decision["production_integration"] is False
    assert decision["production_issuer_activated"] is False
    assert decision["issuer_side_change_required"] is True
    assert decision["algorithm"] == "HS256"
    assert decision["verifier"] == "local-hmac"
    assert decision["proposed_issuer"] == PROPOSED_ISSUER
    assert decision["proposed_audience"] == PROPOSED_AUDIENCE
    assert decision["active_issuer"] == ""
    assert decision["blocker"] == BLOCKER
    assert decision["owner_decisions"] == list(OWNER_DECISIONS)
    assert "JWKS" in decision["blocker"]
    assert "platform_users" in decision["blocker"]


def _staging_env(**overrides) -> dict:
    env = {
        "AMICOR_ENVIRONMENT": "staging",
        "NOVA_CASTING_TRUSTED_SIGNIN": "staging",
        "NOVA_CASTING_TRUSTED_ISSUER": ISSUER,
        "NOVA_CASTING_TRUSTED_AUDIENCE": AUDIENCE,
        "NOVA_CASTING_TRUSTED_JWKS_URL": JWKS_URL,
    }
    env.update(overrides)
    return env


def test_trusted_signin_is_off_with_no_proposed_configuration() -> None:
    decision = trusted_signin_decision({})
    _assert_stays_off(decision)
    assert decision["proposed_env_ignored"] == {name: "" for name in PROPOSED_ENV_NAMES}
    blob = json.dumps(decision["proposed_env_ignored"])
    assert "postgresql://" not in blob
    assert blob == json.dumps({name: "" for name in PROPOSED_ENV_NAMES})


def test_proposed_environment_cannot_enable_remote_verification() -> None:
    decision = trusted_signin_decision({
        "NOVA_CASTING_TRUSTED_SIGNIN": "true",
        "NOVA_CASTING_TRUSTED_ISSUER": "https://amicor-health-isf-py.onrender.com",
        "NOVA_CASTING_TRUSTED_AUDIENCE": "nova-casting-preview",
        "NOVA_CASTING_TRUSTED_JWKS_URL": "https://amicor-health-isf-py.onrender.com/.well-known/jwks.json",
        "DATABASE_URL": "postgresql://must-not-be-read",
        "JWT_SECRET": "must-not-be-read",
        "SECRET_KEY": "must-not-be-read",
    })
    _assert_stays_off(decision)
    assert decision["proposed_env_ignored"]["NOVA_CASTING_TRUSTED_SIGNIN"] == "true"
    assert "must-not-be-read" not in json.dumps(decision)


def test_current_process_environment_cannot_turn_shared_signin_on(monkeypatch) -> None:
    for name in PROPOSED_ENV_NAMES:
        monkeypatch.setenv(name, "approved")
    monkeypatch.setenv("DATABASE_URL", "postgresql://must-not-be-read")
    decision = trusted_signin_decision()
    _assert_stays_off(decision)
    assert set(decision["proposed_env_ignored"]) == set(PROPOSED_ENV_NAMES)
    assert all(value == "approved" for value in decision["proposed_env_ignored"].values())


def test_production_issuer_stays_inactive_even_in_staging() -> None:
    decision = trusted_signin_decision(_staging_env(
        NOVA_CASTING_TRUSTED_ISSUER="https://amicor-health-isf-py.onrender.com",
        NOVA_CASTING_TRUSTED_AUDIENCE="https://amicor-health-isf-py.onrender.com",
        NOVA_CASTING_TRUSTED_JWKS_URL="https://amicor-health-isf-py.onrender.com/.well-known/jwks.json",
    ))
    _assert_stays_off(decision)
    assert "separate" in decision["issuer_side_decision"]
    calls = []
    with pytest.raises(TrustedSigninRejected) as rejected:
        KeyRing(lambda url: calls.append(url), PROPOSED_ISSUER)
    assert rejected.value.reason == "issuer"
    assert calls == []


def test_conflicting_or_production_environment_stays_off() -> None:
    conflict = trusted_signin_decision(_staging_env(ENVIRONMENT="production"))
    missing = trusted_signin_decision({
        "NOVA_CASTING_TRUSTED_SIGNIN": "staging",
        "NOVA_CASTING_TRUSTED_ISSUER": ISSUER,
        "NOVA_CASTING_TRUSTED_AUDIENCE": AUDIENCE,
    })
    preview_host = trusted_signin_decision(_staging_env(
        NOVA_CASTING_TRUSTED_ISSUER="https://amicor-health-isf-pr-339.onrender.com",
        NOVA_CASTING_TRUSTED_JWKS_URL="https://amicor-health-isf-pr-339.onrender.com/jwks",
    ))
    _assert_stays_off(conflict)
    _assert_stays_off(missing)
    _assert_stays_off(preview_host)


def test_synthetic_staging_configuration_enables_verification_only() -> None:
    decision = trusted_signin_decision(_staging_env(DATABASE_URL="postgresql://must-not-be-read"))
    assert decision["supported"] is False
    assert decision["enabled"] is True
    assert decision["staging_tests_enabled"] is True
    assert decision["validates_remote_token"] is True
    assert decision["production_integration"] is False
    assert decision["production_issuer_activated"] is False
    assert decision["imports_accounts"] is False
    assert decision["shares_database"] is False
    assert decision["shares_signing_key"] is False
    assert decision["shares_passwords"] is False
    assert decision["workflows_enabled"] is False
    assert decision["payments_enabled"] is False
    assert decision["active_issuer"] == ISSUER
    assert decision["verifier"] == "local-hmac"
    assert decision["trusted_algorithm"] == "RS256"
    assert "must-not-be-read" not in json.dumps(decision)


def test_a_verified_token_creates_one_local_membership_without_a_password(tmp_path) -> None:
    jwk = _public_jwk(_PRIMARY, "current")
    now = time.time()
    token = _sign(_PRIMARY, "current", _payload(email="person@example.com"))
    verified = verify_nova_token(
        token,
        issuer=ISSUER,
        audience=AUDIENCE,
        ring=_ring(_keys(jwk)),
        now=now,
    )
    assert verified.subject == SUBJECT
    assert not hasattr(verified, "email")
    store = SqliteMembershipStore(str(tmp_path / "members.sqlite"))
    first = establish_staging_membership(store, verified)
    second = establish_staging_membership(store, verified)
    other = establish_staging_membership(
        store,
        verify_nova_token(
            _sign(_PRIMARY, "current", _payload(sub=OTHER_SUBJECT)),
            issuer=ISSUER,
            audience=AUDIENCE,
            ring=_ring(_keys(jwk)),
            now=now,
        ),
    )
    assert first["created"] is True
    assert second["created"] is False
    assert first["local_id"] == second["local_id"]
    assert other["local_id"] != first["local_id"]
    assert first["imports_accounts"] is False
    assert "password" not in first
    columns = [
        row[1]
        for row in store.connection.execute("PRAGMA table_info(casting_trusted_memberships)")
    ]
    assert columns == ["local_id", "issuer", "subject", "created_at"]
    saved = store.connection.execute("SELECT issuer, subject FROM casting_trusted_memberships").fetchall()
    assert (ISSUER, SUBJECT) in saved
    assert "person@example.com" not in json.dumps(saved)
    with pytest.raises(TrustedSigninRejected):
        VerifiedToken(ISSUER, AUDIENCE, SUBJECT, int(now) + 60, "current", object())


def test_signature_issuer_audience_expiry_and_subject_fail_closed() -> None:
    jwk = _public_jwk(_PRIMARY, "current")
    now = time.time()
    valid = _sign(_PRIMARY, "current", _payload())
    tampered = valid.rsplit(".", 1)[0] + ".aaaa"
    cases = {
        "signature": _sign(_SECONDARY, "current", _payload()),
        "issuer": _sign(_PRIMARY, "current", _payload(iss="https://other.nova-staging.test")),
        "audience": _sign(_PRIMARY, "current", _payload(aud="https://elsewhere.nova-staging.test")),
        "expired": _sign(_PRIMARY, "current", _payload(exp=int(now) - 120)),
        "subject": _sign(_PRIMARY, "current", _payload(sub="person@example.com")),
    }
    verified = verify_nova_token(valid, issuer=ISSUER, audience=AUDIENCE, ring=_ring(_keys(jwk)), now=now)
    assert verified.subject == SUBJECT
    with pytest.raises(TrustedSigninRejected) as malformed:
        verify_nova_token(tampered, issuer=ISSUER, audience=AUDIENCE, ring=_ring(_keys(jwk)), now=now)
    assert malformed.value.reason in {"signature", "malformed"}
    for reason, token in cases.items():
        with pytest.raises(TrustedSigninRejected) as rejected:
            verify_nova_token(token, issuer=ISSUER, audience=AUDIENCE, ring=_ring(_keys(jwk)), now=now)
        assert rejected.value.reason == reason
    missing_exp = _payload()
    del missing_exp["exp"]
    with pytest.raises(TrustedSigninRejected) as expired:
        verify_nova_token(
            _sign(_PRIMARY, "current", missing_exp),
            issuer=ISSUER,
            audience=AUDIENCE,
            ring=_ring(_keys(jwk)),
            now=now,
        )
    assert expired.value.reason == "expired"
    with pytest.raises(TrustedSigninRejected) as too_long:
        verify_nova_token(
            _sign(_PRIMARY, "current", _payload(exp=int(now) + 7200)),
            issuer=ISSUER,
            audience=AUDIENCE,
            ring=_ring(_keys(jwk)),
            now=now,
        )
    assert too_long.value.reason == "expired"


def test_hmac_none_and_embedded_keys_are_rejected_before_a_fetch() -> None:
    calls = []

    def fetch(url: str):
        calls.append(url)
        return {"keys": [_public_jwk(_PRIMARY, "current")]}

    now = time.time()
    hmac_token = _sign(_PRIMARY, "current", _payload(), alg="HS256")
    none_token = _sign(_PRIMARY, "current", _payload(), alg="none")
    embedded = _sign(_PRIMARY, "current", _payload(), header={"jwk": {"kty": "RSA"}})
    for token in (hmac_token, none_token, embedded):
        with pytest.raises(TrustedSigninRejected) as rejected:
            verify_nova_token(token, issuer=ISSUER, audience=AUDIENCE, ring=_ring(fetch), now=now)
        assert rejected.value.reason == "algorithm"
    assert calls == []


def test_unknown_kid_refreshes_once_and_a_failed_refresh_does_not_reuse_a_stale_key() -> None:
    clock = {"now": time.time()}
    issued = int(clock["now"])
    body = _payload(iat=issued, exp=issued + 600)
    published = {"keys": [_public_jwk(_PRIMARY, "old")]}
    calls = []

    def fetch(url: str):
        calls.append(url)
        return {"keys": list(published["keys"])}

    ring = _ring(fetch, now=lambda: clock["now"])
    current = verify_nova_token(
        _sign(_PRIMARY, "old", body),
        issuer=ISSUER,
        audience=AUDIENCE,
        ring=ring,
        now=clock["now"],
    )
    assert current.kid == "old"
    assert len(calls) == 1
    verify_nova_token(
        _sign(_PRIMARY, "old", body),
        issuer=ISSUER,
        audience=AUDIENCE,
        ring=ring,
        now=clock["now"],
    )
    assert len(calls) == 1
    published["keys"] = [_public_jwk(_SECONDARY, "new")]
    rotated = verify_nova_token(
        _sign(_SECONDARY, "new", body),
        issuer=ISSUER,
        audience=AUDIENCE,
        ring=ring,
        now=clock["now"],
    )
    assert rotated.kid == "new"
    assert len(calls) == 2

    def serve_old(url: str):
        return {"keys": [_public_jwk(_PRIMARY, "old")]}

    def fail(url: str):
        raise RuntimeError("jwks unavailable")

    stale = _ring(serve_old, now=lambda: clock["now"])
    verify_nova_token(
        _sign(_PRIMARY, "old", body),
        issuer=ISSUER,
        audience=AUDIENCE,
        ring=stale,
        now=clock["now"],
    )
    stale.fetch = fail
    clock["now"] += signin.KEY_CACHE_SECONDS + 1
    with pytest.raises(TrustedSigninRejected) as rejected:
        verify_nova_token(
            _sign(_PRIMARY, "old", body),
            issuer=ISSUER,
            audience=AUDIENCE,
            ring=stale,
            now=clock["now"],
        )
    assert rejected.value.reason == "key"


def test_discovery_must_match_the_issuer_and_jwks_host() -> None:
    calls = []

    def wrong_issuer(url: str):
        calls.append(url)
        return {"issuer": "https://evil.nova-staging.test", "jwks_uri": JWKS_URL}

    ring = KeyRing(wrong_issuer, ISSUER)
    with pytest.raises(TrustedSigninRejected) as rejected:
        ring.public_key("current")
    assert rejected.value.reason == "discovery"
    assert calls == [ISSUER + "/.well-known/openid-configuration"]

    def other_host(url: str):
        calls.append(url)
        return {"issuer": ISSUER, "jwks_uri": "https://keys.other.test/jwks"}

    calls.clear()
    with pytest.raises(TrustedSigninRejected) as rejected:
        KeyRing(other_host, ISSUER).public_key("current")
    assert rejected.value.reason == "discovery"
    assert calls == [ISSUER + "/.well-known/openid-configuration"]


def test_small_and_duplicate_keys_are_rejected() -> None:
    with pytest.raises(TrustedSigninRejected) as small:
        signin._parse_jwks({"keys": [_public_jwk(_SMALL, "small")]})
    assert small.value.reason == "key"
    duplicate = _public_jwk(_PRIMARY, "current")
    with pytest.raises(TrustedSigninRejected) as rejected:
        signin._parse_jwks({"keys": [duplicate, dict(duplicate)]})
    assert rejected.value.reason == "key"


def test_openid_discovery_selects_the_jwks() -> None:
    jwk = _public_jwk(_PRIMARY, "current")

    def fetch(url: str):
        if url.endswith("/.well-known/openid-configuration"):
            return {"issuer": ISSUER, "jwks_uri": JWKS_URL}
        assert url == JWKS_URL
        return {"keys": [jwk]}

    verified = verify_nova_token(
        _sign(_PRIMARY, "current", _payload()),
        issuer=ISSUER,
        audience=AUDIENCE,
        ring=KeyRing(fetch, ISSUER),
        now=time.time(),
    )
    assert verified.subject == SUBJECT


def _client() -> TestClient:
    app = FastAPI()
    app.include_router(signin.router, prefix="/api/nova/casting")
    return TestClient(app)


def test_status_and_session_stay_closed_without_a_fetch(monkeypatch) -> None:
    calls = []
    monkeypatch.setattr(signin, "fetch_json", lambda url: calls.append(url))
    for name in ("NOVA_CASTING_TRUSTED_SIGNIN", "AMICOR_ENVIRONMENT", "ENVIRONMENT", "APP_ENV"):
        monkeypatch.delenv(name, raising=False)
    client = _client()
    status = client.get("/api/nova/casting/trusted-signin")
    assert status.status_code == 200
    body = status.json()
    assert body["enabled"] is False
    assert body["supported"] is False
    assert body["production_integration"] is False
    assert body["production_issuer_activated"] is False
    assert body["issuer_side_change_required"] is True
    assert body["proposed_issuer"] == "https://amicor-health-isf-py.onrender.com"
    assert body["proposed_audience"] == "https://amicor-health-isf-py.onrender.com"
    assert body["workflows_enabled"] is False
    assert body["applications_enabled"] is False
    assert body["media_uploads_enabled"] is False
    assert body["outbound_enabled"] is False
    assert body["payments_enabled"] is False
    assert "postgresql://" not in status.text
    assert "JWT_SECRET" not in status.text
    posted = client.post("/api/nova/casting/trusted-signin/session", json={
        "token": "header.payload.signature",
        "password": "not-used",
        "email": "person@example.com",
    })
    assert posted.status_code == 403
    assert posted.json()["detail"] == "Trusted Nova sign-in is not enabled"
    assert calls == []


def test_staging_session_accepts_only_a_verified_subject(monkeypatch, tmp_path) -> None:
    for name in ("ENVIRONMENT", "APP_ENV", "NOVA_CASTING_STAGING_READS"):
        monkeypatch.delenv(name, raising=False)
    for name, value in _staging_env().items():
        monkeypatch.setenv(name, value)
    jwk = _public_jwk(_PRIMARY, "current")
    calls = []

    def fetch(url: str):
        calls.append(url)
        return {"keys": [jwk]}

    store = SqliteMembershipStore(str(tmp_path / "members.sqlite"))
    monkeypatch.setattr(signin, "fetch_json", fetch)
    monkeypatch.setattr(signin, "store_factory", lambda: store)
    client = _client()
    token = _sign(_PRIMARY, "current", _payload())
    first = client.post("/api/nova/casting/trusted-signin/session", json={"token": token, "password": "not-used"})
    second = client.post("/api/nova/casting/trusted-signin/session", json={"token": token})
    assert first.status_code == 200
    assert second.status_code == 200
    assert first.json()["local_id"] == second.json()["local_id"]
    assert first.json()["subject"] == SUBJECT
    assert first.json()["workflows_enabled"] is False
    assert "password" not in first.text
    assert "person@example.com" not in first.text
    assert calls == [JWKS_URL, JWKS_URL]
    from app.core.nova.creative_studio.casting_flags import casting_staging_reads_enabled
    assert casting_staging_reads_enabled() is False
    rejected = client.post("/api/nova/casting/trusted-signin/session", json={"token": _sign(_SECONDARY, "current", _payload())})
    assert rejected.status_code == 401
    assert rejected.json()["detail"] == "Trusted sign-in was rejected"
    draft = DRAFT.read_text(encoding="utf-8")
    assert "trusted_signin_router" in draft
    assert "follow_redirects=False" in inspect.getsource(signin._default_fetch)
    assert "platform_users" not in inspect.getsource(SqliteMembershipStore)
    assert "JWT_SECRET" not in inspect.getsource(verify_nova_token)
    assert "DATABASE_URL" not in inspect.getsource(trusted_signin_decision)


def _foreign_token(secret: bytes) -> str:
    header = _b64url_encode(json.dumps({"alg": "HS256", "typ": "JWT"}).encode())
    body = _b64url_encode(json.dumps({"sub": "main-nova", "exp": time.time() + 60}).encode())
    signature = hmac.new(secret, f"{header}.{body}".encode(), hashlib.sha256).digest()
    return f"{header}.{body}.{_b64url_encode(signature)}"


def test_a_token_from_another_signing_secret_is_rejected_locally() -> None:
    source = inspect.getsource(_jwt_verify)
    assert "jwks" not in source.lower()
    assert "urlopen" not in source
    assert "httpx" not in source
    assert "requests." not in source
    local = _jwt_sign({"sub": "preview-user", "exp": time.time() + 60})
    assert _jwt_verify(local)["sub"] == "preview-user"
    foreign = _foreign_token(b"different-signing-secret")
    assert TOKEN_SIGNING_SECRET.encode() != b"different-signing-secret"
    with pytest.raises(HTTPException) as rejected:
        _jwt_verify(foreign)
    assert rejected.value.status_code == 401
    assert rejected.value.detail == "Token signature invalid"
