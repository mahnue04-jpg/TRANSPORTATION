"""Provider-neutral multi-source live discovery for Nova Work.

Combines enabled discovery providers, deduplicates results, isolates provider
failures, and preserves Remotive as one live source among others.

Never submits applications, contacts clients, accepts contracts, or moves money.
"""

from __future__ import annotations

import hashlib
import html
import os
import re
import time
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Any, Protocol

import httpx

from app.core.nova.v3.errors import V3Error
from app.core.nova.v3.flags import live_flags

PROVIDER_TYPES = (
    "freelance_marketplace",
    "government_contracting",
    "vendor_project_board",
    "career_page",
    "job_board",
    "public_rfp_feed",
    "remote_contract_feed",
)

# Preferred discovery order for Nova Work.
PROVIDER_TYPE_PRIORITY = {
    "freelance_marketplace": 10,
    "vendor_project_board": 20,
    "public_rfp_feed": 30,
    "government_contracting": 35,
    "remote_contract_feed": 40,
    "job_board": 50,
    "career_page": 60,
}


def _clean_html(value: str | None) -> str:
    text = html.unescape(str(value or ""))
    text = re.sub(r"<[^>]+>", " ", text)
    return re.sub(r"\s+", " ", text).strip()


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def normalize_opportunity(**kwargs: Any) -> dict[str, Any]:
    """Return a normalized multi-source opportunity record."""
    source_url = str(kwargs.get("source_url") or "").strip()
    title = str(kwargs.get("title") or "").strip()
    company = str(kwargs.get("company_name") or kwargs.get("client") or "").strip()
    provider_id = str(kwargs.get("provider_id") or "").strip()
    provider_identifier = str(kwargs.get("provider_identifier") or source_url or title).strip()
    simulated = bool(kwargs.get("simulated") or kwargs.get("real_or_simulated") == "SIMULATED")
    return {
        "provider_id": provider_id,
        "provider_type": str(kwargs.get("provider_type") or "job_board"),
        "provider_identifier": provider_identifier,
        "source_name": str(kwargs.get("source_name") or kwargs.get("source_attribution") or provider_id),
        "source_attribution": str(kwargs.get("source_attribution") or kwargs.get("source_name") or provider_id),
        "source_url": source_url,
        "title": title,
        "company_name": company,
        "client": company,
        "description": _clean_html(kwargs.get("description"))[:5000],
        "compensation_text": (str(kwargs.get("compensation_text")).strip() or None)
        if kwargs.get("compensation_text") is not None
        else None,
        "contract_type": kwargs.get("contract_type") or kwargs.get("job_type"),
        "job_type": kwargs.get("job_type") or kwargs.get("contract_type"),
        "remote_status": str(kwargs.get("remote_status") or "unknown"),
        "geography": str(kwargs.get("geography") or ""),
        "fee_required": str(kwargs.get("fee_required") or "unknown"),
        "application_url": source_url,
        "publication_date": kwargs.get("publication_date"),
        "raw_source_metadata": dict(kwargs.get("raw_source_metadata") or {}),
        "simulated": simulated,
        "real_or_simulated": "SIMULATED" if simulated else "REAL",
        "provenance_sources": list(kwargs.get("provenance_sources") or [provider_id]),
    }


def opportunity_dedupe_key(row: dict[str, Any]) -> str:
    url = str(row.get("source_url") or "").strip().lower()
    if url:
        return "url:" + url
    blob = "|".join(
        [
            str(row.get("company_name") or "").strip().lower(),
            str(row.get("title") or "").strip().lower(),
            str(row.get("provider_identifier") or "").strip().lower(),
        ]
    )
    return "hash:" + hashlib.sha256(blob.encode("utf-8")).hexdigest()[:24]


@dataclass
class ProviderHealth:
    provider_id: str
    enabled: bool
    reachable: bool | None = None
    last_success: str | None = None
    last_failure: str | None = None
    last_error: str | None = None
    result_count: int = 0
    source_type: str = "job_board"
    status: str = "unknown"

    def as_dict(self) -> dict[str, Any]:
        return {
            "provider_id": self.provider_id,
            "enabled": self.enabled,
            "reachable": self.reachable,
            "last_success": self.last_success,
            "last_failure": self.last_failure,
            "last_error": self.last_error,
            "result_count": self.result_count,
            "source_type": self.source_type,
            "status": self.status,
        }


