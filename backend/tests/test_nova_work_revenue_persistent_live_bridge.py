"""Persistent live-discovery bridge: Remotive/RemoteOK → Work & Revenue inbox.

No external submission, client contact, contracts, invoices, Stripe, or payments.
"""
from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

from app.auth import SEED_PASSWORD, UserContext, ensure_auth_schema, seed_default_users
from app.core.nova.v3 import multi_source_discovery
from app.core.nova.v3.kernel import reset_kernel
from app.core.nova.v3.live_qualification import (
    OUTCOME_NEEDS_OWNER_REVIEW,
    OUTCOME_NOT_QUALIFIED,
    OUTCOME_QUALIFIED,
)
from app.core.nova.v3.work_revenue_bridge import persist_live_job, persist_ranked_jobs
from app.core.nova.work_revenue import flags as wr_flags
from app.core.nova.work_revenue import service as work_service
from app.core.nova.work_revenue.schema_ensure import ensure_work_revenue_schema
from app.core.nova.work_revenue.schemas import OpportunityCreate
from app.core.nova.work_revenue.service import _today_source_counts
from app.db.session import SessionLocal, engine
from app.main import app

ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture(scope="module")
def client() -> TestClient:
    ensure_auth_schema()
    seed_default_users()
    ensure_work_revenue_schema(engine)
    return TestClient(app)


@pytest.fixture(autouse=True)
def _reset_kernel():
    reset_kernel()
    yield
    reset_kernel()


def _headers(client: TestClient, email: str = "dispatcher@amicor.local") -> dict[str, str]:
    response = client.post("/api/auth/login", json={"email": email, "password": SEED_PASSWORD})
    assert response.status_code == 200, response.text
    return {"Authorization": f"Bearer {response.json()['access_token']}"}


def _user_from_login(client: TestClient, email: str = "dispatcher@amicor.local") -> UserContext:
    headers = _headers(client, email)
    me = client.get("/api/auth/me", headers=headers)
    assert me.status_code == 200, me.text
    body = me.json()
    return UserContext(
        user_id=body["user_id"],
        email=body.get("email") or email,
        role=body.get("role") or "dispatcher",
        organization_id=body.get("organization_id"),
    )


def _qualified_job(**overrides) -> dict:
    job = {
        "title": "B2B Data Reporting Project",
        "company_name": "Northwind Analytics LLC",
        "description": (
            "Vendor / B2B project-based engagement. Independent contractor or business vendor welcome. "
            "Deliverables: research, data analysis, and reporting documentation. AI tools allowed. "
            "No membership fee. No upfront fee. Clear statement of work."
        ),
        "source_url": "https://remotive.com/remote-jobs/bridge-b2b-1",
        "provider_id": "remotive",
        "source_attribution": "Remotive",
        "geography": "Worldwide",
        "remote_status": "remote",
        "job_type": "contract",
        "compensation_text": "$2,500 per project",
        "qualification_status": OUTCOME_QUALIFIED,
        "live_qualification": {"qualification_status": OUTCOME_QUALIFIED},
        "relevance_score": 90,
    }
    job.update(overrides)
    return job


