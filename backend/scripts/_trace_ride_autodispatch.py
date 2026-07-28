#!/usr/bin/env python3
"""Production read-only trace for a specific ride auto-dispatch failure."""
from __future__ import annotations

import json
import os
import time
from datetime import datetime, timezone
from pathlib import Path

import requests

BASE = os.getenv("AMICOR_PUBLIC_URL", "https://amicor-health-isf-py.onrender.com")
RIDE_ID = os.getenv("TRACE_RIDE_ID", "41c50fb9-7bfa-4f8e-8b88-318cbe5b75fd")
PASSWORD = os.getenv("AMICOR_SEED_PASSWORD", "Amicor123!")
OUT = Path(__file__).resolve().parents[2] / "PRODUCTION_QA_EVIDENCE" / f"AUTODISPATCH_TRACE_{RIDE_ID[:8]}_{datetime.now(timezone.utc).strftime('%Y%m%d%H%M%S')}.json"


def wake() -> dict:
    for i in range(6):
        try:
            return requests.get(f"{BASE}/api/health/live", timeout=240).json()
        except Exception as exc:
            print(f"wake attempt {i+1}: {exc}")
            time.sleep(20)
    return {}


def login(email: str) -> dict:
    sync_key = os.getenv("AMICOR_DEPLOYMENT_SYNC_KEY", PASSWORD).strip()
    r = requests.post(f"{BASE}/api/auth/login", json={"email": email, "password": PASSWORD}, timeout=240)
    if r.status_code != 200 and sync_key:
        requests.post(
            f"{BASE}/api/auth/deployment/sync-seed-users",
            headers={"X-Amicor-Deployment-Key": sync_key},
            timeout=240,
        )
        r = requests.post(f"{BASE}/api/auth/login", json={"email": email, "password": PASSWORD}, timeout=240)
    r.raise_for_status()
    return r.json()


def get_json(path: str, headers: dict, **params) -> tuple[int, object, float]:
    started = time.perf_counter()
    r = requests.get(f"{BASE}{path}", headers=headers, params=params or None, timeout=240)
    elapsed = time.perf_counter() - started
    try:
        body = r.json()
    except Exception:
        body = r.text[:500]
    return r.status_code, body, elapsed


def main() -> int:
    report: dict = {"ride_id": RIDE_ID, "base": BASE, "timings": {}}
    report["health"] = wake()

    disp = login("dispatcher@amicor.local")
    dh = {"Authorization": f"Bearer {disp['access_token']}"}
    report["dispatcher_org"] = disp.get("organization_id")

    for label, path, params in [
        ("ride", f"/api/health-isf/rides/{RIDE_ID}", {}),
        ("dispatch_history", f"/api/health-isf/rides/{RIDE_ID}/dispatch-history", {}),
        ("ride_history", f"/api/health-isf/rides/{RIDE_ID}/history", {}),
        ("workflow_path", f"/api/health-isf/rides/{RIDE_ID}/workflow-path", {}),
        ("dispatch_queue", "/api/health-isf/dispatch/queue", {"limit": 200}),
        ("customer_requests", "/api/health-isf/customer-requests", {"limit": 200}),
        ("drivers", "/api/health-isf/drivers", {"limit": 100}),
    ]:
        status, body, elapsed = get_json(path, dh, **params)
        report["timings"][label] = round(elapsed, 3)
        if label in {"dispatch_queue", "customer_requests", "drivers"} and isinstance(body, list):
            if label == "dispatch_queue":
                report[label] = [row for row in body if str(row.get("ride_id") or row.get("id") or "") == RIDE_ID]
            elif label == "customer_requests":
                report[label] = [row for row in body if str(row.get("ride_id") or "") == RIDE_ID]
            else:
                report[label] = body
        else:
            report[label] = {"status": status, "body": body}

    req_rows = report.get("customer_requests") or []
    request_id = req_rows[0]["id"] if req_rows else None
    report["request_id"] = request_id

    driver_1004 = None
    for d in report.get("drivers") or []:
        phone = str(d.get("phone") or "").replace("-", "")
        if phone.endswith("9175551004") or phone.endswith("5551004") or "1004" in str(d.get("phone") or ""):
            driver_1004 = d
            break
    report["driver_1004_summary"] = driver_1004

    if driver_1004:
        did = driver_1004["id"]
        for label, path in [
            ("driver_active_ride", f"/api/health-isf/drivers/{did}/active-ride"),
            ("driver_active_offer", f"/api/health-isf/drivers/{did}/active-offer"),
            ("driver_live_workspace", f"/api/health-isf/drivers/{did}/live-workspace"),
        ]:
            status, body, elapsed = get_json(path, dh)
            report["timings"][label] = round(elapsed, 3)
            report[label] = {"status": status, "body": body}

    rider = login("rider@amicor.local")
    rh = {"Authorization": f"Bearer {rider['access_token']}"}
    report["rider_org"] = rider.get("organization_id")
    if req_rows:
        phone = req_rows[0].get("rider_phone")
        if phone:
            status, body, elapsed = get_json(
                "/api/health-isf/customers/workspace/live-tracking",
                rh,
                rider_phone=phone,
                limit=20,
            )
            report["timings"]["rider_live_tracking"] = round(elapsed, 3)
            report["rider_live_tracking"] = {"status": status, "body": body}

    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(report, indent=2, default=str), encoding="utf-8")
    print(OUT)
    print(json.dumps({k: report[k] for k in ["ride_id", "request_id", "ride", "dispatch_history", "driver_1004_summary", "customer_requests"] if k in report}, indent=2)[:12000])
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
