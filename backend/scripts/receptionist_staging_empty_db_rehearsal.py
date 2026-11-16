#!/usr/bin/env python3
"""Empty-database first-deploy rehearsal for Nova receptionist staging.

Proves a brand-new PostgreSQL database reaches the approved schema through the
exact free-plan startCommand migration path (scripts/receptionist_staging_start.py
--migrate-only), without stamp_parent shortcuts or ORM create_all for schema.

Then boots uvicorn with the proposed staging environment and requires
GET /api/health/readiness → 200.

STAGING PREP ONLY — never targets production or nova_ga_490_dispos.
"""

from __future__ import annotations

import argparse
import json
import os
import signal
import subprocess
import sys
import time
import urllib.error
import urllib.request
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

RECEPTIONIST_TABLES = (
    "nova_ga_calendar_oauth_states",
    "nova_ga_calendar_connections",
    "nova_ga_calendar_sync_jobs",
    "nova_ga_owner_notifications",
    "nova_ga_handoff_requests",
    "nova_ga_voice_agent_mappings",
    "nova_ga_voice_webhook_events",
    "nova_ga_voice_sessions",
)
PARENT_MARKERS = (
    "nova_ga_business_profiles",
    "nova_ga_contacts",
    "nova_ga_appointments",
    "nova_ga_retention_schedule_runs",
)
TARGET_REVISION = "20261116_nova_ga_receptionist"
UTC = timezone.utc


def _assert_disposable(url: str) -> None:
    parsed = urlparse(url.replace("postgresql+psycopg2://", "postgresql://", 1))
    host = (parsed.hostname or "").lower()
    dbname = (parsed.path or "").lstrip("/").lower()
    if any(f in host for f in ("amicor-health-isf", "production", "prod.", "render.com")):
        raise SystemExit(f"Refusing non-disposable host: {host}")
    if "490" in dbname or dbname in {"nova_ga_490_dispos"}:
        raise SystemExit(f"Refusing existing staging DB name: {dbname}")
    if not any(tok in dbname for tok in ("test", "dispos", "ci", "receptionist", "nova_ga", "empty")):
        raise SystemExit(f"Database name must look disposable: {dbname}")


def _psql_url(sqlalchemy_url: str) -> str:
    return sqlalchemy_url.replace("postgresql+psycopg2://", "postgresql://", 1)


def _dbname(url: str) -> str:
    return (urlparse(url).path or "").lstrip("/")


def _admin_url(url: str) -> str:
    return _psql_url(url).rsplit("/", 1)[0] + "/postgres"


def _run(cmd: list[str], *, cwd: Path | None = None, env: dict[str, str] | None = None) -> None:
    print("+", " ".join(cmd), flush=True)
    subprocess.run(cmd, check=True, cwd=str(cwd) if cwd else None, env=env)


def _recreate_db(url: str) -> None:
    db = _dbname(url)
    admin = _admin_url(url)
    env = {**os.environ, "PGPASSWORD": os.environ.get("PGPASSWORD") or "ga_ci_dispos"}
    _run(
        [
            "psql",
            admin,
            "-v",
            "ON_ERROR_STOP=1",
            "-c",
            "SELECT pg_terminate_backend(pid) FROM pg_stat_activity "
            f"WHERE datname = '{db}' AND pid <> pg_backend_pid();",
        ],
        env=env,
    )
    _run(["psql", admin, "-c", f'DROP DATABASE IF EXISTS "{db}";'], env=env)
    _run(["psql", admin, "-c", f'CREATE DATABASE "{db}" OWNER ga_ci;'], env=env)


def _table_names(url: str) -> set[str]:
    from sqlalchemy import create_engine, inspect

    engine = create_engine(url, pool_pre_ping=True)
    try:
        return set(inspect(engine).get_table_names())
    finally:
        engine.dispose()


def _constraints(url: str, table: str) -> list[str]:
    from sqlalchemy import create_engine, inspect

    engine = create_engine(url, pool_pre_ping=True)
    try:
        insp = inspect(engine)
        names = [c["name"] for c in insp.get_unique_constraints(table)]
        names.extend(pk["name"] for pk in [insp.get_pk_constraint(table)] if pk and pk.get("name"))
        names.extend(ix["name"] for ix in insp.get_indexes(table) if ix.get("name"))
        return sorted({n for n in names if n})
    finally:
        engine.dispose()


