"""Private read-only Growth staging schema inventory — not wired into Render.

Run only with separate owner authorization from an existing private environment.
Reports schema-only metadata. No records, passwords, migrations, exports, or
network allowlist changes. This module is NOT called during service startup.
"""
from __future__ import annotations

import json
import os
import re
import sys
from urllib.parse import urlsplit

_EXPECTED_HOST = "dpg-dbqv7mmtlv9c73d7tnb0-a"
_EXPECTED_DATABASE = "nova_ga_490_dispos"
_RESTORED_HOST = "dpg-dbuku8dckfvc73ch22e0-a"
_RESTORED_DATABASE = "nova_ga_490_dispos_nu6s"
_SHA = re.compile(r"^[0-9a-f]{40}$")


def validate_private_diagnostic_env(env: dict[str, str]) -> str:
    """Fail closed on wrong environment, target, approval, or commit identity."""
    if env.get("NOVA_GA_PRIVATE_DB_DIAGNOSTIC_APPROVED") != "true":
        raise ValueError("Private database inventory not authorized")
    if env.get("APP_ENV", "").lower() != "staging" or env.get("AMICOR_ENVIRONMENT", "").lower() != "staging":
        raise ValueError("Staging environment required")
    approved = env.get("NOVA_GA_APPROVED_STAGING_SHA", "").strip().lower()
    running = env.get("RENDER_GIT_COMMIT", "").strip().lower()
    if not _SHA.fullmatch(approved) or running != approved:
        raise ValueError("Exact staging commit pin required")
    target = env.get("NOVA_GA_DIAGNOSTIC_TARGET", "original")
    if target == "original":
        expected_host, expected_database = _EXPECTED_HOST, _EXPECTED_DATABASE
    elif target == "restored_copy":
        if env.get("NOVA_GA_RESTORED_COPY_READ_ONLY_APPROVED") != "true":
            raise ValueError("Restored-copy schema inspection not authorized")
        expected_host, expected_database = _RESTORED_HOST, _RESTORED_DATABASE
    else:
        raise ValueError("Unrecognized private diagnostic target")
    raw = env.get("DATABASE_URL", "")
    try:
        parsed = urlsplit(raw)
        if parsed.scheme not in ("postgres", "postgresql", "postgresql+psycopg2"):
            raise ValueError("PostgreSQL staging URL required")
        if parsed.hostname != expected_host or parsed.path != "/" + expected_database:
            raise ValueError("Private staging database identity mismatch")
        if not parsed.username or not parsed.password or parsed.query or parsed.fragment:
            raise ValueError("Invalid private staging connection configuration")
    except ValueError as exc:
        raise ValueError("Invalid private staging connection configuration") from None
    if parsed.scheme == "postgresql+psycopg2":
        return "postgresql://" + raw.split("://", 1)[1]
    if parsed.scheme == "postgres":
        return "postgresql://" + raw.split("://", 1)[1]
    return raw


def inspect_schema(connect, url: str, *, expected_database: str = _EXPECTED_DATABASE) -> dict:
    """Use a read-only PostgreSQL transaction; fetch only schema metadata."""
    conn = connect(url, connect_timeout=8, application_name="nova-ga-private-schema-inventory")
    try:
        conn.set_session(readonly=True, autocommit=False)
        with conn.cursor() as cur:
            cur.execute("SELECT current_database(), current_setting('server_version_num')::integer")
            db_name, version = cur.fetchone()
            if db_name != expected_database:
                raise ValueError("Unexpected connected database")
            cur.execute(
                "SELECT EXISTS (SELECT 1 FROM information_schema.tables "
                "WHERE table_schema = current_schema() AND table_name = 'alembic_version')"
            )
            has_alembic = bool(cur.fetchone()[0])
            versions = []
            if has_alembic:
                cur.execute("SELECT version_num FROM alembic_version ORDER BY version_num")
                versions = [str(row[0]) for row in cur.fetchall()]
            cur.execute(
                "SELECT count(*) FROM information_schema.tables "
                "WHERE table_schema = current_schema() AND table_name LIKE 'nova_ga_%'"
            )
            growth_table_count = int(cur.fetchone()[0])
            cur.execute(
                "SELECT EXISTS (SELECT 1 FROM information_schema.tables "
                "WHERE table_schema = current_schema() "
                "AND table_name = 'nova_ga_campaign_asset_reviews')"
            )
            campaign_table_exists = bool(cur.fetchone()[0])
        conn.rollback()
        return {
            "database_identity": expected_database,
            "server_version_num": version,
            "alembic_version_table_exists": has_alembic,
            "alembic_heads": versions,
            "growth_table_count": growth_table_count,
            "campaign_review_table_exists": campaign_table_exists,
            "read_only": True,
            "backup_verified": False,
            "data_rows_examined": 0,
        }
    finally:
        conn.close()


def main() -> int:
    try:
        url = validate_private_diagnostic_env(dict(os.environ))
        import psycopg2
        target = os.environ.get("NOVA_GA_DIAGNOSTIC_TARGET", "original")
        expected = _RESTORED_DATABASE if target == "restored_copy" else _EXPECTED_DATABASE
        summary = inspect_schema(psycopg2.connect, url, expected_database=expected)
    except Exception:
        # Never leak connection strings, account names, SQL diagnostics, or secrets.
        print("Private staging schema inspection unavailable or denied", file=sys.stderr)
        return 1
    print(json.dumps(summary, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
