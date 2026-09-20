"""Nova V3 HTTP lab. Synthetic only. No live connectors or money movement."""
from __future__ import annotations

import os
from datetime import datetime
from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from fastapi.encoders import jsonable_encoder
from pydantic import BaseModel, Field

from app.auth import OPERATOR_ACCOUNT_GRANTS, UserContext, get_current_user_context
from app.core.nova.router import require_nova_access
from app.core.nova.service import NovaCoreService
from app.core.nova.v3.errors import V3Error
from app.core.nova.v3.capability_catalog import capability_catalog, capability_search_queries
from app.core.nova.v3.execution_playbooks import execution_playbook, execution_playbooks
from app.core.nova.v3.flags import live_flags
from app.core.nova.v3.kernel import get_kernel, reset_kernel
from app.core.nova.v3.live_discovery import search_remote_jobs
from app.core.nova.v3.live_qualification import (
    OUTCOME_NEEDS_OWNER_REVIEW,
    OUTCOME_NOT_QUALIFIED,
    OUTCOME_QUALIFIED,
    partition_by_qualification,
    qualify_and_rank_live_jobs,
)
from app.core.nova.v3.growth.kernel import get_growth_kernel

def _nova_v3_owner_emails() -> set[str]:
    configured = str(os.getenv("NOVA_V3_OWNER_EMAILS") or "").strip()
    if configured:
        return {item.strip().lower() for item in configured.split(",") if item.strip()}
    owners = {
        str(grant.get("email") or "").strip().lower()
        for grant in OPERATOR_ACCOUNT_GRANTS
        if str(grant.get("email") or "").strip()
    }
    if os.getenv("PYTEST_CURRENT_TEST"):
        owners.update({
            "admin@amicor.local",
            "dispatcher@amicor.local",
            "staff@amicor.local",
        })
    return owners


def require_nova_v3_owner_access(
    user: UserContext = Depends(get_current_user_context),
) -> UserContext:
    if str(user.email or "").strip().lower() not in _nova_v3_owner_emails():
        raise HTTPException(status_code=403, detail="Nova owner access required")
    return user


router = APIRouter(
    prefix="/api/nova/v3",
    tags=["nova-v3-owner"],
    dependencies=[Depends(require_nova_access), Depends(require_nova_v3_owner_access)],
)


class OrgIn(BaseModel):
    organization_id: str | None = None


class IngestIn(OrgIn):
    provider_id: str


class LiveJobSearchIn(OrgIn):
    query: str
    limit: int = Field(default=10, ge=1, le=25)


class LiveJobDiscoverIn(LiveJobSearchIn):
    save_limit: int = Field(default=5, ge=1, le=10)
    min_relevance_score: int = Field(default=6, ge=0, le=100)


class LiveJobPrepareIn(LiveJobDiscoverIn):
    prepare_limit: int = Field(default=3, ge=1, le=5)


class ManualOpportunityIn(OrgIn):
    title: str
    company_name: str
    description: str
    compensation_amount: float | None = None
    compensation_type: str = "fixed"
    remote_status: str = "remote"
    source_url: str | None = None
    login_required: bool = False
    captcha_required: bool = False


class ProposalIn(OrgIn):
    opportunity_id: str


class ApprovalIn(OrgIn):
    action: str
    target_id: str
    payload: dict[str, Any] = Field(default_factory=dict)
    idempotency_key: str | None = None
    expires_at: datetime | None = None


class DecisionIn(OrgIn):
    decision: str


class MockSubmitIn(OrgIn):
    approval_id: str


class LiveSubmitIn(OrgIn):
    approval_id: str


class WorkIn(OrgIn):
    engagement_id: str
    work_type: str
    source_inputs: dict[str, Any] = Field(default_factory=dict)
    approval_id: str


class MessageIn(OrgIn):
    channel: str
    body: str


class SendMessageIn(OrgIn):
    approval_id: str


class JobIn(OrgIn):
    kind: str
    timezone_name: str
    frequency: str = "daily"


