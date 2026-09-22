"""Bridge live multi-source discovery into the persistent Nova Work & Revenue store.

No external submission, client contact, contract acceptance, invoicing, payment,
Stripe, or financial execution is performed here.
"""
from __future__ import annotations

import re
from typing import Any

from sqlalchemy.orm import Session

from app.auth import UserContext
from app.core.nova.work_revenue import service as work_service
from app.core.nova.work_revenue.schemas import ApplicationCreate, OpportunityCreate
from app.core.nova.v3.live_qualification import OUTCOME_QUALIFIED

_MONEY_RE = re.compile(r"\$\s*([0-9][0-9,]*(?:\.\d+)?)")


def _amount_from_job(job: dict[str, Any]) -> float | None:
    raw = str(job.get("compensation_text") or "").strip()
    match = _MONEY_RE.search(raw)
    if not match:
        return None
    try:
        return float(match.group(1).replace(",", ""))
    except ValueError:
        return None


def _find_existing(
    db: Session,
    *,
    organization_id: str,
    user: UserContext,
    source_url: str | None,
    company_name: str,
    title: str,
):
    for row in work_service.list_opportunities(
        db,
        organization_id=organization_id,
        user=user,
        limit=500,
        offset=0,
    ):
        if source_url and row.source_url and row.source_url == source_url:
            return row
        if (
            str(row.company_name or "").strip().lower() == company_name.strip().lower()
            and str(row.opportunity_title or "").strip().lower() == title.strip().lower()
        ):
            return row
    return None


def persist_live_job(
    db: Session,
    job: dict[str, Any],
    *,
    organization_id: str,
    user: UserContext,
) -> dict[str, Any]:
    title = str(job.get("title") or "").strip()
    company = str(job.get("company_name") or job.get("client") or "").strip()
    source_url = str(job.get("source_url") or "").strip() or None
    if not title or not company:
        return {
            "persisted": False,
            "reason": "missing_title_or_company",
            "work_opportunity_id": None,
            "work_application_id": None,
            "ready_for_owner_review": False,
        }

    existing = _find_existing(
        db,
        organization_id=organization_id,
        user=user,
        source_url=source_url,
        company_name=company,
        title=title,
    )
    created = existing is None
    if existing is None:
        amount = _amount_from_job(job)
        live_qual = dict(job.get("live_qualification") or {})
        payload = OpportunityCreate(
            organization_id=organization_id,
            source=str(job.get("provider_id") or "live_discovery")[:80],
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
            physical_presence_required="false" if str(job.get("remote_status") or "").lower() == "remote" else "unknown",
            notes=(
                "Live multi-source discovery. "
                f"Provider={job.get('provider_id') or 'unknown'}; "
                f"live_qualification={live_qual.get('qualification_status') or job.get('qualification_status') or 'unknown'}; "
                "External submission remains OFF."
            )[:4000],
            estimated_value=amount,
            category="external_paid_work",
            priority="high" if str(job.get("qualification_status") or "") == OUTCOME_QUALIFIED else "normal",
            tags=[
                "live_discovery",
                str(job.get("provider_id") or "unknown")[:60],
                str(job.get("qualification_status") or "unclassified")[:60],
            ],
        )
        existing = work_service.create_discovered_opportunity(
            db,
            payload,
            organization_id=organization_id,
            user=user,
        )

    work_row, work_qualification = work_service.qualify(
        db,
        existing.opportunity_id,
        organization_id=organization_id,
        user=user,
    )

    application = next(
        (
            item
            for item in work_service.list_applications(
                db,
                organization_id=organization_id,
                user=user,
                limit=500,
            )
            if item.opportunity_id == work_row.opportunity_id
        ),
        None,
    )

    live_status = str(
        (job.get("live_qualification") or {}).get("qualification_status")
        or job.get("qualification_status")
        or ""
    )
    if live_status == OUTCOME_QUALIFIED and work_row.status not in {"NOT_QUALIFIED", "CLOSED", "REJECTED"}:
        if application is None:
            application = work_service.create_application(
                db,
                ApplicationCreate(
                    organization_id=organization_id,
                    opportunity_id=work_row.opportunity_id,
                    applicant_party="AMICOR",
                    notes="Prepared automatically from a QUALIFIED live discovery result. Nothing submitted externally.",
                ),
                organization_id=organization_id,
                user=user,
            )
        if application.approval_state in {"DRAFT", "NEEDS_CHANGES"}:
            try:
                application = work_service.mark_ready_for_review(
                    db,
                    application.application_id,
                    organization_id=organization_id,
                    user=user,
                )
            except work_service.NovaWorkError:
                pass

    return {
        "persisted": True,
        "created": created,
        "work_opportunity_id": work_row.opportunity_id,
        "work_status": work_row.status,
        "work_qualification_outcome": work_qualification.get("outcome"),
        "work_application_id": application.application_id if application else None,
        "application_state": application.approval_state if application else None,
        "ready_for_owner_review": bool(
            application and application.approval_state == "READY_FOR_OWNER_REVIEW"
        ),
        "externally_submitted": False,
        "financial_execution": False,
    }


def persist_ranked_jobs(
    db: Session,
    jobs: list[dict[str, Any]],
    *,
    organization_id: str,
    user: UserContext,
) -> list[dict[str, Any]]:
    return [
        persist_live_job(
            db,
            job,
            organization_id=organization_id,
            user=user,
        )
        for job in jobs
    ]
