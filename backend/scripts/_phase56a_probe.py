"""Phase 56A: probe live app loading and dependent assets/APIs."""
from __future__ import annotations

import re
import time

import httpx

BASE = "https://amicor-health-isf-py.onrender.com"


def probe(path: str, timeout: float = 120.0) -> dict:
    t0 = time.perf_counter()
    try:
        r = httpx.get(BASE + path, timeout=timeout, follow_redirects=True)
        ms = (time.perf_counter() - t0) * 1000
        return {
            "path": path,
            "status": r.status_code,
            "ms": round(ms, 1),
            "bytes": len(r.content),
            "content_type": r.headers.get("content-type", ""),
            "error": None,
            "preview": r.text[:500] if "html" in (r.headers.get("content-type") or "") else None,
        }
    except Exception as exc:
        ms = (time.perf_counter() - t0) * 1000
        return {"path": path, "status": None, "ms": round(ms, 1), "error": f"{type(exc).__name__}: {exc}"}


def main() -> None:
    core_paths = [
        "/api/health/live",
        "/api/health/readiness",
        "/api/runtime/topology",
        "/api/auth/deployment/seed-status",
        "/",
        "/app/dashboard",
        "/app/riders",
        "/app/mobile",
    ]
    print("=== core paths ===")
    for p in core_paths:
        print(probe(p))

    dash = httpx.get(BASE + "/app/dashboard", timeout=120)
    scripts = re.findall(r'src="([^"]+)"', dash.text)
    links = re.findall(r'href="([^"]+\.css[^"]*)"', dash.text)
    print("\n=== assets from /app/dashboard ===")
    for asset in scripts + links:
        if asset.startswith("http"):
            continue
        path = asset if asset.startswith("/") else "/" + asset.lstrip("/")
        print(probe(path))

    # APIs ops-shell typically hits on boot
    api_paths = [
        "/api/auth/me",
        "/api/health-isf/dashboard",
        "/api/health-isf/drivers",
        "/api/health-isf/rides",
    ]
    print("\n=== boot APIs (no auth) ===")
    for p in api_paths:
        print(probe(p))


if __name__ == "__main__":
    main()
