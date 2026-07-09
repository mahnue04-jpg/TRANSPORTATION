"""Platform stability + post-test persistence verification for local 8011."""
from __future__ import annotations

import json
import os
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import httpx

SCRIPT_DIR = Path(__file__).resolve().parent
BACKEND_ROOT = SCRIPT_DIR.parent
ARTIFACTS = BACKEND_ROOT / "artifacts"
sys.path.insert(0, str(BACKEND_ROOT))
sys.path.insert(0, str(SCRIPT_DIR))

from server_runtime import BASE, ensure_server_running, verify_server_persistence  # noqa: E402

PASSWORD = os.getenv("AMICOR_SEED_PASSWORD", "Amicor123!")
REPORT_PATH = ARTIFACTS / "platform_stability_report.json"


def _login(client: httpx.Client, email: str) -> str:
    resp = client.post("/api/auth/login", json={"email": email, "password": PASSWORD})
    resp.raise_for_status()
    return str(resp.json().get("token") or resp.json().get("access_token"))


def _probe_surfaces(client: httpx.Client, headers: dict, org_id: str, driver_id: str) -> dict[str, bool]:
    checks: dict[str, bool] = {}
    endpoints = {
        "driver_app_shell": "/static/ops-shell.html",
        "rider_app": "/app/riders",
        "dispatch_app": "/app/dispatch",
        "billing_app": "/app/billing",
        "ai_assistant_app": "/app/ai-assistant",
        "driver_live_workspace": f"/api/health-isf/drivers/{driver_id}/live-workspace",
        "driver_earnings": f"/api/health-isf/drivers/{driver_id}/earnings",
        "dispatch_queue": f"/api/health-isf/dispatch/queue?organization_id={org_id}&limit=20",
        "active_assignments": "/api/health-isf/dispatch/active-assignments?limit=20",
        "billing_handoffs": "/api/health-isf/operations/billing-handoffs?limit=20",
        "admin_revenue": "/api/health-isf/operations/admin-revenue",
        "ai_dispatch": f"/api/health-isf/ai-dispatch/snapshot?organization_id={org_id}&publish=false",
    }
    for key, path in endpoints.items():
        try:
            timeout = 90.0 if key == "ai_dispatch" else 30.0
            if path.startswith("/api/"):
                checks[key] = client.get(path, headers=headers, timeout=timeout).status_code == 200
            else:
                checks[key] = client.get(path, timeout=timeout).status_code == 200
        except Exception:
            checks[key] = False
    return checks


def _run_one_ride(client: httpx.Client, headers: dict, drheaders: dict, rheaders: dict, org_id: str, driver_id: str) -> dict[str, Any]:
    stamp = datetime.now(timezone.utc).strftime("%H%M%S")
    rider_phone = f"646-555-{stamp[-4:]}"
    create = client.post(
        "/api/health-isf/customer-requests",
        headers=rheaders,
        json={
            "rider_name": f"Stability Manual {stamp}",
            "rider_phone": rider_phone,
            "pickup_address": f"10 Stability Pickup {stamp}, New York, NY 10001",
            "dropoff_address": f"20 Stability Dropoff {stamp}, New York, NY 10002",
            "ride_type": "healthcare",
            "recurring": False,
            "notes": "platform stability manual ride",
        },
    )
    create.raise_for_status()
    req = create.json()
    ride_id, request_id = str(req["ride_id"]), str(req["id"])

    client.post(
        f"/api/health-isf/dispatcher/customer-requests/{request_id}/approve",
        headers=headers,
        params={"organization_id": org_id},
    ).raise_for_status()
    ride = client.get(f"/api/health-isf/rides/{ride_id}", headers=headers).json()
    current_driver = str(ride.get("driver_id") or "")
    if current_driver == driver_id:
        pass
    elif current_driver:
        reassign = client.patch(
            f"/api/health-isf/dispatcher/rides/{ride_id}/reassign-driver",
            headers=headers,
            json={"driver_id": driver_id},
        )
        if reassign.status_code >= 400:
            assign = client.post(
                f"/api/health-isf/dispatcher/customer-requests/{request_id}/assign-driver",
                headers=headers,
                params={"organization_id": org_id},
                json={"driver_id": driver_id},
            )
            if assign.status_code >= 400 and current_driver:
                driver_id = current_driver
    else:
        client.post(
            f"/api/health-isf/dispatcher/customer-requests/{request_id}/assign-driver",
            headers=headers,
            params={"organization_id": org_id},
            json={"driver_id": driver_id},
        ).raise_for_status()

    client.post(
        f"/api/health-isf/drivers/{driver_id}/accept-ride",
        headers=headers,
        json={"ride_id": ride_id},
    ).raise_for_status()
    for step in ("en_route_pickup", "arrived_pickup", "rider_loaded", "trip_in_progress", "arrived_destination"):
        client.post(
            f"/api/health-isf/drivers/{driver_id}/route-progress",
            headers=headers,
            json={"ride_id": ride_id, "target_state": step},
        ).raise_for_status()
    client.post(
        f"/api/health-isf/drivers/{driver_id}/dropoff-complete",
        headers=headers,
        json={"ride_id": ride_id},
    ).raise_for_status()

    time.sleep(1)
    earnings = client.get(f"/api/health-isf/drivers/{driver_id}/earnings", headers=headers).json()
    financial = client.get(f"/api/health-isf/rides/{ride_id}/financial-summary", headers=headers)
    admin = client.get("/api/health-isf/operations/admin-revenue", headers=headers).json()
    rider_history = client.get(
        "/api/health-isf/customers/workspace/history",
        headers=rheaders,
        params={"rider_phone": rider_phone, "limit": 20},
    ).json()
    completed = client.get(
        f"/api/health-isf/drivers/{driver_id}/completed-rides",
        headers=headers,
        params={"organization_id": org_id, "limit": 10},
    ).json()
    billing = client.get("/api/health-isf/operations/billing-handoffs", headers=headers, params={"limit": 20}).json()
    active = client.get("/api/health-isf/dispatch/active-assignments", headers=headers, params={"limit": 50}).json()

    return {
        "ride_id": ride_id,
        "rider_phone": rider_phone,
        "checks": {
            "rider_history_completed": any(
                row.get("ride_id") == ride_id and str(row.get("dispatch_status") or "").lower() == "completed"
                for row in rider_history.get("history", [])
            ),
            "driver_completed_history": any(row.get("id") == ride_id for row in completed),
            "driver_earnings_positive": float(earnings.get("earnings_today_usd") or 0.0) > 0.0,
            "billing_handoff_visible": any(row.get("ride_id") == ride_id for row in billing),
            "platform_revenue_visible": float(admin.get("platform_revenue_total_usd") or 0.0) > 0.0,
            "financial_summary_exists": financial.status_code == 200,
            "not_in_active_assignments": not any(row.get("ride_id") == ride_id for row in active),
        },
        "earnings": earnings,
        "admin_revenue": admin,
    }


