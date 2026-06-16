from __future__ import annotations

from datetime import datetime, timezone
from typing import Any
import os

from sqlalchemy.orm import Session

from app.auth import UserContext, is_super_admin
from app.core.nova.event_bus import nova_event_bus
from app.core.nova.events import build_operational_events
from app.core.nova.memory import memory_store
from app.core.nova.prompts import MODE_SYSTEM_GUIDANCE, NOVA_RESPONSIBILITIES
from app.core.nova.schemas import (
    NovaAskResponse,
    NovaContextResponse,
    NovaHealthISFSummary,
    NovaMemoryState,
    NovaMode,
    NovaNextStepResponse,
    NovaReviewReportResponse,
    NovaStatusResponse,
    NovaSummarizeResponse,
)
from app.modules.health_isf.service import get_all_drivers, get_all_providers
from app.modules.health_isf.intelligence import OperationalIntelligenceService
from app.modules.health_isf.models import DriverStatus, HealthISFRide, RideStatus
from app.modules.health_isf.operations import (
    build_operational_metrics,
    evaluate_operational_alerts,
)
from app.modules.health_isf.realtime import get_broadcaster
from app.modules.health_isf.realtime_service import RetryQueueService
from app.modules.health_isf.workflow_engine import WorkflowOrchestrationService


