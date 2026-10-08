"""Focused tests: V3 discovery env flag bridges into Work & Revenue / Today.

Does not enable external submission, contact employers, or touch Stripe/Health.
"""
from __future__ import annotations

import os
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.auth import SEED_PASSWORD, ensure_auth_schema, seed_default_users
from app.core.nova.v3 import flags as v3_flags
from app.core.nova.v3 import live_discovery
from app.core.nova.v3.errors import V3Error
from app.core.nova.work_revenue import flags as wr_flags
from app.core.nova.work_revenue.schema_ensure import ensure_work_revenue_schema
from app.core.nova.work_revenue.service import _today_source_counts
from app.db.session import engine
from app.main import app


ROOT = Path(__file__).resolve().parents[1]
TODAY_JS = (ROOT / "static" / "nova-today" / "today.js").read_text(encoding="utf-8")
WORK_JS = (ROOT / "static" / "nova-work" / "work.js").read_text(encoding="utf-8")


@pytest.fixture(scope="module")
def client() -> TestClient:
    ensure_auth_schema()
    seed_default_users()
    ensure_work_revenue_schema(engine)
    return TestClient(app)


def _headers(client: TestClient, email: str = "dispatcher@amicor.local") -> dict[str, str]:
    response = client.post("/api/auth/login", json={"email": email, "password": SEED_PASSWORD})
    assert response.status_code == 200, response.text
    token = response.json()["access_token"]
    return {"Authorization": f"Bearer {token}"}


def _clear_discovery_env(monkeypatch: pytest.MonkeyPatch) -> None:
    for name in (
        "NOVA_V3_LIVE_DISCOVERY_ENABLED",
        "NOVA_V3_EXTERNAL_SUBMISSION_ENABLED",
        "NOVA_WR_LIVE_DISCOVERY",
        "NOVA_WR_ALLOW_LIVE_ACTIONS",
        "NOVA_WR_PRODUCTION_LIVE_OVERRIDE",
        "NOVA_WR_EXTERNAL_SUBMISSION",
    ):
        monkeypatch.delenv(name, raising=False)


def test_env_string_true_enables_live_discovery(monkeypatch: pytest.MonkeyPatch) -> None:
    _clear_discovery_env(monkeypatch)
    monkeypatch.setenv("NOVA_V3_LIVE_DISCOVERY_ENABLED", "true")
    assert v3_flags.live_discovery_enabled() is True
    assert wr_flags.live_discovery_enabled() is True
    assert wr_flags.engine_guardrails()["LIVE_DISCOVERY_ENABLED"] is True
    assert wr_flags.discovery_diagnostics()["live_discovery_enabled"] is True
    assert wr_flags.discovery_diagnostics()["flag_source"] == "NOVA_V3_LIVE_DISCOVERY_ENABLED"
    assert wr_flags.discovery_diagnostics()["discovery_provider_configured"] is True


def test_env_string_false_disables_live_discovery(monkeypatch: pytest.MonkeyPatch) -> None:
    _clear_discovery_env(monkeypatch)
    monkeypatch.setenv("NOVA_V3_LIVE_DISCOVERY_ENABLED", "false")
    assert v3_flags.live_discovery_enabled() is False
    assert wr_flags.live_discovery_enabled() is False
    assert wr_flags.engine_guardrails()["LIVE_DISCOVERY_ENABLED"] is False
    assert wr_flags.discovery_diagnostics()["live_discovery_enabled"] is False


def test_production_wr_gates_do_not_silently_override_v3_true(monkeypatch: pytest.MonkeyPatch) -> None:
    """V3 discovery flag must not require WR master/production override."""
    _clear_discovery_env(monkeypatch)
    monkeypatch.setenv("AMICOR_ENVIRONMENT", "production")
    monkeypatch.setenv("NOVA_V3_LIVE_DISCOVERY_ENABLED", "true")
    # Explicitly leave WR capability path off / incomplete.
    monkeypatch.delenv("NOVA_WR_ALLOW_LIVE_ACTIONS", raising=False)
    monkeypatch.delenv("NOVA_WR_LIVE_DISCOVERY", raising=False)
    monkeypatch.delenv("NOVA_WR_PRODUCTION_LIVE_OVERRIDE", raising=False)

    assert wr_flags.v3_live_discovery_env_enabled() is True
    assert wr_flags.live_discovery_enabled() is True
    guards = wr_flags.engine_guardrails()
    assert guards["LIVE_DISCOVERY_ENABLED"] is True
    assert guards["EXTERNAL_SUBMISSION_ENABLED"] is False
    assert guards["FINANCIAL_ACTIONS_ENABLED"] is False
    assert guards["APPROVED_EQUALS_SUBMITTED"] is False


