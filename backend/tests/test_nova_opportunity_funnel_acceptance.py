"""Dev-only synthetic acceptance for the Work and Revenue opportunity funnel.

Discovery, qualification, saved lead, application draft, and owner review run
against fictional postings on the isolated sqlite file named by CI. Nothing in
this module contacts a lead, buys credits, or sends an application.
"""
from __future__ import annotations

import logging
from pathlib import Path
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.exc import IntegrityError

from app.auth import SEED_PASSWORD, UserContext, ensure_auth_schema, seed_default_users
from app.core.nova.v3.live_qualification import qualify_and_rank_live_jobs
from app.core.nova.v3.work_revenue_bridge import persist_live_job
from app.core.nova.work_revenue import service as work_service
from app.core.nova.work_revenue.funnel_status import (
    LABEL_APPROVED,
    LABEL_CLOSED,
    LABEL_DISCOVERED,
    LABEL_DRAFT,
    LABEL_NOT_QUALIFIED,
    LABEL_OWNER_REVIEW,
    LABEL_NEEDS_REVIEW_UNSAVED,
    LABEL_QUALIFIED_UNSAVED,
    LABEL_SAVED_PENDING,
    LABEL_SAVED_QUALIFIED,
    LABEL_SENT,
    LABEL_UNCONFIRMED,
    FUNNEL_STAGE_LABELS,
    funnel_stage_status,
)
from app.core.nova.work_revenue.schema_ensure import ensure_work_revenue_schema
from app.db.session import SessionLocal, engine
from app.main import app

ACCEPTANCE_DB = "test_nova_opportunity_funnel_acceptance.db"
QUERY = "Remote 1099 data entry contractor"
ROOT = Path(__file__).resolve().parents[1]
_CATALOG: dict[str, dict] | None = None


@pytest.fixture(scope="module")
def client() -> TestClient:
    ensure_auth_schema()
    seed_default_users()
    ensure_work_revenue_schema(engine)
    return TestClient(app)


@pytest.fixture
def db_session():
    ensure_work_revenue_schema(engine)
    session = SessionLocal()
    try:
        yield session
    finally:
        session.rollback()
        session.close()


def _headers(client: TestClient) -> dict[str, str]:
    response = client.post(
        "/api/auth/login",
        json={"email": "dispatcher@amicor.local", "password": SEED_PASSWORD},
    )
    assert response.status_code == 200, response.text
    return {"Authorization": f"Bearer {response.json()['access_token']}"}


def _user(client: TestClient) -> UserContext:
    headers = _headers(client)
    me = client.get("/api/auth/me", headers=headers)
    assert me.status_code == 200, me.text
    body = me.json()
    return UserContext(
        user_id=body["user_id"],
        email=body.get("email") or "dispatcher@amicor.local",
        role=body.get("role") or "dispatcher",
        organization_id=body.get("organization_id"),
    )


def _token() -> str:
    return uuid4().hex[:10]


def _job(title: str, description: str, **extra: object) -> dict:
    identifier = str(extra.pop("provider_identifier", title.lower().replace(" ", "-")))
    company = str(extra.pop("company_name", "Fictional Northwind Records"))
    source_url = str(extra.pop("source_url", f"https://example.invalid/jobs/{identifier}"))
    job = {
        "provider_id": "synthetic_acceptance",
        "provider_identifier": identifier,
        "title": title,
        "company_name": company,
        "description": description,
        "source_url": source_url,
        "geography": extra.pop("geography", "Worldwide"),
        "remote_status": extra.pop("remote_status", "remote"),
        "job_type": "contract",
        "compensation_text": "$40/hr",
        "search_family": "administrative_operations",
    }
    job.update(extra)
    assert str(job["company_name"]).startswith("Fictional ")
    assert "example.invalid" in str(job["source_url"])
    assert "@" not in str(job["description"])
    return job


