#!/usr/bin/env python3
"""Canonical runtime diagnostics for Phase 33C.

Attach-only: never starts or stops runtime processes.
"""

from __future__ import annotations

import json
import os
import signal
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen


STATE_PATH = Path(__file__).resolve().parents[1] / ".runtime" / "canonical_runtime_state.json"


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _parse_iso(ts: str | None) -> datetime | None:
    if not ts:
        return None
    try:
        return datetime.fromisoformat(ts.replace("Z", "+00:00"))
    except ValueError:
        return None


def pid_alive(pid: int | None) -> bool:
    if not pid or pid <= 0:
        return False
    if os.name == "nt":
        try:
            proc = subprocess.run(
                ["tasklist", "/FI", f"PID eq {pid}", "/FO", "CSV", "/NH"],
                capture_output=True,
                text=True,
                timeout=3,
                check=False,
            )
            out = (proc.stdout or "").strip()
            if not out:
                return False
            if out.lower().startswith("info:"):
                return False
            return f'"{pid}"' in out
        except Exception:
            return False
    try:
        os.kill(pid, 0)
        return True
    except Exception:
        return False


def port_owner_pids(port: int) -> list[int]:
    owners: list[int] = []
    if os.name == "nt":
        try:
            proc = subprocess.run(
                ["netstat", "-ano", "-p", "tcp"],
                capture_output=True,
                text=True,
                timeout=4,
                check=False,
            )
            for line in (proc.stdout or "").splitlines():
                text = line.strip()
                if not text.startswith("TCP"):
                    continue
                parts = text.split()
                if len(parts) < 5:
                    continue
                local_addr = parts[1]
                state = parts[3].upper()
                pid_raw = parts[4]
                if not local_addr.endswith(f":{port}"):
                    continue
                if state not in {"LISTENING", "BOUND"}:
                    continue
                try:
                    owners.append(int(pid_raw))
                except ValueError:
                    continue
        except Exception:
            return []
    return sorted(set(owners))


def probe(url: str, timeout: float = 4.0) -> tuple[int | None, str, str | None]:
    req = Request(url, method="GET")
    try:
        with urlopen(req, timeout=timeout) as resp:
            status = int(resp.getcode())
            ctype = resp.headers.get("Content-Type", "")
            return status, ctype, None
    except HTTPError as exc:
        ctype = exc.headers.get("Content-Type", "") if exc.headers else ""
        return int(exc.code), ctype, None
    except URLError as exc:
        return None, "", str(exc.reason)
    except TimeoutError:
        return None, "", "timeout"


def load_state() -> dict[str, object] | None:
    if not STATE_PATH.exists():
        return None
    try:
        return json.loads(STATE_PATH.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return None


def main() -> int:
    host = os.getenv("AMICOR_HOST", "127.0.0.1").strip() or "127.0.0.1"
    port = int(os.getenv("AMICOR_PORT", "8011"))
    base = f"http://{host}:{port}"

    state = load_state()
    launcher_pid = int(state.get("launcher_pid", 0)) if state else 0
    uvicorn_pid = int(state.get("uvicorn_pid", 0)) if state and state.get("uvicorn_pid") else 0
    listener_pids = port_owner_pids(port)
    active_listener_pid = listener_pids[0] if listener_pids else None
    started_at_raw = str(state.get("started_at")) if state and state.get("started_at") else None
    started_at = _parse_iso(started_at_raw)

    api_status, api_ctype, api_err = probe(f"{base}/api/health")
    app_status, _, app_err = probe(f"{base}/app")
    gov_status, _, gov_err = probe(f"{base}/app/operations/governance")

    runtime_alive = api_status == 200 and bool(listener_pids)
    readiness_state = "ready" if (api_status == 200 and app_status == 200 and gov_status == 200) else "degraded"
    if not runtime_alive:
        readiness_state = "down"

    uptime_seconds = None
    if started_at:
        uptime_seconds = max(0, int((_now() - started_at).total_seconds()))

    payload = {
        "runtime_alive": runtime_alive,
        "pid": {
            "launcher": launcher_pid or None,
            "launcher_alive": pid_alive(launcher_pid),
            "uvicorn": uvicorn_pid or None,
            "uvicorn_alive": pid_alive(uvicorn_pid),
            "listener_owners": listener_pids,
            "active_listener": active_listener_pid,
            "state_listener_mismatch": bool(uvicorn_pid and active_listener_pid and uvicorn_pid != active_listener_pid),
        },
        "uptime_seconds": uptime_seconds,
        "active_port": port,
        "health_status": {
            "api_health": api_status,
            "api_content_type": api_ctype,
            "api_error": api_err,
            "app": app_status,
            "app_error": app_err,
            "governance": gov_status,
            "governance_error": gov_err,
        },
        "readiness_state": readiness_state,
        "state_file": str(STATE_PATH),
        "state_mode": state.get("mode") if state else None,
        "urls": {
            "app": f"{base}/app",
            "governance": f"{base}/app/operations/governance",
            "api_health": f"{base}/api/health",
        },
    }

    print(json.dumps(payload, indent=2))
    if runtime_alive:
        return 0

    print("Runtime is not reachable. Start canonical runtime with: scripts/dev_up.ps1")
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