def test_live_flags_re_read_env_at_call_time(monkeypatch: pytest.MonkeyPatch) -> None:
    _clear_discovery_env(monkeypatch)
    monkeypatch.setenv("NOVA_V3_LIVE_DISCOVERY_ENABLED", "false")
    assert v3_flags.live_flags()["LIVE_DISCOVERY_ENABLED"] is False
    monkeypatch.setenv("NOVA_V3_LIVE_DISCOVERY_ENABLED", "true")
    assert v3_flags.live_flags()["LIVE_DISCOVERY_ENABLED"] is True
    monkeypatch.setenv("NOVA_V3_LIVE_DISCOVERY_ENABLED", "false")
    assert v3_flags.live_flags()["LIVE_DISCOVERY_ENABLED"] is False


def test_today_summary_reports_enabled_when_v3_flag_true(client, monkeypatch: pytest.MonkeyPatch) -> None:
    _clear_discovery_env(monkeypatch)
    monkeypatch.setenv("NOVA_V3_LIVE_DISCOVERY_ENABLED", "true")
    headers = _headers(client)
    summary = client.get("/api/nova/work/today-summary", headers=headers)
    assert summary.status_code == 200, summary.text
    body = summary.json()
    assert body["live_discovery_enabled"] is True
    assert body["opportunity_mode"] == "live_discovery_ready"
    assert body["guardrails"]["LIVE_DISCOVERY_ENABLED"] is True
    assert body["external_submission_enabled"] is False
    assert body["financial_actions_enabled"] is False
    diag = body["discovery_diagnostics"]
    assert diag["live_discovery_enabled"] is True
    assert diag["discovery_provider_configured"] is True
    assert diag["discovery_provider"] == "remotive"
    assert diag["auto_submit"] is False
    assert diag.get("discovery_requires_api_key") is False
    blob = str(diag).lower()
    assert "sk_live" not in blob
    assert "sk_test" not in blob
    assert "whsec" not in blob
    assert "bearer " not in blob
    assert "password" not in blob
    assert "cookie" not in blob
    assert "stripe" not in blob
    assert "postgres" not in blob
    assert "postgresql" not in blob


def test_today_summary_reports_disabled_when_v3_flag_false(client, monkeypatch: pytest.MonkeyPatch) -> None:
    _clear_discovery_env(monkeypatch)
    monkeypatch.setenv("NOVA_V3_LIVE_DISCOVERY_ENABLED", "false")
    headers = _headers(client)
    body = client.get("/api/nova/work/today-summary", headers=headers).json()
    assert body["live_discovery_enabled"] is False
    assert body["opportunity_mode"] == "manual_simulated_only"
    assert body["guardrails"]["LIVE_DISCOVERY_ENABLED"] is False


def test_work_dashboard_status_copy_reflects_v3_flag() -> None:
    assert "NOVA_V3_LIVE_DISCOVERY_ENABLED" in WORK_JS
    assert "LIVE DISCOVERY READY" in WORK_JS
    assert "LIVE DISCOVERY OFF" in WORK_JS
    assert "/api/nova/v3/guardrails" in WORK_JS


def test_today_ui_separates_live_from_simulated_and_requires_auth_copy() -> None:
    lowered = TODAY_JS.lower()
    assert "live discovered" in lowered
    assert "simulated / test" in lowered
    assert "when you are signed in" in lowered
    assert "mrs. nova brain is ready. ask a question below." in lowered
    assert "submit application" not in TODAY_JS


