#!/usr/bin/env python3
"""Audit production database connectivity without modifying workflow data."""
from __future__ import annotations

import json
import os
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

import requests

BASE = os.getenv("AMICOR_RENDER_BASE", "https://amicor-health-isf-py.onrender.com").rstrip("/")
REPO = Path(__file__).resolve().parents[2]
OUT_DIR = REPO / "PRODUCTION_QA_EVIDENCE"
RUN_TS = datetime.now(timezone.utc).strftime("%Y%m%d%H%M%S")
JSON_OUT = OUT_DIR / f"PRODUCTION_DB_CONNECTIVITY_{RUN_TS}.json"
MD_OUT = OUT_DIR / f"PRODUCTION_DB_CONNECTIVITY_{RUN_TS}.md"


def probe(method: str, path: str, **kwargs) -> dict:
    url = f"{BASE}{path}"
    start = time.perf_counter()
    try:
        resp = requests.request(method, url, timeout=120, **kwargs)
        elapsed_ms = int((time.perf_counter() - start) * 1000)
        body: object
        try:
            body = resp.json()
        except ValueError:
            body = resp.text[:500]
        return {"url": path, "status": resp.status_code, "elapsed_ms": elapsed_ms, "body": body}
    except requests.RequestException as exc:
        elapsed_ms = int((time.perf_counter() - start) * 1000)
        return {"url": path, "status": 0, "elapsed_ms": elapsed_ms, "error": str(exc)}


def main() -> int:
    probes = [
        probe("GET", "/api/health/live"),
        probe("GET", "/api/health"),
        probe("GET", "/api/health/readiness"),
        probe("GET", "/api/health/operational"),
        probe("GET", "/api/health/detail"),
        probe("GET", "/api/admin/dashboard"),
        probe("POST", "/api/auth/login", json={"email": "nonexistent@test.com", "password": "wrong"}),
        probe("POST", "/api/health-isf/drivers/mobile-login", json={"phone": "917-555-1004"}),
    ]

    readiness = next((p for p in probes if p.get("url") == "/api/health/readiness"), {})
    readiness_body = readiness.get("body") if isinstance(readiness.get("body"), dict) else {}
    db_connected = bool((readiness_body.get("database") or {}).get("connected"))
    detail = next((p for p in probes if p.get("url") == "/api/health/detail"), {})
    detail_body = detail.get("body") if isinstance(detail.get("body"), dict) else {}
    detail_data = detail_body.get("data") if isinstance(detail_body.get("data"), dict) else detail_body

    report = {
        "run_ts": RUN_TS,
        "base": BASE,
        "deploy_commit": (probes[0].get("body") or {}).get("deploy_commit") if isinstance(probes[0].get("body"), dict) else None,
        "postgresql_connected": db_connected,
        "readiness_status": readiness_body.get("overall_status"),
        "blocked_reasons": readiness_body.get("blocked_reasons"),
        "detail_db_check": detail_data.get("db") if isinstance(detail_data, dict) else None,
        "probes": probes,
        "verdict": "PASS" if db_connected else "FAIL",
        "render_actions_required": [] if db_connected else [
            "Open Render dashboard → PostgreSQL and confirm the database instance is Available (not suspended).",
            "Copy the Postgres Internal Connection String from the database service page.",
            "Open the web service amicor-health-isf-py → Environment → set DATABASE_URL to that internal connection string.",
            "Remove any external/public Postgres URL; Render web services must use the internal hostname.",
            "Redeploy the web service after saving DATABASE_URL.",
            "In Render Shell (web service): cd backend && alembic upgrade heads",
            "Verify GET /api/health/readiness returns 200 and database.connected=true.",
            "Verify POST /api/auth/login returns 401 (not 503) for invalid credentials.",
            "Verify POST /api/health-isf/drivers/mobile-login returns 200 for phone 917-555-1004.",
        ],
    }

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    JSON_OUT.write_text(json.dumps(report, indent=2, default=str), encoding="utf-8")

    lines = [
        "# Production Database Connectivity Audit",
        "",
        f"**Run:** {RUN_TS}",
        f"**Target:** {BASE}",
        f"**Verdict:** **{report['verdict']}**",
        f"**PostgreSQL connected:** {db_connected}",
        "",
        "## Probe summary",
        "",
        "| Endpoint | HTTP | Notes |",
        "|----------|------|-------|",
    ]
    for item in probes:
        note = ""
        if item.get("url") == "/api/health/readiness" and isinstance(item.get("body"), dict):
            note = str((item["body"].get("database") or {}).get("detail", ""))
        elif item.get("url") == "/api/health/detail" and isinstance(item.get("body"), dict):
            data = item["body"].get("data") or item["body"]
            note = str((data.get("db") if isinstance(data, dict) else ""))[:80]
        lines.append(f"| `{item.get('url')}` | {item.get('status')} | {note} |")

    if report["render_actions_required"]:
        lines.extend(["", "## Required Render actions", ""])
        for step in report["render_actions_required"]:
            lines.append(f"- {step}")

    lines.extend(["", f"Evidence: `{JSON_OUT.name}`", ""])
    MD_OUT.write_text("\n".join(lines), encoding="utf-8")

    print(json.dumps({"verdict": report["verdict"], "json": str(JSON_OUT), "md": str(MD_OUT)}, indent=2))
    return 0 if db_connected else 1


if __name__ == "__main__":
    raise SystemExit(main())
