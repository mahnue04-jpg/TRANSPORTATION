from __future__ import annotations

import asyncio
import json

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import StreamingResponse
from sqlalchemy.orm import Session

from app.auth import (
    ROLE_ADMIN,
    ROLE_ANALYTICS_READONLY,
    ROLE_DISPATCHER,
    ROLE_DRIVER,
    ROLE_PROVIDER,
    ROLE_STAFF,
    ROLE_SUPER_ADMIN_SUPPORT,
    UserContext,
    get_current_user_context,
    require_any_role,
)
from app.core.nova.schemas import (
    NovaAssistanceRecommendationsResponse,
    NovaAskRequest,
    NovaAskResponse,
    NovaBusinessStateResponse,
    NovaBusinessStateUpdateRequest,
    NovaContinuityBriefResponse,
    NovaContextResponse,
    NovaDeploymentReadinessResponse,
    NovaIntelligenceResponse,
    NovaMemoryEventRequest,
    NovaMemoryFabricResponse,
    NovaNextStepRequest,
    NovaNextStepResponse,
    NovaReviewReportRequest,
    NovaReviewReportResponse,
    NovaSessionHeartbeatRequest,
    NovaSessionHeartbeatResponse,
    NovaLiveEventsResponse,
    NovaStatusResponse,
    NovaSummarizeRequest,
    NovaSummarizeResponse,
)
from app.core.nova.service import NovaCoreService
from app.db.session import get_db

require_nova_access = require_any_role(
    ROLE_ADMIN,
    ROLE_SUPER_ADMIN_SUPPORT,
    ROLE_DISPATCHER,
    ROLE_DRIVER,
    ROLE_PROVIDER,
    ROLE_STAFF,
    ROLE_ANALYTICS_READONLY,
)

router = APIRouter(
    prefix="/api/nova",
    tags=["nova"],
    dependencies=[Depends(require_nova_access)],
)


def _resolve_org(user: UserContext, requested: str | None) -> str:
    try:
        return NovaCoreService.resolve_organization_scope(user, requested)
    except ValueError as exc:
        message = str(exc)
        status = 403 if "Cross-tenant" in message else 400
        raise HTTPException(status_code=status, detail=message) from exc


@router.get("/status", response_model=NovaStatusResponse)
def get_nova_status(
    organization_id: str | None = None,
    user: UserContext = Depends(get_current_user_context),
    db: Session = Depends(get_db),
):
    org_id = _resolve_org(user, organization_id)
    return NovaCoreService.get_status(db, organization_id=org_id)


@router.get("/context", response_model=NovaContextResponse)
def get_nova_context(
    organization_id: str | None = None,
    user: UserContext = Depends(get_current_user_context),
    db: Session = Depends(get_db),
):
    org_id = _resolve_org(user, organization_id)
    return NovaCoreService.get_context(db, organization_id=org_id)


@router.get("/memory/fabric", response_model=NovaMemoryFabricResponse)
def get_memory_fabric(
    organization_id: str | None = None,
    user: UserContext = Depends(get_current_user_context),
    db: Session = Depends(get_db),
):
    org_id = _resolve_org(user, organization_id)
    return NovaCoreService.get_memory_fabric_snapshot(db, organization_id=org_id)


@router.post("/memory/events", response_model=NovaMemoryFabricResponse)
def append_memory_event(
    payload: NovaMemoryEventRequest,
    user: UserContext = Depends(get_current_user_context),
    db: Session = Depends(get_db),
):
    org_id = _resolve_org(user, payload.organization_id)
    response = NovaCoreService.add_memory_event(
        db,
        organization_id=org_id,
        channel=payload.channel,
        event_type=payload.event_type,
        summary=payload.summary,
        source=payload.source,
        tags=payload.tags,
        metadata=payload.metadata,
        correlation_id=payload.correlation_id,
    )
    return {
        "organization_id": response["organization_id"],
        "generated_at": response["generated_at"],
        "memory_fabric": response["memory_fabric"],
        "continuity_summary": response["continuity_summary"],
    }


@router.get("/continuity/brief", response_model=NovaContinuityBriefResponse)
def get_continuity_brief(
    organization_id: str | None = None,
    user: UserContext = Depends(get_current_user_context),
    db: Session = Depends(get_db),
):
    org_id = _resolve_org(user, organization_id)
    return NovaCoreService.get_continuity_brief(db, organization_id=org_id)


@router.post("/business/state", response_model=NovaBusinessStateResponse)
def update_business_state(
    payload: NovaBusinessStateUpdateRequest,
    user: UserContext = Depends(get_current_user_context),
    db: Session = Depends(get_db),
):
    org_id = _resolve_org(user, payload.organization_id)
    return NovaCoreService.update_business_state(
        db,
        organization_id=org_id,
        objectives=payload.objectives,
        kpis=payload.kpis,
        active_initiatives=payload.active_initiatives,
    )


