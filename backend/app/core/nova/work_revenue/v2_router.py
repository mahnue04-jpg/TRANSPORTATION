"""Work & Revenue V2 HTTP surfaces. No live execution."""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.auth import UserContext, get_current_user_context
from app.core.nova.service import NovaCoreService
from app.core.nova.work_revenue.adapters.registry import adapter_inventory
from app.core.nova.work_revenue.config import capabilities_surface
from app.core.nova.work_revenue.managed import reconciliation as v1_reconciliation
from app.core.nova.work_revenue.safety import evaluate_live_action
from app.core.nova.work_revenue.service import NovaWorkError
from app.core.nova.work_revenue import v2_actions, v2_pilot, v2_revenue, v2_scheduler, v2_status
from app.core.nova.work_revenue.v2_idempotency import WEBHOOK_REUSE_CONTRACT
from app.db.session import get_db

router = APIRouter(prefix="/v2", tags=["nova-work-revenue-v2"])


class SupervisedActionCreate(BaseModel):
    organization_id: str | None = None
    action_type: str
    title: str | None = Field(default=None, max_length=220)
    summary: str | None = Field(default=None, max_length=2000)
    ref_type: str | None = Field(default=None, max_length=32)
    ref_id: str | None = Field(default=None, max_length=32)
    idempotency_key: str = Field(min_length=1, max_length=120)
    timezone: str | None = Field(default="America/Chicago", max_length=64)


class SupervisedActionNotes(BaseModel):
    organization_id: str | None = None
    notes: str | None = Field(default=None, max_length=2000)
    expires_at: str | None = None


class SchedulerPrepare(BaseModel):
    organization_id: str | None = None
    timezone: str | None = Field(default="America/Chicago", max_length=64)
    kinds: list[str] | None = None


class PaymentEventIn(BaseModel):
    organization_id: str | None = None
    entry_id: str | None = Field(default=None, max_length=32)
    engagement_id: str | None = Field(default=None, max_length=32)
    amount: float = Field(default=0, ge=0, le=1_000_000_000)
    currency: str | None = Field(default="USD", max_length=12)
    idempotency_key: str = Field(min_length=1, max_length=120)
    notes: str | None = Field(default=None, max_length=400)
    occurred_at: str | None = None


class HistoricalCorrectionIn(BaseModel):
    organization_id: str | None = None
    entry_id: str | None = Field(default=None, max_length=32)
    engagement_id: str | None = Field(default=None, max_length=32)
    amount: float = Field(default=0, ge=0, le=1_000_000_000)
    currency: str | None = Field(default="USD", max_length=12)
    idempotency_key: str = Field(min_length=1, max_length=120)
    reason: str = Field(min_length=8, max_length=400)


class SafetyProbe(BaseModel):
    organization_id: str | None = None
    action_type: str
    owner_approved: bool = False
    required_facts_available: bool = False
    terms_policy_satisfied: bool = False
    dry_run: bool = True


def _org(user: UserContext, requested: str | None) -> str:
    try:
        return NovaCoreService.resolve_organization_scope(user, requested)
    except ValueError as exc:
        message = str(exc)
        status = 403 if "Cross-tenant" in message else 400
        raise HTTPException(status_code=status, detail=message) from exc


def _raise(exc: Exception) -> None:
    if isinstance(exc, NovaWorkError):
        raise HTTPException(status_code=exc.status_code, detail=str(exc)) from exc
    raise exc


@router.get("/capabilities")
def v2_capabilities(user: UserContext = Depends(get_current_user_context)):
    surface = capabilities_surface()
    surface["adapters"] = adapter_inventory()
    return surface


@router.post("/safety/evaluate")
def v2_safety_evaluate(payload: SafetyProbe, user: UserContext = Depends(get_current_user_context)):
    _org(user, payload.organization_id)
    decision = evaluate_live_action(
        payload.action_type,
        tenant_authorized=True,
        owner_approved=payload.owner_approved,
        adapter_implemented=False,
        required_facts_available=payload.required_facts_available,
        terms_policy_satisfied=payload.terms_policy_satisfied,
        not_duplicated=True,
        dry_run=payload.dry_run,
    )
    return decision.as_dict()


@router.get("/actions")
def v2_list_actions(
    organization_id: str | None = None,
    status: str | None = None,
    limit: int | None = 100,
    user: UserContext = Depends(get_current_user_context),
    db: Session = Depends(get_db),
):
    return v2_actions.list_actions(
        db, organization_id=_org(user, organization_id), user=user, status=status, limit=limit or 100
    )


