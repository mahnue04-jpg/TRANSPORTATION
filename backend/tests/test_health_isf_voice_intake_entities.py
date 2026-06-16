"""Regression tests for AI dispatch voice intake entity extraction."""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from app.auth import SEED_PASSWORD, ensure_auth_schema, seed_default_users
from app.db.models import User as PlatformUser
from app.db.session import SessionLocal
from app.main import app
from app.modules.health_isf.ai_dispatch import AIDispatchOrchestrationService
from app.modules.health_isf.intelligence import OperationalIntelligenceService


@pytest.fixture(scope="module")
def client() -> TestClient:
    ensure_auth_schema()
    seed_default_users()
    return TestClient(app)


def _login(client: TestClient, email: str) -> dict:
    response = client.post(
        "/api/auth/login",
        json={"email": email, "password": SEED_PASSWORD},
    )
    assert response.status_code == 200, response.text
    return response.json()


def _get_org_id(email: str) -> str:
    with SessionLocal() as db:
        user = db.query(PlatformUser).filter(PlatformUser.email == email).first()
        assert user is not None
        return user.organization_id


def test_parse_voice_command_extracts_intake_entities(db, monkeypatch):
    monkeypatch.setattr(
        OperationalIntelligenceService,
        "build_recommendations",
        lambda *_args, **_kwargs: {"dispatcher_recommendation_payloads": []},
    )
    monkeypatch.setattr(
        OperationalIntelligenceService,
        "summarize",
        lambda *_args, **_kwargs: {"summary": "Voice command parsed"},
    )

    transcript = (
        "Create ride from 123 Main St to General Hospital "
        "for passenger John Doe phone 555-111-2222 emergency dialysis"
    )

    payload = AIDispatchOrchestrationService.parse_voice_command(
        db,
        organization_id="org-test-123",
        transcript=transcript,
    )

    assert payload["intent"] == "prepare_intake"
    assert payload["action_label"] == "Prepare ride intake"

    entities = payload["extracted_entities"]
    assert entities["ride_id"] is None
    assert entities["pickup_address"] == "123 Main St"
    assert entities["dropoff_address"] == "General Hospital"
    assert entities["passenger_name"] == "John Doe"
    assert entities["passenger_phone"] == "555-111-2222"
    assert entities["service_type"] == "dialysis"
    assert entities["priority_tag"] == "emergency"
    assert entities["is_emergency"] == "true"


def test_voice_command_endpoint_prefills_intake_entities(client, monkeypatch):
    monkeypatch.setattr(
        OperationalIntelligenceService,
        "build_recommendations",
        lambda *_args, **_kwargs: {"dispatcher_recommendation_payloads": []},
    )
    monkeypatch.setattr(
        OperationalIntelligenceService,
        "summarize",
        lambda *_args, **_kwargs: {"summary": "Voice command parsed"},
    )

    auth = _login(client, "dispatcher@amicor.local")
    org_id = _get_org_id("dispatcher@amicor.local")
    headers = {"Authorization": f"Bearer {auth['access_token']}"}

    response = client.post(
        "/api/health-isf/ai-dispatch/voice/command",
        headers=headers,
        json={
            "organization_id": org_id,
            "transcript": (
                "create ride from 123 Main St to General Hospital "
                "for passenger John Doe phone 555-111-2222 emergency dialysis"
            ),
        },
    )

    assert response.status_code == 200, response.text
    payload = response.json()
    entities = payload["extracted_entities"]

    assert payload["intent"] == "prepare_intake"
    assert entities["ride_id"] is None
    assert entities["pickup_address"] == "123 Main St"
    assert entities["dropoff_address"] == "General Hospital"
    assert entities["passenger_name"] == "John Doe"
    assert entities["passenger_phone"] == "555-111-2222"
    assert entities["service_type"] == "dialysis"
    assert entities["priority_tag"] == "emergency"
    assert entities["is_emergency"] == "true"