@dataclass
class ProviderMeta:
    provider_id: str
    label: str
    provider_type: str
    enabled: bool
    access_status: str
    access_mode: str  # api | feed | page | pending
    requires_login: bool
    requires_fee: bool
    supports_detail_fetch: bool
    supports_external_submission: bool
    terms_safety_notes: str
    pending_requirements: str | None = None
    priority: int = 100


class LiveDiscoveryProvider(Protocol):
    meta: ProviderMeta

    def search(self, query: str, *, limit: int = 10) -> list[dict[str, Any]]:
        ...


_health: dict[str, ProviderHealth] = {}


def _record_success(provider_id: str, *, source_type: str, count: int) -> None:
    row = _health.get(provider_id) or ProviderHealth(provider_id=provider_id, enabled=True, source_type=source_type)
    row.enabled = True
    row.reachable = True
    row.last_success = _now_iso()
    row.result_count = count
    row.source_type = source_type
    row.status = "ok"
    row.last_error = None
    _health[provider_id] = row


def _record_failure(provider_id: str, *, source_type: str, error: str, enabled: bool = True) -> None:
    row = _health.get(provider_id) or ProviderHealth(provider_id=provider_id, enabled=enabled, source_type=source_type)
    row.enabled = enabled
    row.reachable = False if enabled else None
    row.last_failure = _now_iso()
    row.last_error = error[:300]
    row.source_type = source_type
    row.status = "error" if enabled else "pending"
    _health[provider_id] = row


class RemotiveLiveProvider:
    meta = ProviderMeta(
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
        terms_safety_notes="Public Remotive JSON API. Discovery-only. No auto-apply.",
        priority=PROVIDER_TYPE_PRIORITY["remote_contract_feed"],
    )
    API_URL = "https://remotive.com/api/remote-jobs"

    def search(self, query: str, *, limit: int = 10) -> list[dict[str, Any]]:
        capped = max(1, min(25, int(limit)))
        with httpx.Client(timeout=12.0, follow_redirects=True) as client:
            response = client.get(
                self.API_URL,
                params={"search": query, "limit": capped},
                headers={"User-Agent": "AMICOR-Nova/1.0 multi-source-discovery"},
            )
            response.raise_for_status()
            payload = response.json()
        out: list[dict[str, Any]] = []
        for raw in list(payload.get("jobs") or [])[:capped]:
            source_url = str(raw.get("url") or "").strip()
            title = str(raw.get("title") or "").strip()
            company = str(raw.get("company_name") or "").strip()
            if not source_url or not title or not company:
                continue
            out.append(
                normalize_opportunity(
                    provider_id="remotive",
                    provider_type="remote_contract_feed",
                    provider_identifier=str(raw.get("id") or source_url),
                    source_name="Remotive",
                    source_attribution="Remotive",
                    source_url=source_url,
                    title=title,
                    company_name=company,
                    description=_clean_html(raw.get("description"))[:5000],
                    compensation_text=(str(raw.get("salary")).strip() or None)
                    if raw.get("salary") is not None
                    else None,
                    contract_type=(str(raw.get("job_type")).strip() or None)
                    if raw.get("job_type") is not None
                    else None,
                    job_type=(str(raw.get("job_type")).strip() or None)
                    if raw.get("job_type") is not None
                    else None,
                    remote_status="remote",
                    geography=str(raw.get("candidate_required_location") or "Remote"),
                    fee_required="unknown",
                    publication_date=(str(raw.get("publication_date")).strip() or None)
                    if raw.get("publication_date") is not None
                    else None,
                    raw_source_metadata={"origin": "remotive"},
                    simulated=False,
                )
            )
        return out