def _enable_live(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("NOVA_V3_LIVE_DISCOVERY_ENABLED", "true")
    monkeypatch.setenv("NOVA_V3_EXTERNAL_SUBMISSION_ENABLED", "false")
    monkeypatch.setattr(
        multi_source_discovery,
        "live_flags",
        lambda: {
            "LIVE_DISCOVERY_ENABLED": True,
            "EXTERNAL_SUBMISSION_ENABLED": False,
            "FINANCIAL_EXECUTION_ENABLED": False,
            "REAL_FINANCIAL_EXECUTION": False,
            "APPROVED_EQUALS_SUBMITTED": False,
        },
    )


def test_create_discovered_opportunity_preserves_provider_source(client: TestClient) -> None:
    user = _user_from_login(client)
    db = SessionLocal()
    try:
        org = user.organization_id or "org-test"
        row = work_service.create_discovered_opportunity(
            db,
            OpportunityCreate(
                organization_id=org,
                source="remotive",
                source_type="approved_api",
                source_url="https://remotive.com/remote-jobs/preserve-source",
                company_name="Preserve Source Co",
                opportunity_title="Remote reporting contractor",
                description="Remote spreadsheet reporting and CRM updates. Fully remote.",
                physical_presence_required="false",
            ),
            organization_id=org,
            user=user,
        )
        assert row.opportunity_id.startswith("NWO-")
        assert row.source == "remotive"
        assert row.source_type == "approved_api"
        manual = work_service.create_opportunity(
            db,
            OpportunityCreate(
                organization_id=org,
                source="remotive",
                source_type="approved_api",
                company_name="Manual Force Co",
                opportunity_title="Manual entry still forced",
                description="Remote admin support. Fully remote.",
                physical_presence_required="false",
            ),
            organization_id=org,
            user=user,
        )
        assert manual.source == "manual"
    finally:
        db.close()


def test_qualified_live_job_persists_and_counts_as_live(client: TestClient) -> None:
    user = _user_from_login(client)
    db = SessionLocal()
    try:
        org = user.organization_id or "org-test"
        result = persist_live_job(
            db,
            _qualified_job(source_url="https://remotive.com/remote-jobs/persist-live-1"),
            organization_id=org,
            user=user,
            prepare_application=False,
        )
        assert result["persisted"] is True
        assert result["work_opportunity_id"].startswith("NWO-")
        assert result["provider_id"] == "remotive"
        assert result["work_application_id"] is None
        assert result["externally_submitted"] is False
        assert result["financial_execution"] is False
        row = work_service.get_opportunity(
            db,
            result["work_opportunity_id"],
            organization_id=org,
            user=user,
        )
        assert row.source == "remotive"
        assert row.source_type == "approved_api"
        outs = [
            SimpleNamespace(source_type=row.source_type, source=row.source)
            for row in work_service.list_opportunities(db, organization_id=org, user=user, limit=50)
            if row.source_type == "approved_api"
        ]
        counts = _today_source_counts(outs)
        assert counts["live"] >= 1
        assert counts["other"] == 0
    finally:
        db.close()


def test_duplicate_discovery_reuses_opportunity(client: TestClient) -> None:
    user = _user_from_login(client)
    db = SessionLocal()
    try:
        org = user.organization_id or "org-test"
        job = _qualified_job(source_url="https://remotive.com/remote-jobs/dup-1")
        first = persist_live_job(db, job, organization_id=org, user=user, prepare_application=False)
        second = persist_live_job(db, job, organization_id=org, user=user, prepare_application=False)
        assert first["work_opportunity_id"] == second["work_opportunity_id"]
        assert second["created"] is False
        rows = [
            row
            for row in work_service.list_opportunities(db, organization_id=org, user=user, limit=200)
            if row.source_url == job["source_url"]
        ]
        assert len(rows) == 1
    finally:
        db.close()


def test_prepare_qualified_creates_application_idempotently(client: TestClient) -> None:
    user = _user_from_login(client)
    db = SessionLocal()
    try:
        org = user.organization_id or "org-test"
        job = _qualified_job(source_url="https://remotive.com/remote-jobs/prep-1")
        first = persist_live_job(db, job, organization_id=org, user=user, prepare_application=True)
        assert first["work_application_id"]
        assert first["work_application_id"].startswith("NWA-")
        assert first["application_state"] in {"DRAFT", "READY_FOR_OWNER_REVIEW", "NEEDS_CHANGES"}
        if first["package_review_status"] != "BLOCKED":
            assert first["ready_for_owner_review"] is True
            assert first["application_state"] == "READY_FOR_OWNER_REVIEW"
        second = persist_live_job(db, job, organization_id=org, user=user, prepare_application=True)
        assert second["work_opportunity_id"] == first["work_opportunity_id"]
        assert second["work_application_id"] == first["work_application_id"]
        apps = [
            row
            for row in work_service.list_applications(db, organization_id=org, user=user, limit=200)
            if row.opportunity_id == first["work_opportunity_id"]
        ]
        assert len(apps) == 1
        assert first["externally_submitted"] is False
        assert first["client_contacted"] is False
        assert first["contract_accepted"] is False
        assert first["stripe_action"] is False
    finally:
        db.close()


def test_needs_owner_review_and_not_qualified_do_not_auto_prepare(client: TestClient) -> None:
    user = _user_from_login(client)
    db = SessionLocal()
    try:
        org = user.organization_id or "org-test"
        held = persist_live_job(
            db,
            _qualified_job(
                title="Ambiguous vendor role",
                company_name="Review Hold Co",
                source_url="https://remoteok.com/remote-jobs/hold-1",
                provider_id="remoteok",
                description="Possible remote admin work. Details unclear. May require onsite.",
                qualification_status=OUTCOME_NEEDS_OWNER_REVIEW,
                live_qualification={"qualification_status": OUTCOME_NEEDS_OWNER_REVIEW},
            ),
            organization_id=org,
            user=user,
            prepare_application=True,
        )
        assert held["work_opportunity_id"]
        assert held["work_application_id"] is None
        assert held["package_review_status"] == "HELD_FOR_OWNER_REVIEW"

        rejected = persist_live_job(
            db,
            _qualified_job(
                title="Delivery driver needed",
                company_name="Physical Co",
                source_url="https://remotive.com/remote-jobs/driver-1",
                description="Must drive a van and deliver packages in person every day.",
                qualification_status=OUTCOME_NOT_QUALIFIED,
                live_qualification={"qualification_status": OUTCOME_NOT_QUALIFIED},
                remote_status="onsite",
            ),
            organization_id=org,
            user=user,
            prepare_application=True,
        )
        assert rejected["work_opportunity_id"]
        assert rejected["work_application_id"] is None
        assert rejected["package_review_status"] == "SKIPPED_NOT_QUALIFIED"
    finally:
        db.close()


def test_prepare_limit_respected(client: TestClient) -> None:
    user = _user_from_login(client)
    db = SessionLocal()
    try:
        org = user.organization_id or "org-test"
        jobs = [
            _qualified_job(
                title=f"Remote admin contractor {idx}",
                company_name=f"Limit Co {idx}",
                source_url=f"https://remotive.com/remote-jobs/limit-{idx}",
            )
            for idx in range(3)
        ]
        results = persist_ranked_jobs(
            db,
            jobs,
            organization_id=org,
            user=user,
            prepare_applications=True,
            prepare_limit=1,
        )
        prepared = [row for row in results if row.get("work_application_id")]
        assert len(prepared) == 1
        assert all(row["persisted"] for row in results)
    finally:
        db.close()


def test_cross_tenant_access_blocked(client: TestClient) -> None:
    owner_a = _user_from_login(client, "dispatcher@amicor.local")
    owner_b = _user_from_login(client, "admin@amicor.local")
    db = SessionLocal()
    try:
        org_a = owner_a.organization_id or "org-a"
        result = persist_live_job(
            db,
            _qualified_job(source_url="https://remotive.com/remote-jobs/tenant-a"),
            organization_id=org_a,
            user=owner_a,
            prepare_application=False,
        )
        with pytest.raises(work_service.NovaWorkError):
            work_service.get_opportunity(
                db,
                result["work_opportunity_id"],
                organization_id="org-not-the-caller",
                user=owner_b,
            )
    finally:
        db.close()


def test_http_discover_and_prepare_persist(client: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
    _enable_live(monkeypatch)

    def _fake_search(query: str, limit: int = 20):
        return {
            "jobs": [
                _qualified_job(
                    title="B2B Spreadsheet Cleanup Project",
                    company_name="HTTP Bridge Analytics LLC",
                    source_url="https://remotive.com/remote-jobs/http-bridge-1",
                    description=(
                        "Vendor / B2B project-based engagement. Independent contractor or business vendor welcome. "
                        "Deliverables: spreadsheet cleanup, data reconciliation, and reporting. "
                        "AI tools allowed. No membership fee. Clear statement of work."
                    ),
                    compensation_text="$1,800 per project",
                )
            ],
            "providers_queried": ["remotive", "remoteok"],
            "provider_result_counts": {"remotive": 1, "remoteok": 0},
            "provider_errors": [],
            "provider_health": [],
        }

    monkeypatch.setattr(multi_source_discovery, "search_multi_source_jobs", _fake_search)
    monkeypatch.setattr(
        "app.core.nova.v3.router.search_multi_source_jobs",
        _fake_search,
    )

    headers = _headers(client)
    discover = client.post(
        "/api/nova/v3/live/jobs/discover",
        headers=headers,
        json={"query": "remote reporting vendor", "limit": 5, "save_limit": 5, "min_relevance_score": 0},
    )
    assert discover.status_code == 200, discover.text
    body = discover.json()
    assert body["source"] == "multi_source"
    assert body["external_submission"] is False
    assert body["financial_execution"] is False
    assert "ranked_jobs" in body
    assert "saved" in body
    assert body["persistent_results"]
    assert body["persistent_results"][0]["live_qualification_status"] == OUTCOME_QUALIFIED
    opp_id = body["persistent_results"][0]["work_opportunity_id"]
    assert opp_id.startswith("NWO-")
    assert body["persistent_results"][0]["provider_id"] == "remotive"
    assert body["persistent_results"][0]["work_application_id"] is None

    prepare = client.post(
        "/api/nova/v3/live/jobs/prepare",
        headers=headers,
        json={
            "query": "remote reporting vendor",
            "limit": 5,
            "save_limit": 5,
            "prepare_limit": 2,
            "min_relevance_score": 0,
        },
    )
    assert prepare.status_code == 200, prepare.text
    prep = prepare.json()
    assert prep["source"] == "multi_source"
    assert prep["external_submission"] is False
    assert prep["financial_execution"] is False
    assert "prepared" in prep
    assert "persistent_results" in prep
    assert prep["persistent_results"][0]["work_opportunity_id"] == opp_id
    assert prep["persistent_results"][0]["work_application_id"]
    assert prep["auto_prepared_only_qualified"] is True

    guards = wr_flags.engine_guardrails()
    assert guards["EXTERNAL_SUBMISSION_ENABLED"] is False
    assert guards["FINANCIAL_ACTIONS_ENABLED"] is False
