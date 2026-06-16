#!/usr/bin/env python3
"""Phase 54 preview/runtime validation checks.

Read-only diagnostics for local preview startup verification.
"""

from __future__ import annotations

import json
import os
import sys
import time
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen


ROOT = Path(__file__).resolve().parents[1]
BACKEND_PATH = ROOT / "backend"
if str(BACKEND_PATH) not in sys.path:
    sys.path.insert(0, str(BACKEND_PATH))


def _fetch(url: str, timeout: float = 6.0) -> tuple[int | None, str, str | None, float]:
    started = time.perf_counter()
    req = Request(url, method="GET")
    try:
        with urlopen(req, timeout=timeout) as resp:
            elapsed_ms = (time.perf_counter() - started) * 1000.0
            return int(resp.getcode()), str(resp.headers.get("Content-Type", "")), None, elapsed_ms
    except HTTPError as exc:
        elapsed_ms = (time.perf_counter() - started) * 1000.0
        ctype = exc.headers.get("Content-Type", "") if exc.headers else ""
        return int(exc.code), str(ctype), None, elapsed_ms
    except URLError as exc:
        elapsed_ms = (time.perf_counter() - started) * 1000.0
        return None, "", str(exc.reason), elapsed_ms
    except TimeoutError:
        elapsed_ms = (time.perf_counter() - started) * 1000.0
        return None, "", "timeout", elapsed_ms


def _fetch_with_retries(url: str, *, timeout: float = 6.0, attempts: int = 3, sleep_seconds: float = 0.6) -> tuple[int | None, str, str | None, float]:
    last: tuple[int | None, str, str | None, float] = (None, "", "uninitialized", 0.0)
    for i in range(max(1, attempts)):
        last = _fetch(url, timeout=timeout)
        if last[0] == 200:
            return last
        if i < attempts - 1:
            time.sleep(sleep_seconds)
    return last


def _load_openapi(base_url: str) -> dict:
    status, _, err, _ = _fetch(f"{base_url}/openapi.json")
    if status != 200:
        return {"status": status, "error": err, "paths": {}}
    try:
        with urlopen(Request(f"{base_url}/openapi.json", method="GET"), timeout=6.0) as resp:
            payload = json.loads(resp.read().decode("utf-8"))
    except Exception as exc:
        return {"status": 200, "error": str(exc), "paths": {}}
    return {"status": 200, "error": None, "paths": payload.get("paths") or {}}


def _check_route_registration() -> dict:
    try:
        from app.main import app  # type: ignore

        route_paths = []
        websocket_paths = []
        for route in app.router.routes:
            path = getattr(route, "path", "")
            if not path:
                continue
            route_paths.append(path)
            if "ws/live" in path:
                websocket_paths.append(path)

        return {
            "registered_route_count": len(route_paths),
            "has_preview_runtime_route": "/api/health-isf/operations/preview-runtime-status" in route_paths,
            "has_runtime_state_route": "/api/health-isf/operations/runtime-state" in route_paths,
            "has_runtime_replay_route": "/api/health-isf/operations/runtime-replay" in route_paths,
            "websocket_routes": websocket_paths,
            "websocket_registered": bool(websocket_paths),
        }
    except Exception as exc:
        return {
            "registered_route_count": 0,
            "has_preview_runtime_route": False,
            "has_runtime_state_route": False,
            "has_runtime_replay_route": False,
            "websocket_routes": [],
            "websocket_registered": False,
            "error": str(exc),
        }


def main() -> int:
    host = os.getenv("AMICOR_HOST", "127.0.0.1").strip() or "127.0.0.1"
    port = int(os.getenv("AMICOR_PORT", "8010"))
    base_url = f"http://{host}:{port}"
    alt_port = 8011 if port == 8010 else 8010
    alt_base_url = f"http://{host}:{alt_port}"

    checks = {
        "api_health": _fetch_with_retries(f"{base_url}/api/health", attempts=4, sleep_seconds=0.75),
        "app": _fetch_with_retries(f"{base_url}/app", attempts=3),
        "governance": _fetch_with_retries(f"{base_url}/app/operations/governance", attempts=3),
    }

    alternate_checks = {
        "api_health": _fetch(f"{alt_base_url}/api/health", timeout=2.5),
        "app": _fetch(f"{alt_base_url}/app", timeout=2.5),
    }

    openapi = _load_openapi(base_url)
    registered = _check_route_registration()

    required_paths = {
        "/api/health-isf/operations/runtime-state",
        "/api/health-isf/operations/runtime-replay",
        "/api/health-isf/operations/preview-runtime-status",
    }
    openapi_paths = set((openapi.get("paths") or {}).keys())

    api_ok = checks["api_health"][0] == 200
    app_ok = checks["app"][0] == 200
    gov_ok = checks["governance"][0] == 200
    openapi_ok = openapi.get("status") == 200 and required_paths.issubset(openapi_paths)
    routes_ok = bool(registered.get("has_preview_runtime_route")) and bool(registered.get("websocket_registered"))

    payload = {
        "phase": "PHASE_54",
        "base_url": base_url,
        "checks": {
            "api_health": {
                "status": checks["api_health"][0],
                "content_type": checks["api_health"][1],
                "error": checks["api_health"][2],
                "latency_ms": round(checks["api_health"][3], 1),
            },
            "app": {
                "status": checks["app"][0],
                "content_type": checks["app"][1],
                "error": checks["app"][2],
                "latency_ms": round(checks["app"][3], 1),
            },
            "governance": {
                "status": checks["governance"][0],
                "content_type": checks["governance"][1],
                "error": checks["governance"][2],
                "latency_ms": round(checks["governance"][3], 1),
            },
        },
        "openapi": {
            "status": openapi.get("status"),
            "error": openapi.get("error"),
            "required_paths_present": sorted(list(required_paths.intersection(openapi_paths))),
            "missing_required_paths": sorted(list(required_paths.difference(openapi_paths))),
        },
        "route_registration": registered,
        "preview_urls": {
            "app": f"{base_url}/app?voiceDiag=1&liveVerify=1",
            "governance": f"{base_url}/app/operations/governance?voiceDiag=1&liveVerify=1",
            "api_health": f"{base_url}/api/health",
        },
        "alternate_port_probe": {
            "base_url": alt_base_url,
            "api_health_status": alternate_checks["api_health"][0],
            "api_health_error": alternate_checks["api_health"][2],
            "app_status": alternate_checks["app"][0],
            "app_error": alternate_checks["app"][2],
        },
        "success": bool(api_ok and app_ok and gov_ok and openapi_ok and routes_ok),
    }

    print(json.dumps(payload, indent=2))
    return 0 if payload["success"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
