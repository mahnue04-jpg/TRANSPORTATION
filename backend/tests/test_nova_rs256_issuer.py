"""Synthetic RS256 issuer. These tests do not contact Nova or read a password."""
from __future__ import annotations

import base64
import json
from pathlib import Path

import pytest
from cryptography.hazmat.primitives.asymmetric import rsa
from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient

from app.auth import (
    ACCESS_TOKEN_EXPIRE_MINUTES,
    _jwt_sign,
    _jwt_verify,
    create_access_token,
    create_refresh_token,
)
from app.core.nova_rs256_issuer import (
    PROPOSED_AUDIENCE,
    PROPOSED_ISSUER,
    IssuerRejected,
    clear_synthetic_keys,
    install_synthetic_keys,
    issue_if_enabled,
    issuer_decision,
    retire_previous_synthetic_key,
    rotate_synthetic_key,
    router,
    verify_local_rs256,
)

ISSUER = "https://signin.nova-staging.test"
AUDIENCE = "https://signin.nova-staging.test"
SUBJECT = "11111111-1111-4111-8111-111111111111"
BACKEND = Path(__file__).resolve().parents[1]


@pytest.fixture(scope="module")
def rsa_keys():
    primary = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    secondary = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    return primary, secondary


@pytest.fixture(autouse=True)
def _reset_issuer(monkeypatch):
    for name in (
        "NOVA_RS256_ISSUER",
        "NOVA_RS256_PHASE",
        "NOVA_RS256_ISSUER_URL",
        "NOVA_RS256_AUDIENCE",
        "AMICOR_ENVIRONMENT",
        "ENVIRONMENT",
        "APP_ENV",
    ):
        monkeypatch.delenv(name, raising=False)
    clear_synthetic_keys()
    yield
    clear_synthetic_keys()


def _arm(monkeypatch, phase: str = "issue") -> None:
    monkeypatch.setenv("NOVA_RS256_ISSUER", "synthetic")
    monkeypatch.setenv("NOVA_RS256_PHASE", phase)
    monkeypatch.setenv("NOVA_RS256_ISSUER_URL", ISSUER)
    monkeypatch.setenv("NOVA_RS256_AUDIENCE", AUDIENCE)
    monkeypatch.setenv("ENVIRONMENT", "test")


def _claims() -> dict:
    return {
        "sub": SUBJECT,
        "email": "synthetic@example.com",
        "role": "owner",
        "organization_id": "org-1",
        "auth_version": 0,
    }


def _segment(segment: str) -> dict:
    pad = "=" * (-len(segment) % 4)
    return json.loads(base64.urlsafe_b64decode(segment + pad))


def _assert_closed(decision: dict, reason: str) -> None:
    assert decision["reason"] == reason
    assert decision["live_issuer_enabled"] is False
    assert decision["production_activation"] is False
    assert decision["production_release_approval_required"] is True
    assert decision["configuration_accepted"] is False
    assert decision["synthetic_tests_enabled"] is False
    assert decision["publishes_jwks"] is False
    assert decision["issues_rs256"] is False
    assert decision["verifies_rs256"] is False
    assert decision["accepts_hs256"] is True
    assert decision["active_issuer"] == ""
    assert decision["imports_accounts"] is False
    assert decision["reads_signing_secret"] is False
    assert decision["reads_database"] is False
    assert decision["casting_workflows_enabled"] is False
    assert decision["payments_enabled"] is False
    assert decision["outbound_enabled"] is False
    assert decision["casting_verifier_accepts_production_issuer"] is False
    assert decision["proposed_issuer"] == PROPOSED_ISSUER
    assert decision["proposed_audience"] == PROPOSED_AUDIENCE
    assert decision["issuance_algorithm"] == "HS256"


def test_default_gate_stays_off_and_hs256_bytes_are_unchanged(monkeypatch) -> None:
    decision = issuer_decision()
    _assert_closed(decision, "off")
    fixed = 1_700_000_000.0
    monkeypatch.setattr("app.auth.time.time", lambda: fixed)
    data = _claims()
    token = create_access_token(data)
    expected = {**data, "exp": fixed + ACCESS_TOKEN_EXPIRE_MINUTES * 60}
    assert token == _jwt_sign(expected)
    assert _segment(token.split(".")[0])["alg"] == "HS256"
    assert _jwt_verify(token)["email"] == "synthetic@example.com"
    assert "." not in create_refresh_token()
    app = FastAPI()
    app.include_router(router)
    client = TestClient(app)
    assert client.get("/.well-known/jwks.json").status_code == 404
    assert client.get("/.well-known/openid-configuration").status_code == 404
    status = client.get("/api/auth/rs256-issuer")
    assert status.status_code == 200
    assert status.json()["live_issuer_enabled"] is False
    assert "sqlite" not in status.text


