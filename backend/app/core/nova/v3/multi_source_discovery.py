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
from io import BytesIO
from typing import Any, Protocol
from urllib.parse import parse_qsl, urlencode, urlparse, urlunparse

import httpx
from docx import Document
from pypdf import PdfReader

from app.core.nova.v3.errors import V3Error
from app.core.nova.v3.flags import live_flags

# Env-only. Never log, print, commit, or embed in user-facing URLs.
_SAM_GOV_API_KEY_ENV = "SAM_GOV_API_KEY"


class SamGovUnavailable(RuntimeError):
    """SAM.gov provider unavailable (missing/expired key or upstream auth failure)."""


def _sam_gov_api_key() -> str | None:
    key = str(os.environ.get(_SAM_GOV_API_KEY_ENV) or "").strip()
    return key or None


def _redact_secret(text: str, secret: str | None) -> str:
    """Strip a secret from any diagnostic string. Never return the raw key."""
    msg = str(text or "")
    if secret:
        msg = msg.replace(secret, "[REDACTED]")
    # Belt-and-suspenders for query-string leakage.
    msg = re.sub(r"(?i)(api_key=)[^&\s\"']+", r"\1[REDACTED]", msg)
    return msg


def sam_gov_key_configured() -> bool:
    return _sam_gov_api_key() is not None

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
    notice_id = (str(kwargs.get("notice_id")).strip() or None) if kwargs.get("notice_id") is not None else None
    solicitation_number = (
        (str(kwargs.get("solicitation_number")).strip() or None)
        if kwargs.get("solicitation_number") is not None
        else None
    )
    agency = (str(kwargs.get("agency")).strip() or None) if kwargs.get("agency") is not None else None
    response_deadline = (
        (str(kwargs.get("response_deadline")).strip() or None)
        if kwargs.get("response_deadline") is not None
        else None
    )
    place_of_performance = (
        (str(kwargs.get("place_of_performance")).strip() or None)
        if kwargs.get("place_of_performance") is not None
        else None
    )
    set_aside = (str(kwargs.get("set_aside")).strip() or None) if kwargs.get("set_aside") is not None else None
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
        "notice_id": notice_id,
        "solicitation_number": solicitation_number,
        "agency": agency,
        "response_deadline": response_deadline,
        "place_of_performance": place_of_performance,
        "set_aside": set_aside,
        "raw_source_metadata": dict(kwargs.get("raw_source_metadata") or {}),
        "simulated": simulated,
        "real_or_simulated": "SIMULATED" if simulated else "REAL",
        "provenance_sources": list(kwargs.get("provenance_sources") or [provider_id]),
    }


_TRACKING_QUERY_KEYS = {
    "ref", "referrer", "source", "src", "campaign", "campaign_id",
    "fbclid", "gclid", "mc_cid", "mc_eid",
}


def _canonical_source_url(value: str) -> str:
    """Normalize harmless URL variation so repeated listings collapse."""
    raw = str(value or "").strip()
    if not raw:
        return ""
    try:
        parsed = urlparse(raw)
    except Exception:
        return raw.lower()
    host = str(parsed.hostname or "").lower()
    if not host:
        return raw.lower()
    port = parsed.port
    netloc = host
    if port and not ((parsed.scheme.lower() == "https" and port == 443) or (parsed.scheme.lower() == "http" and port == 80)):
        netloc = f"{host}:{port}"
    path = re.sub(r"/+", "/", parsed.path or "/")
    if path != "/":
        path = path.rstrip("/")
    query = [
        (key, val)
        for key, val in parse_qsl(parsed.query, keep_blank_values=True)
        if not key.lower().startswith("utm_") and key.lower() not in _TRACKING_QUERY_KEYS
    ]
    return urlunparse((parsed.scheme.lower() or "https", netloc, path, "", urlencode(sorted(query)), ""))


def _identity_text(value: Any) -> str:
    return re.sub(r"[^a-z0-9]+", " ", str(value or "").lower()).strip()


def opportunity_dedupe_key(row: dict[str, Any]) -> str:
    provider = str(row.get("provider_id") or "").strip().lower()
    identifier = str(row.get("notice_id") or row.get("provider_identifier") or "").strip().lower()
    # SAM notice IDs are canonical across notice URL variants.
    if provider == "sam_gov" and identifier:
        return "sam_notice:" + identifier

    # A canonical public URL is stronger for cross-provider duplicates: the same
    # listing can be syndicated by more than one feed with different provider IDs.
    url = _canonical_source_url(str(row.get("source_url") or ""))
    if url:
        return "url:" + url

    # Fall back to provider identity when no actionable URL exists.
    if provider and identifier:
        return f"provider:{provider}:{identifier}"

    # Last-resort identity intentionally ignores provider so the same buyer/title
    # found through two feeds does not appear twice.
    blob = "|".join(
        [
            _identity_text(row.get("company_name") or row.get("client")),
            _identity_text(row.get("title")),
        ]
    )
    return "identity:" + hashlib.sha256(blob.encode("utf-8")).hexdigest()[:24]


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




_MN_OSP_PAGE_URLS = (
    ("mn_osp_pt", "Minnesota OSP Professional/Technical", "https://osp.admin.mn.gov/PT-auto"),
    ("mn_osp_gs", "Minnesota OSP Goods/Services", "https://osp.admin.mn.gov/GS-auto"),
)
_MN_OSP_IGNORE_QUERY_TOKENS = {
    "remote", "contract", "contractor", "freelance", "project", "vendor", "work",
    "support", "services", "service", "united", "states", "usa", "business",
}


def _mn_osp_text(html_text: str) -> str:
    """Convert the public OSP listing page to stable line-oriented text."""
    text = str(html_text or "")
    text = re.sub(r"(?i)<br\s*/?>", "\n", text)
    text = re.sub(r"(?i)</(?:p|div|li|tr|td|th|h[1-6])>", "\n", text)
    text = re.sub(r"<[^>]+>", " ", text)
    text = html.unescape(text)
    lines = []
    for raw in text.splitlines():
        line = re.sub(r"\s+", " ", raw).strip()
        if line:
            lines.append(line)
    return "\n".join(lines)


def _mn_osp_field(block: str, label: str) -> str | None:
    pattern = re.compile(rf"(?im)^{re.escape(label)}\s*:\s*(.+)$")
    match = pattern.search(block)
    return match.group(1).strip() if match else None