class RemoteOkLiveProvider:
    """Public RemoteOK JSON feed. No API key. Discovery-only."""

    meta = ProviderMeta(
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
        terms_safety_notes=(
            "Uses the public RemoteOK /api JSON endpoint. Read-only discovery. "
            "No login bypass, no scraping of blocked pages, no auto-apply."
        ),
        priority=PROVIDER_TYPE_PRIORITY["remote_contract_feed"] + 1,
    )
    API_URL = "https://remoteok.com/api"

    def search(self, query: str, *, limit: int = 10) -> list[dict[str, Any]]:
        capped = max(1, min(25, int(limit)))
        with httpx.Client(timeout=12.0, follow_redirects=True) as client:
            response = client.get(
                self.API_URL,
                headers={"User-Agent": "AMICOR-Nova/1.0 multi-source-discovery"},
            )
            response.raise_for_status()
            payload = response.json()
        tokens = {t for t in re.findall(r"[a-z0-9]+", query.lower()) if len(t) > 2}
        scored: list[tuple[int, dict[str, Any]]] = []
        for raw in payload:
            if not isinstance(raw, dict) or not raw.get("id"):
                continue
            title = str(raw.get("position") or raw.get("title") or "").strip()
            company = str(raw.get("company") or "").strip()
            url = str(raw.get("url") or raw.get("apply_url") or "").strip()
            if not title or not company or not url:
                continue
            blob = " ".join(
                [
                    title,
                    company,
                    str(raw.get("description") or ""),
                    " ".join(str(t) for t in (raw.get("tags") or [])),
                ]
            ).lower()
            hits = sum(1 for token in tokens if token in blob)
            if tokens and hits == 0:
                continue
            job_type = "contract" if any(tag in {"contract", "freelance"} for tag in (raw.get("tags") or [])) else (
                str(raw.get("job_type") or "unknown")
            )
            row = normalize_opportunity(
                provider_id="remoteok",
                provider_type="remote_contract_feed",
                provider_identifier=str(raw.get("id")),
                source_name="RemoteOK",
                source_attribution="RemoteOK",
                source_url=url,
                title=title,
                company_name=company,
                description=_clean_html(raw.get("description"))[:5000],
                compensation_text=(str(raw.get("salary") or "").strip() or None),
                contract_type=job_type,
                job_type=job_type,
                remote_status="remote",
                geography=str(raw.get("location") or "Remote"),
                fee_required="no",
                publication_date=str(raw.get("date") or "") or None,
                raw_source_metadata={"tags": list(raw.get("tags") or []), "origin": "remoteok"},
                simulated=False,
            )
            scored.append((hits, row))
        scored.sort(key=lambda item: item[0], reverse=True)
        return [row for _, row in scored[:capped]]


