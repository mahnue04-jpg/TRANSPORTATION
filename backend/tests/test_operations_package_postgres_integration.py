"""Disposable PostgreSQL staging ledger integration tests.

Uses the GitHub Actions postgres:16 service with synthetic accounts only.
No Stripe credentials, hosted Neon databases, or production data.
"""
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
import os
from pathlib import Path

import pytest
import sqlalchemy as sa
from sqlalchemy.orm import Session

from app.core.nova.work_revenue.operations_package_allowances import VerifiedEntitlement
from app.core.nova.work_revenue.operations_package_usage_ledger import (
    AllowanceBlocked, reservations, reserve_staging_task,
)

NOW = datetime.now(timezone.utc)
URL = os.environ.get("NOVA_OPERATIONS_TEST_POSTGRES_URL", "")


def entitlement(plan, customer):
    return VerifiedEntitlement(
        plan=plan, customer_id=customer, paid=True, status="active",
        subscription_id="sub_synthetic_" + customer,
        period_start=NOW-timedelta(days=1),
        period_end=NOW+timedelta(days=29), payment_id="pi_synthetic_" + customer,
    )


@pytest.fixture(scope="module")
def engine():
    if not URL or "127.0.0.1" not in URL:
        pytest.skip("Only disposable localhost PostgreSQL is supported")
    for key, value in (
        ("APP_ENV", "staging"),
        ("AMICOR_ENVIRONMENT", "staging"),
        ("NOVA_STRIPE_LIVE_ENABLED", "false"),
        ("NOVA_OPERATIONS_CUSTOMER_SALES_ENABLED", "false"),
        ("NOVA_OPERATIONS_PACKAGE_LEDGER_STAGING_ENABLED", "true"),
    ):
        os.environ[key] = value
    engine = sa.create_engine(URL, pool_pre_ping=True)
    migration = Path(__file__).resolve().parents[1] / "migrations" / (
        "review_only_operations_package_task_reservations_staging.sql"
    )
    with engine.connect().execution_options(isolation_level="AUTOCOMMIT") as connection:
        connection.exec_driver_sql(migration.read_text(encoding="utf-8"))
    yield engine
    reservations.drop(engine, checkfirst=True)
    engine.dispose()


def reserve(engine, e, request_key, fingerprint="a"*64):
    with Session(engine) as session:
        return reserve_staging_task(
            session, entitlement=e, customer_id=e.customer_id,
            request_key=request_key, task_fingerprint=fingerprint, now=NOW,
        )


@pytest.mark.parametrize("plan,limit", [
    ("starter_49", 1), ("launch_99", 3), ("business_299", 10),
])
def test_database_enforces_exact_allowance(engine, plan, limit):
    e = entitlement(plan, "cus_limit_" + plan)
    for i in range(limit):
        out = reserve(engine, e, "task-" + str(i))
        assert out["consumed"] and not out["replayed"]
    with pytest.raises(AllowanceBlocked, match="allowance_exhausted"):
        reserve(engine, e, "extra-task")
    with Session(engine) as session:
        count = session.scalar(sa.select(sa.func.count()).select_from(reservations).where(
            reservations.c.customer_id == e.customer_id
        ))
    assert count == limit


def test_identical_retry_is_not_double_counted(engine):
    e = entitlement("launch_99", "cus_repeat")
    first = reserve(engine, e, "same-key")
    second = reserve(engine, e, "same-key")
    assert first["reservation_id"] == second["reservation_id"]
    assert second["replayed"] and not second["consumed"]
    with pytest.raises(AllowanceBlocked, match="request_key_reused_for_different_task"):
        reserve(engine, e, "same-key", "b"*64)


def test_simultaneous_requests_cannot_exceed_limit(engine):
    e = entitlement("starter_49", "cus_concurrent")
    with ThreadPoolExecutor(max_workers=6) as executor:
        futures = [executor.submit(reserve, engine, e, "concurrent-"+str(i)) for i in range(6)]
        outcomes = []
        for f in futures:
            try:
                outcomes.append(f.result())
            except AllowanceBlocked as exc:
                outcomes.append(str(exc))
    assert sum(isinstance(x, dict) and x["consumed"] for x in outcomes) == 1
    assert outcomes.count("allowance_exhausted") == 5
    with Session(engine) as session:
        assert session.scalar(sa.select(sa.func.count()).select_from(reservations).where(
            reservations.c.customer_id == e.customer_id
        )) == 1


def test_one_subscription_period_does_not_consume_next_period(engine):
    first = entitlement("launch_99", "cus_renewal")
    for i in range(3):
        reserve(engine, first, "request-"+str(i))
    second = VerifiedEntitlement(
        plan="launch_99", customer_id=first.customer_id, paid=True, status="active",
        subscription_id=first.subscription_id, period_start=NOW-timedelta(hours=1),
        period_end=NOW+timedelta(days=29), payment_id=first.payment_id,
    )
    assert reserve(engine, second, "new-month")["consumed"]
