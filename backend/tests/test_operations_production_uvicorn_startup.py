"""Uvicorn must bind when the shared production database is slow or disposable.

These tests start the real server. They never open a non-loopback database.
"""

from __future__ import annotations

import json
import os
import socket
import subprocess
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path
from urllib.parse import urlsplit

import pytest

BACKEND = Path(__file__).resolve().parents[1]
if str(BACKEND) not in sys.path:
    sys.path.insert(0, str(BACKEND))
OWNER_EMAIL = "owner.persist@example.invalid"
OWNER_PASSWORD = "owner-persist-password"
WRITER_PASSWORD = "writerdisposableonly"
BLACKHOLE_PASSWORD = "synthetic-db-password"


def _database_name(url: str) -> str:
    try:
        path = (urlsplit(url).path or "").strip("/")
    except ValueError:
        return ""
    return path.split("/", 1)[0].split("?", 1)[0].casefold()


def _loopback_amicor(url: str) -> bool:
    raw = (url or "").strip()
    if not raw.lower().startswith("postgres"):
        return False
    try:
        host = (urlsplit(raw).hostname or "").casefold()
    except ValueError:
        return False
    return host in {"localhost", "127.0.0.1", "::1"} and _database_name(raw) == "amicor"


def _disposable_postgres_url() -> str:
    for name in ("OPS_STARTUP_POSTGRES_URL", "DATABASE_URL"):
        candidate = os.getenv(name, "").strip()
        if _loopback_amicor(candidate):
            return candidate
    return ""


def _free_port() -> int:
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


def _child_env(database_url: str, **extra: str) -> dict[str, str]:
    env = {
        "PATH": os.environ.get("PATH", ""),
        "SYSTEMROOT": os.environ.get("SYSTEMROOT", ""),
        "TEMP": os.environ.get("TEMP", ""),
        "TMP": os.environ.get("TMP", ""),
        "DATABASE_URL": database_url,
        "APP_ENV": "production",
        "AMICOR_ENVIRONMENT": "production",
        "SECRET_KEY": "ci-only-placeholder",
        "JWT_SECRET": "ci-only-placeholder",
        "ALLOWED_ORIGINS": "https://example.invalid",
        "AMICOR_PUBLIC_URL": "https://example.invalid",
        "APP_VERSION": "diagnostic",
        "LOG_LEVEL": "INFO",
        "NOVA_STRIPE_LIVE_ENABLED": "false",
        "NOVA_OPERATIONS_CUSTOMER_SALES_ENABLED": "false",
        "NOVA_V3_OWNER_EMAILS": OWNER_EMAIL,
        "DB_POOL_SIZE": "2",
        "DB_MAX_OVERFLOW": "1",
        "PYTHONPATH": str(BACKEND),
    }
    env.update(extra)
    return env


def _start_uvicorn(database_url: str, log_path: Path, **extra: str) -> tuple[subprocess.Popen, int]:
    port = _free_port()
    log_handle = log_path.open("w", encoding="utf-8", errors="replace")
    process = subprocess.Popen(
        [
            sys.executable,
            "-m",
            "uvicorn",
            "app.main:app",
            "--host",
            "127.0.0.1",
            "--port",
            str(port),
        ],
        cwd=BACKEND,
        env=_child_env(database_url, **extra),
        stdout=log_handle,
        stderr=subprocess.STDOUT,
    )
    log_handle.close()
    return process, port


def _stop(process: subprocess.Popen) -> None:
    if process.poll() is None:
        process.kill()
    try:
        process.wait(timeout=15)
    except subprocess.TimeoutExpired:
        process.kill()


def _request(port: int, path: str, timeout: float, method: str = "GET", payload: dict | None = None, headers: dict | None = None):
    data = None if payload is None else json.dumps(payload).encode("utf-8")
    request_headers = {"Accept": "application/json"}
    if payload is not None:
        request_headers["Content-Type"] = "application/json"
    if headers:
        request_headers.update(headers)
    request = urllib.request.Request(
        f"http://127.0.0.1:{port}{path}",
        data=data,
        headers=request_headers,
        method=method,
    )
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            return response.status, response.read().decode("utf-8", "replace")
    except urllib.error.HTTPError as exc:
        return exc.code, exc.read().decode("utf-8", "replace")


def _wait_for_http(process: subprocess.Popen, port: int, path: str, deadline_s: float, log_path: Path | None = None):
    started = time.perf_counter()
    last_error = "connection refused"
    while time.perf_counter() - started < deadline_s:
        if process.poll() is not None:
            excerpt = ""
            if log_path is not None and log_path.exists():
                excerpt = log_path.read_text(encoding="utf-8", errors="replace")[-1500:]
                for secret in (BLACKHOLE_PASSWORD, WRITER_PASSWORD, OWNER_PASSWORD):
                    excerpt = excerpt.replace(secret, "[redacted]")
            raise AssertionError(f"uvicorn exited before binding ({process.returncode}) {excerpt}")
        try:
            status, body = _request(port, path, timeout=5)
            return status, body, time.perf_counter() - started
        except (urllib.error.URLError, TimeoutError, ConnectionError, OSError) as exc:
            last_error = type(exc).__name__
            time.sleep(0.4)
    raise AssertionError(f"uvicorn did not serve {path}: {last_error}")


