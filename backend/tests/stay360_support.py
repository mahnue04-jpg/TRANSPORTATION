"""Shared Stay360 test actors. Synthetic identities only."""

from __future__ import annotations

import json

from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.auth import UserContext, get_current_user_context
from app.core.nova.stay360.fixtures import CEDAR_TENANT, HARBOR_TENANT, sensitive_corpus
from app.core.nova.stay360.privacy import forbidden_keys
from app.core.nova.stay360.router import router
from app.core.nova.stay360.store import reset_stay360_store

__all__ = [
    "CEDAR_TENANT",
    "HARBOR_TENANT",
    "anonymous_client",
    "assert_clean",
    "client_for",
    "reset_stay360_store",
    "user",
]


def user(user_id: str, role: str, organization_id: str) -> UserContext:
    return UserContext(
        user_id=user_id,
        email=f"{user_id}@{role}.example.invalid",
        role=role,
        organization_id=organization_id,
    )


def client_for(actor: UserContext) -> TestClient:
    app = FastAPI()
    app.include_router(router)
    app.dependency_overrides[get_current_user_context] = lambda: actor
    return TestClient(app)


def anonymous_client() -> TestClient:
    app = FastAPI()
    app.include_router(router)
    return TestClient(app)


def assert_clean(payload, *extra: str) -> None:
    assert forbidden_keys(payload) == []
    blob = json.dumps(payload, ensure_ascii=False)
    secrets = list(sensitive_corpus()) + list(extra)
    for secret in secrets:
        assert secret not in blob
