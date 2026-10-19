"""First-client board, honest search status, and draft bid materials.

No live job source and no email provider are contacted.
"""
from __future__ import annotations

import json
import uuid
from datetime import datetime, timedelta, timezone

import httpx
import pytest
from fastapi.testclient import TestClient

from app.auth import SEED_PASSWORD, UserContext, ensure_auth_schema, seed_default_users
from app.core.nova.v3.multi_source_discovery import (
    ProviderMeta,
    call_provider_search,
    classify_live_search,
    normalize_opportunity,
    reset_provider_health_for_tests,
    search_multi_source_jobs,
)
from app.core.nova.work_revenue.first_client_pipeline import (
    draft_targeted_proposals,
    set_submission_transport,
)
from app.core.nova.work_revenue.materials import generate_drafts
from app.core.nova.v3.work_revenue_bridge import persist_live_job, source_eligibility_reasons
from app.core.nova.work_revenue.models import (
    NovaWorkApplication,
    NovaWorkMaterial,
    NovaWorkOpportunity,
    NovaWorkSubmissionLedger,
)
from app.core.nova.work_revenue.schema_ensure import ensure_work_revenue_schema
from app.db.session import SessionLocal, engine
from app.main import app


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


def _opportunity(client: TestClient, headers: dict[str, str], title: str, **overrides) -> dict:
    body = {
        "company_name": "Northwind Records",
        "opportunity_title": title,
        "description": (
            "Remote 1099 data entry, CRM notes, and administrative reporting. "
            "Independent contractor. No certification required. No upfront fee."
        ),
        "location": "Remote",
        "remote_status": "remote",
        "engagement_type": "contract",
        "physical_presence_required": "false",
        "source_url": "https://example.com/roles/" + title.replace(" ", "-").lower(),
    }
    body.update(overrides)
    created = client.post("/api/nova/work/opportunities", headers=headers, json=body)
    assert created.status_code == 200, created.text
    return created.json()


def _approve(client: TestClient, headers: dict[str, str], title: str) -> dict:
    created = _opportunity(client, headers, title)
    qualified = client.post(
        f"/api/nova/work/opportunities/{created['opportunity_id']}/qualify",
        headers=headers,
    )
    assert qualified.status_code == 200, qualified.text
    application = client.post(
        "/api/nova/work/applications",
        headers=headers,
        json={"opportunity_id": created["opportunity_id"]},
    )
    assert application.status_code == 200, application.text
    ready = client.post(
        f"/api/nova/work/applications/{application.json()['application_id']}/ready-for-review",
        headers=headers,
    )
    assert ready.status_code == 200, ready.text
    approved = client.post(
        f"/api/nova/work/applications/{application.json()['application_id']}/decision",
        headers=headers,
        json={"decision": "APPROVED"},
    )
    assert approved.status_code == 200, approved.text
    return approved.json()


class _PermittedTransport:
    """In-process double. It records a receipt and does not open a socket."""

    def __init__(self, *, fail: bool = False) -> None:
        self.calls = 0
        self.fail = fail
        self.network_used = False
        self.permitted_channel = {"channel_id": "fake-channel", "permitted": True, "recipient": "applications@example.invalid"}

    def deliver(self, message: dict) -> dict:
        self.calls += 1
        if self.fail:
            return {
                "state": "DELIVERY_FAILURE",
                "receipt": None,
                "reason": "fake mailbox rejected the message",
                "network_used": False,
            }
        return {
            "state": "SENT",
            "receipt": "fake-receipt-1",
            "network_used": False,
        }


def _clear_owner_input(application_id: str) -> None:
    with SessionLocal() as db:
        rows = db.query(NovaWorkMaterial).filter(NovaWorkMaterial.application_id == application_id).all()
        for row in rows:
            row.body = str(row.body or "").replace("OWNER INPUT REQUIRED", "owner supplied this fact")
        db.commit()


class _FlakyProvider:
    meta = ProviderMeta(
        provider_id="flaky_test",
        label="Flaky test",
        provider_type="remote_contract_feed",
        enabled=True,
        access_status="public_api",
        access_mode="api",
        requires_login=False,
        requires_fee=False,
        supports_detail_fetch=False,
        supports_external_submission=False,
        terms_safety_notes="test only",
        priority=1,
    )

    def __init__(self, failures: int) -> None:
        self.failures = failures
        self.calls = 0

    def search(self, query: str, *, limit: int = 10) -> list[dict]:
        self.calls += 1
        if self.calls <= self.failures:
            raise httpx.TimeoutException("timed out")
        return [
            normalize_opportunity(
                provider_id="flaky_test",
                provider_type="remote_contract_feed",
                source_url="https://example.com/roles/flaky",
                title="Remote notes contractor",
                company_name="Example Records",
                description="Remote contractor notes.",
                remote_status="remote",
            )
        ]


