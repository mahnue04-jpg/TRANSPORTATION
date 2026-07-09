"""One-shot E2E lifecycle + cross-surface sync verification."""
from __future__ import annotations

import json
import os
import sys
from pathlib import Path

import httpx

SCRIPT_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(SCRIPT_DIR.parent))
sys.path.insert(0, str(SCRIPT_DIR))

from app.helpers import uuid4
from local_test_reset import main as run_reset

BASE = os.getenv("AMICOR_BROWSER_BASE", "http://127.0.0.1:8011").rstrip("/")
PWD = os.getenv("AMICOR_SEED_PASSWORD", "Amicor123!")
JAMES = "4bc0e517-d60d-4d45-bc20-a14b1e4aa407"


def _norm(v: str) -> str:
    return str(v or "").strip().lower().replace("ridestatus.", "")


def _login(c: httpx.Client, email: str) -> str:
    b = c.post("/api/auth/login", json={"email": email, "password": PWD}).json()
    return str(b.get("token") or b.get("access_token"))


def _status_from_ride(row: dict) -> str:
    return _norm(row.get("lifecycle_state") or row.get("status"))


def _collect_surfaces(c: httpx.Client, h: dict, ride_id: str, driver_id: str, rider_phone: str) -> dict:
    ride = c.get(f"/api/health-isf/rides/{ride_id}", headers=h).json()
    queue = c.get("/api/health-isf/dispatch/queue", headers=h, params={"limit": 200}).json()
    active = c.get("/api/health-isf/dispatch/active-assignments", headers=h, params={"limit": 200}).json()
    driver_active = c.get(f"/api/health-isf/drivers/{driver_id}/active-ride", headers=h).json()
    earnings = c.get(f"/api/health-isf/drivers/{driver_id}/earnings", headers=h).json()
    completed = c.get(f"/api/health-isf/drivers/{driver_id}/completed-rides", headers=h, params={"limit": 20}).json()
    billing = c.get("/api/health-isf/operations/billing-handoffs", headers=h, params={"limit": 50}).json()
    revenue = c.get("/api/health-isf/operations/admin-revenue", headers=h).json()
    timeline = c.get(f"/api/health-isf/rides/{ride_id}/history", headers=h).json()
    rider_hist = c.get("/api/health-isf/customers/workspace/history", headers=h, params={"rider_phone": rider_phone, "limit": 20}).json()
    rides_list = c.get("/api/health-isf/rides", headers=h, params={"limit": 50}).json()
    list_row = next((r for r in rides_list if r.get("id") == ride_id), {})
    q_row = next((r for r in queue if r.get("ride_id") == ride_id), None)
    a_row = next((r for r in active if r.get("ride_id") == ride_id), None)
    bill_row = next((r for r in billing if r.get("ride_id") == ride_id), None)
    comp_row = next((r for r in completed if r.get("id") == ride_id), None)
    rider_row = next((r for r in rider_hist.get("history", []) if r.get("ride_id") == ride_id), None)
    return {
        "ride": _status_from_ride(ride),
        "rides_list": _status_from_ride(list_row),
        "dispatch_queue_present": q_row is not None,
        "dispatch_queue_status": _norm((q_row or {}).get("ride_status") or (q_row or {}).get("assignment_state")),
        "active_assignment_present": a_row is not None,
        "active_assignment_status": _norm((a_row or {}).get("assignment_state")),
        "driver_active_ride": bool(driver_active.get("has_active_ride")),
        "driver_active_status": _status_from_ride((driver_active.get("ride") or {})),
        "earnings": float(earnings.get("earnings_lifetime_usd") or 0),
        "completed_present": comp_row is not None,
        "billing_ready": str((bill_row or {}).get("billing_status") or "").lower() == "ready",
        "platform_revenue": float(revenue.get("platform_revenue_total_usd") or 0),
        "gross_revenue": float(revenue.get("ride_revenue_total_usd") or 0),
        "timeline_has_completed": any(_norm(i.get("to_status")) == "completed" for i in timeline),
        "rider_history_status": _norm((rider_row or {}).get("dispatch_status")),
        "timeline_states": [_norm(i.get("to_status")) for i in timeline],
    }


