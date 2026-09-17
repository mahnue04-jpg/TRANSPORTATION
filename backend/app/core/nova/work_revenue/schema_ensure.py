"""Create isolated Work & Revenue tables locally. Does not alter payment or Lifesaver tables."""
from __future__ import annotations

from sqlalchemy.engine import Engine

from app.core.nova.work_revenue.models import (
    NovaWorkApplication,
    NovaWorkAuditEvent,
    NovaWorkMaterial,
    NovaWorkOpportunity,
    NovaWorkOwnerAction,
    NovaWorkStatusHistory,
)
from app.db.session import Base, engine as default_engine

WORK_TABLES = (
    NovaWorkOpportunity.__table__,
    NovaWorkApplication.__table__,
    NovaWorkMaterial.__table__,
    NovaWorkOwnerAction.__table__,
    NovaWorkStatusHistory.__table__,
    NovaWorkAuditEvent.__table__,
)


def ensure_work_revenue_schema(engine: Engine | None = None) -> None:
    bind = engine or default_engine
    Base.metadata.create_all(bind=bind, tables=list(WORK_TABLES))
