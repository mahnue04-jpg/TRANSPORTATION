"""Additive Creative Studio tables. Does not alter Work/Health/Delivery/Freight/Stripe tables."""

from __future__ import annotations

from sqlalchemy import inspect
from sqlalchemy.engine import Engine

from app.core.nova.creative_studio.db_models import (
    NovaCreativeAsset,
    NovaCreativeBrand,
    NovaCreativeBrief,
    NovaCreativeJob,
    NovaCreativeProject,
    NovaCreativeScene,
)
from app.db.session import Base, engine as default_engine

CREATIVE_TABLES = (
    NovaCreativeBrand.__table__,
    NovaCreativeBrief.__table__,
    NovaCreativeProject.__table__,
    NovaCreativeAsset.__table__,
    NovaCreativeScene.__table__,
    NovaCreativeJob.__table__,
)


def ensure_nova_creative_schema(engine: Engine | None = None) -> None:
    eng = engine or default_engine
    Base.metadata.create_all(bind=eng, tables=list(CREATIVE_TABLES))
    # Defensive: confirm expected tables exist without touching unrelated schemas.
    inspector = inspect(eng)
    names = set(inspector.get_table_names())
    missing = [table.name for table in CREATIVE_TABLES if table.name not in names]
    if missing:
        raise RuntimeError(f"Creative Studio schema ensure failed; missing tables: {missing}")
