"""Fail-closed checks for the optional Growth campaign-review Alembic revision.

Uses an in-memory disposable SQLite schema for reflection only; no Render connection.
"""
from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest
import sqlalchemy as sa


def _revision():
    path = (
        Path(__file__).resolve().parents[1]
        / "migrations" / "versions" / "20261118_nova_ga_campaign_review.py"
    )
    spec = importlib.util.spec_from_file_location("growth_review_schema_guard", path)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


def _schema(*, index=True, unique=True, omit_column=False):
    engine = sa.create_engine("sqlite:///:memory:")
    meta = sa.MetaData()
    cols = [
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("organization_id", sa.String(36), nullable=False),
        sa.Column("owner_user_id", sa.String(36), nullable=False),
        sa.Column("campaign_id", sa.String(128), nullable=False),
        sa.Column("studio_project_id", sa.String(128), nullable=False),
        sa.Column("asset_id", sa.String(128), nullable=False),
        sa.Column("status", sa.String(32), nullable=False),
        sa.Column("created_at", sa.String(48), nullable=False),
        sa.Column("updated_at", sa.String(48), nullable=False),
    ]
    if omit_column:
        cols = [c for c in cols if c.name != "asset_id"]
    if unique:
        cols.append(
            sa.UniqueConstraint(
                "organization_id", "campaign_id",
                name="uq_nova_ga_campaign_org_ref",
            )
        )
    table = sa.Table("nova_ga_campaign_asset_reviews", meta, *cols)
    if index:
        sa.Index(
            "ix_nova_ga_campaign_owner",
            table.c.organization_id, table.c.owner_user_id, table.c.created_at,
        )
    meta.create_all(engine)
    return engine


def test_existing_complete_schema_is_accepted():
    engine = _schema()
    try:
        _revision()._verify_existing_table(sa.inspect(engine))
    finally:
        engine.dispose()


@pytest.mark.parametrize(
    "broken", [
        {"index": False},
        {"unique": False},
        {"omit_column": True},
    ],
)
def test_partial_schema_fails_closed(broken):
    engine = _schema(**broken)
    try:
        with pytest.raises(RuntimeError, match="Campaign review"):
            _revision()._verify_existing_table(sa.inspect(engine))
    finally:
        engine.dispose()


def test_existing_schema_never_auto_repairs_missing_index(monkeypatch):
    engine = _schema(index=False)
    try:
        from alembic.migration import MigrationContext
        from alembic.operations import Operations

        with engine.begin() as conn:
            revision = _revision()
            revision.op = Operations(MigrationContext.configure(conn))
            with pytest.raises(RuntimeError, match="owner index"):
                revision.upgrade()
        assert all(
            entry["name"] != "ix_nova_ga_campaign_owner"
            for entry in sa.inspect(engine).get_indexes("nova_ga_campaign_asset_reviews")
        )
    finally:
        engine.dispose()
