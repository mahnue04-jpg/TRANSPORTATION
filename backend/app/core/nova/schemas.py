from __future__ import annotations

from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, Field

NovaMode = Literal[
    "founder_advisor",
    "engineering_director",
    "operations_commander",
    "business_strategist",
    "grant_advisor",
    "dispatch_supervisor",
]

NovaRecommendationCategory = Literal[
    "risk",
    "growth",
    "deployment",
    "workflow",
    "staffing",
    "revenue",
    "reliability",
    "operational",
]


class NovaMemoryState(BaseModel):
    current_build_phase: str
    active_module: str
    last_completed_milestone: str
    next_recommended_step: str
    founder_priorities: list[str] = Field(default_factory=list)
    business_setup_status: str
    deployment_readiness_status: str
    updated_at: str


class NovaHealthISFSummary(BaseModel):
    organization_id: str
    rides_total: int
    rides_pending: int
    rides_in_transit: int
    rides_completed: int
    drivers_total: int
    drivers_available: int
    providers_total: int
    alerts_open: int
    workflow_open_incidents: int
    dispatch_health: str
    workflow_health: str
    enterprise_readiness: str
    ai_dispatch_summary: list[str] = Field(default_factory=list)


class NovaContextResponse(BaseModel):
    generated_at: str
    organization_id: str
    active_modules: list[str]
    platform_phase: str
    build_completion_estimate: str
    system_health_summary: str
    business_legal_checklist_status: str
    operational_health: dict[str, Any] = Field(default_factory=dict)
    workflow_status: dict[str, Any] = Field(default_factory=dict)
    health_isf_summary: NovaHealthISFSummary
    memory: NovaMemoryState


class NovaStatusResponse(BaseModel):
    status: str
    organization_id: str | None = None
    generated_at: str
    mode_default: NovaMode
    current_platform_phase: str
    next_recommended_action: str
    build_completion_estimate: str
    system_health_summary: str
    business_legal_checklist_status: str
    memory: NovaMemoryState


class NovaAskRequest(BaseModel):
    question: str = Field(min_length=3, max_length=4000)
    mode: NovaMode = "founder_advisor"
    organization_id: str | None = None


class NovaAskResponse(BaseModel):
    mode: NovaMode
    answer: str
    next_actions: list[str] = Field(default_factory=list)
    context_used: dict[str, Any] = Field(default_factory=dict)
    generated_at: str


class NovaSummarizeRequest(BaseModel):
    summary_type: Literal[
        "operational_health",
        "health_isf_dispatch",
        "build_progress",
        "business_next_steps",
    ] = "operational_health"
    mode: NovaMode = "operations_commander"
    organization_id: str | None = None
    source_text: str | None = Field(default=None, max_length=10000)


class NovaSummarizeResponse(BaseModel):
    summary_type: str
    mode: NovaMode
    summary: str
    highlights: list[str] = Field(default_factory=list)
    generated_at: str


class NovaNextStepRequest(BaseModel):
    mode: NovaMode = "founder_advisor"
    organization_id: str | None = None
    goal: str | None = Field(default=None, max_length=1000)


class NovaNextStepResponse(BaseModel):
    mode: NovaMode
    current_phase: str
    next_recommended_step: str
    checklist: list[str] = Field(default_factory=list)
    generated_at: str


class NovaReviewReportRequest(BaseModel):
    report_title: str | None = Field(default=None, max_length=200)
    report_text: str = Field(min_length=10, max_length=30000)
    mode: NovaMode = "engineering_director"
    organization_id: str | None = None


class NovaReviewReportResponse(BaseModel):
    report_title: str
    mode: NovaMode
    executive_summary: str
    strengths: list[str] = Field(default_factory=list)
    risks: list[str] = Field(default_factory=list)
    recommended_actions: list[str] = Field(default_factory=list)
    generated_at: str


# ─── Nova Operational Intelligence ─────────────────────────────────────────

class NovaIntelligenceRequest(BaseModel):
    organization_id: str | None = None