def _clear_description() -> str:
    return (
        "Remote 1099 data entry for spreadsheet cleanup, CRM notes, email drafts, "
        "and administrative reporting. Independent contractor. No certification required. "
        "No upfront fee. No residency requirement. Fully remote. Work from anywhere."
    )


def _catalog() -> dict[str, dict]:
    global _CATALOG
    if _CATALOG is not None:
        return _CATALOG
    jobs = [
        _job(
            "Data Entry Clerk",
            _clear_description(),
            provider_identifier="clear-data-entry",
        ),
        _job(
            "Data Entry Clerk",
            "Remote 1099 data entry. Application fee required. Pay to apply before tasks are visible.",
            provider_identifier="fee-data-entry",
            company_name="Fictional Tollbooth Data",
        ),
        _job(
            "Data Entry Clerk",
            "Remote data entry. Must reside in the United Arab Emirates. No upfront fee.",
            provider_identifier="residency-uae",
            company_name="Fictional Harbor Residency",
            geography="United Arab Emirates",
        ),
        _job(
            "Data Entry Clerk",
            "Office data entry for local staff. Remote work is not offered. No upfront fee.",
            provider_identifier="remote-negated",
            company_name="Fictional Inland Office",
            geography="India",
            remote_status="not_remote",
        ),
        _job(
            "Data Entry Clerk",
            "This role is not remote. Office data entry. No upfront fee.",
            provider_identifier="remote-denied",
            company_name="Fictional Closed Campus",
            geography="Dubai",
            remote_status="remote",
        ),
    ]
    ranked = qualify_and_rank_live_jobs(QUERY, jobs)
    _CATALOG = {str(row.get("provider_identifier")): row for row in ranked}
    return _CATALOG


def _isolated_copy(row: dict) -> dict:
    token = _token()
    copied = dict(row)
    copied["company_name"] = f"Fictional Northwind Records {token}"
    copied["source_url"] = f"https://example.invalid/jobs/fictional-{token}"
    copied["provider_identifier"] = f"synthetic-{token}"
    assert copied["company_name"].startswith("Fictional ")
    assert "example.invalid" in copied["source_url"]
    return copied


def _audit_types(client: TestClient, headers: dict[str, str], ref_id: str) -> set[str]:
    audit = client.get("/api/nova/work/audit", headers=headers, params={"limit": 200})
    assert audit.status_code == 200, audit.text
    return {
        str(row.get("event_type"))
        for row in audit.json()
        if row.get("ref_id") == ref_id
    }


def _forbid_external_send(monkeypatch: pytest.MonkeyPatch) -> dict[str, int]:
    calls = {"count": 0}

    def explode(*_args, **_kwargs):
        calls["count"] += 1
        raise AssertionError("synthetic acceptance invoked an external send")

    monkeypatch.setattr("app.core.nova.communications.service.send_confirmed", explode)
    return calls


def _assert_isolated_database() -> None:
    """The acceptance run must stay on a disposable sqlite file.

    The pytest harness replaces DATABASE_URL with backend/data/chat_test_<pid>.db
    whenever TESTING is true. CI also offers test_nova_opportunity_funnel_acceptance.db
    for a direct invocation that does not load that harness.
    """
    url = str(engine.url)
    path = url.split("sqlite:///", 1)[-1]
    name = Path(path).name
    assert url.startswith("sqlite")
    assert "postgres" not in url.lower()
    assert name != "chat.db"
    assert name == ACCEPTANCE_DB or name.startswith("chat_test_")
    assert name.endswith(".db")
    assert "example.invalid" not in url


def test_acceptance_database_is_isolated_sqlite() -> None:
    _assert_isolated_database()