@router.post("/session/heartbeat", response_model=NovaSessionHeartbeatResponse)
def session_heartbeat(
    payload: NovaSessionHeartbeatRequest,
    user: UserContext = Depends(get_current_user_context),
    db: Session = Depends(get_db),
):
    org_id = _resolve_org(user, payload.organization_id)
    return NovaCoreService.session_heartbeat(
        db,
        organization_id=org_id,
        session_id=payload.session_id,
        status=payload.status,
    )


@router.get("/assist/recommendations", response_model=NovaAssistanceRecommendationsResponse)
def get_assistance_recommendations(
    organization_id: str | None = None,
    user: UserContext = Depends(get_current_user_context),
    db: Session = Depends(get_db),
):
    org_id = _resolve_org(user, organization_id)
    return NovaCoreService.get_assistance_recommendations(db, organization_id=org_id)


@router.get("/events/live", response_model=NovaLiveEventsResponse)
def get_live_events(
    organization_id: str | None = None,
    limit: int = 60,
    user: UserContext = Depends(get_current_user_context),
    db: Session = Depends(get_db),
):
    org_id = _resolve_org(user, organization_id)
    return NovaCoreService.get_live_events(db, organization_id=org_id, limit=max(1, min(200, int(limit))))


@router.post("/ask", response_model=NovaAskResponse)
def ask_nova(
    payload: NovaAskRequest,
    user: UserContext = Depends(get_current_user_context),
    db: Session = Depends(get_db),
):
    org_id = _resolve_org(user, payload.organization_id)
    return NovaCoreService.ask(
        db,
        organization_id=org_id,
        mode=payload.mode,
        question=payload.question,
    )


@router.post("/ask/stream")
async def ask_nova_stream(
    payload: NovaAskRequest,
    user: UserContext = Depends(get_current_user_context),
    db: Session = Depends(get_db),
):
    org_id = _resolve_org(user, payload.organization_id)
    result = NovaCoreService.ask(
        db,
        organization_id=org_id,
        mode=payload.mode,
        question=payload.question,
    )

    async def _stream():
        yield "data: " + json.dumps({"type": "start", "mode": result.mode}) + "\n\n"
        words = str(result.answer or "").split()
        for word in words:
            yield "data: " + json.dumps({"type": "chunk", "content": word + " "}) + "\n\n"
            await asyncio.sleep(0.005)
        yield "data: " + json.dumps({
            "type": "done",
            "answer": result.answer,
            "next_actions": result.next_actions,
            "context_used": result.context_used,
            "generated_at": result.generated_at,
        }) + "\n\n"

    return StreamingResponse(_stream(), media_type="text/event-stream")


@router.post("/summarize", response_model=NovaSummarizeResponse)
def summarize_with_nova(
    payload: NovaSummarizeRequest,
    user: UserContext = Depends(get_current_user_context),
    db: Session = Depends(get_db),
):
    org_id = _resolve_org(user, payload.organization_id)
    return NovaCoreService.summarize(
        db,
        organization_id=org_id,
        summary_type=payload.summary_type,
        mode=payload.mode,
        source_text=payload.source_text,
    )


@router.post("/next-step", response_model=NovaNextStepResponse)
def next_step_with_nova(
    payload: NovaNextStepRequest,
    user: UserContext = Depends(get_current_user_context),
    db: Session = Depends(get_db),
):
    org_id = _resolve_org(user, payload.organization_id)
    return NovaCoreService.next_step(
        db,
        organization_id=org_id,
        mode=payload.mode,
        goal=payload.goal,
    )


@router.post("/review-report", response_model=NovaReviewReportResponse)
def review_report_with_nova(
    payload: NovaReviewReportRequest,
    user: UserContext = Depends(get_current_user_context),
    db: Session = Depends(get_db),
):
    org_id = _resolve_org(user, payload.organization_id)
    return NovaCoreService.review_report(
        db,
        organization_id=org_id,
        mode=payload.mode,
        report_title=payload.report_title,
        report_text=payload.report_text,
    )


@router.get("/intelligence", response_model=NovaIntelligenceResponse)
def get_nova_intelligence(
    organization_id: str | None = None,
    user: UserContext = Depends(get_current_user_context),
    db: Session = Depends(get_db),
):
    """Full operational intelligence report: scoring, bottlenecks, stale rides, recommendations."""
    org_id = _resolve_org(user, organization_id)
    return NovaCoreService.get_intelligence_report(db, organization_id=org_id)


@router.get("/deployment-readiness", response_model=NovaDeploymentReadinessResponse)
def get_deployment_readiness(
    user: UserContext = Depends(get_current_user_context),
):
    """Environment validation and production config readiness check."""
    from app.deployment.readiness import DeploymentReadinessChecker
    return DeploymentReadinessChecker.build_readiness_report()
