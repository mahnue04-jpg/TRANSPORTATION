"""Autonomy Phase 1 SQLAlchemy + API models. Append-only ledger; no secrets."""
from __future__ import annotations

from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, Field
from sqlalchemy import Boolean, DateTime, Index, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.db.session import Base
from app.helpers import now, uuid4


class NovaAutonomyLedger(Base):
    """Append-only autonomy audit row. Never stores secrets, tokens, or message bodies."""

    __tablename__ = "nova_autonomy_ledger"
    __table_args__ = (
        Index("ix_nova_autonomy_audit_id", "audit_id"),
        Index("ix_nova_autonomy_correlation", "organization_id", "correlation_id"),
        Index("ix_nova_autonomy_idempotency", "organization_id", "idempotency_key"),
        Index("ix_nova_autonomy_org_created", "organization_id", "created_at"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uuid4)
    audit_id: Mapped[str] = mapped_column(String(40), nullable=False)
    correlation_id: Mapped[str] = mapped_column(String(80), nullable=False)
    idempotency_key: Mapped[str | None] = mapped_column(String(80), nullable=True)
    actor_user_id: Mapped[str] = mapped_column(String(36), nullable=False)
    actor_role: Mapped[str] = mapped_column(String(40), nullable=False)
    organization_id: Mapped[str] = mapped_column(String(36), nullable=False)
    action_type: Mapped[str] = mapped_column(String(64), nullable=False)
    source_module: Mapped[str] = mapped_column(String(40), nullable=False, default="autonomy")
    source_ref_id: Mapped[str] = mapped_column(String(80), nullable=False)
    result_ref_id: Mapped[str | None] = mapped_column(String(80), nullable=True)
    target: Mapped[str | None] = mapped_column(String(240), nullable=True)
    risk_class: Mapped[str] = mapped_column(String(16), nullable=False)
    approval_state: Mapped[str] = mapped_column(String(32), nullable=False)
    executed: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    today_action_id: Mapped[str | None] = mapped_column(String(32), nullable=True)
    result: Mapped[str] = mapped_column(String(240), nullable=False, default="recorded")
    verification_result: Mapped[str | None] = mapped_column(String(40), nullable=True)
    detail: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now, nullable=False)


class AutonomyIntentCreate(BaseModel):
    action_type: str = Field(min_length=2, max_length=64)
    source_module: Literal["workspace", "communications", "government", "business", "link", "autonomy"] = "autonomy"
    source_ref_id: str = Field(min_length=1, max_length=80)
    title: str = Field(default="Autonomy intent", max_length=240)
    organization_id: str | None = None
    correlation_id: str | None = Field(default=None, max_length=80)
    today_action_id: str | None = Field(default=None, max_length=32)
    hours: int | None = None
    draft_to: list[str] = Field(default_factory=list)
    draft_subject: str | None = Field(default=None, max_length=512)
    task_title: str | None = Field(default=None, max_length=220)
    confidence: float | None = None
    recommendation_strength: float | None = None


class AutonomyApproveRequest(BaseModel):
    organization_id: str | None = None
    hours: int | None = None
    draft_to: list[str] = Field(default_factory=list)
    draft_subject: str | None = Field(default=None, max_length=512)
    task_title: str | None = Field(default=None, max_length=220)


class AutonomyIntentOut(BaseModel):
    audit_id: str
    correlation_id: str
    action_type: str
    source_module: str
    source_ref_id: str
    target: str | None = None
    result_ref_id: str | None = None
    today_action_id: str | None = None
    risk_class: str
    approval_state: str
    executed: bool
    actor_user_id: str
    actor_role: str
    organization_id: str
    timestamp: datetime
    result: str
    verification_result: str | None = None
    href: str | None = None
    mutated_external: bool = False

    @classmethod
    def from_row(cls, row: NovaAutonomyLedger, **extra: Any) -> "AutonomyIntentOut":
        return cls(
            audit_id=row.audit_id,
            correlation_id=row.correlation_id,
            action_type=row.action_type,
            source_module=row.source_module,
            source_ref_id=row.source_ref_id,
            target=row.target,
            result_ref_id=row.result_ref_id,
            today_action_id=row.today_action_id,
            risk_class=row.risk_class,
            approval_state=row.approval_state,
            executed=bool(row.executed),
            actor_user_id=row.actor_user_id,
            actor_role=row.actor_role,
            organization_id=row.organization_id,
            timestamp=row.created_at,
            result=row.result,
            verification_result=row.verification_result,
            href=extra.get("href"),
            mutated_external=bool(extra.get("mutated_external", False)),
        )