def test_work_page_includes_the_mobile_first_client_board(client: TestClient) -> None:
    page = client.get("/nova/work")
    assert page.status_code == 200
    html = page.text
    assert "First client board" in html
    assert "/static/nova-work/first-client.js" in html
    assert "/static/nova-work/first-client.css" in html
    script = client.get("/static/nova-work/first-client.js")
    assert script.status_code == 200
    assert "Store mock receipt" in script.text
    assert "mock_receipt_consent" in script.text
    assert "source_eligibility_reasons" in script.text
    assert "visibilitychange" in script.text
    assert "Sent vs draft" in script.text
    assert "Fetched at" in script.text
    assert "pageshow" in script.text
    assert "Refresh board" in html
    assert "submit-email" not in script.text
    style = client.get("/static/nova-work/first-client.css")
    assert style.status_code == 200
    assert "@media (max-width: 720px)" in style.text
    discovery = client.get("/static/nova-work/work.js")
    assert "this is not a zero-match result" in discovery.text


def test_classify_live_search_does_not_claim_a_failed_source() -> None:
    failed = classify_live_search(
        {
            "providers_queried": ["remotive"],
            "provider_result_counts": {},
            "provider_errors": [{"provider_id": "remotive", "error": "timeout"}],
            "jobs": [],
        }
    )
    assert failed["live_search_status"] == "unavailable"
    assert failed["live_search_claimed"] is False
    assert failed["empty_reason"] == "source_unavailable"

    empty = classify_live_search(
        {
            "providers_queried": ["remotive"],
            "provider_result_counts": {"remotive": 0},
            "provider_errors": [],
            "jobs": [],
        }
    )
    assert empty["live_search_status"] == "ok"
    assert empty["live_search_claimed"] is True
    assert empty["empty_reason"] == "no_matches"

    # One timeout on a later query must not hide a provider that already
    # returned rows. The aggregated run is partial, not a source outage.
    mixed = classify_live_search(
        {
            "providers_queried": ["remotive", "remoteok"],
            "provider_result_counts": {"remotive": 2, "remoteok": 0},
            "provider_errors": [
                {"provider_id": "remotive", "error": "timeout"},
                {"provider_id": "remoteok", "error": "429"},
            ],
            "jobs": [{"title": "Remote notes"}],
        }
    )
    assert mixed["live_search_status"] == "partial"
    assert mixed["live_search_claimed"] is True
    assert mixed["providers_succeeded"] == ["remotive", "remoteok"]
    assert mixed["providers_failed"] == []
    assert mixed["empty_reason"] is None


