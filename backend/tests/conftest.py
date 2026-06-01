from __future__ import annotations

import asyncio
import os
import inspect
import sys
from pathlib import Path

os.environ.setdefault("TESTING", "true")

_REPO_ROOT = Path(__file__).resolve().parents[2]
_BACKEND_DIR = _REPO_ROOT / "backend"
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))
if str(_BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(_BACKEND_DIR))

import pytest
from sqlalchemy import Column, String, Table, create_engine
from sqlalchemy.orm import sessionmaker

from app.db.session import Base


def _ensure_fk_stub_tables() -> None:
    if "platform_users" not in Base.metadata.tables:
        Table(
            "platform_users",
            Base.metadata,
            Column("id", String(36), primary_key=True),
            extend_existing=True,
        )


@pytest.fixture
def db():

    engine = create_engine("sqlite:///:memory:")
    TestingSessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
    _ensure_fk_stub_tables()
    Base.metadata.create_all(bind=engine)
    session = TestingSessionLocal()
    try:
        yield session
    finally:
        session.close()


def pytest_pyfunc_call(pyfuncitem): # type: ignore
    test_func = pyfuncitem.obj # type: ignore
    if inspect.iscoroutinefunction(test_func): # type: ignore
        kwargs = {name: pyfuncitem.funcargs[name] for name in pyfuncitem._fixtureinfo.argnames} # type: ignore
        asyncio.run(test_func(**kwargs)) # type: ignore
        return True
    return None
