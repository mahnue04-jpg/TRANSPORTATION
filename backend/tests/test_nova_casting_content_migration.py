"""Static regression coverage for inactive casting content migration."""
from pathlib import Path

MIGRATION = Path(__file__).resolve().parents[1] / "migrations/versions/20261010_casting_content_draft.py"


def test_casting_content_migration_is_reversible_and_tenant_scoped():
    source = MIGRATION.read_text(encoding="utf-8")
    assert 'down_revision = "20261010_casting_org_draft"' in source
    assert "def upgrade():" in source and "def downgrade():" in source
    for table in ("nova_casting_campaigns", "nova_casting_applications",
                  "nova_casting_reviews", "nova_casting_media"):
        assert f'op.create_table("{table}"' in source
        assert f'op.drop_table("{table}")' in source
    for fk in ("fk_nova_casting_application_campaign_owner",
               "fk_nova_casting_review_application_owner",
               "fk_nova_casting_media_application_owner"):
        assert fk in source
    assert 'server_default="DRAFT"' in source
    assert 'server_default="PENDING"' in source
    assert "byte_size > 0 AND byte_size <= 262144000" in source
