from __future__ import annotations

import asyncio
import os
import inspect
import sys
from pathlib import Path

os.environ.setdefault("TESTING", "true")

# Keep tests isolated from the live runtime DB to avoid sqlite lock contention.
if os.environ.get("TESTING", "").lower() == "true":
    test_db_name = f"chat_test_{os.getpid()}.db"
    test_db_path = Path(__file__).resolve().parents[1] / "data" / test_db_name
    os.environ["DB_FILENAME"] = str(test_db_path)
    os.environ["DATABASE_URL"] = f"sqlite:///{test_db_path}"

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


@pytest.fixture(autouse=True)
def _reset_health_isf_driver_state_before_test(request):
    from tests.health_isf_driver_test_helpers import (
        driver_test_module_names,
        organization_id_for_dispatcher,
        reset_organization_driver_test_state,
        reset_scheduling_test_organization,
    )

    module_name = request.node.fspath.basename
    if module_name not in driver_test_module_names():
        return
    from app.auth import ensure_auth_schema, seed_default_users

    ensure_auth_schema()
    seed_default_users()
    if module_name in {
        "test_scheduled_route_activation.py",
        "test_multi_ride_driver_scheduling.py",
        "test_advance_scheduling.py",
    }:
        from app.db.models import User as PlatformUser
        from app.db.session import SessionLocal

        with SessionLocal() as db:
            user = db.query(PlatformUser).filter(PlatformUser.email == "rider@amicor.local").first()
            assert user is not None and user.organization_id is not None
            rider_org_id = str(user.organization_id)
        reset_scheduling_test_organization(rider_org_id)
    else:
        reset_organization_driver_test_state(organization_id_for_dispatcher())


def pytest_pyfunc_call(pyfuncitem): # type: ignore
    test_func = pyfuncitem.obj # type: ignore
    if inspect.iscoroutinefunction(test_func): # type: ignore
        kwargs = {name: pyfuncitem.funcargs[name] for name in pyfuncitem._fixtureinfo.argnames} # type: ignore
        asyncio.run(test_func(**kwargs)) # type: ignore
        return True
    return None
