"""Today Ask Nova: user prompt is primary; unconfigured mailbox is not an error."""
from __future__ import annotations

from datetime import timedelta
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.auth import SEED_PASSWORD, ensure_auth_schema, seed_default_users
from app.core.nova.service import NovaCoreService
from app.core.nova.today.service import today_supporting_context_relevant
from app.helpers import now, uuid4
from app.main import app

ROOT = Path(__file__).resolve().parents[1]
TODAY_JS = (ROOT / "static" / "nova-today" / "today.js").read_text(encoding="utf-8")


@pytest.fixture(scope="module")
def client() -> TestClient:
    from app.core.nova.today.schema_ensure import ensure_nova_today_schema
    from app.db.session import engine, init_platform_db

    ensure_auth_schema()
    seed_default_users()
    init_platform_db()
    ensure_nova_today_schema(engine)
    return TestClient(app)


def _headers(client: TestClient, email: str = "dispatcher@amicor.local") -> dict[str, str]:
    response = client.post("/api/auth/login", json={"email": email, "password": SEED_PASSWORD})
    assert response.status_code == 200, response.text
    return {"Authorization": f"Bearer {response.json()['access_token']}"}


def _enable_llm(monkeypatch: pytest.MonkeyPatch) -> list[str]:
    prompts: list[str] = []

    def _primary_text(message: str) -> str:
        marker = "answer it directly):\n"
        if marker in message:
            return message.split(marker, 1)[1].split("\n\n", 1)[0].strip()
        marker = "\nUser question:\n"
        if marker in message:
            return message.split(marker, 1)[1].strip()
        return message

    def fake_openai(message, history=None):
        prompts.append(message)
        text = _primary_text(message).lower()
        if "my name is not" in text:
            return "Understood. You are not Mrs. Nova Brain."
        if "my name is" in text:
            return "Nice to meet you. I heard your name as a conversational statement."
        if "attention" in text:
            return "Here is what needs attention on Today."
        if "weather" in text:
            return "I do not currently have live weather information."
        if "news" in text:
            return "I do not currently have live news information."
        return "Plain conversational answer."

    monkeypatch.setattr(
        "app.core.nova.service.NovaCoreService._can_use_llm",
        classmethod(lambda cls: True),
    )
    monkeypatch.setattr("app.ai.ask_openai", fake_openai)
    return prompts


def _add_gmail(user_id: str) -> str:
    from app.db.models import IntegrationAccount
    from app.db.session import SessionLocal

    row_id = uuid4()
    with SessionLocal() as db:
        db.add(
            IntegrationAccount(
                id=row_id,
                user_id=user_id,
                service="email",
                provider="gmail",
                account_email="gmail-owner@example.com",
                access_token="test-token",
                token_expires_at=now() + timedelta(hours=2),
            )
        )
        db.commit()
    return row_id


def _cleanup_accounts(user_id: str) -> None:
    from app.db.models import IntegrationAccount
    from app.db.session import SessionLocal

    with SessionLocal() as db:
        db.query(IntegrationAccount).filter(IntegrationAccount.user_id == user_id).delete()
        db.commit()


def test_today_supporting_context_relevance_rules() -> None:
    assert today_supporting_context_relevant("What is the weather today?", selected_item=False) is False
    assert today_supporting_context_relevant("What is today's news?", selected_item=False) is False
    assert today_supporting_context_relevant("best AI news", selected_item=False) is False
    assert today_supporting_context_relevant("my name is Saye", selected_item=False) is False
    assert today_supporting_context_relevant("my name is not Mrs. Nova Brain", selected_item=False) is False
    assert today_supporting_context_relevant("What needs my attention today?", selected_item=False) is True
    assert today_supporting_context_relevant("hello there", selected_item=True) is True


def test_today_ui_shows_not_configured_not_disconnected() -> None:
    assert "Mailbox: not configured" in TODAY_JS
    assert "health.status === \"not_configured\"" in TODAY_JS


def test_unconfigured_mailbox_is_not_an_error(client: TestClient) -> None:
    owner = _headers(client, "staff@amicor.local")
    mailbox = client.get("/api/nova/today/mailbox", headers=owner)
    assert mailbox.status_code == 200, mailbox.text
    health = mailbox.json()["connector_health"]
    assert health["status"] == "not_configured"
    assert health["status"] != "disconnected"
    detail = (health.get("detail") or "").lower()
    assert "never been connected" in detail
    assert "not an error" in detail
    assert mailbox.json()["items"] == []

    dash = client.get("/api/nova/today/dashboard", headers=owner)
    assert dash.status_code == 200, dash.text
    comms = {row["source"]: row for row in dash.json()["source_health"]}["communications"]
    assert comms["connector"] == "not_configured"
    assert "not an error" in comms["detail"].lower() or "never been connected" in comms["detail"].lower()
    assert dash.json()["connector_health"]["status"] == "not_configured"


