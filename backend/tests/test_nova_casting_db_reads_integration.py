"""PostgreSQL integration test for inactive casting read service.

Uses disposable CASTING_TEST_POSTGRES_URL and rolls back seeded rows.
"""
import os
import pytest
import sqlalchemy as sa
from sqlalchemy.orm import Session

URL = os.getenv("CASTING_TEST_POSTGRES_URL")

@pytest.mark.skipif(not URL, reason="Disposable PostgreSQL unavailable")
def test_authenticated_casting_reads_are_tenant_scoped():
    from app.db.session import Base
    from app.db.models import User
    from app.core.nova.creative_studio.casting_db_models import (
        NovaCastingOrganization, NovaCastingMembership, NovaCastingCampaign,
        NovaCastingApplication,
    )
    from app.core.nova.creative_studio.casting_db_reads import read_casting_application_for_nova_user
    from app.core.nova.creative_studio.casting_access import CastingAccessDenied

    # Use a dedicated schema so minimalist migration fixtures cannot shadow Nova users.
    admin_engine = sa.create_engine(URL)
    with admin_engine.begin() as admin:
        admin.exec_driver_sql("DROP SCHEMA IF EXISTS casting_read_ci CASCADE")
        admin.exec_driver_sql("CREATE SCHEMA casting_read_ci")
    engine = sa.create_engine(URL, connect_args={"options": "-csearch_path=casting_read_ci"})
    tables = [User.__table__, NovaCastingOrganization.__table__,
              NovaCastingMembership.__table__, NovaCastingCampaign.__table__,
              NovaCastingApplication.__table__]
    # Create only the test tables, never the application's real database.
    Base.metadata.create_all(bind=engine, tables=tables)
    with engine.connect() as conn:
        transaction = conn.begin()
        db = Session(bind=conn)
        try:
            db.add_all([
                User(id="casting-reviewer", email="casting-reviewer@example.invalid",
                     hashed_password="not-a-login", role="staff", organization_id="tenant-a",
                     is_active=True, is_verified=True),
                User(id="casting-applicant", email="casting-applicant@example.invalid",
                     hashed_password="not-a-login", role="staff", organization_id="tenant-a",
                     is_active=True, is_verified=True),
                NovaCastingOrganization(id="casting-org-a", nova_tenant_id="tenant-a",
                    name="Test company", verification_status="VERIFIED", created_at="now"),
            ])
            db.flush()  # Parent users and organization must exist before child rows.
            db.add_all([
                NovaCastingMembership(id="member-a", nova_tenant_id="tenant-a",
                    organization_id="casting-org-a", user_id="casting-reviewer",
                    casting_role="reviewer", active=True, created_at="now"),
                NovaCastingCampaign(id="campaign-a", owner_id="casting-org-a",
                    title="Demo", category="film", status="DRAFT", created_at="now"),
            ])
            db.flush()
            db.add(NovaCastingApplication(id="application-a", owner_id="casting-org-a",
                campaign_id="campaign-a", applicant_id="casting-applicant",
                status="DRAFT", created_at="now"))
            db.flush()
            def read(tenant="tenant-a"):
                return read_casting_application_for_nova_user(
                    db=db, user_id="casting-reviewer", tenant_id=tenant,
                    organization_id="casting-org-a", application_id="application-a")
            assert read()["id"] == "application-a"
            # Even a valid reviewer must never receive a private storage locator.
            assert "storage_key" not in read()
            membership = db.get(NovaCastingMembership, "member-a")
            membership.casting_role = "admin"
            db.flush()
            with pytest.raises(CastingAccessDenied):
                read()
            membership.casting_role = "reviewer"
            db.flush()
            with pytest.raises(CastingAccessDenied):
                read_casting_application_for_nova_user(
                    db=db, user_id="casting-reviewer", tenant_id="tenant-a",
                    organization_id="some-other-organization", application_id="application-a")
            with pytest.raises(CastingAccessDenied):
                read("tenant-b")
            reviewer = db.get(User, "casting-reviewer")
            reviewer.is_active = False
            db.flush()
            with pytest.raises(CastingAccessDenied):
                read()
            reviewer.is_active = True
            reviewer.organization_id = "tenant-b"
            db.flush()
            with pytest.raises(CastingAccessDenied):
                read()
            reviewer.organization_id = "tenant-a"
            db.flush()
            db.get(NovaCastingMembership, "member-a").active = False
            db.flush()
            with pytest.raises(CastingAccessDenied):
                read()
            db.get(NovaCastingMembership, "member-a").active = True
            db.get(NovaCastingOrganization, "casting-org-a").verification_status = "REJECTED"
            db.flush()
            with pytest.raises(CastingAccessDenied):
                read()
        finally:
            db.close()
            transaction.rollback()
    engine.dispose()
    with admin_engine.begin() as admin:
        admin.exec_driver_sql("DROP SCHEMA casting_read_ci CASCADE")
    admin_engine.dispose()
