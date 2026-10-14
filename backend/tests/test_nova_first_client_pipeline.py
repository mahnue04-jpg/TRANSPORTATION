"""First-client board, honest search status, and draft bid materials.

No live job source and no email provider are contacted.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

import httpx
import pytest
from fastapi.testclient import TestClient

from app.auth import SEED_PASSWORD, ensure_auth_schema, seed_default_users
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
from app.core.nova.work_revenue.models import NovaWorkApplication, NovaWorkMaterial
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
    assert "Record blocked handoff" in script.text
    assert "Sent vs draft" in script.text
    assert "Fetched at" in script.text
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
    assert "$" not in by_kind["paid_pilot_options"]
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
        sent = client.post(
            f"/api/nova/work/first-client/applications/{application_id}/submission-attempt",
            headers=headers,
        )
        assert sent.status_code == 200, sent.text
        assert sent.json()["ledger"]["state"] == "SENT"
        assert sent.json()["ledger"]["receipt"]
        assert sent.json()["application_externally_submitted"] is True
        assert sent.json()["applications_sent_by_this_request"] == 1
        assert transport.calls == 1
        assert transport.network_used is False
        again = client.post(
            f"/api/nova/work/first-client/applications/{application_id}/submission-attempt",
            headers=headers,
        )
        assert again.status_code == 200, again.text
        assert again.json()["applications_sent_by_this_request"] == 0
        assert again.json()["ledger"]["ledger_id"] == sent.json()["ledger"]["ledger_id"]
        assert transport.calls == 1
    finally:
        set_submission_transport(None)

    past = client.post(
        f"/api/nova/work/first-client/applications/{application_id}/follow-up",
        headers=headers,
        json={"follow_up_at": (datetime.now(timezone.utc) - timedelta(days=1)).isoformat()},
    )
    assert past.status_code == 422
    scheduled = client.post(
        f"/api/nova/work/first-client/applications/{application_id}/follow-up",
        headers=headers,
        json={"follow_up_at": future},
    )
    assert scheduled.status_code == 200, scheduled.text
    assert scheduled.json()["message_sent"] is False
    assert scheduled.json()["externally_submitted"] is True
    recorded = client.post(
        f"/api/nova/work/first-client/applications/{application_id}/response",
        headers=headers,
        json={"outcome": "DELIVERY_FAILURE", "note": "mailbox rejected the message"},
    )
    assert recorded.status_code == 200, recorded.text
    assert recorded.json()["applications_sent_by_this_request"] == 0
    assert recorded.json()["actually_sent"] is True
    assert recorded.json()["ledger"]["state"] == "DELIVERY_FAILURE"
    board = client.get("/api/nova/work/first-client/board", headers=headers)
    match = next(
        item
        for item in board.json()["top_matches"] + board.json()["sent_outside_top_matches"]
        if item["application_id"] == application_id
    )
    assert match["stage"] == "DELIVERY_FAILURE"
    assert match["actually_sent"] is True
    assert match["receipt_verified"] is True
    assert match["sent_vs_draft"] == "sent"
    assert match["receipt"] == "fake-receipt-1"


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
        assert "I have 5 years" not in item["proposal"]
        assert "SOC 2" not in item["proposal"]
        assert "partnership with" not in item["proposal"].lower()
