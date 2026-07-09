"""Keep uvicorn on 8011 stable across verification scripts (Windows-safe)."""
from __future__ import annotations

import os
import subprocess
import sys
import time
from pathlib import Path

import httpx

SCRIPT_DIR = Path(__file__).resolve().parent
BACKEND_ROOT = SCRIPT_DIR.parent
LOG_DIR = BACKEND_ROOT / "logs"
PID_FILE = LOG_DIR / "uvicorn-8011.pid"
LOG_FILE = LOG_DIR / "uvicorn-8011.log"
BASE = os.getenv("AMICOR_BROWSER_BASE", "http://127.0.0.1:8011").rstrip("/")
HOST = "127.0.0.1"
PORT = 8011


def server_health(timeout_sec: float = 3.0) -> bool:
    try:
        return httpx.get(f"{BASE}/api/runtime/topology", timeout=timeout_sec).status_code == 200
    except Exception:
        return False


def wait_server_ready(timeout_sec: int = 120) -> bool:
    deadline = time.time() + timeout_sec
    while time.time() < deadline:
        if server_health():
            return True
        time.sleep(2)
    return False


def _read_pid() -> int | None:
    try:
        raw = PID_FILE.read_text(encoding="utf-8").strip()
        return int(raw) if raw.isdigit() else None
    except Exception:
        return None


def kill_server_on_port() -> None:
    if os.getenv("SKIP_SERVER_KILL", "").strip().lower() in {"1", "true", "yes"}:
        return
    ps = (
        f"Get-NetTCPConnection -LocalPort {PORT} -ErrorAction SilentlyContinue | "
        "ForEach-Object { Stop-Process -Id $_.OwningProcess -Force -ErrorAction SilentlyContinue }; "
        "Get-CimInstance Win32_Process -Filter \"Name = 'python.exe'\" | "
        f"Where-Object {{ $_.CommandLine -like '*uvicorn*app.main:app*{PORT}*' }} | "
        "ForEach-Object { Stop-Process -Id $_.ProcessId -Force -ErrorAction SilentlyContinue }; "
        "Start-Sleep -Seconds 2"
    )
    subprocess.run(["powershell", "-NoProfile", "-Command", ps], check=False)
    try:
        PID_FILE.unlink(missing_ok=True)
    except Exception:
        pass


def start_server_detached(*, allow_skip: bool = True) -> int:
    """Start uvicorn detached from the parent script so it survives test exit."""
    if allow_skip and os.getenv("SKIP_SERVER_RESTART", "").strip().lower() in {"1", "true", "yes"}:
        if wait_server_ready(timeout_sec=15):
            pid = _read_pid()
            return pid or 0
        raise RuntimeError("SKIP_SERVER_RESTART set but server is not healthy")

    LOG_DIR.mkdir(parents=True, exist_ok=True)
    log_handle = open(LOG_FILE, "a", encoding="utf-8", errors="replace")
    log_handle.write(f"\n--- uvicorn start {time.strftime('%Y-%m-%d %H:%M:%S')} ---\n")
    log_handle.flush()

    creationflags = 0
    if sys.platform == "win32":
        creationflags = subprocess.DETACHED_PROCESS | subprocess.CREATE_NEW_PROCESS_GROUP

    proc = subprocess.Popen(
        [sys.executable, "-m", "uvicorn", "app.main:app", "--host", HOST, f"--port", str(PORT)],
        cwd=str(BACKEND_ROOT),
        stdout=log_handle,
        stderr=subprocess.STDOUT,
        creationflags=creationflags,
        close_fds=False,
    )
    PID_FILE.write_text(str(proc.pid), encoding="utf-8")
    return proc.pid


def ensure_server_running(*, force_restart: bool = False) -> dict[str, object]:
    """Return server status; restart only when unhealthy or force_restart=True."""
    if not force_restart and server_health():
        return {
            "action": "already_running",
            "healthy": True,
            "pid": _read_pid(),
            "base": BASE,
            "log_file": str(LOG_FILE),
        }

    kill_server_on_port()
    pid = start_server_detached(allow_skip=not force_restart)
    if not wait_server_ready():
        tail = ""
        try:
            tail = LOG_FILE.read_text(encoding="utf-8", errors="replace")[-2000:]
        except Exception:
            pass
        raise RuntimeError(
            f"Server did not become ready at {BASE}. Check log: {LOG_FILE}\n{tail}"
        )
    return {
        "action": "restarted",
        "healthy": True,
        "pid": pid,
        "base": BASE,
        "log_file": str(LOG_FILE),
    }


def verify_server_persistence() -> dict[str, object]:
    healthy = server_health()
    return {
        "healthy": healthy,
        "pid": _read_pid(),
        "base": BASE,
        "log_file": str(LOG_FILE),
    }