class NovaCoreService:
    """Central additive orchestration layer for Mr. Nova."""

    ACTIVE_MODULES = [
        "amicor_core_assistant",
        "health_isf",
        "auth",
        "voice_runtime",
        "operations_intelligence",
    ]

    @classmethod
    def resolve_organization_scope(
        cls,
        user: UserContext,
        requested_organization_id: str | None,
    ) -> str:
        if requested_organization_id:
            if not is_super_admin(user) and requested_organization_id != user.organization_id:
                raise ValueError("Cross-tenant Nova access denied")
            return requested_organization_id
        if user.organization_id:
            return user.organization_id
        if is_super_admin(user):
            return "global"
        raise ValueError("Organization scope is required for Nova")

    @staticmethod
    def _now() -> str:
        return datetime.now(timezone.utc).isoformat()

    @classmethod
    def _read_memory(cls, organization_id: str) -> dict[str, Any]:
        return memory_store.read(organization_id)

    @classmethod
    def _record_memory_event(
        cls,
        organization_id: str,
        *,
        channel: str,
        event_type: str,
        summary: str,
        source: str,
        tags: list[str] | None = None,
        metadata: dict[str, Any] | None = None,
        correlation_id: str | None = None,
    ) -> None:
        memory_store.append_event(
            organization_id,
            channel,
            {
                "event_type": str(event_type or "event"),
                "summary": str(summary or ""),
                "source": str(source or "nova"),
                "tags": list(tags or []),
                "metadata": dict(metadata or {}),
                "correlation_id": correlation_id,
            },
        )

    @classmethod
    def _continuity_summary(cls, organization_id: str) -> str:
        fabric = memory_store.read_fabric(organization_id)
        founder_notes = list(fabric.get("founder_continuity") or [])
        op_history = list(fabric.get("operational_history") or [])
        wf_history = list(fabric.get("workflow_history") or [])
        return (
            f"Continuity notes: {len(founder_notes)}, operational events: {len(op_history)}, "
            f"workflow events: {len(wf_history)}"
        )

    @classmethod
    def _build_runtime_context(cls, context: NovaContextResponse) -> dict[str, Any]:
        continuity_summary = cls._continuity_summary(context.organization_id)
        return {
            "platform_phase": context.platform_phase,
            "build_completion_estimate": context.build_completion_estimate,
            "system_health_summary": context.system_health_summary,
            "business_legal_checklist_status": context.business_legal_checklist_status,
            "operational_health": context.operational_health,
            "workflow_status": context.workflow_status,
            "health_isf_summary": context.health_isf_summary.model_dump(),
            "memory": context.memory.model_dump(),
            "continuity_summary": continuity_summary,
        }

    @classmethod
    def _can_use_llm(cls) -> bool:
        return bool(os.getenv("OPENAI_API_KEY"))

    @classmethod
    def _deterministic_answer(
        cls,
        mode: NovaMode,
        question: str,
        context: NovaContextResponse,
    ) -> str:
        summary = context.health_isf_summary
        guidance = MODE_SYSTEM_GUIDANCE[mode]
        return (
            f"{guidance} Based on current platform phase '{context.platform_phase}', "
            f"dispatch health is '{summary.dispatch_health}', workflow health is '{summary.workflow_health}', "
            f"and enterprise readiness is '{summary.enterprise_readiness}'. "
            f"Question received: {question.strip()}"
        )

    @classmethod
    def _llm_answer(
        cls,
        mode: NovaMode,
        question: str,
        context: NovaContextResponse,
    ) -> tuple[str, str]:
        if not cls._can_use_llm():
            return cls._deterministic_answer(mode, question, context), "deterministic_fallback"

        try:
            from app.ai import ask_openai

            runtime_context = cls._build_runtime_context(context)
            prompt = (
                MODE_SYSTEM_GUIDANCE[mode]
                + "\nYou are operating inside the Amicor runtime. Use only provided context."
                + "\nRespond with:\n1) direct answer\n2) short rationale\n3) 3 concrete next actions"
                + "\nContext JSON:\n"
                + str(runtime_context)
                + "\nUser question:\n"
                + question.strip()
            )
            answer = ask_openai(prompt)
            if not answer or not str(answer).strip():
                return cls._deterministic_answer(mode, question, context), "deterministic_empty_llm"
            return str(answer).strip(), "openai"
        except Exception:
            return cls._deterministic_answer(mode, question, context), "deterministic_error_fallback"

    @classmethod
    def _get_health_isf_context(cls, db: Session, organization_id: str) -> dict[str, Any]:
        metrics = build_operational_metrics(db, organization_id=organization_id)
        websocket_stats = get_broadcaster().get_websocket_health_stats(organization_id=organization_id)
        queue_stats = RetryQueueService.get_queue_stats(db, organization_id=organization_id)
        health = {
            "status": "healthy" if queue_stats.get("dead_letter", 0) < 20 else "degraded",
            "websocket": websocket_stats,
            "event_queue": queue_stats,
            "source": "nova_lightweight_health",
        }
        alerts = evaluate_operational_alerts(
            db,
            queue_stats=queue_stats,
            websocket_stats=websocket_stats,
            organization_id=organization_id,
        )
        workflows = WorkflowOrchestrationService.list_workflows(db, organization_id=organization_id, limit=120)

        rides = db.query(HealthISFRide).filter(HealthISFRide.organization_id == organization_id).all()
        providers = [p for p in get_all_providers(db, skip=0, limit=500) if p.organization_id == organization_id]
        drivers = [d for d in get_all_drivers(db, skip=0, limit=500) if d.organization_id == organization_id]

        ride_status_counts = {
            "pending": sum(1 for ride in rides if ride.status == RideStatus.PENDING),
            "in_transit": sum(1 for ride in rides if ride.status == RideStatus.IN_TRANSIT),
            "completed": sum(1 for ride in rides if ride.status == RideStatus.COMPLETED),
        }
        drivers_available = sum(1 for driver in drivers if driver.status == DriverStatus.AVAILABLE)

        open_workflows = [w for w in workflows if str(w.get("status", "")).lower() not in {"completed", "resolved"}]

        recommendations = OperationalIntelligenceService.build_recommendations(db, organization_id)

        readiness_score = 0
        readiness_score += 1 if ride_status_counts["pending"] < max(5, len(rides) // 2 or 1) else 0
        readiness_score += 1 if len(alerts) <= 3 else 0
        readiness_score += 1 if len(open_workflows) <= 5 else 0
        readiness_score += 1 if drivers_available >= 1 else 0
        readiness_label = "high" if readiness_score >= 3 else "medium" if readiness_score == 2 else "needs_attention"

        return {
            "metrics": metrics,
            "health": health,
            "alerts": alerts,
            "workflows": workflows,
            "open_workflow_count": len(open_workflows),
            "rides_total": len(rides),
            "rides_pending": ride_status_counts["pending"],
            "rides_in_transit": ride_status_counts["in_transit"],
            "rides_completed": ride_status_counts["completed"],
            "drivers_total": len(drivers),
            "drivers_available": drivers_available,
            "providers_total": len(providers),
            "dispatch_health": health.get("status") or "stable",
            "workflow_health": "stable" if len(open_workflows) <= 3 else "watch" if len(open_workflows) <= 8 else "critical",
            "enterprise_readiness": readiness_label,
            "ai_dispatch_summary": list(recommendations.get("recommendation_summaries") or [])[:5],
        }

    @classmethod
    def _build_completion_estimate(cls, memory: dict[str, Any], context: dict[str, Any]) -> str:
        readiness = context.get("enterprise_readiness", "medium")
        base = 72 if readiness == "high" else 61 if readiness == "medium" else 48
        if str(memory.get("deployment_readiness_status", "")).lower().startswith("production"):
            base = min(95, base + 15)
        return f"{base}%"

    @classmethod
    def _build_system_health_summary(cls, context: dict[str, Any]) -> str:
        alerts = len(context.get("alerts") or [])
        open_workflows = int(context.get("open_workflow_count") or 0)
        rides_pending = int(context.get("rides_pending") or 0)

        if alerts >= 5 or open_workflows >= 10:
            return "Elevated risk: immediate triage recommended for alerts and workflow backlog."
        if alerts >= 2 or rides_pending >= 8:
            return "Operationally stable with watch items; continue proactive dispatch monitoring."
        return "System health is stable with low operational risk and manageable dispatch load."

    @classmethod
    def _build_business_checklist_status(cls, memory: dict[str, Any]) -> str:
        status = str(memory.get("business_setup_status") or "foundation-in-progress")
        deploy = str(memory.get("deployment_readiness_status") or "staging-validation-pending")
        return f"Business setup: {status}; Deployment readiness: {deploy}."

    @classmethod
    def get_status(cls, db: Session, organization_id: str) -> NovaStatusResponse:
        memory = cls._read_memory(organization_id)
        health_ctx = cls._get_health_isf_context(db, organization_id)
        return NovaStatusResponse(
            status="ok",
            organization_id=organization_id,
            generated_at=cls._now(),
            mode_default="founder_advisor",
            current_platform_phase=memory["current_build_phase"],
            next_recommended_action=memory["next_recommended_step"],
            build_completion_estimate=cls._build_completion_estimate(memory, health_ctx),
            system_health_summary=cls._build_system_health_summary(health_ctx),
            business_legal_checklist_status=cls._build_business_checklist_status(memory),
            memory=NovaMemoryState(**memory),
        )

    @classmethod
    def get_context(cls, db: Session, organization_id: str) -> NovaContextResponse:
        memory = cls._read_memory(organization_id)
        health_ctx = cls._get_health_isf_context(db, organization_id)

        summary = NovaHealthISFSummary(
            organization_id=organization_id,
            rides_total=health_ctx["rides_total"],
            rides_pending=health_ctx["rides_pending"],
            rides_in_transit=health_ctx["rides_in_transit"],
            rides_completed=health_ctx["rides_completed"],
            drivers_total=health_ctx["drivers_total"],
            drivers_available=health_ctx["drivers_available"],
            providers_total=health_ctx["providers_total"],
            alerts_open=len(health_ctx.get("alerts") or []),
            workflow_open_incidents=health_ctx["open_workflow_count"],
            dispatch_health=str(health_ctx.get("dispatch_health") or "stable"),
            workflow_health=str(health_ctx.get("workflow_health") or "stable"),
            enterprise_readiness=str(health_ctx.get("enterprise_readiness") or "medium"),
            ai_dispatch_summary=list(health_ctx.get("ai_dispatch_summary") or []),
        )

        return NovaContextResponse(
            generated_at=cls._now(),
            organization_id=organization_id,
            active_modules=cls.ACTIVE_MODULES,
            platform_phase=memory["current_build_phase"],
            build_completion_estimate=cls._build_completion_estimate(memory, health_ctx),
            system_health_summary=cls._build_system_health_summary(health_ctx),
            business_legal_checklist_status=cls._build_business_checklist_status(memory),
            operational_health={
                "metrics": health_ctx.get("metrics", {}),
                "health": health_ctx.get("health", {}),
                "alert_count": len(health_ctx.get("alerts") or []),
            },
            workflow_status={
                "open_incidents": health_ctx.get("open_workflow_count", 0),
                "latest": list(health_ctx.get("workflows") or [])[:8],
            },
            health_isf_summary=summary,
            memory=NovaMemoryState(**memory),
        )

    @classmethod
    def ask(
        cls,
        db: Session,
        organization_id: str,
        mode: NovaMode,
        question: str,
    ) -> NovaAskResponse:
        context = cls.get_context(db, organization_id)
        answer, execution_mode = cls._llm_answer(mode, question, context)

        next_actions = cls._build_next_action_list(mode, context)

        cls._record_memory_event(
            organization_id,
            channel="founder_continuity",
            event_type="nova_ask",
            summary=f"Question handled in mode={mode}: {question.strip()[:180]}",
            source="nova.ask",
            tags=["reasoning", "continuity", mode],
            metadata={
                "execution_mode": execution_mode,
                "next_actions_count": len(next_actions),
            },
        )

        return NovaAskResponse(
            mode=mode,
            answer=answer,
            next_actions=next_actions,
            context_used={
                "organization_id": organization_id,
                "active_modules": context.active_modules,
                "health_isf": context.health_isf_summary.model_dump(),
                "execution_mode": execution_mode,
                "llm_enabled": cls._can_use_llm(),
            },
            generated_at=cls._now(),
        )

    @classmethod
    def summarize(
        cls,
        db: Session,
        organization_id: str,
        summary_type: str,
        mode: NovaMode,
        source_text: str | None,
    ) -> NovaSummarizeResponse:
        context = cls.get_context(db, organization_id)
        hs = context.health_isf_summary

        if summary_type == "health_isf_dispatch":
            summary = (
                f"Health ISF dispatch currently has {hs.rides_total} rides, {hs.rides_pending} pending, "
                f"{hs.drivers_available} available drivers, and {hs.alerts_open} open alerts."
            )
            highlights = [
                f"Dispatch health: {hs.dispatch_health}",
                f"Workflow health: {hs.workflow_health}",
                f"Enterprise readiness: {hs.enterprise_readiness}",
            ]
        elif summary_type == "build_progress":
            summary = (
                f"Platform phase: {context.platform_phase}. Build completion estimate: {context.build_completion_estimate}. "
                f"Next recommended action: {context.memory.next_recommended_step}."
            )
            highlights = [
                f"Active module: {context.memory.active_module}",
                f"Last milestone: {context.memory.last_completed_milestone}",
                f"Deployment status: {context.memory.deployment_readiness_status}",
            ]
        elif summary_type == "business_next_steps":
            summary = (
                "Business and operational momentum is positive; focus on governance, deployment readiness, "
                "and measurable dispatch reliability outcomes."
            )
            highlights = [
                context.business_legal_checklist_status,
                "Keep founder checklist aligned with operational milestones.",
                "Document enterprise readiness evidence for partners and grants.",
            ]
        else:
            summary = (
                f"System health summary: {context.system_health_summary} "
                f"Open workflow incidents: {hs.workflow_open_incidents}."
            )
            highlights = [
                f"Alert count: {hs.alerts_open}",
                f"Rides pending: {hs.rides_pending}",
                f"Drivers available: {hs.drivers_available}",
            ]

        if source_text:
            summary = f"{summary} Source note: {source_text[:320].strip()}"

        cls._record_memory_event(
            organization_id,
            channel="operational_history",
            event_type="nova_summarize",
            summary=f"Generated {summary_type} summary in mode={mode}",
            source="nova.summarize",
            tags=["summary", summary_type, mode],
            metadata={
                "highlights": highlights[:3],
            },
        )

        return NovaSummarizeResponse(
            summary_type=summary_type,
            mode=mode,
            summary=summary,
            highlights=highlights,
            generated_at=cls._now(),
        )

    @classmethod
    def _build_next_action_list(cls, mode: NovaMode, context: NovaContextResponse) -> list[str]:
        hs = context.health_isf_summary
        action_seed = {
            "founder_advisor": [
                "Align this week targets to one measurable platform KPI.",
                "Confirm legal and business checklist owners.",
                "Lock the next milestone demo scope.",
            ],
            "engineering_director": [
                "Add regression tests for new operational endpoints.",
                "Track unresolved workflow incidents and root causes.",
                "Validate deployment readiness in staging.",
            ],
            "operations_commander": [
                "Triage open operational alerts by severity.",
                "Reduce pending queue aging for high-priority rides.",
                "Audit replay and resilience workflows.",
            ],
            "business_strategist": [
                "Prepare enterprise readiness narrative for partners.",
                "Map launch plan to dispatch reliability outcomes.",
                "Refresh revenue and operating assumptions.",
            ],
            "grant_advisor": [
                "Capture latest operational metrics as grant evidence.",
                "Document milestones, impact, and compliance items.",
                "Prepare a concise execution timeline.",
            ],
            "dispatch_supervisor": [
                "Balance driver assignment for pending rides.",
                "Review provider latency and exception patterns.",
                "Validate dispatch timeline and alert coverage.",
            ],
        }

        extra = []
        if hs.alerts_open > 0:
            extra.append("Resolve critical operational alerts before expanding feature scope.")
        if hs.rides_pending > max(5, hs.rides_total // 2 if hs.rides_total else 5):
            extra.append("Run queue-thinning actions for pending rides to protect SLA windows.")

        return (action_seed.get(mode, action_seed["founder_advisor"]) + extra)[:5]

    @classmethod
    def next_step(
        cls,
        db: Session,
        organization_id: str,
        mode: NovaMode,
        goal: str | None,
    ) -> NovaNextStepResponse:
        context = cls.get_context(db, organization_id)
        checklist = cls._build_next_action_list(mode, context)
        selected = checklist[0] if checklist else context.memory.next_recommended_step
        if goal:
            selected = f"{selected} Goal alignment: {goal.strip()[:160]}"

        memory_store.write(
            organization_id,
            {
                "next_recommended_step": selected,
                "active_module": "nova",
            },
        )

        cls._record_memory_event(
            organization_id,
            channel="founder_continuity",
            event_type="nova_next_step",
            summary=f"Next step selected: {selected[:220]}",
            source="nova.next_step",
            tags=["continuity", "execution", mode],
            metadata={"goal": goal[:160] if goal else None},
        )

        return NovaNextStepResponse(
            mode=mode,
            current_phase=context.platform_phase,
            next_recommended_step=selected,
            checklist=checklist,
            generated_at=cls._now(),
        )

    @classmethod
    def review_report(
        cls,
        db: Session,
        organization_id: str,
        mode: NovaMode,
        report_title: str | None,
        report_text: str,
    ) -> NovaReviewReportResponse:
        _ = cls.get_context(db, organization_id)

        text = (report_text or "").strip()
        lowered = text.lower()

        strengths = []
        risks = []
        actions = []

        if "test" in lowered or "validation" in lowered:
            strengths.append("Includes validation or testing evidence.")
        if "tenant" in lowered or "rbac" in lowered or "auth" in lowered:
            strengths.append("References tenant isolation and access control safeguards.")
        if "rollback" in lowered or "resilience" in lowered:
            strengths.append("Mentions operational resilience or rollback posture.")

        if "todo" in lowered or "tbd" in lowered:
            risks.append("Contains unresolved placeholders that can hide delivery risk.")
        if "manual" in lowered and "test" in lowered:
            risks.append("Depends on manual-only testing; automation coverage may be insufficient.")
        if "not implemented" in lowered or "missing" in lowered:
            risks.append("Report indicates incomplete implementation areas.")

        actions.append("Convert report findings into prioritized execution tasks with owners.")
        actions.append("Add measurable acceptance checks for each recommendation.")
        if not strengths:
            strengths.append("Structured report provided for analysis.")
        if not risks:
            risks.append("No major textual risk markers detected; verify with runtime evidence.")

        executive_summary = (
            "Report review completed with emphasis on architecture safety, operational readiness, "
            "and additive delivery continuity."
        )

        memory_store.write(
            organization_id,
            {
                "last_completed_milestone": report_title or "Reviewed implementation report",
            },
        )

        cls._record_memory_event(
            organization_id,
            channel="workflow_history",
            event_type="nova_review_report",
            summary=f"Reviewed report: {(report_title or 'Implementation Report')[:120]}",
            source="nova.review_report",
            tags=["workflow", "review", mode],
            metadata={
                "strengths_count": len(strengths),
                "risks_count": len(risks),
                "actions_count": len(actions),
            },
        )

        return NovaReviewReportResponse(
            report_title=report_title or "Implementation Report",
            mode=mode,
            executive_summary=executive_summary,
            strengths=strengths[:5],
            risks=risks[:5],
            recommended_actions=actions[:5],
            generated_at=cls._now(),
        )

    @classmethod
    def founder_checklist(cls, db: Session, organization_id: str) -> list[str]:
        context = cls.get_context(db, organization_id)
        return [
            "Confirm this week strategic objective and measurable KPI.",
            f"Review platform phase: {context.platform_phase}.",
            f"Review deployment readiness: {context.memory.deployment_readiness_status}.",
            "Validate enterprise RBAC and tenant isolation posture.",
            "Approve next action plan before broad rollout.",
        ]

    @classmethod
    def responsibilities(cls) -> list[str]:
        return list(NOVA_RESPONSIBILITIES)

    @classmethod
    def get_memory_fabric_snapshot(cls, db: Session, organization_id: str) -> dict[str, Any]:
        context = cls.get_context(db, organization_id)
        fabric = memory_store.read_fabric(organization_id)
        continuity_summary = cls._continuity_summary(organization_id)
        return {
            "organization_id": organization_id,
            "generated_at": cls._now(),
            "memory_fabric": fabric,
            "continuity_summary": continuity_summary,
            "current_phase": context.platform_phase,
            "next_recommended_step": context.memory.next_recommended_step,
        }

    @classmethod
    def add_memory_event(
        cls,
        db: Session,
        organization_id: str,
        *,
        channel: str,
        event_type: str,
        summary: str,
        source: str,
        tags: list[str] | None = None,
        metadata: dict[str, Any] | None = None,
        correlation_id: str | None = None,
    ) -> dict[str, Any]:
        _ = db
        event = memory_store.append_event(
            organization_id,
            channel,
            {
                "event_type": event_type,
                "summary": summary,
                "source": source,
                "tags": list(tags or []),
                "metadata": dict(metadata or {}),
                "correlation_id": correlation_id,
            },
        )
        return {
            "organization_id": organization_id,
            "generated_at": cls._now(),
            "memory_fabric": memory_store.read_fabric(organization_id),
            "continuity_summary": cls._continuity_summary(organization_id),
            "event": event,
        }

    @classmethod
    def get_continuity_brief(cls, db: Session, organization_id: str) -> dict[str, Any]:
        context = cls.get_context(db, organization_id)
        fabric = memory_store.read_fabric(organization_id)
        founder = list(fabric.get("founder_continuity") or [])[:6]
        op_history = list(fabric.get("operational_history") or [])[:10]
        top_risks = []
        for item in op_history:
            summary = str(item.get("summary") or "").strip()
            if summary:
                top_risks.append(summary)
            if len(top_risks) >= 5:
                break

        for risk in list(fabric.get("operational_risks") or [])[:8]:
            summary = str((risk or {}).get("summary") or "").strip()
            if summary and summary not in top_risks:
                top_risks.append(summary)
            if len(top_risks) >= 6:
                break

        founder_notes = [str(item.get("summary") or "").strip() for item in founder if str(item.get("summary") or "").strip()][:5]
        strategic_focus = list(fabric.get("unresolved_priorities") or context.memory.founder_priorities or [])[:6]
        next_actions = cls._build_next_action_list("founder_advisor", context)
        return {
            "organization_id": organization_id,
            "generated_at": cls._now(),
            "current_phase": context.platform_phase,
            "strategic_focus": strategic_focus,
            "unresolved_operational_risks": top_risks,
            "founder_continuity_notes": founder_notes,
            "next_actions": next_actions,
        }

    @classmethod
    def update_business_state(
        cls,
        db: Session,
        organization_id: str,
        *,
        objectives: list[str] | None,
        kpis: dict[str, Any] | None,
        active_initiatives: list[str] | None,
    ) -> dict[str, Any]:
        _ = db
        patch: dict[str, Any] = {}
        if objectives is not None:
            patch["objectives"] = [str(item).strip() for item in objectives if str(item).strip()][:20]
        if kpis is not None:
            patch["kpis"] = dict(kpis)
        if active_initiatives is not None:
            patch["active_initiatives"] = [str(item).strip() for item in active_initiatives if str(item).strip()][:30]
        business_state = memory_store.update_business_state(organization_id, patch)
        deployment_status = "staging-validation-pending"
        initiatives_lower = [str(item).lower() for item in list(business_state.get("active_initiatives") or [])]
        if any("production" in item or "go-live" in item for item in initiatives_lower):
            deployment_status = "production-readiness-tracked"
        elif any("deploy" in item or "release" in item for item in initiatives_lower):
            deployment_status = "deployment-workstream-active"
        memory_store.update_deployment_state(
            organization_id,
            deployment_status,
            {
                "objective_count": len(list(business_state.get("objectives") or [])),
                "initiative_count": len(list(business_state.get("active_initiatives") or [])),
            },
        )
        cls._record_memory_event(
            organization_id,
            channel="founder_continuity",
            event_type="business_state_update",
            summary="Business execution state updated",
            source="nova.business_state",
            tags=["business", "continuity"],
            metadata={
                "objective_count": len(list(business_state.get("objectives") or [])),
                "initiative_count": len(list(business_state.get("active_initiatives") or [])),
            },
        )
        return {
            "organization_id": organization_id,
            "generated_at": cls._now(),
            "business_state": business_state,
        }

    @classmethod
    def session_heartbeat(
        cls,
        db: Session,
        organization_id: str,
        *,
        session_id: str | None,
        status: str,
    ) -> dict[str, Any]:
        _ = db
        fabric = memory_store.read_fabric(organization_id)
        previous_stability = dict(fabric.get("session_stability") or {})
        last_status = str(previous_stability.get("last_status") or "").lower()
        last_heartbeat_at = previous_stability.get("last_heartbeat_at")
        stale_busy = False
        if last_status == "busy" and last_heartbeat_at:
            try:
                age_seconds = max(0.0, (datetime.now(timezone.utc) - datetime.fromisoformat(str(last_heartbeat_at))).total_seconds())
                stale_busy = age_seconds > 120
            except Exception:
                stale_busy = False

        stability = memory_store.heartbeat(organization_id, session_id, status)

        if stale_busy and str(status or "").lower() in {"active", "idle"}:
            cls._record_memory_event(
                organization_id,
                channel="workflow_history",
                event_type="stale_execution_cleanup",
                summary="Recovered stale busy execution state during heartbeat",
                source="nova.session_heartbeat",
                tags=["stability", "recovery"],
                metadata={"recovery_attempt": 1, "stage": "recovery_attempt"},
                correlation_id=f"heartbeat-{session_id or 'global'}",
            )

        return {
            "organization_id": organization_id,
            "generated_at": cls._now(),
            "session_stability": stability,
        }

    @classmethod
    def _mk_recommendation(
        cls,
        *,
        category: str,
        priority: str,
        reason: str,
        impact: str,
        urgency: str,
        suggested_action: str,
        confidence: float,
        impacted_surface: str,
        operational_risk: str,
        related_event_ids: list[str] | None = None,
        approval_required: bool = False,
        metadata: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        timestamp = cls._now()
        return {
            "category": category,
            "priority": priority,
            "reason": reason,
            "impact": impact,
            "urgency": urgency,
            "suggested_action": suggested_action,
            "confidence": max(0.0, min(1.0, float(confidence))),
            "related_event_ids": list(related_event_ids or []),
            "timestamp": timestamp,
            "summary": suggested_action,
            "title": f"{category.capitalize()} recommendation",
            "operational_risk": operational_risk,
            "approval_required": approval_required,
            "execution_mode": "approval_required" if approval_required else "recommendation_only",
            "impacted_surface": impacted_surface,
            "synchronization_impact": "replay-safe",
            "metadata": dict(metadata or {}),
        }

    @classmethod
    def _build_operational_recommendations(
        cls,
        context: NovaContextResponse,
        fabric: dict[str, Any],
        events: list[dict[str, Any]],
    ) -> list[dict[str, Any]]:
        business_state = dict(fabric.get("business_state") or {})
        kpis = dict(business_state.get("kpis") or {})
        deployment_state = dict(fabric.get("deployment_state") or {})

        severity_to_urgency = {
            "critical": "critical",
            "high": "high",
            "medium": "medium",
            "low": "low",
            "info": "low",
        }
        severity_to_impact = {
            "critical": "high",
            "high": "high",
            "medium": "medium",
            "low": "low",
            "info": "low",
        }

        mapping = {
            "provider_shortage": {
                "category": "staffing",
                "surface": "provider_analytics",
                "default_action": "Escalate provider coverage and rebalance dispatch allocation.",
            },
            "inactive_provider_clusters": {
                "category": "growth",
                "surface": "provider_analytics",
                "default_action": "Re-activate inactive provider clusters with targeted incentives.",
            },
            "ride_spike": {
                "category": "operational",
                "surface": "rides_runtime",
                "default_action": "Prioritize queue-thinning for pending rides and monitor SLA risk.",
            },
            "dispatch_bottleneck": {
                "category": "operational",
                "surface": "rides_runtime",
                "default_action": "Escalate workflow backlog and reassign dispatch ownership.",
            },
            "cancellation_spike": {
                "category": "revenue",
                "surface": "dashboard",
                "default_action": "Investigate cancellation drivers and deploy retention actions.",
            },
            "websocket_instability": {
                "category": "reliability",
                "surface": "dashboard",
                "default_action": "Stabilize websocket lifecycle and reduce reconnect churn.",
            },
            "stale_busy_state": {
                "category": "deployment",
                "surface": "operational_summaries",
                "default_action": "Release stale busy runtime states via recovery-safe heartbeat flow.",
            },
            "repeated_execution_failure": {
                "category": "risk",
                "surface": "operational_summaries",
                "default_action": "Pause repeated failing flows and require approval-safe recovery execution.",
            },
            "api_degradation": {
                "category": "reliability",
                "surface": "dashboard",
                "default_action": "Reduce non-critical runtime calls while degraded endpoints recover.",
            },
        }

        recommendations: list[dict[str, Any]] = []
        seen_categories: set[str] = set()

        for event in events:
            event_type = str(event.get("event_type") or "").strip().lower()
            if not event_type or event_type not in mapping:
                continue
            cfg = mapping[event_type]
            severity = str(event.get("severity") or "info").lower()
            context_snapshot = dict(event.get("operational_context") or {})
            suggested_action = str(event.get("recommended_action") or cfg["default_action"])
            reason = (
                f"Event {event_type} observed with evidence "
                f"{context_snapshot if context_snapshot else {'severity': severity}}"
            )
            category = str(cfg["category"])
            seen_categories.add(category)

            recommendations.append(cls._mk_recommendation(
                category=category,
                priority="high" if severity in {"critical", "high"} else "medium" if severity == "medium" else "low",
                reason=reason,
                impact=severity_to_impact.get(severity, "medium"),
                urgency=severity_to_urgency.get(severity, "medium"),
                suggested_action=suggested_action,
                confidence=0.92 if severity == "critical" else 0.86 if severity == "high" else 0.72 if severity == "medium" else 0.6,
                impacted_surface=str(cfg["surface"]),
                operational_risk=severity,
                related_event_ids=[str(event.get("event_id") or "")],
                approval_required=severity in {"critical", "high"},
                metadata={
                    "source": event.get("source"),
                    "event_type": event_type,
                    "operational_context": context_snapshot,
                    "recovery_hint": event.get("recovery_hint"),
                },
            ))

        if "deployment" not in seen_categories:
            deploy_status = str(deployment_state.get("status") or context.memory.deployment_readiness_status or "staging-validation-pending")
            recommendations.append(cls._mk_recommendation(
                category="deployment",
                priority="medium",
                reason=f"Deployment state evidence: {deploy_status}",
                impact="medium",
                urgency="medium",
                suggested_action="Validate deployment gates and rollback readiness with latest runtime evidence.",
                confidence=0.68,
                impacted_surface="operational_summaries",
                operational_risk="medium",
                related_event_ids=[],
                approval_required=True,
                metadata={"deployment_state": deploy_status},
            ))

        if "revenue" not in seen_categories:
            workflow_target = float(kpis.get("workflow_success_target") or 95)
            recommendations.append(cls._mk_recommendation(
                category="revenue",
                priority="medium",
                reason=f"Revenue protection anchored to workflow target KPI {workflow_target}",
                impact="medium",
                urgency="medium",
                suggested_action="Review weekly revenue-risk impact against dispatch reliability trend.",
                confidence=0.64,
                impacted_surface="dashboard",
                operational_risk="low",
                related_event_ids=[],
                metadata={"workflow_success_target": workflow_target},
            ))

        return recommendations[:10]

    @classmethod
    def get_assistance_recommendations(cls, db: Session, organization_id: str) -> dict[str, Any]:
        context = cls.get_context(db, organization_id)
        fabric = memory_store.read_fabric(organization_id)

        detected_events = build_operational_events(context, fabric)
        published = nova_event_bus.publish_events(organization_id, detected_events)
        live_events = list(published.get("events") or [])
        recommendations = cls._build_operational_recommendations(context, fabric, live_events)

        summary = (
            f"Generated {len(recommendations)} event-driven recommendations from "
            f"{len(live_events)} live operational events for phase {context.platform_phase}."
        )

        memory_store.add_recommendations(organization_id, recommendations)

        cls._record_memory_event(
            organization_id,
            channel="operational_history",
            event_type="assistance_recommendations",
            summary=summary,
            source="nova.assistance",
            tags=["phase6e", "event_driven", "recommendations"],
            metadata={
                "count": len(recommendations),
                "live_event_count": len(live_events),
            },
        )

        return {
            "organization_id": organization_id,
            "generated_at": cls._now(),
            "recommendations": recommendations,
            "reasoning_summary": summary,
        }

    @classmethod
    def get_live_events(cls, db: Session, organization_id: str, *, limit: int = 60) -> dict[str, Any]:
        context = cls.get_context(db, organization_id)
        fabric = memory_store.read_fabric(organization_id)
        detected_events = build_operational_events(context, fabric)
        nova_event_bus.publish_events(organization_id, detected_events)
        events = nova_event_bus.replay_events(organization_id, limit=limit)
        return {
            "organization_id": organization_id,
            "generated_at": cls._now(),
            "events": events,
            "reasoning_summary": f"Live event stream includes {len(events)} replay-safe operational events.",
        }

    @classmethod
    def get_intelligence_report(cls, db: Session, organization_id: str) -> dict[str, Any]:
        """
        Full operational intelligence report: scoring, bottlenecks, stale rides,
        overloaded drivers, provider imbalance, and recommended actions.

        Uses NovaIntelligenceEngine — no external AI services, no validate_query_optimization.
        """
        from app.core.nova.intelligence import NovaIntelligenceEngine
        return NovaIntelligenceEngine.full_intelligence_report(db, organization_id)