@router.get("/actions/board")
def v2_action_board(
    organization_id: str | None = None,
    user: UserContext = Depends(get_current_user_context),
    db: Session = Depends(get_db),
):
    return v2_actions.queue_board(db, organization_id=_org(user, organization_id), user=user)


@router.post("/actions")
def v2_create_action(
    payload: SupervisedActionCreate,
    user: UserContext = Depends(get_current_user_context),
    db: Session = Depends(get_db),
):
    try:
        return v2_actions.create_action(
            db, payload.model_dump(), organization_id=_org(user, payload.organization_id), user=user
        )
    except NovaWorkError as exc:
        _raise(exc)


@router.post("/actions/{supervised_action_id}/review")
def v2_review_action(
    supervised_action_id: str,
    payload: SupervisedActionNotes | None = None,
    user: UserContext = Depends(get_current_user_context),
    db: Session = Depends(get_db),
):
    body = payload or SupervisedActionNotes()
    try:
        return v2_actions.submit_for_review(
            db, supervised_action_id, organization_id=_org(user, body.organization_id), user=user
        )
    except NovaWorkError as exc:
        _raise(exc)


@router.post("/actions/{supervised_action_id}/approve")
def v2_approve_action(
    supervised_action_id: str,
    payload: SupervisedActionNotes | None = None,
    user: UserContext = Depends(get_current_user_context),
    db: Session = Depends(get_db),
):
    body = payload or SupervisedActionNotes()
    try:
        expires = None
        if body.expires_at:
            from datetime import datetime

            try:
                expires = datetime.fromisoformat(str(body.expires_at).replace("Z", "+00:00"))
            except ValueError as exc:
                raise NovaWorkError("expires_at must be ISO-8601") from exc
        return v2_actions.approve_action(
            db,
            supervised_action_id,
            organization_id=_org(user, body.organization_id),
            user=user,
            notes=body.notes,
            expires_at=expires,
        )
    except NovaWorkError as exc:
        _raise(exc)


@router.post("/actions/{supervised_action_id}/queue")
def v2_queue_action(
    supervised_action_id: str,
    payload: SupervisedActionNotes | None = None,
    user: UserContext = Depends(get_current_user_context),
    db: Session = Depends(get_db),
):
    body = payload or SupervisedActionNotes()
    try:
        return v2_actions.queue_action(
            db, supervised_action_id, organization_id=_org(user, body.organization_id), user=user
        )
    except NovaWorkError as exc:
        _raise(exc)


@router.post("/actions/{supervised_action_id}/cancel")
def v2_cancel_action(
    supervised_action_id: str,
    payload: SupervisedActionNotes | None = None,
    user: UserContext = Depends(get_current_user_context),
    db: Session = Depends(get_db),
):
    body = payload or SupervisedActionNotes()
    try:
        return v2_actions.cancel_action(
            db,
            supervised_action_id,
            organization_id=_org(user, body.organization_id),
            user=user,
            notes=body.notes,
        )
    except NovaWorkError as exc:
        _raise(exc)


@router.post("/actions/{supervised_action_id}/reject")
def v2_reject_action(
    supervised_action_id: str,
    payload: SupervisedActionNotes | None = None,
    user: UserContext = Depends(get_current_user_context),
    db: Session = Depends(get_db),
):
    body = payload or SupervisedActionNotes()
    try:
        return v2_actions.reject_action(
            db,
            supervised_action_id,
            organization_id=_org(user, body.organization_id),
            user=user,
            notes=body.notes,
        )
    except NovaWorkError as exc:
        _raise(exc)


@router.post("/actions/{supervised_action_id}/revoke")
def v2_revoke_action(
    supervised_action_id: str,
    payload: SupervisedActionNotes | None = None,
    user: UserContext = Depends(get_current_user_context),
    db: Session = Depends(get_db),
):
    body = payload or SupervisedActionNotes()
    try:
        return v2_actions.revoke_action(
            db,
            supervised_action_id,
            organization_id=_org(user, body.organization_id),
            user=user,
            notes=body.notes,
        )
    except NovaWorkError as exc:
        _raise(exc)


@router.post("/actions/{supervised_action_id}/expire")
def v2_expire_action(
    supervised_action_id: str,
    payload: SupervisedActionNotes | None = None,
    user: UserContext = Depends(get_current_user_context),
    db: Session = Depends(get_db),
):
    body = payload or SupervisedActionNotes()
    try:
        return v2_actions.expire_action(
            db, supervised_action_id, organization_id=_org(user, body.organization_id), user=user
        )
    except NovaWorkError as exc:
        _raise(exc)


