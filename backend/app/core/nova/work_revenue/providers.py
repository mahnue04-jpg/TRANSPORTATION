"""Provider-based work finder. Phase 1: manual + simulated only. No live scraping or submission."""
from __future__ import annotations

import hashlib
from typing import Any, Protocol

PROVIDER_FLAG_KEYS = (
    "DISCOVERY_SUPPORTED",
    "DETAIL_FETCH_SUPPORTED",
    "SUBMISSION_SUPPORTED",
    "OWNER_LOGIN_REQUIRED",
    "CAPTCHA_POSSIBLE",
    "IDENTITY_REQUIRED",
    "TERMS_RESTRICT_AUTOMATION",
    "MANUAL_ONLY",
)


def _flags(**overrides: bool) -> dict[str, bool]:
    flags = {
        "DISCOVERY_SUPPORTED": False,
        "DETAIL_FETCH_SUPPORTED": False,
        "SUBMISSION_SUPPORTED": False,
        "OWNER_LOGIN_REQUIRED": False,
        "CAPTCHA_POSSIBLE": False,
        "IDENTITY_REQUIRED": False,
        "TERMS_RESTRICT_AUTOMATION": True,
        "MANUAL_ONLY": True,
    }
    flags.update(overrides)
    return flags


def opportunity_fingerprint(
    *,
    organization_id: str,
    company_name: str,
    opportunity_title: str,
    source_url: str | None = None,
) -> str:
    key = "|".join(
        [
            (organization_id or "").strip().lower(),
            (company_name or "").strip().lower(),
            (opportunity_title or "").strip().lower(),
            (source_url or "").strip().lower(),
        ]
    )
    return hashlib.sha256(key.encode("utf-8")).hexdigest()[:40]


class OpportunityProvider(Protocol):
    provider_id: str
    label: str
    phase1_enabled: bool
    capabilities: dict[str, bool]

    def ingest(self, payload: dict[str, Any] | None = None) -> list[dict[str, Any]]:
        ...


class ManualProvider:
    provider_id = "manual"
    label = "Manual entry"
    phase1_enabled = True
    capabilities = _flags(DISCOVERY_SUPPORTED=True, MANUAL_ONLY=True, TERMS_RESTRICT_AUTOMATION=False)

    def ingest(self, payload: dict[str, Any] | None = None) -> list[dict[str, Any]]:
        if not payload:
            return []
        item = dict(payload)
        item["source"] = item.get("source") or "manual"
        item["source_type"] = item.get("source_type") or "manual"
        return [item]


class SimulatedProvider:
    provider_id = "simulated"
    label = "Simulated fixtures (tests / local development only)"
    phase1_enabled = True
    capabilities = _flags(DISCOVERY_SUPPORTED=True, MANUAL_ONLY=True)

    def ingest(self, payload: dict[str, Any] | None = None) -> list[dict[str, Any]]:
        from app.core.nova.work_revenue.fixtures import simulated_opportunities

        requested = (payload or {}).get("fixture_ids")
        rows = simulated_opportunities()
        if requested:
            allow = {str(item) for item in requested}
            rows = [row for row in rows if row.get("fixture_id") in allow]
        for row in rows:
            row["source"] = "simulated"
            row["source_type"] = "simulated"
        return rows


class _FutureProvider:
    phase1_enabled = False
    capabilities = _flags(MANUAL_ONLY=True, TERMS_RESTRICT_AUTOMATION=True)

    def ingest(self, payload: dict[str, Any] | None = None) -> list[dict[str, Any]]:
        return []


class FutureApprovedApiProvider(_FutureProvider):
    provider_id = "approved_api"
    label = "Approved APIs"
    capabilities = _flags(DISCOVERY_SUPPORTED=False, SUBMISSION_SUPPORTED=False, TERMS_RESTRICT_AUTOMATION=True)


class FutureCareerPageProvider(_FutureProvider):
    provider_id = "career_page"
    label = "Public career pages"
    capabilities = _flags(CAPTCHA_POSSIBLE=True, TERMS_RESTRICT_AUTOMATION=True, MANUAL_ONLY=True)