def test_discovery_ranks_fictional_postings_without_saving() -> None:
    catalog = _catalog()
    assert set(catalog) == {
        "clear-data-entry",
        "fee-data-entry",
        "residency-uae",
        "remote-negated",
        "remote-denied",
    }
    for row in catalog.values():
        assert str(row["company_name"]).startswith("Fictional ")
        assert "example.invalid" in str(row["source_url"])
        assert row.get("work_opportunity_id") in {None, ""}
        qual = row["live_qualification"]
        assert qual["external_submission"] is False
        assert qual["financial_execution"] is False
        assert qual["native_fluency_claimed"] is False
        stage = funnel_stage_status(row)
        assert stage["external_send"] is False
        print(
            f"FUNNEL_ACCEPTANCE case=discovery provider={row['provider_identifier']} "
            f"stage={stage['funnel_stage']} external_send=false"
        )


def test_qualification_closes_remote_negation() -> None:
    catalog = _catalog()
    for key in ("remote-negated", "remote-denied"):
        row = catalog[key]
        qual = row["live_qualification"]
        assert qual["qualification_status"] == "NOT_QUALIFIED"
        assert row["discovery_band"] == "REJECT"
        assert "non_us_location_required" in qual["blockers"] or "residency_required" in qual["blockers"]
        stage = funnel_stage_status(row)
        assert stage["funnel_stage"] == "not_qualified"
        assert stage["funnel_stage_label"] == LABEL_NOT_QUALIFIED
        assert stage["external_send"] is False


def test_qualification_closes_foreign_residency() -> None:
    row = _catalog()["residency-uae"]
    qual = row["live_qualification"]
    assert qual["qualification_status"] == "NOT_QUALIFIED"
    assert qual["eligibility_decision"] == "fail_closed"
    assert "residency_required" in qual["blockers"]
    assert any("United Arab Emirates" in line and "fails closed" in line for line in qual["eligibility_explanations"])
    stage = funnel_stage_status(row)
    assert stage["funnel_stage_label"] == LABEL_NOT_QUALIFIED
    assert stage["external_send"] is False


def test_qualification_closes_upfront_fee_and_keeps_no_fee_data_entry() -> None:
    catalog = _catalog()
    paid = catalog["fee-data-entry"]
    assert paid["discovery_band"] == "REJECT"
    assert paid["live_qualification"]["qualification_status"] == "NOT_QUALIFIED"
    assert "upfront_fee_required" in paid["live_qualification"]["blockers"]
    assert funnel_stage_status(paid)["external_send"] is False

    clear = catalog["clear-data-entry"]
    qual = clear["live_qualification"]
    assert qual["qualification_status"] != "NOT_QUALIFIED"
    assert "work_lane_mismatch" not in qual.get("blockers", [])
    assert "upfront_fee_required" not in qual.get("blockers", [])
    assert qual.get("upfront_fee_blocked") is not True
    assert qual["fee_required"] == "no"
    assert "data entry" in str(clear["title"]).lower() or "data entry" in str(clear["description"]).lower()
    stage = funnel_stage_status(clear)
    assert stage["funnel_stage"] == "qualification"
    assert stage["funnel_stage_label"] == LABEL_NEEDS_REVIEW_UNSAVED
    assert qual["qualification_status"] == "NEEDS_OWNER_REVIEW"
    assert stage["external_send"] is False


def test_saved_lead_is_isolated_and_duplicate_save_reuses_it(client: TestClient, db_session) -> None:
    user = _user(client)
    job = _isolated_copy(_catalog()["clear-data-entry"])
    first = persist_live_job(
        db_session,
        job,
        organization_id=user.organization_id,
        user=user,
        prepare_application=False,
    )
    assert first["persisted"] is True
    assert first["created"] is True
    assert first["externally_submitted"] is False
    assert first["client_contacted"] is False
    assert first["financial_execution"] is False
    _assert_isolated_database()
    second = persist_live_job(
        db_session,
        job,
        organization_id=user.organization_id,
        user=user,
        prepare_application=False,
    )
    assert second["persisted"] is True
    assert second["created"] is False
    assert second["work_opportunity_id"] == first["work_opportunity_id"]
    assert second["externally_submitted"] is False
    headers = _headers(client)
    saved = client.get(f"/api/nova/work/opportunities/{first['work_opportunity_id']}", headers=headers)
    assert saved.status_code == 200, saved.text
    body = saved.json()
    assert body["company_name"].startswith("Fictional ")
    assert "example.invalid" in str(body["source_url"])
    assert body["funnel_stage"] == "saved_lead"
    assert body["external_send"] is False
    assert body["funnel_stage_label"] in {LABEL_SAVED_QUALIFIED, LABEL_SAVED_PENDING}


