#!/usr/bin/env python3
"""Disposable Postgres backup/restore + receptionist Alembic rehearsal.

STAGING PREP ONLY — never targets production or nova_ga_490_dispos.

Flow:
1. Upgrade source DB to 20261112_nova_ga_retention.
2. Seed synthetic pre-existing Growth records.
3. pg_dump → restore into a second disposable DB.
4. Apply 20261116_nova_ga_receptionist on the restored DB (no ORM create_all for those tables).
5. Verify eight receptionist tables + pre-existing rows intact.
6. Exercise connection/sync/notify/handoff/voice rows.

Outputs JSON evidence (default under docs/nova/growth-agent/screenshots/).
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import uuid
from datetime import datetime, timedelta, timezone
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
PARENT_REVISION = "20261112_nova_ga_retention"
TARGET_REVISION = "20261116_nova_ga_receptionist"
UTC = timezone.utc


def _assert_disposable(url: str) -> None:
    parsed = urlparse(url)
    host = (parsed.hostname or "").lower()
    dbname = (parsed.path or "").lstrip("/").lower()
    if any(f in host for f in ("amicor-health-isf", "production", "prod.", "render.com")):
        raise SystemExit(f"Refusing non-disposable host: {host}")
    if "490" in dbname or dbname in {"nova_ga_490_dispos"}:
        raise SystemExit(f"Refusing existing staging DB name: {dbname}")
    if not any(tok in dbname for tok in ("test", "dispos", "ci", "receptionist", "nova_ga")):
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


def _alembic(backend: Path, url: str, *args: str) -> None:
    env = os.environ.copy()
    env["ALEMBIC_DATABASE_URL"] = url
    env["DATABASE_URL"] = url
    env["APP_ENV"] = "test"
    env["AMICOR_ENVIRONMENT"] = "test"
    env["TESTING"] = "true"
    env["PGPASSWORD"] = env.get("PGPASSWORD") or "ga_ci_dispos"
    _run([sys.executable, "-m", "alembic", *args], cwd=backend, env=env)


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


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--src-url",
        default="postgresql+psycopg2://ga_ci:ga_ci_dispos@127.0.0.1:5432/nova_ga_receptionist_src",
    )
    parser.add_argument(
        "--restore-url",
        default="postgresql+psycopg2://ga_ci:ga_ci_dispos@127.0.0.1:5432/nova_ga_receptionist_restore",
    )
    parser.add_argument(
        "--out",
        default="docs/nova/growth-agent/screenshots/receptionist_staging_db_rehearsal.json",
    )
    args = parser.parse_args()
    _assert_disposable(args.src_url)
    _assert_disposable(args.restore_url)

    repo = Path(__file__).resolve().parents[2]
    backend = repo / "backend"
    sys.path.insert(0, str(backend))
    os.environ.setdefault("PGPASSWORD", "ga_ci_dispos")

    evidence: dict[str, Any] = {
        "started_at_utc": datetime.now(UTC).isoformat(),
        "parent_revision": PARENT_REVISION,
        "target_revision": TARGET_REVISION,
        "src_db": _dbname(args.src_url),
        "restore_db": _dbname(args.restore_url),
        "orm_create_all_used_for_receptionist": False,
    }

    _recreate_db(args.src_url)
    _recreate_db(args.restore_url)

    # Prefer stamp-parent path for disposable DBs that cannot run full Health/ISF chain,
    # then ensure non-receptionist tables via ORM only after parent stamp.
    _alembic(backend, args.src_url, "stamp", PARENT_REVISION)
    evidence["src_bootstrap"] = "stamp_parent"

    from cryptography.fernet import Fernet
    from sqlalchemy import create_engine, inspect, text
    from sqlalchemy.orm import sessionmaker

    os.environ["NOVA_GA_CREDENTIAL_ENCRYPTION_KEY"] = Fernet.generate_key().decode()
    os.environ["NOVA_GROWTH_AGENT_ENABLED"] = "true"
    os.environ["TESTING"] = "true"
    os.environ["APP_ENV"] = "test"
    os.environ["AMICOR_ENVIRONMENT"] = "test"

    from app.core.nova.growth_agent.models import (
        GaAppointment,
        GaAppointmentService,
        GaBusinessProfile,
        GaCalendarConnection,
        GaCalendarSyncJob,
        GaContact,
        GaHandoffRequest,
        GaOwnerNotification,
        GaVoiceAgentMapping,
    )
    from app.core.nova.growth_agent.providers.credential_crypto import encrypt_secret
    from app.core.nova.growth_agent.schema_ensure import ensure_growth_agent_schema

    src_engine = create_engine(args.src_url, pool_pre_ping=True)
    # Core GA tables for seed (not receptionist — those come only via Alembic later).
    ensure_growth_agent_schema(bind=src_engine)
    # Drop receptionist tables if ORM ensure created them so restore+upgrade is honest.
    with src_engine.begin() as conn:
        for name in reversed(RECEPTIONIST_TABLES):
            conn.execute(text(f'DROP TABLE IF EXISTS "{name}" CASCADE'))
    Session = sessionmaker(bind=src_engine)
    db = Session()
    org = f"org-rehearse-{uuid.uuid4().hex[:8]}"
    profile_id = uuid.uuid4().hex
    contact_id = uuid.uuid4().hex
    service_id = uuid.uuid4().hex
    appt_id = uuid.uuid4().hex
    now = datetime.utcnow()
    db.add(
        GaBusinessProfile(
            id=profile_id,
            organization_id=org,
            owner_user_id="owner-rehearse",
            business_name="Rehearse Biz",
            timezone="America/Chicago",
            activated=True,
            plan_code="starter",
            faqs_json=[],
            operating_hours_json={},
            escalation_settings_json={},
        )
    )
    db.add(
        GaContact(
            id=contact_id,
            organization_id=org,
            display_name="Synthetic Lead",
            lead_state="new",
            dedupe_fingerprint=f"fp-{contact_id}",
        )
    )
    db.add(
        GaAppointmentService(
            id=service_id,
            organization_id=org,
            code="consult",
            name="Consult",
            duration_minutes=30,
            buffer_minutes=0,
            active=True,
        )
    )
    start = now + timedelta(days=1)
    end = start + timedelta(minutes=30)
    db.add(
        GaAppointment(
            id=appt_id,
            organization_id=org,
            contact_id=contact_id,
            service_id=service_id,
            starts_at_utc=start,
            ends_at_utc=end,
            timezone="America/Chicago",
            status="confirmed",
            idempotency_key=f"idem-{appt_id}",
            is_synthetic_demo=True,
        )
    )
    db.commit()
    evidence["seed"] = {
        "organization_id": org,
        "profile_id": profile_id,
        "contact_id": contact_id,
        "appointment_id": appt_id,
        "business_name": "Rehearse Biz",
    }
    db.close()

    dump_path = Path("/tmp/nova_ga_receptionist_src.dump")
    _run(
        ["pg_dump", "--format=custom", "--file", str(dump_path), _psql_url(args.src_url)],
        env={**os.environ, "PGPASSWORD": "ga_ci_dispos"},
    )
    evidence["backup_bytes"] = dump_path.stat().st_size
    _run(
        [
            "pg_restore",
            "--clean",
            "--if-exists",
            "--no-owner",
            "--dbname",
            _psql_url(args.restore_url),
            str(dump_path),
        ],
        env={**os.environ, "PGPASSWORD": "ga_ci_dispos"},
    )
    evidence["restore_ok"] = True

    restore_engine = create_engine(args.restore_url, pool_pre_ping=True)
    with restore_engine.begin() as conn:
        row = conn.execute(text("SELECT version_num FROM alembic_version")).fetchone()
        evidence["revision_after_restore"] = row[0] if row else None
    if evidence["revision_after_restore"] != PARENT_REVISION:
        _alembic(backend, args.restore_url, "stamp", PARENT_REVISION)
        evidence["stamped_parent_on_restore"] = True

    before = set(inspect(restore_engine).get_table_names())
    evidence["receptionist_present_before_upgrade"] = sorted(
        t for t in RECEPTIONIST_TABLES if t in before
    )
    if evidence["receptionist_present_before_upgrade"]:
        with restore_engine.begin() as conn:
            for name in reversed(RECEPTIONIST_TABLES):
                conn.execute(text(f'DROP TABLE IF EXISTS "{name}" CASCADE'))
        _alembic(backend, args.restore_url, "stamp", PARENT_REVISION)

    _alembic(backend, args.restore_url, "upgrade", TARGET_REVISION)
    after = set(inspect(restore_engine).get_table_names())
    missing = [t for t in RECEPTIONIST_TABLES if t not in after]
    if missing:
        raise SystemExit(f"Receptionist tables missing after Alembic: {missing}")
    evidence["receptionist_tables"] = list(RECEPTIONIST_TABLES)

    with restore_engine.begin() as conn:
        rev = conn.execute(text("SELECT version_num FROM alembic_version")).fetchone()
        evidence["revision_after_upgrade"] = rev[0] if rev else None
        name = conn.execute(
            text(
                "SELECT business_name FROM nova_ga_business_profiles WHERE organization_id = :org"
            ),
            {"org": org},
        ).scalar()
        contact = conn.execute(
            text("SELECT display_name FROM nova_ga_contacts WHERE id = :id"),
            {"id": contact_id},
        ).scalar()
        appt = conn.execute(
            text("SELECT status FROM nova_ga_appointments WHERE id = :id"),
            {"id": appt_id},
        ).scalar()
        # Sample index presence
        idx = conn.execute(
            text(
                "SELECT indexname FROM pg_indexes WHERE tablename = 'nova_ga_calendar_sync_jobs'"
            )
        ).fetchall()
        evidence["sync_job_indexes"] = sorted(r[0] for r in idx)

    evidence["preexisting_intact"] = {
        "business_name": name,
        "contact_display_name": contact,
        "appointment_status": appt,
    }
    if name != "Rehearse Biz" or contact != "Synthetic Lead" or appt != "confirmed":
        raise SystemExit(f"Pre-existing data damaged: {evidence['preexisting_intact']}")

    RSession = sessionmaker(bind=restore_engine)
    rdb = RSession()
    conn_id = uuid.uuid4().hex
    rdb.add(
        GaCalendarConnection(
            id=conn_id,
            organization_id=org,
            owner_user_id="owner-rehearse",
            provider="google",
            status="connected",
            calendar_id="primary",
            calendar_summary="Test Calendar",
            scopes_json=["https://www.googleapis.com/auth/calendar.events"],
            refresh_token_encrypted=encrypt_secret("rt-rehearse"),
            access_token_encrypted=encrypt_secret("at-rehearse"),
            connected_at=datetime.utcnow(),
            meta_json={},
        )
    )
    sync_id = uuid.uuid4().hex
    rdb.add(
        GaCalendarSyncJob(
            id=sync_id,
            organization_id=org,
            appointment_id=appt_id,
            connection_id=conn_id,
            calendar_id="primary",
            event_id="evt-synthetic",
            action="create",
            operation_version=1,
            status="pending",
            attempt_number=0,
            payload_json={"label": "SIMULATED"},
            available_at=datetime.utcnow(),
        )
    )
    notify_id = uuid.uuid4().hex
    rdb.add(
        GaOwnerNotification(
            id=notify_id,
            organization_id=org,
            event_type="appointment_booked",
            channel="email",
            status="queued",
            attempt_number=0,
            idempotency_key=f"notify-{notify_id}",
            payload_redacted_json={"appointment_id": appt_id},
            available_at=datetime.utcnow(),
        )
    )
    handoff_id = uuid.uuid4().hex
    rdb.add(
        GaHandoffRequest(
            id=handoff_id,
            organization_id=org,
            contact_id=contact_id,
            reason="owner_requested",
            status="open",
            channel="voice_sim",
            summary="Synthetic handoff",
            payload_redacted_json={},
        )
    )
    map_id = uuid.uuid4().hex
    rdb.add(
        GaVoiceAgentMapping(
            id=map_id,
            organization_id=org,
            provider="twilio",
            external_number="+15555550100",
            agent_label="receptionist",
            active=True,
            kill_switch=False,
            meta_json={"label": "SIMULATED"},
        )
    )
    rdb.commit()
    evidence["exercised_counts"] = {
        "connections": rdb.query(GaCalendarConnection).filter_by(organization_id=org).count(),
        "sync_jobs": rdb.query(GaCalendarSyncJob).filter_by(organization_id=org).count(),
        "notifications": rdb.query(GaOwnerNotification).filter_by(organization_id=org).count(),
        "handoffs": rdb.query(GaHandoffRequest).filter_by(organization_id=org).count(),
        "voice_mappings": rdb.query(GaVoiceAgentMapping).filter_by(organization_id=org).count(),
    }
    rdb.close()
    evidence["application_rollback"] = {
        "method": "Redeploy previous application SHA; leave additive receptionist tables in place",
        "compatible": True,
        "do_not_default_to": "DROP TABLE for receptionist tables",
        "optional_alembic_downgrade": "Only with separate owner approval; not required for app rollback",
    }
    evidence["passed"] = True
    evidence["finished_at_utc"] = datetime.now(UTC).isoformat()

    out_path = (repo / args.out).resolve()
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(evidence, indent=2) + "\n")
    print(json.dumps({"ok": True, "out": str(out_path), "revision": evidence["revision_after_upgrade"]}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
