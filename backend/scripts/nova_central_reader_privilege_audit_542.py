"""Read-only permission report for a future isolated Nova Central PostgreSQL reader.

No GRANT/REVOKE, schema changes, fixture insertion, or deployment actions.
Only run against a separately approved, dedicated disposable staging database.
"""
from __future__ import annotations

import json
import os
import re
from typing import Any

from sqlalchemy import create_engine, text
from sqlalchemy.engine.url import make_url

_ALLOWED_DB = "nova_central_542_dispos"
_ALLOWED_USER = "nova_central_542_reader"
_READER_TABLES = ("platform_users", "nova_central_journey_read_model")
_READER_COLUMNS = (
    "id", "role", "authorized_roles", "session_role",
    "organization_id", "auth_version", "is_active",
)


def check_target() -> str:
    """Fail before opening connections, even if accidentally invoked elsewhere."""
    if os.getenv("AMICOR_ENVIRONMENT") != "staging" or os.getenv("APP_ENV") != "staging":
        raise RuntimeError("Dedicated staging flags required")
    if os.getenv("NOVA_CENTRAL_ISOLATED_TEST") == "1":
        raise RuntimeError("Test override not allowed for PostgreSQL audit")
    if os.getenv("NOVA_CENTRAL_PERMISSION_AUDIT_APPROVED") != "true":
        raise RuntimeError("Separate owner approval required for database audit")
    approved_sha = os.getenv("NOVA_CENTRAL_APPROVED_COMMIT", "")
    if not re.fullmatch(r"[0-9a-f]{40}", approved_sha):
        raise RuntimeError("Missing approved revision")
    if approved_sha != os.getenv("RENDER_GIT_COMMIT", ""):
        raise RuntimeError("Commit mismatch")
    url_value = os.getenv("NOVA_CENTRAL_READER_DATABASE_URL", "")
    if not url_value:
        raise RuntimeError("Dedicated reader URL required")
    url = make_url(url_value)
    if (url.drivername not in {"postgresql", "postgresql+psycopg2"}
            or url.host != os.getenv("NOVA_CENTRAL_EXPECTED_DB_HOST")
            or not url.host
            or url.database != _ALLOWED_DB
            or url.username != _ALLOWED_USER
            or not url.password or url.query):
        raise RuntimeError("Reader connection identity mismatch")
    # No credentials are printed or serialized.
    return url_value


def assess_privileges(observed: dict[str, Any]) -> list[str]:
    """Pure fail-closed privilege decision; isolated from database I/O."""
    problems = []
    if observed.get("database") != _ALLOWED_DB:
        problems.append("wrong_database")
    if observed.get("principal") != _ALLOWED_USER or observed.get("session_user") != _ALLOWED_USER:
        problems.append("wrong_role")
    if observed.get("can_login") is not True:
        problems.append("login_not_verified")
    for name in ("superuser", "create_role", "create_db", "replication", "bypass_rls"):
        if observed.get(name) is not False:
            problems.append("unsafe_role_" + name)
    if observed.get("can_create_schema") is not False:
        problems.append("database_create_allowed")
    for table in _READER_TABLES:
        permissions = (observed.get("tables") or {}).get(table)
        if not isinstance(permissions, dict):
            problems.append("unknown_table_" + table)
            continue
        for action in ("INSERT", "UPDATE", "DELETE", "TRUNCATE", "REFERENCES", "TRIGGER"):
            if permissions.get(action) is not False:
                problems.append("unsafe_" + table + "_" + action)
    return problems


def read_privilege_report(url_value: str) -> dict[str, Any]:
    """Use catalog SELECTs only. Does not grant privileges or mutate tables."""
    engine = create_engine(url_value, pool_pre_ping=False)
    try:
        with engine.connect() as connection:
            identity = connection.execute(text(
                "SELECT current_database() AS db, current_user AS principal, "
                "session_user AS session_user"
            )).mappings().one()
            role = connection.execute(text(
                "SELECT rolcanlogin, rolsuper, rolcreaterole, rolcreatedb, "
                "rolreplication, rolbypassrls FROM pg_roles "
                "WHERE rolname = current_user"
            )).mappings().one()
            can_create = connection.execute(text(
                "SELECT has_database_privilege(current_user, current_database(), 'CREATE')"
            )).scalar_one()
            tables = {}
            for table in _READER_TABLES:
                table_exists = connection.execute(text(
                    "SELECT to_regclass(:table_name) IS NOT NULL"
                ), {"table_name": "public." + table}).scalar_one()
                if not table_exists:
                    tables[table] = None
                    continue
                tables[table] = {}
                for action in ("SELECT", "INSERT", "UPDATE", "DELETE", "TRUNCATE", "REFERENCES", "TRIGGER"):
                    tables[table][action] = bool(connection.execute(
                        text("SELECT has_table_privilege(current_user, :table_name, :action)"),
                        {"table_name": "public." + table, "action": action},
                    ).scalar_one())
            return {
                "database": identity["db"],
                "principal": identity["principal"],
                "session_user": identity["session_user"],
                "can_login": role["rolcanlogin"],
                "superuser": role["rolsuper"],
                "create_role": role["rolcreaterole"],
                "create_db": role["rolcreatedb"],
                "replication": role["rolreplication"],
                "bypass_rls": role["rolbypassrls"],
                "can_create_schema": bool(can_create),
                "tables": tables,
            }
    finally:
        engine.dispose()


def main() -> int:
    result = read_privilege_report(check_target())
    failures = assess_privileges(result)
    print(json.dumps({"status": "blocked" if failures else "review_required",
                      "checks": failures, "tables_present": sorted(
                          k for k, v in result["tables"].items() if v is not None)}))
    # A successful catalog check remains review_required; independent physical
    # privilege-denial tests and owner approval are still necessary.
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