class SamGovLiveProvider:
    """Official SAM.gov Contract Opportunities API. Discovery-only."""

    API_URL = "https://api.sam.gov/opportunities/v2/search"

    def __init__(self) -> None:
        self.api_key = (os.getenv("SAM_GOV_API_KEY") or "").strip()
        self.meta = ProviderMeta(
            provider_id="sam_gov",
            label="SAM.gov opportunities",
            provider_type="government_contracting",
            enabled=bool(self.api_key),
            access_status="public_api" if self.api_key else "pending_api_key",
            access_mode="api" if self.api_key else "pending",
            requires_login=False,
            requires_fee=False,
            supports_detail_fetch=True,
            supports_external_submission=False,
            terms_safety_notes=(
                "Official SAM.gov public Contract Opportunities API. Read-only discovery only; "
                "no bid, proposal, contract acceptance, or external submission."
            ),
            pending_requirements=None if self.api_key else "Set SAM_GOV_API_KEY from the owner's SAM.gov public API key.",
            priority=PROVIDER_TYPE_PRIORITY["government_contracting"],
        )

    @staticmethod
    def _search_terms(query: str) -> list[str]:
        generic = {
            "remote", "contract", "contractor", "support", "work", "project",
            "weekly", "cleanup", "preparation",
        }
        tokens = [
            token
            for token in re.findall(r"[a-z0-9]+", str(query or "").lower())
            if len(token) >= 4 and token not in generic
        ]
        preferred = [
            token for token in tokens
            if token in {
                "administrative", "spreadsheet", "reporting", "reconciliation",
                "research", "document", "records", "data", "operations",
                "analysis", "bookkeeping",
            }
        ]
        ordered = list(dict.fromkeys(preferred + tokens))
        return ordered[:4] or ["administrative"]

    def search(self, query: str, *, limit: int = 10) -> list[dict[str, Any]]:
        if not self.api_key:
            return []
        capped = max(1, min(25, int(limit)))
        today = datetime.now(timezone.utc).date()
        posted_from = today - timedelta(days=45)
        rows: list[dict[str, Any]] = []

        with httpx.Client(timeout=15.0, follow_redirects=True) as client:
            for term in self._search_terms(query):
                response = client.get(
                    self.API_URL,
                    params={
                        "api_key": self.api_key,
                        "postedFrom": posted_from.strftime("%m/%d/%Y"),
                        "postedTo": today.strftime("%m/%d/%Y"),
                        "limit": capped,
                        "offset": 0,
                        "title": term,
                    },
                    headers={"User-Agent": "AMICOR-Nova/1.0 multi-source-discovery"},
                )
                response.raise_for_status()
                payload = response.json()
                for raw in list(payload.get("opportunitiesData") or []):
                    notice_id = str(raw.get("noticeId") or "").strip()
                    title = str(raw.get("title") or "").strip()
                    if not notice_id or not title:
                        continue
                    office_path = str(raw.get("fullParentPathName") or raw.get("office") or "").strip()
                    solicitation = str(raw.get("solicitationNumber") or "").strip()
                    description = _clean_html(raw.get("description"))
                    place = raw.get("placeOfPerformance") or {}
                    if not isinstance(place, dict):
                        place = {}
                    country = place.get("country") or {}
                    if not isinstance(country, dict):
                        country = {}
                    geography = " ".join(
                        part for part in [
                            str(place.get("city") or "").strip(),
                            str(place.get("state") or "").strip(),
                            str(country.get("name") or country.get("code") or "").strip(),
                        ] if part
                    ).strip() or "United States / federal"
                    source_url = f"https://sam.gov/opp/{notice_id}/view"
                    rows.append(
                        normalize_opportunity(
                            provider_id="sam_gov",
                            provider_type="government_contracting",
                            provider_identifier=notice_id,
                            source_name="SAM.gov",
                            source_attribution="SAM.gov Contract Opportunities",
                            source_url=source_url,
                            title=title,
                            company_name=office_path or "U.S. Federal Government",
                            description=description or (
                                f"Federal contract opportunity {solicitation or notice_id}. "
                                "Review the official SAM.gov notice for scope, eligibility, and response requirements."
                            ),
                            compensation_text=None,
                            contract_type="government_contract",
                            job_type="government_contract",
                            remote_status="unknown",
                            geography=geography,
                            fee_required="no",
                            publication_date=(str(raw.get("postedDate")).strip() or None)
                            if raw.get("postedDate") is not None
                            else None,
                            raw_source_metadata={
                                "origin": "sam_gov",
                                "solicitation_number": solicitation or None,
                                "notice_type": raw.get("type") or raw.get("baseType"),
                                "naics_code": raw.get("naicsCode"),
                                "response_deadline": raw.get("responseDeadLine"),
                                "set_aside": raw.get("typeOfSetAsideDescription") or raw.get("typeOfSetAside"),
                            },
                            simulated=False,
                        )
                    )
                if len(dedupe_opportunities(rows)) >= capped:
                    break

        return dedupe_opportunities(rows)[:capped]


@dataclass
class PendingProvider:
    meta: ProviderMeta

    def search(self, query: str, *, limit: int = 10) -> list[dict[str, Any]]:
        return []