def test_retry_after_insert_conflict_reuses_the_lead(client: TestClient, db_session, monkeypatch: pytest.MonkeyPatch) -> None:
    user = _user(client)
    job = _isolated_copy(_catalog()["clear-data-entry"])
    first = persist_live_job(
        db_session,
        job,
        organization_id=user.organization_id,
        user=user,
        prepare_application=False,
    )
    assert first["created"] is True
    real_lookup = work_service.get_opportunity_by_fingerprint
    state = {"lookups": 0, "inserts": 0}

    def miss_once(*args, **kwargs):
        state["lookups"] += 1
        if state["lookups"] == 1:
            return None
        return real_lookup(*args, **kwargs)

    def conflict(*_args, **_kwargs):
        state["inserts"] += 1
        raise IntegrityError("INSERT", {}, Exception("synthetic acceptance conflict"))

    monkeypatch.setattr(work_service, "get_opportunity_by_fingerprint", miss_once)
    monkeypatch.setattr(work_service, "create_discovered_opportunity", conflict)
    recovered = persist_live_job(
        db_session,
        job,
        organization_id=user.organization_id,
        user=user,
        prepare_application=False,
    )
    assert state["inserts"] == 1
    assert state["lookups"] >= 2
    assert recovered["persisted"] is True
    assert recovered["created"] is False
    assert recovered["work_opportunity_id"] == first["work_opportunity_id"]
    assert recovered["externally_submitted"] is False
    assert recovered["client_contacted"] is False


def test_failures_stay_closed_and_do_not_open_a_draft(client: TestClient, db_session) -> None:
    user = _user(client)
    headers = _headers(client)
    missing = persist_live_job(
        db_session,
        {"title": "", "company_name": "", "description": "Fictional blank posting"},
        organization_id=user.organization_id,
        user=user,
        prepare_application=True,
    )
    assert missing["persisted"] is False
    assert missing["work_opportunity_id"] is None
    assert missing["work_application_id"] is None
    assert missing["externally_submitted"] is False

    blocked = persist_live_job(
        db_session,
        _isolated_copy(_catalog()["residency-uae"]),
        organization_id=user.organization_id,
        user=user,
        prepare_application=True,
    )
    assert blocked["persisted"] is True
    assert blocked["work_application_id"] is None
    assert blocked["ready_for_owner_review"] is False
    assert blocked["externally_submitted"] is False
    saved = client.get(f"/api/nova/work/opportunities/{blocked['work_opportunity_id']}", headers=headers)
    assert saved.status_code == 200, saved.text
    assert saved.json()["status"] == "NOT_QUALIFIED"
    assert saved.json()["funnel_stage"] == "not_qualified"
    assert saved.json()["funnel_stage_label"] == LABEL_NOT_QUALIFIED
    assert saved.json()["external_send"] is False
    refused = client.post(
        "/api/nova/work/applications",
        headers=headers,
        json={"opportunity_id": blocked["work_opportunity_id"], "applicant_party": "AMICOR"},
    )
    assert refused.status_code == 400
    events = _audit_types(client, headers, blocked["work_opportunity_id"])
    assert "OPPORTUNITY_CREATED" in events
    assert "OPPORTUNITY_QUALIFIED" in events
    assert "APPLICATION_DRAFT_CREATED" not in events