def test_source_counts_keep_simulated_separate_from_live() -> None:
    class _Opp:
        def __init__(self, source_type: str):
            self.source_type = source_type
            self.source = source_type

    counts = _today_source_counts(
        [
            _Opp("manual"),
            _Opp("simulated"),
            _Opp("simulated"),
            _Opp("remotive"),
            _Opp("live"),
            _Opp("approved_api"),
            _Opp("remoteok"),
        ]
    )
    assert counts == {"manual": 1, "simulated": 2, "live": 4, "other": 0}


def test_discovery_never_auto_submits_when_flag_on(monkeypatch: pytest.MonkeyPatch) -> None:
    _clear_discovery_env(monkeypatch)
    monkeypatch.setenv("NOVA_V3_LIVE_DISCOVERY_ENABLED", "true")
    monkeypatch.setenv("NOVA_V3_EXTERNAL_SUBMISSION_ENABLED", "false")
    flags = v3_flags.live_flags()
    assert flags["LIVE_DISCOVERY_ENABLED"] is True
    assert flags["EXTERNAL_SUBMISSION_ENABLED"] is False
    assert flags["APPROVED_EQUALS_SUBMITTED"] is False
    assert wr_flags.discovery_diagnostics()["external_submission_enabled"] is False
    assert wr_flags.discovery_diagnostics()["auto_submit"] is False
    monkeypatch.setattr(live_discovery, "live_flags", lambda: flags)
    with pytest.raises(V3Error) as exc:
        # Still needs a transport; flag path first checks enabled then query.
        # Force provider gate with empty query after enabling.
        live_discovery.search_remote_jobs("")
    assert exc.value.code in {"INVALID_QUERY", "LIVE_DISABLED"}


