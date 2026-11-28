"""Production startup must not seed or alter the shared Operations database."""

import json

import pytest

from app.deployment.operations_production_startup import (
    operations_production_startup_mode,
    operations_production_startup_report,
)


_SECRET = "synthetic-db-password"
_SHARED_URL = f"postgresql://operations:{_SECRET}@db.internal:5432/amicor"
_OWNER_PASSWORD = "preserve-owner-password"
_CUSTOMER_PASSWORD = "preserve-customer-password"


def test_sqlite_and_other_databases_keep_disposable_startup(monkeypatch):
    monkeypatch.setenv("APP_ENV", "production")
    monkeypatch.setenv("AMICOR_ENVIRONMENT", "production")
    monkeypatch.setenv("DATABASE_URL", "sqlite:///./disposable-startup.db")
    assert operations_production_startup_mode() is False

    monkeypatch.setenv(
        "DATABASE_URL",
        f"postgresql://operations:{_SECRET}@db.internal:5432/synthetic_ops",
    )
    assert operations_production_startup_mode() is False

    monkeypatch.setenv("APP_ENV", "staging")
    monkeypatch.setenv("AMICOR_ENVIRONMENT", "staging")
    monkeypatch.setenv("DATABASE_URL", _SHARED_URL)
    assert operations_production_startup_mode() is False


def test_disposable_sqlite_still_reaches_demo_seed(monkeypatch):
    monkeypatch.setenv("APP_ENV", "development")
    monkeypatch.setenv("AMICOR_ENVIRONMENT", "development")
    monkeypatch.setenv("DATABASE_URL", "sqlite:///./disposable-startup.db")
    called = []

    class Stop(Exception):
        pass

    monkeypatch.setattr("app.auth.ensure_auth_schema", lambda: called.append("auth"))
    monkeypatch.setattr(
        "app.modules.health_isf.models.ensure_health_isf_schema",
        lambda: called.append("health"),
    )
    monkeypatch.setattr("app.db.session.SessionLocal", lambda: (_ for _ in ()).throw(Stop()))

    from app.auth import seed_default_users

    with pytest.raises(Stop):
        seed_default_users()
    assert called == ["auth", "health"]


