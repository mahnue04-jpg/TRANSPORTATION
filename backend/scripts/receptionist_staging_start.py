#!/usr/bin/env python3
"""Guarded migrate-then-exec for free-plan Nova receptionist staging.

Render free web services do not support ``preDeployCommand``. ``releaseCommand``
is not a valid Blueprint field. Official free-plan guidance is to run an
idempotent migration step inside ``startCommand`` before the app process.

This script:
1. Requires an exact full 40-character hex git commit pin before any DB access.
2. Unifies ``DATABASE_URL`` and ``ALEMBIC_DATABASE_URL`` (rejects conflicts).
3. Refuses SQLite, production hosts, and the existing Growth staging DB.
4. Takes a PostgreSQL advisory lock so concurrent cold starts cannot race DDL.
5. Runs ``alembic upgrade`` to the approved receptionist revision only.
6. Verifies the resulting revision, then ``exec``s uvicorn with the same URL.

Migration failure exits non-zero. There is no SQLite or ORM ``create_all`` fallback.
"""

from __future__ import annotations

import faulthandler
import os
import re
import subprocess
import sys
import time
from pathlib import Path
from typing import Any
from urllib.parse import unquote, urlparse

TARGET_REVISION = "20261116_nova_ga_receptionist"
DEFAULT_EXPECTED_DB = "nova_ga_receptionist_dispos"
LOCK_KEY = 0x4E4F5641474152  # "NOVAGAR" truncated
LOCK_WAIT_SECONDS = 120
DB_CONNECT_TIMEOUT_SECONDS = 10
ALEMBIC_UPGRADE_TIMEOUT_SECONDS = 120
ALEMBIC_CURRENT_TIMEOUT_SECONDS = 30
STARTUP_TRACE_TIMEOUT_SECONDS = 180
_FULL_SHA = re.compile(r"^[0-9a-f]{40}$")
_SUPPORTED_SCHEMES = {
    "postgresql",
    "postgres",
    "postgresql+psycopg2",
    "postgresql+psycopg",
}
_BLOCKED_DATABASE_NAMES = frozenset(
    {
        "nova_ga_490_dispos",
        "amicor_health_isf",
        "amicor-health-isf",
        "production",
        "prod",
    }
)
_BLOCKED_HOSTS = frozenset(
    {
        "amicor-health-isf-db",
        "amicor-health-isf-db.oregon-postgres.render.com",
        "production",
        "prod",
    }
)


def _die(message: str, code: int = 1) -> None:
    print(f"[receptionist-staging-start] FATAL: {message}", file=sys.stderr, flush=True)
    raise SystemExit(code)


def _env(name: str, default: str = "") -> str:
    return (os.environ.get(name) or default).strip()


def _normalize_scheme(scheme: str) -> str:
    raw = (scheme or "").lower()
    if raw in {"postgres", "postgresql", "postgresql+psycopg2", "postgresql+psycopg"}:
        return "postgresql"
    return raw


def _parse_postgres_url(url: str) -> dict[str, Any]:
    """Parse a PostgreSQL URL into a credential-free destination identity."""
    raw = (url or "").strip()
    if not raw:
        _die("Database URL is empty")
    lowered = raw.lower()
    if lowered.startswith("sqlite:") or "sqlite" in lowered.split(":", 1)[0]:
        _die("Refusing SQLite DATABASE_URL — staging requires PostgreSQL")

    parsed = urlparse(raw)
    if parsed.scheme.lower() not in _SUPPORTED_SCHEMES:
        _die(f"Unsupported database URL scheme: {parsed.scheme or '(missing)'}")
    scheme = _normalize_scheme(parsed.scheme)

    host = (parsed.hostname or "").lower()
    if not host:
        _die("Database URL is missing a host")
    port = parsed.port or 5432
    dbname = unquote((parsed.path or "").lstrip("/").split("?", 1)[0]).lower()
    if not dbname:
        _die("Database URL is missing a database name")
    user = unquote(parsed.username or "")

    return {
        "scheme": scheme,
        "host": host,
        "port": int(port),
        "database": dbname,
        "user": user,
        # Credential-free identity for comparisons / logs.
        "identity": f"{scheme}://{host}:{int(port)}/{dbname}",
    }