def test_genuine_connector_error_is_unavailable_not_unconfigured(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    login = client.post(
        "/api/auth/login",
        json={"email": "dispatcher@amicor.local", "password": SEED_PASSWORD},
    )
    user_id = login.json()["user_id"]
    headers = {"Authorization": f"Bearer {login.json()['access_token']}"}
    _cleanup_accounts(user_id)
    _add_gmail(user_id)
    try:
        def boom(*_args, **_kwargs):
            raise RuntimeError("provider unavailable")

        monkeypatch.setattr("app.core.nova.today.mailbox.fetch_provider_messages", boom)
        broken = client.get("/api/nova/today/mailbox", headers=headers)
        assert broken.status_code == 200, broken.text
        health = broken.json()["connector_health"]
        assert health["status"] == "unavailable"
        assert health["status"] != "not_configured"
        assert "unavailable" in (health.get("detail") or "").lower()
    finally:
        _cleanup_accounts(user_id)


def _assert_conversational_prompt(prompt: str, user_text: str) -> None:
    assert "PRIMARY USER PROMPT" in prompt
    assert user_text in prompt
    assert "3 concrete next actions" not in prompt
    assert "health_isf_summary" not in prompt
    assert "SUPPORTING TODAY CONTEXT" not in prompt
    assert "Top attention:" not in prompt
    assert "Mailbox connector disconnected" not in prompt
    assert "Align this week targets" not in prompt


@pytest.mark.parametrize(
    ("question", "answer_needles"),
    [
        ("What is the weather today?", ("weather", "do not currently have")),
        ("What is today's news?", ("news", "do not currently have")),
        ("best AI news", ("news", "do not currently have")),
        ("my name is Saye", ("name",)),
        ("my name is not Mrs. Nova Brain", ("not mrs. nova brain", "understood")),
    ],
)
def test_conversational_ask_does_not_stuff_today_ops(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
    question: str,
    answer_needles: tuple[str, ...],
) -> None:
    prompts = _enable_llm(monkeypatch)
    asked = client.post(
        "/api/nova/today/ask",
        headers=_headers(client),
        json={"question": question},
    )
    assert asked.status_code == 200, asked.text
    body = asked.json()
    assert body["answer"]
    lower = body["answer"].lower()
    assert any(needle in lower for needle in answer_needles)
    assert "mailbox" not in lower
    assert "approval" not in lower
    assert body["next_actions"] == []
    assert prompts
    _assert_conversational_prompt(prompts[-1], question)


def test_conversational_ask_does_not_write_today_dashboard(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    import app.core.nova.today.service as today_service

    _enable_llm(monkeypatch)
    calls = {"n": 0}
    real = today_service.dashboard

    def wrapped(*args, **kwargs):
        calls["n"] += 1
        return real(*args, **kwargs)

    monkeypatch.setattr(today_service, "dashboard", wrapped)
    asked = client.post(
        "/api/nova/today/ask",
        headers=_headers(client),
        json={"question": "What is the weather today?"},
    )
    assert asked.status_code == 200, asked.text
    assert calls["n"] == 0


def test_operational_ask_still_reads_today_dashboard(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    import app.core.nova.today.service as today_service

    _enable_llm(monkeypatch)
    calls = {"n": 0}
    real = today_service.dashboard

    def wrapped(*args, **kwargs):
        calls["n"] += 1
        return real(*args, **kwargs)

    monkeypatch.setattr(today_service, "dashboard", wrapped)
    asked = client.post(
        "/api/nova/today/ask",
        headers=_headers(client),
        json={"question": "What needs my attention today?"},
    )
    assert asked.status_code == 200, asked.text
    assert calls["n"] == 1


def test_operational_attention_ask_keeps_today_supporting_context(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    prompts = _enable_llm(monkeypatch)
    asked = client.post(
        "/api/nova/today/ask",
        headers=_headers(client),
        json={"question": "What needs my attention today?"},
    )
    assert asked.status_code == 200, asked.text
    body = asked.json()
    assert body["answer"]
    assert "attention" in body["answer"].lower()
    assert "Align this week targets" not in body["next_actions"]
    assert prompts
    prompt = prompts[-1]
    assert "PRIMARY USER PROMPT" in prompt
    assert "What needs my attention today?" in prompt
    assert "SUPPORTING TODAY CONTEXT" in prompt
    assert "3 concrete next actions" not in prompt
    assert "health_isf_summary" not in prompt
    assert "Mailbox connector disconnected" not in prompt
    assert "never been connected" in prompt.lower() or "not configured" in prompt.lower()
    assert "not an error" in prompt.lower()


def test_shared_nova_ask_still_requires_operational_next_actions(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    login = client.post(
        "/api/auth/login",
        json={"email": "dispatcher@amicor.local", "password": SEED_PASSWORD},
    )
    assert login.status_code == 200, login.text
    org_id = login.json()["organization_id"]
    prompts = _enable_llm(monkeypatch)
    from app.db.session import SessionLocal

    with SessionLocal() as db:
        result = NovaCoreService.ask(
            db,
            organization_id=org_id,
            mode="founder_advisor",
            question="How is dispatch?",
        )
    assert result.next_actions
    assert "Align this week targets to one measurable platform KPI." in result.next_actions
    assert prompts
    assert "3 concrete next actions" in prompts[-1]
    assert "Use only provided context" in prompts[-1]


def test_today_ask_still_blocks_external_mutations(client: TestClient) -> None:
    owner = _headers(client)
    assert client.post("/api/nova/today/send", headers=owner).status_code == 403
    assert client.post("/api/nova/today/file", headers=owner).status_code == 403
    assert client.post("/api/nova/today/call", headers=owner).status_code == 403
    assert client.post("/api/nova/payments/pay", headers=owner).status_code == 403