def _parse_mn_osp_page(
    html_text: str,
    *,
    provider_id: str,
    source_name: str,
    source_url: str,
) -> list[dict[str, Any]]:
    """Parse Minnesota OSP public solicitation pages into vendor opportunities."""
    text = _mn_osp_text(html_text)
    chunks = re.split(r"(?=REFERENCE NUMBER:\s*[A-Z0-9-]+)", text, flags=re.I)
    out: list[dict[str, Any]] = []
    for block in chunks:
        ref = _mn_osp_field(block, "REFERENCE NUMBER")
        title = _mn_osp_field(block, "Title")
        agency = (
            _mn_osp_field(block, "Contracting Agency")
            or _mn_osp_field(block, "Purchasing Agency")
        )
        if not ref or not title or not agency:
            continue

        lowered = block.lower()
        # Single-source notices are informational and are not open work Nova can bid.
        if "single source" in lowered and (
            "not a request for bid" in lowered
            or "not a request for proposal" in lowered
            or "no solicitation documents" in lowered
        ):
            continue

        deadline = _mn_osp_field(block, "Response to this solicitation is due no later than")
        solicitation_number = _mn_osp_field(block, "Solicitation Number")
        estimated_cost = _mn_osp_field(block, "Estimated Cost")

        description = ""
        desc_match = re.search(
            r"(?is)(?:Description of Work|Notes)\s*:\s*(.+?)(?:Date This Solicitation Was Posted\s*:|Category Codes\s*:|$)",
            block,
        )
        if desc_match:
            description = re.sub(r"\s+", " ", desc_match.group(1)).strip()
        if not description:
            description = re.sub(r"\s+", " ", block).strip()

        posted = _mn_osp_field(block, "Date This Solicitation Was Posted")
        out.append(
            normalize_opportunity(
                provider_id=provider_id,
                provider_type="public_rfp_feed",
                provider_identifier=ref,
                source_name=source_name,
                source_attribution=source_name,
                source_url=source_url,
                title=title,
                company_name=agency,
                description=description[:5000],
                compensation_text=estimated_cost,
                contract_type="RFP / vendor solicitation",
                job_type="contract",
                remote_status="unknown",
                geography="Minnesota vendor opportunity",
                fee_required="no",
                publication_date=posted,
                solicitation_number=solicitation_number or ref,
                agency=agency,
                response_deadline=deadline,
                raw_source_metadata={
                    "reference_number": ref,
                    "origin": "mn_osp_public_posting",
                    "submission_channel": (
                        "supplier_portal"
                        if "supplier portal" in lowered or "swift system" in lowered
                        else "listing_instructions"
                    ),
                },
                simulated=False,
            )
        )
    return out


class MinnesotaOspLiveProvider:
    """Official Minnesota public procurement postings, discovery-only."""

    meta = ProviderMeta(
        provider_id="mn_osp",
        label="Minnesota Office of State Procurement",
        provider_type="public_rfp_feed",
        enabled=True,
        access_status="public_page",
        access_mode="page",
        requires_login=False,
        requires_fee=False,
        supports_detail_fetch=False,
        supports_external_submission=False,
        terms_safety_notes=(
            "Read-only discovery from official public Minnesota OSP solicitation pages. "
            "No Supplier Portal login automation, no bid submission, no CAPTCHA bypass."
        ),
        priority=PROVIDER_TYPE_PRIORITY["public_rfp_feed"],
    )

    def __init__(self) -> None:
        self._cache: list[dict[str, Any]] | None = None

    def _load(self) -> list[dict[str, Any]]:
        if self._cache is not None:
            return list(self._cache)
        rows: list[dict[str, Any]] = []
        with httpx.Client(timeout=15.0, follow_redirects=True) as client:
            for provider_id, source_name, source_url in _MN_OSP_PAGE_URLS:
                response = client.get(
                    source_url,
                    headers={"User-Agent": "AMICOR-Nova/1.0 public-procurement-discovery"},
                )
                response.raise_for_status()
                rows.extend(
                    _parse_mn_osp_page(
                        response.text,
                        provider_id=provider_id,
                        source_name=source_name,
                        source_url=source_url,
                    )
                )
        self._cache = dedupe_opportunities(rows)
        return list(self._cache)

    def search(self, query: str, *, limit: int = 10) -> list[dict[str, Any]]:
        capped = max(1, min(25, int(limit)))
        rows = self._load()
        tokens = {
            token for token in re.findall(r"[a-z0-9]+", str(query or "").lower())
            if len(token) > 2 and token not in _MN_OSP_IGNORE_QUERY_TOKENS
        }
        scored: list[tuple[int, dict[str, Any]]] = []
        for row in rows:
            blob = " ".join(
                [
                    str(row.get("title") or ""),
                    str(row.get("company_name") or ""),
                    str(row.get("description") or ""),
                ]
            ).lower()
            hits = sum(1 for token in tokens if token in blob)
            # Keep exact capability-keyword hits even when the owner's query is broad.
            capability_hit = bool(_SAM_DIGITAL_RELEVANCE.search(blob))
            if tokens and hits == 0 and not capability_hit:
                continue
            scored.append((hits + (2 if capability_hit else 0), row))
        scored.sort(
            key=lambda item: (
                item[0],
                str(item[1].get("publication_date") or ""),
            ),
            reverse=True,
        )
        return [row for _, row in scored[:capped]]




