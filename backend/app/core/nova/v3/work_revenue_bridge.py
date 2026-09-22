"""Bridge live multi-source discovery into the persistent Nova Work & Revenue store.

No external submission, client contact, contract acceptance, invoicing, payment,
Stripe, or financial execution is performed here.
Approval remains separate from submission.
"""
from __future__ import annotations

import re
from typing import Any

from sqlalchemy.orm import Session

from app.auth import UserContext
from app.core.nova.work_revenue import service as work_service
from app.core.nova.work_revenue.schemas import ApplicationCreate, OpportunityCreate
from app.core.nova.v3.live_qualification import (
    OUTCOME_NEEDS_OWNER_REVIEW,
    OUTCOME_NOT_QUALIFIED,
    OUTCOME_QUALIFIED,
)

_MONEY_RE = re.compile(r"\$\s*([0-9][0-9,]*(?:\.\d+)?)")


def _amount_from_job(job: dict[str, Any]) -> float | None:
    """Extract a numeric amount when present. Never invent a compensation period."""
    raw = str(job.get("compensation_text") or "").strip()
    match = _MONEY_RE.search(raw)
    if not match:
        return None
    try:
        return float(match.group(1).replace(",", ""))
    except ValueError:
        return None


def _live_status(job: dict[str, Any]) -> str:
    return str(
        (job.get("live_qualification") or {}).get("qualification_status")
        or job.get("qualification_status")
        or ""
    )


def _compensation_note(job: dict[str, Any]) -> str:
    raw = str(job.get("compensation_text") or "").strip()
    if not raw:
        return "Compensation period unknown; raw listing text unavailable."
    return f"Raw compensation text preserved (period not inferred): {raw}"


