"""Bounded Nova Work autopilot cycle.

A cycle performs live discovery, qualification, persistence, and application
preparation for strong fits. It never submits applications, contacts clients,
accepts contracts, or performs financial actions.
"""
from __future__ import annotations

from typing import Any

from sqlalchemy.orm import Session

from app.auth import UserContext
from app.core.nova.v3.live_qualification import (
    OUTCOME_NEEDS_OWNER_REVIEW,
    OUTCOME_NOT_QUALIFIED,
    OUTCOME_QUALIFIED,
    partition_by_qualification,
    qualify_and_rank_live_jobs,
)
from app.core.nova.v3.multi_source_discovery import search_multi_source_jobs
from app.core.nova.v3.work_revenue_bridge import persist_ranked_jobs
from app.core.nova.work_revenue.capability_first_discovery import generate_capability_first_queries

MAX_QUERIES = 5
MAX_RESULTS_PER_QUERY = 10
MAX_SAVED = 10
MAX_PREPARED = 5


def _dedupe_key(job: dict[str, Any]) -> str:
    provider = str(job.get("provider_id") or "").strip().lower()
    source_url = str(job.get("source_url") or "").strip().lower()
    if source_url:
        return f"{provider}|{source_url}"
    title = str(job.get("title") or "").strip().lower()
    company = str(job.get("company_name") or job.get("client") or "").strip().lower()
    notice = str(job.get("notice_id") or "").strip().lower()
    return f"{provider}|{notice}|{company}|{title}"


def _default_queries(limit: int) -> list[str]:
    rows = generate_capability_first_queries()
    # Spread the default run across different capability families instead of
    # spending the entire budget on one family.
    selected: list[str] = []
    seen_families: set[str] = set()
    for row in rows:
        family = str(row.get("search_family") or "")
        if family in seen_families:
            continue
        query = str(row.get("query") or "").strip()
        if not query:
            continue
        selected.append(query)
        seen_families.add(family)
        if len(selected) >= limit:
            break
    return selected


def run_autopilot_cycle(
    db: Session,
    *,
    organization_id: str,
    user: UserContext,
    queries: list[str] | None = None,
    query_limit: int = 3,
    per_query_limit: int = 5,
    save_limit: int = 8,
    prepare_limit: int = 3,
    min_relevance_score: int = 60,
) -> dict[str, Any]:
    """Run one bounded owner-safe work-search cycle.

    Strong fits may have application workspaces prepared and moved to owner
    review. External execution remains impossible here.
    """
    q_limit = max(1, min(int(query_limit or 3), MAX_QUERIES))
    result_limit = max(1, min(int(per_query_limit or 5), MAX_RESULTS_PER_QUERY))
    save_cap = max(1, min(int(save_limit or 8), MAX_SAVED))
    prep_cap = max(0, min(int(prepare_limit or 3), MAX_PREPARED))
    threshold = max(0, min(int(min_relevance_score or 0), 100))

    supplied = [str(item).strip() for item in (queries or []) if str(item).strip()]
    selected_queries = supplied[:q_limit] if supplied else _default_queries(q_limit)

    combined: list[dict[str, Any]] = []
    providers_queried: set[str] = set()
    provider_errors: list[dict[str, Any]] = []
    per_query: list[dict[str, Any]] = []

    for query in selected_queries:
        multi = search_multi_source_jobs(query, limit=result_limit)
        ranked = qualify_and_rank_live_jobs(query, multi.get("jobs") or [])
        providers_queried.update(str(item) for item in (multi.get("providers_queried") or []))
        provider_errors.extend(list(multi.get("provider_errors") or []))
        per_query.append(
            {
                "query": query,
                "ranked_count": len(ranked),
                "provider_result_counts": multi.get("provider_result_counts") or {},
            }
        )
        combined.extend(ranked)

    # Highest-scoring representation wins when the same opportunity appears
    # through repeated search queries.
    combined.sort(key=lambda row: int(row.get("relevance_score") or 0), reverse=True)
    unique: list[dict[str, Any]] = []
    seen: set[str] = set()
    for job in combined:
        key = _dedupe_key(job)
        if key in seen:
            continue
        seen.add(key)
        if int(job.get("relevance_score") or 0) < threshold:
            continue
        unique.append(job)
        if len(unique) >= save_cap:
            break

    persistent = persist_ranked_jobs(
        db,
        unique,
        organization_id=organization_id,
        user=user,
        prepare_applications=True,
        prepare_limit=prep_cap,
    )
    buckets = partition_by_qualification(unique)

    ready_for_owner_review = [
        row for row in persistent if row.get("ready_for_owner_review")
    ]
    blocked_packages = [
        row for row in persistent if row.get("package_review_status") == "BLOCKED"
    ]

    return {
        "mode": "bounded_autopilot_cycle",
        "queries": selected_queries,
        "query_count": len(selected_queries),
        "per_query": per_query,
        "providers_queried": sorted(providers_queried),
        "provider_errors": provider_errors,
        "ranked_count": len(combined),
        "selected_count": len(unique),
        "qualification_counts": {
            OUTCOME_QUALIFIED: len(buckets[OUTCOME_QUALIFIED]),
            OUTCOME_NEEDS_OWNER_REVIEW: len(buckets[OUTCOME_NEEDS_OWNER_REVIEW]),
            OUTCOME_NOT_QUALIFIED: len(buckets[OUTCOME_NOT_QUALIFIED]),
        },
        "prepared_application_count": len(
            [row for row in persistent if row.get("work_application_id")]
        ),
        "ready_for_owner_review_count": len(ready_for_owner_review),
        "blocked_package_count": len(blocked_packages),
        "ready_for_owner_review": ready_for_owner_review,
        "blocked_packages": blocked_packages,
        "persistent_results": persistent,
        "external_action_taken": False,
        "external_submission": False,
        "agency_contact": False,
        "contract_acceptance": False,
        "financial_execution": False,
        "approval_required_before_submission": True,
        "continuous_worker": False,
    }