class JobicyLiveProvider:
    """Public Jobicy remote-jobs API. Discovery-only."""

    meta = ProviderMeta(
        provider_id="jobicy",
        label="Jobicy",
        provider_type="remote_contract_feed",
        enabled=True,
        access_status="public_api",
        access_mode="api",
        requires_login=False,
        requires_fee=False,
        supports_detail_fetch=False,
        supports_external_submission=False,
        terms_safety_notes=(
            "Uses Jobicy's public remote jobs API for read-only discovery. "
            "Preserves Jobicy source URLs and attribution. No auto-apply."
        ),
        priority=PROVIDER_TYPE_PRIORITY["remote_contract_feed"] + 2,
    )
    API_URL = "https://jobicy.com/api/v2/remote-jobs"

    @staticmethod
    def _query_tag(query: str) -> str:
        """Reduce long owner prompts to a concise public API keyword tag."""
        tokens = [
            token
            for token in re.findall(r"[a-z0-9+#.]+", str(query or "").lower())
            if len(token) > 2
            and token not in {
                "remote", "contract", "contractor", "freelance", "vendor", "project",
                "business", "support", "services", "service", "work", "united",
                "states", "usa", "company", "role", "jobs", "job",
            }
        ]
        return " ".join(tokens[:6]).strip()

    def search(self, query: str, *, limit: int = 10) -> list[dict[str, Any]]:
        capped = max(1, min(25, int(limit)))
        params: dict[str, Any] = {
            "count": capped,
            "geo": "usa",
        }
        tag = self._query_tag(query)
        if tag:
            params["tag"] = tag

        with httpx.Client(timeout=12.0, follow_redirects=True) as client:
            response = client.get(
                self.API_URL,
                params=params,
                headers={"User-Agent": "AMICOR-Nova/1.0 multi-source-discovery"},
            )
            response.raise_for_status()
            payload = response.json()

        out: list[dict[str, Any]] = []
        for raw in list(payload.get("jobs") or [])[:capped]:
            if not isinstance(raw, dict):
                continue
            source_url = str(raw.get("url") or "").strip()
            title = str(raw.get("jobTitle") or "").strip()
            company = str(raw.get("companyName") or "").strip()
            if not source_url or not title or not company:
                continue

            job_types = raw.get("jobType") or []
            if isinstance(job_types, str):
                job_types = [job_types]
            job_type_text = ", ".join(str(item) for item in job_types if item)
            contract_type = "contract" if re.search(
                r"\b(contract|contractor|freelance|temporary|project)\b",
                job_type_text,
                re.I,
            ) else (job_type_text or "unknown")

            salary_parts = [
                str(raw.get("annualSalaryMin") or "").strip(),
                str(raw.get("annualSalaryMax") or "").strip(),
                str(raw.get("salaryCurrency") or "").strip(),
            ]
            compensation = " - ".join(part for part in salary_parts[:2] if part)
            if compensation and salary_parts[2]:
                compensation = f"{compensation} {salary_parts[2]}"
            compensation = compensation or None

            out.append(
                normalize_opportunity(
                    provider_id="jobicy",
                    provider_type="remote_contract_feed",
                    provider_identifier=str(raw.get("id") or source_url),
                    source_name="Jobicy",
                    source_attribution="Jobicy",
                    source_url=source_url,
                    title=title,
                    company_name=company,
                    description=_clean_html(raw.get("jobDescription") or raw.get("jobExcerpt"))[:5000],
                    compensation_text=compensation,
                    contract_type=contract_type,
                    job_type=contract_type,
                    remote_status="remote",
                    geography=str(raw.get("jobGeo") or "United States"),
                    fee_required="no",
                    publication_date=(str(raw.get("pubDate") or "").strip() or None),
                    raw_source_metadata={
                        "origin": "jobicy_public_api",
                        "job_industry": list(raw.get("jobIndustry") or []),
                        "job_level": raw.get("jobLevel"),
                        "job_type_raw": list(job_types),
                    },
                    simulated=False,
                )
            )
        return out


# Capability-aligned digital/remote contracting signals for SAM.gov pre-filter.
_SAM_DIGITAL_RELEVANCE = re.compile(
    r"\b("
    r"administrative|admin(?:istrative)? support|document preparation|document support|"
    r"report(?:ing)?|spreadsheet|data cleanup|data reconciliation|data entry|"
    r"research|operational analysis|operations support|virtual assistant|"
    r"clerical|records management|information management|program support|"
    r"management support|business operations|technical writing|editorial|"
    r"transcription|analyst|analytical|workflow|crm|office support|"
    r"knowledge management|policy analysis|market research"
    r")\b",
    re.I,
)

_SAM_HARD_REJECT = re.compile(
    r"\b("
    r"construction|renovation|demolition|janitorial|custodial|groundskeeping|"
    r"security guard|armed guard|physician|registered nurse|nursing|"
    r"electrician|plumbing|hvac|pest control|lawn care|"
    r"food service|catering|truck driving|vehicle maintenance|"
    r"weapons|ammunition|aircraft maintenance|ship repair|"
    r"facility maintenance|roofing|paving|asphalt"
    r")\b",
    re.I,
)


def _pop_name(node: Any) -> str:
    if isinstance(node, dict):
        return str(node.get("name") or node.get("code") or "").strip()
    return str(node or "").strip()


def _format_place_of_performance(raw: Any) -> str:
    if not isinstance(raw, dict):
        return ""
    city = _pop_name(raw.get("city"))
    state = _pop_name(raw.get("state"))
    country = _pop_name(raw.get("country"))
    zip_code = str(raw.get("zip") or "").strip()
    parts = [p for p in (city, state, zip_code, country) if p]
    return ", ".join(parts)


def _award_compensation(award: Any) -> str | None:
    if not isinstance(award, dict):
        return None
    amount = award.get("amount")
    if amount is None or amount == "":
        return None
    try:
        return f"${float(amount):,.2f} award"
    except (TypeError, ValueError):
        text = str(amount).strip()
        return text or None


