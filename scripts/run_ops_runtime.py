#!/usr/bin/env python3
"""Persistent runtime launcher for Amicor operational shell.

Phase 33B scope: process orchestration only.
This launcher intentionally does not modify API behavior, routing, governance, or replay logic.
"""

from __future__ import annotations

import json
import os
import signal
import subprocess
import sys
import threading
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen


STATE_DIR_NAME = ".runtime"
STATE_FILE_NAME = "canonical_runtime_state.json"


@dataclass(frozen=True)
class RuntimeConfig:
    host: str
    port: int
    reload: bool
    log_level: str
    startup_timeout_seconds: int
    health_interval_seconds: int


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def log_event(event: str, **details: object) -> None:
    payload = {
        "ts": _utc_now(),
        "event": event,
        **details,
    }
    print(json.dumps(payload, separators=(",", ":")), flush=True)


def parse_bool_env(name: str, default: bool) -> bool:
    raw = os.getenv(name)
    if raw is None:
        return default
    return raw.strip().lower() in {"1", "true", "yes", "on"}


def load_config() -> RuntimeConfig:
    host = os.getenv("AMICOR_HOST", "127.0.0.1").strip() or "127.0.0.1"
    port_raw = os.getenv("AMICOR_PORT", "8011")
    log_level = os.getenv("AMICOR_LOG_LEVEL", "info").strip() or "info"
    reload_enabled = parse_bool_env("AMICOR_RELOAD", False)
    startup_timeout_raw = os.getenv("AMICOR_STARTUP_TIMEOUT", "90")
    health_interval_raw = os.getenv("AMICOR_HEALTH_INTERVAL", "10")

    try:
        port = int(port_raw)
    except ValueError as exc:
        raise ValueError(f"AMICOR_PORT must be an integer, got: {port_raw}") from exc

    try:
        startup_timeout_seconds = int(startup_timeout_raw)
    except ValueError as exc:
        raise ValueError(
            f"AMICOR_STARTUP_TIMEOUT must be an integer, got: {startup_timeout_raw}"
        ) from exc

    try:
        health_interval_seconds = int(health_interval_raw)
    except ValueError as exc:
        raise ValueError(
            f"AMICOR_HEALTH_INTERVAL must be an integer, got: {health_interval_raw}"
        ) from exc

    if port <= 0 or port > 65535:
        raise ValueError(f"AMICOR_PORT must be in range 1-65535, got: {port}")
    if startup_timeout_seconds <= 0:
        raise ValueError("AMICOR_STARTUP_TIMEOUT must be > 0")
    if health_interval_seconds <= 0:
        raise ValueError("AMICOR_HEALTH_INTERVAL must be > 0")

    return RuntimeConfig(
        host=host,
        port=port,
        reload=reload_enabled,
        log_level=log_level,
        startup_timeout_seconds=startup_timeout_seconds,
        health_interval_seconds=health_interval_seconds,
    )


def runtime_urls(cfg: RuntimeConfig) -> dict[str, str]:
    probe_host = (os.getenv("AMICOR_PROBE_HOST", "").strip() or cfg.host)
    if probe_host in {"0.0.0.0", "::"}:
        probe_host = "127.0.0.1"
    base = f"http://{probe_host}:{cfg.port}"
    return {
        "api_health": f"{base}/api/health",
        "app": f"{base}/app",
        "app_governance": f"{base}/app/operations/governance",
    }


def state_file_path(repo_root: Path) -> Path:
    return repo_root / STATE_DIR_NAME / STATE_FILE_NAME


def write_state(path: Path, payload: dict[str, object]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, separators=(",", ":"), indent=2), encoding="utf-8")


def read_state(path: Path) -> dict[str, object] | None:
    if not path.exists():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return None


def pid_exists(pid: int | None) -> bool:
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


def remove_state_if_owner(path: Path, owner_pid: int) -> None:
    state = read_state(path)
    if not state:
        return
    if int(state.get("launcher_pid", -1)) != owner_pid:
        return
    try:
        path.unlink(missing_ok=True)
    except OSError:
        pass


def check_url(url: str, timeout_seconds: float = 3.0) -> tuple[bool, int | None, str | None]:
    request = Request(url, method="GET")
    try:
        with urlopen(request, timeout=timeout_seconds) as response:
            status = int(response.getcode())
            content_type = response.headers.get("Content-Type", "")
            return 200 <= status < 400, status, content_type
    except HTTPError as exc:
        content_type = exc.headers.get("Content-Type", "") if exc.headers else ""
        return False, int(exc.code), content_type
    except URLError as exc:
        return False, None, str(exc.reason)
    except TimeoutError:
        return False, None, "timeout"


