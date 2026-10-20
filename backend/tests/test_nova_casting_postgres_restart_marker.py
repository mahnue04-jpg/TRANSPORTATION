"""Postgres restart proof is a different instance id, not an idle wake.

The marker row is safe to store. It has no password, token, or connection
string. The first writer and the same boot id leave the owner gate closed.
"""
from __future__ import annotations

import inspect
import json
import os
import subprocess
import sys
from pathlib import Path

from sqlalchemy import create_engine, text

from app.auth import deployment_seed_status, signin_gate_from_store
from app.db.session import apply_auth_restart_marker

BACKEND = Path(__file__).resolve().parents[1]


def _engine(tmp_path: Path):
    return create_engine(f"sqlite:///{tmp_path / 'marker.db'}")


def _gate(restart_observed: bool, *, signing: str = "env", location: str = "postgres", durable: bool = True):
    return signin_gate_from_store(
        {
            "durable": durable,
            "restart_observed": restart_observed,
            "location": location,
        },
        signing,
    )


def test_first_and_same_boot_stay_closed_until_a_different_id(tmp_path: Path) -> None:
    first = _engine(tmp_path)
    assert apply_auth_restart_marker(first, "boot-a") is False
    assert _gate(False)["owner_retry_allowed"] is False
    assert _gate(False)["blocked_reason"] == "restart survival has not been observed on this store"
    first.dispose()

    second = _engine(tmp_path)
    assert apply_auth_restart_marker(second, "boot-a") is False
    assert _gate(False)["owner_retry_allowed"] is False
    assert apply_auth_restart_marker(second, "   ") is False
    assert apply_auth_restart_marker(second, "x" * 129) is False
    assert apply_auth_restart_marker(second, "boot-b") is True
    opened = _gate(True)
    assert opened["owner_retry_allowed"] is True
    assert opened["blocked_reason"] == ""
    assert _gate(True, signing="ephemeral")["owner_retry_allowed"] is False
    assert _gate(True, location="workspace", durable=False)["owner_retry_allowed"] is False
    second.dispose()

    third = _engine(tmp_path)
    assert apply_auth_restart_marker(third, "boot-b") is False
    with third.connect() as connection:
        row = connection.execute(text(
            "SELECT instance_id, marker_kind FROM amicor_auth_restart_marker WHERE id = 1"
        )).one()
    assert row[0] == "boot-b"
    assert row[1] == "instance"


def test_blank_or_non_instance_marker_is_not_proof(tmp_path: Path) -> None:
    engine = _engine(tmp_path)
    with engine.begin() as connection:
        connection.execute(text(
            "CREATE TABLE amicor_auth_restart_marker ("
            "id INTEGER PRIMARY KEY, instance_id TEXT NOT NULL, marker_kind TEXT NOT NULL)"
        ))
        connection.execute(text(
            "INSERT INTO amicor_auth_restart_marker (id, instance_id, marker_kind) "
            "VALUES (1, '', 'other')"
        ))
    assert apply_auth_restart_marker(engine, "boot-c") is False
    assert _gate(False)["owner_retry_allowed"] is False
    assert apply_auth_restart_marker(engine, "boot-d") is True
    assert _gate(True)["owner_retry_allowed"] is True


def test_seed_status_observes_the_marker_before_the_gate() -> None:
    source = inspect.getsource(deployment_seed_status)
    assert source.index("observe_postgres_restart_marker") < source.index("owner_signin_gate")


def test_unreachable_postgres_does_not_open_or_cache_the_gate() -> None:
    env = os.environ.copy()
    for name in (
        "DATABASE_URL",
        "DB_FILENAME",
        "JWT_SECRET",
        "SECRET_KEY",
        "AMICOR_AUTH_STORE_DIR",
        "AMICOR_AUTH_DISK_DIR",
        "AMICOR_AUTH_BOOT_ID",
        "RENDER_INSTANCE_ID",
    ):
        env.pop(name, None)
    env["DATABASE_URL"] = "postgresql://preview_unused:unused@127.0.0.1:1/preview_unused"
    env["JWT_SECRET"] = "staging-marker-test-only"
    env["AMICOR_AUTH_BOOT_ID"] = "boot-unreachable"
    env["TESTING"] = "true"
    env["PYTHONPATH"] = str(BACKEND)
    completed = subprocess.run(
        [sys.executable, str(Path(__file__).resolve()), "unreachable"],
        cwd=str(BACKEND),
        env=env,
        text=True,
        capture_output=True,
        timeout=20,
        check=False,
    )
    if completed.returncode != 0:
        tail = (completed.stderr or completed.stdout or "")[-2000:]
        raise AssertionError(f"unreachable marker child failed: {tail}")
    lines = [line for line in completed.stdout.splitlines() if line.startswith("{")]
    assert lines, completed.stdout[-500:]
    payload = json.loads(lines[-1])
    assert "preview_unused" not in json.dumps(payload)
    assert payload["observed"] is False
    assert payload["again"] is False
    assert payload["restart_observed"] is False
    assert payload["owner_retry_allowed"] is False
    assert payload["blocked_reason"] == "restart survival has not been observed on this store"
    assert payload["location"] == "postgres"


if __name__ == "__main__":
    if sys.argv[1] == "unreachable":
        from app.auth import owner_signin_gate
        from app.db.session import auth_store_metadata, observe_postgres_restart_marker

        observed = observe_postgres_restart_marker()
        again = observe_postgres_restart_marker()
        store = auth_store_metadata()
        gate = owner_signin_gate()
        print(json.dumps({
            "observed": observed,
            "again": again,
            "restart_observed": store.get("restart_observed"),
            "owner_retry_allowed": gate.get("owner_retry_allowed"),
            "blocked_reason": gate.get("blocked_reason"),
            "location": store.get("location"),
        }))