def _draft_clear_lead(client: TestClient, db_session) -> tuple[dict[str, str], str, str]:
    user = _user(client)
    headers = _headers(client)
    saved = persist_live_job(
        db_session,
        _isolated_copy(_catalog()["clear-data-entry"]),
        organization_id=user.organization_id,
        user=user,
        prepare_application=False,
    )
    assert saved["persisted"] is True
    assert saved["work_status"] in {"QUALIFIED", "OWNER_REVIEW"}
    assert saved["work_application_id"] is None
    created = client.post(
        "/api/nova/work/applications",
        headers=headers,
        json={"opportunity_id": saved["work_opportunity_id"], "applicant_party": "AMICOR"},
    )
    assert created.status_code == 200, created.text
    return headers, saved["work_opportunity_id"], created.json()["application_id"]


def test_proposal_draft_stays_internal(client: TestClient, db_session) -> None:
    headers, _opportunity_id, application_id = _draft_clear_lead(client, db_session)
    drafted = client.get(f"/api/nova/work/applications/{application_id}", headers=headers)
    assert drafted.status_code == 200, drafted.text
    body = drafted.json()
    kinds = {item["kind"] for item in body["materials"]}
    assert "proposal" in kinds
    assert "cover_letter" in kinds
    assert body["approval_state"] == "DRAFT"
    assert body["approved_for_future_submission"] is False
    assert body["externally_submitted"] is False
    assert body["external_send"] is False
    assert body["funnel_stage"] == "application_draft"
    assert body["funnel_stage_label"] == LABEL_DRAFT
    events = _audit_types(client, headers, application_id)
    assert "APPLICATION_DRAFT_CREATED" in events


def test_owner_review_queue_requires_an_explicit_gate(client: TestClient, db_session, monkeypatch: pytest.MonkeyPatch) -> None:
    calls = _forbid_external_send(monkeypatch)
    headers, opportunity_id, application_id = _draft_clear_lead(client, db_session)
    early = client.post(f"/api/nova/work/applications/{application_id}/submit", headers=headers)
    assert early.status_code == 409
    assert calls["count"] == 0
    ready = client.post(f"/api/nova/work/applications/{application_id}/ready-for-review", headers=headers)
    assert ready.status_code == 200, ready.text
    queued = ready.json()
    assert queued["approval_state"] == "READY_FOR_OWNER_REVIEW"
    assert queued["approved_for_future_submission"] is False
    assert queued["externally_submitted"] is False
    assert queued["funnel_stage"] == "owner_review"
    assert queued["funnel_stage_label"] == LABEL_OWNER_REVIEW
    assert queued["external_send"] is False
    dashboard = client.get("/api/nova/work/dashboard", headers=headers)
    assert dashboard.status_code == 200, dashboard.text
    waiting = [
        row for row in dashboard.json()["owner_approvals"]
        if row["application_id"] == application_id
    ]
    assert len(waiting) == 1
    assert waiting[0]["funnel_stage_label"] == LABEL_OWNER_REVIEW
    assert waiting[0]["external_send"] is False
    still_blocked = client.post(f"/api/nova/work/applications/{application_id}/submit", headers=headers)
    assert still_blocked.status_code == 409
    assert calls["count"] == 0
    events = _audit_types(client, headers, application_id)
    assert "APPLICATION_READY_FOR_REVIEW" in events
    saved = client.get(f"/api/nova/work/opportunities/{opportunity_id}", headers=headers)
    assert saved.status_code == 200, saved.text
    assert saved.json()["external_send"] is False