class InvoiceIn(OrgIn):
    engagement_id: str
    amount: float
    kind: str = "fixed"


class InvoiceApproveIn(OrgIn):
    approval_id: str


class PaymentEventIn(OrgIn):
    event_id: str
    invoice_id: str | None = None
    amount: float
    event_type: str = "payment"
    occurred_at: datetime | None = None


class ConfirmIn(OrgIn):
    total_received_so_far: float
    idempotency_key: str | None = None


class CorrectionIn(OrgIn):
    original_amount: float
    corrected_amount: float
    reason: str
    authorized: bool = False
    idempotency_key: str


class CredentialIn(OrgIn):
    provider: str
    credential_type: str = "oauth"
    authorization_scope: str = "readonly"
    refresh_capable: bool = True
    owner_approved: bool = False


class LabActionIn(OrgIn):
    action: str
    payload: dict[str, Any] = Field(default_factory=dict)


class ConnectorIn(OrgIn):
    kind: str
    state: str = "CONNECTED"


class WebhookIn(OrgIn):
    provider: str
    event_id: str
    payload: dict[str, Any] = Field(default_factory=dict)
    signature: str = ""


class WorkerTickIn(OrgIn):
    worker_id: str = "worker-a"


def _org(user: UserContext, requested: str | None) -> str:
    try:
        return NovaCoreService.resolve_organization_scope(user, requested)
    except ValueError as exc:
        message = str(exc)
        status = 403 if "Cross-tenant" in message else 400
        raise HTTPException(status_code=status, detail=message) from exc


def _raise(exc: V3Error) -> None:
    raise HTTPException(status_code=exc.http_status, detail={"code": exc.code, "reason": str(exc)}) from exc


@router.get("/owner-access")
def v3_owner_access(user: UserContext = Depends(get_current_user_context)):
    return {"owner_access": True, "email": user.email}


@router.get("/guardrails")
def v3_guardrails(user: UserContext = Depends(get_current_user_context)):
    from app.core.nova.work_revenue.flags import discovery_diagnostics

    flags = live_flags()
    diag = discovery_diagnostics()
    return {
        **flags,
        "discovery_diagnostics": {
            "live_discovery_enabled": bool(diag.get("live_discovery_enabled")),
            "discovery_provider_configured": bool(diag.get("discovery_provider_configured")),
            "discovery_provider": diag.get("discovery_provider"),
            "authenticated": True,
            "discovery_execution_status": "ready" if diag.get("live_discovery_enabled") else "disabled",
            "result_count": None,
            "error_category": None if diag.get("live_discovery_enabled") else "flag_off",
            "auto_submit": False,
        },
    }


@router.get("/capabilities")
def v3_capabilities(user: UserContext = Depends(get_current_user_context)):
    """Read-only catalog of work Nova can perform and target in discovery."""
    return {
        "capabilities": capability_catalog(),
        "search_queries": capability_search_queries(),
        "external_submission": False,
        "financial_execution": False,
    }


@router.get("/execution-playbooks")
def v3_execution_playbooks(user: UserContext = Depends(get_current_user_context)):
    """Read-only execution instructions for Nova sellable capabilities."""
    return {
        "playbooks": execution_playbooks(),
        "external_submission": False,
        "financial_execution": False,
    }


@router.get("/execution-playbooks/{capability_id}")
def v3_execution_playbook(capability_id: str, user: UserContext = Depends(get_current_user_context)):
    row = execution_playbook(capability_id)
    if row is None:
        raise HTTPException(status_code=404, detail="Unknown Nova capability")
    return row


@router.get("/connectors")
def v3_connectors(user: UserContext = Depends(get_current_user_context)):
    return get_kernel().diagnostics(organization_id="unused", owner_user_id=user.user_id)["adapter_registry"]