def test_production_values_cannot_arm_the_issuer() -> None:
    approved = issuer_decision({
        "NOVA_RS256_ISSUER": "approved",
        "NOVA_RS256_PHASE": "issue",
        "NOVA_RS256_ISSUER_URL": PROPOSED_ISSUER,
        "NOVA_RS256_AUDIENCE": PROPOSED_AUDIENCE,
        "ENVIRONMENT": "production",
    })
    _assert_closed(approved, "production_release_approval_required")

    production_env = issuer_decision({
        "NOVA_RS256_ISSUER": "synthetic",
        "NOVA_RS256_PHASE": "issue",
        "NOVA_RS256_ISSUER_URL": ISSUER,
        "NOVA_RS256_AUDIENCE": AUDIENCE,
        "ENVIRONMENT": "production",
        "APP_ENV": "production",
    })
    _assert_closed(production_env, "production_environment_refused")

    production_issuer = issuer_decision({
        "NOVA_RS256_ISSUER": "synthetic",
        "NOVA_RS256_PHASE": "issue",
        "NOVA_RS256_ISSUER_URL": PROPOSED_ISSUER,
        "NOVA_RS256_AUDIENCE": AUDIENCE,
        "ENVIRONMENT": "test",
    })
    _assert_closed(production_issuer, "production_issuer_refused")

    conflict = issuer_decision({
        "NOVA_RS256_ISSUER": "synthetic",
        "NOVA_RS256_PHASE": "issue",
        "NOVA_RS256_ISSUER_URL": ISSUER,
        "NOVA_RS256_AUDIENCE": AUDIENCE,
        "ENVIRONMENT": "test",
        "APP_ENV": "staging",
    })
    _assert_closed(conflict, "environment_conflict")
    assert issue_if_enabled(_claims(), 600) is None
    with pytest.raises(RuntimeError):
        install_synthetic_keys(None)  # type: ignore[arg-type]


def test_uninstalled_key_keeps_hs256_sign_in(monkeypatch) -> None:
    _arm(monkeypatch, "issue")
    decision = issuer_decision()
    assert decision["configuration_accepted"] is True
    assert decision["reason"] == "signing_keys_not_installed"
    assert decision["issues_rs256"] is False
    fixed = 1_700_000_000.0
    monkeypatch.setattr("app.auth.time.time", lambda: fixed)
    data = _claims()
    assert create_access_token(data) == _jwt_sign({**data, "exp": fixed + ACCESS_TOKEN_EXPIRE_MINUTES * 60})
    with pytest.raises(ValueError):
        install_synthetic_keys(rsa.generate_private_key(public_exponent=65537, key_size=1024))


