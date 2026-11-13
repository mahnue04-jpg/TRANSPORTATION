"""Pydantic request/response schemas for Growth Agent APIs."""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field


class OrgScoped(BaseModel):
    organization_id: str | None = None


class ProfileUpsertIn(OrgScoped):
    business_name: str
    website: str | None = None
    timezone: str = "America/Chicago"
    operating_hours: dict[str, Any] = Field(default_factory=dict)
    services: list[dict[str, Any]] = Field(default_factory=list)
    faqs: list[dict[str, Any]] = Field(default_factory=list)
    contact_email: str | None = None
    handoff_phone: str | None = None
    escalation_settings: dict[str, Any] = Field(default_factory=dict)
    branding: dict[str, Any] = Field(default_factory=dict)
    quiet_hours: dict[str, Any] = Field(default_factory=dict)
    plan_code: str = "starter"
    activate: bool = False
    preview_only: bool = False
    is_synthetic_demo: bool = False


class AgentStateIn(OrgScoped):
    paused: bool | None = None
    disabled: bool | None = None


class WidgetCreateIn(OrgScoped):
    domain: str
    branding: dict[str, Any] = Field(default_factory=dict)


class WidgetChatIn(BaseModel):
    token: str
    message: str
    conversation_id: str | None = None
    visitor_name: str | None = None
    visitor_email: str | None = None
    consent_marketing: bool = False
    consent_transactional: bool = False


class LeadUpdateIn(OrgScoped):
    lead_state: str | None = None
    notes: str | None = None


class ConsentIn(OrgScoped):
    contact_id: str
    channel: str
    purpose: str
    status: str
    collection_source: str = "owner_dashboard"


class WorkflowPreviewIn(OrgScoped):
    workflow_code: str
    contact_id: str
    conversation_id: str | None = None


class WorkflowReviewDecisionIn(OrgScoped):
    decision: str  # reject | request_information; approval is intentionally unavailable


class WorkflowExecuteIn(OrgScoped):
    run_id: str
    dry_run: bool = True
    idempotency_key: str | None = None


class AvailabilityIn(OrgScoped):
    service_code: str
    day: str  # YYYY-MM-DD


class BookIn(OrgScoped):
    contact_id: str
    service_code: str
    starts_at_utc: str
    idempotency_key: str
    conversation_id: str | None = None
    is_synthetic_demo: bool = False


class RescheduleIn(OrgScoped):
    starts_at_utc: str
    idempotency_key: str


class RetentionIn(OrgScoped):
    batch_limit: int = 500


class WorkerTickIn(OrgScoped):
    limit: int = 10


class RetentionScheduleTickIn(OrgScoped):
    limit: int = 10
    window_key: str | None = None
    ensure: bool = True
