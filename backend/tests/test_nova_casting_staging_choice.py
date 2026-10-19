"""No-cost staging choices stay closed. These tests do not connect or provision."""
from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

from app.core.casting_staging_choice import (
    ACCEPTANCE_STAGES,
    PREVIEW_WEB_SERVICE,
    VERIFIED_STAGING_DATABASE,
    decide_preview_database_link,
    decide_staging_store,
)
from app.db.session import _classify_db_connection_error

BACKEND = Path(__file__).resolve().parents[1]


def test_acceptance_stages_keep_retry_intake_and_outbound_closed() -> None:
    assert [item["stage"] for item in ACCEPTANCE_STAGES] == [0, 1, 2, 3, 4]
    assert ACCEPTANCE_STAGES[0]["executable_without_owner"] is True
    for stage in ACCEPTANCE_STAGES:
        assert stage["owner_retry_allowed"] is False
        assert stage["spend_usd"] == 0
        assert stage["public_intake"] is False
        assert stage["outbound"] is False
        assert stage["copies_accounts"] is False
    assert ACCEPTANCE_STAGES[1]["dashboard_read_only"] is True
    assert ACCEPTANCE_STAGES[2]["requires_free_slot_empty"] is True
    assert ACCEPTANCE_STAGES[3]["save_mode"] == "save-only"
    assert ACCEPTANCE_STAGES[3]["database_id"] == "dpg-dbap057btjjs7381egmg-a"
    assert ACCEPTANCE_STAGES[3]["service_id"] == "srv-db7r3ke7bikc73ddosmg"
    assert ACCEPTANCE_STAGES[4]["uses_owner_password"] is False


def test_paid_and_production_choices_are_refused() -> None:
    refused = [
        decide_staging_store("resume_suspended"),
        decide_staging_store("upgrade_suspended_free"),
        decide_staging_store("create_paid_postgres"),
        decide_staging_store("attach_disk"),
        decide_staging_store("attach_production", database_name="amicor-health-isf-db"),
        decide_staging_store("create_empty_free", database_name="amicor-nova-db", free_postgres_active=False),
        decide_staging_store("copy_database", database_name="casting-preview-empty", free_postgres_active=False),
        decide_staging_store(
            "create_empty_free",
            database_name="casting-preview-empty",
            free_postgres_active=False,
            copy_requested=True,
        ),
    ]
    assert all(item["allowed_now"] is False for item in refused)
    assert all(item["owner_retry_allowed"] is False for item in refused)
    assert all(item["provisioned"] is False for item in refused)
    assert all(item["copies_accounts"] is False for item in refused)
    assert refused[0]["monthly_usd"] == 6
    assert refused[1]["monthly_usd"] == 6
    assert refused[2]["monthly_usd"] == 6
    assert refused[3]["monthly_usd"] == 7.25


def test_empty_free_database_needs_a_verified_open_slot() -> None:
    unknown = decide_staging_store(
        "create_empty_free",
        database_name="casting-preview-empty",
        free_postgres_active=None,
    )
    occupied = decide_staging_store(
        "create_empty_free",
        database_name="casting-preview-empty",
        free_postgres_active=True,
    )
    empty = decide_staging_store(
        "create_empty_free",
        database_name="casting-preview-empty",
        free_postgres_active=False,
    )
    assert unknown["allowed_now"] is False
    assert occupied["allowed_now"] is False
    assert empty["allowed_now"] is True
    assert empty["monthly_usd"] == 0
    assert empty["owner_retry_allowed"] is False
    assert empty["provisioned"] is False
    assert empty["copies_accounts"] is False


def test_inspection_and_ephemeral_preview_cost_nothing() -> None:
    keep = decide_staging_store("keep_ephemeral")
    look = decide_staging_store("inspect_suspended_free", database_name="unverified-suspended-db")
    assert keep["allowed_now"] is True
    assert look["allowed_now"] is True
    assert keep["monthly_usd"] == 0
    assert look["monthly_usd"] == 0
    assert keep["owner_retry_allowed"] is False
    assert look["durable"] is False


def test_suspended_postgres_message_is_classified_without_connecting() -> None:
    category = _classify_db_connection_error(ConnectionError("connection refused"))
    assert category == "missing_or_suspended_postgresql_service"