def test_publish_then_issue_then_rollback_preserves_hs256_sessions(monkeypatch, rsa_keys) -> None:
    active, replacement = rsa_keys
    fixed = 1_700_000_000.0
    monkeypatch.setattr("app.auth.time.time", lambda: fixed)
    data = _claims()
    original = create_access_token(data)
    expected = {**data, "exp": fixed + ACCESS_TOKEN_EXPIRE_MINUTES * 60}
    assert original == _jwt_sign(expected)

    _arm(monkeypatch, "off")
    install_synthetic_keys(active)
    assert issuer_decision()["publishes_jwks"] is False
    assert create_access_token(data) == original

    monkeypatch.setenv("NOVA_RS256_PHASE", "publish-only")
    published = issuer_decision()
    assert published["publishes_jwks"] is True
    assert published["issues_rs256"] is False
    assert published["verifies_rs256"] is True
    assert published["issuance_algorithm"] == "HS256"
    assert published["live_issuer_enabled"] is False
    assert create_access_token(data) == original

    app = FastAPI()
    app.include_router(router)
    client = TestClient(app)
    jwks = client.get("/.well-known/jwks.json")
    assert jwks.status_code == 200
    assert jwks.headers["cache-control"] == "no-store"
    key = jwks.json()["keys"][0]
    assert key["kty"] == "RSA" and key["alg"] == "RS256" and key["e"] == "AQAB"
    assert "d" not in key and "p" not in key and "q" not in key
    discovery = client.get("/.well-known/openid-configuration")
    assert discovery.json()["issuer"] == ISSUER
    assert discovery.json()["jwks_uri"] == ISSUER + "/.well-known/jwks.json"

    monkeypatch.setenv("NOVA_RS256_PHASE", "issue")
    issued = create_access_token(data)
    assert _segment(issued.split(".")[0])["alg"] == "RS256"
    assert _segment(issued.split(".")[0])["kid"] == key["kid"]
    verified = _jwt_verify(issued)
    assert verified["sub"] == SUBJECT
    assert verified["iss"] == ISSUER
    assert verified["aud"] == AUDIENCE
    assert isinstance(verified["exp"], int)
    assert verified["email"] == "synthetic@example.com"
    assert verified["auth_version"] == 0
    assert _jwt_verify(original)["sub"] == SUBJECT

    monkeypatch.setenv("NOVA_RS256_PHASE", "publish-only")
    assert create_access_token(data) == original
    assert _segment(issued.split(".")[0])["kid"] == key["kid"]
    assert _jwt_verify(issued)["sub"] == SUBJECT

    monkeypatch.setenv("NOVA_RS256_PHASE", "off")
    assert create_access_token(data) == original
    assert _jwt_verify(original)["role"] == "owner"
    with pytest.raises(HTTPException) as closed:
        _jwt_verify(issued)
    assert closed.value.status_code == 401
    assert closed.value.detail == "Token signature invalid"

    new_kid = rotate_synthetic_key(replacement)
    monkeypatch.setenv("NOVA_RS256_PHASE", "issue")
    rotated = create_access_token(data)
    assert _segment(rotated.split(".")[0])["kid"] == new_kid
    assert _segment(issued.split(".")[0])["kid"] == key["kid"]
    assert _jwt_verify(issued)["sub"] == SUBJECT
    retire_previous_synthetic_key()
    assert _jwt_verify(rotated)["sub"] == SUBJECT
    with pytest.raises(HTTPException) as retired:
        _jwt_verify(issued)
    assert retired.value.detail == "Token signature invalid"
    with pytest.raises(ValueError):
        rotate_synthetic_key(replacement)


def test_rs256_rejects_bad_claims_and_expired_tokens(monkeypatch, rsa_keys) -> None:
    active, _replacement = rsa_keys
    _arm(monkeypatch, "issue")
    install_synthetic_keys(active)
    with pytest.raises(HTTPException) as bad_subject:
        create_access_token({"sub": "synthetic@example.com"})
    assert bad_subject.value.detail == "Token payload invalid"

    issued = issue_if_enabled(_claims(), 7200, now=1_700_000_000)
    assert issued is not None
    body = _segment(issued.split(".")[1])
    assert body["exp"] - body["iat"] == 3600
    monkeypatch.setattr("app.core.nova_rs256_issuer.time.time", lambda: float(body["exp"] + 60))
    assert _jwt_verify(issued)["sub"] == SUBJECT
    monkeypatch.setattr("app.core.nova_rs256_issuer.time.time", lambda: float(body["exp"] + 61))
    with pytest.raises(HTTPException) as expired:
        _jwt_verify(issued)
    assert expired.value.detail == "Token expired"

    chars = list(issued)
    chars[-2] = "A" if chars[-2] != "A" else "B"
    with pytest.raises(IssuerRejected) as changed:
        verify_local_rs256("".join(chars), now=1_700_000_000)
    assert changed.value.detail == "Token signature invalid"

    header = _segment(issued.split(".")[0])
    header["jwk"] = {"kty": "RSA"}
    forged = base64.urlsafe_b64encode(json.dumps(header, separators=(",", ":")).encode()).rstrip(b"=").decode()
    forged_token = forged + issued[issued.find("."):]
    with pytest.raises(IssuerRejected) as embedded:
        verify_local_rs256(forged_token, now=1_700_000_000)
    assert embedded.value.detail == "Token signature invalid"


def test_issuer_source_does_not_read_secrets_and_is_mounted() -> None:
    issuer_source = (BACKEND / "app" / "core" / "nova_rs256_issuer.py").read_text(encoding="utf-8")
    auth_source = (BACKEND / "app" / "auth.py").read_text(encoding="utf-8")
    main_source = (BACKEND / "app" / "main.py").read_text(encoding="utf-8")
    for banned in ("JWT_SECRET", "SECRET_KEY", "DATABASE_URL", "platform_users", "AMICOR_SEED_PASSWORD"):
        assert banned not in issuer_source
    assert '{"alg": "HS256", "typ": "JWT"}' in auth_source
    assert 'os.getenv("NOVA_RS256_ISSUER", "").strip().lower() == "synthetic"' in auth_source
    assert "include_router(nova_rs256_issuer_router)" in main_source
    with pytest.raises(HTTPException) as malformed:
        _jwt_verify("not-a-token")
    assert malformed.value.detail == "Invalid token format"
