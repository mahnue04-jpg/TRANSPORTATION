"""Phase 2E: connect existing authenticated Nova upload to /app/ai-assistant.

Reuses AmiCorUpload and JWT-protected POST /api/upload.
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
UPLOAD_UX = (STATIC / "ux" / "uploadUX.js").read_text(encoding="utf-8")


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


def test_files_pane_renders_and_reuses_existing_upload_engine() -> None:
    assert "/static/ux/uploadUX.js" in OPS_HTML
    assert "AmiCorUpload" in UPLOAD_UX
    assert "/api/upload" in UPLOAD_UX
    assert "AmiCorSession.authFetch" in UPLOAD_UX
    assert "function resolveAuthFetch" in UPLOAD_UX

    pane = OPS_JS.split("function renderNovaFilesPane()", 1)[1].split(
        "function bindNovaFilesEvents()", 1
    )[0]
    for fragment in [
        "function renderNovaFilesPane",
        "function mountNovaFilesUpload",
        "function bindNovaFilesEvents",
        "function novaFilesAuthFetch",
        "AmiCorUpload.init",
        "/api/upload",
        "novaFilesAuthFetch",
        "novaConversationAuthFetch",
        "data-nova-files-clear",
        'id="nova-files-dropzone"',
        'id="nova-files-strip"',
        'id="nova-files-meta"',
    ]:
        assert fragment in OPS_JS, fragment
    assert "AmiCorUpload.init" in pane or "POST /api/upload" in pane
    files_block = OPS_JS.split("function renderNovaFilesPane()", 1)[1].split(
        "function renderAssistant()", 1
    )[0]
    assert 'fetch("/api/ops/workspace/action"' not in files_block
    assert "<iframe" not in files_block.lower()
    assert "function uploadWithRetry" not in files_block
    files_def = OPS_JS.split('id: "files"', 1)[1][:500]
    assert "Live" in files_def
    assistant = OPS_JS.split("function renderAssistant()", 1)[1][:600]
    assert 'pane.id === "files"' in assistant
    assert 'pane.id === "conversation"' in assistant
    assert 'pane.id === "voice"' in assistant
    assert "@app.post" not in OPS_JS
    assert "/api/files" not in OPS_JS


def test_unauthenticated_upload_is_blocked(client: TestClient) -> None:
    upload = client.post(
        "/api/upload",
        files={"file": ("note.txt", b"phase 2e unauthenticated", "text/plain")},
    )
    assert upload.status_code == 401, upload.text


def test_authenticated_upload_uses_existing_jwt_upload_path(client: TestClient) -> None:
    rider = _login(client, "rider@amicor.local")
    dispatcher = _login(client, "dispatcher@amicor.local")
    headers = _headers(rider["access_token"])
    assert dispatcher["user_id"] != rider["user_id"]

    upload = client.post(
        "/api/upload",
        headers=headers,
        files={"file": ("phase2e.txt", b"hello from phase 2e files pane", "text/plain")},
    )
    assert upload.status_code == 200, upload.text
    body = upload.json()
    assert body.get("filename")
    assert body.get("status") == "uploaded"
    assert "extracted_text" in body
    assert "size_bytes" in body

    other = client.post(
        "/api/upload",
        headers=_headers(dispatcher["access_token"]),
        files={"file": ("other.txt", b"dispatcher file", "text/plain")},
    )
    assert other.status_code == 200, other.text


def test_conversation_voice_governance_remain_intact_and_workspace_stays_available() -> None:
    client = TestClient(app)
    for path in ["/app", "/app/ai-assistant", "/workspace"]:
        response = client.get(path, follow_redirects=False)
        assert response.status_code == 200, f"{path} -> {response.status_code}"

    assert "function renderNovaConversationPane()" in OPS_JS
    assert "function sendNovaConversationMessage" in OPS_JS
    assert "/api/chat/stream" in OPS_JS
    assert "/api/chat" in OPS_JS
    assert "function renderNovaVoicePane()" in OPS_JS
    assert "sendNovaConversationMessage" in OPS_JS.split("function sendNovaVoiceUtterance", 1)[1][:1200]
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
    voice_def = OPS_JS.split('id: "voice"', 1)[1][:500]
    assert "Live" in conversation_def
    assert "Live" in voice_def
    health_def = OPS_JS.split('id: "health-isf"', 1)[1][:500]
    assert "Live" in health_def


def test_streaming_conversation_still_works_for_authenticated_user(client: TestClient) -> None:
    auth = _login(client, "admin@amicor.local")
    headers = _headers(auth["access_token"])
    user_id = auth["user_id"]

    async def fake_stream(_message: str, bound_user_id: str):
        assert bound_user_id == user_id
        yield 'data: {"type": "token", "content": "hello"}\n\n'
        yield "data: [DONE]\n\n"

    with patch("app.main._stream_openai", side_effect=fake_stream):
        response = client.post(
            "/api/chat/stream",
            headers=headers,
            json={"user_id": user_id, "message": "xyzzy phase2e stream probe"},
        )
    assert response.status_code == 200, response.text
    assert "text/event-stream" in response.headers.get("content-type", "")
    body = response.text
    assert '"type": "token"' in body or '"type":"token"' in body
    assert "[DONE]" in body