@router.post("/live/jobs/search")
def v3_live_job_search(
    payload: LiveJobSearchIn,
    user: UserContext = Depends(get_current_user_context),
):
    _org(user, payload.organization_id)
    try:
        raw_jobs = search_remote_jobs(payload.query, limit=payload.limit)
        ranked = qualify_and_rank_live_jobs(payload.query, raw_jobs)
        return {
            "query": payload.query,
            "count": len(ranked),
            "source": "Remotive",
            "read_only": True,
            "external_action_taken": False,
            "jobs": ranked,
        }
    except V3Error as exc:
        _raise(exc)


@router.post("/live/jobs/discover")
def v3_live_job_discover(
    payload: LiveJobDiscoverIn,
    user: UserContext = Depends(get_current_user_context),
):
    org_id = _org(user, payload.organization_id)
    try:
        raw_jobs = search_remote_jobs(payload.query, limit=payload.limit)
        ranked = qualify_and_rank_live_jobs(payload.query, raw_jobs)
        selected = [
            job for job in ranked
            if int(job.get("relevance_score") or 0) >= payload.min_relevance_score
        ][: payload.save_limit]
        saved = get_kernel().ingest_live_jobs(
            selected,
            organization_id=org_id,
            owner_user_id=user.user_id,
        )
        buckets = partition_by_qualification(selected)
        return {
            "query": payload.query,
            "source": "Remotive",
            "read_only_discovery": True,
            "external_action_taken": False,
            "ranked_count": len(ranked),
            "selected_count": len(selected),
            "qualification_counts": {
                OUTCOME_QUALIFIED: len(buckets[OUTCOME_QUALIFIED]),
                OUTCOME_NEEDS_OWNER_REVIEW: len(buckets[OUTCOME_NEEDS_OWNER_REVIEW]),
                OUTCOME_NOT_QUALIFIED: len(buckets[OUTCOME_NOT_QUALIFIED]),
            },
            "ranked_jobs": ranked,
            "saved": saved,
        }
    except V3Error as exc:
        _raise(exc)


@router.post("/live/jobs/prepare")
def v3_live_job_prepare(
    payload: LiveJobPrepareIn,
    user: UserContext = Depends(get_current_user_context),
):
    org_id = _org(user, payload.organization_id)
    try:
        raw_jobs = search_remote_jobs(payload.query, limit=payload.limit)
        ranked = qualify_and_rank_live_jobs(payload.query, raw_jobs)
        selected = [
            job for job in ranked
            if int(job.get("relevance_score") or 0) >= payload.min_relevance_score
        ][: payload.save_limit]
        # Retain QUALIFIED, NEEDS_OWNER_REVIEW, and NOT_QUALIFIED for audit/history.
        saved = get_kernel().ingest_live_jobs(
            selected,
            organization_id=org_id,
            owner_user_id=user.user_id,
        )

        prepared = []
        skipped_not_qualified = []
        held_for_owner_review = []
        for opportunity in saved["created"]:
            status = str(
                (opportunity.get("live_qualification") or {}).get("qualification_status")
                or opportunity.get("qualification_status")
                or ""
            )
            if status == OUTCOME_NOT_QUALIFIED:
                skipped_not_qualified.append(opportunity["opportunity_id"])
                continue
            if status == OUTCOME_NEEDS_OWNER_REVIEW:
                held_for_owner_review.append(opportunity["opportunity_id"])
                continue
            if status != OUTCOME_QUALIFIED:
                held_for_owner_review.append(opportunity["opportunity_id"])
                continue
            if len(prepared) >= payload.prepare_limit:
                continue
            proposal = get_kernel().prepare_proposal(
                opportunity["opportunity_id"],
                organization_id=org_id,
                owner_user_id=user.user_id,
            )
            approval = get_kernel().request_approval(
                organization_id=org_id,
                owner_user_id=user.user_id,
                action="OPPORTUNITY_APPROVE",
                target_id=proposal.proposal_id,
                payload={"proposal_id": proposal.proposal_id},
                idempotency_key=f"live-job-proposal:{proposal.proposal_id}",
            )
            prepared.append(
                {
                    "opportunity": opportunity,
                    "proposal": jsonable_encoder(proposal),
                    "approval": jsonable_encoder(approval),
                }
            )

        buckets = partition_by_qualification(selected)
        return {
            "query": payload.query,
            "source": "Remotive",
            "external_action_taken": False,
            "financial_execution": False,
            "ranked_count": len(ranked),
            "selected_count": len(selected),
            "prepared_count": len(prepared),
            "prepared": prepared,
            "duplicates": saved["duplicates"],
            "saved": saved,
            "qualification_counts": {
                OUTCOME_QUALIFIED: len(buckets[OUTCOME_QUALIFIED]),
                OUTCOME_NEEDS_OWNER_REVIEW: len(buckets[OUTCOME_NEEDS_OWNER_REVIEW]),
                OUTCOME_NOT_QUALIFIED: len(buckets[OUTCOME_NOT_QUALIFIED]),
            },
            "auto_prepared_only_qualified": True,
            "held_for_owner_review": held_for_owner_review,
            "skipped_not_qualified": skipped_not_qualified,
            "ranked_jobs": ranked,
        }
    except V3Error as exc:
        _raise(exc)