def test_unavailable_database_cannot_hold_the_port(tmp_path: Path):
    database_url = f"postgresql://operations:{BLACKHOLE_PASSWORD}@192.0.2.1:5432/amicor"
    log_path = tmp_path / "blackhole-uvicorn.log"
    process, port = _start_uvicorn(database_url, log_path)
    try:
        status, body, elapsed = _wait_for_http(process, port, "/api/health", deadline_s=90, log_path=log_path)
        assert status == 200
        assert elapsed < 90
        assert "status" in body
        readiness_started = time.perf_counter()
        readiness_status, readiness_body = _request(port, "/api/health/readiness", timeout=15)
        readiness_elapsed = time.perf_counter() - readiness_started
        assert readiness_status in {200, 503}
        assert readiness_elapsed < 15
        log_text = log_path.read_text(encoding="utf-8", errors="replace")
        secret_text = "\n".join((body, readiness_body, log_text))
        assert BLACKHOLE_PASSWORD not in secret_text
        assert "postgresql://" not in secret_text
        assert "preserve_existing_records=True" in log_text
    finally:
        _stop(process)

    probe = subprocess.run(
        [
            sys.executable,
            "-c",
            (
                "import json,time\n"
                "from app.db.session import DATABASE_CONNECT_TIMEOUT_SECONDS, check_db_connection_detail\n"
                "started=time.perf_counter()\n"
                "detail=check_db_connection_detail()\n"
                "elapsed=time.perf_counter()-started\n"
                "print(json.dumps({'connected': detail.get('connected'), 'elapsed': elapsed,"
                "'timeout': DATABASE_CONNECT_TIMEOUT_SECONDS,"
                "'error_class': detail.get('error_class')}))\n"
            ),
        ],
        cwd=BACKEND,
        env=_child_env(database_url),
        capture_output=True,
        text=True,
        timeout=20,
        check=False,
    )
    assert probe.returncode == 0, probe.stderr
    assert BLACKHOLE_PASSWORD not in probe.stdout
    reported = json.loads(probe.stdout.strip().splitlines()[-1])
    assert reported["connected"] is False
    assert reported["timeout"] == 5
    assert reported["elapsed"] < 12