def persist_live_job(
    db: Session,
    job: dict[str, Any],
    *,
    organization_id: str,
    user: UserContext,
    prepare_application: bool = False,
) -> dict[str, Any]:
    title = str(job.get("title") or "").strip()
    company = str(job.get("company_name") or job.get("client") or "").strip()
    source_url = str(job.get("source_url") or "").strip() or None
    provider_id = str(job.get("provider_id") or "live_discovery").strip()[:80] or "live_discovery"
    if not title or not company:
        return {
            "persisted": False,
            "reason": "missing_title_or_company",
            "work_opportunity_id": None,
            "work_application_id": None,
            "ready_for_owner_review": False,
            "package_review_status": None,
            "package_review_blocker": None,
            "externally_submitted": False,
            "financial_execution": False,
            "client_contacted": False,
            "contract_accepted": False,
        }

    existing = work_service.get_opportunity_by_fingerprint(
        db,
        organization_id=organization_id,
        user=user,
        company_name=company,
        opportunity_title=title,
        source_url=source_url,
    )
    created = existing is None
    if existing is None:
        amount = _amount_from_job(job)
        live_qual = dict(job.get("live_qualification") or {})
        payload = OpportunityCreate(
            organization_id=organization_id,
            source=provider_id,
            source_url=source_url,
            source_type="approved_api",
            company_name=company,
            opportunity_title=title,
            description=str(job.get("description") or "") or None,
            location=str(job.get("geography") or "")[:220] or None,
            remote_status=str(job.get("remote_status") or "unknown")[:40],
            engagement_type=str(job.get("job_type") or job.get("contract_type") or "unknown")[:40],
            compensation_type="listed" if amount is not None else "unknown",
            compensation_amount=amount,
            compensation_period=None,
            currency="USD",
            requirements=None,
            skills_required=[],
            credentials_required=[],
            physical_presence_required=(
                "false" if str(job.get("remote_status") or "").lower() == "remote" else "unknown"
            ),
            notes=(
                "Live multi-source discovery. "
                f"Provider={provider_id}; "
                f"live_qualification={live_qual.get('qualification_status') or job.get('qualification_status') or 'unknown'}; "
                f"{_compensation_note(job)}; "
                "External submission remains OFF. Approval does not equal submission."
            )[:4000],
            estimated_value=amount,
            category="external_paid_work",
            priority="high" if _live_status(job) == OUTCOME_QUALIFIED else "normal",
            tags=[
                "live_discovery",
                provider_id[:60],
                str(job.get("qualification_status") or "unclassified")[:60],
            ],
        )
        try:
            existing = work_service.create_discovered_opportunity(
                db,
                payload,
                organization_id=organization_id,
                user=user,
            )
        except work_service.NovaWorkError as exc:
            if getattr(exc, "status_code", 400) != 409:
                raise
            existing = work_service.get_opportunity_by_fingerprint(
                db,
                organization_id=organization_id,
                user=user,
                company_name=company,
                opportunity_title=title,
                source_url=source_url,
            )
            if existing is None:
                raise
            created = False

    work_row, work_qualification = work_service.qualify(
        db,
        existing.opportunity_id,
        organization_id=organization_id,
        user=user,
    )

    application = work_service.get_application_for_opportunity(
        db,
        work_row.opportunity_id,
        organization_id=organization_id,
        user=user,
    )

    live_status = _live_status(job)
    package_review_status = None
    package_review_blocker = None

    # Only QUALIFIED live outcomes may auto-create application workspaces.
    if (
        prepare_application
        and live_status == OUTCOME_QUALIFIED
        and work_row.status not in {"NOT_QUALIFIED", "CLOSED", "REJECTED"}
    ):
        if application is None:
            try:
                application = work_service.create_application(
                    db,
                    ApplicationCreate(
                        organization_id=organization_id,
                        opportunity_id=work_row.opportunity_id,
                        applicant_party="AMICOR",
                        notes=(
                            "Prepared automatically from a QUALIFIED live discovery result. "
                            "Nothing submitted externally. Owner approval remains separate."
                        ),
                    ),
                    organization_id=organization_id,
                    user=user,
                )
            except work_service.NovaWorkError as exc:
                if getattr(exc, "status_code", 400) != 409:
                    raise
                application = work_service.get_application_for_opportunity(
                    db,
                    work_row.opportunity_id,
                    organization_id=organization_id,
                    user=user,
                )

        if application is not None and application.approval_state in {"DRAFT", "NEEDS_CHANGES"}:
            try:
                application = work_service.mark_ready_for_review(
                    db,
                    application.application_id,
                    organization_id=organization_id,
                    user=user,
                )
                package_review_status = "READY"
            except work_service.NovaWorkError as exc:
                # Honest blocker: stay DRAFT / NEEDS_CHANGES; do not force READY.
                package_review_status = "BLOCKED"
                package_review_blocker = str(exc)
                review = work_service.get_application_package_review(
                    db,
                    application.application_id,
                    organization_id=organization_id,
                    user=user,
                )
                package_review_status = review.get("status") or package_review_status
                if review.get("blockers"):
                    package_review_blocker = ", ".join(review.get("blockers") or [])
    elif live_status == OUTCOME_NEEDS_OWNER_REVIEW:
        package_review_status = "HELD_FOR_OWNER_REVIEW"
    elif live_status == OUTCOME_NOT_QUALIFIED:
        package_review_status = "SKIPPED_NOT_QUALIFIED"

    return {
        "persisted": True,
        "created": created,
        "provider_id": provider_id,
        "live_qualification_status": live_status or None,
        "work_opportunity_id": work_row.opportunity_id,
        "work_status": work_row.status,
        "work_qualification_outcome": work_qualification.get("outcome"),
        "work_application_id": application.application_id if application else None,
        "application_state": application.approval_state if application else None,
        "ready_for_owner_review": bool(
            application and application.approval_state == "READY_FOR_OWNER_REVIEW"
        ),
        "package_review_status": package_review_status,
        "package_review_blocker": package_review_blocker,
        "externally_submitted": False,
        "financial_execution": False,
        "client_contacted": False,
        "contract_accepted": False,
        "invoice_created": False,
        "stripe_action": False,
    }


def persist_ranked_jobs(
    db: Session,
    jobs: list[dict[str, Any]],
    *,
    organization_id: str,
    user: UserContext,
    prepare_applications: bool = False,
    prepare_limit: int | None = None,
) -> list[dict[str, Any]]:
    results: list[dict[str, Any]] = []
    prepared = 0
    limit = prepare_limit if prepare_limit is not None else len(jobs)
    for job in jobs:
        live_status = _live_status(job)
        should_prepare = (
            prepare_applications
            and live_status == OUTCOME_QUALIFIED
            and prepared < max(0, int(limit))
        )
        result = persist_live_job(
            db,
            job,
            organization_id=organization_id,
            user=user,
            prepare_application=should_prepare,
        )
        if should_prepare and result.get("work_application_id"):
            prepared += 1
        results.append(result)
    return results
