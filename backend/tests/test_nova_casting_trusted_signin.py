"""Shared Nova sign-in stays off. These tests do not connect or import accounts."""
from __future__ import annotations

import hashlib
import hmac
import inspect
import json
import time

import pytest
from fastapi import HTTPException

from app.auth import TOKEN_SIGNING_SECRET, _b64url_encode, _jwt_sign, _jwt_verify
from app.core.casting_trusted_signin import (
    BLOCKER,
    OWNER_DECISIONS,
    PROPOSED_ENV_NAMES,
    trusted_signin_decision,
)


def _assert_stays_off(decision: dict) -> None:
    assert decision["supported"] is False
    assert decision["enabled"] is False
    assert decision["imports_accounts"] is False
    assert decision["shares_database"] is False
    assert decision["shares_signing_key"] is False
    assert decision["shares_passwords"] is False
    assert decision["validates_remote_token"] is False
    assert decision["workflows_enabled"] is False
    assert decision["production_integration"] is False
    assert decision["algorithm"] == "HS256"
    assert decision["verifier"] == "local-hmac"
    assert decision["blocker"] == BLOCKER
    assert decision["owner_decisions"] == list(OWNER_DECISIONS)
    assert "JWKS" in decision["blocker"]
    assert "platform_users" in decision["blocker"]


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
    assert foreign.split(".", 1)[0] != ""
    assert TOKEN_SIGNING_SECRET.encode() != b"different-signing-secret"
    with pytest.raises(HTTPException) as rejected:
        _jwt_verify(foreign)
    assert rejected.value.status_code == 401
    assert rejected.value.detail == "Token signature invalid"