def check_readiness(endpoints: dict[str, str]) -> tuple[bool, list[dict[str, object]]]:
    results: list[dict[str, object]] = []
    overall_ok = True
    for name, url in endpoints.items():
        ok, status, info = check_url(url)
        if name in {"app", "app_governance"}:
            # Shell routes are considered ready only on direct success.
            route_ok = ok and status == 200
        else:
            route_ok = ok and status == 200
        results.append(
            {
                "name": name,
                "url": url,
                "ok": route_ok,
                "status": status,
                "info": info,
            }
        )
        if not route_ok:
            overall_ok = False
            log_event(
                "runtime.health.probe_failed",
                endpoint=name,
                url=url,
                status=status,
                info=info,
            )
    return overall_ok, results


def port_owner_pids(port: int) -> set[int]:
    owners: set[int] = set()
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
                    owners.add(int(pid_raw))
                except ValueError:
                    continue
        except Exception:
            return owners
        return owners

    try:
        proc = subprocess.run(
            ["lsof", "-i", f"TCP:{port}", "-sTCP:LISTEN", "-t"],
            capture_output=True,
            text=True,
            timeout=4,
            check=False,
        )
        for line in (proc.stdout or "").splitlines():
            try:
                owners.add(int(line.strip()))
            except ValueError:
                continue
    except Exception:
        return owners
    return owners


def stream_subprocess_output(proc: subprocess.Popen[str], stop_event: threading.Event) -> None:
    assert proc.stdout is not None
    for line in iter(proc.stdout.readline, ""):
        if not line and stop_event.is_set():
            break
        text = line.rstrip("\r\n")
        if text:
            log_event("runtime.log", line=text)
    log_event("runtime.log.stream_closed")


def build_uvicorn_command(cfg: RuntimeConfig) -> list[str]:
    cmd = [
        sys.executable,
        "-m",
        "uvicorn",
        "app.main:app",
        "--host",
        cfg.host,
        "--port",
        str(cfg.port),
        "--log-level",
        cfg.log_level,
    ]
    if cfg.reload:
        cmd.append("--reload")
    return cmd


def terminate_process(proc: subprocess.Popen[str], timeout_seconds: int = 10) -> None:
    if proc.poll() is not None:
        return

    log_event("runtime.shutdown.signal", signal="terminate", pid=proc.pid)
    proc.terminate()
    try:
        proc.wait(timeout=timeout_seconds)
        log_event("runtime.shutdown.complete", pid=proc.pid, returncode=proc.returncode)
    except subprocess.TimeoutExpired:
        log_event("runtime.shutdown.force_kill", pid=proc.pid)
        proc.kill()
        proc.wait(timeout=timeout_seconds)
        log_event("runtime.shutdown.complete", pid=proc.pid, returncode=proc.returncode)