def _priority_issues(flags: dict[str, bool], surfaces: dict[str, bool]) -> list[dict[str, str]]:
    issues: list[dict[str, str]] = []
    if not flags.get("server_healthy_after_test"):
        issues.append({"priority": "P0", "issue": "Backend not reachable on 8011 after verification"})
    if not flags.get("server_persistence"):
        issues.append({"priority": "P0", "issue": "Server does not persist after lifecycle scripts exit"})
    for key, ok in surfaces.items():
        if not ok:
            issues.append({"priority": "P1", "issue": f"Surface/API unavailable: {key}"})
    ride_checks = flags.get("manual_ride_checks") or {}
    for key, ok in ride_checks.items():
        if not ok:
            issues.append({"priority": "P1", "issue": f"Manual ride verification failed: {key}"})
    if not issues:
        issues.append({"priority": "INFO", "issue": "No blocking issues detected in local stability run"})
    return issues


def main() -> int:
    ARTIFACTS.mkdir(parents=True, exist_ok=True)
    runtime = ensure_server_running(force_restart=False)
    client = httpx.Client(base_url=BASE, timeout=120.0)

    dtoken = _login(client, "dispatcher@amicor.local")
    dheaders = {"Authorization": f"Bearer {dtoken}"}
    me = client.get("/api/auth/me", headers=dheaders)
    org_id = ""
    if me.status_code == 200:
        org_id = str((me.json() or {}).get("organization_id") or "")
    drivers = client.get("/api/health-isf/drivers?limit=50", headers=dheaders).json()
    james = next(
        (d for d in drivers if "9175551001" in str(d.get("phone", "")).replace("-", "").replace(" ", "")),
        drivers[0] if drivers else None,
    )
    if not james:
        raise RuntimeError("No driver available for stability verification")
    driver_id = str(james["id"])
    if not org_id:
        org_id = "ca8d0c7c-1fff-4465-99d7-75a1fc51543e"

    drheaders = {"Authorization": f"Bearer {_login(client, 'driver@amicor.local')}"}
    rheaders = {"Authorization": f"Bearer {_login(client, 'rider@amicor.local')}"}

    surfaces = _probe_surfaces(client, dheaders, org_id, driver_id)
    ride_result = _run_one_ride(client, dheaders, drheaders, rheaders, org_id, driver_id)
    persistence = verify_server_persistence()

    report = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "base_url": BASE,
        "server_runtime": runtime,
        "server_persistence": persistence,
        "surface_checks": surfaces,
        "manual_ride": ride_result,
        "flags": {
            "server_healthy_after_test": persistence.get("healthy") is True,
            "server_persistence": persistence.get("healthy") is True,
            "all_surfaces_up": all(surfaces.values()),
            "manual_ride_checks": ride_result["checks"],
        },
    }
    report["issues"] = _priority_issues(report["flags"], surfaces)
    report["result"] = (
        "PASS"
        if report["flags"]["server_healthy_after_test"]
        and all(ride_result["checks"].values())
        and all(
            surfaces.get(k) is True
            for k in (
                "driver_app_shell",
                "rider_app",
                "dispatch_app",
                "billing_app",
                "ai_assistant_app",
            )
        )
        else "FAIL"
    )

    REPORT_PATH.write_text(json.dumps(report, indent=2), encoding="utf-8")
    print(json.dumps(report, indent=2))
    print(f"RESULT={report['result']}")
    print(f"REPORT={REPORT_PATH}")
    print(f"SERVER_STILL_RUNNING={str(persistence.get('healthy')).lower()}")
    return 0 if report["result"] == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