def _wait_readiness(base: str, timeout: float = 90.0) -> dict[str, Any]:
    deadline = time.time() + timeout
    last_error = ""
    while time.time() < deadline:
        try:
            with urllib.request.urlopen(f"{base}/api/health/readiness", timeout=5) as resp:
                body = resp.read().decode("utf-8")
                payload = json.loads(body)
                return {
                    "http_status": resp.status,
                    "overall_status": payload.get("overall_status"),
                    "traffic_ready": payload.get("traffic_ready"),
                    "http_probe": payload.get("http_probe"),
                    "database_connected": (payload.get("database") or {}).get("connected"),
                    "blocked_reasons": payload.get("blocked_reasons") or [],
                }
        except urllib.error.HTTPError as exc:
            body = exc.read().decode("utf-8", errors="replace")
            try:
                payload = json.loads(body)
            except Exception:
                payload = {"raw": body[:500]}
            last_error = f"HTTP {exc.code}: {payload}"
            if exc.code == 503:
                time.sleep(1.0)
                continue
            raise SystemExit(last_error)
        except Exception as exc:
            last_error = str(exc)
            time.sleep(1.0)
    raise SystemExit(f"readiness did not become healthy: {last_error}")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--url",
        default="postgresql+psycopg2://ga_ci:ga_ci_dispos@127.0.0.1:5432/nova_ga_receptionist_empty",
    )
    parser.add_argument(
        "--out",
        default="docs/nova/growth-agent/screenshots/receptionist_staging_empty_db_rehearsal.json",
    )
    parser.add_argument("--port", default="8788")
    args = parser.parse_args()
    _assert_disposable(args.url)

    repo = Path(__file__).resolve().parents[2]
    backend = repo / "backend"
    out_path = Path(args.out)
    if not out_path.is_absolute():
        out_path = repo / out_path

    evidence: dict[str, Any] = {
        "started_at_utc": datetime.now(UTC).isoformat(),
        "procedure": "scripts/receptionist_staging_start.py --migrate-only",
        "target_revision": TARGET_REVISION,
        "db": _dbname(args.url),
        "src_bootstrap": "empty_database_full_alembic_chain",
        "orm_create_all_used": False,
        "stamp_parent_used": False,
    }

    _recreate_db(args.url)
    before = _table_names(args.url)
    evidence["tables_before_migrate"] = sorted(before)
    if before:
        raise SystemExit(f"Expected empty database, found tables: {sorted(before)[:20]}")

    env = os.environ.copy()
    env.update(
        {
            "PGPASSWORD": env.get("PGPASSWORD") or "ga_ci_dispos",
            "DATABASE_URL": args.url,
            "ALEMBIC_DATABASE_URL": args.url,
            "NOVA_GA_EXPECTED_DATABASE_NAME": _dbname(args.url),
            "NOVA_GA_EXPECTED_ALEMBIC_REVISION": TARGET_REVISION,
            "APP_ENV": "staging",
            "AMICOR_ENVIRONMENT": "staging",
            "TESTING": "false",
        }
    )
    # Local rehearsal does not set RENDER_GIT_COMMIT; leave commit guard unset.
    env.pop("NOVA_GA_EXPECTED_GIT_COMMIT", None)

    migrate = subprocess.run(
        [sys.executable, "scripts/receptionist_staging_start.py", "--migrate-only"],
        cwd=str(backend),
        env=env,
        check=False,
        capture_output=True,
        text=True,
    )
    evidence["migrate_exit"] = migrate.returncode
    evidence["migrate_stdout_tail"] = (migrate.stdout or "")[-1200:]
    evidence["migrate_stderr_tail"] = (migrate.stderr or "")[-1200:]
    if migrate.returncode != 0:
        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.write_text(json.dumps(evidence, indent=2) + "\n")
        raise SystemExit(f"migrate-only failed: {migrate.stderr or migrate.stdout}")

    tables = _table_names(args.url)
    missing_recv = [t for t in RECEPTIONIST_TABLES if t not in tables]
    missing_parent = [t for t in PARENT_MARKERS if t not in tables]
    evidence["receptionist_tables"] = [t for t in RECEPTIONIST_TABLES if t in tables]
    evidence["parent_marker_tables"] = [t for t in PARENT_MARKERS if t in tables]
    evidence["missing_receptionist_tables"] = missing_recv
    evidence["missing_parent_tables"] = missing_parent
    evidence["voice_mapping_constraints"] = _constraints(args.url, "nova_ga_voice_agent_mappings")
    evidence["sync_job_constraints"] = _constraints(args.url, "nova_ga_calendar_sync_jobs")

    if missing_recv or missing_parent:
        raise SystemExit(f"schema incomplete: recv={missing_recv} parent={missing_parent}")

    # Confirm alembic current via start script verification already; also store current.
    cur = subprocess.run(
        [sys.executable, "-m", "alembic", "current"],
        cwd=str(backend),
        env=env,
        check=True,
        capture_output=True,
        text=True,
    )
    evidence["alembic_current"] = (cur.stdout or cur.stderr or "").strip()
    if TARGET_REVISION not in evidence["alembic_current"]:
        raise SystemExit(f"unexpected revision: {evidence['alembic_current']}")

    # Boot app with proposed staging traffic env (optional Google/Twilio unset).
    from cryptography.fernet import Fernet

    app_env = env.copy()
    app_env.update(
        {
            "PORT": str(args.port),
            "SECRET_KEY": "staging-secret-key-not-default-xxxxxxxx",
            "JWT_SECRET": "staging-jwt-secret-not-default-yyyyyyyy",
            "AMICOR_SEED_PASSWORD": "Amicor123!",
            "AMICOR_DEPLOYMENT_SYNC_KEY": "sync-key-staging-zzzzzzzz",
            "AMICOR_PUBLIC_URL": "https://nova-receptionist-staging.onrender.com",
            "ALLOWED_ORIGINS": "https://nova-receptionist-staging.onrender.com",
            "APP_VERSION": "2026.11.16-nova-receptionist.staging",
            "LOG_LEVEL": "INFO",
            "NOVA_GROWTH_AGENT_ENABLED": "true",
            "NOVA_GROWTH_AGENT_DEMO_MODE": "true",
            "NOVA_GROWTH_AGENT_WIDGET_ENABLED": "true",
            "NOVA_GROWTH_AGENT_WIDGET_SECRET": "widget-secret-staging",
            "NOVA_GROWTH_AGENT_BACKGROUND_WORKER": "true",
            "NOVA_GROWTH_AGENT_RETENTION_SCHEDULE_ENABLED": "true",
            "NOVA_GROWTH_AGENT_RETENTION_DELETE_ENABLED": "false",
            "NOVA_GROWTH_AGENT_CALENDAR_SYNC_WORKER": "true",
            "NOVA_GROWTH_AGENT_OWNER_NOTIFY_WORKER": "true",
            "NOVA_GROWTH_AGENT_VOICE_SIMULATOR": "true",
            "NOVA_GA_GOOGLE_OAUTH_HTTP_ENABLED": "false",
            "NOVA_STRIPE_LIVE_ENABLED": "false",
            "NOVA_GA_CREDENTIAL_ENCRYPTION_KEY": Fernet.generate_key().decode(),
            "DB_POOL_SIZE": "2",
            "DB_MAX_OVERFLOW": "1",
        }
    )
    # Intentionally omit Google OAuth client secrets and Twilio auth token.
    for k in (
        "NOVA_GA_GOOGLE_OAUTH_CLIENT_ID",
        "NOVA_GA_GOOGLE_OAUTH_CLIENT_SECRET",
        "TWILIO_AUTH_TOKEN",
    ):
        app_env.pop(k, None)

    proc = subprocess.Popen(
        [
            sys.executable,
            "-m",
            "uvicorn",
            "app.main:app",
            "--host",
            "127.0.0.1",
            "--port",
            str(args.port),
        ],
        cwd=str(backend),
        env=app_env,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
    )
    base = f"http://127.0.0.1:{args.port}"
    try:
        readiness = _wait_readiness(base)
        evidence["readiness"] = readiness
        if readiness.get("http_status") != 200:
            raise SystemExit(f"readiness not 200: {readiness}")
        if not readiness.get("traffic_ready"):
            raise SystemExit(f"traffic_ready false: {readiness}")
        evidence["passed"] = True
    finally:
        proc.send_signal(signal.SIGTERM)
        try:
            proc.wait(timeout=15)
        except subprocess.TimeoutExpired:
            proc.kill()
        out_tail = ""
        if proc.stdout:
            try:
                out_tail = proc.stdout.read()[-1500:]
            except Exception:
                out_tail = ""
        evidence["uvicorn_tail"] = out_tail

    evidence["finished_at_utc"] = datetime.now(UTC).isoformat()
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(evidence, indent=2) + "\n")
    print(json.dumps({"passed": evidence.get("passed"), "out": str(out_path)}, indent=2))
    return 0 if evidence.get("passed") else 1


if __name__ == "__main__":
    raise SystemExit(main())
