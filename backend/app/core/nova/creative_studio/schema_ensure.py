"""Additive Creative Studio tables. Does not alter Work/Health/Delivery/Freight/Stripe tables."""

from __future__ import annotations

from sqlalchemy import inspect, text
from sqlalchemy.engine import Engine

from app.core.nova.creative_studio.db_models import (
    NovaCreativeAsset,
    NovaCreativeCalendarEntry,
    NovaCreativeBrand,
    NovaCreativeBrief,
    NovaCreativeJob,
    NovaCreativeRenderClaim,
    NovaCreativeAiRequestSlot,
    NovaCreativeOrder,
    NovaCreativeProject,
    NovaCreativeScene,
    NovaCreativeWebhookEvent,
)
from app.db.session import Base, engine as default_engine

CREATIVE_TABLES = (
    NovaCreativeBrand.__table__,
    NovaCreativeCalendarEntry.__table__,
    NovaCreativeBrief.__table__,
    NovaCreativeProject.__table__,
    NovaCreativeAsset.__table__,
    NovaCreativeScene.__table__,
    NovaCreativeJob.__table__,
    NovaCreativeRenderClaim.__table__,
    NovaCreativeAiRequestSlot.__table__,
    NovaCreativeOrder.__table__,
    NovaCreativeWebhookEvent.__table__,
)


def ensure_nova_creative_schema(engine: Engine | None = None) -> None:
    eng = engine or default_engine
    Base.metadata.create_all(bind=eng, tables=list(CREATIVE_TABLES))
    # Defensive: confirm expected tables exist without touching unrelated schemas.
    # Existing installations already have this table. CREATE TABLE does not add
    # newly introduced columns, so migrate it additively without data loss.
    inspector = inspect(eng)
    if "nova_creative_calendar_entries" in inspector.get_table_names():
        existing = {column["name"] for column in inspector.get_columns("nova_creative_calendar_entries")}
        if "duration_seconds" not in existing:
            with eng.begin() as conn:
                conn.execute(text(
                    "ALTER TABLE nova_creative_calendar_entries "
                    "ADD COLUMN duration_seconds INTEGER NOT NULL DEFAULT 30"
                ))
        if "timeline_json" not in existing:
            with eng.begin() as conn:
                conn.execute(text(
                    "ALTER TABLE nova_creative_calendar_entries "
                    "ADD COLUMN timeline_json TEXT NOT NULL DEFAULT '[]'"
                ))
        if "chapters_json" not in existing:
            with eng.begin() as conn:
                conn.execute(text(
                    "ALTER TABLE nova_creative_calendar_entries "
                    "ADD COLUMN chapters_json TEXT NOT NULL DEFAULT '[]'"
                ))
        if "storyboard_json" not in existing:
            with eng.begin() as conn:
                conn.execute(text(
                    "ALTER TABLE nova_creative_calendar_entries "
                    "ADD COLUMN storyboard_json TEXT NOT NULL DEFAULT '[]'"
                ))
        if "narrator_voice" not in existing:
            with eng.begin() as conn:
                conn.execute(text(
                    "ALTER TABLE nova_creative_calendar_entries "
                    "ADD COLUMN narrator_voice VARCHAR(16) NOT NULL DEFAULT 'en-us'"
                ))
        if "narrator_speed" not in existing:
            with eng.begin() as conn:
                conn.execute(text(
                    "ALTER TABLE nova_creative_calendar_entries "
                    "ADD COLUMN narrator_speed INTEGER NOT NULL DEFAULT 148"
                ))
    if "nova_creative_render_claims" in inspector.get_table_names():
        claim_columns = {col["name"] for col in inspector.get_columns("nova_creative_render_claims")}
        if "checkpoint_json" not in claim_columns:
            with eng.begin() as conn:
                conn.execute(text(
                    "ALTER TABLE nova_creative_render_claims "
                    "ADD COLUMN checkpoint_json TEXT NOT NULL DEFAULT '{}'"
                ))
    # Additive budget-ledger fields for already-created Studio AI request slots.
    inspector = inspect(eng)
    if "nova_creative_ai_request_slots" in inspector.get_table_names():
        existing_slots = {
            column["name"] for column in inspector.get_columns("nova_creative_ai_request_slots")
        }
        additions = (
            ("reserved_micro_usd", "INTEGER NOT NULL DEFAULT 0"),
            ("estimated_micro_usd", "INTEGER"),
            ("input_tokens", "INTEGER"),
            ("output_tokens", "INTEGER"),
            ("charge_status", "VARCHAR(36) NOT NULL DEFAULT 'reserved_unverified'"),
            ("updated_at", "VARCHAR(40) NOT NULL DEFAULT ''"),
        )
        with eng.begin() as conn:
            for column, sql_type in additions:
                if column not in existing_slots:
                    conn.execute(text(
                        f"ALTER TABLE nova_creative_ai_request_slots ADD COLUMN {column} {sql_type}"
                    ))
    inspector = inspect(eng)
    names = set(inspector.get_table_names())
    missing = [table.name for table in CREATIVE_TABLES if table.name not in names]
    if missing:
        raise RuntimeError(f"Creative Studio schema ensure failed; missing tables: {missing}")
