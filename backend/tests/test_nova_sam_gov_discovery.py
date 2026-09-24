"""Focused SAM.gov discovery tests — fixtures/stubs only.

No live network calls unless explicitly marked. Never prints or asserts the API key value.
No proposal submission, agency contact, contract acceptance, or Stripe/financial execution.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import pytest

from app.core.nova.v3.live_qualification import (
    OUTCOME_NOT_QUALIFIED,
    OUTCOME_QUALIFIED,
    qualify_live_job,
)
from app.core.nova.v3.multi_source_discovery import (
    PENDING_PROVIDERS,
    ProviderMeta,
    RemotiveLiveProvider,
    RemoteOkLiveProvider,
    SamGovLiveProvider,
    SamGovUnavailable,
    dedupe_opportunities,
    live_providers,
    normalize_opportunity,
    opportunity_dedupe_key,
    provider_catalog,
    reset_provider_health_for_tests,
    sam_gov_key_configured,
    search_multi_source_jobs,
)
from app.core.nova.work_revenue.flags import engine_guardrails
from app.core.nova.v3.flags import live_flags


FAKE_KEY = "test-sam-gov-key-do-not-use-in-production"


@dataclass
class _StubProvider:
    meta: ProviderMeta
    rows: list[dict[str, Any]]
    fail: bool = False
    fail_exc: Exception | None = None

    def search(self, query: str, *, limit: int = 10) -> list[dict[str, Any]]:
        if self.fail:
            raise self.fail_exc or RuntimeError(f"{self.meta.provider_id} outage")
        return list(self.rows)[:limit]


def _sam_admin_notice(**overrides: Any) -> dict[str, Any]:
    base = {
        "noticeId": "abc123noticeid001",
        "title": "Remote Administrative Support and Document Preparation Services",
        "solicitationNumber": " fort-admin-26-001 ",
        "fullParentPathName": "DEPARTMENT OF COMMERCE.OFFICE OF THE SECRETARY",
        "postedDate": "2026-09-10",
        "type": "Solicitation",
        "typeOfSetAsideDescription": "Total Small Business Set-Aside (FAR 19.5)",
        "typeOfSetAside": "SBA",
        "responseDeadLine": "2026-10-15T17:00:00-04:00",
        "naicsCode": "561110",
        "active": "Yes",
        "description": "https://api.sam.gov/opportunities/v1/noticedesc?noticeid=abc123noticeid001",
        "placeOfPerformance": {
            "city": {"name": "Remote"},
            "state": {"name": "Nationwide"},
            "country": {"name": "UNITED STATES"},
        },
        "award": None,
        "uiLink": "https://sam.gov/opp/abc123noticeid001/view?api_key=SHOULD_NOT_APPEAR",
    }
    base.update(overrides)
    return base


def _sam_physical_notice() -> dict[str, Any]:
    return {
        "noticeId": "phys999construction",
        "title": "Historic Office Renovation and Construction",
        "solicitationNumber": "47PF0018R0023",
        "fullParentPathName": "GENERAL SERVICES ADMINISTRATION.PUBLIC BUILDINGS SERVICE",
        "postedDate": "2026-09-01",
        "type": "Solicitation",
        "typeOfSetAside": None,
        "responseDeadLine": "2026-09-30T17:00:00-04:00",
        "naicsCode": "236220",
        "active": "Yes",
        "description": "On-site construction and renovation services only.",
        "placeOfPerformance": {
            "city": {"name": "Chicago"},
            "state": {"name": "Illinois"},
            "country": {"name": "UNITED STATES"},
        },
    }


def _sam_licensed_notice() -> dict[str, Any]:
    return {
        "noticeId": "lic888nursing",
        "title": "Administrative Support for Clinical Operations",
        "solicitationNumber": "VA-NURSE-26",
        "fullParentPathName": "DEPARTMENT OF VETERANS AFFAIRS",
        "postedDate": "2026-09-05",
        "type": "Solicitation",
        "responseDeadLine": "2026-10-01T17:00:00-04:00",
        "naicsCode": "561110",
        "active": "Yes",
        "description": (
            "Contractor must hold an active nursing license and RN license. "
            "In-person nursing and patient care on-site only. Security clearance required."
        ),
        "placeOfPerformance": {
            "city": {"name": "Minneapolis"},
            "state": {"name": "Minnesota"},
            "country": {"name": "UNITED STATES"},
        },
    }


@pytest.fixture(autouse=True)
def _reset(monkeypatch):
    reset_provider_health_for_tests()
    monkeypatch.setattr(
        "app.core.nova.v3.multi_source_discovery.live_flags",
        lambda: {"LIVE_DISCOVERY_ENABLED": True},
    )
    # Ensure tests never inherit a real key from the host environment.
    monkeypatch.delenv("SAM_GOV_API_KEY", raising=False)
    yield
    reset_provider_health_for_tests()


def test_api_key_missing_reports_provider_unavailable(monkeypatch) -> None:
    assert sam_gov_key_configured() is False
    with pytest.raises(SamGovUnavailable) as exc:
        SamGovLiveProvider().search("administrative support", limit=5)
    assert "unavailable" in str(exc.value).lower()
    assert "missing" in str(exc.value).lower()
    assert FAKE_KEY not in str(exc.value)

    catalog = {row["provider_id"]: row for row in provider_catalog()}
    assert catalog["sam_gov"]["access_status"] == "api_key_missing"
    assert catalog["sam_gov"]["supports_external_submission"] is False


def test_successful_read_only_parsing(monkeypatch) -> None:
    monkeypatch.setenv("SAM_GOV_API_KEY", FAKE_KEY)
    assert sam_gov_key_configured() is True

    class _Resp:
        status_code = 200

        def raise_for_status(self):
            return None

        def json(self):
            return {
                "totalRecords": 2,
                "opportunitiesData": [_sam_admin_notice(), _sam_physical_notice()],
            }

    captured: dict[str, Any] = {}

    class _Client:
        def __init__(self, *a, **k):
            pass

        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

        def get(self, url, params=None, headers=None):
            captured["url"] = url
            captured["params"] = dict(params or {})
            captured["headers"] = dict(headers or {})
            return _Resp()

    monkeypatch.setattr(
        "app.core.nova.v3.multi_source_discovery.httpx.Client",
        _Client,
    )
    rows = SamGovLiveProvider().search("administrative support document preparation", limit=10)
    assert len(rows) == 1
    row = rows[0]
    assert row["provider_id"] == "sam_gov"
    assert row["provider_type"] == "government_contracting"
    assert row["notice_id"] == "abc123noticeid001"
    assert row["provider_identifier"] == "abc123noticeid001"
    assert row["solicitation_number"] == "fort-admin-26-001"
    assert "COMMERCE" in (row["agency"] or "").upper()
    assert row["title"].lower().startswith("remote administrative")
    assert "document preparation" in row["description"].lower() or "administrative" in row["description"].lower()
    assert row["response_deadline"]
    assert row["place_of_performance"]
    assert row["set_aside"]
    assert row["source_url"] == "https://sam.gov/opp/abc123noticeid001/view"
    assert FAKE_KEY not in row["source_url"]
    assert FAKE_KEY not in row["description"]
    assert FAKE_KEY not in str(row.get("raw_source_metadata"))
    assert "api_key=" not in row["source_url"]
    assert captured["url"] == SamGovLiveProvider.API_URL
    assert captured["params"].get("api_key") == FAKE_KEY  # used for request only
    # Remotive/RemoteOK still present and unchanged as live providers.
    ids = {p.meta.provider_id for p in live_providers()}
    assert {"remotive", "remoteok", "sam_gov"} <= ids


def test_deduplication_by_notice_id() -> None:
    a = normalize_opportunity(
        provider_id="sam_gov",
        provider_type="government_contracting",
        provider_identifier="notice-dup-1",
        notice_id="notice-dup-1",
        source_url="https://sam.gov/opp/notice-dup-1/view",
        title="Administrative Support Services",
        company_name="DEPARTMENT OF ENERGY",
        agency="DEPARTMENT OF ENERGY",
        description="Remote administrative support and reporting.",
    )
    b = normalize_opportunity(
        provider_id="sam_gov",
        provider_type="government_contracting",
        provider_identifier="notice-dup-1",
        notice_id="notice-dup-1",
        source_url="https://sam.gov/opp/notice-dup-1/view?version=2",
        title="Administrative Support Services (Amendment)",
        company_name="DEPARTMENT OF ENERGY",
        agency="DEPARTMENT OF ENERGY",
        description="Remote administrative support and reporting amendment.",
    )
    assert opportunity_dedupe_key(a) == opportunity_dedupe_key(b)
    assert opportunity_dedupe_key(a).startswith("sam_notice:")
    deduped = dedupe_opportunities([a, b])
    assert len(deduped) == 1
    assert deduped[0]["notice_id"] == "notice-dup-1"


def test_capability_qualification_accepts_digital_admin() -> None:
    job = normalize_opportunity(
        provider_id="sam_gov",
        provider_type="government_contracting",
        provider_identifier="cap-ok-1",
        notice_id="cap-ok-1",
        source_name="SAM.gov",
        source_attribution="SAM.gov",
        source_url="https://sam.gov/opp/cap-ok-1/view",
        title="Remote Administrative Support and Spreadsheet Cleanup",
        company_name="DEPARTMENT OF COMMERCE",
        agency="DEPARTMENT OF COMMERCE",
        solicitation_number="DOC-ADMIN-001",
        description=(
            "Government contract solicitation for remote administrative support, "
            "document preparation, weekly reporting, spreadsheet cleanup, and "
            "data reconciliation. Independent contractor / vendor welcome. "
            "AI tools allowed. Clear statement of work. No membership fee. "
            "Compensation $25,000 award estimated."
        ),
        compensation_text="$25,000 award",
        contract_type="government_contract",
        job_type="contract",
        remote_status="remote",
        geography="Remote, Nationwide, UNITED STATES",
        place_of_performance="Remote, Nationwide, UNITED STATES",
        set_aside="Total Small Business Set-Aside (FAR 19.5)",
        response_deadline="2026-10-15T17:00:00-04:00",
        fee_required="no",
    )
    qual = qualify_live_job(job)
    assert qual["qualification_outcome"] == OUTCOME_QUALIFIED
    assert qual["qualification_status"] == OUTCOME_QUALIFIED


def test_physical_licensed_specialist_rejected() -> None:
    physical = normalize_opportunity(
        provider_id="sam_gov",
        provider_type="government_contracting",
        provider_identifier="phys-1",
        notice_id="phys-1",
        source_url="https://sam.gov/opp/phys-1/view",
        title="On-site Facility Maintenance Electrician",
        company_name="GENERAL SERVICES ADMINISTRATION",
        agency="GENERAL SERVICES ADMINISTRATION",
        description=(
            "Must be on-site only. Licensed electrician on site required. "
            "Physical labor and facility maintenance. PE license required."
        ),
        job_type="contract",
        remote_status="on-site",
        geography="Chicago, Illinois",
        place_of_performance="Chicago, Illinois, UNITED STATES",
    )
    licensed = normalize_opportunity(
        provider_id="sam_gov",
        provider_type="government_contracting",
        provider_identifier="lic-1",
        notice_id="lic-1",
        source_url="https://sam.gov/opp/lic-1/view",
        title="Clinical Administrative Support",
        company_name="DEPARTMENT OF VETERANS AFFAIRS",
        agency="DEPARTMENT OF VETERANS AFFAIRS",
        description=(
            "Active nursing license and RN license required. "
            "In-person nursing and patient care. Security clearance required."
        ),
        job_type="contract",
        geography="Minneapolis, Minnesota",
    )
    specialist = normalize_opportunity(
        provider_id="sam_gov",
        provider_type="government_contracting",
        provider_identifier="spec-1",
        notice_id="spec-1",
        source_url="https://sam.gov/opp/spec-1/view",
        title="Lead Product Designer",
        company_name="DEPARTMENT OF DEFENSE",
        agency="DEPARTMENT OF DEFENSE",
        description="Seeking a senior product designer for UX/UI design system work.",
        job_type="contract",
    )
    for job in (physical, licensed, specialist):
        qual = qualify_live_job(job)
        assert qual["qualification_outcome"] == OUTCOME_NOT_QUALIFIED, job["title"]
        assert qual["qualification_status"] == OUTCOME_NOT_QUALIFIED


def test_provider_failure_isolation_preserves_other_sources(monkeypatch) -> None:
    monkeypatch.delenv("SAM_GOV_API_KEY", raising=False)
    remotive = _StubProvider(
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
        [
            normalize_opportunity(
                provider_id="remotive",
                provider_type="remote_contract_feed",
                provider_identifier="r-ok",
                source_url="https://remotive.com/remote-jobs/r-ok",
                title="Remote Spreadsheet Cleanup Contract",
                company_name="Data Co",
                description="Freelance spreadsheet cleanup and reporting.",
                remote_status="remote",
                job_type="contract",
            )
        ],
    )
    remoteok = _StubProvider(
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
        [
            normalize_opportunity(
                provider_id="remoteok",
                provider_type="remote_contract_feed",
                provider_identifier="rok-ok",
                source_url="https://remoteok.com/remote-jobs/rok-ok",
                title="Document Preparation Contractor",
                company_name="Docs LLC",
                description="Remote document preparation contractor project.",
                remote_status="remote",
                job_type="contract",
            )
        ],
    )
    sam = _StubProvider(
        ProviderMeta(
            provider_id="sam_gov",
            label="SAM.gov",
            provider_type="government_contracting",
            enabled=True,
            access_status="api_key_missing",
            access_mode="api",
            requires_login=False,
            requires_fee=False,
            supports_detail_fetch=False,
            supports_external_submission=False,
            terms_safety_notes="test",
            priority=35,
        ),
        [],
        fail=True,
        fail_exc=SamGovUnavailable("provider unavailable: SAM_GOV_API_KEY missing from environment"),
    )
    result = search_multi_source_jobs(
        "spreadsheet",
        limit=10,
        providers_override=[remotive, remoteok, sam],
    )
    assert result["count"] == 2
    assert {row["provider_id"] for row in result["jobs"]} == {"remotive", "remoteok"}
    assert any(err["provider_id"] == "sam_gov" for err in result["provider_errors"])
    assert all(FAKE_KEY not in err["error"] for err in result["provider_errors"])
    health = {row["provider_id"]: row for row in result["provider_health"]}
    assert health["sam_gov"]["status"] == "error"
    assert health["remotive"]["status"] == "ok"
    assert health["remoteok"]["status"] == "ok"
    assert result["external_submission"] is False
    assert result["financial_execution"] is False
    assert result["read_only"] is True


def test_expired_key_isolated_and_redacted(monkeypatch) -> None:
    monkeypatch.setenv("SAM_GOV_API_KEY", FAKE_KEY)

    class _Resp:
        status_code = 401

        def raise_for_status(self):
            raise AssertionError("should not raise_for_status on 401 path")

        def json(self):
            return {}

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
    with pytest.raises(SamGovUnavailable) as exc:
        SamGovLiveProvider().search("reporting", limit=3)
    msg = str(exc.value)
    assert "unavailable" in msg.lower()
    assert FAKE_KEY not in msg


def test_safety_rails_remain_off() -> None:
    guards = engine_guardrails()
    flags = live_flags()
    assert flags["EXTERNAL_SUBMISSION_ENABLED"] is False
    assert flags["FINANCIAL_EXECUTION_ENABLED"] is False
    assert flags["REAL_FINANCIAL_EXECUTION"] is False
    assert guards.get("EXTERNAL_SUBMISSION_ENABLED") is False or guards.get("EXTERNAL_SUBMISSION") is False
    sam = next(p for p in live_providers() if p.meta.provider_id == "sam_gov")
    assert sam.meta.supports_external_submission is False
    assert "sam_gov" not in {p.meta.provider_id for p in PENDING_PROVIDERS}
    assert isinstance(live_providers()[0], RemotiveLiveProvider) or any(
        isinstance(p, RemotiveLiveProvider) for p in live_providers()
    )
    assert any(isinstance(p, RemoteOkLiveProvider) for p in live_providers())



def test_sam_title_search_uses_procurement_friendly_terms() -> None:
    provider = SamGovLiveProvider()
    assert provider._title_search_term("AI workflow automation project contractor") == "workflow"
    assert provider._title_search_term("spreadsheet cleanup freelance project") == "data support"
    assert provider._title_search_term("RFP proposal support contractor remote") == "proposal support"
    assert provider._title_search_term("business research freelance project") == "research support"


def test_find_exact_fetches_notice_description(monkeypatch) -> None:
    monkeypatch.setenv("SAM_GOV_API_KEY", FAKE_KEY)

    class _Resp:
        status_code = 200
        headers = {"content-type": "application/json"}

        def __init__(self, payload):
            self._payload = payload
            self.text = ""

        def raise_for_status(self):
            return None

        def json(self):
            return self._payload

    calls = []

    class _Client:
        def __init__(self, *a, **k):
            pass

        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

        def get(self, url, params=None, headers=None):
            calls.append((url, dict(params or {})))
            if "noticedesc" in url:
                return _Resp({"description": "<p>Contractor shall provide administrative operations support, document control, recurring reports, scheduling support, data reconciliation, and workflow documentation.</p>"})
            return _Resp({"totalRecords": 1, "opportunitiesData": [_sam_admin_notice()]})

    monkeypatch.setattr("app.core.nova.v3.multi_source_discovery.httpx.Client", _Client)
    row = SamGovLiveProvider().find_exact("fort-admin-26-001")
    assert row is not None
    assert "document control" in row["description"].lower()
    assert "data reconciliation" in row["description"].lower()
    assert row["raw_source_metadata"]["description_fetched"] is True
    assert FAKE_KEY not in row["description"]
    assert any("noticedesc" in url for url, _ in calls)
    assert all(params.get("api_key") == FAKE_KEY for url, params in calls if "noticedesc" in url)


def test_find_exact_description_failure_keeps_notice(monkeypatch) -> None:
    monkeypatch.setenv("SAM_GOV_API_KEY", FAKE_KEY)

    class _Resp:
        headers = {"content-type": "application/json"}

        def __init__(self, payload=None, status_code=200, fail=False):
            self._payload = payload or {}
            self.status_code = status_code
            self._fail = fail
            self.text = ""

        def raise_for_status(self):
            if self._fail:
                raise RuntimeError("upstream description unavailable")

        def json(self):
            return self._payload

    class _Client:
        def __init__(self, *a, **k):
            pass

        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

        def get(self, url, params=None, headers=None):
            if "noticedesc" in url:
                return _Resp(fail=True)
            return _Resp({"totalRecords": 1, "opportunitiesData": [_sam_admin_notice()]})

    monkeypatch.setattr("app.core.nova.v3.multi_source_discovery.httpx.Client", _Client)
    row = SamGovLiveProvider().find_exact("fort-admin-26-001")
    assert row is not None
    assert row["title"]
    assert row["source_url"].startswith("https://sam.gov/opp/")



def test_exact_lookup_enriches_from_sam_supporting_pws_when_notice_desc_is_thin(monkeypatch) -> None:
    monkeypatch.setenv("SAM_GOV_API_KEY", FAKE_KEY)
    notice = _sam_admin_notice(
        noticeId="amendment-with-pws-001",
        solicitationNumber="W911SF26RA009",
        title="Amendment 4 - Business Operations Support Services",
        description="https://api.sam.gov/opportunities/v1/noticedesc?noticeid=amendment-with-pws-001",
        resourceLinks=[
            "https://sam.gov/api/prod/opps/v3/opportunities/resources/files/pws-business-operations.pdf"
        ],
    )

    class _Headers(dict):
        pass

    class _Resp:
        def __init__(self, *, payload=None, text="", content=b"", content_type="application/json", disposition=""):
            self.status_code = 200
            self._payload = payload
            self.text = text
            self.content = content
            self.headers = _Headers({
                "content-type": content_type,
                "content-disposition": disposition,
            })

        def raise_for_status(self):
            return None

        def json(self):
            return self._payload

    class _Page:
        def extract_text(self):
            return (
                "Performance Work Statement. Contractor shall provide administrative "
                "operations support, meeting summaries, document control, recurring "
                "reports, workflow documentation, and data reconciliation deliverables."
            )

    class _Reader:
        def __init__(self, stream):
            self.pages = [_Page()]

    monkeypatch.setattr(
        "app.core.nova.v3.multi_source_discovery.PdfReader",
        _Reader,
    )

    class _Client:
        def __init__(self, *a, **k):
            pass

        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

        def get(self, url, params=None, headers=None):
            if "opportunities/v2/search" in url:
                return _Resp(payload={"opportunitiesData": [notice]})
            if "noticedesc" in url:
                return _Resp(
                    payload={"description": "Amendment 4 updates proposal dates. See attached PWS."},
                )
            if "pws-business-operations.pdf" in url:
                return _Resp(
                    content=b"%PDF-stub",
                    content_type="application/pdf",
                    disposition='attachment; filename="PWS Business Operations.pdf"',
                )
            raise AssertionError(f"unexpected URL: {url}")

    monkeypatch.setattr(
        "app.core.nova.v3.multi_source_discovery.httpx.Client",
        _Client,
    )

    row = SamGovLiveProvider().find_exact("W911SF26RA009")
    assert row is not None
    description = row["description"].lower()
    assert "contractor shall provide administrative operations support" in description
    assert "document control" in description
    assert "data reconciliation" in description
    assert row["raw_source_metadata"]["description_fetched"] is True
    assert row["raw_source_metadata"]["supporting_resource_fetched"] is True
    qualification = qualify_live_job(row)
    assert qualification["capability_classification"] != "INSUFFICIENT_INFORMATION"
    assert "requirements_or_skills" not in list(qualification.get("missing_requirements") or [])



def test_exact_lookup_reads_structured_sam_resource_link_object(monkeypatch) -> None:
    """SAM may return attachment references as objects, not bare URL strings."""
    monkeypatch.setenv("SAM_GOV_API_KEY", FAKE_KEY)
    notice = _sam_admin_notice(
        noticeId="structured-resource-link-001",
        solicitationNumber="W911SF26RA009",
        title="Amendment 4 - Business Operations Support Services",
        description="https://api.sam.gov/opportunities/v1/noticedesc?noticeid=structured-resource-link-001",
        resourceLinks=[
            {
                "url": "https://sam.gov/api/prod/opps/v3/opportunities/resources/files/pws-structured.pdf",
                "name": "Performance Work Statement.pdf",
            }
        ],
    )

    class _Resp:
        def __init__(self, *, payload=None, content=b"", content_type="application/json", disposition=""):
            self.status_code = 200
            self._payload = payload
            self.content = content
            self.text = ""
            self.headers = {
                "content-type": content_type,
                "content-disposition": disposition,
            }

        def raise_for_status(self):
            return None

        def json(self):
            return self._payload

    class _Page:
        def extract_text(self):
            return (
                "Performance Work Statement. Contractor shall provide business operations "
                "support, administrative workflow management, recurring reports, document "
                "control, meeting summaries, and data reconciliation."
            )

    class _Reader:
        def __init__(self, stream):
            self.pages = [_Page()]

    monkeypatch.setattr("app.core.nova.v3.multi_source_discovery.PdfReader", _Reader)

    class _Client:
        def __init__(self, *a, **k):
            pass
        def __enter__(self):
            return self
        def __exit__(self, *a):
            return False
        def get(self, url, params=None, headers=None):
            if "opportunities/v2/search" in url:
                return _Resp(payload={"opportunitiesData": [notice]})
            if "noticedesc" in url:
                return _Resp(payload={"description": "Amendment 4. See attached PWS for requirements."})
            if "pws-structured.pdf" in url:
                return _Resp(
                    content=b"%PDF-structured-stub",
                    content_type="application/pdf",
                    disposition='attachment; filename="Performance Work Statement.pdf"',
                )
            raise AssertionError(f"unexpected URL: {url}")

    monkeypatch.setattr("app.core.nova.v3.multi_source_discovery.httpx.Client", _Client)

    row = SamGovLiveProvider().find_exact("W911SF26RA009")
    assert row is not None
    assert row["raw_source_metadata"]["resource_link_objects"][0]["name"] == "Performance Work Statement.pdf"
    assert row["raw_source_metadata"]["supporting_resource_fetched"] is True
    assert "business operations support" in row["description"].lower()
    qualification = qualify_live_job(row)
    assert qualification["capability_classification"] != "INSUFFICIENT_INFORMATION"
    assert "requirements_or_skills" not in list(qualification.get("missing_requirements") or [])
