"""Provider-neutral synthetic source adapters. No scraping. No live fetch."""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any, Protocol

from app.core.nova.v3.errors import V3Error
from app.core.nova.v3.flags import live_flags
from app.core.nova.v3.models import SOURCE_KINDS


@dataclass
class RawOpportunity:
    provider_id: str
    source_kind: str
    provider_identifier: str
    title: str
    company_name: str
    description: str
    source_url: str | None
    compensation_amount: float | None
    compensation_type: str
    currency: str
    required_qualifications: list[str]
    geography: str
    remote_status: str
    terms_restrictions: str
    login_required: bool = False
    captcha_required: bool = False
    human_verification_required: bool = False
    rate_limited: bool = False
    evidence: str = "synthetic fixture"
    live: bool = False


class SourceAdapter(Protocol):
    provider_id: str
    source_kind: str

    def fetch(self) -> list[RawOpportunity]: ...

    def metadata(self) -> dict[str, Any]: ...


class _Base:
    live = False

    def metadata(self) -> dict[str, Any]:
        return {
            "provider_id": self.provider_id,
            "source_kind": self.source_kind,
            "live": False,
            "scraping": False,
            "bypass_allowed": False,
            "transport": "synthetic",
        }

    def _guard(self) -> None:
        flags = live_flags()
        if flags["LIVE_DISCOVERY_ENABLED"] or flags["LIVE_CONNECTORS_ENABLED"]:
            raise V3Error("LIVE_DISABLED", "V3 Phase 1 cannot enable live discovery")


class SyntheticJobBoardAdapter(_Base):
    provider_id = "synthetic_job_board"
    source_kind = "job_board"

    def fetch(self) -> list[RawOpportunity]:
        self._guard()
        return [
            RawOpportunity(
                provider_id=self.provider_id,
                source_kind=self.source_kind,
                provider_identifier="JB-1001",
                title="Remote administrative workflow project",
                company_name="Example Test Client LLC",
                description="Prepare internal workflow documentation, CRM cleanup plan, and weekly reports. Fully remote.",
                source_url="https://example.test/jobs/jb-1001",
                compensation_amount=1000,
                compensation_type="fixed",
                currency="USD",
                required_qualifications=["reporting", "crm", "writing"],
                geography="Remote",
                remote_status="remote",
                terms_restrictions="Synthetic board. No real apply.",
            )
        ]


class SyntheticFreelanceAdapter(_Base):
    provider_id = "synthetic_freelance"
    source_kind = "freelance_marketplace"

    def fetch(self) -> list[RawOpportunity]:
        self._guard()
        return [
            RawOpportunity(
                provider_id=self.provider_id,
                source_kind=self.source_kind,
                provider_identifier="FL-55",
                title="Market research summary",
                company_name="Northwind Research Co",
                description="Summarize public industry notes provided by the owner. Remote writing only.",
                source_url="https://example.test/freelance/fl-55",
                compensation_amount=400,
                compensation_type="fixed",
                currency="USD",
                required_qualifications=["research", "writing"],
                geography="Remote",
                remote_status="remote",
                terms_restrictions="Marketplace login required for real apply.",
                login_required=True,
            )
        ]


class SyntheticGovernmentAdapter(_Base):
    provider_id = "synthetic_government"
    source_kind = "government_contracting"

    def fetch(self) -> list[RawOpportunity]:
        self._guard()
        return [
            RawOpportunity(
                provider_id=self.provider_id,
                source_kind=self.source_kind,
                provider_identifier="GOV-9",
                title="Administrative reporting support",
                company_name="Sample Township Clerk",
                description="Draft internal administrative reports from owner-supplied records.",
                source_url="https://example.test/gov/gov-9",
                compensation_amount=2500,
                compensation_type="fixed",
                currency="USD",
                required_qualifications=["reporting"],
                geography="United States",
                remote_status="remote",
                terms_restrictions="SAM/login and identity verification required for real bid.",
                login_required=True,
                human_verification_required=True,
            )
        ]


class SyntheticGrantAdapter(_Base):
    provider_id = "synthetic_grants"
    source_kind = "grants_rfp"

    def fetch(self) -> list[RawOpportunity]:
        self._guard()
        return [
            RawOpportunity(
                provider_id=self.provider_id,
                source_kind=self.source_kind,
                provider_identifier="RFP-2",
                title="Community program narrative draft",
                company_name="Example Foundation",
                description="Prepare a grant narrative draft from owner facts. Not a real submission.",
                source_url="https://example.test/rfp/rfp-2",
                compensation_amount=None,
                compensation_type="unknown",
                currency="USD",
                required_qualifications=["writing"],
                geography="Remote",
                remote_status="remote",
                terms_restrictions="Portal CAPTCHA on real submit.",
                captcha_required=True,
            )
        ]