@router.post("/actions/{supervised_action_id}/execute")
def v2_execute_action(
    supervised_action_id: str,
    payload: SupervisedActionNotes | None = None,
    user: UserContext = Depends(get_current_user_context),
    db: Session = Depends(get_db),
):
    body = payload or SupervisedActionNotes()
    try:
        return v2_actions.execute_action(
            db, supervised_action_id, organization_id=_org(user, body.organization_id), user=user
        )
    except NovaWorkError as exc:
        _raise(exc)


@router.get("/audit")
def v2_live_audit(
    organization_id: str | None = None,
    limit: int | None = 100,
    user: UserContext = Depends(get_current_user_context),
    db: Session = Depends(get_db),
):
    return v2_actions.list_live_audits(
        db, organization_id=_org(user, organization_id), user=user, limit=limit or 100
    )


@router.post("/scheduler/prepare")
def v2_scheduler_prepare(
    payload: SchedulerPrepare,
    user: UserContext = Depends(get_current_user_context),
    db: Session = Depends(get_db),
):
    try:
        return v2_scheduler.prepare_jobs(
            db,
            organization_id=_org(user, payload.organization_id),
            user=user,
            timezone_name=payload.timezone,
            kinds=payload.kinds,
        )
    except NovaWorkError as exc:
        _raise(exc)


@router.get("/scheduler/jobs")
def v2_scheduler_jobs(
    organization_id: str | None = None,
    limit: int | None = 100,
    user: UserContext = Depends(get_current_user_context),
    db: Session = Depends(get_db),
):
    return v2_scheduler.list_jobs(db, organization_id=_org(user, organization_id), user=user, limit=limit or 100)


@router.post("/revenue/payment-events")
def v2_payment_event(
    payload: PaymentEventIn,
    user: UserContext = Depends(get_current_user_context),
    db: Session = Depends(get_db),
):
    try:
        data = payload.model_dump()
        occurred = data.get("occurred_at")
        if occurred:
            from datetime import datetime

            try:
                data["occurred_at"] = datetime.fromisoformat(str(occurred).replace("Z", "+00:00"))
            except ValueError as exc:
                raise NovaWorkError("occurred_at must be ISO-8601") from exc
        else:
            data["occurred_at"] = None
        return v2_revenue.record_payment_event(
            db, data, organization_id=_org(user, payload.organization_id), user=user
        )
    except NovaWorkError as exc:
        _raise(exc)


@router.get("/revenue/preparation")
def v2_revenue_preparation(
    organization_id: str | None = None,
    user: UserContext = Depends(get_current_user_context),
    db: Session = Depends(get_db),
):
    org_id = _org(user, organization_id)
    recon = v1_reconciliation(db, organization_id=org_id, user=user)
    return v2_revenue.revenue_preparation(db, organization_id=org_id, user=user, reconciliation=recon)


@router.post("/revenue/historical-corrections")
def v2_historical_correction(
    payload: HistoricalCorrectionIn,
    user: UserContext = Depends(get_current_user_context),
    db: Session = Depends(get_db),
):
    try:
        return v2_revenue.record_historical_correction(
            db, payload.model_dump(), organization_id=_org(user, payload.organization_id), user=user
        )
    except NovaWorkError as exc:
        _raise(exc)


@router.get("/revenue/historical-corrections")
def v2_list_historical_corrections(
    organization_id: str | None = None,
    user: UserContext = Depends(get_current_user_context),
    db: Session = Depends(get_db),
):
    return v2_revenue.list_historical_corrections(
        db, organization_id=_org(user, organization_id), user=user
    )


@router.get("/status")
def v2_status_surface(
    organization_id: str | None = None,
    user: UserContext = Depends(get_current_user_context),
    db: Session = Depends(get_db),
):
    return v2_status.monitoring_snapshot(db, organization_id=_org(user, organization_id), user=user)


@router.get("/pilot/workflow")
def v2_pilot_workflow(
    organization_id: str | None = None,
    opportunity_id: str | None = None,
    user: UserContext = Depends(get_current_user_context),
    db: Session = Depends(get_db),
):
    return v2_pilot.pilot_workflow(
        db,
        organization_id=_org(user, organization_id),
        user=user,
        opportunity_id=opportunity_id,
    )


@router.get("/idempotency/contract")
def v2_idempotency_contract(user: UserContext = Depends(get_current_user_context)):
    return {
        **WEBHOOK_REUSE_CONTRACT,
        "live_webhooks_enabled": False,
        "stripe_touched": False,
    }
