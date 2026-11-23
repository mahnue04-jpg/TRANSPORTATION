"""Run the hosted Operations approval rehearsal against an empty staging DB."""

import hashlib
import os
from contextlib import asynccontextmanager
from datetime import datetime, timedelta, timezone
from pathlib import Path
from secrets import token_urlsafe
from types import SimpleNamespace

from fastapi import FastAPI
from fastapi.concurrency import run_in_threadpool
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, func, inspect, select, text
from sqlalchemy.engine import make_url

DATABASE_NAME = "nova_ops_approval_rehearsal_583"
REPORT_TABLE = "nova_ops_approval_rehearsal_result"
SOURCE = os.environ.get("RENDER_GIT_COMMIT", "local")
LIMITS = {"launch_99": 3, "business_299": 10}


def check(condition, description):
    if not condition:
        raise RuntimeError(description)


def subscription_fixture(plan, lead_id):
    subscription_id = f"sub_synthetic_{plan}"
    customer_id = f"cus_synthetic_{plan}"
    now = datetime.now(timezone.utc)
    start = int((now - timedelta(days=1)).timestamp())
    end = int((now + timedelta(days=29)).timestamp())
    return {
        "id": subscription_id, "customer": customer_id, "livemode": False, "status": "active",
        "metadata": {
            "nova_product": "nova_anonymous_operations_agent",
            "nova_agent_plan": plan, "nova_agent_lead_id": lead_id,
        },
        "items": {"data": [{
            "quantity": 1, "price": "price_synthetic",
            "current_period_start": start, "current_period_end": end,
        }]},
        "latest_invoice": {
            "livemode": False, "status": "paid", "currency": "usd", "customer": customer_id,
            "amount_paid": {"launch_99": 9900, "business_299": 29900}[plan],
            "parent": {"type": "subscription_details", "subscription_details": {"subscription": subscription_id}},
            "lines": {"data": [{
                "parent": {"type": "subscription_item_details", "subscription_item_details": {
                    "subscription": subscription_id, "proration": False,
                }},
                "period": {"start": start, "end": end},
            }]},
        },
    }


def verify_plan(client, headers, db_session, engagement_model, task_model, lead_model, plan, limit):
    lead_id = f"lead_synthetic_{plan}"
    with db_session.begin() as db:
        db.add(lead_model(
            id=lead_id, lead_type="anonymous_operations", contact_name="Synthetic",
            work_email=f"{plan}@example.invalid", service_plan=plan, payment_status="paid",
            stripe_customer_id=f"cus_synthetic_{plan}", stripe_subscription_id=f"sub_synthetic_{plan}",
        ))
        db.add(engagement_model(
            engagement_id=plan, organization_id="org-synthetic", owner_user_id="owner-synthetic",
            client_name="Synthetic rehearsal", service="CSV",
        ))
        for index in range(limit + 1):
            db.add(task_model(
                task_id=f"{plan}-{index}", engagement_id=plan, organization_id="org-synthetic",
                owner_user_id="owner-synthetic", title="Synthetic CSV scope", review_required=True,
            ))
    base = "/api/nova/work/operations/subscription-approvals"
    for index in range(limit + 1):
        task_id = f"{plan}-{index}"
        scope = {
            "engagement_id": plan, "task_id": task_id, "lead_id": lead_id,
            "task_fingerprint": hashlib.sha256(task_id.encode()).hexdigest(),
        }
        request = {**scope, "request_key": task_id}
        check(client.post(f"{base}/reserve", json=request).status_code == 401, "signed out reservation")
        check(client.post(f"{base}/reserve", headers=headers, json=request).status_code == 409, "missing approval")
        decision = client.post(f"{base}/decision", headers=headers, json={**scope, "decision": "APPROVED"})
        check(decision.status_code == 200, "owner approval")
        response = client.post(f"{base}/reserve", headers=headers, json=request)
        if index == limit:
            check(response.status_code == 409, "package allowance")
            return
        check(response.status_code == 200, "owner reservation")
        first = response.json()
        check(first["consumed"] and not first["executed"] and not first["delivered"], "reservation boundary")
        retry = client.post(f"{base}/reserve", headers=headers, json=request)
        check(retry.status_code == 200 and retry.json() == {
            "reservation_id": first["reservation_id"], "consumed": False,
            "replayed": True, "executed": False, "delivered": False,
        }, "reservation retry")
        revoked = client.post(f"{base}/decision", headers=headers, json={**scope, "decision": "REVOKED"})
        check(revoked.status_code == 200, "owner revocation")
        check(client.post(f"{base}/reserve", headers=headers, json=request).status_code == 409, "revoked approval")


