"""Read-only live opportunity discovery for Nova V3 owner workspace.

Phase 1 intentionally supports discovery only. It does not submit applications,
contact employers, accept terms, or move money.
"""
from __future__ import annotations

import html
import re
import time
from dataclasses import dataclass
from typing import Any

import httpx

from app.core.nova.v3.errors import V3Error
from app.core.nova.v3.flags import live_flags

REMOTIVE_URL = "https://remotive.com/api/remote-jobs"
_CACHE_TTL_SECONDS = 30 * 60
_cache: dict[str, tuple[float, list[dict[str, Any]]]] = {}


@dataclass(frozen=True)
class LiveJob:
    provider_id: str
    provider_identifier: str
    title: str
    company_name: str
    description: str
    source_url: str
    geography: str
    remote_status: str
    compensation_text: str | None
    job_type: str | None
    publication_date: str | None
    source_attribution: str = "Remotive"

    def as_dict(self) -> dict[str, Any]:
        return {
            "provider_id": self.provider_id,
            "provider_identifier": self.provider_identifier,
            "title": self.title,
            "company_name": self.company_name,
            "description": self.description,
            "source_url": self.source_url,
            "geography": self.geography,
            "remote_status": self.remote_status,
            "compensation_text": self.compensation_text,
            "job_type": self.job_type,
            "publication_date": self.publication_date,
            "source_attribution": self.source_attribution,
        }


def _clean_html(value: str | None) -> str:
    text = html.unescape(str(value or ""))
    text = re.sub(r"<[^>]+>", " ", text)
    return re.sub(r"\s+", " ", text).strip()


def _validated_limit(limit: int) -> int:
    return max(1, min(25, int(limit)))


def search_remote_jobs(query: str, *, limit: int = 10) -> list[dict[str, Any]]:
    if not live_flags()["LIVE_DISCOVERY_ENABLED"]:
        raise V3Error("LIVE_DISABLED", "Live discovery is not enabled", http_status=409)

    normalized = str(query or "").strip()
    if not normalized:
        raise V3Error("INVALID_QUERY", "Job search query is required", http_status=400)

    capped = _validated_limit(limit)
    cache_key = f"{normalized.lower()}::{capped}"
    cached = _cache.get(cache_key)
    if cached and (time.monotonic() - cached[0]) < _CACHE_TTL_SECONDS:
        return cached[1]

    try:
        with httpx.Client(timeout=12.0, follow_redirects=True) as client:
            response = client.get(
                REMOTIVE_URL,
                params={"search": normalized, "limit": capped},
                headers={"User-Agent": "AMICOR-Nova/1.0 live-discovery"},
            )
            response.raise_for_status()
            payload = response.json()
    except (httpx.HTTPError, ValueError) as exc:
        raise V3Error("LIVE_SOURCE_UNAVAILABLE", "Live job source is unavailable", http_status=503) from exc

    jobs: list[dict[str, Any]] = []
    for raw in list(payload.get("jobs") or [])[:capped]:
        source_url = str(raw.get("url") or "").strip()
        title = str(raw.get("title") or "").strip()
        company = str(raw.get("company_name") or "").strip()
        if not source_url or not title or not company:
            continue
        item = LiveJob(
            provider_id="remotive",
            provider_identifier=str(raw.get("id") or source_url),
            title=title,
            company_name=company,
            description=_clean_html(raw.get("description"))[:5000],
            source_url=source_url,
            geography=str(raw.get("candidate_required_location") or "Remote"),
            remote_status="remote",
            compensation_text=(str(raw.get("salary")).strip() or None) if raw.get("salary") is not None else None,
            job_type=(str(raw.get("job_type")).strip() or None) if raw.get("job_type") is not None else None,
            publication_date=(str(raw.get("publication_date")).strip() or None)
            if raw.get("publication_date") is not None
            else None,
        )
        jobs.append(item.as_dict())

    _cache[cache_key] = (time.monotonic(), jobs)
    return jobs