class NovaIntelligenceResponse(BaseModel):
    organization_id: str
    generated_at: str
    composite_score: float
    composite_label: str
    deployment_readiness: dict[str, Any] = Field(default_factory=dict)
    operational_health: dict[str, Any] = Field(default_factory=dict)
    workflow_bottlenecks: list[dict[str, Any]] = Field(default_factory=list)
    stale_rides: list[dict[str, Any]] = Field(default_factory=list)
    overloaded_drivers: list[dict[str, Any]] = Field(default_factory=list)
    provider_imbalance: list[dict[str, Any]] = Field(default_factory=list)
    recommended_actions: list[dict[str, Any]] = Field(default_factory=list)
    summary: str


class NovaDeploymentReadinessResponse(BaseModel):
    overall_status: str
    score: int
    environment: dict[str, Any] = Field(default_factory=dict)
    config_checks: dict[str, Any] = Field(default_factory=dict)
    summary: str
    recommendations: list[str] = Field(default_factory=list)


class NovaMemoryEventRequest(BaseModel):
    organization_id: str | None = None
    channel: Literal["founder_continuity", "operational_history", "workflow_history"] = "operational_history"
    event_type: str = Field(default="note", min_length=2, max_length=80)
    summary: str = Field(min_length=3, max_length=2000)
    source: str = Field(default="nova", min_length=2, max_length=80)
    tags: list[str] = Field(default_factory=list)
    metadata: dict[str, Any] = Field(default_factory=dict)
    correlation_id: str | None = Field(default=None, max_length=120)


class NovaMemoryFabricResponse(BaseModel):
    organization_id: str
    generated_at: str
    memory_fabric: dict[str, Any] = Field(default_factory=dict)
    continuity_summary: str


class NovaContinuityBriefResponse(BaseModel):
    organization_id: str
    generated_at: str
    current_phase: str
    strategic_focus: list[str] = Field(default_factory=list)
    unresolved_operational_risks: list[str] = Field(default_factory=list)
    founder_continuity_notes: list[str] = Field(default_factory=list)
    next_actions: list[str] = Field(default_factory=list)


class NovaBusinessStateUpdateRequest(BaseModel):
    organization_id: str | None = None
    objectives: list[str] | None = None
    kpis: dict[str, Any] | None = None
    active_initiatives: list[str] | None = None


class NovaBusinessStateResponse(BaseModel):
    organization_id: str
    generated_at: str
    business_state: dict[str, Any] = Field(default_factory=dict)


class NovaSessionHeartbeatRequest(BaseModel):
    organization_id: str | None = None
    session_id: str | None = Field(default=None, max_length=120)
    status: str = Field(default="active", min_length=2, max_length=80)


class NovaSessionHeartbeatResponse(BaseModel):
    organization_id: str
    generated_at: str
    session_stability: dict[str, Any] = Field(default_factory=dict)


class NovaOperationalRecommendation(BaseModel):
    category: NovaRecommendationCategory
    priority: str
    reason: str
    impact: str = "medium"
    urgency: str = "medium"
    suggested_action: str
    confidence: float = 0.0
    related_event_ids: list[str] = Field(default_factory=list)
    timestamp: str
    summary: str
    title: str | None = None
    operational_risk: str | None = None
    approval_required: bool = False
    execution_mode: str = "recommendation_only"
    impacted_surface: str | None = None
    synchronization_impact: str = "replay-safe"
    metadata: dict[str, Any] = Field(default_factory=dict)


class NovaAssistanceRecommendationsResponse(BaseModel):
    organization_id: str
    generated_at: str
    recommendations: list[NovaOperationalRecommendation] = Field(default_factory=list)
    reasoning_summary: str


class NovaLiveOperationalEvent(BaseModel):
    event_id: str
    event_type: str
    severity: str
    source: str
    timestamp: str
    correlation_id: str | None = None
    operational_context: dict[str, Any] = Field(default_factory=dict)
    recommended_action: str | None = None
    recovery_hint: str | None = None
    replay_safe: bool = True
    websocket_compatible: bool = True


class NovaLiveEventsResponse(BaseModel):
    organization_id: str
    generated_at: str
    events: list[NovaLiveOperationalEvent] = Field(default_factory=list)
    reasoning_summary: str