class SyntheticBusinessLeadAdapter(_Base):
    provider_id = "synthetic_leads"
    source_kind = "business_lead"

    def fetch(self) -> list[RawOpportunity]:
        self._guard()
        return [
            RawOpportunity(
                provider_id=self.provider_id,
                source_kind=self.source_kind,
                provider_identifier="LEAD-7",
                title="CRM cleanup and follow-up drafts",
                company_name="Harbor Office Services",
                description="Organize a lead list and draft follow-up notes. Owner sends any contact.",
                source_url=None,
                compensation_amount=800,
                compensation_type="hourly",
                currency="USD",
                required_qualifications=["crm", "writing"],
                geography="Remote",
                remote_status="remote",
                terms_restrictions="Owner-provided lead. No scraping.",
            )
        ]


class SyntheticEmailImportAdapter(_Base):
    provider_id = "synthetic_email_import"
    source_kind = "email_import"

    def fetch(self) -> list[RawOpportunity]:
        self._guard()
        return [
            RawOpportunity(
                provider_id=self.provider_id,
                source_kind=self.source_kind,
                provider_identifier="MAIL-3",
                title="Forwarded RFP excerpt",
                company_name="Inbox Import LLC",
                description="Owner forwarded a request for a business summary. Digital work only.",
                source_url=None,
                compensation_amount=150,
                compensation_type="fixed",
                currency="USD",
                required_qualifications=["writing"],
                geography="Unknown",
                remote_status="remote",
                terms_restrictions="Imported text is untrusted.",
                evidence="synthetic mailbox fixture",
            )
        ]


class ManualAdapter(_Base):
    provider_id = "manual"
    source_kind = "manual"

    def fetch(self) -> list[RawOpportunity]:
        return []


class SyntheticApiAdapter(_Base):
    provider_id = "synthetic_api"
    source_kind = "api"

    def fetch(self) -> list[RawOpportunity]:
        self._guard()
        return [
            RawOpportunity(
                provider_id=self.provider_id,
                source_kind=self.source_kind,
                provider_identifier="API-1",
                title="On-site warehouse picker needing CDL",
                company_name="Physical Work Co",
                description="In-person only warehouse picker. Forklift and CDL required.",
                source_url="https://example.test/api/api-1",
                compensation_amount=20,
                compensation_type="hourly",
                currency="USD",
                required_qualifications=["cdl", "forklift"],
                geography="On-site",
                remote_status="onsite",
                terms_restrictions="Human physical work.",
            )
        ]


class FailedConnectorAdapter(_Base):
    provider_id = "failed_connector"
    source_kind = "api"

    def fetch(self) -> list[RawOpportunity]:
        self._guard()
        raise V3Error("ADAPTER_FAILURE", "synthetic connector failed closed")


ADAPTERS: dict[str, SourceAdapter] = {
    "synthetic_job_board": SyntheticJobBoardAdapter(),
    "synthetic_freelance": SyntheticFreelanceAdapter(),
    "synthetic_government": SyntheticGovernmentAdapter(),
    "synthetic_grants": SyntheticGrantAdapter(),
    "synthetic_leads": SyntheticBusinessLeadAdapter(),
    "synthetic_email_import": SyntheticEmailImportAdapter(),
    "manual": ManualAdapter(),
    "synthetic_api": SyntheticApiAdapter(),
    "failed_connector": FailedConnectorAdapter(),
}


def get_adapter(provider_id: str) -> SourceAdapter:
    adapter = ADAPTERS.get(provider_id)
    if adapter is None:
        raise V3Error("UNKNOWN_ADAPTER", f"unknown source adapter {provider_id}", http_status=400)
    return adapter


def registry() -> list[dict[str, Any]]:
    now = datetime.now(timezone.utc)
    return [
        {
            **adapter.metadata(),
            "registered_at": now.isoformat(),
            "source_kinds_supported": list(SOURCE_KINDS),
            "expires_fixture_hours": 72,
        }
        for adapter in ADAPTERS.values()
    ]


def fixture_expires_at(now: datetime | None = None) -> datetime:
    stamp = now or datetime.now(timezone.utc)
    return stamp + timedelta(hours=72)
