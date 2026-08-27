"""Phase 2D: connect existing authenticated Nova voice to /app/ai-assistant.

Reuses AmiCorVoiceRuntime, AmiCorHumanVoice, and /api/voice/* endpoints.
Does not migrate /workspace or change Health ISF engines.
"""
from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient

from app.auth import SEED_PASSWORD, ensure_auth_schema, seed_default_users
from app.database import init_db
from app.main import app

ROOT = Path(__file__).resolve().parents[1]
STATIC = ROOT / "static"
OPS_JS = (STATIC / "ops-shell.js").read_text(encoding="utf-8")
OPS_HTML = (STATIC / "ops-shell.html").read_text(encoding="utf-8")
VOICE_ENGINE = (STATIC / "ux" / "humanVoiceEngine.js").read_text(encoding="utf-8")
VOICE_RUNTIME = (STATIC / "ux" / "voiceRuntime.js").read_text(encoding="utf-8")


@pytest.fixture(scope="module")
def client() -> TestClient:
    ensure_auth_schema()
    seed_default_users()
    init_db()
    return TestClient(app)


def _login(client: TestClient, email: str) -> dict:
    response = client.post("/api/auth/login", json={"email": email, "password": SEED_PASSWORD})
    assert response.status_code == 200, response.text
    payload = response.json()
    assert payload.get("access_token")
    assert payload.get("user_id")
    return payload


def _headers(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


def test_voice_pane_mounts_existing_authenticated_voice_stack() -> None:
    assert "/static/ux/voiceRuntime.js" in OPS_HTML
    assert "/static/ux/humanVoiceEngine.js" in OPS_HTML
    assert "AmiCorVoiceRuntime" in VOICE_RUNTIME
    assert "createVoiceRuntimeController" in VOICE_RUNTIME
    assert "AmiCorHumanVoice" in VOICE_ENGINE
    assert "/api/voice/providers" in VOICE_ENGINE
    assert "/api/voice/speak" in VOICE_ENGINE
    assert "AmiCorSession.authFetch" in VOICE_ENGINE

    pane = OPS_JS.split("function renderNovaVoicePane()", 1)[1].split(
        "function stopNovaVoiceMicTracks()", 1
    )[0]
    for fragment in [
        "function renderNovaVoicePane",
        "function ensureNovaVoiceEngines",
        "function startNovaVoiceListening",
        "function sendNovaVoiceUtterance",
        "function loadNovaVoiceProviders",
        "AmiCorVoiceRuntime",
        "AmiCorHumanVoice",
        "/api/voice/providers",
        "/api/voice/speak",
        "sendNovaConversationMessage",
        "novaConversationAuthFetch",
        "data-nova-voice-listen",
        "data-nova-voice-stop",
        "browserFallbackEnabled: true",
    ]:
        assert fragment in OPS_JS, fragment
    assert "/api/voice/providers" in pane
    assert "/api/voice/speak" in pane
    assert "sendNovaConversationMessage" in OPS_JS.split("function sendNovaVoiceUtterance", 1)[1][:1200]
    voice_block = OPS_JS.split("function renderNovaVoicePane()", 1)[1].split(
        "function renderAssistant()", 1
    )[0]
    assert 'fetch("/api/ops/workspace/action"' not in voice_block
    assert "<iframe" not in voice_block.lower()
    voice_def = OPS_JS.split('id: "voice"', 1)[1][:500]
    assert "Live" in voice_def
    assistant = OPS_JS.split("function renderAssistant()", 1)[1][:500]
    assert 'pane.id === "voice"' in assistant
    assert 'pane.id === "conversation"' in assistant


def test_unauthenticated_voice_requests_are_rejected(client: TestClient) -> None:
    providers = client.get("/api/voice/providers")
    speak = client.post("/api/voice/speak", json={"text": "hello"})
    assert providers.status_code == 401, providers.text
    assert speak.status_code == 401, speak.text


def test_authenticated_nova_user_can_access_voice_endpoints(client: TestClient) -> None:
    rider = _login(client, "rider@amicor.local")
    dispatcher = _login(client, "dispatcher@amicor.local")
    headers = _headers(rider["access_token"])
    assert dispatcher["user_id"] != rider["user_id"]

    providers = client.get("/api/voice/providers", headers=headers)
    assert providers.status_code == 200, providers.text
    body = providers.json()
    assert "available" in body
    assert "primary" in body
    assert "browser_native" in body.get("available", {})

    with patch("app.voice._synthesize_openai", return_value=(b"ID3fakeaudio", "audio/mpeg")):
        speak = client.post(
            "/api/voice/speak",
            headers=headers,
            json={"text": "hello nova voice", "preferred_provider": "openai_realtime_voice"},
        )
    assert speak.status_code in (200, 503), speak.text
    if speak.status_code == 200:
        payload = speak.json()
        assert payload.get("audio_b64")
        assert payload.get("provider")

    foreign_headers = _headers(dispatcher["access_token"])
    other_providers = client.get("/api/voice/providers", headers=foreign_headers)
    assert other_providers.status_code == 200, other_providers.text


def test_phase2c_conversation_and_governance_remain_intact_and_workspace_stays_available() -> None:
    client = TestClient(app)
    for path in ["/app", "/app/ai-assistant", "/workspace"]:
        response = client.get(path, follow_redirects=False)
        assert response.status_code == 200, f"{path} -> {response.status_code}"

    assert "function renderNovaConversationPane()" in OPS_JS
    assert "function sendNovaConversationMessage" in OPS_JS
    assert "/api/chat/stream" in OPS_JS
    assert "/api/chat" in OPS_JS
    assert "/api/history/" in OPS_JS
    assert "/api/reset" in OPS_JS
    chassis = OPS_JS.split("function renderNovaGovernanceChassis()", 1)[1].split(
        "var novaConversationAbort", 1
    )[0]
    for control in ["preview", "inspect", "simulate", "confirm", "cancel"]:
        assert 'data-assistant-intent="' + control + '"' in chassis, control
    assert "renderSafetyIndicators()" in chassis
    assert "NOVA_SHELL_PANES" in OPS_JS
    assert "function renderNovaShellChrome()" in OPS_JS
    assert 'data-route="ai-assistant"' in OPS_HTML
    assert "/workspace remains the live conversation source" in OPS_JS
    assert "function renderOperationsHome()" in OPS_JS
    assert "<iframe" not in chassis.lower()
    conversation_def = OPS_JS.split('id: "conversation"', 1)[1][:500]
    assert "Live" in conversation_def
    health_def = OPS_JS.split('id: "health-isf"', 1)[1][:500]
    assert "Live" in health_def
