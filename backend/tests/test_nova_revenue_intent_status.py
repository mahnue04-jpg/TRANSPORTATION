"""Cross-page discovery and honest status evidence regressions."""
import pytest
from fastapi.testclient import TestClient
from app.auth import SEED_PASSWORD, ensure_auth_schema, seed_default_users
from app.core.nova.memory import DEFAULT_MEMORY_STATE
from app.core.nova.service import NovaCoreService
from app.core.nova.today import service as today
from app.core.nova.today.schemas import NovaTodayBrainOut
from app.main import app


@pytest.fixture(scope="module")
def client():
    ensure_auth_schema()
    seed_default_users()
    return TestClient(app)


def headers(client, email="dispatcher@amicor.local"):
    result = client.post("/api/auth/login", json={"email": email, "password": SEED_PASSWORD})
    assert result.status_code == 200, result.text
    return {"Authorization": "Bearer " + result.json()["access_token"]}


@pytest.mark.parametrize("page", ["workspace", "business"])
@pytest.mark.parametrize("kind", ["jobs", "clients"])
def test_discovery_uses_existing_pipeline_with_sources(client, monkeypatch, page, kind):
    calls = []
    def search(db, **kwargs):
        calls.append(kwargs)
        return NovaTodayBrainOut(answer="Search completed: one qualified result, draft ready for review.", fact_label="VERIFIED DATA", next_actions=["Review application"], generated_at="2026-10-01T00:00:00Z", source_href="/nova/work", sources=[{"title": "Buyer", "url": "https://example.com/request"}], verification_status="verified")
    monkeypatch.setenv("NOVA_V3_OWNER_EMAILS", "dispatcher@amicor.local")
    monkeypatch.setattr(today, "_run_work_revenue_job_search" if kind == "jobs" else "_find_nova_anonymous_clients", search)
    question = "Find suitable revenue-ready jobs and prepare applications for my review" if kind == "jobs" else "Find clients for AMICOR Nova Anonymous Operations Agent"
    result = client.post(f"/api/nova/{page}/ask", headers=headers(client), json={"action": "ask", "question": question})
    assert result.status_code == 200, result.text
    data = result.json()
    assert len(calls) == 1
    assert calls[0]["user"].email == "dispatcher@amicor.local"
    assert data["sources"][0]["url"] == "https://example.com/request"
    assert data["source_href"] == "/nova/work"
    assert data["fact_label"] == "VERIFIED DATA"
    assert "draft ready" in data["answer"]


@pytest.mark.parametrize("page", ["workspace", "business"])
def test_nonowner_cannot_invoke_revenue_pipeline(client, monkeypatch, page):
    monkeypatch.setenv("NOVA_V3_OWNER_EMAILS", "dispatcher@amicor.local")
    def forbidden(*args, **kwargs):
        pytest.fail("Non-owner reached discovery")
    monkeypatch.setattr(today, "_run_work_revenue_job_search", forbidden)
    result = client.post(f"/api/nova/{page}/ask", headers=headers(client, "staff@amicor.local"), json={"action": "ask", "question": "Find jobs for me"})
    assert result.status_code == 403, result.text


@pytest.mark.parametrize("page", ["workspace", "business"])
def test_failed_discovery_returns_unavailable_not_setup_advice(client, monkeypatch, page):
    monkeypatch.setenv("NOVA_V3_OWNER_EMAILS", "dispatcher@amicor.local")
    def failed(*args, **kwargs):
        raise RuntimeError("provider unavailable")
    monkeypatch.setattr(today, "_find_nova_anonymous_clients", failed)
    result = client.post(f"/api/nova/{page}/ask", headers=headers(client), json={"action": "ask", "question": "Find clients for Nova Anonymous Operations Agent"})
    assert result.status_code == 200, result.text
    assert "couldn't complete" in result.json()["answer"]
    assert result.json()["sources"] == []
    assert result.json()["fact_label"] != "VERIFIED DATA"


def test_legacy_defaults_and_completion_are_unknown(monkeypatch):
    monkeypatch.setattr("app.core.nova.service.memory_store.read", lambda _org: dict(DEFAULT_MEMORY_STATE))
    memory = NovaCoreService._read_memory("owner-org")
    for key in ["business_setup_status", "deployment_readiness_status", "current_build_phase"]:
        assert "Unknown" in memory[key]
    for readiness in ["high", "medium", "low"]:
        completion = NovaCoreService._build_completion_estimate(memory, {"enterprise_readiness": readiness})
        assert "Unknown" in completion
        assert "%" not in completion
    assert "unverified" in NovaCoreService._build_business_checklist_status(memory)


def test_saved_nondefault_status_is_preserved_as_unverified(monkeypatch):
    saved = dict(DEFAULT_MEMORY_STATE, business_setup_status="Owner reports completed setup", deployment_readiness_status="production-owner-recorded")
    monkeypatch.setattr("app.core.nova.service.memory_store.read", lambda _org: saved)
    memory = NovaCoreService._read_memory("owner-org")
    assert memory["business_setup_status"] == saved["business_setup_status"]
    assert "unverified" in NovaCoreService._build_business_checklist_status(memory)
    assert "%" not in NovaCoreService._build_completion_estimate(memory, {"enterprise_readiness": "high"})


@pytest.mark.parametrize("page", ["workspace", "business"])
def test_saas_customer_cannot_use_owner_search(client, monkeypatch, page):
    monkeypatch.setenv("NOVA_V3_OWNER_EMAILS", "dispatcher@amicor.local")
    monkeypatch.setattr("app.core.nova.work_revenue.router.customer_access", lambda *args, **kwargs: {"nova_saas_customer": True})
    result = client.post(f"/api/nova/{page}/ask", headers=headers(client), json={"action": "ask", "question": "Find jobs for me"})
    assert result.status_code == 403, result.text


def test_status_prompt_contains_unknowns_and_evidence_rules(client, monkeypatch):
    prompts = []
    monkeypatch.setattr("app.core.nova.service.memory_store.read", lambda _org: dict(DEFAULT_MEMORY_STATE))
    monkeypatch.setattr(NovaCoreService, "_can_use_llm", classmethod(lambda cls: True))
    monkeypatch.setattr("app.ai.ask_openai", lambda prompt: prompts.append(prompt) or "Status is unknown without evidence.")
    result = client.post("/api/nova/ask", headers=headers(client), json={"mode": "founder_advisor", "question": "Summarize platform status"})
    assert result.status_code == 200, result.text
    assert len(prompts) == 1
    assert "no measured build completion" in prompts[0]
    assert "Memory is saved context, not verified current status" in prompts[0]
    assert "foundation-in-progress" not in prompts[0]
    assert "staging-validation-pending" not in prompts[0]
    assert "72%" not in prompts[0]
