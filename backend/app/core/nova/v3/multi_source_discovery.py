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


def opportunity_dedupe_key(row: dict[str, Any]) -> str:
    # SAM.gov: stable government notice/opportunity id wins over URL churn.
    if str(row.get("provider_id") or "").strip().lower() == "sam_gov":
        notice = str(row.get("notice_id") or row.get("provider_identifier") or "").strip().lower()
        if notice:
            return "sam_notice:" + notice
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

    def _parse_row(self, raw: dict[str, Any]) -> dict[str, Any] | None:
        notice_id = str(raw.get("noticeId") or "").strip()
        title = str(raw.get("title") or "").strip()
        if not notice_id or not title:
            return None
        if not self._is_digitally_relevant(title, self._source_text_blob(raw, title)):
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
            },
            simulated=False,
        )

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
    return [RemotiveLiveProvider(), RemoteOkLiveProvider(), SamGovLiveProvider()]


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


_ADMIN_STRONG_TITLE = re.compile(
    r"\b("
    r"administrative (?:assistant|support|coordinator|specialist)|"
    r"admin(?:istrative)? assistant|virtual assistant|office assistant|office administrator|"
    r"operations (?:assistant|support|coordinator|administrator)|"
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
    combined = " ".join([title, description, geography, job_type])

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

    # Positive-fit gate: for an admin search, do not keep generic managers,
    # schedulers, sales roles, or other jobs merely because their body contains
    # words such as "operations" or "support". The title itself must map to an
    # administrative work archetype Nova is actually allowed to pursue.
    if not _ADMIN_STRONG_TITLE.search(title):
        return False

    return title_has_admin or body_has_admin


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
