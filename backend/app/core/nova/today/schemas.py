"""Nova V2 Today schemas. Additive Command Center only."""
from __future__ import annotations

from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, Field

TRUST_LABELS = (
    "VERIFIED DATA",
    "USER-SAVED INFORMATION",
    "AI SUGGESTION",
    "ACTION REQUIRES APPROVAL",
)
RECOMMENDED_ACTIONS = ("open_link", "create_draft", "create_task", "acknowledge")
ACTION_STATUSES = ("proposed", "approved", "dismissed", "done", "snoozed")
SNOOZE_HOURS = (1, 4, 24, 72)
SOURCE_MODULES = (
    "workspace",
    "communications",
    "government",
    "business",
    "link",
)


class NovaTodayCard(BaseModel):
    source_module: str
    source_ref_id: str
    title: str
    detail: str | None = None
    explanation: str | None = None
    source_label: str | None = None
    sender: str | None = None
    subject: str | None = None
    href: str | None = None
    trust_label: str
    priority: int
    priority_band: str | None = None
    recommended_action: str
    why_recommended: str | None = None
    if_approved: str | None = None
    will_not_happen: str | None = None
    action_id: str | None = None
    status: str | None = None
    received_at: datetime | None = None
    source_href: str | None = None


class NovaTodayActionOut(BaseModel):
    action_id: str
    organization_id: str
    owner_user_id: str
    source_module: str
    source_ref_id: str
    title: str
    detail: str | None
    explanation: str | None = None
    source_label: str | None = None
    href: str | None
    trust_label: str
    priority: int
    priority_band: str | None = None
    status: str
    recommended_action: str
    why_recommended: str | None = None
    if_approved: str | None = None
    will_not_happen: str | None = None
    result_ref_id: str | None
    created_at: datetime
    decided_at: datetime | None
    snoozed_until: datetime | None = None
    prior_status: str | None = None
    resulting_status: str | None = None
    result_type: str | None = None
    actor_user_id: str | None = None
    source_href: str | None = None
    source_details: dict[str, str] | None = None
    related_history: list["NovaTodayHistoryItem"] = Field(default_factory=list)
    why_surfaced: str | None = None


class NovaTodayProductCount(BaseModel):
    key: str
    label: str
    metric: str
    count: int | None = None
    status: Literal["ok", "unavailable"]
    href: str
    trust_label: str = "VERIFIED DATA"


class NovaTodaySourceHealth(BaseModel):
    source: str
    status: Literal["ok", "empty", "unavailable", "partial"]
    detail: str
    connector: Literal["connected", "disconnected", "n/a"] = "n/a"


class NovaTodayHistoryItem(BaseModel):
    action_id: str
    source_module: str
    source_ref_id: str
    title: str
    prior_status: str
    resulting_status: str
    result_ref_id: str | None = None
    actor_user_id: str
    decided_at: datetime | None = None
    trust_label: str
    recommended_action: str
    result_type: str
    source_href: str | None = None


class NovaTodayDashboardOut(BaseModel):
    attention_now: list[NovaTodayCard]
    communications: list[NovaTodayCard]
    government: list[NovaTodayCard]
    business: list[NovaTodayCard]
    workspace: list[NovaTodayCard]
    product_links: list[NovaTodayCard]
    product_counts: list[NovaTodayProductCount] = Field(default_factory=list)
    recommendations: list[NovaTodayCard]
    approval_queue: list[NovaTodayActionOut]
    recent_activity: list[NovaTodayHistoryItem] = Field(default_factory=list)
    source_health: list[NovaTodaySourceHealth] = Field(default_factory=list)
    trust_labels: list[str] = Field(default_factory=lambda: list(TRUST_LABELS))


class NovaTodayBrainRequest(BaseModel):
    question: str = Field(min_length=3, max_length=4000)
    organization_id: str | None = None
    action_id: str | None = Field(default=None, max_length=32)
    source_ref_id: str | None = Field(default=None, max_length=80)


class NovaTodayBrainOut(BaseModel):
    answer: str
    fact_label: str
    next_actions: list[str] = Field(default_factory=list)
    generated_at: str
    source_href: str | None = None
    referenced_action_id: str | None = None
    referenced_source_ref_id: str | None = None


class NovaTodayActionCreate(BaseModel):
    source_module: Literal["workspace", "communications", "government", "business", "link"]
    source_ref_id: str = Field(min_length=1, max_length=80)
    title: str = Field(min_length=2, max_length=240)
    detail: str | None = Field(default=None, max_length=4000)
    href: str | None = Field(default=None, max_length=400)
    trust_label: Literal[
        "VERIFIED DATA",
        "USER-SAVED INFORMATION",
        "AI SUGGESTION",
        "ACTION REQUIRES APPROVAL",
    ] = "ACTION REQUIRES APPROVAL"
    priority: int = Field(default=50, ge=0, le=100)
    recommended_action: Literal["open_link", "create_draft", "create_task", "acknowledge"]
    organization_id: str | None = None


class NovaTodayApproveRequest(BaseModel):
    organization_id: str | None = None
    draft_to: list[str] = Field(default_factory=list)
    draft_subject: str | None = Field(default=None, max_length=512)
    draft_body: str | None = Field(default=None, max_length=20000)
    task_title: str | None = Field(default=None, max_length=220)


class NovaTodayApproveOut(BaseModel):
    action: NovaTodayActionOut
    href: str | None = None
    draft_id: str | None = None
    task_id: str | None = None
    message: str
    fact_label: str


class NovaTodaySnoozeRequest(BaseModel):
    organization_id: str | None = None
    hours: Literal[1, 4, 24, 72] = 24


class NovaTodaySafetyOut(BaseModel):
    refused: bool = True
    detail: str
    extra: dict[str, Any] = Field(default_factory=dict)