def _assert_commit_guard() -> None:
    """Require exact full SHA equality before any database access."""
    expected = _env("NOVA_GA_EXPECTED_GIT_COMMIT").lower()
    actual = (_env("RENDER_GIT_COMMIT") or _env("GIT_COMMIT")).lower()

    if not expected:
        _die("NOVA_GA_EXPECTED_GIT_COMMIT is required (full 40-character hex SHA)")
    if not _FULL_SHA.match(expected):
        _die(
            "NOVA_GA_EXPECTED_GIT_COMMIT must be a full 40-character hexadecimal SHA "
            f"(got length {len(expected)})"
        )
    if not actual:
        _die("RENDER_GIT_COMMIT or GIT_COMMIT is required and must equal the expected SHA")
    if not _FULL_SHA.match(actual):
        _die(
            "RENDER_GIT_COMMIT/GIT_COMMIT must be a full 40-character hexadecimal SHA "
            f"(got length {len(actual)})"
        )
    if actual != expected:
        _die(f"Deploy commit mismatch: actual={actual} expected={expected}")


def _assert_destination_allowed(dest: dict[str, Any]) -> None:
    host = dest["host"]
    dbname = dest["database"]

    if dbname in _BLOCKED_DATABASE_NAMES or dbname == "nova_ga_490_dispos":
        _die(f"Refusing protected / existing Growth staging database: {dbname}")
    if "490" == dbname or dbname.endswith("_490_dispos") or dbname.startswith("nova_ga_490"):
        _die(f"Refusing protected Growth staging database: {dbname}")

    if host in _BLOCKED_HOSTS:
        _die(f"Refusing protected / production database host: {host}")
    # Exact DNS labels that mark production Health ISF — not substring search on arbitrary hosts.
    host_labels = set(host.split("."))
    if "amicor-health-isf-db" in host_labels or host == "amicor-health-isf-db":
        _die(f"Refusing production Health ISF database host: {host}")
    if host in {"production", "prod"} or host.startswith("prod."):
        _die(f"Refusing production-like database host: {host}")

    expected_db = _env("NOVA_GA_EXPECTED_DATABASE_NAME", DEFAULT_EXPECTED_DB).lower()
    if not expected_db:
        _die("NOVA_GA_EXPECTED_DATABASE_NAME is required")
    if dbname != expected_db:
        _die(f"Database name {dbname!r} does not match expected {expected_db!r}")

    expected_host = _env("NOVA_GA_EXPECTED_DATABASE_HOST").lower()
    if expected_host and host != expected_host:
        _die(f"Database host {host!r} does not match expected {expected_host!r}")


def resolve_approved_database_url() -> tuple[str, dict[str, Any]]:
    """Unify Alembic + app URLs; reject conflicts; return approved URL + destination."""
    alembic_url = _env("ALEMBIC_DATABASE_URL")
    database_url = _env("DATABASE_URL")
    if not alembic_url and not database_url:
        _die("DATABASE_URL / ALEMBIC_DATABASE_URL is required")

    destinations: list[tuple[str, dict[str, Any]]] = []
    if alembic_url:
        destinations.append((alembic_url, _parse_postgres_url(alembic_url)))
    if database_url:
        destinations.append((database_url, _parse_postgres_url(database_url)))

    if len(destinations) == 2:
        left = destinations[0][1]
        right = destinations[1][1]
        if (
            left["host"] != right["host"]
            or left["port"] != right["port"]
            or left["database"] != right["database"]
        ):
            _die(
                "ALEMBIC_DATABASE_URL and DATABASE_URL point at different destinations: "
                f"{left['identity']} vs {right['identity']}"
            )

    # Prefer DATABASE_URL when both agree; otherwise the sole configured URL.
    approved_url = database_url or alembic_url
    dest = _parse_postgres_url(approved_url)
    _assert_destination_allowed(dest)

    # Propagate the same approved configuration to migrations and the app process.
    os.environ["DATABASE_URL"] = approved_url
    os.environ["ALEMBIC_DATABASE_URL"] = approved_url
    return approved_url, dest


def _backend_dir() -> Path:
    return Path(__file__).resolve().parents[1]


def _psycopg_url(url: str) -> str:
    for prefix in ("postgresql+psycopg2://", "postgresql+psycopg://"):
        if url.startswith(prefix):
            return "postgresql://" + url[len(prefix) :]
    return url


