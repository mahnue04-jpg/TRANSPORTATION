"""Explicit, staging-only Nova Operations lease migration runner.

Run from backend/ on a trusted Render internal-network execution environment.
Never put a DB URL in command-line arguments or logs. This script does not
create a backup or certify a restore; those must be independently evidenced.
It does not start a web app, worker, storage client, or customer processing.
"""
from __future__ import annotations

import argparse
import importlib.util
import json
import os
from pathlib import Path

import sqlalchemy as sa
from alembic.migration import MigrationContext
from alembic.operations import Operations

EXPECTED_DB = "nova_operations_staging_db_541"
EXPECTED_USER = "nova_operations_staging_db_541_user"
TABLE = "nova_operations_processing_leases"
MIGRATION = Path(__file__).with_name("staging_migrations") / "operations_lease_schema.py"


def _check_environment() -> None:
    configured = {
        os.environ[name].strip().lower()
        for name in ("AMICOR_ENVIRONMENT", "APP_ENV", "ENVIRONMENT")
        if os.getenv(name)
    }
    if configured != {"staging"}:
        raise RuntimeError("Only explicitly identified staging environment is supported")
    if os.getenv("NOVA_OPERATIONS_LEASE_SCHEMA_APPROVED") != "staging-only":
        raise RuntimeError("Explicit staging-only schema approval flag required")
    if os.getenv("NOVA_OPERATIONS_EXPECTED_STAGING_DATABASE") != EXPECTED_DB:
        raise RuntimeError("Exact dedicated Operations staging database identity required")
    for name in (
        "NOVA_OPERATIONS_LEASE_WORKER_ENABLED",
        "NOVA_OPERATIONS_QUEUED_CSV_HTTP_ENABLED",
        "NOVA_OPERATIONS_DURABLE_CSV_ENABLED",
        "NOVA_WORK_REVENUE_PRIVATE_STORAGE_ENABLED",
    ):
        if os.getenv(name, "").strip().lower() in {"1", "true", "yes"}:
            raise RuntimeError(f"Forbidden active capability: {name}")


def _restore_evidence(path: str | None) -> None:
    """Require manually captured evidence of an actually completed restore.

    This guards omissions, not forgery: the operator must independently inspect
    Render recovery details and the disposable restore's schema/data.
    """
    if not path:
        raise RuntimeError("Verified backup and disposable restore evidence required")
    evidence = json.loads(Path(path).read_text(encoding="utf-8"))
    required = ("source_database", "backup_identifier", "restore_target",
                "restore_verified_at", "verified_by", "verification_result")
    if not isinstance(evidence, dict) or any(not isinstance(evidence.get(k), str)
                                              or not evidence[k].strip() for k in required):
        raise RuntimeError("Incomplete backup/restore evidence")
    if (evidence["source_database"] != EXPECTED_DB
            or evidence["restore_target"] == EXPECTED_DB
            or evidence["verification_result"] != "passed"):
        raise RuntimeError("Restoration evidence must prove isolated target verification")


def _load_migration():
    spec = importlib.util.spec_from_file_location("operations_lease_schema_manual", MIGRATION)
    if not spec or not spec.loader:
        raise RuntimeError("Reviewed migration file unavailable")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def main() -> None:
    parser = argparse.ArgumentParser(description="Operations staging lease schema gate")
    parser.add_argument("--apply", action="store_true",
                        help="Apply reviewed additive DDL; requires prior verified restore")
    parser.add_argument("--restore-evidence", metavar="JSON_FILE")
    args = parser.parse_args()
    _check_environment()
    url = os.environ.get("NOVA_OPERATIONS_STAGING_DATABASE_URL", "")
    if not url:
        raise RuntimeError("Internal staging database URL required in environment")
    engine = sa.create_engine(url, pool_pre_ping=True, connect_args={"connect_timeout": 8})
    try:
        with engine.connect() as conn:
            if conn.dialect.name != "postgresql":
                raise RuntimeError("PostgreSQL required")
            identity = conn.execute(sa.text(
                "SELECT current_database(), current_user, pg_is_in_recovery()"
            )).one()
            if identity[0] != EXPECTED_DB or identity[1] != EXPECTED_USER:
                raise RuntimeError("Connected to unexpected dedicated staging DB or role")
            if identity[2]:
                raise RuntimeError("Migration must not target a recovery replica")
            existing = sa.inspect(conn).get_table_names()
            if TABLE in existing:
                raise RuntimeError("Lease table already exists; reconcile, never reapply")
            if not args.apply:
                print("PREFLIGHT PASS: expected dedicated staging DB; lease table absent; no DDL")
                return
        _restore_evidence(args.restore_evidence)
        migration = _load_migration()
        with engine.begin() as conn:
            identity = conn.execute(sa.text(
                "SELECT current_database(), current_user, pg_is_in_recovery()"
            )).one()
            if (identity[0], identity[1], identity[2]) != (
                EXPECTED_DB, EXPECTED_USER, False
            ):
                raise RuntimeError("Database identity or primary status changed")
            if TABLE in sa.inspect(conn).get_table_names():
                raise RuntimeError("Lease table appeared since preflight")
            migration.op = Operations(MigrationContext.configure(conn))
            migration.upgrade()
            # Keep verification inside the transaction so an invalid schema
            # rolls back atomically rather than persisting a partial rollout.
            schema = sa.inspect(conn)
            columns = {col["name"] for col in schema.get_columns(TABLE)}
            required = {"job_id", "organization_id", "owner_user_id",
                        "lease_token", "state", "input_sha256", "input_ref",
                        "input_size", "updated_at", "available_at"}
            checks = {c["name"] for c in schema.get_check_constraints(TABLE)}
            indexes = {i["name"] for i in schema.get_indexes(TABLE)}
            if not required.issubset(columns) or not {
                "ck_nova_operations_lease_state",
                "ck_nova_operations_lease_input_binding",
                "ck_nova_operations_lease_attempts",
            }.issubset(checks) or "ix_nova_operations_lease_ready" not in indexes:
                raise RuntimeError("Schema postcheck failed; transaction rolled back")
        print("MIGRATION APPLIED: dedicated staging lease schema only; workers/customer processing OFF")
    finally:
        engine.dispose()


if __name__ == "__main__":
    main()