@router.post("/ingest")
def v3_ingest(payload: IngestIn, user: UserContext = Depends(get_current_user_context)):
    try:
        return get_kernel().ingest(
            payload.provider_id, organization_id=_org(user, payload.organization_id), owner_user_id=user.user_id
        )
    except V3Error as exc:
        _raise(exc)


@router.post("/opportunities/manual")
def v3_manual(payload: ManualOpportunityIn, user: UserContext = Depends(get_current_user_context)):
    try:
        row = get_kernel().enter_manual(
            payload.model_dump(), organization_id=_org(user, payload.organization_id), owner_user_id=user.user_id
        )
        return get_kernel().opportunity_out(row)
    except V3Error as exc:
        _raise(exc)


@router.get("/opportunities")
def v3_opportunities(organization_id: str | None = None, user: UserContext = Depends(get_current_user_context)):
    org = _org(user, organization_id)
    return [get_kernel().opportunity_out(item) for item in get_kernel().list_opportunities(organization_id=org, owner_user_id=user.user_id)]


@router.post("/proposals")
def v3_proposal(payload: ProposalIn, user: UserContext = Depends(get_current_user_context)):
    try:
        row = get_kernel().prepare_proposal(
            payload.opportunity_id, organization_id=_org(user, payload.organization_id), owner_user_id=user.user_id
        )
        return jsonable_encoder(row)
    except V3Error as exc:
        _raise(exc)


@router.post("/approvals")
def v3_request_approval(payload: ApprovalIn, user: UserContext = Depends(get_current_user_context)):
    try:
        row = get_kernel().request_approval(
            organization_id=_org(user, payload.organization_id),
            owner_user_id=user.user_id,
            action=payload.action,
            target_id=payload.target_id,
            payload=payload.payload,
            expires_at=payload.expires_at,
            idempotency_key=payload.idempotency_key,
        )
        return jsonable_encoder(row)
    except V3Error as exc:
        _raise(exc)


@router.post("/approvals/{approval_id}/decide")
def v3_decide(approval_id: str, payload: DecisionIn, user: UserContext = Depends(get_current_user_context)):
    try:
        return jsonable_encoder(
            get_kernel().decide_approval(
                approval_id,
                organization_id=_org(user, payload.organization_id),
                owner_user_id=user.user_id,
                decision=payload.decision,
            )
        )
    except V3Error as exc:
        _raise(exc)


@router.post("/approvals/{approval_id}/revoke")
def v3_revoke(approval_id: str, payload: OrgIn | None = None, user: UserContext = Depends(get_current_user_context)):
    body = payload or OrgIn()
    try:
        return jsonable_encoder(
            get_kernel().revoke_approval(
                approval_id, organization_id=_org(user, body.organization_id), owner_user_id=user.user_id
            )
        )
    except V3Error as exc:
        _raise(exc)


