from __future__ import annotations

from fastapi.testclient import TestClient

from app.main import app
from app import main as main_module


client = TestClient(app)


def _login_headers() -> dict[str, str]:
    response = client.post(
        "/api/auth/login",
        json={"email": "admin@amicor.local", "password": "Amicor123!"},
    )
    assert response.status_code == 200
    token = response.json()["access_token"]
    return {"Authorization": f"Bearer {token}"}


def _preview(headers: dict[str, str], *, session_id: str, prompt: str) -> dict:
    response = client.post(
        "/api/assistant/preview",
        headers=headers,
        json={
            "intent": "preview",
            "prompt": prompt,
            "role": "admin",
            "scope": "assistant-workspace",
            "session_id": session_id,
            "context": {"source": "phase38-test"},
        },
    )
    assert response.status_code == 200
    body = response.json()
    assert isinstance(body.get("supervision_classification"), dict)
    assert isinstance(body.get("integrity"), dict)
    assert isinstance(body.get("confirmation"), dict)
    return body


def _confirm(headers: dict[str, str], preview: dict, *, supervision_input: object) -> dict:
    confirmation = preview["confirmation"]
    integrity = preview["integrity"]
    response = client.post(
        "/api/assistant/confirm",
        headers=headers,
        json={
            "token": confirmation["signed_token"],
            "intent_id": confirmation["intent_id"],
            "action_type": confirmation["action_type"],
            "session_id": confirmation["session_id"],
            "intent_hash": integrity["intent_hash"],
            "preview_payload_hash": integrity["preview_payload_hash"],
            "dependency_graph_hash": integrity["dependency_graph_hash"],
            "safety_classification_hash": integrity["safety_classification_hash"],
            "supervision_classification": supervision_input,
            "nonce": confirmation["nonce"],
            "correlation_id": confirmation["correlation_id"],
            "policy_version": confirmation["policy_version"],
        },
    )
    assert response.status_code == 200
    body = response.json()
    assert body.get("confirmation_verification", {}).get("status") == "VERIFIED_PREVIEW"
    assert isinstance(body.get("workflow_execution"), dict)
    return body


def test_phase38_contract_lock_object_and_legacy_supervision_payloads() -> None:
    headers = _login_headers()

    object_session = "phase38-object-session"
    preview_object = _preview(headers, session_id=object_session, prompt="phase38 object supervision payload")
    object_supervision = preview_object["supervision_classification"]
    confirmed_object = _confirm(headers, preview_object, supervision_input=object_supervision)

    duplicate_response = client.post(
        "/api/assistant/confirm",
        headers=headers,
        json={
            "token": preview_object["confirmation"]["signed_token"],
            "intent_id": preview_object["confirmation"]["intent_id"],
            "action_type": preview_object["confirmation"]["action_type"],
            "session_id": preview_object["confirmation"]["session_id"],
            "intent_hash": preview_object["integrity"]["intent_hash"],
            "preview_payload_hash": preview_object["integrity"]["preview_payload_hash"],
            "dependency_graph_hash": preview_object["integrity"]["dependency_graph_hash"],
            "safety_classification_hash": preview_object["integrity"]["safety_classification_hash"],
            "supervision_classification": object_supervision,
            "nonce": preview_object["confirmation"]["nonce"],
            "correlation_id": preview_object["confirmation"]["correlation_id"],
            "policy_version": preview_object["confirmation"]["policy_version"],
        },
    )
    assert duplicate_response.status_code == 409

    string_session = "phase38-string-session"
    preview_string = _preview(headers, session_id=string_session, prompt="phase38 legacy string supervision payload")
    legacy_supervision = preview_string["supervision_classification"]["classification"]
    confirmed_string = _confirm(headers, preview_string, supervision_input=legacy_supervision)

    executions = client.get("/api/assistant/executions", params={"limit": 50}, headers=headers)
    assert executions.status_code == 200
    execution_items = executions.json().get("items", [])
    execution_ids = {item.get("execution_id") for item in execution_items}
    assert confirmed_object["workflow_execution"].get("execution_id") in execution_ids
    assert confirmed_string["workflow_execution"].get("execution_id") in execution_ids

    memory = client.get("/api/assistant/memory", params={"session_id": object_session, "limit": 20}, headers=headers)
    assert memory.status_code == 200
    assert memory.json().get("count", 0) >= 1

    events = client.get("/api/assistant/events", params={"session_id": object_session, "limit": 20}, headers=headers)
    assert events.status_code == 200
    event_items = events.json().get("items", [])
    assert any(item.get("event_name") == "confirmation_executed" for item in event_items)

    with main_module._assistant_local_replay_lock:
        main_module._assistant_local_confirmation_tokens.clear()
        main_module._assistant_local_preview_records.clear()
        main_module._assistant_local_nonce_consumed.clear()
        main_module._assistant_local_request_digests.clear()
        main_module._assistant_local_intent_hashes.clear()

    resumed = client.get("/api/assistant/executions", params={"limit": 50}, headers=headers)
    assert resumed.status_code == 200
    resumed_ids = {item.get("execution_id") for item in resumed.json().get("items", [])}
    assert confirmed_object["workflow_execution"].get("execution_id") in resumed_ids
