"""Fail-closed, read-only preflight for the existing Nova Growth staging service.

Do not run on production. No migrations, test-data inserts, worker starts,
external provider calls, or database writes happen here. The only effect after
validation is replacing this process with the existing single-worker app.
"""
from __future__ import annotations

import os
import sys
from urllib.parse import urlparse


EXPECTED_DB_HOST = "dpg-dbqv7mmtlv9c73d7tnb0-a"
EXPECTED_DB_NAME = "nova_ga_490_dispos"
EXPECTED_ORIGIN = "https://nova-growth-validation-490.onrender.com"
EXPECTED_REVISION = "20261112_nova_ga_retention"
TRUE = {"1", "true", "yes", "on"}


def _enabled(value: str | None) -> bool:
    return str(value or "").strip().lower() in TRUE


def validate_environment(env: dict[str, str]) -> str:
    """Return normalized private database URL; never print it."""
    if any(env.get(k, "").strip().lower() in {"production", "prod"}
           for k in ("AMICOR_ENVIRONMENT", "ENVIRONMENT", "APP_ENV")):
        raise RuntimeError("Growth staging refuses production environment")
    approved = env.get("NOVA_GA_APPROVED_STAGING_SHA", "").strip()
    running = env.get("RENDER_GIT_COMMIT", "").strip()
    if len(approved) != 40 or any(c not in "0123456789abcdef" for c in approved) or running != approved:
        raise RuntimeError("Staging commit is not explicitly approved")
    if env.get("RENDER_EXTERNAL_URL", "").rstrip("/") != EXPECTED_ORIGIN:
        raise RuntimeError("Unexpected staging public URL")
    if not _enabled(env.get("NOVA_GROWTH_AGENT_ENABLED")) or not _enabled(env.get("NOVA_GROWTH_AGENT_DEMO_MODE")):
        raise RuntimeError("Staging must use enabled synthetic Growth Agent mode")
    for key in (
        "NOVA_GROWTH_AGENT_BACKGROUND_WORKER",
        "NOVA_GROWTH_AGENT_RETENTION_DELETE_ENABLED",
        "NOVA_GROWTH_AGENT_RETENTION_SCHEDULE_ENABLED",
        "NOVA_GA_REAL_EMAIL_SEND",
        "NOVA_GA_REAL_SMS_SEND",
        "NOVA_GA_REAL_CALENDAR_WRITE",
        "NOVA_GA_REAL_STRIPE_CHARGES",
    ):
        if _enabled(env.get(key)):
            raise RuntimeError("Unsafe staging feature flag: " + key)
    raw = env.get("DATABASE_URL", "").strip()
    if raw.startswith("postgres://"):
        normalized = "postgresql+psycopg2://" + raw[len("postgres://"):]
    elif raw.startswith("postgresql://"):
        normalized = "postgresql+psycopg2://" + raw[len("postgresql://"):]
    elif raw.startswith("postgresql+psycopg2://"):
        normalized = raw
    else:
        raise RuntimeError("Unexpected staging database driver")
    parsed = urlparse(normalized)
    if parsed.hostname != EXPECTED_DB_HOST or parsed.path != "/" + EXPECTED_DB_NAME:
        raise RuntimeError("Unexpected staging database identity")
    if not parsed.username or not parsed.password:
        raise RuntimeError("Staging database credentials are missing")
    port = env.get("PORT", "")
    if not port.isdecimal() or not (1 <= int(port) <= 65535):
        raise RuntimeError("Invalid staging app port")
    return normalized


def verify_read_only_database(database_url: str) -> None:
    from sqlalchemy import create_engine, text
    engine = create_engine(database_url, pool_pre_ping=True, connect_args={"connect_timeout": 8})
    try:
        with engine.connect() as conn:
            conn.exec_driver_sql("SET TRANSACTION READ ONLY")
            db_name = conn.execute(text("SELECT current_database()")).scalar_one()
            if db_name != EXPECTED_DB_NAME:
                raise RuntimeError("Unexpected connected database")
            revisions = set(conn.execute(text("SELECT version_num FROM alembic_version")).scalars())
            if revisions != {EXPECTED_REVISION}:
                raise RuntimeError("Unexpected staging migration revision")
            found = set(conn.execute(text(
                "SELECT table_name FROM information_schema.tables "
                "WHERE table_schema='public' AND table_name IN "
                "('nova_ga_business_profiles', 'nova_ga_workflow_runs', 'nova_ga_audit_events')"
            )).scalars())
            if found != {"nova_ga_business_profiles", "nova_ga_workflow_runs", "nova_ga_audit_events"}:
                raise RuntimeError("Missing required staging Growth Agent tables")
            conn.rollback()
    finally:
        engine.dispose()


def main() -> None:
    normalized = validate_environment(dict(os.environ))
    from app.core.nova.growth_agent.flags import live_flags
    flags = live_flags()
    if not flags.get("MOCK_TRANSPORT_ONLY") or any(flags.get(k) for k in (
        "REAL_EMAIL_SEND", "REAL_SMS_SEND", "REAL_CALENDAR_WRITE",
        "REAL_VOICE", "REAL_STRIPE_CHARGES", "BULK_COLD_OUTREACH",
    )):
        raise RuntimeError("Live Growth Agent providers must stay disabled")
    verify_read_only_database(normalized)
    os.environ["DATABASE_URL"] = normalized
    os.environ["AMICOR_PUBLIC_URL"] = EXPECTED_ORIGIN
    os.environ["ALLOWED_ORIGINS"] = EXPECTED_ORIGIN
    os.execvp("uvicorn", [
        "uvicorn", "app.main:app", "--host", "0.0.0.0",
        "--port", os.environ["PORT"], "--workers", "1",
    ])


if __name__ == "__main__":
    try:
        main()
    except Exception as exc:
        # Fail closed without printing DB URLs, secrets, or exception context.
        print("Growth Agent staging preflight failed: " + type(exc).__name__, file=sys.stderr)
        sys.exit(1)