PENDING_PROVIDERS: list[PendingProvider] = [
    PendingProvider(
        ProviderMeta(
            provider_id="upwork",
            label="Upwork",
            provider_type="freelance_marketplace",
            enabled=False,
            access_status="pending_credentials_and_terms",
            access_mode="pending",
            requires_login=True,
            requires_fee=False,
            supports_detail_fetch=False,
            supports_external_submission=False,
            terms_safety_notes="Marketplace TOS typically forbid unattended scraping/auto-apply.",
            pending_requirements="Owner-approved Upwork API/OAuth credentials + written terms review before enablement.",
            priority=PROVIDER_TYPE_PRIORITY["freelance_marketplace"],
        )
    ),
    PendingProvider(
        ProviderMeta(
            provider_id="freelancer",
            label="Freelancer.com",
            provider_type="freelance_marketplace",
            enabled=False,
            access_status="pending_credentials_and_terms",
            access_mode="pending",
            requires_login=True,
            requires_fee=False,
            supports_detail_fetch=False,
            supports_external_submission=False,
            terms_safety_notes="API/terms review required. No scraping.",
            pending_requirements="Freelancer.com API key + owner terms approval.",
            priority=PROVIDER_TYPE_PRIORITY["freelance_marketplace"] + 1,
        )
    ),
    PendingProvider(
        ProviderMeta(
            provider_id="public_rfp_rss",
            label="Public RFP RSS feeds",
            provider_type="public_rfp_feed",
            enabled=False,
            access_status="pending_feed_allowlist",
            access_mode="pending",
            requires_login=False,
            requires_fee=False,
            supports_detail_fetch=False,
            supports_external_submission=False,
            terms_safety_notes="Only owner-approved public RSS/Atom feeds may be enabled.",
            pending_requirements="Owner-approved allowlist of public RFP feed URLs + robots/terms check per feed.",
            priority=PROVIDER_TYPE_PRIORITY["public_rfp_feed"],
        )
    ),
    PendingProvider(
        ProviderMeta(
            provider_id="vendor_project_board",
            label="Vendor project boards",
            provider_type="vendor_project_board",
            enabled=False,
            access_status="pending_source_selection",
            access_mode="pending",
            requires_login=True,
            requires_fee=False,
            supports_detail_fetch=False,
            supports_external_submission=False,
            terms_safety_notes="Partner/vendor boards often require login and forbid bots.",
            pending_requirements="Named vendor board + access method (API/feed) + terms approval.",
            priority=PROVIDER_TYPE_PRIORITY["vendor_project_board"],
        )
    ),
]


def live_providers() -> list[LiveDiscoveryProvider]:
    providers: list[LiveDiscoveryProvider] = [RemotiveLiveProvider(), RemoteOkLiveProvider()]
    sam = SamGovLiveProvider()
    if sam.meta.enabled:
        providers.append(sam)
    return providers


def all_provider_metas() -> list[ProviderMeta]:
    rows = [provider.meta for provider in live_providers()]
    if not any(meta.provider_id == "sam_gov" for meta in rows):
        rows.append(SamGovLiveProvider().meta)
    rows.extend(item.meta for item in PENDING_PROVIDERS)
    return sorted(rows, key=lambda item: (item.priority, item.provider_id))


def provider_catalog() -> list[dict[str, Any]]:
    out = []
    for meta in all_provider_metas():
        health = _health.get(meta.provider_id)
        out.append(
            {
                "provider_id": meta.provider_id,
                "label": meta.label,
                "provider_type": meta.provider_type,
                "enabled": meta.enabled,
                "access_status": meta.access_status,
                "access_mode": meta.access_mode,
                "requires_login": meta.requires_login,
                "requires_fee": meta.requires_fee,
                "supports_detail_fetch": meta.supports_detail_fetch,
                "supports_external_submission": False,
                "terms_safety_notes": meta.terms_safety_notes,
                "pending_requirements": meta.pending_requirements,
                "priority": meta.priority,
                "health": (health.as_dict() if health else {
                    "provider_id": meta.provider_id,
                    "enabled": meta.enabled,
                    "reachable": None,
                    "last_success": None,
                    "last_failure": None,
                    "last_error": None,
                    "result_count": 0,
                    "source_type": meta.provider_type,
                    "status": "pending" if not meta.enabled else "idle",
                }),
            }
        )
    return out


def provider_health_snapshot() -> list[dict[str, Any]]:
    return [row["health"] | {"label": row["label"], "provider_type": row["provider_type"]} for row in provider_catalog()]