@router.post("/proposals/{proposal_id}/live-submit")
def v3_live_submit(
    proposal_id: str,
    payload: LiveSubmitIn,
    user: UserContext = Depends(get_current_user_context),
):
    try:
        return get_kernel().live_submit(
            proposal_id,
            organization_id=_org(user, payload.organization_id),
            owner_user_id=user.user_id,
            approval_id=payload.approval_id,
        )
    except V3Error as exc:
        _raise(exc)


@router.post("/proposals/{proposal_id}/mock-submit")
def v3_mock_submit(proposal_id: str, payload: MockSubmitIn, user: UserContext = Depends(get_current_user_context)):
    try:
        return jsonable_encoder(
            get_kernel().mock_submit(
                proposal_id,
                organization_id=_org(user, payload.organization_id),
                owner_user_id=user.user_id,
                approval_id=payload.approval_id,
            )
        )
    except V3Error as exc:
        _raise(exc)


@router.post("/proposals/{proposal_id}/synthetic-accept")
def v3_accept(proposal_id: str, payload: OrgIn | None = None, user: UserContext = Depends(get_current_user_context)):
    body = payload or OrgIn()
    try:
        return jsonable_encoder(
            get_kernel().accept_synthetic(
                proposal_id, organization_id=_org(user, body.organization_id), owner_user_id=user.user_id
            )
        )
    except V3Error as exc:
        _raise(exc)


@router.post("/work-items")
def v3_work(payload: WorkIn, user: UserContext = Depends(get_current_user_context)):
    try:
        return jsonable_encoder(
            get_kernel().create_work_item(
                organization_id=_org(user, payload.organization_id),
                owner_user_id=user.user_id,
                engagement_id=payload.engagement_id,
                work_type=payload.work_type,
                source_inputs=payload.source_inputs,
                approval_id=payload.approval_id,
            )
        )
    except V3Error as exc:
        _raise(exc)


@router.post("/work-items/{work_item_id}/execute")
def v3_execute(work_item_id: str, payload: OrgIn | None = None, user: UserContext = Depends(get_current_user_context)):
    body = payload or OrgIn()
    try:
        return jsonable_encoder(
            get_kernel().execute_work(
                work_item_id, organization_id=_org(user, body.organization_id), owner_user_id=user.user_id
            )
        )
    except V3Error as exc:
        _raise(exc)


@router.post("/work-items/{work_item_id}/approve")
def v3_approve_del(work_item_id: str, payload: OrgIn | None = None, user: UserContext = Depends(get_current_user_context)):
    body = payload or OrgIn()
    try:
        return jsonable_encoder(
            get_kernel().owner_approve_deliverable(
                work_item_id, organization_id=_org(user, body.organization_id), owner_user_id=user.user_id
            )
        )
    except V3Error as exc:
        _raise(exc)


@router.post("/work-items/{work_item_id}/mock-deliver")
def v3_mock_del(work_item_id: str, payload: OrgIn | None = None, user: UserContext = Depends(get_current_user_context)):
    body = payload or OrgIn()
    try:
        return jsonable_encoder(
            get_kernel().mock_deliver(
                work_item_id, organization_id=_org(user, body.organization_id), owner_user_id=user.user_id
            )
        )
    except V3Error as exc:
        _raise(exc)


@router.post("/messages")
def v3_message(payload: MessageIn, user: UserContext = Depends(get_current_user_context)):
    try:
        return jsonable_encoder(
            get_kernel().prepare_message(
                organization_id=_org(user, payload.organization_id),
                owner_user_id=user.user_id,
                channel=payload.channel,
                body=payload.body,
            )
        )
    except V3Error as exc:
        _raise(exc)


@router.post("/messages/{message_id}/mock-send")
def v3_send(message_id: str, payload: SendMessageIn, user: UserContext = Depends(get_current_user_context)):
    try:
        return jsonable_encoder(
            get_kernel().send_mock(
                message_id,
                organization_id=_org(user, payload.organization_id),
                owner_user_id=user.user_id,
                approval_id=payload.approval_id,
            )
        )
    except V3Error as exc:
        _raise(exc)


