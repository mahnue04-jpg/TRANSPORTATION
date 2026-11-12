"""Development-only owner-review evidence export.

Uses fictional simulated records. The export is read-only: it does not submit
an application, change approval state, or include another tenant or user.
"""
from __future__ import annotations

import csv
from datetime import datetime, timedelta, timezone
from io import StringIO
from types import SimpleNamespace
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient

from app.auth import SEED_PASSWORD, ensure_auth_schema, seed_default_users
from app.core.nova.work_revenue.owner_review_evidence import (
    _history_text,
    csv_safe,
    redact_text,
)
from app.core.nova.work_revenue.schema_ensure import ensure_work_revenue_schema
from app.db.session import engine
from app.main import app

EXPORT_PATH = "/api/nova/work/owner-review/evidence-export"


@pytest.fixture(scope="module")
def client() -> TestClient:
    ensure_auth_schema()
    seed_default_users()
    ensure_work_revenue_schema(engine)
    return TestClient(app)


def _headers(client: TestClient, email: str = "dispatcher@amicor.local") -> dict[str, str]:
    response = client.post("/api/auth/login", json={"email": email, "password": SEED_PASSWORD})
    assert response.status_code == 200, response.text
    return {"Authorization": f"Bearer {response.json()['access_token']}"}


def _allow_development(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        "app.core.nova.work_revenue.owner_review_evidence.is_production_runtime",
        lambda: False,
    )


def _forbid_submission(monkeypatch: pytest.MonkeyPatch) -> dict[str, int]:
    calls = {"count": 0}

    def _blocked(*_args, **_kwargs):
        calls["count"] += 1
        raise AssertionError("evidence export must not submit an application")

    monkeypatch.setattr("app.core.nova.work_revenue.submission.submit_or_handoff", _blocked)
    monkeypatch.setattr("app.core.nova.work_revenue.submission.submit_via_confirmed_email", _blocked)
    return calls


def _fictional_body(token: str, **overrides) -> dict:
    body = {
        "source": "simulated",
        "source_type": "simulated",
        "company_name": "Fictional Harbor Ledger",
        "opportunity_title": f"Remote data entry contractor {token}",
        "description": (
            "Remote 1099 data entry for spreadsheet cleanup, CRM notes, email drafts, "
            "and administrative reporting. Independent contractor. No certification required. "
            "No upfront fee. No residency requirement. Fully remote."
        ),
        "location": "Remote",
        "remote_status": "remote",
        "engagement_type": "contract",
        "compensation_type": "hourly",
        "compensation_amount": 40,
        "compensation_period": "hour",
        "currency": "USD",
        "requirements": "Spreadsheet cleanup and CRM notes.",
        "skills_required": ["data entry", "crm", "reporting"],
        "credentials_required": [],
        "physical_presence_required": "false",
        "source_url": f"https://example.invalid/jobs/{token}",
        "notes": f"Fictional owner note {token}",
    }
    body.update(overrides)
    return body


def _save_fictional(client: TestClient, headers: dict[str, str], **overrides) -> dict:
    token = overrides.pop("token", uuid4().hex[:10])
    decision_notes = overrides.pop("decision_notes", "Fictional owner approval. Do not send.")
    created = client.post(
        "/api/nova/work/opportunities",
        headers=headers,
        json=_fictional_body(token, **overrides),
    )
    assert created.status_code == 200, created.text
    opportunity = created.json()
    qualified = client.post(
        f"/api/nova/work/opportunities/{opportunity['opportunity_id']}/qualify",
        headers=headers,
    )
    assert qualified.status_code == 200, qualified.text
    application = client.post(
        "/api/nova/work/applications",
        headers=headers,
        json={"opportunity_id": opportunity["opportunity_id"], "applicant_party": "AMICOR"},
    )
    assert application.status_code == 200, application.text
    ready = client.post(
        f"/api/nova/work/applications/{application.json()['application_id']}/ready-for-review",
        headers=headers,
    )
    assert ready.status_code == 200, ready.text
    decision = client.post(
        f"/api/nova/work/applications/{application.json()['application_id']}/decision",
        headers=headers,
        json={
            "decision": "APPROVED",
            "notes": decision_notes,
        },
    )
    assert decision.status_code == 200, decision.text
    approved = decision.json()
    assert approved["externally_submitted"] is False
    assert approved["approved_for_future_submission"] is True
    return {
        "opportunity_id": opportunity["opportunity_id"],
        "application_id": approved["application_id"],
        "source_url": opportunity["source_url"],
        "token": token,
    }


def _csv_rows(text: str) -> list[dict[str, str]]:
    return list(csv.DictReader(StringIO(text)))