def main() -> int:
    if run_reset() != 0:
        print("RESET_FAIL")
        return 1

    c = httpx.Client(base_url=BASE, timeout=120)
    dt = _login(c, "dispatcher@amicor.local")
    rt = _login(c, "rider@amicor.local")
    dh = {"Authorization": f"Bearer {dt}"}
    rh = {"Authorization": f"Bearer {rt}"}

    suffix = uuid4()[:8]
    phone_digits = "".join(ch for ch in suffix if ch.isdigit()) or "1234"
    phone = f"646555{phone_digits[-4:].zfill(4)}"
    created_resp = c.post(
        "/api/health-isf/customer-requests",
        headers=rh,
        json={
            "rider_name": f"E2E Sync {suffix}",
            "rider_phone": phone,
            "pickup_address": f"10 Sync Pickup {suffix}, NY",
            "dropoff_address": f"20 Sync Dropoff {suffix}, NY",
            "ride_type": "healthcare",
            "recurring": False,
            "notes": "e2e sync verify",
        },
    )
    if created_resp.status_code >= 400:
        print("CREATE_FAIL", created_resp.status_code, created_resp.text[:400])
        return 1
    created = created_resp.json()
    ride_id = str(created.get("ride_id") or "")
    req_id = str(created.get("id") or "")
    if not ride_id or not req_id:
        print("CREATE_MISSING_IDS", json.dumps(created, indent=2)[:400])
        return 1

    stages: list[tuple[str, callable]] = []

    def snap(label: str) -> None:
        s = _collect_surfaces(c, dh, ride_id, JAMES, phone)
        print(f"STAGE {label}", json.dumps(s, indent=2))
        stages.append((label, s))

    snap("created")
    assert _collect_surfaces(c, dh, ride_id, JAMES, phone)["dispatch_queue_present"]

    c.post(f"/api/health-isf/dispatcher/customer-requests/{req_id}/approve", headers=dh).raise_for_status()
    ride = c.get(f"/api/health-isf/rides/{ride_id}", headers=dh).json()
    if str(ride.get("driver_id") or "") != JAMES:
        resp = c.post(
            f"/api/health-isf/dispatcher/customer-requests/{req_id}/assign-driver",
            headers=dh,
            json={"driver_id": JAMES},
        )
        if resp.status_code >= 400:
            c.patch(
                f"/api/health-isf/dispatcher/rides/{ride_id}/reassign-driver",
                headers=dh,
                json={"driver_id": JAMES},
            ).raise_for_status()
    snap("assigned")

    steps = [
        ("accepted", lambda: c.post(f"/api/health-isf/drivers/{JAMES}/accept-ride", headers=dh, json={"ride_id": ride_id})),
        ("arrived_pickup", lambda: c.post(f"/api/health-isf/drivers/{JAMES}/route-progress", headers=dh, json={"ride_id": ride_id, "target_state": "arrived_pickup"})),
        ("rider_loaded", lambda: c.post(f"/api/health-isf/drivers/{JAMES}/route-progress", headers=dh, json={"ride_id": ride_id, "target_state": "rider_loaded"})),
        ("trip_in_progress", lambda: c.post(f"/api/health-isf/drivers/{JAMES}/route-progress", headers=dh, json={"ride_id": ride_id, "target_state": "trip_in_progress"})),
        ("arrived_destination", lambda: c.post(f"/api/health-isf/drivers/{JAMES}/route-progress", headers=dh, json={"ride_id": ride_id, "target_state": "arrived_destination"})),
        ("completed", lambda: c.post(f"/api/health-isf/drivers/{JAMES}/dropoff-complete", headers=dh, json={"ride_id": ride_id})),
    ]
    for label, fn in steps:
        r = fn()
        if r.status_code >= 400:
            print(f"STEP_FAIL {label}", r.status_code, r.text[:300])
            return 1
        snap(label)
        s = stages[-1][1]
        if s["ride"] and s["rider_history_status"] and s["rider_history_status"] != s["ride"]:
            print(f"SYNC_MISMATCH {label} ride={s['ride']} rider_history={s['rider_history_status']}")
            return 1

    final = stages[-1][1]
    checks = {
        "ride_completed": final["ride"] == "completed",
        "rides_list_completed": final["rides_list"] == "completed",
        "queue_removed": not final["dispatch_queue_present"],
        "active_assignment_removed": not final["active_assignment_present"],
        "driver_active_cleared": not final["driver_active_ride"],
        "completed_history": final["completed_present"],
        "earnings_positive": final["earnings"] > 0,
        "billing_ready": final["billing_ready"],
        "platform_revenue": final["platform_revenue"] > 0,
        "gross_revenue": final["gross_revenue"] > 0,
        "timeline_completed": final["timeline_has_completed"],
        "rider_history_completed": final["rider_history_status"] == "completed",
        "status_sync_ride_vs_list": final["ride"] == final["rides_list"],
    }
    print("CHECKS", json.dumps(checks, indent=2))
    ok = all(checks.values())
    print("RESULT", "PASS" if ok else "FAIL")
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