@router.post("/jobs")
def v3_job(payload: JobIn, user: UserContext = Depends(get_current_user_context)):
    try:
        return jsonable_encoder(
            get_kernel().schedule_job(
                organization_id=_org(user, payload.organization_id),
                owner_user_id=user.user_id,
                kind=payload.kind,
                timezone_name=payload.timezone_name,
                frequency=payload.frequency,
            )
        )
    except V3Error as exc:
        _raise(exc)


@router.post("/invoices")
def v3_invoice(payload: InvoiceIn, user: UserContext = Depends(get_current_user_context)):
    try:
        return jsonable_encoder(
            get_kernel().create_invoice(
                organization_id=_org(user, payload.organization_id),
                owner_user_id=user.user_id,
                engagement_id=payload.engagement_id,
                amount=payload.amount,
                kind=payload.kind,
            )
        )
    except V3Error as exc:
        _raise(exc)


@router.post("/invoices/{invoice_id}/approve")
def v3_inv_approve(invoice_id: str, payload: InvoiceApproveIn, user: UserContext = Depends(get_current_user_context)):
    try:
        return jsonable_encoder(
            get_kernel().approve_invoice(
                invoice_id,
                organization_id=_org(user, payload.organization_id),
                owner_user_id=user.user_id,
                approval_id=payload.approval_id,
            )
        )
    except V3Error as exc:
        _raise(exc)


@router.post("/invoices/{invoice_id}/mock-deliver")
def v3_inv_deliver(invoice_id: str, payload: OrgIn | None = None, user: UserContext = Depends(get_current_user_context)):
    body = payload or OrgIn()
    try:
        return jsonable_encoder(
            get_kernel().mock_deliver_invoice(
                invoice_id, organization_id=_org(user, body.organization_id), owner_user_id=user.user_id
            )
        )
    except V3Error as exc:
        _raise(exc)


@router.post("/payments/events")
def v3_event(payload: PaymentEventIn, user: UserContext = Depends(get_current_user_context)):
    try:
        return jsonable_encoder(
            get_kernel().ingest_payment_event(
                organization_id=_org(user, payload.organization_id),
                owner_user_id=user.user_id,
                event_id=payload.event_id,
                invoice_id=payload.invoice_id,
                amount=payload.amount,
                event_type=payload.event_type,
                occurred_at=payload.occurred_at or get_kernel().now,
            )
        )
    except V3Error as exc:
        _raise(exc)


@router.post("/engagements/{engagement_id}/confirm")
def v3_confirm(engagement_id: str, payload: ConfirmIn, user: UserContext = Depends(get_current_user_context)):
    try:
        return jsonable_encoder(
            get_kernel().confirm_received(
                engagement_id,
                organization_id=_org(user, payload.organization_id),
                owner_user_id=user.user_id,
                total_received_so_far=payload.total_received_so_far,
                idempotency_key=payload.idempotency_key,
            )
        )
    except V3Error as exc:
        _raise(exc)


@router.post("/engagements/{engagement_id}/corrections")
def v3_correct(engagement_id: str, payload: CorrectionIn, user: UserContext = Depends(get_current_user_context)):
    try:
        return jsonable_encoder(
            get_kernel().historical_correct(
                engagement_id,
                organization_id=_org(user, payload.organization_id),
                owner_user_id=user.user_id,
                original_amount=payload.original_amount,
                corrected_amount=payload.corrected_amount,
                reason=payload.reason,
                authorized=payload.authorized,
                idempotency_key=payload.idempotency_key,
            )
        )
    except V3Error as exc:
        _raise(exc)


@router.post("/credentials")
def v3_cred(payload: CredentialIn, user: UserContext = Depends(get_current_user_context)):
    try:
        return jsonable_encoder(
            get_kernel().register_credential(
                organization_id=_org(user, payload.organization_id),
                owner_user_id=user.user_id,
                provider=payload.provider,
                credential_type=payload.credential_type,
                authorization_scope=payload.authorization_scope,
                expires_at=None,
                refresh_capable=payload.refresh_capable,
                owner_approved=payload.owner_approved,
            )
        )
    except V3Error as exc:
        _raise(exc)