def test_uvicorn_preserves_production_records_on_disposable_postgres(tmp_path: Path):
    admin_url = _disposable_postgres_url()
    if not admin_url:
        pytest.skip("Disposable loopback PostgreSQL database amicor is not configured")

    import psycopg2
    from psycopg2 import sql

    from app.auth import hash_password

    owner_hash = hash_password(OWNER_PASSWORD)
    admin = psycopg2.connect(admin_url, connect_timeout=5)
    try:
        admin.autocommit = True
        with admin.cursor() as cursor:
            cursor.execute(
                """
                CREATE TABLE IF NOT EXISTS platform_users (
                    id varchar(36) primary key,
                    email varchar(320) unique not null,
                    hashed_password varchar(256) not null,
                    display_name varchar(128),
                    role varchar(32) not null,
                    authorized_roles varchar(512),
                    session_role varchar(32),
                    auth_version integer not null default 0,
                    organization_name varchar(128),
                    organization_id varchar(36),
                    is_active boolean not null default true,
                    is_verified boolean not null default false,
                    created_at timestamptz default now(),
                    last_login timestamptz
                )
                """
            )
            for statement in (
                "ALTER TABLE platform_users ADD COLUMN IF NOT EXISTS display_name varchar(128)",
                "ALTER TABLE platform_users ADD COLUMN IF NOT EXISTS role varchar(32) NOT NULL DEFAULT 'staff'",
                "ALTER TABLE platform_users ADD COLUMN IF NOT EXISTS authorized_roles varchar(512)",
                "ALTER TABLE platform_users ADD COLUMN IF NOT EXISTS session_role varchar(32)",
                "ALTER TABLE platform_users ADD COLUMN IF NOT EXISTS auth_version integer NOT NULL DEFAULT 0",
                "ALTER TABLE platform_users ADD COLUMN IF NOT EXISTS organization_name varchar(128)",
                "ALTER TABLE platform_users ADD COLUMN IF NOT EXISTS organization_id varchar(36)",
            ):
                cursor.execute(statement)
            cursor.execute(
                """
                CREATE TABLE IF NOT EXISTS platform_refresh_tokens (
                    id varchar(36) primary key,
                    user_id varchar(36) not null references platform_users(id) on delete cascade,
                    token_hash varchar(128) unique not null,
                    expires_at timestamptz not null,
                    created_at timestamptz default now(),
                    revoked boolean default false
                )
                """
            )
            cursor.execute(
                """
                INSERT INTO platform_users (
                    id, email, hashed_password, display_name, role, authorized_roles,
                    session_role, organization_name, organization_id, is_active, is_verified
                ) VALUES (
                    'owner-persist', %s, %s, 'Existing Owner', 'admin', 'admin',
                    'admin', 'Existing Owner Org', 'tenant-owner', true, true
                )
                ON CONFLICT (email) DO UPDATE SET
                    hashed_password = EXCLUDED.hashed_password,
                    role = EXCLUDED.role,
                    authorized_roles = EXCLUDED.authorized_roles,
                    session_role = EXCLUDED.session_role,
                    organization_id = EXCLUDED.organization_id,
                    is_active = true,
                    is_verified = true
                """,
                (OWNER_EMAIL, owner_hash),
            )
            cursor.execute(
                """
                CREATE TABLE IF NOT EXISTS nova_operations_payment_events (
                    event_id text PRIMARY KEY,
                    event_type text NOT NULL,
                    object_id text NOT NULL,
                    received_at timestamptz NOT NULL DEFAULT now(),
                    processed_at timestamptz
                )
                """
            )
            cursor.execute("SELECT 1 FROM pg_roles WHERE rolname = 'nova_ops_event_writer'")
            if cursor.fetchone():
                cursor.execute(
                    sql.SQL("ALTER ROLE nova_ops_event_writer WITH LOGIN PASSWORD {}").format(
                        sql.Literal(WRITER_PASSWORD)
                    )
                )
            else:
                cursor.execute(
                    sql.SQL("CREATE ROLE nova_ops_event_writer LOGIN PASSWORD {}").format(
                        sql.Literal(WRITER_PASSWORD)
                    )
                )
            cursor.execute("REVOKE ALL ON TABLE public.nova_operations_payment_events FROM PUBLIC")
            cursor.execute(
                "REVOKE ALL ON TABLE public.nova_operations_payment_events FROM nova_ops_event_writer"
            )
            cursor.execute(
                """
                GRANT SELECT (event_id, event_type, object_id, received_at, processed_at)
                ON public.nova_operations_payment_events TO nova_ops_event_writer
                """
            )
            cursor.execute(
                """
                GRANT INSERT (event_id, event_type, object_id)
                ON public.nova_operations_payment_events TO nova_ops_event_writer
                """
            )
            cursor.execute(
                "SELECT hashed_password, role, authorized_roles, organization_id FROM platform_users WHERE email = %s",
                (OWNER_EMAIL,),
            )
            before = cursor.fetchone()
    finally:
        admin.close()

    parsed = urlsplit(admin_url)
    writer_url = (
        f"postgresql://nova_ops_event_writer:{WRITER_PASSWORD}"
        f"@{parsed.hostname}:{parsed.port or 5432}{parsed.path}"
    )
    log_path = tmp_path / "postgres-uvicorn.log"
    process, port = _start_uvicorn(
        admin_url,
        log_path,
        NOVA_OPERATIONS_DATABASE_URL=writer_url,
    )
    try:
        status, body, _elapsed = _wait_for_http(
            process, port, "/api/health/readiness", deadline_s=90, log_path=log_path
        )
        assert status == 200, body[:500]
        assert BLACKHOLE_PASSWORD not in body
        assert WRITER_PASSWORD not in body
        assert "postgresql://" not in body

        with psycopg2.connect(admin_url, connect_timeout=5) as check:
            with check.cursor() as cursor:
                cursor.execute(
                    "SELECT hashed_password, role, authorized_roles, organization_id FROM platform_users WHERE email = %s",
                    (OWNER_EMAIL,),
                )
                after = cursor.fetchone()
        assert after == before

        login_status, login_body = _request(
            port,
            "/api/auth/login",
            timeout=20,
            method="POST",
            payload={"email": OWNER_EMAIL, "password": OWNER_PASSWORD},
        )
        assert login_status == 200, login_body[:500]
        login = json.loads(login_body)
        assert login["email"] == OWNER_EMAIL
        assert login["role"] == "admin"
        token = login["access_token"]
        assert OWNER_PASSWORD not in login_body

        probe_status, probe_body = _request(
            port,
            "/api/nova/work/operations/owner/storage-probe",
            timeout=15,
            method="POST",
            headers={"Authorization": f"Bearer {token}"},
        )
        assert probe_status == 403
        assert "Explicit owner storage probe required" in probe_body

        ready_status, ready_body = _request(port, "/payments/operations/readiness", timeout=15)
        assert ready_status == 200, ready_body[:500]
        ready = json.loads(ready_body)
        assert ready["live_sales_enabled"] is False
        assert ready["payment_receiver"]["writer_permissions_ok"] is True
        assert ready["payment_receiver"]["database_url_configured"] is True
        assert "whsec_" not in ready_body
        assert "sk_live" not in ready_body
        assert WRITER_PASSWORD not in ready_body
        log_text = log_path.read_text(encoding="utf-8", errors="replace")
        assert "preserve_existing_records=True" in log_text
        assert WRITER_PASSWORD not in log_text
        assert OWNER_PASSWORD not in log_text
    finally:
        _stop(process)
