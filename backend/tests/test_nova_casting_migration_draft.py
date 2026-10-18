"""Static staging-migration safety checks: no database access."""
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
MIGRATION = ROOT / "migrations/versions/20261010_casting_org_draft.py"


def test_staging_casting_migration_is_reversible_and_deny_by_default():
    source = MIGRATION.read_text(encoding="utf-8")
    assert 'down_revision = "20261009_nova_ws_transfer"' in source
    assert 'def upgrade():' in source
    assert 'def downgrade():' in source
    assert 'server_default="PENDING"' in source
    assert 'server_default=sa.false()' in source
    assert 'fk_nova_casting_member_tenant_org' in source
    assert 'sa.ForeignKey("platform_users.id")' in source
    for table in ("nova_casting_organizations", "nova_casting_memberships"):
        assert f'op.create_table(\n        "{table}"' in source
        assert f'op.drop_table("{table}")' in source