@router.get("/monitor")
def v3_monitor(organization_id: str | None = None, user: UserContext = Depends(get_current_user_context)):
    return get_kernel().diagnostics(organization_id=_org(user, organization_id), owner_user_id=user.user_id)


@router.get("/lab")
def v3_lab(organization_id: str | None = None, user: UserContext = Depends(get_current_user_context)):
    return jsonable_encoder(get_kernel().lab_snapshot(organization_id=_org(user, organization_id), owner_user_id=user.user_id))


@router.post("/lab/action")
def v3_lab_action(payload: LabActionIn, user: UserContext = Depends(get_current_user_context)):
    try:
        result = get_kernel().lab_action(
            payload.action,
            payload.payload,
            organization_id=_org(user, payload.organization_id),
            owner_user_id=user.user_id,
        )
        return jsonable_encoder(result)
    except V3Error as exc:
        _raise(exc)


@router.post("/jobs/{job_id}/pause")
def v3_pause_job(job_id: str, payload: OrgIn | None = None, user: UserContext = Depends(get_current_user_context)):
    body = payload or OrgIn()
    try:
        return jsonable_encoder(
            get_kernel().pause_job(job_id, organization_id=_org(user, body.organization_id), owner_user_id=user.user_id)
        )
    except V3Error as exc:
        _raise(exc)


@router.post("/jobs/{job_id}/resume")
def v3_resume_job(job_id: str, payload: OrgIn | None = None, user: UserContext = Depends(get_current_user_context)):
    body = payload or OrgIn()
    try:
        return jsonable_encoder(
            get_kernel().resume_job(job_id, organization_id=_org(user, body.organization_id), owner_user_id=user.user_id)
        )
    except V3Error as exc:
        _raise(exc)


@router.post("/jobs/{job_id}/retry")
def v3_retry_job(job_id: str, payload: OrgIn | None = None, user: UserContext = Depends(get_current_user_context)):
    body = payload or OrgIn()
    try:
        return jsonable_encoder(
            get_kernel().retry_job(job_id, organization_id=_org(user, body.organization_id), owner_user_id=user.user_id)
        )
    except V3Error as exc:
        _raise(exc)


@router.post("/workers/tick")
def v3_tick(payload: WorkerTickIn, user: UserContext = Depends(get_current_user_context)):
    try:
        return jsonable_encoder(
            get_kernel().tick_worker(
                organization_id=_org(user, payload.organization_id),
                owner_user_id=user.user_id,
                worker_id=payload.worker_id,
            )
        )
    except V3Error as exc:
        _raise(exc)


@router.post("/simulated-connectors")
def v3_sim_connector(payload: ConnectorIn, user: UserContext = Depends(get_current_user_context)):
    try:
        return jsonable_encoder(
            get_kernel().register_connector(
                organization_id=_org(user, payload.organization_id),
                owner_user_id=user.user_id,
                kind=payload.kind,
                state=payload.state,
            )
        )
    except V3Error as exc:
        _raise(exc)


@router.post("/webhooks/lab")
def v3_lab_webhook(payload: WebhookIn, user: UserContext = Depends(get_current_user_context)):
    try:
        return jsonable_encoder(
            get_kernel().ingest_lab_webhook(
                organization_id=_org(user, payload.organization_id),
                owner_user_id=user.user_id,
                provider=payload.provider,
                event_id=payload.event_id,
                payload=payload.payload,
                signature=payload.signature,
            )
        )
    except V3Error as exc:
        _raise(exc)


@router.post("/lab/reset")
def v3_reset(user: UserContext = Depends(get_current_user_context)):
    reset_kernel()
    return {"reset": True, "live_flags": live_flags()}


class LeadIn(OrgIn):
    organization_name: str
    contact_name: str = ""
    role_title: str = ""
    industry: str = ""
    geography: str = ""
    website: str | None = None
    email_placeholder: str | None = None
    phone_placeholder: str | None = None
    source: str = "manual"
    source_url: str | None = None
    business_need: str = ""
    product_fit: str = ""
    estimated_value: float | None = None
    urgency: str = "unspecified"
    consent_restrictions: list[str] = Field(default_factory=list)