class SamGovLiveProvider:
    """Read-only SAM.gov Get Opportunities Public API. Discovery-only.

    Never submits proposals, contacts agencies, accepts contracts, or registers.
    API key is read only from SAM_GOV_API_KEY and never embedded in source URLs
    returned to callers or persisted diagnostics.
    """

    API_URL = "https://api.sam.gov/opportunities/v2/search"
    PUBLIC_OPP_URL = "https://sam.gov/opp/{notice_id}/view"

    meta = ProviderMeta(
        provider_id="sam_gov",
        label="SAM.gov opportunities",
        provider_type="government_contracting",
        enabled=True,
        access_status="public_api_key_required",
        access_mode="api",
        requires_login=False,
        requires_fee=False,
        supports_detail_fetch=False,
        supports_external_submission=False,
        terms_safety_notes=(
            "Read-only SAM.gov Get Opportunities Public API. Discovery only. "
            "No proposal submission, agency contact, registration, or contract acceptance."
        ),
        pending_requirements=None,
        priority=PROVIDER_TYPE_PRIORITY["government_contracting"],
    )

    def _require_key(self) -> str:
        key = _sam_gov_api_key()
        if not key:
            raise SamGovUnavailable(
                "provider unavailable: SAM_GOV_API_KEY missing from environment"
            )
        return key

    def _posted_window(self) -> tuple[str, str]:
        today = datetime.now(timezone.utc).date()
        start = today - timedelta(days=30)
        return start.strftime("%m/%d/%Y"), today.strftime("%m/%d/%Y")

    def _title_search_term(self, query: str) -> str:
        cleaned = re.sub(r"\s+", " ", str(query or "").strip())
        low = cleaned.lower()
        # SAM title search is much narrower than general job-board search.
        # Convert Nova capability phrases to short procurement-friendly terms
        # instead of sending long freelance/remote wording that often yields 0.
        canonical = (
            ("rfp", "proposal support"),
            ("proposal", "proposal support"),
            ("sop", "technical writing"),
            ("technical writing", "technical writing"),
            ("document", "document support"),
            ("records", "records management"),
            ("spreadsheet", "data support"),
            ("data cleaning", "data support"),
            ("data cleanup", "data support"),
            ("research", "research support"),
            ("competitor", "market research"),
            ("customer support", "customer support"),
            ("crm", "administrative support"),
            ("bookkeeping", "financial support"),
            ("invoice", "financial support"),
            ("workflow automation", "workflow"),
            ("automation", "workflow"),
            ("api integration", "information technology"),
            ("web development", "information technology"),
            ("operations", "operations support"),
            ("administrative", "administrative support"),
        )
        for signal, term in canonical:
            if signal in low:
                return term
        tokens = [t for t in re.findall(r"[A-Za-z]{3,}", cleaned) if t.lower() not in {"the", "and", "for", "remote", "contractor", "freelance", "project"}]
        if not tokens:
            return "administrative support"
        return " ".join(tokens[:3])[:80]

    def _source_text_blob(self, raw: dict[str, Any], title: str) -> str:
        """Title + original SAM text only (never synthetic boilerplate)."""
        desc = str(raw.get("description") or "").strip()
        if desc.lower().startswith("http"):
            desc = ""
        return f"{title} {_clean_html(desc)}"

    def _is_digitally_relevant(self, title: str, source_blob: str) -> bool:
        # Title-level hard rejects always win (construction, nursing, etc.).
        if _SAM_HARD_REJECT.search(title):
            return False
        if _SAM_HARD_REJECT.search(source_blob) and not _SAM_DIGITAL_RELEVANCE.search(title):
            return False
        return bool(_SAM_DIGITAL_RELEVANCE.search(source_blob))

    def _build_description(self, raw: dict[str, Any], *, place: str, set_aside: str | None) -> str:
        parts = [
            str(raw.get("title") or "").strip(),
            f"Notice type: {str(raw.get('type') or '').strip()}" if raw.get("type") else "",
            f"NAICS: {str(raw.get('naicsCode') or '').strip()}" if raw.get("naicsCode") else "",
            f"Set-aside: {set_aside}" if set_aside else "",
            f"Place of performance: {place}" if place else "",
            "Public government contract opportunity. Discovery only.",
        ]
        # Prefer any inline textual description if SAM ever returns plain text.
        desc = str(raw.get("description") or "").strip()
        if desc and not desc.lower().startswith("http"):
            parts.insert(1, _clean_html(desc)[:3500])
        return _clean_html(" ".join(p for p in parts if p))[:5000]

    def _parse_row(
        self,
        raw: dict[str, Any],
        *,
        enforce_relevance: bool = True,
    ) -> dict[str, Any] | None:
        notice_id = str(raw.get("noticeId") or "").strip()
        title = str(raw.get("title") or "").strip()
        if not notice_id or not title:
            return None
        if enforce_relevance and not self._is_digitally_relevant(title, self._source_text_blob(raw, title)):
            return None
        agency = (
            str(raw.get("fullParentPathName") or "").strip()
            or str(raw.get("department") or "").strip()
            or str(raw.get("subTier") or "").strip()
            or "U.S. Government"
        )
        solicitation = str(raw.get("solicitationNumber") or "").strip() or None
        response_deadline = str(raw.get("responseDeadLine") or raw.get("reponseDeadLine") or "").strip() or None
        set_aside = (
            str(raw.get("typeOfSetAsideDescription") or raw.get("setAside") or "").strip()
            or str(raw.get("typeOfSetAside") or raw.get("setAsideCode") or "").strip()
            or None
        )
        place = _format_place_of_performance(raw.get("placeOfPerformance"))
        description = self._build_description(raw, place=place, set_aside=set_aside)
        place_lower = place.lower()
        if any(token in place_lower for token in ("remote", "virtual", "telework", "nationwide", "continental us")):
            remote_status = "remote"
        elif place:
            remote_status = "unknown"
        else:
            remote_status = "unknown"
        compensation = _award_compensation(raw.get("award"))
        # Public UI link — never append api_key.
        source_url = self.PUBLIC_OPP_URL.format(notice_id=notice_id)
        return normalize_opportunity(
            provider_id="sam_gov",
            provider_type="government_contracting",
            provider_identifier=notice_id,
            notice_id=notice_id,
            solicitation_number=solicitation,
            agency=agency,
            response_deadline=response_deadline,
            place_of_performance=place or None,
            set_aside=set_aside,
            source_name="SAM.gov",
            source_attribution="SAM.gov",
            source_url=source_url,
            title=title,
            company_name=agency,
            description=description,
            compensation_text=compensation,
            contract_type="government_contract",
            job_type="contract",
            remote_status=remote_status,
            geography=place or "United States",
            fee_required="no",
            publication_date=(str(raw.get("postedDate") or "").strip() or None),
            raw_source_metadata={
                "origin": "sam_gov",
                "notice_id": notice_id,
                "solicitation_number": solicitation,
                "agency": agency,
                "response_deadline": response_deadline,
                "place_of_performance": place or None,
                "set_aside": set_aside,
                "naics_code": str(raw.get("naicsCode") or "").strip() or None,
                "notice_type": str(raw.get("type") or "").strip() or None,
                "active": str(raw.get("active") or "").strip() or None,
                # Store description endpoint without key if present.
                "description_ref": (
                    str(raw.get("description") or "").strip()
                    if str(raw.get("description") or "").lower().startswith("http")
                    else None
                ),
                "resource_links": [
                    str(item).strip()
                    for item in list(raw.get("resourceLinks") or [])
                    if isinstance(item, str) and str(item or "").strip()
                ][:12],
                "resource_link_objects": [
                    dict(item)
                    for item in list(raw.get("resourceLinks") or [])
                    if isinstance(item, dict)
                ][:12],
                "additional_info_link": str(raw.get("additionalInfoLink") or "").strip() or None,
            },
            simulated=False,
        )


    @staticmethod
    def _allowed_sam_resource_url(value: str) -> bool:
        """Allow only public SAM.gov attachment/resource URLs."""
        try:
            parsed = urlparse(str(value or "").strip())
        except Exception:
            return False
        host = str(parsed.hostname or "").lower()
        return parsed.scheme == "https" and (host == "sam.gov" or host.endswith(".sam.gov"))

    @staticmethod
    def _resource_name_hint(url: str, headers: Any) -> str:
        disposition = str((headers or {}).get("content-disposition") or "")
        return f"{url} {disposition}".lower()

    @staticmethod
    def _extract_resource_text(*, url: str, response: Any) -> str:
        """Extract text from a bounded public solicitation resource without executing it."""
        content_type = str(response.headers.get("content-type") or "").lower()
        hint = SamGovLiveProvider._resource_name_hint(url, response.headers)
        payload = bytes(response.content or b"")
        if not payload:
            return ""
        if len(payload) > 10_000_000:
            return ""
        try:
            if "pdf" in content_type or ".pdf" in hint:
                reader = PdfReader(BytesIO(payload))
                text = " ".join(str(page.extract_text() or "") for page in reader.pages[:80])
                return _clean_html(text)[:18000]
            if (
                "wordprocessingml" in content_type
                or ".docx" in hint
            ):
                doc = Document(BytesIO(payload))
                text = " ".join(str(paragraph.text or "") for paragraph in doc.paragraphs)
                return _clean_html(text)[:18000]
            if (
                content_type.startswith("text/")
                or "html" in content_type
                or ".txt" in hint
                or ".htm" in hint
            ):
                return _clean_html(str(response.text or ""))[:18000]
        except Exception:
            return ""
        return ""

    def _fetch_notice_supporting_text(self, row: dict[str, Any]) -> str | None:
        """Read a few public SAM solicitation attachments for actual scope/duties.

        Amendment descriptions frequently contain only change notices while the
        real duties live in a PWS/SOW/requirements attachment. This remains
        read-only, SAM-host allowlisted, byte/page bounded, and never submits.
        """
        metadata = dict(row.get("raw_source_metadata") or {})
        links = [
            str(item).strip()
            for item in list(metadata.get("resource_links") or [])
            if self._allowed_sam_resource_url(str(item or ""))
        ]
        # SAM resourceLinks may be strings or structured objects depending on
        # notice/version.  Do not stringify objects: extract URL-like values.
        for item in list(metadata.get("resource_link_objects") or []):
            if not isinstance(item, dict):
                continue
            for key_name in (
                "url", "href", "link", "resourceUrl", "resourceURL",
                "downloadUrl", "downloadURL", "uri",
            ):
                candidate = str(item.get(key_name) or "").strip()
                if self._allowed_sam_resource_url(candidate):
                    links.append(candidate)
                    break
        additional = str(metadata.get("additional_info_link") or "").strip()
        if self._allowed_sam_resource_url(additional):
            links.append(additional)
        # Keep stable order while removing duplicates.
        links = list(dict.fromkeys(links))
        if not links:
            return None

        priority_terms = (
            "performance work statement", "pws", "statement of work", "sow",
            "performance requirements", "requirements", "scope", "technical exhibit",
        )
        links = sorted(
            links,
            key=lambda value: (
                -sum(1 for term in priority_terms if term in value.lower()),
                value.lower(),
            ),
        )[:6]

        extracted: list[tuple[int, str]] = []
        key = self._require_key()
        try:
            with httpx.Client(timeout=20.0, follow_redirects=True) as client:
                for link in links:
                    try:
                        response = client.get(
                            link,
                            headers={
                                "User-Agent": "AMICOR-Nova/1.0 opportunity-resource-review",
                                "Accept": "application/pdf,application/vnd.openxmlformats-officedocument.wordprocessingml.document,text/plain,text/html",
                            },
                        )
                        if response.status_code in {401, 403} and "api.sam.gov" in link:
                            response = client.get(
                                link,
                                params={"api_key": key},
                                headers={
                                    "User-Agent": "AMICOR-Nova/1.0 opportunity-resource-review",
                                    "Accept": "application/pdf,application/vnd.openxmlformats-officedocument.wordprocessingml.document,text/plain,text/html",
                                },
                            )
                        if response.status_code in {401, 403}:
                            continue
                        response.raise_for_status()
                        text = self._extract_resource_text(url=link, response=response)
                        if not text:
                            continue
                        hint = self._resource_name_hint(link, response.headers)
                        score = sum(3 for term in priority_terms if term in hint)
                        score += sum(
                            1 for term in (
                                "contractor shall", "performance objective", "task ",
                                "deliverable", "scope of work", "performance requirement",
                            )
                            if term in text.lower()
                        )
                        extracted.append((score, text))
                    except Exception:
                        continue
        except Exception:
            return None

        if not extracted:
            return None
        extracted.sort(key=lambda item: item[0], reverse=True)
        combined = " ".join(text for _, text in extracted[:2])
        return _clean_html(combined)[:18000] or None

    def _fetch_notice_description(self, row: dict[str, Any]) -> str | None:
        """Fetch the public SAM notice description read-only using the configured API key.

        The search API frequently returns description as an API URL rather than
        inline text. This helper follows only SAM.gov API URLs and never exposes
        the API key in returned data, logs, or source URLs.
        """
        key = self._require_key()
        metadata = dict(row.get("raw_source_metadata") or {})
        ref = str(metadata.get("description_ref") or "").strip()
        if not ref:
            return None
        if not ref.startswith(("https://api.sam.gov/", "https://api-alpha.sam.gov/")):
            return None
        try:
            with httpx.Client(timeout=15.0, follow_redirects=True) as client:
                response = client.get(
                    ref,
                    params={"api_key": key},
                    headers={
                        "User-Agent": "AMICOR-Nova/1.0 opportunity-description-review",
                        "Accept": "application/json,text/plain,text/html",
                    },
                )
                if response.status_code in {401, 403}:
                    raise SamGovUnavailable(
                        "provider unavailable: SAM.gov API key rejected or expired"
                    )
                response.raise_for_status()
                content_type = str(response.headers.get("content-type") or "").lower()
                if "json" in content_type:
                    payload = response.json()
                    if isinstance(payload, dict):
                        raw = (
                            payload.get("description")
                            or payload.get("body")
                            or payload.get("content")
                            or payload.get("descriptionText")
                            or ""
                        )
                        if isinstance(raw, dict):
                            raw = raw.get("body") or raw.get("content") or ""
                    else:
                        raw = ""
                else:
                    raw = response.text
                cleaned = _clean_html(str(raw or ""))
                if not cleaned:
                    return None
                return cleaned[:12000]
        except SamGovUnavailable:
            raise
        except Exception:
            return None

    def find_exact(self, identifier: str) -> dict[str, Any] | None:
        """Read-only exact lookup by solicitation number or SAM notice ID."""
        key = self._require_key()
        value = str(identifier or "").strip()
        if not value:
            return None
        today = datetime.now(timezone.utc).date()
        posted_from = (today - timedelta(days=365)).strftime("%m/%d/%Y")
        posted_to = today.strftime("%m/%d/%Y")

        def _request(param_name: str) -> list[dict[str, Any]]:
            params = {
                "api_key": key,
                "postedFrom": posted_from,
                "postedTo": posted_to,
                "limit": 25,
                "offset": 0,
                param_name: value,
            }
            with httpx.Client(timeout=15.0, follow_redirects=True) as client:
                response = client.get(
                    self.API_URL,
                    params=params,
                    headers={
                        "User-Agent": "AMICOR-Nova/1.0 exact-opportunity-review",
                        "Accept": "application/json",
                    },
                )
                if response.status_code in {401, 403}:
                    raise SamGovUnavailable(
                        "provider unavailable: SAM.gov API key rejected or expired"
                    )
                response.raise_for_status()
                payload = response.json()
            return [row for row in list(payload.get("opportunitiesData") or []) if isinstance(row, dict)]

        try:
            raw_rows = _request("solnum")
            if not raw_rows:
                raw_rows = _request("noticeid")
        except SamGovUnavailable:
            raise
        except Exception as exc:
            raise RuntimeError(_redact_secret(f"{type(exc).__name__}: {exc}", key)) from None

        wanted = value.upper()
        for raw in raw_rows:
            ids = {
                str(raw.get("solicitationNumber") or "").strip().upper(),
                str(raw.get("noticeId") or "").strip().upper(),
            }
            if wanted in ids:
                parsed = self._parse_row(raw, enforce_relevance=False)
                if parsed is None:
                    return None
                detailed = self._fetch_notice_description(parsed)
                if detailed:
                    parsed["description"] = detailed
                    metadata = dict(parsed.get("raw_source_metadata") or {})
                    metadata["description_fetched"] = True
                    parsed["raw_source_metadata"] = metadata
                supporting = self._fetch_notice_supporting_text(parsed)
                if supporting:
                    current = str(parsed.get("description") or "").strip()
                    parsed["description"] = _clean_html(
                        f"{current} Supporting solicitation requirements: {supporting}"
                    )[:22000]
                    metadata = dict(parsed.get("raw_source_metadata") or {})
                    metadata["supporting_resource_fetched"] = True
                    parsed["raw_source_metadata"] = metadata
                return parsed
        return None

    def search(self, query: str, *, limit: int = 10) -> list[dict[str, Any]]:
        key = self._require_key()
        capped = max(1, min(25, int(limit)))
        posted_from, posted_to = self._posted_window()
        title_term = self._title_search_term(query)
        params = {
            "api_key": key,
            "postedFrom": posted_from,
            "postedTo": posted_to,
            "limit": min(100, max(capped * 4, 25)),
            "offset": 0,
            "ptype": "o,k,r",
            "title": title_term,
        }
        try:
            with httpx.Client(timeout=15.0, follow_redirects=True) as client:
                response = client.get(
                    self.API_URL,
                    params=params,
                    headers={
                        "User-Agent": "AMICOR-Nova/1.0 multi-source-discovery",
                        "Accept": "application/json",
                    },
                )
                if response.status_code in {401, 403}:
                    raise SamGovUnavailable(
                        "provider unavailable: SAM.gov API key rejected or expired"
                    )
                response.raise_for_status()
                payload = response.json()
        except SamGovUnavailable:
            raise
        except Exception as exc:  # noqa: BLE001 - redact secrets before re-raise
            raise RuntimeError(_redact_secret(f"{type(exc).__name__}: {exc}", key)) from None

        out: list[dict[str, Any]] = []
        seen: set[str] = set()
        for raw in list(payload.get("opportunitiesData") or []):
            if not isinstance(raw, dict):
                continue
            row = self._parse_row(raw)
            if not row:
                continue
            notice = str(row.get("notice_id") or "")
            if notice in seen:
                continue
            seen.add(notice)
            # Never leak the key into normalized records.
            assert key not in str(row.get("source_url") or "")
            assert key not in str(row.get("description") or "")
            out.append(row)
            if len(out) >= capped:
                break
        return out


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
    return [
        MinnesotaOspLiveProvider(),
        RemotiveLiveProvider(),
        RemoteOkLiveProvider(),
        JobicyLiveProvider(),
        SamGovLiveProvider(),
    ]


