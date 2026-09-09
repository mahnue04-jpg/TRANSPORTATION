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
ACTION_STATUSES = ("proposed", "approved", "dismissed", "done")
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
    href: str
    trust_label: str
    priority: int
    recommended_action: str
    action_id: str | None = None
    status: str | None = None


class NovaTodayActionOut(BaseModel):
    action_id: str
    organization_id: str
    owner_user_id: str
    source_module: str
    source_ref_id: str
    title: str
    detail: str | None
    href: str | None
    trust_label: str
    priority: int
    status: str
    recommended_action: str
    result_ref_id: str | None
    created_at: datetime
    decided_at: datetime | None


class NovaTodayDashboardOut(BaseModel):
    attention_now: list[NovaTodayCard]
    communications: list[NovaTodayCard]
    government: list[NovaTodayCard]
    business: list[NovaTodayCard]
    workspace: list[NovaTodayCard]
    product_links: list[NovaTodayCard]
    recommendations: list[NovaTodayCard]
    approval_queue: list[NovaTodayActionOut]
    trust_labels: list[str] = Field(default_factory=lambda: list(TRUST_LABELS))


class NovaTodayBrainRequest(BaseModel):
    question: str = Field(min_length=3, max_length=4000)
    organization_id: str | None = None


class NovaTodayBrainOut(BaseModel):
    answer: str
    fact_label: str
    next_actions: list[str] = Field(default_factory=list)
    generated_at: str


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


class NovaTodaySafetyOut(BaseModel):
    refused: bool = True
    detail: str
    extra: dict[str, Any] = Field(default_factory=dict)
