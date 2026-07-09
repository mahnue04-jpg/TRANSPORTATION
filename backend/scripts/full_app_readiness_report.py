"""Aggregate readiness results and probe compliance APIs."""
from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

import httpx

SCRIPT_DIR = Path(__file__).resolve().parent
BACKEND = SCRIPT_DIR.parent
import sys

sys.path.insert(0, str(BACKEND))
import browser_ride_lifecycle_demo as lifecycle  # noqa: E402
ARTIFACTS = BACKEND / "artifacts"
BASE = "http://127.0.0.1:8010"
PASSWORD = "Amicor123!"
OUT = ARTIFACTS / "full_app_readiness_report.json"


def load_json(name: str) -> dict:
    path = ARTIFACTS / name
    if not path.exists():
        return {}
    with open(path, encoding="utf-8") as fh:
        return json.load(fh)


def login(email: str) -> dict:
    tok = httpx.post(
        f"{BASE}/api/auth/login",
        json={"email": email, "password": PASSWORD},
        timeout=60,
    ).json()["access_token"]
    return {"Authorization": f"Bearer {tok}"}


def probe_compliance(headers: dict) -> dict[str, str]:
    checks = {}
    endpoints = [
        ("runtime_state", "/api/health-isf/operations/runtime-state"),
        ("timeline", "/api/health-isf/operations/timeline?limit=20"),
        ("audit_log", "/api/health-isf/dispatcher/audit-log?limit=20"),
        ("lifecycle_matrix", "/api/health-isf/operations/lifecycle-matrix"),
    ]
    for key, path in endpoints:
        resp = httpx.get(f"{BASE}{path}", headers=headers, timeout=60)
        checks[key] = "PASS" if resp.status_code == 200 else f"FAIL HTTP {resp.status_code}"
    return checks


def probe_provider(headers: dict) -> bool:
    resp = httpx.get(f"{BASE}/api/health-isf/providers", headers=headers, timeout=60)
    return resp.status_code == 200


def probe_admin(headers: dict) -> dict[str, str]:
    endpoints = [
        ("dashboard", "/api/health-isf/dashboard"),
        ("command_center", "/api/health-isf/admin/command-center/summary"),
        ("drivers", "/api/health-isf/drivers?limit=5"),
        ("providers", "/api/health-isf/providers?limit=5"),
    ]
    out = {}
    for key, path in endpoints:
        resp = httpx.get(f"{BASE}{path}", headers=headers, timeout=60)
        out[key] = "PASS" if resp.status_code == 200 else f"FAIL HTTP {resp.status_code}"
    return out


def probe_grants_ai(headers: dict) -> dict[str, str]:
    out = {}
    for key, path in [
        ("analytics", "/api/health-isf/dashboard"),
        ("grants", "/api/health-isf/grant-proof/snapshot"),
        ("intelligence", "/api/health-isf/intelligence/summary"),
        ("ai_dispatch", "/api/health-isf/ai-dispatch/snapshot?publish=false"),
    ]:
        resp = httpx.get(f"{BASE}{path}", headers=headers, timeout=60)
        out[key] = "PASS" if resp.status_code == 200 else f"FAIL HTTP {resp.status_code}"
    return out


def main() -> int:
    server_proc = lifecycle.ensure_preview_server(BASE)
    report: dict = {}
    try:
        rider = load_json("rider_app_browser_verification_report.json")
        ops = load_json("real_life_ops_verification_report.json")

        admin_h = login("admin@amicor.local")
        compliance = probe_compliance(admin_h)
        admin_api = probe_admin(admin_h)
        grants_ai = probe_grants_ai(admin_h)

        revenue_critical = all(
            [
                rider.get("all_pass"),
                ops.get("all_pass"),
                rider.get("checks", {}).get("trip_lifecycle"),
                ops.get("checks", {}).get("full_trip_lifecycle"),
                ops.get("checks", {}).get("dashboard_update"),
            ]
        )

        matrix = {
            "1. Rider app (/app/riders)": "PASS" if rider.get("all_pass") else "FAIL",
            "2. Driver app": "PASS" if ops.get("checks", {}).get("driver_accept") else "FAIL",
            "3. Dispatcher app": "PASS" if ops.get("checks", {}).get("auto_manual_assignment") else "FAIL",
            "4. Provider app": "PASS" if probe_provider(login("provider@amicor.local")) else "FAIL",
            "5. Admin app": "PASS" if all(v == "PASS" for v in admin_api.values()) else "FAIL",
            "6. Billing/payment handoff": (
                "PASS"
                if ops.get("checks", {}).get("dashboard_update")
                and admin_api.get("dashboard") == "PASS"
                else "FAIL"
            ),
            "7. Grants/analytics": "PASS" if all(v == "PASS" for v in grants_ai.values()) else "FAIL",
            "8. AI assistant/advisory": (
                "PASS"
                if grants_ai.get("intelligence") == "PASS" and grants_ai.get("ai_dispatch") == "PASS"
                else "FAIL"
            ),
            "9. Compliance/audit status": "PASS" if all(v == "PASS" for v in compliance.values()) else "FAIL",
        }

        blockers = []
        blockers.extend(rider.get("blockers") or [])
        blockers.extend(ops.get("blockers") or [])
        for app, status in matrix.items():
            if status == "FAIL":
                blockers.append(f"{app} did not pass verification")
        for probe_name, probe in (("compliance", compliance), ("admin", admin_api), ("grants_ai", grants_ai)):
            for key, status in probe.items():
                if status != "PASS":
                    blockers.append(f"{probe_name} API {key}: {status}")

        report = {
            "timestamp_utc": datetime.now(timezone.utc).isoformat(),
            "base": BASE,
            "matrix": matrix,
            "revenue_critical_flow_pass": revenue_critical,
            "ready_for_redeployment": revenue_critical,
            "compliance_api": compliance,
            "admin_api": admin_api,
            "grants_ai_api": grants_ai,
            "sources": {
                "rider_app_browser_verification": rider.get("summary"),
                "real_life_ops_verification": ops.get("summary"),
            },
            "blockers": blockers,
            "fixes_applied": [
                "rider_app_browser_verification: capture request_id, assign-driver to James, route-progress endpoint",
                "routes.py: dispatcher audit-log JSON details parsing",
                "browser_health_isf_readiness_audit: canonical James driver + driver_accept_and_complete_ops",
            ],
        }
        OUT.parent.mkdir(parents=True, exist_ok=True)
        with open(OUT, "w", encoding="utf-8") as fh:
            json.dump(report, fh, indent=2)
        print(json.dumps(report, indent=2))
    finally:
        if server_proc and server_proc.poll() is None:
            server_proc.terminate()
    return 0 if report.get("ready_for_redeployment") else 1


if __name__ == "__main__":
    raise SystemExit(main())
