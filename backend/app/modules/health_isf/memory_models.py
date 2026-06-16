"""Typed contracts for append-only operational memory events."""

from __future__ import annotations

from pydantic import BaseModel, Field


class OperationalMemoryEvent(BaseModel):
    event_id: str
    organization_id: str
    stream: str
    event_type: str
    tenant_scope: str
    role_scope: list[str] = Field(default_factory=list)
    payload: dict
    replay_key: str
    immutable: bool = True
    recorded_at: str
    actor_user_id: str | None = None


class OperationalMemoryPage(BaseModel):
    organization_id: str
    stream: str
    count: int
    events: list[OperationalMemoryEvent]
