"""Static safeguards for inactive casting persistence models."""
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
MODELS = ROOT / "app/core/nova/creative_studio/casting_db_models.py"
SCHEMA = ROOT / "app/core/nova/creative_studio/schema_ensure.py"
ROUTER = ROOT / "app/core/nova/creative_studio/router.py"


def test_casting_tables_are_defined_but_not_activated():
    models = MODELS.read_text(encoding="utf-8")
    for table in ("nova_casting_campaigns", "nova_casting_applications", "nova_casting_reviews", "nova_casting_media"):
        assert table in models
    assert "UniqueConstraint" in models
    assert "CheckConstraint" in models
    assert "casting_db_models" not in SCHEMA.read_text(encoding="utf-8")
    assert "casting_db_models" not in ROUTER.read_text(encoding="utf-8")


def test_media_metadata_is_private_and_quarantined_by_default():
    models = MODELS.read_text(encoding="utf-8")
    assert 'class NovaCastingMedia(Base):' in models
    assert 'ForeignKey("nova_casting_applications.id")' in models
    assert 'default="PENDING"' in models
    assert "ck_nova_casting_media_status" in models
    assert "byte_size > 0 AND byte_size <= 262144000" in models
    assert "storage_key" in models


def test_casting_has_no_live_registration_or_upload_routes():
    main = (ROOT / "app/main.py").read_text(encoding="utf-8")
    creative_router = ROUTER.read_text(encoding="utf-8")
    assert "/api/nova/casting/" not in main
    assert "/api/nova/casting/" not in creative_router
    assert "casting_media_access" not in main
    assert "casting_access" not in main
    assert "casting_upload_rules" not in creative_router


def test_private_casting_models_not_created_by_existing_schema_ensure():
    schema = SCHEMA.read_text(encoding="utf-8")
    for name in ("NovaCastingCampaign", "NovaCastingApplication", "NovaCastingReview", "NovaCastingMedia"):
        assert name not in schema


def test_casting_memberships_are_explicit_and_inactive():
    models = MODELS.read_text(encoding="utf-8")
    assert 'class NovaCastingOrganization(Base):' in models
    assert 'class NovaCastingMembership(Base):' in models
    assert 'default="PENDING"' in models
    assert 'nova_tenant_id: Mapped[str]' in models
    assert 'uq_nova_casting_org_tenant_id' in models
    assert 'mapped_column(Boolean, nullable=False, default=False)' in models
    assert 'uq_nova_casting_org_user' in models
    assert 'ix_nova_casting_membership_active_org' in models
    assert 'ForeignKey("platform_users.id")' in models
    assert 'ck_nova_casting_membership_role' in models
    schema = SCHEMA.read_text(encoding="utf-8")
    assert "NovaCastingMembership" not in schema
    assert "NovaCastingOrganization" not in schema


def test_applicants_and_reviewers_reference_existing_nova_users():
    models = MODELS.read_text(encoding="utf-8")
    assert 'applicant_id: Mapped[str] = mapped_column(String(36), ForeignKey("platform_users.id")' in models
    assert 'reviewer_id: Mapped[str] = mapped_column(String(36), ForeignKey("platform_users.id")' in models


def test_campaign_owner_references_casting_organization():
    models = MODELS.read_text(encoding="utf-8")
    assert 'owner_id: Mapped[str] = mapped_column(String(36), ForeignKey("nova_casting_organizations.id"), nullable=False)' in models


def test_cross_organization_cascade_is_blocked_by_composite_keys():
    models = MODELS.read_text(encoding="utf-8")
    for constraint in ("uq_nova_casting_campaign_owner_id", "uq_nova_casting_application_owner_id",
                       "fk_nova_casting_application_campaign_owner",
                       "fk_nova_casting_review_application_owner",
                       "fk_nova_casting_media_application_owner"):
        assert constraint in models
    assert "ForeignKeyConstraint" in models


def test_membership_tenant_matches_casting_organization():
    models = MODELS.read_text(encoding="utf-8")
    assert "fk_nova_casting_member_tenant_org" in models
    assert 'ForeignKeyConstraint(["nova_tenant_id", "organization_id"]' in models