def test_history_keeps_recent_approval_when_older_text_exceeds_the_cap() -> None:
    start = datetime(2026, 1, 1, tzinfo=timezone.utc)
    history = []
    audits = []
    for index in range(40):
        stamp = start + timedelta(minutes=index)
        history.append(SimpleNamespace(
            created_at=stamp,
            from_status="READY_FOR_OWNER_REVIEW",
            to_status="NEEDS_CHANGES",
            ref_type="application",
            note="change request " + ("n" * 180),
        ))
        audits.append(SimpleNamespace(
            created_at=stamp,
            event_type="APPLICATION_STATUS_CHANGED",
            summary="Owner requested changes. " + ("t" * 220),
        ))
    approved_at = start + timedelta(hours=3)
    audits.append(SimpleNamespace(
        created_at=approved_at,
        event_type="OWNER_APPROVED_APPLICATION",
        summary="Owner approved application for FUTURE submission only.",
    ))
    history.append(SimpleNamespace(
        created_at=approved_at,
        from_status="READY_FOR_OWNER_REVIEW",
        to_status="APPROVED",
        ref_type="application",
        note="APPROVED",
    ))
    text = _history_text(
        history,
        audits,
        approval_note="2026-01-01T03:00:00+00:00 approval_note Fictional owner approval. Do not send.",
    )
    assert "OWNER_APPROVED_APPLICATION" in text
    assert "approval_note Fictional owner approval. Do not send." in text
    assert "->APPROVED" in text
    assert len(text) <= 2001


def test_csv_formula_cells_are_prefixed() -> None:
    for raw in ("=HYPERLINK(\"https://evil.invalid\")", "+1+1", "-10+1", "@SUM(A1)", "\t=1+1", " =1+1"):
        escaped = csv_safe(raw)
        assert escaped.startswith("'"), raw
        assert not escaped.lstrip("'").startswith(raw[0]) or escaped[0] == "'"


def test_redaction_removes_contact_and_secret_text() -> None:
    raw = (
        "Call 612-555-0144 or jane.doe@example.invalid. SSN 123-45-6789. "
        "password=hunter2 api_key=sk_live_example bearer tok_123"
    )
    cleaned = redact_text(raw)
    assert "612-555-0144" not in cleaned
    assert "jane.doe@example.invalid" not in cleaned
    assert "123-45-6789" not in cleaned
    assert "hunter2" not in cleaned
    assert "sk_live_example" not in cleaned
    assert "[redacted-phone]" in cleaned
    assert "[redacted-email]" in cleaned
    assert "[redacted-ssn]" in cleaned
    assert "[redacted]" in cleaned


