from __future__ import annotations

from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, Field


class NovaCommsMessageCreate(BaseModel):
    sender: str = Field(min_length=1, max_length=320)
    subject: str = Field(min_length=1, max_length=512)
    body: str = Field(default="", max_length=20000)
    important: bool = False
    organization_id: str | None = None


class NovaCommsMessageUpdate(BaseModel):
    read: bool | None = None
    important: bool | None = None
    organization_id: str | None = None


class NovaCommsMessageOut(BaseModel):
    message_id: str
    sender: str
    subject: str
    snippet: str | None
    body: str | None = None
    read: bool
    important: bool
    source: str
    created_at: datetime


class NovaCommsDraftCreate(BaseModel):
    to: list[str] = Field(default_factory=list)
    cc: list[str] = Field(default_factory=list)
    bcc: list[str] = Field(default_factory=list)
    subject: str = Field(min_length=1, max_length=512)
    body: str = Field(default="", max_length=20000)
    in_reply_to: str | None = None
    organization_id: str | None = None


class NovaCommsDraftOut(BaseModel):
    draft_id: str
    to: list[str]
    cc: list[str]
    bcc: list[str]
    subject: str
    body: str
    status: str
    updated_at: datetime


class NovaCommsSendRequest(BaseModel):
    draft_id: str | None = None
    confirm_send: bool = False
    to: list[str] = Field(default_factory=list)
    subject: str | None = None
    body: str | None = None
    organization_id: str | None = None


class NovaCommsEventCreate(BaseModel):
    title: str = Field(min_length=1, max_length=512)
    description: str | None = Field(default=None, max_length=4000)
    start_time: str
    end_time: str
    timezone: str = "UTC"
    location: str | None = Field(default=None, max_length=400)
    attendees: list[str] = Field(default_factory=list)
    organization_id: str | None = None


class NovaCommsEventOut(BaseModel):
    event_id: str
    title: str
    description: str | None
    start_time: datetime
    end_time: datetime
    timezone: str
    location: str | None = None
    attendees: list[str]
    status: str
    provider: str


class NovaCommsContactOut(BaseModel):
    name: str
    email: str | None = None
    organization: str | None = None
    phone: str | None = None
    recent_interaction: str | None = None


class NovaCommsNotificationOut(BaseModel):
    notification_id: str
    kind: str
    title: str
    detail: str | None
    link: str | None
    read: bool
    created_at: datetime


class NovaCommsDashboardOut(BaseModel):
    inbox: list[NovaCommsMessageOut]
    important: list[NovaCommsMessageOut]
    drafts: list[NovaCommsDraftOut]
    today: list[NovaCommsEventOut]
    upcoming: list[NovaCommsEventOut]
    contacts: list[NovaCommsContactOut]
    notifications: list[NovaCommsNotificationOut]
    recent: list[dict[str, Any]]
    email_connected: bool
    calendar_connected: bool
    send_enabled: bool


class NovaCommsBrainRequest(BaseModel):
    action: Literal[
        "summarize_recent",
        "needs_attention",
        "draft_reply",
        "summarize_thread",
        "meeting_notes",
        "summarize_calendar",
        "follow_up",
        "locate_contact",
        "explain_notification",
        "ask",
    ] = "ask"
    question: str | None = Field(default=None, max_length=4000)
    message_id: str | None = None
    notification_id: str | None = None
    organization_id: str | None = None


class NovaCommsBrainOut(BaseModel):
    action: str
    answer: str
    draft: NovaCommsDraftOut | None = None
    next_actions: list[str] = Field(default_factory=list)
    generated_at: str