def test_provider_search_retries_one_transient_failure(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("app.core.nova.v3.multi_source_discovery._RETRY_SLEEP_SECONDS", 0)
    monkeypatch.setattr(
        "app.core.nova.v3.multi_source_discovery.live_flags",
        lambda: {"LIVE_DISCOVERY_ENABLED": True},
    )
    reset_provider_health_for_tests()
    flaky = _FlakyProvider(failures=1)
    rows = call_provider_search(flaky, "remote notes", limit=5)
    assert flaky.calls == 2
    assert rows[0]["title"] == "Remote notes contractor"

    reset_provider_health_for_tests()
    down = _FlakyProvider(failures=2)
    result = search_multi_source_jobs("remote notes", providers_override=[down])
    assert down.calls == 2
    assert result["live_search_claimed"] is False
    assert result["live_search_status"] == "unavailable"
    assert result["jobs"] == []
    assert result["external_action_taken"] is False


def test_non_transient_provider_error_is_not_retried(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("app.core.nova.v3.multi_source_discovery._RETRY_SLEEP_SECONDS", 0)

    class _Bad(_FlakyProvider):
        def search(self, query: str, *, limit: int = 10) -> list[dict]:
            self.calls += 1
            raise ValueError("bad payload")

    bad = _Bad(failures=0)
    with pytest.raises(ValueError):
        call_provider_search(bad, "remote notes", limit=5)
    assert bad.calls == 1


def test_draft_materials_do_not_invent_credentials() -> None:
    drafts = generate_drafts(
        {
            "opportunity_title": "Remote CRM cleanup",
            "company_name": "Example Records",
            "description": "Preferred: 5 years of CRM work. No upfront fee. Remote contractor.",
            "source_url": "https://example.com/roles/crm",
        }
    )
    by_kind = {item["kind"]: item["body"] for item in drafts}
    for kind in ("evidence_checklist", "paid_pilot_options", "eligibility_assessment"):
        assert kind in by_kind
        assert "OWNER INPUT REQUIRED" in by_kind[kind]
    assert "No certification is claimed" in by_kind["eligibility_assessment"]
    assert "Not a quote" in by_kind["paid_pilot_options"]
    assert "7 calendar days" in by_kind["paid_pilot_options"]
    assert "Example Records" in by_kind["paid_pilot_options"]
    assert "$" not in by_kind["paid_pilot_options"]
    assert "cost_scope_check" in by_kind
    assert "Out of scope" in by_kind["cost_scope_check"]
    assert "Years of experience" in by_kind["evidence_checklist"]
    assert "$" not in by_kind["cost_scope_check"]
    assert "SOC 2" not in by_kind["eligibility_assessment"]
    assert "I have 5 years" not in by_kind["eligibility_assessment"]


def test_board_is_user_scoped_and_caps_the_top_matches(client: TestClient) -> None:
    headers = _headers(client)
    titles = []
    for index in range(11):
        title = f"Board remote contractor {index}"
        titles.append(title)
        created = _opportunity(client, headers, title)
        qualified = client.post(
            f"/api/nova/work/opportunities/{created['opportunity_id']}/qualify",
            headers=headers,
        )
        assert qualified.status_code == 200, qualified.text
    board = client.get("/api/nova/work/first-client/board", headers=headers)
    assert board.status_code == 200, board.text
    body = board.json()
    assert body["live_search_claimed"] is False
    assert body["applications_sent_by_this_request"] == 0
    assert body["external_action_taken"] is False
    assert len(body["top_matches"]) == 10
    shown = {item["title"] for item in body["top_matches"]}
    assert titles[-1] in shown
    assert all(item["actually_sent"] is False for item in body["top_matches"])
    assert all(item["record_class"] == "manual" for item in body["top_matches"] if item["title"] in shown)

    other = client.get("/api/nova/work/first-client/board", headers=_headers(client, "admin@amicor.local"))
    assert other.status_code == 200, other.text
    other_titles = {item["title"] for item in other.json()["top_matches"]}
    assert titles[-1] not in other_titles

    denied = client.get(
        "/api/nova/work/first-client/board",
        headers=headers,
        params={"organization_id": "org-not-the-caller"},
    )
    assert denied.status_code == 403
    anonymous = client.get("/api/nova/work/first-client/board")
    assert anonymous.status_code == 401


def test_blocked_handoff_is_not_a_send(client: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
    def _blocked(*_args, **_kwargs):
        raise AssertionError("email submission must not run")

    monkeypatch.setattr("app.core.nova.work_revenue.submission.submit_via_confirmed_email", _blocked)
    headers = _headers(client)
    approved = _approve(client, headers, "Blocked handoff remote contractor")
    application_id = approved["application_id"]
    first = client.post(
        f"/api/nova/work/first-client/applications/{application_id}/submission-attempt",
        headers=headers,
    )
    assert first.status_code == 200, first.text
    payload = first.json()
    assert payload["applications_sent_by_this_request"] == 0
    assert payload["application_externally_submitted"] is False
    assert payload["ledger"]["state"] == "BLOCKED"
    assert payload["handoff"]["externally_submitted"] is False
    second = client.post(
        f"/api/nova/work/first-client/applications/{application_id}/submission-attempt",
        headers=headers,
    )
    assert second.status_code == 200, second.text
    assert second.json()["ledger"]["ledger_id"] == payload["ledger"]["ledger_id"]
    board = client.get("/api/nova/work/first-client/board", headers=headers)
    match = next(item for item in board.json()["top_matches"] if item["application_id"] == application_id)
    assert match["stage"] == "BLOCKED"
    assert match["actually_sent"] is False
    assert "submit the approved package" in match["next_action"]


def test_follow_up_and_delivery_failure_require_a_real_submission(client: TestClient) -> None:
    headers = _headers(client)
    approved = _approve(client, headers, "Follow-up gate remote contractor")
    application_id = approved["application_id"]
    future = (datetime.now(timezone.utc) + timedelta(days=3)).isoformat()
    early = client.post(
        f"/api/nova/work/first-client/applications/{application_id}/follow-up",
        headers=headers,
        json={"follow_up_at": future},
    )
    assert early.status_code == 409
    failure = client.post(
        f"/api/nova/work/first-client/applications/{application_id}/response",
        headers=headers,
        json={"outcome": "DELIVERY_FAILURE", "note": "mailbox rejected the message"},
    )
    assert failure.status_code == 409

    transport = _PermittedTransport()
    set_submission_transport(transport)
    try:
        _clear_owner_input(application_id)
        refused = client.post(
            f"/api/nova/work/first-client/applications/{application_id}/submission-attempt",
            headers=headers,
            json={"mock_receipt_consent": False},
        )
        assert refused.status_code == 200, refused.text
        assert refused.json()["ledger"]["state"] == "BLOCKED"
        assert "consent" in refused.json()["ledger"]["blocker_reason"].lower()
        assert refused.json()["application_externally_submitted"] is False
        assert transport.calls == 0
        mock = client.post(
            f"/api/nova/work/first-client/applications/{application_id}/submission-attempt",
            headers=headers,
            json={"mock_receipt_consent": True},
        )
        assert mock.status_code == 200, mock.text
        assert mock.json()["ledger"]["state"] == "MOCK_RECEIPT"
        assert mock.json()["ledger"]["mock_only"] is True
        assert mock.json()["ledger"]["is_send_receipt"] is False
        assert mock.json()["mock_only"] is True
        assert mock.json()["application_externally_submitted"] is False
        assert mock.json()["applications_sent_by_this_request"] == 0
        assert transport.calls == 1
        assert transport.network_used is False
        again = client.post(
            f"/api/nova/work/first-client/applications/{application_id}/submission-attempt",
            headers=headers,
            json={"mock_receipt_consent": True},
        )
        assert again.status_code == 200, again.text
        assert again.json()["applications_sent_by_this_request"] == 0
        assert again.json()["ledger"]["ledger_id"] == mock.json()["ledger"]["ledger_id"]
        assert transport.calls == 1
    finally:
        set_submission_transport(None)

    still_blocked = client.post(
        f"/api/nova/work/first-client/applications/{application_id}/follow-up",
        headers=headers,
        json={"follow_up_at": future},
    )
    assert still_blocked.status_code == 409
    board = client.get("/api/nova/work/first-client/board", headers=headers)
    match = next(item for item in board.json()["top_matches"] if item["application_id"] == application_id)
    assert match["stage"] == "MOCK_RECEIPT"
    assert match["actually_sent"] is False
    assert match["mock_only"] is True
    assert match["sent_vs_draft"] == "draft"
    assert match["receipt"] == "fake-receipt-1"
    assert board.json()["counts"]["actually_sent"] == 0
    assert board.json()["counts"]["mock_receipts"] >= 1


def test_missing_auth_blocks_without_calling_transport(client: TestClient) -> None:
    class _Counting:
        def __init__(self) -> None:
            self.calls = 0
            self.permitted_channel = None

        def deliver(self, message: dict) -> dict:
            self.calls += 1
            return {"state": "SENT", "receipt": "should-not-exist", "network_used": False}

    transport = _Counting()
    set_submission_transport(transport)
    try:
        headers = _headers(client)
        approved = _approve(client, headers, "Unauthenticated channel contractor")
        attempted = client.post(
            f"/api/nova/work/first-client/applications/{approved['application_id']}/submission-attempt",
            headers=headers,
        )
        assert attempted.status_code == 200, attempted.text
        body = attempted.json()
        assert body["ledger"]["state"] == "BLOCKED"
        assert body["applications_sent_by_this_request"] == 0
        assert body["application_externally_submitted"] is False
        assert "connect one authenticated permitted submission channel" in body["ledger"]["next_action"]
        assert transport.calls == 0
        other = client.post(
            f"/api/nova/work/first-client/applications/{approved['application_id']}/submission-attempt",
            headers=_headers(client, "admin@amicor.local"),
        )
        assert other.status_code == 404
    finally:
        set_submission_transport(None)


def test_delivery_failure_and_network_flag_are_not_sends(client: TestClient) -> None:
    headers = _headers(client)
    approved = _approve(client, headers, "Delivery failure contractor")
    application_id = approved["application_id"]
    _clear_owner_input(application_id)
    failing = _PermittedTransport(fail=True)
    set_submission_transport(failing)
    try:
        failed = client.post(
            f"/api/nova/work/first-client/applications/{application_id}/submission-attempt",
            headers=headers,
            json={"mock_receipt_consent": True},
        )
        assert failed.status_code == 200, failed.text
        assert failed.json()["ledger"]["state"] == "DELIVERY_FAILURE"
        assert failed.json()["application_externally_submitted"] is False
        assert failed.json()["applications_sent_by_this_request"] == 0
        assert failing.network_used is False
    finally:
        set_submission_transport(None)

    class _Network:
        permitted_channel = {"channel_id": "network-channel", "permitted": True}
        calls = 0

        def deliver(self, message: dict) -> dict:
            self.calls += 1
            return {"state": "SENT", "receipt": "remote-receipt", "network_used": True}

    networked = _Network()
    set_submission_transport(networked)
    try:
        refused = client.post(
            f"/api/nova/work/first-client/applications/{application_id}/submission-attempt",
            headers=headers,
            json={"mock_receipt_consent": True},
        )
        assert refused.status_code == 200, refused.text
        assert refused.json()["ledger"]["state"] == "BLOCKED"
        assert refused.json()["application_externally_submitted"] is False
        assert refused.json()["ledger"]["receipt"] in {None, ""}
    finally:
        set_submission_transport(None)


def test_fixture_records_draft_zero_proposals() -> None:
    fixtures = [
        {
            "record_class": "FIXTURE",
            "fixture": True,
            "title": "Fixture virtual assistant",
            "company_name": "Fixture Co",
            "description": "Remote contractor administrative support.",
            "source_url": "https://example.invalid/fixture",
            "fetched_at": "2026-10-14T00:00:00+00:00",
            "qualification_status": "QUALIFIED",
            "provenance_verified": True,
        }
    ]
    assert draft_targeted_proposals(fixtures) == []


def test_verified_shape_drafts_a_proposal_that_was_not_sent() -> None:
    """Shape check only. This dict was not fetched from a job source."""
    shape = {
        "record_class": "live",
        "provenance_verified": True,
        "title": "Remote CRM cleanup contractor",
        "company_name": "Shape Example",
        "description": "Remote contractor CRM cleanup. Preferred: 5 years. No certification is stated.",
        "source_url": "https://remotive.com/remote-jobs/shape-not-a-fetch",
        "fetched_at": "2026-10-14T18:00:00+00:00",
        "qualification_status": "QUALIFIED",
        "live_qualification": {"qualification_status": "QUALIFIED", "blockers": []},
    }
    drafted = draft_targeted_proposals([shape, shape, shape, shape])
    assert len(drafted) == 3
    for item in drafted:
        assert item["sent"] is False
        assert item["external_action_taken"] is False
        assert item["fixture"] is False
        assert "This draft was not sent." in item["proposal"]
        assert "7 calendar days" in item["paid_pilot_options"]
        assert "Out of scope" in item["cost_scope_check"]
        assert item["fetched_at"] == "2026-10-14T18:00:00+00:00"
        assert "I have 5 years" not in item["proposal"]
        assert "SOC 2" not in item["proposal"]
        assert "partnership with" not in item["proposal"].lower()


def test_later_provider_error_keeps_rows_and_reconciles_the_funnel(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("app.core.nova.v3.multi_source_discovery._RETRY_SLEEP_SECONDS", 0)
    monkeypatch.setattr(
        "app.core.nova.v3.multi_source_discovery.live_flags",
        lambda: {"LIVE_DISCOVERY_ENABLED": True},
    )
    reset_provider_health_for_tests()

    class _Partial( _FlakyProvider):
        def search(self, query: str, *, limit: int = 10) -> list[dict]:
            self.calls += 1
            if self.calls > 1:
                raise httpx.TimeoutException("later query timed out")
            kept = normalize_opportunity(
                provider_id="flaky_test",
                provider_type="remote_contract_feed",
                provider_identifier="va-1",
                title="Virtual Assistant Contractor",
                company_name="Example Client",
                description="Remote calendar, email, document and administrative support.",
                source_url="https://example.test/va-1",
                job_type="contractor",
                geography="United States remote",
                fee_required="no",
            )
            duplicate = dict(kept)
            duplicate["source_url"] = "https://example.test/va-1?utm_source=repeat"
            excluded = normalize_opportunity(
                provider_id="flaky_test",
                provider_type="remote_contract_feed",
                provider_identifier="sales-1",
                title="Regional Sales Manager",
                company_name="Example Client",
                description="Contract role supporting business operations and scheduling.",
                source_url="https://example.test/sales-1",
                job_type="contractor",
                geography="United States remote",
                fee_required="no",
            )
            return [kept, duplicate, excluded]

    provider = _Partial(failures=0)
    result = search_multi_source_jobs(
        "remote administrative assistant contractor",
        providers_override=[provider],
    )
    funnel = result["funnel"]
    assert provider.calls >= 2
    assert result["live_search_status"] == "partial"
    assert result["live_search_claimed"] is True
    assert result["provider_errors"]
    assert result["provider_result_counts"]["flaky_test"] >= 1
    assert any(job["title"] == "Virtual Assistant Contractor" for job in result["jobs"])
    assert funnel["reconciled"] is True
    assert funnel["unique_screened"] == funnel["unique_kept"] + funnel["unique_excluded"]
    assert funnel["screened_rows"] >= funnel["unique_screened"]
    assert funnel["unique_kept"] >= 1
    assert funnel["unique_excluded"] >= 1
    assert funnel["screened_rows"] > funnel["unique_screened"]
    assert result["external_action_taken"] is False
    assert result["financial_execution"] is False


def test_join_our_team_does_not_reclassify_an_explicit_contractor() -> None:
    from app.core.nova.v3.live_qualification import qualify_live_job

    contractor = qualify_live_job(
        {
            "title": "Remote CRM contractor",
            "company_name": "Example",
            "description": (
                "Independent contractor. Join our team of freelancers. "
                "No upfront fee. Paid project for CRM notes."
            ),
            "source_url": "https://example.com/crm",
            "job_type": "contractor",
            "remote_status": "remote",
        }
    )
    assert contractor["work_type"] != "employee"
    assert "employee_w2_staff_role" not in contractor["blockers"]
    employee = qualify_live_job(
        {
            "title": "Remote CRM contractor",
            "company_name": "Example",
            "description": "Independent contractor. Join our team. This is a W-2 employee only role.",
            "source_url": "https://example.com/w2",
            "job_type": "contractor",
            "remote_status": "remote",
        }
    )
    assert "employee_w2_staff_role" in employee["blockers"]


def test_rejected_and_incomplete_records_stay_out_of_top_matches(client: TestClient) -> None:
    headers = _headers(client)
    rejected = _opportunity(
        client,
        headers,
        "On site surgeon employee",
        description="Must be an on-site surgeon and a W-2 employee. Commercial truck driving required.",
        physical_presence_required="true",
        engagement_type="employee",
    )
    client.post(
        f"/api/nova/work/opportunities/{rejected['opportunity_id']}/qualify",
        headers=headers,
    )
    incomplete = _opportunity(
        client,
        headers,
        "Missing provenance contractor",
        source_url=None,
    )
    client.post(
        f"/api/nova/work/opportunities/{incomplete['opportunity_id']}/qualify",
        headers=headers,
    )
    board = client.get("/api/nova/work/first-client/board", headers=headers)
    assert board.status_code == 200, board.text
    body = board.json()
    titles = {item["title"] for item in body["top_matches"]}
    assert "On site surgeon employee" not in titles
    assert "Missing provenance contractor" not in titles
    assert body["counts"]["rejected"] >= 1
    assert any(item["title"] == "Missing provenance contractor" for item in body["incomplete_provenance"])
    assert all(item["provenance_complete"] for item in body["top_matches"])


def test_sandbox_receipt_idempotency_retry_and_failure(client: TestClient) -> None:
    headers = _headers(client)
    approved = _approve(client, headers, "Sandbox receipt contractor")
    application_id = approved["application_id"]
    _clear_owner_input(application_id)

    class _Sandbox:
        def __init__(self) -> None:
            self.calls = 0
            self.mode = "no-receipt"
            self.permitted_channel = {
                "channel_id": "sandbox-direct",
                "permitted": True,
                "recipient": "applications@example.invalid",
            }

        def deliver(self, message: dict) -> dict:
            self.calls += 1
            assert message["sandbox"] is True
            assert message["billable"] is False
            if self.mode == "no-receipt":
                return {"state": "SENT", "receipt": "   ", "network_used": False}
            if self.mode == "network":
                return {"state": "SENT", "receipt": "remote-receipt", "network_used": True}
            if self.mode == "failure":
                return {
                    "state": "DELIVERY_FAILURE",
                    "receipt": None,
                    "reason": "sandbox mailbox rejected the message",
                    "network_used": False,
                }
            return {
                "state": "SENT",
                "receipt": "sandbox-receipt-1",
                "network_used": False,
            }

    transport = _Sandbox()
    set_submission_transport(transport)
    try:
        missing = client.post(
            f"/api/nova/work/first-client/applications/{application_id}/submission-attempt",
            headers=headers,
            json={"mock_receipt_consent": True},
        )
        assert missing.status_code == 200, missing.text
        assert missing.json()["ledger"]["state"] == "BLOCKED"
        assert missing.json()["application_externally_submitted"] is False
        assert missing.json()["ledger"]["is_send_receipt"] is False
        assert transport.calls == 1

        transport.mode = "network"
        networked = client.post(
            f"/api/nova/work/first-client/applications/{application_id}/submission-attempt",
            headers=headers,
            json={"mock_receipt_consent": True},
        )
        assert networked.status_code == 200, networked.text
        assert networked.json()["ledger"]["state"] == "BLOCKED"
        assert networked.json()["ledger"]["receipt"] in {None, ""}
        assert networked.json()["application_externally_submitted"] is False
        assert transport.calls == 2

        transport.mode = "failure"
        failed = client.post(
            f"/api/nova/work/first-client/applications/{application_id}/submission-attempt",
            headers=headers,
            json={"mock_receipt_consent": True},
        )
        assert failed.status_code == 200, failed.text
        assert failed.json()["ledger"]["state"] == "DELIVERY_FAILURE"
        assert failed.json()["application_externally_submitted"] is False
        assert failed.json()["applications_sent_by_this_request"] == 0
        assert transport.calls == 3

        transport.mode = "sent"
        sent = client.post(
            f"/api/nova/work/first-client/applications/{application_id}/submission-attempt",
            headers=headers,
            json={"mock_receipt_consent": True},
        )
        assert sent.status_code == 200, sent.text
        assert sent.json()["ledger"]["state"] == "MOCK_RECEIPT"
        assert sent.json()["ledger"]["receipt"] == "sandbox-receipt-1"
        assert sent.json()["ledger"]["is_send_receipt"] is False
        assert sent.json()["ledger"]["mock_only"] is True
        assert sent.json()["applications_sent_by_this_request"] == 0
        assert sent.json()["application_externally_submitted"] is False
        assert sent.json()["financial_execution"] is False
        assert transport.calls == 4

        transport.mode = "failure"
        repeat = client.post(
            f"/api/nova/work/first-client/applications/{application_id}/submission-attempt",
            headers=headers,
            json={"mock_receipt_consent": True},
        )
        assert repeat.status_code == 200, repeat.text
        assert repeat.json()["applications_sent_by_this_request"] == 0
        assert repeat.json()["ledger"]["state"] == "MOCK_RECEIPT"
        assert repeat.json()["ledger"]["receipt"] == "sandbox-receipt-1"
        assert repeat.json()["application_externally_submitted"] is False
        assert transport.calls == 4
    finally:
        set_submission_transport(None)


def test_source_eligibility_reasons_do_not_invent_text() -> None:
    assert source_eligibility_reasons({}) == []
    assert source_eligibility_reasons({"eligibility_explanations": ["  ", "Fee status is unclear."]}) == [
        "Fee status is unclear."
    ]


def test_source_eligibility_persists_on_the_board_and_across_refresh(client: TestClient) -> None:
    headers = _headers(client)
    created = _opportunity(client, headers, "Source eligibility persistence contractor")
    opportunity_id = created["opportunity_id"]
    explanation = "Preferred residency: United States. A preference is not a blocker."
    with SessionLocal() as db:
        row = db.query(NovaWorkOpportunity).filter(NovaWorkOpportunity.opportunity_id == opportunity_id).one()
        row.qualification_json = json.dumps(
            {
                "reasons": ["Saved work qualifier reason."],
                "source_eligibility_reasons": [explanation],
                "eligibility_decision": "clear",
                "source_provider_id": "remotive",
                "capability_fit_score": 10000,
                "fetched_at": "2026-10-18T12:00:00+00:00",
            }
        )
        row.qualification_outcome = "NOVA_CAN_PERFORM"
        row.updated_at = datetime(2099, 1, 1, tzinfo=timezone.utc)
        organization_id = row.organization_id
        owner_user_id = row.owner_user_id
        db.commit()

    def _card(payload: dict) -> dict:
        rows = payload["top_matches"] + payload["incomplete_provenance"]
        return next(item for item in rows if item["opportunity_id"] == opportunity_id)

    first = client.get("/api/nova/work/first-client/board", headers=headers)
    assert first.status_code == 200, first.text
    card = _card(first.json())
    assert card["source_eligibility_reasons"] == [explanation]
    assert card["eligibility_decision"] == "clear"
    assert card["source_provider_id"] == "remotive"
    refreshed = client.get("/api/nova/work/first-client/board", headers=headers)
    assert _card(refreshed.json())["source_eligibility_reasons"] == [explanation]

    qualified = client.post(
        f"/api/nova/work/opportunities/{opportunity_id}/qualify",
        headers=headers,
    )
    assert qualified.status_code == 200, qualified.text
    with SessionLocal() as db:
        row = db.query(NovaWorkOpportunity).filter(NovaWorkOpportunity.opportunity_id == opportunity_id).one()
        stored = json.loads(row.qualification_json or "{}")
        user = UserContext(
            user_id=owner_user_id,
            email="dispatcher@amicor.local",
            role="dispatcher",
            organization_id=organization_id,
        )
    assert stored["source_eligibility_reasons"] == [explanation]
    assert stored["source_provider_id"] == "remotive"

    job = {
        "title": "Remote CRM source eligibility contractor",
        "company_name": "Harbor Ledger",
        "source_url": "https://example.com/roles/source-eligibility-live",
        "description": "Remote independent contractor CRM notes. No upfront fee.",
        "provider_id": "jobicy",
        "fetched_at": "2026-10-18T15:00:00+00:00",
        "eligibility_explanations": [explanation],
        "eligibility_decision": "clear",
        "remote_status": "remote",
        "job_type": "contractor",
    }
    with SessionLocal() as db:
        persisted = persist_live_job(db, job, organization_id=organization_id, user=user)
        saved = (
            db.query(NovaWorkOpportunity)
            .filter(NovaWorkOpportunity.opportunity_id == persisted["work_opportunity_id"])
            .one()
        )
        copied = json.loads(saved.qualification_json or "{}")
        assert copied["source_eligibility_reasons"] == [explanation]
        copied["capability_fit_score"] = 10000
        saved.qualification_json = json.dumps(copied)
        saved.qualification_outcome = "NOVA_CAN_PERFORM"
        saved.updated_at = datetime(2099, 1, 2, tzinfo=timezone.utc)
        db.commit()
    assert persisted["persisted"] is True
    assert copied["source_provider_id"] == "jobicy"
    assert copied["eligibility_decision"] == "clear"
    live_board = client.get("/api/nova/work/first-client/board", headers=headers)
    live_card = next(
        item
        for item in live_board.json()["top_matches"] + live_board.json()["incomplete_provenance"]
        if item["opportunity_id"] == persisted["work_opportunity_id"]
    )
    assert live_card["source_eligibility_reasons"] == [explanation]


def test_follow_up_still_requires_a_stored_send_receipt(client: TestClient) -> None:
    """The mock workflow does not create this row. It is a fixture receipt."""
    headers = _headers(client)
    approved = _approve(client, headers, "Fixture send receipt contractor")
    application_id = approved["application_id"]
    with SessionLocal() as db:
        application = db.query(NovaWorkApplication).filter(NovaWorkApplication.application_id == application_id).one()
        application.externally_submitted = True
        db.add(
            NovaWorkSubmissionLedger(
                ledger_id=f"NWL-{uuid.uuid4().hex[:12]}",
                organization_id=application.organization_id,
                owner_user_id=application.owner_user_id,
                application_id=application.application_id,
                opportunity_id=application.opportunity_id,
                channel="fixture",
                state="SENT",
                receipt="fixture-receipt-not-a-network-send",
                idempotency_key=f"send:{application.application_id}",
                next_action="Fixture receipt. Nothing was sent by this test.",
            )
        )
        db.commit()
    future = (datetime.now(timezone.utc) + timedelta(days=3)).isoformat()
    scheduled = client.post(
        f"/api/nova/work/first-client/applications/{application_id}/follow-up",
        headers=headers,
        json={"follow_up_at": future},
    )
    assert scheduled.status_code == 200, scheduled.text
    assert scheduled.json()["message_sent"] is False
    assert scheduled.json()["externally_submitted"] is True