def _with_advisory_lock(url: str, fn) -> None:
    try:
        import psycopg2
    except ImportError as exc:
        _die(f"psycopg2 required for migrate lock: {exc}")

    print("[receptionist-staging-start] connecting to approved database", flush=True)
    conn = psycopg2.connect(_psycopg_url(url), connect_timeout=DB_CONNECT_TIMEOUT_SECONDS)
    print("[receptionist-staging-start] database connection established", flush=True)
    conn.autocommit = True
    cur = conn.cursor()
    deadline = time.time() + LOCK_WAIT_SECONDS
    locked = False
    try:
        print("[receptionist-staging-start] acquiring migration lock", flush=True)
        while time.time() < deadline:
            cur.execute("SELECT pg_try_advisory_lock(%s)", (LOCK_KEY,))
            locked = bool(cur.fetchone()[0])
            if locked:
                break
            time.sleep(1.0)
        if not locked:
            _die(f"Could not acquire migration advisory lock within {LOCK_WAIT_SECONDS}s")
        print("[receptionist-staging-start] migration lock acquired", flush=True)
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
    env.pop("SQLALCHEMY_DATABASE_URI", None)
    cmd = [sys.executable, "-m", "alembic", "upgrade", TARGET_REVISION]
    print(f"[receptionist-staging-start] + {' '.join(cmd)}", flush=True)
    try:
        completed = subprocess.run(
            cmd, cwd=str(backend), env=env, check=False,
            timeout=ALEMBIC_UPGRADE_TIMEOUT_SECONDS,
        )
    except subprocess.TimeoutExpired:
        _die(f"Alembic upgrade exceeded {ALEMBIC_UPGRADE_TIMEOUT_SECONDS}s")
    if completed.returncode != 0:
        _die(f"alembic upgrade {TARGET_REVISION} failed with exit {completed.returncode}")


def _verify_revision(backend: Path, url: str) -> str:
    env = os.environ.copy()
    env["ALEMBIC_DATABASE_URL"] = url
    env["DATABASE_URL"] = url
    print("[receptionist-staging-start] checking migration revision", flush=True)
    try:
        completed = subprocess.run(
            [sys.executable, "-m", "alembic", "current"],
            cwd=str(backend),
            env=env,
            check=False,
            capture_output=True,
            text=True,
            timeout=ALEMBIC_CURRENT_TIMEOUT_SECONDS,
        )
    except subprocess.TimeoutExpired:
        _die(f"Alembic current exceeded {ALEMBIC_CURRENT_TIMEOUT_SECONDS}s")
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
    # Commit pin first — fail closed before any database access.
    print("[receptionist-staging-start] verifying pinned commit", flush=True)
    _assert_commit_guard()
    print("[receptionist-staging-start] verifying database destination", flush=True)
    url, dest = resolve_approved_database_url()
    backend = _backend_dir()
    print(
        f"[receptionist-staging-start] migrating {dest['identity']} → {TARGET_REVISION}",
        flush=True,
    )

    def _locked_migrate() -> None:
        _run_alembic(backend, url)
        _verify_revision(backend, url)

    _with_advisory_lock(url, _locked_migrate)
    return TARGET_REVISION


def _exec_uvicorn() -> None:
    # Ensure the inherited process uses the same approved URLs.
    approved = _env("DATABASE_URL")
    if approved:
        os.environ["DATABASE_URL"] = approved
        os.environ["ALEMBIC_DATABASE_URL"] = approved
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
    print("[receptionist-staging-start] bootstrap entered", flush=True)
    argv = list(sys.argv[1:] if argv is None else argv)
    migrate_only_flag = "--migrate-only" in argv
    # Diagnostic only: emit a safe Python traceback if initialization hangs.
    # Never print environment values, credentials, or connection URLs.
    faulthandler.enable()
    faulthandler.dump_traceback_later(
        STARTUP_TRACE_TIMEOUT_SECONDS, repeat=False, file=sys.stderr
    )
    try:
        migrate_only()
        faulthandler.cancel_dump_traceback_later()
        if migrate_only_flag:
            return 0
        _exec_uvicorn()
    finally:
        faulthandler.cancel_dump_traceback_later()
    return 0  # unreachable after exec


if __name__ == "__main__":
    raise SystemExit(main())