class FutureJobBoardProvider(_FutureProvider):
    provider_id = "job_board"
    label = "Approved job boards"
    capabilities = _flags(
        OWNER_LOGIN_REQUIRED=True,
        CAPTCHA_POSSIBLE=True,
        IDENTITY_REQUIRED=True,
        TERMS_RESTRICT_AUTOMATION=True,
        MANUAL_ONLY=True,
    )


class FutureFreelanceProvider(_FutureProvider):
    provider_id = "freelance_marketplace"
    label = "Freelance marketplaces"
    capabilities = _flags(
        OWNER_LOGIN_REQUIRED=True,
        CAPTCHA_POSSIBLE=True,
        IDENTITY_REQUIRED=True,
        TERMS_RESTRICT_AUTOMATION=True,
        MANUAL_ONLY=True,
    )


class FutureRfpProvider(_FutureProvider):
    provider_id = "rfp"
    label = "RFP / procurement portals"
    capabilities = _flags(OWNER_LOGIN_REQUIRED=True, TERMS_RESTRICT_AUTOMATION=True, MANUAL_ONLY=True)


class FutureVendorProvider(_FutureProvider):
    provider_id = "vendor"
    label = "Vendor / partner opportunities"
    capabilities = _flags(MANUAL_ONLY=True)


class FutureContractProvider(_FutureProvider):
    provider_id = "contract_work"
    label = "Contract work"
    capabilities = _flags(MANUAL_ONLY=True)


class FutureConsultingProvider(_FutureProvider):
    provider_id = "consulting"
    label = "Consulting opportunities"
    capabilities = _flags(MANUAL_ONLY=True)


class FutureGovernmentProvider(_FutureProvider):
    provider_id = "government_procurement"
    label = "Government procurement listings"
    capabilities = _flags(
        OWNER_LOGIN_REQUIRED=True,
        IDENTITY_REQUIRED=True,
        TERMS_RESTRICT_AUTOMATION=True,
        MANUAL_ONLY=True,
    )


class FutureSubcontractingProvider(_FutureProvider):
    provider_id = "small_business_subcontracting"
    label = "Small-business subcontracting"
    capabilities = _flags(OWNER_LOGIN_REQUIRED=True, TERMS_RESTRICT_AUTOMATION=True, MANUAL_ONLY=True)


PROVIDERS: dict[str, OpportunityProvider] = {
    "manual": ManualProvider(),
    "simulated": SimulatedProvider(),
    "approved_api": FutureApprovedApiProvider(),
    "career_page": FutureCareerPageProvider(),
    "job_board": FutureJobBoardProvider(),
    "freelance_marketplace": FutureFreelanceProvider(),
    "rfp": FutureRfpProvider(),
    "vendor": FutureVendorProvider(),
    "contract_work": FutureContractProvider(),
    "consulting": FutureConsultingProvider(),
    "government_procurement": FutureGovernmentProvider(),
    "small_business_subcontracting": FutureSubcontractingProvider(),
}

_NOTES = {
    "manual": "Owner or operator enters an opportunity. No external fetch.",
    "simulated": "Local test/dev fixtures only. Never written as production job-board data.",
    "approved_api": "Not implemented. Discovery and submission flags are false.",
    "career_page": "Not implemented. No scraping. CAPTCHA possible on future sources.",
    "job_board": "Not implemented. Owner login, CAPTCHA, and identity are likely.",
    "freelance_marketplace": "Not implemented. Submission is not supported.",
    "rfp": "Not implemented. Manual capture only.",
    "vendor": "Not implemented. Manual capture only.",
    "contract_work": "Not implemented. Manual capture only.",
    "consulting": "Not implemented. Manual capture only.",
    "government_procurement": "Not implemented. Identity and owner login likely required.",
    "small_business_subcontracting": "Not implemented. Manual capture only.",
}


def list_providers() -> list[dict[str, Any]]:
    return [
        {
            "provider_id": provider.provider_id,
            "label": provider.label,
            "phase1_enabled": provider.phase1_enabled,
            "notes": _NOTES[provider.provider_id],
            "capabilities": dict(provider.capabilities),
        }
        for provider in PROVIDERS.values()
    ]


def get_provider(provider_id: str) -> OpportunityProvider:
    provider = PROVIDERS.get(provider_id)
    if provider is None:
        raise KeyError(provider_id)
    return provider
