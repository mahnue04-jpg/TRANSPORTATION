"""Issue a synthetic RS256 token and verify it with the pinned Casting verifier."""
from __future__ import annotations

import importlib.util
import sys
from pathlib import Path
from urllib.parse import urlsplit

import pytest
from cryptography.hazmat.primitives.asymmetric import rsa
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.auth import _jwt_verify, create_access_token
from app.core.nova_rs256_issuer import (
    PROPOSED_AUDIENCE,
    PROPOSED_ISSUER,
    clear_synthetic_keys,
    install_synthetic_keys,
    retire_previous_synthetic_key,
    rotate_synthetic_key,
    router,
)

PIN = "0f42164a"
ISSUER = "https://signin.nova-staging.test"
AUDIENCE = "https://signin.nova-staging.test"
SUBJECT = "11111111-1111-4111-8111-111111111111"
OTHER_SUBJECT = "22222222-2222-4222-8222-222222222222"
VERIFIER_PATH = Path(__file__).resolve().parent / "support" / "casting_trusted_signin_0f42164a.py"


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


def _claims(subject: str = SUBJECT) -> dict:
    return {
        "sub": subject,
        "email": "synthetic@example.com",
        "role": "owner",
        "organization_id": "org-1",
        "auth_version": 0,
    }


def _verifier():
    text = VERIFIER_PATH.read_text(encoding="utf-8")
    assert text.startswith(
        f"# Pinned staging Casting verifier from cursor/casting-auditions-pilot-e1ae at {PIN}."
    )
    spec = importlib.util.spec_from_file_location("casting_trusted_signin_0f42164a", VERIFIER_PATH)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def _client() -> TestClient:
    app = FastAPI()
    app.include_router(router)
    return TestClient(app)


def test_pinned_verifier_still_refuses_the_production_origin() -> None:
    verifier = _verifier()
    decision = verifier.trusted_signin_decision({
        "NOVA_CASTING_TRUSTED_SIGNIN": "staging",
        "NOVA_CASTING_TRUSTED_ISSUER": PROPOSED_ISSUER,
        "NOVA_CASTING_TRUSTED_AUDIENCE": PROPOSED_AUDIENCE,
        "NOVA_CASTING_TRUSTED_JWKS_URL": PROPOSED_ISSUER + "/.well-known/jwks.json",
        "ENVIRONMENT": "test",
    })
    assert decision["enabled"] is False
    assert decision["production_issuer_activated"] is False
    assert decision["imports_accounts"] is False
    assert decision["shares_signing_key"] is False


