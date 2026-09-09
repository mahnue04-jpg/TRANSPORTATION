"""Nova V2 Today action/acknowledgment store. References V1 IDs; does not copy V1 rows."""
from __future__ import annotations

from datetime import datetime

from sqlalchemy import DateTime, Index, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.db.session import Base
from app.helpers import now, uuid4


class NovaV2CommandAction(Base):
    __tablename__ = "nova_v2_command_actions"
    __table_args__ = (
        Index("ix_nova_v2_action_id", "action_id", unique=True),
        Index("ix_nova_v2_action_org_owner", "organization_id", "owner_user_id", "status"),
        Index(
            "ix_nova_v2_action_source",
            "organization_id",
            "owner_user_id",
            "source_module",
            "source_ref_id",
            "recommended_action",
            unique=True,
        ),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uuid4)
    action_id: Mapped[str] = mapped_column(String(32), nullable=False, unique=True)
    organization_id: Mapped[str] = mapped_column(String(36), nullable=False)
    owner_user_id: Mapped[str] = mapped_column(String(36), nullable=False)
    source_module: Mapped[str] = mapped_column(String(40), nullable=False)
    source_ref_id: Mapped[str] = mapped_column(String(80), nullable=False)
    title: Mapped[str] = mapped_column(String(240), nullable=False)
    detail: Mapped[str | None] = mapped_column(Text, nullable=True)
    href: Mapped[str | None] = mapped_column(String(400), nullable=True)
    trust_label: Mapped[str] = mapped_column(String(48), nullable=False)
    priority: Mapped[int] = mapped_column(Integer, nullable=False, default=50)
    status: Mapped[str] = mapped_column(String(24), nullable=False, default="proposed")
    recommended_action: Mapped[str] = mapped_column(String(32), nullable=False)
    result_ref_id: Mapped[str | None] = mapped_column(String(80), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now, nullable=False)
    decided_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