def run() -> int:
    try:
        cfg = load_config()
    except ValueError as exc:
        log_event("runtime.config.invalid", error=str(exc))
        return 2

    repo_root = Path(__file__).resolve().parents[1]
    backend_dir = repo_root / "backend"
    state_path = state_file_path(repo_root)
    if not backend_dir.exists():
        log_event("runtime.backend.missing", backend_dir=str(backend_dir))
        return 2

    existing_state = read_state(state_path)
    if existing_state:
        existing_launcher_pid = int(existing_state.get("launcher_pid", -1))
        existing_port = int(existing_state.get("port", -1)) if str(existing_state.get("port", "")).isdigit() else -1
        if existing_launcher_pid > 0 and existing_port == cfg.port:
            if pid_exists(existing_launcher_pid):
                log_event(
                    "runtime.state.already_owned",
                    message="existing canonical runtime owner detected",
                    launcher_pid=existing_launcher_pid,
                    port=existing_port,
                    state_file=str(state_path),
                )
                return 2
            else:
                log_event(
                    "runtime.state.stale",
                    message="stale runtime state detected and ignored",
                    launcher_pid=existing_launcher_pid,
                    state_file=str(state_path),
                )

    endpoints = runtime_urls(cfg)
    cmd = build_uvicorn_command(cfg)
    launcher_pid = os.getpid()
    launcher_started_at = _utc_now()
    startup_begin = time.monotonic()

    log_event(
        "runtime.starting",
        cwd=str(backend_dir),
        command=cmd,
        host=cfg.host,
        port=cfg.port,
        reload=cfg.reload,
        log_level=cfg.log_level,
        launcher_pid=launcher_pid,
        state_file=str(state_path),
    )
    for name, url in endpoints.items():
        log_event("runtime.url", name=name, url=url)

    write_state(
        state_path,
        {
            "mode": "starting",
            "launcher_pid": launcher_pid,
            "uvicorn_pid": None,
            "host": cfg.host,
            "port": cfg.port,
            "reload": cfg.reload,
            "log_level": cfg.log_level,
            "started_at": launcher_started_at,
            "ready": False,
            "last_health": None,
            "endpoints": endpoints,
        },
    )

    proc = subprocess.Popen(
        cmd,
        cwd=str(backend_dir),
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        bufsize=1,
    )
    log_event("runtime.process.spawned", pid=proc.pid, command=cmd)

    write_state(
        state_path,
        {
            "mode": "starting",
            "launcher_pid": launcher_pid,
            "uvicorn_pid": proc.pid,
            "host": cfg.host,
            "port": cfg.port,
            "reload": cfg.reload,
            "log_level": cfg.log_level,
            "started_at": launcher_started_at,
            "ready": False,
            "last_health": None,
            "endpoints": endpoints,
        },
    )

    stop_event = threading.Event()
    stream_thread = threading.Thread(
        target=stream_subprocess_output,
        args=(proc, stop_event),
        name="amicor-runtime-log-stream",
        daemon=True,
    )
    stream_thread.start()

    terminate_requested = threading.Event()

    def _request_shutdown(signum: int, _frame: object) -> None:
        signame = signal.Signals(signum).name if signum in signal.Signals._value2member_map_ else str(signum)
        log_event("runtime.shutdown.requested", signal=signame)
        terminate_requested.set()

    for sig in (signal.SIGINT, signal.SIGTERM):
        try:
            signal.signal(sig, _request_shutdown)
        except (ValueError, OSError):
            pass

    if hasattr(signal, "SIGBREAK"):
        try:
            signal.signal(signal.SIGBREAK, _request_shutdown)
        except (ValueError, OSError):
            pass

    startup_deadline = time.monotonic() + cfg.startup_timeout_seconds
    readiness_complete = False
    readiness_streak = 0
    transient_probe_failures = 0
    hard_probe_failures = 0
    listener_acquired_ms: int | None = None
    first_probe_ms: int | None = None
    escalation_marks = (20, 40, 60)
    escalation_logged = {mark: False for mark in escalation_marks}

    while time.monotonic() < startup_deadline:
        if terminate_requested.is_set():
            break
        if proc.poll() is not None:
            log_event(
                "runtime.process.crash",
                pid=proc.pid,
                returncode=proc.returncode,
                message="uvicorn exited before readiness",
            )
            stop_event.set()
            stream_thread.join(timeout=2)
            remove_state_if_owner(state_path, launcher_pid)
            return 1

        elapsed_ms = int((time.monotonic() - startup_begin) * 1000)
        if first_probe_ms is None:
            first_probe_ms = elapsed_ms

        owners = port_owner_pids(cfg.port)
        if listener_acquired_ms is None and proc.pid in owners:
            listener_acquired_ms = elapsed_ms

        ready, checks = check_readiness(endpoints)
        if ready:
            readiness_streak += 1
        else:
            readiness_streak = 0
            if any(item.get("status") is None for item in checks):
                transient_probe_failures += 1
            else:
                hard_probe_failures += 1

        elapsed_seconds = int(elapsed_ms / 1000)
        for mark in escalation_marks:
            if not escalation_logged[mark] and elapsed_seconds >= mark:
                escalation_logged[mark] = True
                log_event(
                    "runtime.readiness.escalation",
                    seconds=mark,
                    transient_probe_failures=transient_probe_failures,
                    hard_probe_failures=hard_probe_failures,
                    checks=checks,
                )

        log_event("runtime.readiness.poll", ready=ready, checks=checks)
        write_state(
            state_path,
            {
                "mode": "starting",
                "launcher_pid": launcher_pid,
                "uvicorn_pid": proc.pid,
                "host": cfg.host,
                "port": cfg.port,
                "reload": cfg.reload,
                "log_level": cfg.log_level,
                "started_at": launcher_started_at,
                "ready": ready,
                "last_health": _utc_now(),
                "startup_elapsed_ms": elapsed_ms,
                "readiness_streak": readiness_streak,
                "transient_probe_failures": transient_probe_failures,
                "hard_probe_failures": hard_probe_failures,
                "listener_acquired_ms": listener_acquired_ms,
                "checks": checks,
                "endpoints": endpoints,
            },
        )
        if readiness_streak >= 2:
            readiness_complete = True
            readiness_ms = int((time.monotonic() - startup_begin) * 1000)
            log_event(
                "runtime.ready",
                pid=proc.pid,
                startup_ms=readiness_ms,
                listener_acquired_ms=listener_acquired_ms,
                transient_probe_failures=transient_probe_failures,
                hard_probe_failures=hard_probe_failures,
            )
            write_state(
                state_path,
                {
                    "mode": "running",
                    "launcher_pid": launcher_pid,
                    "uvicorn_pid": proc.pid,
                    "host": cfg.host,
                    "port": cfg.port,
                    "reload": cfg.reload,
                    "log_level": cfg.log_level,
                    "started_at": launcher_started_at,
                    "ready": True,
                    "last_health": _utc_now(),
                    "startup_elapsed_ms": readiness_ms,
                    "listener_acquired_ms": listener_acquired_ms,
                    "transient_probe_failures": transient_probe_failures,
                    "hard_probe_failures": hard_probe_failures,
                    "checks": checks,
                    "endpoints": endpoints,
                },
            )
            break
        time.sleep(1.0)

    if not readiness_complete and not terminate_requested.is_set():
        log_event(
            "runtime.readiness.timeout",
            timeout_seconds=cfg.startup_timeout_seconds,
            pid=proc.pid,
            startup_ms=int((time.monotonic() - startup_begin) * 1000),
            listener_acquired_ms=listener_acquired_ms,
            transient_probe_failures=transient_probe_failures,
            hard_probe_failures=hard_probe_failures,
        )
        terminate_process(proc)
        stop_event.set()
        stream_thread.join(timeout=2)
        remove_state_if_owner(state_path, launcher_pid)
        return 1

    try:
        while not terminate_requested.is_set():
            if proc.poll() is not None:
                log_event(
                    "runtime.process.crash",
                    pid=proc.pid,
                    returncode=proc.returncode,
                    message="uvicorn subprocess exited unexpectedly",
                )
                write_state(
                    state_path,
                    {
                        "mode": "crashed",
                        "launcher_pid": launcher_pid,
                        "uvicorn_pid": proc.pid,
                        "host": cfg.host,
                        "port": cfg.port,
                        "reload": cfg.reload,
                        "log_level": cfg.log_level,
                        "started_at": launcher_started_at,
                        "ready": False,
                        "last_health": _utc_now(),
                        "endpoints": endpoints,
                        "returncode": proc.returncode,
                    },
                )
                return 1

            ready, checks = check_readiness(endpoints)
            log_event("runtime.monitor.poll", ready=ready, checks=checks)
            write_state(
                state_path,
                {
                    "mode": "running" if ready else "degraded",
                    "launcher_pid": launcher_pid,
                    "uvicorn_pid": proc.pid,
                    "host": cfg.host,
                    "port": cfg.port,
                    "reload": cfg.reload,
                    "log_level": cfg.log_level,
                    "started_at": launcher_started_at,
                    "ready": ready,
                    "last_health": _utc_now(),
                    "checks": checks,
                    "endpoints": endpoints,
                },
            )
            if not ready:
                log_event("runtime.monitor.degraded", checks=checks)
            time.sleep(cfg.health_interval_seconds)
    finally:
        write_state(
            state_path,
            {
                "mode": "stopping",
                "launcher_pid": launcher_pid,
                "uvicorn_pid": proc.pid,
                "host": cfg.host,
                "port": cfg.port,
                "reload": cfg.reload,
                "log_level": cfg.log_level,
                "started_at": launcher_started_at,
                "ready": False,
                "last_health": _utc_now(),
                "endpoints": endpoints,
            },
        )
        terminate_process(proc)
        stop_event.set()
        stream_thread.join(timeout=3)
        remove_state_if_owner(state_path, launcher_pid)

    return 0


if __name__ == "__main__":
    raise SystemExit(run())