def run_workflow(connection):
    # This process only runs synthetic tests. It never calls Stripe or starts the main app's lifespan.
    os.environ["STRIPE_SECRET_KEY"] = "sk_test_synthetic_placeholder"
    owner_email = "owner@example.invalid"
    os.environ["NOVA_V3_OWNER_EMAILS"] = owner_email
    for plan in ("LAUNCH", "BUSINESS"):
        os.environ[f"NOVA_OPERATIONS_{plan}_TEST_PRICE_ID"] = "price_synthetic"

    from app.auth import hash_password
    from app.core.nova.work_revenue.models import NovaWorkEngagement, NovaWorkTask
    from app.core.nova.work_revenue.operations_package_usage_ledger import reservations
    from app.core.nova.work_revenue.operations_subscription_approvals import approval_events
    from app.db.models import RefreshToken, User
    from app.db.session import SessionLocal, engine
    from app.main import app as amicor_app
    from app.modules.marketing.models import MarketingWebsiteLead
    from app.modules.marketing.operations_billing import set_agent_stripe_override

    for model in (User, RefreshToken, NovaWorkEngagement, NovaWorkTask, MarketingWebsiteLead):
        model.__table__.create(engine, checkfirst=True)
    migration_dir = Path(__file__).resolve().parent / "migrations"
    for filename in (
        "review_only_operations_package_task_reservations_staging.sql",
        "review_only_operations_subscription_scope_approvals_staging.sql",
    ):
        connection.exec_driver_sql((migration_dir / filename).read_text(encoding="utf-8"))

    password = token_urlsafe()
    with SessionLocal.begin() as db:
        db.add(User(
            id="owner-synthetic", email=owner_email, hashed_password=hash_password(password),
            role="admin", session_role="admin", organization_id="org-synthetic",
            is_active=True, is_verified=True,
        ))
    client = TestClient(amicor_app, base_url="https://synthetic.invalid")
    response = client.post("/api/auth/login", json={"email": owner_email, "password": password})
    check(response.status_code == 200, "actual application login")
    headers = {"Authorization": f"Bearer {response.json()['access_token']}"}
    fixtures = {f"sub_synthetic_{plan}": subscription_fixture(plan, f"lead_synthetic_{plan}") for plan in LIMITS}
    set_agent_stripe_override(SimpleNamespace(retrieve_subscription=fixtures.__getitem__))
    try:
        for plan, limit in LIMITS.items():
            verify_plan(client, headers, SessionLocal, NovaWorkEngagement, NovaWorkTask, MarketingWebsiteLead, plan, limit)
            with SessionLocal() as db:
                check(db.scalar(select(func.count()).select_from(reservations).where(
                    reservations.c.plan == plan,
                )) == limit, "durable reservation count")
                check(db.scalar(select(func.count()).select_from(approval_events).where(
                    approval_events.c.engagement_id == plan,
                )) == 2 * limit + 1, "durable approval audit count")
    finally:
        set_agent_stripe_override(None)
        client.close()


def rehearse():
    check(os.getenv("APP_ENV") == os.getenv("AMICOR_ENVIRONMENT") == "staging", "staging required")
    for flag in ("NOVA_STRIPE_LIVE_ENABLED", "NOVA_OPERATIONS_CUSTOMER_SALES_ENABLED"):
        check(os.getenv(flag) == "false", "live billing and customer sales must be off")
    check(not os.getenv("STRIPE_SECRET_KEY"), "Stripe credentials must be absent")
    target = make_url(os.environ["DATABASE_URL"])
    check(target.get_backend_name() == "postgresql" and target.database == DATABASE_NAME, "database target mismatch")
    check(bool(os.environ.get("JWT_SECRET")), "rehearsal signing secret missing")
    engine = create_engine(target.set(drivername="postgresql+psycopg2"), isolation_level="AUTOCOMMIT")
    try:
        with engine.connect() as connection:
            check(connection.scalar(text("SELECT current_database()")) == DATABASE_NAME, "server database mismatch")
            connection.execute(text("SELECT pg_advisory_lock(583)"))
            tables = inspect(connection).get_table_names(schema="public")
            if REPORT_TABLE in tables:
                commit = connection.scalar(text(f"SELECT source_commit FROM {REPORT_TABLE}"))
                check(commit == SOURCE, "database was used with a different deployment commit")
                return
            check(not tables, "empty rehearsal database required")
            try:
                run_workflow(connection)
            finally:
                os.environ.pop("STRIPE_SECRET_KEY", None)
            connection.execute(text(f"CREATE TABLE {REPORT_TABLE} (source_commit TEXT PRIMARY KEY)"))
            connection.execute(text(f"INSERT INTO {REPORT_TABLE} VALUES (:source)"), {"source": SOURCE})
    finally:
        engine.dispose()


@asynccontextmanager
async def lifespan(_app):
    await run_in_threadpool(rehearse)
    yield


app = FastAPI(lifespan=lifespan, docs_url=None, redoc_url=None, openapi_url=None)


@app.get("/health")
def health():
    return {
        "status": "passed",
        "source_commit": SOURCE,
        "database_migrations": "passed",
        "owner_login_and_approval": "passed",
        "verified_reservations": LIMITS,
        "stripe_mode": "synthetic_fixture",
    }