def test_shared_production_database_preserves_accounts_and_records(monkeypatch):
    from sqlalchemy.orm import Session

    from app.auth import (
        UserContext,
        ensure_auth_schema,
        hash_password,
        seed_default_users,
        verify_password,
    )
    from app.core.nova.work_revenue.operations_authenticated_checkout import public_sales_enabled
    from app.core.nova.work_revenue.operations_customer_fulfillment import customer_fulfillment
    from app.core.nova.work_revenue.operations_private_storage import OperationsPrivateArtifactStorage
    from app.core.nova.work_revenue.owner_auth import require_work_revenue_owner
    from app.core.nova.work_revenue.schema_ensure import ensure_work_revenue_schema
    import app.database as database_module
    from app.database import init_db
    from app.db.models import Conversation, User
    from app.db.session import Base, SessionLocal, engine, init_platform_db
    from app.deployment import background_startup
    from app.modules.approval_engine.models import ensure_approval_engine_schema
    from app.modules.health_isf.models import ensure_driver_mobile_login_schema, ensure_health_isf_schema
    from app.modules.marketing.models import ensure_marketing_schema
    from app.modules.platform_ops.models import ensure_platform_ops_schema
    from app.modules.platform_ops.secure_storage import SecureStorageNotConfigured

    assert engine.dialect.name == "sqlite"
    User.__table__.create(bind=engine, checkfirst=True)
    Conversation.__table__.create(bind=engine, checkfirst=True)

    owner_hash = hash_password(_OWNER_PASSWORD)
    customer_hash = hash_password(_CUSTOMER_PASSWORD)
    with Session(bind=engine) as db:
        owner = db.query(User).filter(User.email == "admin@amicor.local").one_or_none()
        if owner is None:
            owner = User(id="owner-persist", email="admin@amicor.local", hashed_password=owner_hash)
            db.add(owner)
        owner.hashed_password = owner_hash
        owner.role = "admin"
        owner.authorized_roles = "admin,dispatcher"
        owner.session_role = "admin"
        owner.organization_id = "tenant-owner"
        owner.organization_name = "Existing Owner Org"
        owner.is_active = True
        owner.is_verified = True

        customer = db.query(User).filter(User.email == "customer.persist@example.invalid").one_or_none()
        if customer is None:
            customer = User(
                id="customer-persist",
                email="customer.persist@example.invalid",
                hashed_password=customer_hash,
            )
            db.add(customer)
        customer.hashed_password = customer_hash
        customer.role = "customer"
        customer.authorized_roles = "customer"
        customer.session_role = "customer"
        customer.organization_id = "tenant-customer"
        customer.organization_name = "Existing Customer Org"
        customer.is_active = True
        customer.is_verified = True
        db.flush()

        conversation = db.query(Conversation).filter(Conversation.id == "conversation-persist").one_or_none()
        if conversation is None:
            conversation = Conversation(id="conversation-persist", user_id=customer.id, title="keep-this-record")
            db.add(conversation)
        conversation.user_id = customer.id
        conversation.title = "keep-this-record"
        db.commit()
        before_count = db.query(User).count()

    monkeypatch.setenv("APP_ENV", "production")
    monkeypatch.setenv("AMICOR_ENVIRONMENT", "production")
    monkeypatch.setenv("DATABASE_URL", _SHARED_URL)
    monkeypatch.setenv("NOVA_STRIPE_LIVE_ENABLED", "false")
    monkeypatch.setenv("NOVA_OPERATIONS_CUSTOMER_SALES_ENABLED", "false")
    for suffix in ("BUCKET", "REGION", "ACCESS_KEY", "SECRET_KEY", "ENDPOINT"):
        monkeypatch.delenv(f"NOVA_OPERATIONS_PRIVATE_S3_{suffix}", raising=False)

    report = operations_production_startup_report()
    encoded = json.dumps(report)
    assert report == {
        "mode": "preserve_existing_records",
        "database_name": "amicor",
        "seed_demo_accounts": False,
        "schema_mutations": False,
        "preserves_accounts": True,
        "preserves_passwords": True,
        "preserves_roles": True,
        "preserves_permissions": True,
        "preserves_records": True,
        "live_sales_enabled": False,
    }
    assert _SECRET not in encoded
    assert "db.internal" not in encoded
    assert "postgresql://" not in encoded

    def refuse_schema_change(*_args, **_kwargs):
        raise AssertionError("schema change")

    original_create_all = Base.metadata.create_all
    original_begin = engine.begin
    original_status = dict(background_startup._deferred_status)
    original_connect = database_module.sqlite3.connect
    Base.metadata.create_all = refuse_schema_change
    engine.begin = refuse_schema_change
    database_module.sqlite3.connect = refuse_schema_change
    try:
        assert seed_default_users() == []
        ensure_auth_schema()
        init_platform_db()
        init_db()
        ensure_health_isf_schema()
        ensure_driver_mobile_login_schema()
        ensure_marketing_schema()
        ensure_approval_engine_schema()
        ensure_platform_ops_schema()
        ensure_work_revenue_schema()
        background_startup.run_deferred_platform_startup(runtime_environment="production")
        assert background_startup.deferred_startup_status()["skipped"] == "preserve_existing_records"
    finally:
        Base.metadata.create_all = original_create_all
        engine.begin = original_begin
        database_module.sqlite3.connect = original_connect
        background_startup._deferred_status.clear()
        background_startup._deferred_status.update(original_status)

    with SessionLocal() as db:
        owner = db.query(User).filter(User.email == "admin@amicor.local").one()
        customer = db.query(User).filter(User.email == "customer.persist@example.invalid").one()
        conversation = db.query(Conversation).filter(Conversation.id == "conversation-persist").one()
        assert db.query(User).count() == before_count
        assert verify_password(_OWNER_PASSWORD, owner.hashed_password)
        assert owner.role == "admin"
        assert owner.authorized_roles == "admin,dispatcher"
        assert owner.organization_id == "tenant-owner"
        assert owner.is_active is True
        assert owner.is_verified is True
        context = UserContext(
            user_id=owner.id,
            email=owner.email,
            role=owner.role,
            organization_name=owner.organization_name,
            organization_id=owner.organization_id,
        )
        assert require_work_revenue_owner(context, db).email == "admin@amicor.local"
        assert verify_password(_CUSTOMER_PASSWORD, customer.hashed_password)
        assert customer.role == "customer"
        assert customer.authorized_roles == "customer"
        assert customer.organization_id == "tenant-customer"
        assert customer.is_active is True
        assert customer.is_verified is True
        assert conversation.title == "keep-this-record"
        assert conversation.user_id == customer.id

    assert public_sales_enabled() is False
    for package in ("starter", "starter_49", "launch_99", "business_299"):
        fulfillment = customer_fulfillment(package)
        assert fulfillment["package"] == package
        assert fulfillment["executes_work"] is False
    with pytest.raises(SecureStorageNotConfigured):
        OperationsPrivateArtifactStorage()
