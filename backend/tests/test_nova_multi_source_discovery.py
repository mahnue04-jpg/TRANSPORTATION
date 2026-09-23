"""Multi-source contract/project discovery — fixtures and provider stubs only.

No live network calls, no submissions, no financial execution.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import pytest

from app.core.nova.v3 import live_discovery
from app.core.nova.v3.errors import V3Error
from app.core.nova.v3.flags import live_flags
from app.core.nova.v3.live_qualification import (
    OUTCOME_NOT_QUALIFIED,
    OUTCOME_QUALIFIED,
    qualify_and_rank_live_jobs,
    qualify_live_job,
)
from app.core.nova.v3.multi_source_discovery import (
    PENDING_PROVIDERS,
    PROVIDER_TYPES,
    ProviderMeta,
    RemotiveLiveProvider,
    RemoteOkLiveProvider,
    dedupe_opportunities,
    live_providers,
    normalize_opportunity,
    provider_catalog,
    reset_provider_health_for_tests,
    search_multi_source_jobs,
)
from app.core.nova.work_revenue.capability_classification import (
    CANNOT_PERFORM,
    INSUFFICIENT_INFORMATION,
    classify_opportunity_capability,
)
from app.core.nova.work_revenue.capability_first_discovery import (
    SEARCH_FAMILIES,
    capability_first_search_queries,
)
from app.core.nova.work_revenue.flags import engine_guardrails


@dataclass
class _StubProvider:
    meta: ProviderMeta
    rows: list[dict[str, Any]]
    fail: bool = False

    def search(self, query: str, *, limit: int = 10) -> list[dict[str, Any]]:
        if self.fail:
            raise RuntimeError(f"{self.meta.provider_id} outage")
        return list(self.rows)[:limit]


def _norm(**kwargs: Any) -> dict[str, Any]:
    return normalize_opportunity(**kwargs)


def _b2b_project(*, provider_id: str = "vendor_stub", url: str = "https://example.com/projects/b2b-1") -> dict:
    return _norm(
        provider_id=provider_id,
        provider_type="vendor_project_board",
        provider_identifier="b2b-1",
        source_name=provider_id,
        source_url=url,
        title="B2B Spreadsheet Cleanup Project",
        company_name="Northwind Analytics LLC",
        description=(
            "Vendor / B2B project-based engagement. Independent contractor welcome. "
            "Deliverables: spreadsheet cleanup, data reconciliation, and reporting. "
            "AI tools allowed. Clear statement of work. No membership fee."
        ),
        compensation_text="$1,800 per project",
        contract_type="contract",
        remote_status="remote",
        geography="Worldwide",
        fee_required="no",
        simulated=False,
    )


def _w2_job() -> dict:
    return _norm(
        provider_id="remotive",
        provider_type="remote_contract_feed",
        provider_identifier="w2-1",
        source_name="Remotive",
        source_url="https://remotive.com/remote-jobs/w2-office",
        title="Remote Office Assistant",
        company_name="Coalition Technologies",
        description=(
            "Full-time staff position. Join our team as an employee with benefits package "
            "and 401k. W-2 employment. Office assistant duties, schedules, and reporting."
        ),
        compensation_text="$45,000",
        contract_type="full_time",
        remote_status="remote",
        geography="USA",
        fee_required="no",
        simulated=False,
    )


def _physical_job() -> dict:
    return _norm(
        provider_id="remoteok",
        provider_type="remote_contract_feed",
        provider_identifier="phys-1",
        source_name="RemoteOK",
        source_url="https://remoteok.com/remote-jobs/warehouse",
        title="Warehouse Associate",
        company_name="Warehouse Co",
        description="On-site physical labor required. Heavy lifting, packing, and loading daily.",
        compensation_text="$20/hr",
        contract_type="contract",
        remote_status="onsite",
        geography="Texas",
        fee_required="no",
        simulated=False,
    )


def _licensed_job() -> dict:
    return _norm(
        provider_id="remotive",
        provider_type="remote_contract_feed",
        provider_identifier="rn-1",
        source_name="Remotive",
        source_url="https://remotive.com/remote-jobs/rn",
        title="Remote Registered Nurse",
        company_name="Clinic Co",
        description="Licensed medical RN required. Patient care and clinical judgment.",
        compensation_text="$80/hr",
        contract_type="contract",
        remote_status="remote",
        geography="USA",
        fee_required="no",
        simulated=False,
    )


def _insufficient_job() -> dict:
    return _norm(
        provider_id="remoteok",
        provider_type="remote_contract_feed",
        provider_identifier="thin-1",
        source_name="RemoteOK",
        source_url="https://remoteok.com/remote-jobs/mystery",
        title="Help Needed",
        company_name="Mystery LLC",
        description="Do some work somehow.",
        compensation_text=None,
        contract_type=None,
        remote_status="remote",
        geography="Remote",
        fee_required="unknown",
        simulated=False,
    )


def _simulated_job() -> dict:
    return _norm(
        provider_id="sim_fixture",
        provider_type="job_board",
        provider_identifier="sim-1",
        source_name="Simulated",
        source_url="https://example.test/sim/1",
        title="Simulated Spreadsheet Project",
        company_name="Sim Co",
        description="Simulated B2B spreadsheet cleanup for tests only.",
        compensation_text="$500",
        contract_type="contract",
        remote_status="remote",
        geography="Worldwide",
        fee_required="no",
        simulated=True,
    )


@pytest.fixture(autouse=True)
def _reset_health(monkeypatch):
    reset_provider_health_for_tests()
    monkeypatch.setattr(
        "app.core.nova.v3.multi_source_discovery.live_flags",
        lambda: {"LIVE_DISCOVERY_ENABLED": True},
    )
    yield
    reset_provider_health_for_tests()


def test_provider_type_classes_supported() -> None:
    required = {
        "freelance_marketplace",
        "government_contracting",
        "vendor_project_board",
        "career_page",
        "job_board",
        "public_rfp_feed",
        "remote_contract_feed",
    }
    assert required.issubset(set(PROVIDER_TYPES))


def test_more_than_one_live_provider_registered() -> None:
    providers = live_providers()
    assert len(providers) >= 3
    ids = {p.meta.provider_id for p in providers}
    assert "remotive" in ids
    assert "remoteok" in ids
    assert "sam_gov" in ids
    assert all(p.meta.enabled for p in providers)


def test_remotive_still_works_as_one_source(monkeypatch) -> None:
    class _Resp:
        def raise_for_status(self):
            return None

        def json(self):
            return {
                "jobs": [
                    {
                        "id": "r1",
                        "url": "https://remotive.com/remote-jobs/ops-1",
                        "title": "Remote Operations Assistant",
                        "company_name": "Example Co",
                        "description": "Prepare reports and coordinate tasks.",
                        "candidate_required_location": "USA",
                        "salary": "$40/hr",
                        "job_type": "contract",
                        "publication_date": "2026-09-20T00:00:00",
                    }
                ]
            }

    class _Client:
        def __init__(self, *a, **k):
            pass

        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

        def get(self, *a, **k):
            return _Resp()

    monkeypatch.setattr(
        "app.core.nova.v3.multi_source_discovery.httpx.Client",
        _Client,
    )
    rows = RemotiveLiveProvider().search("operations", limit=5)
    assert len(rows) == 1
    assert rows[0]["provider_id"] == "remotive"
    assert rows[0]["provider_type"] == "remote_contract_feed"
    assert rows[0]["real_or_simulated"] == "REAL"
    assert rows[0]["source_url"].startswith("https://remotive.com/")

    # Legacy Remotive path remains available for regression.
    live_discovery._cache.clear()
    monkeypatch.setattr(live_discovery, "live_flags", lambda: {"LIVE_DISCOVERY_ENABLED": True})
    monkeypatch.setattr(live_discovery.httpx, "Client", _Client)
    legacy = live_discovery.search_remote_jobs("operations", limit=5)
    assert legacy[0]["provider_id"] == "remotive"


def test_multiple_provider_results_merge() -> None:
    a = _StubProvider(
        ProviderMeta(
            provider_id="remotive",
            label="Remotive",
            provider_type="remote_contract_feed",
            enabled=True,
            access_status="public_api",
            access_mode="api",
            requires_login=False,
            requires_fee=False,
            supports_detail_fetch=False,
            supports_external_submission=False,
            terms_safety_notes="test",
            priority=40,
        ),
        [_w2_job()],
    )
    b = _StubProvider(
        ProviderMeta(
            provider_id="remoteok",
            label="RemoteOK",
            provider_type="remote_contract_feed",
            enabled=True,
            access_status="public_api",
            access_mode="api",
            requires_login=False,
            requires_fee=False,
            supports_detail_fetch=False,
            supports_external_submission=False,
            terms_safety_notes="test",
            priority=41,
        ),
        [_b2b_project(provider_id="remoteok", url="https://remoteok.com/remote-jobs/b2b")],
    )
    result = search_multi_source_jobs(
        "spreadsheet project",
        limit=10,
        providers_override=[a, b],
    )
    assert result["count"] == 2
    assert set(result["providers_queried"]) == {"remotive", "remoteok"}
    assert result["provider_result_counts"]["remotive"] == 1
    assert result["provider_result_counts"]["remoteok"] == 1
    assert result["external_submission"] is False
    assert result["financial_execution"] is False


def test_duplicate_opportunities_collapse_with_provenance() -> None:
    shared_url = "https://example.com/projects/same"
    a = _StubProvider(
        ProviderMeta(
            provider_id="remotive",
            label="Remotive",
            provider_type="remote_contract_feed",
            enabled=True,
            access_status="public_api",
            access_mode="api",
            requires_login=False,
            requires_fee=False,
            supports_detail_fetch=False,
            supports_external_submission=False,
            terms_safety_notes="test",
            priority=40,
        ),
        [_b2b_project(provider_id="remotive", url=shared_url)],
    )
    b = _StubProvider(
        ProviderMeta(
            provider_id="remoteok",
            label="RemoteOK",
            provider_type="remote_contract_feed",
            enabled=True,
            access_status="public_api",
            access_mode="api",
            requires_login=False,
            requires_fee=False,
            supports_detail_fetch=False,
            supports_external_submission=False,
            terms_safety_notes="test",
            priority=41,
        ),
        [_b2b_project(provider_id="remoteok", url=shared_url)],
    )
    result = search_multi_source_jobs("project", limit=10, providers_override=[a, b])
    assert result["count"] == 1
    job = result["jobs"][0]
    assert set(job["provenance_sources"]) == {"remotive", "remoteok"}

    collapsed = dedupe_opportunities(
        [
            _b2b_project(provider_id="a", url="https://x.test/1"),
            _b2b_project(provider_id="b", url="https://x.test/1"),
        ]
    )
    assert len(collapsed) == 1
    assert collapsed[0]["provenance_sources"] == ["a", "b"]


def test_w2_physical_licensed_insufficient_and_b2b_guards() -> None:
    w2 = qualify_live_job(_w2_job())
    assert w2["qualification_status"] == OUTCOME_NOT_QUALIFIED

    physical = classify_opportunity_capability(_physical_job())
    assert physical["capability_classification"] == CANNOT_PERFORM
    assert physical["required_physical_presence"] == "YES"

    licensed = classify_opportunity_capability(_licensed_job())
    assert licensed["capability_classification"] == CANNOT_PERFORM

    thin = classify_opportunity_capability(_insufficient_job())
    assert thin["capability_classification"] == INSUFFICIENT_INFORMATION
    ranked_thin = qualify_and_rank_live_jobs("help", [_insufficient_job()])
    assert ranked_thin[0]["qualification_status"] != OUTCOME_QUALIFIED

    b2b = qualify_live_job(_b2b_project())
    assert b2b["qualification_status"] == OUTCOME_QUALIFIED


def test_simulated_excluded_from_real_totals() -> None:
    real = _StubProvider(
        ProviderMeta(
            provider_id="remoteok",
            label="RemoteOK",
            provider_type="remote_contract_feed",
            enabled=True,
            access_status="public_api",
            access_mode="api",
            requires_login=False,
            requires_fee=False,
            supports_detail_fetch=False,
            supports_external_submission=False,
            terms_safety_notes="test",
            priority=40,
        ),
        [_b2b_project(provider_id="remoteok")],
    )
    sim = _StubProvider(
        ProviderMeta(
            provider_id="sim_fixture",
            label="Simulated",
            provider_type="job_board",
            enabled=True,
            access_status="test_only",
            access_mode="page",
            requires_login=False,
            requires_fee=False,
            supports_detail_fetch=False,
            supports_external_submission=False,
            terms_safety_notes="test fixture",
            priority=90,
        ),
        [_simulated_job()],
    )
    defaulted = search_multi_source_jobs("spreadsheet", limit=10, providers_override=[real, sim])
    assert defaulted["real_count"] == 1
    assert defaulted["simulated_count"] == 0
    assert all(not row.get("simulated") for row in defaulted["jobs"])

    with_sim = search_multi_source_jobs(
        "spreadsheet",
        limit=10,
        providers_override=[real, sim],
        include_simulated=True,
    )
    assert with_sim["real_count"] == 1
    assert with_sim["simulated_count"] == 1


def test_provider_outage_isolates_failure() -> None:
    good = _StubProvider(
        ProviderMeta(
            provider_id="remoteok",
            label="RemoteOK",
            provider_type="remote_contract_feed",
            enabled=True,
            access_status="public_api",
            access_mode="api",
            requires_login=False,
            requires_fee=False,
            supports_detail_fetch=False,
            supports_external_submission=False,
            terms_safety_notes="test",
            priority=40,
        ),
        [_b2b_project(provider_id="remoteok")],
    )
    bad = _StubProvider(
        ProviderMeta(
            provider_id="remotive",
            label="Remotive",
            provider_type="remote_contract_feed",
            enabled=True,
            access_status="public_api",
            access_mode="api",
            requires_login=False,
            requires_fee=False,
            supports_detail_fetch=False,
            supports_external_submission=False,
            terms_safety_notes="test",
            priority=39,
        ),
        [],
        fail=True,
    )
    result = search_multi_source_jobs("project", limit=10, providers_override=[bad, good])
    assert result["count"] == 1
    assert result["jobs"][0]["provider_id"] == "remoteok"
    assert any(err["provider_id"] == "remotive" for err in result["provider_errors"])
    health = {row["provider_id"]: row for row in result["provider_health"]}
    assert health["remotive"]["status"] == "error"
    assert health["remoteok"]["status"] == "ok"


def test_pending_providers_disabled_and_catalog_quality() -> None:
    catalog = provider_catalog()
    enabled = [row for row in catalog if row["enabled"]]
    pending = [row for row in catalog if not row["enabled"]]
    assert len(enabled) >= 3
    assert {row["provider_id"] for row in enabled} >= {"remotive", "remoteok", "sam_gov"}
    assert len(pending) >= 3
    for row in catalog:
        assert row["supports_external_submission"] is False
        assert "requires_login" in row
        assert "requires_fee" in row
        assert "terms_safety_notes" in row
        assert row["provider_type"] in PROVIDER_TYPES or row["provider_id"] in {
            p.meta.provider_id for p in PENDING_PROVIDERS
        }
    pending_ids = {p.meta.provider_id for p in PENDING_PROVIDERS}
    assert {"upwork", "freelancer", "public_rfp_rss", "vendor_project_board"} <= pending_ids
    assert "sam_gov" not in pending_ids
    for item in PENDING_PROVIDERS:
        assert item.meta.enabled is False
        assert item.meta.pending_requirements
    sam_row = next(row for row in catalog if row["provider_id"] == "sam_gov")
    assert sam_row["enabled"] is True
    assert sam_row["supports_external_submission"] is False
    assert sam_row["access_status"] in {"api_key_configured", "api_key_missing", "public_api_key_required"}


def test_capability_first_families_not_remotive_only() -> None:
    queries = capability_first_search_queries()
    assert queries
    families = set(SEARCH_FAMILIES)
    for needed in {
        "bookkeeping_support",
        "research_analysis",
        "administrative_operations",
        "data_spreadsheet",
        "web_software",
        "document_writing",
    }:
        assert needed in families
    # Architecture: enabled live providers cover every family search path.
    assert len(live_providers()) >= 2


def test_live_discovery_disabled_blocks_multi_source(monkeypatch) -> None:
    monkeypatch.setattr(
        "app.core.nova.v3.multi_source_discovery.live_flags",
        lambda: {"LIVE_DISCOVERY_ENABLED": False},
    )
    with pytest.raises(V3Error) as exc:
        search_multi_source_jobs("ops")
    assert exc.value.code == "LIVE_DISABLED"


def test_external_submission_and_financial_remain_off() -> None:
    guards = engine_guardrails()
    flags = live_flags()
    assert guards.get("EXTERNAL_SUBMISSION_ENABLED") is False or guards.get("EXTERNAL_SUBMISSION") is False
    assert flags["EXTERNAL_SUBMISSION_ENABLED"] is False
    assert flags["FINANCIAL_EXECUTION_ENABLED"] is False
    assert flags["REAL_FINANCIAL_EXECUTION"] is False
    assert all(not p.meta.supports_external_submission for p in live_providers())
    assert all(not p.meta.supports_external_submission for p in PENDING_PROVIDERS)


def test_remoteok_token_filter(monkeypatch) -> None:
    class _Resp:
        def raise_for_status(self):
            return None

        def json(self):
            return [
                {"legal": "RemoteOK"},
                {
                    "id": "1",
                    "position": "Spreadsheet Cleanup Contract",
                    "company": "Data Co",
                    "url": "https://remoteok.com/remote-jobs/1",
                    "description": "Freelance spreadsheet cleanup project",
                    "tags": ["contract", "freelance"],
                    "salary": "$1500",
                    "location": "Remote",
                    "date": "2026-09-20",
                },
                {
                    "id": "2",
                    "position": "Senior React Engineer",
                    "company": "App Co",
                    "url": "https://remoteok.com/remote-jobs/2",
                    "description": "Build SPA features",
                    "tags": ["react"],
                    "salary": "$120k",
                    "location": "Remote",
                    "date": "2026-09-19",
                },
            ]

    class _Client:
        def __init__(self, *a, **k):
            pass

        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

        def get(self, *a, **k):
            return _Resp()

    monkeypatch.setattr(
        "app.core.nova.v3.multi_source_discovery.httpx.Client",
        _Client,
    )
    rows = RemoteOkLiveProvider().search("spreadsheet freelance", limit=10)
    assert len(rows) == 1
    assert rows[0]["provider_id"] == "remoteok"
    assert rows[0]["title"] == "Spreadsheet Cleanup Contract"



def test_admin_search_filters_unrelated_technical_titles(monkeypatch) -> None:
    monkeypatch.setenv("NOVA_V3_LIVE_DISCOVERY_ENABLED", "1")

    class AdminProvider:
        meta = ProviderMeta(
            provider_id="admin-test",
            label="Admin test",
            provider_type="remote_contract_feed",
            enabled=True,
            access_status="test",
            access_mode="api",
            requires_login=False,
            requires_fee=False,
            supports_detail_fetch=False,
            supports_external_submission=False,
            terms_safety_notes="test",
            priority=1,
        )

        def search(self, query: str, *, limit: int = 10):
            return [
                normalize_opportunity(
                    provider_id="admin-test",
                    provider_type="remote_contract_feed",
                    provider_identifier="admin-1",
                    source_url="https://example.test/admin-1",
                    title="Remote Administrative Support Contractor",
                    company_name="Example",
                    description="Scheduling, document preparation, CRM cleanup and reporting support.",
                    job_type="contract",
                    remote_status="remote",
                    simulated=False,
                ),
                normalize_opportunity(
                    provider_id="admin-test",
                    provider_type="remote_contract_feed",
                    provider_identifier="dev-1",
                    source_url="https://example.test/dev-1",
                    title="Senior Shopify Developer",
                    company_name="Example",
                    description="Build storefront software and support development operations.",
                    job_type="contract",
                    remote_status="remote",
                    simulated=False,
                ),
                normalize_opportunity(
                    provider_id="admin-test",
                    provider_type="remote_contract_feed",
                    provider_identifier="ai-1",
                    source_url="https://example.test/ai-1",
                    title="Senior AI Engineer",
                    company_name="Example",
                    description="Machine learning engineering and platform operations.",
                    job_type="contract",
                    remote_status="remote",
                    simulated=False,
                ),
            ]

    result = search_multi_source_jobs(
        "remote administrative support contractor",
        limit=10,
        providers_override=[AdminProvider()],
    )

    assert result["count"] == 1
    assert result["jobs"][0]["title"] == "Remote Administrative Support Contractor"
    assert result["external_action_taken"] is False



def test_admin_search_targets_us_contract_and_rejects_employee_fee_and_foreign_only(monkeypatch) -> None:
    monkeypatch.setenv("NOVA_V3_LIVE_DISCOVERY_ENABLED", "1")

    class TargetProvider:
        meta = ProviderMeta(
            provider_id="admin-target-test",
            label="Admin target test",
            provider_type="remote_contract_feed",
            enabled=True,
            access_status="test",
            access_mode="api",
            requires_login=False,
            requires_fee=False,
            supports_detail_fetch=False,
            supports_external_submission=False,
            terms_safety_notes="test",
            priority=1,
        )

        def search(self, query: str, *, limit: int = 10):
            common = dict(
                provider_id="admin-target-test",
                provider_type="remote_contract_feed",
                company_name="Example",
                remote_status="remote",
                simulated=False,
            )
            return [
                normalize_opportunity(
                    **common,
                    provider_identifier="contract-us",
                    source_url="https://example.test/contract-us",
                    title="Remote Administrative Support Contractor",
                    description="1099 contractor for scheduling, CRM cleanup and document support.",
                    job_type="contract",
                    geography="United States remote nationwide",
                ),
                normalize_opportunity(
                    **common,
                    provider_identifier="employee-us",
                    source_url="https://example.test/employee-us",
                    title="Remote Office Assistant",
                    description="Full-time employee role with salary, benefits and 401(k).",
                    job_type="employee",
                    geography="United States",
                ),
                normalize_opportunity(
                    **common,
                    provider_identifier="fee",
                    source_url="https://example.test/fee",
                    title="Administrative Assistant Contractor",
                    description="Contract work. Paid membership required to access applications.",
                    job_type="contract",
                    geography="United States",
                ),
                normalize_opportunity(
                    **common,
                    provider_identifier="foreign",
                    source_url="https://example.test/foreign",
                    title="Administrative Support Freelancer",
                    description="Freelance administrative support.",
                    job_type="freelance",
                    geography="Europe",
                ),
            ]

    result = search_multi_source_jobs(
        "remote administrative support contractor",
        limit=10,
        providers_override=[TargetProvider()],
    )

    assert result["count"] == 1
    assert result["jobs"][0]["title"] == "Remote Administrative Support Contractor"
    assert result["external_action_taken"] is False


def test_admin_search_expands_queries_and_requires_positive_title_fit(monkeypatch):
    monkeypatch.setenv("NOVA_V3_LIVE_DISCOVERY_ENABLED", "true")

    class Provider:
        meta = multi_source_discovery.ProviderMeta(
            provider_id="positive_fit_fixture",
            label="Positive Fit Fixture",
            provider_type="remote_contract_feed",
            enabled=True,
            access_status="test",
            access_mode="api",
            requires_login=False,
            requires_fee=False,
            supports_detail_fetch=False,
            supports_external_submission=False,
            terms_safety_notes="test only",
            priority=1,
        )

        def __init__(self):
            self.queries = []

        def search(self, query, *, limit=10):
            self.queries.append(query)
            if "virtual assistant" in query.lower():
                return [
                    multi_source_discovery.normalize_opportunity(
                        provider_id=self.meta.provider_id,
                        provider_type=self.meta.provider_type,
                        provider_identifier="va-1",
                        title="Virtual Assistant Contractor",
                        company_name="Example Client",
                        description="Remote calendar, email, document and administrative support.",
                        source_url="https://example.test/va-1",
                        job_type="contractor",
                        geography="United States remote",
                        fee_required="no",
                    )
                ]
            return [
                multi_source_discovery.normalize_opportunity(
                    provider_id=self.meta.provider_id,
                    provider_type=self.meta.provider_type,
                    provider_identifier="sales-1",
                    title="Regional Sales Manager",
                    company_name="Example Client",
                    description="Contract role supporting business operations and scheduling.",
                    source_url="https://example.test/sales-1",
                    job_type="contractor",
                    geography="United States remote",
                    fee_required="no",
                )
            ]

    provider = Provider()
    result = multi_source_discovery.search_multi_source_jobs(
        "remote administrative support contractor",
        limit=10,
        providers_override=[provider],
    )

    assert len(provider.queries) > 1
    assert result["count"] == 1
    assert result["jobs"][0]["title"] == "Virtual Assistant Contractor"
    assert result["provider_screened_counts"]["positive_fit_fixture"] >= 2
    assert "remote administrative support contractor" in result["query_variants"]