def dedupe_opportunities(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    merged: dict[str, dict[str, Any]] = {}
    order: list[str] = []
    for row in rows:
        key = opportunity_dedupe_key(row)
        if key not in merged:
            item = dict(row)
            item["provenance_sources"] = list(dict.fromkeys(item.get("provenance_sources") or [row.get("provider_id")]))
            merged[key] = item
            order.append(key)
            continue
        existing = merged[key]
        sources = list(existing.get("provenance_sources") or [])
        pid = row.get("provider_id")
        if pid and pid not in sources:
            sources.append(pid)
        existing["provenance_sources"] = sources
        # Prefer richer description / compensation when duplicate collapses.
        if len(str(row.get("description") or "")) > len(str(existing.get("description") or "")):
            existing["description"] = row.get("description")
        if not existing.get("compensation_text") and row.get("compensation_text"):
            existing["compensation_text"] = row.get("compensation_text")
        existing["raw_source_metadata"] = {
            **dict(existing.get("raw_source_metadata") or {}),
            f"dup_{row.get('provider_id')}": dict(row.get("raw_source_metadata") or {}),
        }
    return [merged[key] for key in order]


def search_multi_source_jobs(
    query: str,
    *,
    limit: int = 10,
    provider_ids: list[str] | None = None,
    include_simulated: bool = False,
    providers_override: list[LiveDiscoveryProvider] | None = None,
) -> dict[str, Any]:
    """Query all enabled live providers. One failure does not stop the others."""
    if not live_flags()["LIVE_DISCOVERY_ENABLED"]:
        raise V3Error("LIVE_DISABLED", "Live discovery is not enabled", http_status=409)
    normalized = str(query or "").strip()
    if not normalized:
        raise V3Error("INVALID_QUERY", "Job search query is required", http_status=400)

    capped = max(1, min(25, int(limit)))
    providers = list(providers_override) if providers_override is not None else live_providers()
    if provider_ids:
        allow = {str(item) for item in provider_ids}
        providers = [p for p in providers if p.meta.provider_id in allow]
    providers = sorted(providers, key=lambda p: (p.meta.priority, p.meta.provider_id))

    collected: list[dict[str, Any]] = []
    errors: list[dict[str, Any]] = []
    per_provider: dict[str, int] = {}

    for provider in providers:
        meta = provider.meta
        if not meta.enabled:
            continue
        try:
            rows = provider.search(normalized, limit=capped)
            if not include_simulated:
                rows = [row for row in rows if not row.get("simulated")]
            per_provider[meta.provider_id] = len(rows)
            _record_success(meta.provider_id, source_type=meta.provider_type, count=len(rows))
            collected.extend(rows)
        except Exception as exc:  # noqa: BLE001 - isolate provider outages
            message = f"{type(exc).__name__}: {exc}"
            _record_failure(meta.provider_id, source_type=meta.provider_type, error=message)
            errors.append({"provider_id": meta.provider_id, "error": message[:300]})

    # Pending providers stay visible in diagnostics but never searched.
    for pending in PENDING_PROVIDERS:
        _health.setdefault(
            pending.meta.provider_id,
            ProviderHealth(
                provider_id=pending.meta.provider_id,
                enabled=False,
                source_type=pending.meta.provider_type,
                status="pending",
            ),
        )

    deduped = dedupe_opportunities(collected)[:capped]
    real_jobs = [row for row in deduped if not row.get("simulated")]
    return {
        "query": normalized,
        "count": len(deduped),
        "real_count": len(real_jobs),
        "simulated_count": len(deduped) - len(real_jobs),
        "jobs": deduped,
        "providers_queried": [p.meta.provider_id for p in providers if p.meta.enabled],
        "provider_result_counts": per_provider,
        "provider_errors": errors,
        "deduplicated": True,
        "read_only": True,
        "external_action_taken": False,
        "external_submission": False,
        "financial_execution": False,
        "provider_health": provider_health_snapshot(),
    }


def reset_provider_health_for_tests() -> None:
    _health.clear()
