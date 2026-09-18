"""Canonical V3 persistence on the shared SQLAlchemy engine/session.

Replaces Grok's isolated sqlite-only V3Store. Production tables come from Alembic.
This module never binds to Stripe and never writes nova_work_revenue_entries.
"""
from __future__ import annotations

import json
from dataclasses import asdict, is_dataclass
from datetime import datetime
from typing import Any

from sqlalchemy import create_engine, select
from sqlalchemy.engine import Engine
from sqlalchemy.orm import sessionmaker

from app.core.nova.v3.db_models import APPEND_ONLY_TABLES, V3_MODEL_BY_TABLE, V3_TABLES
from app.core.nova.v3.errors import V3Error
from app.core.nova.v3.schema import assert_store_url, ensure_v3_schema
from app.helpers import uuid4


def _json(value: Any) -> str:
    def _default(item: Any) -> Any:
        if isinstance(item, datetime):
            return item.isoformat()
        if is_dataclass(item):
            return asdict(item)
        return str(item)

    return json.dumps(value, default=_default, sort_keys=True)


def _lookup_filters(model, key_cols: dict[str, Any]) -> dict[str, Any]:
    return {name: key_cols[name] for name in key_cols if hasattr(model, name)}


class V3Store:
    def __init__(self, url: str | None = None, *, engine: Engine | None = None) -> None:
        if engine is not None:
            self.engine = engine
        else:
            token = assert_store_url(url or "sqlite:///:memory:")
            self.engine = create_engine(token, future=True)
        ensure_v3_schema(self.engine)
        self._session_factory = sessionmaker(bind=self.engine, future=True)
        self.fail_next_write = False

    def session(self) -> Session:
        return self._session_factory()

    def upsert(self, table: str, key_cols: dict[str, Any], payload: Any) -> None:
        if table not in V3_TABLES:
            raise V3Error("PERSISTENCE_REFUSED", f"unknown V3 table {table}")
        if self.fail_next_write:
            self.fail_next_write = False
            raise RuntimeError("injected database write failure")
        model = V3_MODEL_BY_TABLE[table]
        columns = dict(key_cols)
        columns["payload_json"] = _json(payload)
        with self.session() as db:
            if table in APPEND_ONLY_TABLES:
                row = model(**{name: columns[name] for name in columns if hasattr(model, name)})
                if hasattr(row, "id") and not getattr(row, "id", None):
                    row.id = uuid4()
                db.add(row)
                db.commit()
                return
            filters = _lookup_filters(model, key_cols)
            existing = db.execute(select(model).filter_by(**filters)).scalars().first()
            if existing is None:
                init = {name: columns[name] for name in columns if hasattr(model, name)}
                if "id" not in init:
                    init["id"] = uuid4()
                db.add(model(**init))
            else:
                existing.payload_json = columns["payload_json"]
                for name, value in columns.items():
                    if name in {"id", "payload_json"}:
                        continue
                    if hasattr(existing, name):
                        setattr(existing, name, value)
            db.commit()

    def fetch(self, table: str, *, organization_id: str, owner_user_id: str | None = None) -> list[dict[str, Any]]:
        if table not in V3_TABLES:
            raise V3Error("PERSISTENCE_REFUSED", f"unknown V3 table {table}")
        model = V3_MODEL_BY_TABLE[table]
        with self.session() as db:
            query = select(model).where(model.organization_id == organization_id)
            if owner_user_id is not None and hasattr(model, "owner_user_id"):
                query = query.where(model.owner_user_id == owner_user_id)
            rows = db.execute(query).scalars().all()
        out: list[dict[str, Any]] = []
        for row in rows:
            parsed = json.loads(row.payload_json)
            if isinstance(parsed, dict):
                out.append(parsed)
            else:
                out.append({"payload": parsed})
        return out

    def count(self, table: str) -> int:
        if table not in V3_TABLES:
            raise V3Error("PERSISTENCE_REFUSED", f"unknown V3 table {table}")
        model = V3_MODEL_BY_TABLE[table]
        with self.session() as db:
            return int(db.query(model).count())


def bind_app_engine() -> V3Store:
    from app.db.session import engine as app_engine

    return V3Store(engine=app_engine)
