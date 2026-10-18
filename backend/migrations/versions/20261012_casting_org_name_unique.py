"""Unique sandbox organization name per Nova tenant.

Revision ID: 20261012_casting_org_name
Revises: 20261011_casting_schema_repair

Safe plan, dev and disposable databases only:

- Do not run this against production. When AMICOR_ENVIRONMENT, ENVIRONMENT,
  or APP_ENV is production or prod, upgrade and downgrade return without DDL.
  Production ``alembic upgrade heads`` would only stamp the revision.
- Do not deploy, and do not apply this on a persistent database, until an
  owner has reviewed duplicate names and authorized the schema change.
- This revision does not delete, merge, or rewrite organization rows.
- If nova_casting_organizations is absent, it returns. It does not create the
  table and it does not enable casting reads, writes, or public intake.
- If two rows already share a tenant and name, upgrade raises and leaves the
  schema unchanged. Resolve those rows manually, then run the revision again.
- When the table is present and names are unique, upgrade adds
  uq_nova_casting_org_tenant_name. Downgrade drops that constraint only.

The application retry in ensure_sandbox_organization depends on this
constraint. Without it, two concurrent creates can still insert two rows.
"""
from alembic import op
import sqlalchemy as sa

revision = "20261012_casting_org_name"
down_revision = "20261011_casting_schema_repair"
branch_labels = None
depends_on = None

CONSTRAINT = "uq_nova_casting_org_tenant_name"


def _production_schema_locked() -> bool:
    """Match casting_flags.casting_production_locked without importing the app."""
    import os
    for name in ("AMICOR_ENVIRONMENT", "ENVIRONMENT", "APP_ENV"):
        if os.getenv(name, "").strip().lower() in {"production", "prod"}:
            return True
    return False


def _table_ready(bind) -> bool:
    return "nova_casting_organizations" in set(sa.inspect(bind).get_table_names())


def _constraint_present(bind) -> bool:
    found = sa.inspect(bind).get_unique_constraints("nova_casting_organizations")
    return any(item.get("name") == CONSTRAINT for item in found)


def _duplicate_groups(bind):
    return bind.execute(sa.text(
        """
        SELECT nova_tenant_id, name, COUNT(*) AS n
        FROM nova_casting_organizations
        GROUP BY nova_tenant_id, name
        HAVING COUNT(*) > 1
        """
    )).fetchall()


def upgrade():
    if _production_schema_locked():
        return
    bind = op.get_bind()
    if not _table_ready(bind) or _constraint_present(bind):
        return
    duplicates = _duplicate_groups(bind)
    if duplicates:
        raise RuntimeError(
            "nova_casting_organizations has "
            f"{len(duplicates)} duplicate tenant/name groups. "
            "Resolve them manually before adding "
            f"{CONSTRAINT}. This revision does not delete or merge rows."
        )
    _add_constraint(bind)


def _add_constraint(bind) -> None:
    """SQLite cannot ALTER in a constraint, so disposable sqlite copies the table.

    The copy keeps every existing row. PostgreSQL adds the constraint in place.
    """
    if bind.dialect.name == "sqlite":
        with op.batch_alter_table("nova_casting_organizations") as batch:
            batch.create_unique_constraint(CONSTRAINT, ["nova_tenant_id", "name"])
        return
    op.create_unique_constraint(
        CONSTRAINT,
        "nova_casting_organizations",
        ["nova_tenant_id", "name"],
    )


def downgrade():
    if _production_schema_locked():
        return
    bind = op.get_bind()
    if not _table_ready(bind) or not _constraint_present(bind):
        return
    if bind.dialect.name == "sqlite":
        with op.batch_alter_table("nova_casting_organizations") as batch:
            batch.drop_constraint(CONSTRAINT, type_="unique")
        return
    op.drop_constraint(CONSTRAINT, "nova_casting_organizations", type_="unique")
