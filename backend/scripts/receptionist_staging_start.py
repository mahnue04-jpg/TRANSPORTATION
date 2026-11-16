#!/usr/bin/env python3
"""Guarded migrate-then-exec for free-plan Nova receptionist staging.

Render free web services do not support ``preDeployCommand``. ``releaseCommand``
is not a valid Blueprint field. Official free-plan guidance is to run an
idempotent migration step inside ``startCommand`` before the app process.

This script:
1. Refuses SQLite, production hosts, and the existing Growth staging DB.
2. Optionally enforces expected git SHA / database name / Alembic revision.
3. Takes a PostgreSQL advisory lock so concurrent cold starts cannot race DDL.
4. Runs ``alembic upgrade`` to the approved receptionist revision only.
5. Verifies the resulting revision, then ``exec``s uvicorn.

Migration failure exits non-zero. There is no SQLite or ORM ``create_all`` fallback.
"""

from __future__ import annotations

import os
import subprocess
import sys
import time
from pathlib import Path
from urllib.parse import urlparse

TARGET_REVISION = "20261116_nova_ga_receptionist"
DEFAULT_EXPECTED_DB = "nova_ga_receptionist_dispos"
LOCK_KEY = 0x4E4F5641474152  # "NOVAGAR" truncated
LOCK_WAIT_SECONDS = 120


def _die(message: str, code: int = 1) -> None:
    print(f"[receptionist-staging-start] FATAL: {message}", file=sys.stderr, flush=True)
    raise SystemExit(code)


def _env(name: str, default: str = "") -> str:
    return (os.environ.get(name) or default).strip()


def _database_url() -> str:
    url = _env("ALEMBIC_DATABASE_URL") or _env("DATABASE_URL")
    if not url:
        _die("DATABASE_URL / ALEMBIC_DATABASE_URL is required")
    return url


def _assert_safe_database(url: str) -> str:
    lowered = url.lower()
    if "sqlite" in lowered:
        _die("Refusing SQLite DATABASE_URL — staging requires PostgreSQL")
    parsed = urlparse(url.replace("postgresql+psycopg2://", "postgresql://", 1))
    host = (parsed.hostname or "").lower()
    dbname = (parsed.path or "").lstrip("/").lower()
    if any(tok in host for tok in ("amicor-health-isf", "production", "prod.")):
        _die(f"Refusing non-staging host: {host}")
    if "490" in dbname or dbname in {"nova_ga_490_dispos"}:
        _die(f"Refusing existing Growth staging database: {dbname}")
    expected_db = _env("NOVA_GA_EXPECTED_DATABASE_NAME", DEFAULT_EXPECTED_DB).lower()
    if expected_db and dbname != expected_db:
        _die(f"Database name {dbname!r} does not match expected {expected_db!r}")
    if not dbname:
        _die("DATABASE_URL is missing a database name")
    return dbname


def _assert_commit_guard() -> None:
    expected = _env("NOVA_GA_EXPECTED_GIT_COMMIT")
    if not expected:
        return
    actual = _env("RENDER_GIT_COMMIT") or _env("GIT_COMMIT")
    if not actual:
        _die(
            "NOVA_GA_EXPECTED_GIT_COMMIT is set but RENDER_GIT_COMMIT/GIT_COMMIT is missing"
        )
    if not (
        actual == expected
        or actual.startswith(expected)
        or expected.startswith(actual)
    ):
        _die(f"Deploy commit {actual} does not match expected {expected}")


def _backend_dir() -> Path:
    return Path(__file__).resolve().parents[1]


def _psycopg_url(url: str) -> str:
    if url.startswith("postgresql+psycopg2://"):
        return "postgresql://" + url[len("postgresql+psycopg2://") :]
    return url


def _with_advisory_lock(url: str, fn) -> None:
    try:
        import psycopg2
    except ImportError as exc:
        _die(f"psycopg2 required for migrate lock: {exc}")

    conn = psycopg2.connect(_psycopg_url(url))
    conn.autocommit = True
    cur = conn.cursor()
    deadline = time.time() + LOCK_WAIT_SECONDS
    locked = False
    try:
        while time.time() < deadline:
            cur.execute("SELECT pg_try_advisory_lock(%s)", (LOCK_KEY,))
            locked = bool(cur.fetchone()[0])
            if locked:
                break
            time.sleep(1.0)
        if not locked:
            _die(f"Could not acquire migration advisory lock within {LOCK_WAIT_SECONDS}s")
        fn()
    finally:
        if locked:
            try:
                cur.execute("SELECT pg_advisory_unlock(%s)", (LOCK_KEY,))
            except Exception:
                pass
        cur.close()
        conn.close()


def _run_alembic(backend: Path, url: str) -> None:
    env = os.environ.copy()
    env["ALEMBIC_DATABASE_URL"] = url
    env["DATABASE_URL"] = url
    # Keep Alembic env from defaulting into a local SQLite fallback path.
    env.pop("SQLALCHEMY_DATABASE_URI", None)
    cmd = [sys.executable, "-m", "alembic", "upgrade", TARGET_REVISION]
    print(f"[receptionist-staging-start] + {' '.join(cmd)}", flush=True)
    completed = subprocess.run(cmd, cwd=str(backend), env=env, check=False)
    if completed.returncode != 0:
        _die(f"alembic upgrade {TARGET_REVISION} failed with exit {completed.returncode}")


def _verify_revision(backend: Path, url: str) -> str:
    env = os.environ.copy()
    env["ALEMBIC_DATABASE_URL"] = url
    env["DATABASE_URL"] = url
    completed = subprocess.run(
        [sys.executable, "-m", "alembic", "current"],
        cwd=str(backend),
        env=env,
        check=False,
        capture_output=True,
        text=True,
    )
    if completed.returncode != 0:
        _die(
            "alembic current failed after upgrade: "
            + (completed.stderr or completed.stdout or "")[-500:]
        )
    output = (completed.stdout or "") + (completed.stderr or "")
    expected = _env("NOVA_GA_EXPECTED_ALEMBIC_REVISION", TARGET_REVISION)
    if expected not in output:
        _die(f"Expected Alembic revision {expected} not current. Output:\n{output[-800:]}")
    print(f"[receptionist-staging-start] revision verified: {expected}", flush=True)
    return expected


def migrate_only() -> str:
    """Apply and verify migrations; used by rehearsals and startCommand."""
    url = _database_url()
    dbname = _assert_safe_database(url)
    _assert_commit_guard()
    backend = _backend_dir()
    print(
        f"[receptionist-staging-start] migrating {dbname} → {TARGET_REVISION}",
        flush=True,
    )

    def _locked_migrate() -> None:
        _run_alembic(backend, url)
        _verify_revision(backend, url)

    _with_advisory_lock(url, _locked_migrate)
    return TARGET_REVISION


def _exec_uvicorn() -> None:
    port = _env("PORT", "8000")
    args = [
        sys.executable,
        "-m",
        "uvicorn",
        "app.main:app",
        "--host",
        "0.0.0.0",
        "--port",
        port,
    ]
    print(f"[receptionist-staging-start] exec {' '.join(args)}", flush=True)
    os.chdir(str(_backend_dir()))
    os.execvp(args[0], args)


def main(argv: list[str] | None = None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    migrate_only_flag = "--migrate-only" in argv
    migrate_only()
    if migrate_only_flag:
        return 0
    _exec_uvicorn()
    return 0  # unreachable after exec


if __name__ == "__main__":
    raise SystemExit(main())