def all_provider_metas() -> list[ProviderMeta]:
    rows = [provider.meta for provider in live_providers()]
    rows.extend(item.meta for item in PENDING_PROVIDERS)
    return sorted(rows, key=lambda item: (item.priority, item.provider_id))


def provider_catalog() -> list[dict[str, Any]]:
    out = []
    for meta in all_provider_metas():
        health = _health.get(meta.provider_id)
        access_status = meta.access_status
        if meta.provider_id == "sam_gov":
            access_status = "api_key_configured" if sam_gov_key_configured() else "api_key_missing"
        out.append(
            {
                "provider_id": meta.provider_id,
                "label": meta.label,
                "provider_type": meta.provider_type,
                "enabled": meta.enabled,
                "access_status": access_status,
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


_ADMIN_QUERY_HINTS = re.compile(
    r"\b(administrative|admin|virtual assistant|office assistant|operations support|"
    r"project administration|scheduling support|data entry|crm cleanup|"
    r"workflow documentation|business operations support)\b",
    re.I,
)
_ADMIN_JOB_SIGNALS = re.compile(
    r"\b(administrative|admin|assistant|office|clerical|scheduling|calendar|"
    r"data entry|crm|document preparation|document support|records|"
    r"operations support|business operations|project coordinator|project administration|"
    r"customer operations|back office|reporting support)\b",
    re.I,
)
_ADMIN_TECH_TITLE_REJECT = re.compile(
    r"\b(engineer|developer|architect|data scientist|devops|full[- ]?stack|"
    r"front[- ]?end|back[- ]?end|shopify|rails|machine learning|ml engineer|"
    r"software developer|software engineer|tech lead)\b",
    re.I,
)
_ADMIN_DOMAIN_SPECIALIST_TITLE_REJECT = re.compile(
    r"\b(digital assets?|crypto(?:currency)?|blockchain)\b",
    re.I,
)
_ADMIN_EMPLOYEE_SIGNALS = re.compile(
    r"\b(full[- ]?time|part[- ]?time|employee|w-?2|salary|benefits|401\(k\)|401k|"
    r"join our team|permanent position|staff position)\b",
    re.I,
)
_ADMIN_PAID_ACCESS_SIGNALS = re.compile(
    r"\b(upfront fee|membership fee|paid membership|subscription required|"
    r"pay to apply|application fee|pay to access|payment required)\b",
    re.I,
)
_ADMIN_NON_US_GEO = re.compile(
    r"\b(europe|european union|germany|deutschland|uk only|united kingdom only|"
    r"canada only|australia only|india only|emea|apac only)\b",
    re.I,
)
_ADMIN_US_GEO = re.compile(
    r"\b(united states|usa|u\.s\.|us only|nationwide|worldwide|anywhere|remote)\b",
    re.I,
)
_EXPLICIT_US_OR_WORLD_GEO = re.compile(
    r"\b(united states|usa|u\.s\.|us only|nationwide|worldwide|anywhere)\b",
    re.I,
)
_US_REMOTE_QUERY = re.compile(
    r"\b(united states|usa|u\.s\.|nationwide|remote)\b",
    re.I,
)
_REMOTE_QUERY = re.compile(r"\b(remote|virtual|telework|nationwide)\b", re.I)


_VENDOR_INTENT_QUERY = re.compile(
    r"\b(contract|contractor|freelance|vendor|b2b|project)\b",
    re.I,
)
_VENDOR_COMPATIBLE_SIGNALS = re.compile(
    r"\b(contract|contractor|freelance|1099|vendor|b2b|consultant|project[- ]based|statement of work|sow)\b",
    re.I,
)
_EMPLOYEE_ONLY_SIGNALS = re.compile(
    r"\b(w-?2|full[- ]?time employee|part[- ]?time employee|employee role|salary|benefits|401\(k\)|401k|join our team|staff position|talent network)\b",
    re.I,
)

_BOOKKEEPING_QUERY_HINTS = re.compile(
    r"\b(bookkeep(?:ing)?|accounts? payable|accounts? receivable|reconciliation|"
    r"invoice|expense|financial spreadsheet|financial reporting|transaction categorization)\b",
    re.I,
)
_BOOKKEEPING_RESULT_SIGNALS = re.compile(
    r"\b(bookkeep(?:ing)?|accounts? payable|accounts? receivable|reconciliation|"
    r"invoice|expense|financial spreadsheet|financial report|transaction categorization|"
    r"ledger|quickbooks|xero)\b",
    re.I,
)
_AI_AUTOMATION_QUERY_HINTS = re.compile(
    r"\b(ai|artificial intelligence|automation|prompt|workflow automation|ai operations)\b",
    re.I,
)
_AI_AUTOMATION_RESULT_SIGNALS = re.compile(
    r"\b(ai|artificial intelligence|automation|workflow automation|zapier|make\.com|"
    r"n8n|api integration|prompt engineering|prompt workflow|llm|ai agent|agent workflow)\b",
    re.I,
)


_ADMIN_STRONG_TITLE = re.compile(
    r"\b("
    r"administrative (?:assistant|support|coordinator|specialist)|"
    r"admin(?:istrative)? assistant|virtual assistant|office assistant|office administrator|"
    r"operations (?:assistant|support|coordinator|administrator|analyst(?: contractor)?)|"
    r"business operations (?:assistant|support|coordinator)|"
    r"data entry (?:assistant|clerk|specialist|contractor)|"
    r"records (?:assistant|clerk|specialist|coordinator)|"
    r"document (?:assistant|specialist|coordinator|processor)|"
    r"crm (?:assistant|administrator|specialist|coordinator)|"
    r"scheduling (?:assistant|coordinator|specialist)|"
    r"back office (?:assistant|support|specialist)|"
    r"bookkeeping (?:assistant|support|specialist)"
    r")\b",
    re.I,
)

_ADMIN_QUERY_VARIANTS = (
    "remote administrative assistant contractor",
    "virtual assistant contractor remote",
    "operations assistant contractor remote",
    "data entry contractor remote",
    "back office support contractor remote",
)


def _discovery_query_variants(query: str) -> list[str]:
    normalized = re.sub(r"\s+", " ", str(query or "").strip())
    if not _ADMIN_QUERY_HINTS.search(normalized):
        return [normalized]
    variants = [normalized, *_ADMIN_QUERY_VARIANTS]
    out: list[str] = []
    seen: set[str] = set()
    for item in variants:
        key = item.lower()
        if key in seen:
            continue
        seen.add(key)
        out.append(item)
    return out[:5]



def _query_relevant(row: dict[str, Any], query: str) -> bool:
    """Reject obvious provider false positives before qualification.

    This is intentionally narrow: it only applies an extra guard to
    administrative/operations searches, where broad remote-job APIs commonly
    return unrelated software roles. General searches keep provider behavior.
    """
    title = str(row.get("title") or "")
    description = str(row.get("description") or "")
    geography = str(row.get("geography") or "")
    job_type = str(row.get("job_type") or row.get("contract_type") or "")
    provider_id = str(row.get("provider_id") or "").strip().lower()
    remote_status = str(row.get("remote_status") or "").strip().lower()
    place_of_performance = str(row.get("place_of_performance") or geography or "")
    query_text = str(query or "")
    combined = " ".join([title, description, geography, job_type])

    # Remote digital / AI / administrative contractor searches drop physical
    # trades, operator licenses, and mandatory on-site roles before they consume
    # a provider result slot. A direct trade query is not rewritten.
    from app.core.nova.work_revenue.capability_first_discovery import (
        blocks_physical_role_for_digital_search,
    )

    if blocks_physical_role_for_digital_search(row, query_text):
        return False

    # User-requested U.S./remote discovery must not surface an explicitly
    # foreign-only listing merely because the listing itself also says "remote".
    if _US_REMOTE_QUERY.search(query_text):
        if _ADMIN_NON_US_GEO.search(geography) and not _EXPLICIT_US_OR_WORLD_GEO.search(geography):
            return False

    # SAM.gov notices with a concrete place of performance are not remote
    # opportunities unless SAM itself marked the notice remote/virtual/telework.
    if (
        provider_id == "sam_gov"
        and _REMOTE_QUERY.search(query_text)
        and place_of_performance.strip()
        and remote_status != "remote"
    ):
        return False

    # Capability-family searches need a positive duty signal, not merely a
    # provider keyword hit. Bookkeeping is especially noisy on broad remote-job
    # feeds, where generic operations/analyst roles can otherwise be mislabeled.
    if _BOOKKEEPING_QUERY_HINTS.search(query_text):
        if not _BOOKKEEPING_RESULT_SIGNALS.search(" ".join([title, description])):
            return False

    # AI/automation searches must contain an actual AI/automation duty signal.
    # Generic "operations" or "digital assets" titles are not enough.
    if _AI_AUTOMATION_QUERY_HINTS.search(query_text):
        if not _AI_AUTOMATION_RESULT_SIGNALS.search(" ".join([title, description])):
            return False

    # For any explicit vendor/contract/project search, remove obvious employee-
    # only feed results before expensive qualification. This preserves true
    # contractor/freelance/B2B listings while reducing W-2/talent-network noise.
    if _VENDOR_INTENT_QUERY.search(str(query or "")):
        if _EMPLOYEE_ONLY_SIGNALS.search(combined) and not _VENDOR_COMPATIBLE_SIGNALS.search(combined):
            return False

    if not _ADMIN_QUERY_HINTS.search(str(query or "")):
        return True

    title_has_admin = bool(_ADMIN_JOB_SIGNALS.search(title))
    body_has_admin = bool(_ADMIN_JOB_SIGNALS.search(description))

    # Technical IC titles should not survive an admin search merely because
    # their descriptions contain generic words like support/operations.
    if _ADMIN_TECH_TITLE_REJECT.search(title) and not title_has_admin:
        return False

    # Domain-specialist analyst roles (for example digital-asset/blockchain
    # operations) are not administrative support simply because the title also
    # contains "operations analyst".
    if _ADMIN_DOMAIN_SPECIALIST_TITLE_REJECT.search(title):
        explicit_admin = bool(re.search(
            r"\b(administrative|admin(?:istrative)? assistant|virtual assistant|office|clerical|"
            r"operations support|business operations support|project administration|data entry)\b",
            title,
            re.I,
        ))
        if not explicit_admin:
            return False

    # This query family is explicitly for contract/vendor work, not employee jobs.
    if _ADMIN_EMPLOYEE_SIGNALS.search(combined) and not re.search(
        r"\b(contract|contractor|freelance|1099|vendor|b2b|project[- ]based)\b",
        combined,
        re.I,
    ):
        return False

    # Never surface pay-to-apply / paid-access admin opportunities.
    if _ADMIN_PAID_ACCESS_SIGNALS.search(combined):
        return False

    # Prefer U.S.-remote/nationwide work. Worldwide is allowed, but explicit
    # non-U.S.-only regions are removed from this U.S. contractor search.
    if _ADMIN_NON_US_GEO.search(geography) and not _ADMIN_US_GEO.search(geography):
        return False

    # Public RFP/vendor notices are scoped by deliverables, not job titles.
    # Their titles are often procurement labels (for example "Data Reporting
    # Services") that would fail the employee-job title gate even when the body
    # clearly describes Nova-compatible administrative/digital work.
    provider_type = str(row.get("provider_type") or "").strip().lower()
    if provider_type in {"public_rfp_feed", "government_contracting", "vendor_project_board"}:
        if not (title_has_admin or body_has_admin or _SAM_DIGITAL_RELEVANCE.search(" ".join([title, description]))):
            return False
        return True

    # Positive-fit gate for ordinary job feeds: do not keep generic managers,
    # schedulers, sales roles, or other jobs merely because their body contains
    # words such as "operations" or "support". The title itself must map to an
    # administrative work archetype Nova is actually allowed to pursue.
    if not _ADMIN_STRONG_TITLE.search(title):
        return False

    # Reaching this point means the title matched an approved administrative
    # archetype and all employee/geo/paid-access guards passed.
    return True


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

        # The same live listing can be returned by multiple capability-planned
        # queries. Preserve every family that found it so later qualification
        # does not judge the listing only against whichever query happened to
        # arrive first.
        family_candidates = list(existing.get("search_family_candidates") or [])
        for family_id in (existing.get("search_family"), row.get("search_family")):
            family_id = str(family_id or "").strip()
            if family_id and family_id not in family_candidates:
                family_candidates.append(family_id)
        if family_candidates:
            existing["search_family_candidates"] = family_candidates

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
    provider_screened_counts: dict[str, int] = {}
    provider_query_variants: dict[str, list[str]] = {}
    query_variants = _discovery_query_variants(normalized)

    for provider in providers:
        meta = provider.meta
        if not meta.enabled:
            continue
        provider_rows: list[dict[str, Any]] = []
        screened = 0
        used_variants: list[str] = []
        try:
            for variant in query_variants:
                used_variants.append(variant)
                rows = provider.search(variant, limit=capped)
                screened += len(rows)
                rows = [row for row in rows if _query_relevant(row, normalized)]
                if not include_simulated:
                    rows = [row for row in rows if not row.get("simulated")]
                provider_rows.extend(rows)
                provider_rows = dedupe_opportunities(provider_rows)
                if len(provider_rows) >= capped:
                    break
            provider_rows = provider_rows[:capped]
            per_provider[meta.provider_id] = len(provider_rows)
            provider_screened_counts[meta.provider_id] = screened
            provider_query_variants[meta.provider_id] = used_variants
            _record_success(meta.provider_id, source_type=meta.provider_type, count=len(provider_rows))
            collected.extend(provider_rows)
        except Exception as exc:  # noqa: BLE001 - isolate provider outages
            message = _redact_secret(f"{type(exc).__name__}: {exc}", _sam_gov_api_key())
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
        "provider_screened_counts": provider_screened_counts,
        "provider_query_variants": provider_query_variants,
        "query_variants": query_variants,
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