def test_external_send_stays_off_without_and_after_approval(
    client: TestClient,
    db_session,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls = _forbid_external_send(monkeypatch)
    headers, _opportunity_id, application_id = _draft_clear_lead(client, db_session)
    unconfirmed = client.post(
        f"/api/nova/work/applications/{application_id}/submit-email",
        headers=headers,
        json={"confirm_send": False, "confirm_listing_accepts_email": False},
    )
    assert unconfirmed.status_code in {400, 422}
    assert calls["count"] == 0
    ready = client.post(f"/api/nova/work/applications/{application_id}/ready-for-review", headers=headers)
    assert ready.status_code == 200, ready.text
    unapproved_email = client.post(
        f"/api/nova/work/applications/{application_id}/submit-email",
        headers=headers,
        json={
            "to_email": "applications@example.invalid",
            "confirm_send": True,
            "confirm_listing_accepts_email": True,
        },
    )
    assert unapproved_email.status_code == 409
    assert calls["count"] == 0
    decision = client.post(
        f"/api/nova/work/applications/{application_id}/decision",
        headers=headers,
        json={"decision": "APPROVED", "notes": "Synthetic owner approval for a fictional posting. Do not send."},
    )
    assert decision.status_code == 200, decision.text
    approved = decision.json()
    assert approved["approved_for_future_submission"] is True
    assert approved["externally_submitted"] is False
    assert approved["funnel_stage"] == "approved_not_sent"
    assert approved["funnel_stage_label"] == LABEL_APPROVED
    assert approved["external_send"] is False
    handoff = client.post(f"/api/nova/work/applications/{application_id}/submit", headers=headers)
    assert handoff.status_code == 200, handoff.text
    body = handoff.json()
    assert body["external_action_taken"] is False
    assert body["externally_submitted"] is False
    assert body["approval_consumed"] is False
    assert body["financial_execution"] is False
    assert calls["count"] == 0
    reread = client.get(f"/api/nova/work/applications/{application_id}", headers=headers)
    assert reread.status_code == 200, reread.text
    assert reread.json()["externally_submitted"] is False
    assert reread.json()["external_send"] is False
    assert reread.json()["funnel_stage_label"] == LABEL_APPROVED


def test_audit_trail_records_the_stage_events(client: TestClient, db_session) -> None:
    headers, opportunity_id, application_id = _draft_clear_lead(client, db_session)
    ready = client.post(f"/api/nova/work/applications/{application_id}/ready-for-review", headers=headers)
    assert ready.status_code == 200, ready.text
    decision = client.post(
        f"/api/nova/work/applications/{application_id}/decision",
        headers=headers,
        json={"decision": "APPROVED", "notes": "Synthetic audit approval. Nothing sent."},
    )
    assert decision.status_code == 200, decision.text
    opportunity_events = _audit_types(client, headers, opportunity_id)
    application_events = _audit_types(client, headers, application_id)
    assert {"OPPORTUNITY_CREATED", "OPPORTUNITY_QUALIFIED"} <= opportunity_events
    assert {
        "APPLICATION_DRAFT_CREATED",
        "APPLICATION_READY_FOR_REVIEW",
        "OWNER_APPROVED_APPLICATION",
    } <= application_events
    audit = client.get("/api/nova/work/audit", headers=headers, params={"limit": 200})
    summaries = [
        str(row.get("summary") or "")
        for row in audit.json()
        if row.get("ref_id") in {opportunity_id, application_id}
    ]
    assert summaries
    assert all("@" not in summary for summary in summaries)
    assert any("Nothing was sent externally" in summary for summary in summaries)


def test_ui_status_matches_each_funnel_stage() -> None:
    script = (ROOT / "static" / "nova-work" / "work.js").read_text(encoding="utf-8")
    style = (ROOT / "static" / "nova-work" / "work.css").read_text(encoding="utf-8")
    assert "function deriveFunnelStage" in script
    assert "function funnelStageMarkup" in script
    live = script.split("function liveJobItem", 1)[1].split("function setSignedIn", 1)[0]
    saved = script.split("function oppItem", 1)[1].split("function applicationItem", 1)[0]
    review = script.split("function applicationItem", 1)[1].split("function markActiveFilter", 1)[0]
    assert "funnelStageMarkup(opp)" in live
    assert "funnelStageMarkup(row)" in saved
    assert "funnelStageMarkup(row)" in review
    assert ".funnel-stage" in style
    assert 'data-external-send="false"' in style or "data-external-send" in style
    for label in FUNNEL_STAGE_LABELS:
        assert label in script

    fixtures = {
        LABEL_DISCOVERED: {"title": "Data Entry Clerk", "company_name": "Fictional Northwind Records"},
        LABEL_QUALIFIED_UNSAVED: {"title": "Data Entry Clerk", "qualification_status": "QUALIFIED"},
        LABEL_NEEDS_REVIEW_UNSAVED: {"title": "Data Entry Clerk", "qualification_status": "NEEDS_OWNER_REVIEW"},
        LABEL_NOT_QUALIFIED: {"title": "Data Entry Clerk", "eligibility_decision": "fail_closed"},
        LABEL_SAVED_PENDING: {"opportunity_id": "NWO-FICTION", "status": "DISCOVERED"},
        LABEL_SAVED_QUALIFIED: {"opportunity_id": "NWO-FICTION", "status": "QUALIFIED"},
        LABEL_DRAFT: {"application_id": "NWA-FICTION", "approval_state": "DRAFT", "opportunity_id": "NWO-FICTION"},
        LABEL_OWNER_REVIEW: {"approval_state": "READY_FOR_OWNER_REVIEW", "opportunity_id": "NWO-FICTION"},
        LABEL_APPROVED: {"approval_state": "APPROVED", "approved_for_future_submission": True},
        LABEL_SENT: {"externally_submitted": True, "approval_state": "APPROVED"},
        LABEL_CLOSED: {"approval_state": "REJECTED"},
        LABEL_UNCONFIRMED: {},
    }
    for label, record in fixtures.items():
        stage = funnel_stage_status(record)
        assert stage["funnel_stage_label"] == label
        if label == LABEL_SENT:
            assert stage["external_send"] is True
            assert stage["funnel_stage"] == "external_send"
        else:
            assert stage["external_send"] is False


def test_stage_logs_name_the_funnel_and_keep_external_send_off(caplog: pytest.LogCaptureFixture) -> None:
    records = [
        {"title": "Data Entry Clerk"},
        {"qualification_status": "QUALIFIED", "title": "Data Entry Clerk"},
        {"eligibility_decision": "fail_closed", "title": "Data Entry Clerk"},
        {"opportunity_id": "NWO-FICTION", "status": "QUALIFIED"},
        {"approval_state": "DRAFT", "opportunity_id": "NWO-FICTION"},
        {"approval_state": "READY_FOR_OWNER_REVIEW"},
        {"approved_for_future_submission": True},
    ]
    with caplog.at_level(logging.INFO, logger="nova.work_revenue.funnel_status"):
        stages = [funnel_stage_status(record) for record in records]
    assert all(stage["external_send"] is False for stage in stages)
    messages = [item.getMessage() for item in caplog.records if item.name == "nova.work_revenue.funnel_status"]
    assert len(messages) == len(records)
    assert all("external_send=false" in message for message in messages)
    assert any("funnel_stage=discovery" in message for message in messages)
    assert any("funnel_stage=qualification" in message for message in messages)
    assert any("funnel_stage=not_qualified" in message for message in messages)
    assert any("funnel_stage=saved_lead" in message for message in messages)
    assert any("funnel_stage=application_draft" in message for message in messages)
    assert any("funnel_stage=owner_review" in message for message in messages)
    assert any("funnel_stage=approved_not_sent" in message for message in messages)
    assert all("@" not in message for message in messages)
    for stage in stages:
        print(
            f"FUNNEL_ACCEPTANCE case=logs stage={stage['funnel_stage']} "
            f"external_send={'true' if stage['external_send'] else 'false'}"
        )