def test_casting_verifier_accepts_synthetic_discovery_rotation_and_membership(monkeypatch, rsa_keys) -> None:
    primary, secondary = rsa_keys
    verifier = _verifier()
    _arm(monkeypatch, "issue")
    install_synthetic_keys(primary)
    client = _client()
    calls: list[str] = []

    def fetch(url: str):
        calls.append(url)
        response = client.get(urlsplit(url).path)
        if response.status_code != 200:
            raise RuntimeError(f"jwks status {response.status_code}")
        body = response.json()
        if not isinstance(body, dict):
            raise RuntimeError("jwks document")
        return body

    issued_at = 1_700_000_000
    monkeypatch.setattr("app.auth.time.time", lambda: float(issued_at))
    monkeypatch.setattr("app.core.nova_rs256_issuer.time.time", lambda: float(issued_at))
    token = create_access_token(_claims())
    hs256 = None
    monkeypatch.setenv("NOVA_RS256_PHASE", "off")
    hs256 = create_access_token(_claims(OTHER_SUBJECT))
    monkeypatch.setenv("NOVA_RS256_PHASE", "issue")

    ring = verifier.KeyRing(fetch, ISSUER)
    verified = verifier.verify_nova_token(
        token,
        issuer=ISSUER,
        audience=AUDIENCE,
        ring=ring,
        now=issued_at,
    )
    assert verified.subject == SUBJECT
    assert verified.issuer == ISSUER
    assert verified.audience == AUDIENCE
    assert calls == [
        ISSUER + "/.well-known/openid-configuration",
        ISSUER + "/.well-known/jwks.json",
    ]
    store = verifier.MemoryMembershipStore()
    first = verifier.establish_staging_membership(store, verified)
    second = verifier.establish_staging_membership(store, verified)
    assert first["created"] is True
    assert second["created"] is False
    assert first["local_id"] == second["local_id"]
    assert set(first) == {"local_id", "issuer", "subject", "created", "imports_accounts", "workflows_enabled"}
    assert first["imports_accounts"] is False
    assert first["workflows_enabled"] is False
    assert "email" not in first
    assert _jwt_verify(token)["email"] == "synthetic@example.com"

    other = verifier.verify_nova_token(
        create_access_token(_claims(OTHER_SUBJECT)),
        issuer=ISSUER,
        audience=AUDIENCE,
        ring=verifier.KeyRing(fetch, ISSUER),
        now=issued_at,
    )
    other_row = verifier.establish_staging_membership(store, other)
    assert other_row["local_id"] != first["local_id"]

    with pytest.raises(verifier.TrustedSigninRejected) as hs256_rejected:
        verifier.verify_nova_token(hs256, issuer=ISSUER, audience=AUDIENCE, ring=ring, now=issued_at)
    assert hs256_rejected.value.reason == "algorithm"

    wrong_audience = token
    with pytest.raises(verifier.TrustedSigninRejected) as audience_rejected:
        verifier.verify_nova_token(
            wrong_audience,
            issuer=ISSUER,
            audience="https://other.nova-staging.test",
            ring=verifier.KeyRing(fetch, ISSUER),
            now=issued_at,
        )
    assert audience_rejected.value.reason == "audience"

    next_kid = rotate_synthetic_key(secondary)
    rotated = create_access_token(_claims())
    clock = {"now": float(issued_at)}
    cached = verifier.KeyRing(fetch, ISSUER, now=lambda: clock["now"])
    assert verifier.verify_nova_token(
        token, issuer=ISSUER, audience=AUDIENCE, ring=cached, now=clock["now"]
    ).kid != next_kid
    assert verifier.verify_nova_token(
        rotated, issuer=ISSUER, audience=AUDIENCE, ring=cached, now=clock["now"]
    ).kid == next_kid

    retire_previous_synthetic_key()
    clock["now"] = float(issued_at + verifier.KEY_CACHE_SECONDS - 1)
    assert verifier.verify_nova_token(
        token, issuer=ISSUER, audience=AUDIENCE, ring=cached, now=clock["now"]
    ).subject == SUBJECT
    clock["now"] = float(issued_at + verifier.KEY_CACHE_SECONDS)
    with pytest.raises(verifier.TrustedSigninRejected) as retired:
        verifier.verify_nova_token(token, issuer=ISSUER, audience=AUDIENCE, ring=cached, now=clock["now"])
    assert retired.value.reason == "key"
    assert verifier.verify_nova_token(
        rotated,
        issuer=ISSUER,
        audience=AUDIENCE,
        ring=verifier.KeyRing(fetch, ISSUER, now=lambda: clock["now"]),
        now=clock["now"],
    ).kid == next_kid

    monkeypatch.setenv("NOVA_RS256_PHASE", "off")
    with pytest.raises(RuntimeError):
        fetch(ISSUER + "/.well-known/jwks.json")
    assert _jwt_verify(hs256)["sub"] == OTHER_SUBJECT


def test_disposable_membership_survives_reopen_without_a_password(monkeypatch, rsa_keys, tmp_path) -> None:
    primary, _secondary = rsa_keys
    verifier = _verifier()
    _arm(monkeypatch, "issue")
    install_synthetic_keys(primary)
    issued_at = 1_700_000_000
    monkeypatch.setattr("app.core.nova_rs256_issuer.time.time", lambda: float(issued_at))
    token = create_access_token(_claims())
    app = FastAPI()
    app.include_router(router)
    client = TestClient(app)

    def fetch(url: str):
        response = client.get(urlsplit(url).path)
        response.raise_for_status()
        return response.json()

    verified = verifier.verify_nova_token(
        token,
        issuer=ISSUER,
        audience=AUDIENCE,
        ring=verifier.KeyRing(fetch, ISSUER),
        now=issued_at,
    )
    path = tmp_path / "membership.sqlite"
    store = verifier.SqliteMembershipStore(str(path))
    first = verifier.establish_staging_membership(store, verified)
    store.connection.close()
    reopened = verifier.SqliteMembershipStore(str(path))
    second = verifier.establish_staging_membership(reopened, verified)
    columns = [
        row[1]
        for row in reopened.connection.execute("PRAGMA table_info(casting_trusted_memberships)")
    ]
    assert second["local_id"] == first["local_id"]
    assert second["created"] is False
    assert second["subject"] == SUBJECT
    assert "password" not in columns
    assert "email" not in columns
    reopened.connection.close()
