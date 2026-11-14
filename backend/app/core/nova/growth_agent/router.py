"""HTTP API for Nova Growth Agent. Default-off via NOVA_GROWTH_AGENT_ENABLED."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, Header, HTTPException, Query, Request
from fastapi.responses import HTMLResponse
from sqlalchemy.orm import Session

from app.auth import UserContext
from app.core.nova.growth_agent.errors import GrowthAgentError
from app.core.nova.growth_agent.flags import live_flags, widget_public_enabled
from app.core.nova.growth_agent.demo import run_synthetic_demo
from app.core.nova.growth_agent.schemas import (
    CampaignCreateIn,
    CampaignStateIn,
    AgentStateIn,
    AvailabilityIn,
    BookIn,
    ConsentIn,
    LeadUpdateIn,
    ProfileUpsertIn,
    RescheduleIn,
    RetentionIn,
    RetentionScheduleTickIn,
    WidgetChatIn,
    WidgetCreateIn,
    WorkerTickIn,
    WorkflowExecuteIn,
    WorkflowPreviewIn,
)
from app.core.nova.growth_agent.service import GrowthAgentService
from app.core.nova.growth_agent.tenant import require_growth_owner, resolve_org
from app.db.session import get_db

router = APIRouter(
    prefix="/api/nova/growth-agent",
    tags=["nova-growth-agent"],
)


def _svc(db: Session = Depends(get_db)) -> GrowthAgentService:
    return GrowthAgentService(db)


def _org(user: UserContext, organization_id: str | None) -> str:
    try:
        return resolve_org(user, organization_id)
    except GrowthAgentError as exc:
        raise HTTPException(status_code=exc.http_status, detail=exc.message) from exc


def _handle(exc: GrowthAgentError) -> None:
    raise HTTPException(status_code=exc.http_status, detail=exc.as_dict()) from exc


@router.get("/flags")
def get_flags(user: UserContext = Depends(require_growth_owner)) -> dict[str, Any]:
    return {"flags": live_flags(), "user": user.email}


@router.get("/health")
def health(
    organization_id: str | None = None,
    user: UserContext = Depends(require_growth_owner),
    svc: GrowthAgentService = Depends(_svc),
) -> dict[str, Any]:
    return svc.health(_org(user, organization_id))


@router.get("/plans")
def plans(user: UserContext = Depends(require_growth_owner)) -> dict[str, Any]:
    from app.core.nova.growth_agent.commercial import plan_catalog

    return plan_catalog()


@router.get("/retention")
def retention(user: UserContext = Depends(require_growth_owner)) -> dict[str, Any]:
    return GrowthAgentService.retention_policy()


@router.get("/profile")
def get_profile(
    organization_id: str | None = None,
    user: UserContext = Depends(require_growth_owner),
    svc: GrowthAgentService = Depends(_svc),
) -> dict[str, Any]:
    return svc.get_profile(_org(user, organization_id))


@router.post("/profile")
def upsert_profile(
    body: ProfileUpsertIn,
    user: UserContext = Depends(require_growth_owner),
    svc: GrowthAgentService = Depends(_svc),
) -> dict[str, Any]:
    org = _org(user, body.organization_id)
    try:
        return svc.upsert_profile(
            org,
            user.user_id,
            body.model_dump(),
            activate=body.activate,
            preview_only=body.preview_only,
        )
    except GrowthAgentError as exc:
        _handle(exc)
        raise


@router.post("/agent")
def agent_state(
    body: AgentStateIn,
    user: UserContext = Depends(require_growth_owner),
    svc: GrowthAgentService = Depends(_svc),
) -> dict[str, Any]:
    org = _org(user, body.organization_id)
    try:
        return svc.set_agent_state(
            org,
            paused=body.paused,
            disabled=body.disabled,
            actor_user_id=user.user_id,
        )
    except GrowthAgentError as exc:
        _handle(exc)
        raise


@router.post("/widget/installations")
def create_widget(
    body: WidgetCreateIn,
    user: UserContext = Depends(require_growth_owner),
    svc: GrowthAgentService = Depends(_svc),
) -> dict[str, Any]:
    org = _org(user, body.organization_id)
    try:
        return svc.create_widget_installation(
            org,
            domain=body.domain,
            branding=body.branding,
            actor_user_id=user.user_id,
        )
    except GrowthAgentError as exc:
        _handle(exc)
        raise


@router.post("/widget/chat")
def widget_chat(
    body: WidgetChatIn,
    request: Request,
    origin: str | None = Header(default=None, alias="Origin"),
    embed_origin: str | None = Header(default=None, alias="X-Amicor-Growth-Origin"),
    svc: GrowthAgentService = Depends(_svc),
) -> dict[str, Any]:
    # Public embed requires both master + widget flags. Signed token alone is
    # not enough when NOVA_GROWTH_AGENT_WIDGET_ENABLED is unset.
    if not live_flags().get("GROWTH_AGENT_ENABLED") or not widget_public_enabled():
        raise HTTPException(status_code=404, detail="Growth Agent widget disabled")
    try:
        return svc.widget_chat(
            token=body.token,
            origin=origin or embed_origin or request.headers.get("Referer"),
            message=body.message,
            conversation_id=body.conversation_id,
            campaign_id=body.campaign_id,
            visitor_name=body.visitor_name,
            visitor_email=body.visitor_email,
            consent_marketing=body.consent_marketing,
            consent_transactional=body.consent_transactional,
        )
    except GrowthAgentError as exc:
        _handle(exc)
        raise


@router.get("/leads")
def list_leads(
    organization_id: str | None = None,
    q: str | None = None,
    state: str | None = None,
    user: UserContext = Depends(require_growth_owner),
    svc: GrowthAgentService = Depends(_svc),
) -> dict[str, Any]:
    org = _org(user, organization_id)
    return {"leads": svc.list_leads(org, q=q, state=state)}


@router.patch("/leads/{contact_id}")
def update_lead(
    contact_id: str,
    body: LeadUpdateIn,
    user: UserContext = Depends(require_growth_owner),
    svc: GrowthAgentService = Depends(_svc),
) -> dict[str, Any]:
    org = _org(user, body.organization_id)
    try:
        return svc.update_lead(
            org,
            contact_id,
            lead_state=body.lead_state,
            notes=body.notes,
            actor_user_id=user.user_id,
        )
    except GrowthAgentError as exc:
        _handle(exc)
        raise


@router.post("/consent")
def record_consent(
    body: ConsentIn,
    user: UserContext = Depends(require_growth_owner),
    svc: GrowthAgentService = Depends(_svc),
) -> dict[str, Any]:
    org = _org(user, body.organization_id)
    try:
        return svc.record_consent(
            org,
            contact_id=body.contact_id,
            channel=body.channel,
            purpose=body.purpose,
            status=body.status,
            collection_source=body.collection_source,
            actor_user_id=user.user_id,
        )
    except GrowthAgentError as exc:
        _handle(exc)
        raise


@router.get("/conversations")
def list_conversations(
    organization_id: str | None = None,
    user: UserContext = Depends(require_growth_owner),
    svc: GrowthAgentService = Depends(_svc),
) -> dict[str, Any]:
    return {"conversations": svc.list_conversations(_org(user, organization_id))}


@router.get("/conversations/{conversation_id}")
def get_conversation(
    conversation_id: str,
    organization_id: str | None = None,
    user: UserContext = Depends(require_growth_owner),
    svc: GrowthAgentService = Depends(_svc),
) -> dict[str, Any]:
    try:
        return svc.get_conversation(_org(user, organization_id), conversation_id)
    except GrowthAgentError as exc:
        _handle(exc)
        raise


@router.post("/conversations/{conversation_id}/handoff")
def handoff(
    conversation_id: str,
    organization_id: str | None = None,
    user: UserContext = Depends(require_growth_owner),
    svc: GrowthAgentService = Depends(_svc),
) -> dict[str, Any]:
    try:
        return svc.handoff_conversation(
            _org(user, organization_id),
            conversation_id,
            actor_user_id=user.user_id,
        )
    except GrowthAgentError as exc:
        _handle(exc)
        raise


@router.post("/workflows/preview")
def workflow_preview(
    body: WorkflowPreviewIn,
    user: UserContext = Depends(require_growth_owner),
    svc: GrowthAgentService = Depends(_svc),
) -> dict[str, Any]:
    org = _org(user, body.organization_id)
    try:
        return svc.preview_workflow(
            org,
            workflow_code=body.workflow_code,
            contact_id=body.contact_id,
            conversation_id=body.conversation_id,
        )
    except GrowthAgentError as exc:
        _handle(exc)
        raise


@router.post("/workflows/execute")
def workflow_execute(
    body: WorkflowExecuteIn,
    user: UserContext = Depends(require_growth_owner),
    svc: GrowthAgentService = Depends(_svc),
) -> dict[str, Any]:
    org = _org(user, body.organization_id)
    try:
        return svc.approve_and_execute_workflow(
            org,
            run_id=body.run_id,
            dry_run=body.dry_run,
            actor_user_id=user.user_id,
            idempotency_key=body.idempotency_key,
        )
    except GrowthAgentError as exc:
        _handle(exc)
        raise


@router.post("/workflows/recover")
def workflow_recover(
    organization_id: str | None = None,
    limit: int = Query(default=50, ge=1, le=200),
    user: UserContext = Depends(require_growth_owner),
    svc: GrowthAgentService = Depends(_svc),
) -> dict[str, Any]:
    """Reclaim queued/retrying mock deliveries after process restart."""
    try:
        return svc.recover_pending_deliveries(
            _org(user, organization_id),
            actor_user_id=user.user_id,
            limit=limit,
        )
    except GrowthAgentError as exc:
        _handle(exc)
        raise


@router.post("/workflows/worker/tick")
def workflow_worker_tick(
    body: WorkerTickIn,
    user: UserContext = Depends(require_growth_owner),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    """Run one mock-worker batch for this tenant (never live delivery)."""
    from app.core.nova.growth_agent.flags import background_worker_enabled, growth_agent_enabled
    from app.core.nova.growth_agent.worker import MockDeliveryWorker
    from sqlalchemy.orm import sessionmaker

    if not growth_agent_enabled():
        raise HTTPException(status_code=404, detail="Growth Agent disabled")
    if not background_worker_enabled():
        raise HTTPException(
            status_code=404,
            detail="Mock background worker disabled (set NOVA_GROWTH_AGENT_BACKGROUND_WORKER=true)",
        )
    org = _org(user, body.organization_id)
    factory = sessionmaker(bind=db.get_bind(), expire_on_commit=False)
    worker = MockDeliveryWorker(factory, organization_id=org, worker_id=f"tick-{user.user_id[:8]}")
    result = worker.run_once(limit=body.limit)
    result["distinction"] = "mock_only"
    result["live_send"] = False
    return result


@router.get("/diagnostics")
def diagnostics(
    organization_id: str | None = None,
    user: UserContext = Depends(require_growth_owner),
    svc: GrowthAgentService = Depends(_svc),
) -> dict[str, Any]:
    return svc.diagnostics(_org(user, organization_id))


@router.post("/retention/preview")
def retention_preview(
    body: RetentionIn,
    user: UserContext = Depends(require_growth_owner),
    svc: GrowthAgentService = Depends(_svc),
) -> dict[str, Any]:
    try:
        return svc.retention_preview(_org(user, body.organization_id), batch_limit=body.batch_limit)
    except GrowthAgentError as exc:
        _handle(exc)
        raise


@router.post("/retention/execute")
def retention_execute(
    body: RetentionIn,
    user: UserContext = Depends(require_growth_owner),
    svc: GrowthAgentService = Depends(_svc),
) -> dict[str, Any]:
    try:
        return svc.retention_execute(
            _org(user, body.organization_id),
            batch_limit=body.batch_limit,
            actor_user_id=user.user_id,
        )
    except GrowthAgentError as exc:
        _handle(exc)
        raise


@router.post("/retention/schedule/tick")
def retention_schedule_tick(
    body: RetentionScheduleTickIn,
    user: UserContext = Depends(require_growth_owner),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    """Run one scheduled-retention batch for this tenant (dry-run unless delete enabled)."""
    from sqlalchemy.orm import sessionmaker

    from app.core.nova.growth_agent.flags import growth_agent_enabled, retention_schedule_enabled
    from app.core.nova.growth_agent.retention_schedule import RetentionScheduler

    if not growth_agent_enabled():
        raise HTTPException(status_code=404, detail="Growth Agent disabled")
    if not retention_schedule_enabled():
        raise HTTPException(
            status_code=404,
            detail=(
                "Retention schedule disabled "
                "(set NOVA_GROWTH_AGENT_RETENTION_SCHEDULE_ENABLED=true)"
            ),
        )
    org = _org(user, body.organization_id)
    factory = sessionmaker(bind=db.get_bind(), expire_on_commit=False)
    scheduler = RetentionScheduler(
        factory,
        organization_id=org,
        scheduler_id=f"tick-ret-{user.user_id[:8]}",
    )
    result = scheduler.run_once(
        limit=body.limit,
        window_key=body.window_key,
        ensure=body.ensure,
    )
    result["distinction"] = "scheduled_retention"
    result["owner_triggered"] = True
    return result


@router.get("/appointments")
def list_appointments(
    organization_id: str | None = None,
    limit: int = Query(default=50, ge=1, le=200),
    user: UserContext = Depends(require_growth_owner),
    svc: GrowthAgentService = Depends(_svc),
) -> dict[str, Any]:
    return {"appointments": svc.list_appointments(_org(user, organization_id), limit=limit)}


@router.get("/availability")
def availability(
    service_code: str = Query(...),
    day: str = Query(...),
    organization_id: str | None = None,
    user: UserContext = Depends(require_growth_owner),
    svc: GrowthAgentService = Depends(_svc),
) -> dict[str, Any]:
    try:
        return svc.list_availability(
            _org(user, organization_id),
            service_code=service_code,
            day=day,
        )
    except GrowthAgentError as exc:
        _handle(exc)
        raise


@router.post("/appointments")
def book(
    body: BookIn,
    user: UserContext = Depends(require_growth_owner),
    svc: GrowthAgentService = Depends(_svc),
) -> dict[str, Any]:
    org = _org(user, body.organization_id)
    try:
        return svc.book_appointment(
            org,
            contact_id=body.contact_id,
            service_code=body.service_code,
            starts_at_utc=body.starts_at_utc,
            idempotency_key=body.idempotency_key,
            conversation_id=body.conversation_id,
            actor_user_id=user.user_id,
            is_synthetic_demo=body.is_synthetic_demo,
        )
    except GrowthAgentError as exc:
        _handle(exc)
        raise


@router.post("/appointments/{appointment_id}/cancel")
def cancel_appt(
    appointment_id: str,
    organization_id: str | None = None,
    user: UserContext = Depends(require_growth_owner),
    svc: GrowthAgentService = Depends(_svc),
) -> dict[str, Any]:
    try:
        return svc.cancel_appointment(
            _org(user, organization_id),
            appointment_id,
            actor_user_id=user.user_id,
        )
    except GrowthAgentError as exc:
        _handle(exc)
        raise


@router.post("/appointments/{appointment_id}/reschedule")
def reschedule_appt(
    appointment_id: str,
    body: RescheduleIn,
    user: UserContext = Depends(require_growth_owner),
    svc: GrowthAgentService = Depends(_svc),
) -> dict[str, Any]:
    org = _org(user, body.organization_id)
    try:
        return svc.reschedule_appointment(
            org,
            appointment_id,
            starts_at_utc=body.starts_at_utc,
            idempotency_key=body.idempotency_key,
            actor_user_id=user.user_id,
        )
    except GrowthAgentError as exc:
        _handle(exc)
        raise


@router.get("/analytics")
def analytics(
    days: int = Query(default=30, ge=1, le=90),
    organization_id: str | None = None,
    user: UserContext = Depends(require_growth_owner),
    svc: GrowthAgentService = Depends(_svc),
) -> dict[str, Any]:
    return svc.analytics(_org(user, organization_id), days=days)


@router.get("/audit")
def audit(
    limit: int = Query(default=100, ge=1, le=500),
    organization_id: str | None = None,
    user: UserContext = Depends(require_growth_owner),
    svc: GrowthAgentService = Depends(_svc),
) -> dict[str, Any]:
    return {"events": svc.audit_history(_org(user, organization_id), limit=limit)}


@router.get("/export")
def export_org(
    organization_id: str | None = None,
    user: UserContext = Depends(require_growth_owner),
    svc: GrowthAgentService = Depends(_svc),
) -> dict[str, Any]:
    return svc.export_org(_org(user, organization_id))


@router.post("/demo/synthetic")
def synthetic_demo(
    organization_id: str | None = None,
    user: UserContext = Depends(require_growth_owner),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    from app.core.nova.growth_agent.flags import demo_mode_enabled, growth_agent_enabled

    if not growth_agent_enabled():
        raise HTTPException(status_code=404, detail="Growth Agent disabled")
    if not demo_mode_enabled():
        raise HTTPException(
            status_code=404,
            detail="Synthetic demo disabled (set NOVA_GROWTH_AGENT_DEMO_MODE=true)",
        )
    org = _org(user, organization_id)
    try:
        result = run_synthetic_demo(db, organization_id=org, owner_user_id=user.user_id)
        result["demo_mode_flag"] = True
        return result
    except GrowthAgentError as exc:
        _handle(exc)
        raise


@router.get("/campaign-projects")
def campaign_projects(user: UserContext = Depends(require_growth_owner), svc: GrowthAgentService = Depends(_svc)):
    from app.core.nova.growth_agent.campaigns import CampaignService
    try:
        _org(user, None)
        return {"projects": CampaignService(svc).projects(user.user_id)}
    except GrowthAgentError as exc:
        _handle(exc)


@router.get("/campaigns")
def campaigns(user: UserContext = Depends(require_growth_owner), svc: GrowthAgentService = Depends(_svc)):
    from app.core.nova.growth_agent.campaigns import CampaignService
    try:
        return {"campaigns": CampaignService(svc).list(_org(user, None), user.user_id)}
    except GrowthAgentError as exc:
        _handle(exc)


@router.post("/campaigns")
def create_campaign(body: CampaignCreateIn, user: UserContext = Depends(require_growth_owner), svc: GrowthAgentService = Depends(_svc)):
    from app.core.nova.growth_agent.campaigns import CampaignService
    try:
        return CampaignService(svc).create(_org(user, body.organization_id), user.user_id, body.model_dump())
    except GrowthAgentError as exc:
        _handle(exc)


@router.patch("/campaigns/{campaign_id}")
def campaign_state(campaign_id: str, body: CampaignStateIn, user: UserContext = Depends(require_growth_owner), svc: GrowthAgentService = Depends(_svc)):
    from app.core.nova.growth_agent.campaigns import CampaignService
    try:
        return CampaignService(svc).set_state(_org(user, body.organization_id), user.user_id,
                                              campaign_id, body.active, body.content_approved)
    except GrowthAgentError as exc:
        _handle(exc)


@router.get("/campaigns/{campaign_id}/visit", response_class=HTMLResponse)
def campaign_visit(campaign_id: str, request: Request, svc: GrowthAgentService = Depends(_svc)):
    from app.core.nova.growth_agent.campaigns import CampaignService
    try:
        return HTMLResponse(CampaignService(svc).landing(campaign_id, str(request.base_url)), headers={
            "Cache-Control": "no-store", "Referrer-Policy": "no-referrer",
            "X-Content-Type-Options": "nosniff",
            "Content-Security-Policy": "default-src 'self'; script-src 'self'; style-src 'self' 'unsafe-inline'; frame-ancestors 'none'; base-uri 'none'",
        })
    except GrowthAgentError as exc:
        _handle(exc)
