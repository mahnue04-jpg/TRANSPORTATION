from __future__ import annotations

from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, Field


class NovaWorkspaceProjectCreate(BaseModel):
    title: str = Field(min_length=2, max_length=180)
    description: str | None = Field(default=None, max_length=4000)
    organization_id: str | None = None


class NovaWorkspaceProjectUpdate(BaseModel):
    title: str | None = Field(default=None, min_length=2, max_length=180)
    description: str | None = Field(default=None, max_length=4000)
    status: Literal["active", "paused"] | None = None
    organization_id: str | None = None


class NovaWorkspaceProjectOut(BaseModel):
    workspace_id: str
    organization_id: str
    owner_user_id: str
    title: str
    description: str | None
    status: str
    archived: bool
    created_at: datetime
    updated_at: datetime
    last_opened_at: datetime | None


class NovaWorkspaceFileCreate(BaseModel):
    filename: str = Field(min_length=1, max_length=260)
    content_type: str | None = Field(default=None, max_length=120)
    size_bytes: int | None = Field(default=None, ge=0)
    excerpt: str | None = Field(default=None, max_length=4000)
    workspace_id: str | None = None
    upload_id: str | None = Field(default=None, max_length=64)
    organization_id: str | None = None


class NovaWorkspaceFileOut(BaseModel):
    file_id: str
    workspace_id: str | None
    organization_id: str
    owner_user_id: str
    filename: str
    content_type: str | None
    size_bytes: int | None
    created_at: datetime
    last_accessed_at: datetime | None


class NovaWorkspaceConversationCreate(BaseModel):
    title: str | None = Field(default=None, max_length=180)
    workspace_id: str | None = None
    source: Literal["nova_ask", "assistant_history"] = "nova_ask"
    organization_id: str | None = None


class NovaWorkspaceConversationUpdate(BaseModel):
    title: str | None = Field(default=None, min_length=1, max_length=180)
    workspace_id: str | None = None
    organization_id: str | None = None


class NovaWorkspaceMessageOut(BaseModel):
    message_id: str
    conversation_id: str
    role: str
    content: str
    created_at: datetime


class NovaWorkspaceConversationOut(BaseModel):
    conversation_id: str
    workspace_id: str | None
    organization_id: str
    owner_user_id: str
    title: str
    source: str
    created_at: datetime
    updated_at: datetime
    last_opened_at: datetime | None
    preview: str | None = None
    messages: list[NovaWorkspaceMessageOut] = Field(default_factory=list)


class NovaWorkspaceSearchHit(BaseModel):
    kind: str
    id: str
    title: str
    snippet: str
    workspace_id: str | None = None


class NovaWorkspaceSearchOut(BaseModel):
    query: str
    result_count: int
    hits: list[NovaWorkspaceSearchHit]


class NovaWorkspaceSearchSavedOut(BaseModel):
    search_id: str
    query: str
    result_count: int
    created_at: datetime


class NovaWorkspaceActivityOut(BaseModel):
    activity_id: str
    kind: str
    title: str
    workspace_id: str | None
    ref_type: str | None
    ref_id: str | None
    created_at: datetime


class NovaWorkspaceDashboardOut(BaseModel):
    recent_work: list[NovaWorkspaceActivityOut]
    recent_conversations: list[NovaWorkspaceConversationOut]
    recent_files: list[NovaWorkspaceFileOut]
    active_projects: list[NovaWorkspaceProjectOut]
    saved_searches: list[NovaWorkspaceSearchSavedOut]
    assistant_history: list[dict[str, Any]] = Field(default_factory=list)


class NovaWorkspaceBrainRequest(BaseModel):
    action: Literal[
        "ask",
        "continue",
        "summarize",
        "find_file",
        "search_prior",
        "explain_changed",
        "next_action",
    ] = "ask"
    question: str | None = Field(default=None, max_length=4000)
    workspace_id: str | None = None
    conversation_id: str | None = None
    organization_id: str | None = None


class NovaWorkspaceBrainOut(BaseModel):
    action: str
    answer: str
    next_actions: list[str] = Field(default_factory=list)
    conversation_id: str | None = None
    search: NovaWorkspaceSearchOut | None = None
    generated_at: str