class GrowthActionIn(OrgIn):
    lead_id: str | None = None
    kind: str | None = None
    message: str | None = None
    timezone_name: str | None = None
    service_id: str | None = None
    quote_kind: str = "standard"
    discount_pct: float = 0
    custom_amount: float | None = None
    approval_id: str | None = None
    decision: str | None = None
    session_id: str | None = None
    day: int = 0
    product: str | None = None
    industry: str | None = None
    location: str | None = None
    status: str | None = None
    source: str | None = None


@router.post("/growth/leads")
def growth_discover(payload: LeadIn, user: UserContext = Depends(get_current_user_context)):
    try:
        row = get_growth_kernel().discover(payload.model_dump(), organization_id=_org(user, payload.organization_id), owner_user_id=user.user_id)
        return get_growth_kernel().lead_out(row)
    except V3Error as exc:
        _raise(exc)


@router.post("/growth/leads/{lead_id}/qualify")
def growth_qualify(lead_id: str, payload: OrgIn | None = None, user: UserContext = Depends(get_current_user_context)):
    body = payload or OrgIn()
    try:
        return get_growth_kernel().lead_out(
            get_growth_kernel().qualify(lead_id, organization_id=_org(user, body.organization_id), owner_user_id=user.user_id)
        )
    except V3Error as exc:
        _raise(exc)


@router.post("/growth/leads/{lead_id}/convert")
def growth_convert(lead_id: str, payload: GrowthActionIn | None = None, user: UserContext = Depends(get_current_user_context)):
    body = payload or GrowthActionIn()
    try:
        row = get_growth_kernel().convert(
            lead_id,
            organization_id=_org(user, body.organization_id),
            owner_user_id=user.user_id,
            approval_id=body.approval_id,
        )
        return get_growth_kernel().customer_out(row)
    except V3Error as exc:
        _raise(exc)


@router.post("/growth/outreach")
def growth_outreach(payload: GrowthActionIn, user: UserContext = Depends(get_current_user_context)):
    try:
        row = get_growth_kernel().prepare_outreach(
            payload.lead_id or "",
            payload.kind or "introduction_email",
            organization_id=_org(user, payload.organization_id),
            owner_user_id=user.user_id,
        )
        return jsonable_encoder(row)
    except V3Error as exc:
        _raise(exc)


@router.post("/growth/mock-send/{message_id}")
def growth_send(message_id: str, payload: GrowthActionIn, user: UserContext = Depends(get_current_user_context)):
    try:
        return jsonable_encoder(
            get_growth_kernel().mock_send(
                message_id,
                organization_id=_org(user, payload.organization_id),
                owner_user_id=user.user_id,
                approval_id=payload.approval_id,
            )
        )
    except V3Error as exc:
        _raise(exc)


@router.post("/growth/inbound")
def growth_inbound(payload: GrowthActionIn, user: UserContext = Depends(get_current_user_context)):
    try:
        return get_growth_kernel().inbound(
            payload.session_id or "lab",
            payload.message or "",
            organization_id=_org(user, payload.organization_id),
            owner_user_id=user.user_id,
        )
    except V3Error as exc:
        _raise(exc)


@router.get("/growth/dashboard")
def growth_dashboard(organization_id: str | None = None, user: UserContext = Depends(get_current_user_context)):
    return get_growth_kernel().growth_dashboard(organization_id=_org(user, organization_id), owner_user_id=user.user_id)


@router.get("/growth/shield")
def growth_shield(organization_id: str | None = None, user: UserContext = Depends(get_current_user_context)):
    return get_growth_kernel().shield_dashboard(organization_id=_org(user, organization_id), owner_user_id=user.user_id)


@router.get("/growth/crm")
def growth_crm(organization_id: str | None = None, user: UserContext = Depends(get_current_user_context)):
    return get_growth_kernel().crm_views(organization_id=_org(user, organization_id), owner_user_id=user.user_id)
