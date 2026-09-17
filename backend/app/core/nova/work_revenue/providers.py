"""Provider-based work finder. Phase 1: manual + simulated only. No scraping or live boards."""
from __future__ import annotations

from typing import Any, Protocol


class OpportunityProvider(Protocol):
    provider_id: str
    label: str
    phase1_enabled: bool

    def ingest(self, payload: dict[str, Any] | None = None) -> list[dict[str, Any]]:
        ...


class ManualProvider:
    provider_id = "manual"
    label = "Manual entry"
    phase1_enabled = True

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


class FutureApprovedApiProvider:
    provider_id = "approved_api"
    label = "Approved APIs"
    phase1_enabled = False

    def ingest(self, payload: dict[str, Any] | None = None) -> list[dict[str, Any]]:
        return []


class FutureCareerPageProvider:
    provider_id = "career_page"
    label = "Company career pages"
    phase1_enabled = False

    def ingest(self, payload: dict[str, Any] | None = None) -> list[dict[str, Any]]:
        return []


class FutureRfpProvider:
    provider_id = "rfp"
    label = "Contract / RFP sources"
    phase1_enabled = False

    def ingest(self, payload: dict[str, Any] | None = None) -> list[dict[str, Any]]:
        return []


class FutureFreelanceProvider:
    provider_id = "freelance_marketplace"
    label = "Approved freelance marketplaces"
    phase1_enabled = False

    def ingest(self, payload: dict[str, Any] | None = None) -> list[dict[str, Any]]:
        return []


PROVIDERS: dict[str, OpportunityProvider] = {
    "manual": ManualProvider(),
    "simulated": SimulatedProvider(),
    "approved_api": FutureApprovedApiProvider(),
    "career_page": FutureCareerPageProvider(),
    "rfp": FutureRfpProvider(),
    "freelance_marketplace": FutureFreelanceProvider(),
}


def list_providers() -> list[dict[str, Any]]:
    notes = {
        "manual": "Owner or operator enters an opportunity. No external fetch.",
        "simulated": "Local test/dev fixtures only. Never written as production job-board data.",
        "approved_api": "Not implemented in Phase 1.",
        "career_page": "Not implemented in Phase 1. No scraping.",
        "rfp": "Not implemented in Phase 1.",
        "freelance_marketplace": "Not implemented in Phase 1.",
    }
    return [
        {
            "provider_id": provider.provider_id,
            "label": provider.label,
            "phase1_enabled": provider.phase1_enabled,
            "notes": notes[provider.provider_id],
        }
        for provider in PROVIDERS.values()
    ]


def get_provider(provider_id: str) -> OpportunityProvider:
    provider = PROVIDERS.get(provider_id)
    if provider is None:
        raise KeyError(provider_id)
    return provider