def test_verified_preview_link_stays_save_only_and_stores_no_uri() -> None:
    linked = decide_preview_database_link(
        database_id=VERIFIED_STAGING_DATABASE["id"],
        database_name=VERIFIED_STAGING_DATABASE["name"],
        service_id=PREVIEW_WEB_SERVICE["id"],
        service_name=PREVIEW_WEB_SERVICE["name"],
        plan="free",
        region="virginia",
        status="available",
    )
    assert linked["allowed_now"] is True
    assert linked["executable_without_owner"] is False
    assert linked["agent_can_store_reference"] is False
    assert linked["monthly_usd"] == 0
    assert linked["owner_retry_allowed"] is False
    assert linked["provisioned"] is False
    assert linked["schema_initialized"] is False
    assert linked["public_intake"] is False
    assert linked["outbound"] is False
    assert linked["media_uploads"] is False
    assert linked["copies_accounts"] is False
    assert linked["save_mode"] == "save-only"
    assert linked["database_id"] == "dpg-dbap057btjjs7381egmg-a"
    assert linked["service_id"] == "srv-db7r3ke7bikc73ddosmg"
    rendered = json.dumps(linked)
    assert "postgres://" not in rendered
    assert "postgresql://" not in rendered
    assert "password" not in rendered

    secret = "connection-string-must-not-be-stored"
    refused_secret = decide_preview_database_link(
        database_id=VERIFIED_STAGING_DATABASE["id"],
        database_name=VERIFIED_STAGING_DATABASE["name"],
        service_id=PREVIEW_WEB_SERVICE["id"],
        service_name=PREVIEW_WEB_SERVICE["name"],
        connection_string=secret,
    )
    assert refused_secret["allowed_now"] is False
    assert refused_secret["owner_retry_allowed"] is False
    assert secret not in json.dumps(refused_secret)

    refused = [
        decide_preview_database_link(
            database_id="dpg-production",
            database_name="amicor-health-isf-db",
            service_id=PREVIEW_WEB_SERVICE["id"],
            service_name=PREVIEW_WEB_SERVICE["name"],
        ),
        decide_preview_database_link(
            database_id=VERIFIED_STAGING_DATABASE["id"],
            database_name=VERIFIED_STAGING_DATABASE["name"],
            service_id="srv-production",
            service_name="amicor-health-isf-py",
        ),
        decide_preview_database_link(
            database_id=VERIFIED_STAGING_DATABASE["id"],
            database_name=VERIFIED_STAGING_DATABASE["name"],
            service_id=PREVIEW_WEB_SERVICE["id"],
            service_name=PREVIEW_WEB_SERVICE["name"],
            plan="0.1c-256mb",
        ),
        decide_preview_database_link(
            database_id=VERIFIED_STAGING_DATABASE["id"],
            database_name=VERIFIED_STAGING_DATABASE["name"],
            service_id=PREVIEW_WEB_SERVICE["id"],
            service_name=PREVIEW_WEB_SERVICE["name"],
            deploy_requested=True,
        ),
        decide_preview_database_link(
            database_id=VERIFIED_STAGING_DATABASE["id"],
            database_name=VERIFIED_STAGING_DATABASE["name"],
            service_id=PREVIEW_WEB_SERVICE["id"],
            service_name=PREVIEW_WEB_SERVICE["name"],
            status="creating",
        ),
        decide_staging_store(
            "link_verified_preview_database",
            database_name=VERIFIED_STAGING_DATABASE["name"],
        ),
    ]
    assert all(item["allowed_now"] is False for item in refused)
    assert all(item["owner_retry_allowed"] is False for item in refused)
    assert refused[2]["monthly_usd"] == 6


def test_postgres_url_keeps_the_owner_retry_gate_closed() -> None:
    with_secret = _gate_child(jwt_secret="staging-choice-test-only")
    without_secret = _gate_child(jwt_secret="")
    assert with_secret["backend"] == "postgres"
    assert with_secret["durable"] is True
    assert with_secret["location"] == "postgres"
    assert with_secret["restart_observed"] is False
    assert with_secret["signing_key"] == "env"
    assert with_secret["owner_retry_allowed"] is False
    assert with_secret["blocked_reason"] == "restart survival has not been observed on this store"
    assert without_secret["signing_key"] == "ephemeral"
    assert without_secret["owner_retry_allowed"] is False
    assert without_secret["blocked_reason"] == "signing key is ephemeral"


def _gate_child(*, jwt_secret: str) -> dict:
    env = os.environ.copy()
    for name in (
        "DATABASE_URL",
        "DB_FILENAME",
        "JWT_SECRET",
        "SECRET_KEY",
        "AMICOR_AUTH_STORE_DIR",
        "AMICOR_AUTH_DISK_DIR",
        "AMICOR_SEED_PASSWORD",
    ):
        env.pop(name, None)
    env["DATABASE_URL"] = "postgresql://preview_unused:unused@127.0.0.1:1/preview_unused"
    if jwt_secret:
        env["JWT_SECRET"] = jwt_secret
    env["TESTING"] = "true"
    env["PYTHONPATH"] = str(BACKEND)
    completed = subprocess.run(
        [sys.executable, str(Path(__file__).resolve()), "postgres-gate"],
        cwd=str(BACKEND),
        env=env,
        text=True,
        capture_output=True,
        timeout=60,
        check=False,
    )
    if completed.returncode != 0:
        tail = (completed.stderr or completed.stdout or "")[-2000:]
        raise AssertionError(f"postgres gate child failed: {tail}")
    lines = [line for line in completed.stdout.splitlines() if line.startswith("{")]
    assert lines, completed.stdout[-500:]
    payload = json.loads(lines[-1])
    assert "preview_unused" not in json.dumps(payload)
    return payload


def _postgres_gate() -> dict:
    from app.auth import owner_signin_gate
    from app.db.session import auth_store_metadata

    store = auth_store_metadata()
    gate = owner_signin_gate()
    return {
        "backend": store.get("backend"),
        "durable": store.get("durable"),
        "location": store.get("location"),
        "restart_observed": store.get("restart_observed"),
        "signing_key": gate.get("signing_key"),
        "owner_retry_allowed": gate.get("owner_retry_allowed"),
        "blocked_reason": gate.get("blocked_reason"),
    }


if __name__ == "__main__":
    if sys.argv[1] == "postgres-gate":
        print(json.dumps(_postgres_gate()))