def test_export_includes_fictional_saved_opportunity_evidence(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _allow_development(monkeypatch)
    calls = _forbid_submission(monkeypatch)
    headers = _headers(client)
    saved = _save_fictional(client, headers)
    before = client.get(f"/api/nova/work/applications/{saved['application_id']}", headers=headers)
    assert before.status_code == 200, before.text
    approval_state = before.json()["approval_state"]

    exported = client.get(EXPORT_PATH, headers=headers)
    assert exported.status_code == 200, exported.text
    assert exported.headers["content-type"].startswith("text/csv")
    assert "no-store" in exported.headers["cache-control"]
    assert calls["count"] == 0
    rows = _csv_rows(exported.text)
    match = next(row for row in rows if row["opportunity_id"] == saved["opportunity_id"])
    assert match["export_scope"] == "development_fictional"
    assert match["source_url"] == saved["source_url"]
    assert "example.invalid" in match["source_url"]
    assert match["qualification_outcome"]
    assert match["qualification_reason"]
    assert match["application_id"] == saved["application_id"]
    assert match["proposal_status"] == "DRAFT"
    assert match["application_status"] == "APPROVED"
    assert match["approved_for_future_submission"] == "true"
    assert match["externally_submitted"] == "false"
    assert "OWNER_APPROVED_APPLICATION" in match["approval_history"]
    assert "READY_FOR_OWNER_REVIEW" in match["approval_history"]
    assert match["created_at"]
    assert match["updated_at"]
    assert match["discovered_at"]
    assert match["qualified_at"]
    assert match["decided_at"]
    assert "Fictional Harbor Ledger" in match["company_name"]

    after = client.get(f"/api/nova/work/applications/{saved['application_id']}", headers=headers)
    assert after.status_code == 200, after.text
    assert after.json()["approval_state"] == approval_state
    assert after.json()["externally_submitted"] is False
    assert after.json()["approved_for_future_submission"] is True
    assert calls["count"] == 0


def test_export_redacts_privacy_and_neutralizes_formula_injection(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _allow_development(monkeypatch)
    headers = _headers(client)
    token = uuid4().hex[:10]
    formula = '=HYPERLINK("https://evil.invalid/steal","open")'
    secret_note = (
        "Reach jane.doe@example.invalid or 612-555-0144. "
        "SSN 123-45-6789 password=hunter2"
    )
    saved = _save_fictional(
        client,
        headers,
        token=token,
        opportunity_title=formula,
        notes=secret_note,
        decision_notes=secret_note + " " + formula,
    )
    exported = client.get(EXPORT_PATH, headers=headers, params={"format": "csv"})
    assert exported.status_code == 200, exported.text
    assert "jane.doe@example.invalid" not in exported.text
    assert "612-555-0144" not in exported.text
    assert "123-45-6789" not in exported.text
    assert "hunter2" not in exported.text
    assert "[redacted-email]" in exported.text
    assert "[redacted-phone]" in exported.text
    assert "[redacted-ssn]" in exported.text
    rows = _csv_rows(exported.text)
    match = next(row for row in rows if row["opportunity_id"] == saved["opportunity_id"])
    assert match["opportunity_title"].startswith("'")
    assert "jane.doe@example.invalid" not in match["saved_notes"]
    assert "hunter2" not in match["approval_history"]
    assert "=HYPERLINK" in match["approval_history"]
    for value in match.values():
        assert value.lstrip(" \t")[:1] not in "=+-@", value


def test_export_json_stays_user_scoped_and_omits_non_fictional_records(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _allow_development(monkeypatch)
    owner = _headers(client, "dispatcher@amicor.local")
    other = _headers(client, "admin@amicor.local")
    token = uuid4().hex[:10]
    saved = _save_fictional(client, owner, token=token)
    manual = client.post(
        "/api/nova/work/opportunities",
        headers=owner,
        json={
            "source": "manual",
            "source_type": "manual",
            "company_name": "Example Operations Co",
            "opportunity_title": f"Manual live-style lead {token}",
            "description": "Remote administrative support. Fully remote.",
            "source_url": "https://example.invalid/jobs/manual-" + token,
            "physical_presence_required": "false",
        },
    )
    assert manual.status_code == 200, manual.text
    live_url = client.post(
        "/api/nova/work/opportunities",
        headers=owner,
        json=_fictional_body(
            token + "live",
            source_url="https://jobs.example.com/not-reserved",
            opportunity_title=f"Simulated with a live-looking url {token}",
        ),
    )
    assert live_url.status_code == 200, live_url.text

    owner_export = client.get(EXPORT_PATH, headers=owner, params={"format": "json"})
    assert owner_export.status_code == 200, owner_export.text
    body = owner_export.json()
    assert body["development_only"] is True
    assert body["external_submission"] is False
    assert body["applications_submitted_by_export"] is False
    assert body["fictional_records_only"] is True
    assert body["tenant_scoped"] is True
    assert body["user_scoped"] is True
    assert body["omitted_non_fictional_count"] >= 2
    assert body["truncated_count"] == 0
    ids = {row["opportunity_id"] for row in body["rows"]}
    assert saved["opportunity_id"] in ids
    assert manual.json()["opportunity_id"] not in ids
    assert live_url.json()["opportunity_id"] not in ids
    assert "jobs.example.com" not in owner_export.text

    other_export = client.get(EXPORT_PATH, headers=other, params={"format": "json"})
    assert other_export.status_code == 200, other_export.text
    other_ids = {row["opportunity_id"] for row in other_export.json()["rows"]}
    assert saved["opportunity_id"] not in other_ids
    assert manual.json()["opportunity_id"] not in other_ids


def test_export_rejects_cross_tenant_signed_out_non_owner_and_production(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _allow_development(monkeypatch)
    headers = _headers(client)
    saved = _save_fictional(client, headers)
    assert client.get(EXPORT_PATH).status_code == 401
    rider = _headers(client, "rider@amicor.local")
    denied = client.get(EXPORT_PATH, headers=rider)
    assert denied.status_code in {401, 403}
    cross = client.get(EXPORT_PATH, headers=headers, params={"organization_id": "org-not-the-caller"})
    assert cross.status_code == 403
    assert saved["opportunity_id"] not in cross.text
    unknown = client.get(EXPORT_PATH, headers=headers, params={"format": "xlsx"})
    assert unknown.status_code == 400

    monkeypatch.setattr(
        "app.core.nova.work_revenue.owner_review_evidence.is_production_runtime",
        lambda: True,
    )
    blocked = client.get(EXPORT_PATH, headers=headers, params={"format": "json"})
    assert blocked.status_code == 403
    assert blocked.json()["detail"] == "Owner-review evidence export is development-only."
    assert saved["opportunity_id"] not in blocked.text
    blocked_csv = client.get(EXPORT_PATH, headers=headers)
    assert blocked_csv.status_code == 403
    assert saved["opportunity_id"] not in blocked_csv.text