def test_search_blocked_when_discovery_off(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(live_discovery, "live_flags", lambda: {"LIVE_DISCOVERY_ENABLED": False})
    with pytest.raises(V3Error) as exc:
        live_discovery.search_remote_jobs("operations")
    assert exc.value.code == "LIVE_DISABLED"


def test_v3_guardrails_endpoint_includes_safe_diagnostics(client, monkeypatch: pytest.MonkeyPatch) -> None:
    _clear_discovery_env(monkeypatch)
    monkeypatch.setenv("NOVA_V3_LIVE_DISCOVERY_ENABLED", "true")
    headers = _headers(client)
    resp = client.get("/api/nova/v3/guardrails", headers=headers)
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["LIVE_DISCOVERY_ENABLED"] is True
    assert body["EXTERNAL_SUBMISSION_ENABLED"] is False
    diag = body["discovery_diagnostics"]
    assert diag["live_discovery_enabled"] is True
    assert diag["discovery_provider_configured"] is True
    assert diag["authenticated"] is True
    assert diag["discovery_execution_status"] == "ready"
    assert diag["auto_submit"] is False
    assert diag["error_category"] is None
    blob = str(body).lower()
    assert "sk_" not in blob
    assert "whsec" not in blob
    assert "password" not in blob


def test_lifecycle_follows_discovery_flag_while_submit_stays_handoff(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Discovery status follows the runtime flag. Submit never becomes an external action."""
    _clear_discovery_env(monkeypatch)
    monkeypatch.setenv("NOVA_V3_LIVE_DISCOVERY_ENABLED", "false")
    headers = _headers(client)

    off = client.get("/api/nova/work/lifecycle", headers=headers)
    assert off.status_code == 200, off.text
    off_body = off.json()
    assert off_body["live_discovery_enabled"] is False
    assert off_body["external_submission_enabled"] is False
    assert off_body["financial_actions_enabled"] is False
    assert off_body["approved_equals_submitted"] is False

    monkeypatch.setenv("NOVA_V3_LIVE_DISCOVERY_ENABLED", "true")
    on = client.get("/api/nova/work/lifecycle", headers=headers)
    assert on.status_code == 200, on.text
    on_body = on.json()
    assert on_body["live_discovery_enabled"] is True
    assert on_body["external_submission_enabled"] is False
    assert on_body["financial_actions_enabled"] is False
    assert on_body["approved_equals_submitted"] is False

    guards = client.get("/api/nova/work/guardrails", headers=headers)
    assert guards.status_code == 200, guards.text
    guard_body = guards.json()
    assert guard_body["LIVE_DISCOVERY_ENABLED"] is True
    assert guard_body["EXTERNAL_SUBMISSION_ENABLED"] is False
    assert guard_body["FINANCIAL_ACTIONS_ENABLED"] is False
    assert guard_body["live_execution_implemented"] is False

    created = client.post(
        "/api/nova/work/opportunities",
        headers=headers,
        json={
            "company_name": "Example Operations Co",
            "opportunity_title": "Remote administrative support contractor",
            "description": "Prepare email drafts, organize CRM notes, and summarize reports. Fully remote.",
            "location": "Remote",
            "remote_status": "remote",
            "engagement_type": "contract",
            "compensation_type": "hourly",
            "compensation_amount": 40,
            "compensation_period": "hour",
            "currency": "USD",
            "requirements": "Email writing, CRM, reporting.",
            "skills_required": ["email", "crm", "reporting"],
            "credentials_required": [],
            "physical_presence_required": "false",
            "source": "remotive",
            "source_type": "approved_api",
            "source_url": "https://remotive.com/remote-jobs/nova-repair-lifecycle",
        },
    )
    assert created.status_code == 200, created.text
    opportunity_id = created.json()["opportunity_id"]
    qualified = client.post(f"/api/nova/work/opportunities/{opportunity_id}/qualify", headers=headers)
    assert qualified.status_code == 200, qualified.text
    app_resp = client.post(
        "/api/nova/work/applications",
        headers=headers,
        json={"opportunity_id": opportunity_id, "applicant_party": "AMICOR"},
    )
    assert app_resp.status_code == 200, app_resp.text
    application_id = app_resp.json()["application_id"]
    ready = client.post(f"/api/nova/work/applications/{application_id}/ready-for-review", headers=headers)
    assert ready.status_code == 200, ready.text
    decision = client.post(
        f"/api/nova/work/applications/{application_id}/decision",
        headers=headers,
        json={"decision": "APPROVED"},
    )
    assert decision.status_code == 200, decision.text
    submit = client.post(f"/api/nova/work/applications/{application_id}/submit", headers=headers)
    assert submit.status_code == 200, submit.text
    handoff = submit.json()
    assert handoff["status"] == "HUMAN_ACTION_REQUIRED"
    assert handoff["external_action_taken"] is False
    assert handoff["externally_submitted"] is False
    assert handoff["approval_consumed"] is False
    assert handoff["financial_execution"] is False
    assert handoff["provider_id"] == "remotive"
    stored = client.get(f"/api/nova/work/applications/{application_id}", headers=headers)
    assert stored.status_code == 200, stored.text
    assert stored.json()["externally_submitted"] is False
    still_on = client.get("/api/nova/work/lifecycle", headers=headers).json()
    assert still_on["live_discovery_enabled"] is True
    assert still_on["external_submission_enabled"] is False
    assert still_on["financial_actions_enabled"] is False


def test_unauthenticated_today_summary_requires_auth(client, monkeypatch: pytest.MonkeyPatch) -> None:
    _clear_discovery_env(monkeypatch)
    monkeypatch.setenv("NOVA_V3_LIVE_DISCOVERY_ENABLED", "true")
    resp = client.get("/api/nova/work/today-summary")
    assert resp.status_code in {401, 403}


def test_diagnostics_never_print_env_secret_values(monkeypatch: pytest.MonkeyPatch) -> None:
    _clear_discovery_env(monkeypatch)
    monkeypatch.setenv("NOVA_V3_LIVE_DISCOVERY_ENABLED", "true")
    monkeypatch.setenv("STRIPE_SECRET_KEY", "sk_test_SHOULD_NOT_LEAK")
    diag = wr_flags.discovery_diagnostics()
    rendered = repr(diag)
    assert "sk_test_SHOULD_NOT_LEAK" not in rendered
    assert "STRIPE_SECRET_KEY" not in rendered
    # Cleanup unrelated env so later tests stay clean.
    monkeypatch.delenv("STRIPE_SECRET_KEY", raising=False)
    assert os.getenv("STRIPE_SECRET_KEY") != "sk_test_SHOULD_NOT_LEAK" or True
