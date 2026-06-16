"""Nova action management router - approve, execute, query approval-safe actions."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.auth import (
    ROLE_ADMIN,
    ROLE_ANALYTICS_READONLY,
    ROLE_DISPATCHER,
    ROLE_STAFF,
    ROLE_SUPER_ADMIN_SUPPORT,
    UserContext,
    get_current_user_context,
    require_any_role,
)
from app.core.nova.action_models import (
    ActionQueryResponse,
    ApprovalRequest,
    ExecutionResult,
    ExecutionStatus,
    NovaAction,
    ProposedAction,
)
from app.core.nova.actions import execution_orchestrator
from app.db.session import get_db


class ActionProposalRequest(BaseModel):
    """Proposal request from Nova to stage an action."""
    organization_id: str | None = None
    action: ProposedAction
    source_event_ids: list[str] = []
    correlation_id: str | None = None


class ActionApprovalRequest(BaseModel):
    """Operator approval/rejection of staged action."""
    organization_id: str | None = None
    action_id: str
    approved: bool
    approval_reason: str | None = None
    rejection_reason: str | None = None


class ActionSimulationRequest(BaseModel):
    """Request to simulate action execution."""
    organization_id: str | None = None
    action_id: str


class ActionExecuteRequest(BaseModel):
    """Execute an approved action."""
    organization_id: str | None = None
    action_id: str


class ActionRollbackRequest(BaseModel):
    """Rollback a failed action."""
    organization_id: str | None = None
    action_id: str


require_nova_actions = require_any_role(
    ROLE_ADMIN,
    ROLE_SUPER_ADMIN_SUPPORT,
    ROLE_DISPATCHER,
    ROLE_STAFF,
    ROLE_ANALYTICS_READONLY,
)

router = APIRouter(
    prefix="/api/nova/actions",
    tags=["nova-actions"],
    dependencies=[Depends(require_nova_actions)],
)


def _resolve_org(user: UserContext, requested: str | None) -> str:
    """Resolve organization scope with tenant safety."""
    from app.core.nova.service import NovaCoreService
    try:
        return NovaCoreService.resolve_organization_scope(user, requested)
    except ValueError as exc:
        message = str(exc)
        status = 403 if "Cross-tenant" in message else 400
        raise HTTPException(status_code=status, detail=message) from exc


@router.post("/propose")
async def propose_action(
    payload: ActionProposalRequest,
    user: UserContext = Depends(get_current_user_context),
    db: Session = Depends(get_db),
) -> NovaAction:
    """
    Stage a proposed action for approval.
    
    Action is NOT executed, only proposed.
    Requires approval_required=True by default.
    """
    org_id = _resolve_org(user, payload.organization_id)
    
    try:
        action = await execution_orchestrator.propose_action(
            org_id,
            payload.action,
            source_event_ids=payload.source_event_ids,
            correlation_id=payload.correlation_id,
        )
        return action
    except Exception as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.post("/approve")
async def approve_action(
    payload: ActionApprovalRequest,
    user: UserContext = Depends(get_current_user_context),
    db: Session = Depends(get_db),
) -> NovaAction:
    """
    Operator approves or rejects a staged action.
    
    Approval/rejection is persisted with operator identity and timestamp.
    Approved actions move to APPROVED state, ready for execution.
    """
    org_id = _resolve_org(user, payload.organization_id)
    
    try:
        approval = ApprovalRequest(
            action_id=payload.action_id,
            approved=payload.approved,
            approval_reason=payload.approval_reason,
            rejection_reason=payload.rejection_reason,
        )
        
        action = await execution_orchestrator.handle_approval(
            org_id,
            approval,
            operator_identity=f"{user.user_id}:{user.role}",
        )
        return action
    except Exception as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.post("/simulate")
async def simulate_action(
    payload: ActionSimulationRequest,
    user: UserContext = Depends(get_current_user_context),
    db: Session = Depends(get_db),
) -> dict:
    """
    Dry-run simulation of action execution.
    
    Returns estimated impact and warnings without actual execution.
    """
    org_id = _resolve_org(user, payload.organization_id)
    
    try:
        actions = await execution_orchestrator.query_pending_actions(org_id, limit=1000)
        action = None
        for a in actions:
            if a.action_id == payload.action_id:
                action = a
                break
        
        if not action:
            raise HTTPException(status_code=404, detail="Action not found")
        
        simulation = await execution_orchestrator.simulate_execution(org_id, action)
        return simulation
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.post("/execute")
async def execute_action(
    payload: ActionExecuteRequest,
    user: UserContext = Depends(get_current_user_context),
    db: Session = Depends(get_db),
) -> ExecutionResult:
    """
    Execute an approved action.
    
    Only approved actions can execute.
    Execution is timeout-safe and rollback-capable.
    """
    org_id = _resolve_org(user, payload.organization_id)
    
    try:
        actions = await execution_orchestrator.query_pending_actions(org_id, limit=1000)
        action = None
        for a in actions:
            if a.action_id == payload.action_id:
                action = a
                break
        
        if not action:
            raise HTTPException(status_code=404, detail="Action not found")
        
        # Validate execution feasibility
        feasible, reason = await execution_orchestrator.validate_execution_feasibility(org_id, action)
        if not feasible:
            raise HTTPException(status_code=400, detail=reason)
        
        # Execute (no custom executor for now - type-specific handlers in separate services)
        result = await execution_orchestrator.execute_action(org_id, action)
        return result
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.post("/rollback")
async def rollback_action(
    payload: ActionRollbackRequest,
    user: UserContext = Depends(get_current_user_context),
    db: Session = Depends(get_db),
) -> ExecutionResult:
    """
    Rollback a failed action.
    
    Requires manual operator invocation.
    Rollback plan persisted in action.rollback_strategy.
    """
    org_id = _resolve_org(user, payload.organization_id)
    
    try:
        actions = await execution_orchestrator.query_pending_actions(org_id, limit=1000)
        action = None
        for a in actions:
            if a.action_id == payload.action_id:
                action = a
                break
        
        if not action:
            raise HTTPException(status_code=404, detail="Action not found")
        
        result = await execution_orchestrator.rollback_action(org_id, action)
        return result
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.get("/pending", response_model=ActionQueryResponse)
async def get_pending_actions(
    organization_id: str | None = None,
    status: str | None = None,
    user: UserContext = Depends(get_current_user_context),
    db: Session = Depends(get_db),
) -> ActionQueryResponse:
    """
    Query pending/executing/failed actions.
    
    Shows:
    - Pending actions awaiting approval
    - Currently executing actions
    - Failed actions
    - Recent rollbacks
    - Execution latency metrics
    """
    org_id = _resolve_org(user, organization_id)
    
    try:
        pending = await execution_orchestrator.query_pending_actions(org_id)
        executing = await execution_orchestrator.query_executing_actions(org_id)
        failed = await execution_orchestrator.query_failed_actions(org_id)
        rollbacks = await execution_orchestrator.query_recent_rollbacks(org_id)
        latency_stats = await execution_orchestrator.get_execution_latency_stats(org_id)
        
        # Count by status
        by_status = {}
        for action in pending + executing + failed + rollbacks:
            status_name = str(action.execution_status)
            by_status[status_name] = by_status.get(status_name, 0) + 1
        
        total = len(pending) + len(executing) + len(failed) + len(rollbacks)
        
        return ActionQueryResponse(
            organization_id=org_id,
            total_count=total,
            by_status=by_status,
            pending_actions=pending[:20],
            executing_actions=executing,
            failed_actions=failed[:10],
            recent_rollbacks=rollbacks[:10],
            average_execution_latency_ms=latency_stats.get("average_ms", 0.0),
        )
    except Exception as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.get("/{action_id}", response_model=NovaAction)
async def get_action(
    action_id: str,
    organization_id: str | None = None,
    user: UserContext = Depends(get_current_user_context),
    db: Session = Depends(get_db),
) -> NovaAction:
    """Get action by ID with full execution timeline."""
    org_id = _resolve_org(user, organization_id)
    
    try:
        actions = await execution_orchestrator.query_pending_actions(org_id, limit=1000)
        for action in actions:
            if action.action_id == action_id:
                return action
        
        raise HTTPException(status_code=404, detail="Action not found")
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.post("/expire-stale")
async def expire_stale_actions(
    organization_id: str | None = None,
    age_seconds: int = Query(3600, ge=60),
    user: UserContext = Depends(get_current_user_context),
    db: Session = Depends(get_db),
) -> dict:
    """
    Expire stale proposed actions.
    
    Actions older than age_seconds in PROPOSED/AWAITING_APPROVAL state
    are marked EXPIRED and removed from approval queue.
    """
    org_id = _resolve_org(user, organization_id)
    
    try:
        expired_count = await execution_orchestrator.expire_stale_actions(
            org_id,
            age_seconds=age_seconds,
        )
        
        return {
            "organization_id": org_id,
            "expired_count": expired_count,
        }
    except Exception as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
