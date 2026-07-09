"""Single-ride driver assignment → completion proof with API + Driver App browser checks."""
from __future__ import annotations

import json
import os
import re
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

import httpx

SCRIPT_DIR = Path(__file__).resolve().parent
BACKEND_ROOT = SCRIPT_DIR.parent
sys.path.insert(0, str(BACKEND_ROOT))
sys.path.insert(0, str(SCRIPT_DIR))

from local_test_reset import main as run_test_reset
from server_runtime import BASE, ensure_server_running

PASSWORD = os.getenv("AMICOR_SEED_PASSWORD", "Amicor123!")
JAMES_PHONE = "9175551001"


def _login(client: httpx.Client, email: str) -> str:
    resp = client.post("/api/auth/login", json={"email": email, "password": PASSWORD})
    resp.raise_for_status()
    return str(resp.json().get("token") or resp.json().get("access_token"))


def _find_james(client: httpx.Client, headers: dict) -> tuple[str, str]:
    rows = client.get("/api/health-isf/drivers?limit=200", headers=headers).json()
    james = next(
        (row for row in rows if str(row.get("phone", "")).replace("-", "").replace(" ", "") == JAMES_PHONE),
        None,
    )
    if not james:
        raise RuntimeError("James Smith driver not found")
    org = client.get("/api/auth/me", headers=headers)
    org_id = str((org.json() or {}).get("organization_id") or "ca8d0c7c-1fff-4465-99d7-75a1fc51543e")
    return str(james["id"]), org_id


def _create_ride(client: httpx.Client, rider_headers: dict) -> tuple[str, str, str, str]:
    stamp = datetime.now(timezone.utc).strftime("%H%M%S")
    rider_phone = f"646-555-{stamp[-4:]}"
    rider_name = f"Driver Proof Rider {stamp}"
    payload = {
        "rider_name": rider_name,
        "rider_phone": rider_phone,
        "pickup_address": f"100 Proof Pickup {stamp}, New York, NY 10001",
        "dropoff_address": f"200 Proof Dropoff {stamp}, New York, NY 10002",
        "ride_type": "healthcare",
        "recurring": False,
        "notes": f"driver assignment completion proof {stamp}",
    }
    resp = client.post("/api/health-isf/customer-requests", headers=rider_headers, json=payload)
    resp.raise_for_status()
    body = resp.json()
    return str(body["ride_id"]), str(body["id"]), rider_phone, rider_name


def _assign_driver(
    client: httpx.Client,
    headers: dict,
    request_id: str,
    ride_id: str,
    driver_id: str,
    org_id: str,
) -> None:
    client.post(
        f"/api/health-isf/dispatcher/customer-requests/{request_id}/approve",
        headers=headers,
        params={"organization_id": org_id},
    ).raise_for_status()
    ride = client.get(f"/api/health-isf/rides/{ride_id}", headers=headers).json()
    if str(ride.get("driver_id") or "") == driver_id:
        return
    if ride.get("driver_id"):
        client.patch(
            f"/api/health-isf/dispatcher/rides/{ride_id}/reassign-driver",
            headers=headers,
            json={"driver_id": driver_id},
        ).raise_for_status()
    else:
        client.post(
            f"/api/health-isf/dispatcher/customer-requests/{request_id}/assign-driver",
            headers=headers,
            params={"organization_id": org_id},
            json={"driver_id": driver_id},
        ).raise_for_status()


def _driver_lifecycle_complete(client: httpx.Client, headers: dict, driver_id: str, ride_id: str) -> None:
    accept = client.post(
        f"/api/health-isf/drivers/{driver_id}/accept-ride",
        headers=headers,
        json={"ride_id": ride_id},
    )
    if accept.status_code >= 400:
        raise RuntimeError(f"accept-ride: {accept.status_code} {accept.text[:200]}")

    for step in (
        "en_route_pickup",
        "arrived_pickup",
        "rider_loaded",
        "trip_in_progress",
        "arrived_destination",
    ):
        resp = client.post(
            f"/api/health-isf/drivers/{driver_id}/route-progress",
            headers=headers,
            json={"ride_id": ride_id, "target_state": step},
        )
        if resp.status_code >= 400:
            raise RuntimeError(f"route-progress {step}: {resp.status_code} {resp.text[:200]}")

    resp = client.post(
        f"/api/health-isf/drivers/{driver_id}/dropoff-complete",
        headers=headers,
        json={"ride_id": ride_id},
    )
    if resp.status_code >= 400:
        raise RuntimeError(f"dropoff-complete: {resp.status_code} {resp.text[:200]}")


def _browser_proof(
    *,
    passenger_marker: str,
    expect_assigned: bool,
    expect_cleared: bool = False,
    expect_earnings: bool = False,
) -> dict:
    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        return {"ok": False, "error": "playwright_not_installed"}

    url = f"{BASE}/static/ops-shell.html?platform_reset=1"
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=True)
        context = browser.new_context()
        page = context.new_page()
        try:
            token = _login(httpx.Client(base_url=BASE, timeout=60), "driver@amicor.local")
            session_json = json.dumps({"access_token": token, "email": "driver@amicor.local"})
            context.add_init_script(
                f'localStorage.setItem("amicor_session", {json.dumps(session_json)});'
            )
            page.goto(url, wait_until="domcontentloaded", timeout=90000)
            if page.locator("#role-select").count():
                page.select_option("#role-select", "driver")
            page.wait_for_timeout(3000)
            page.evaluate(
                """async () => {
                  if (window.AmiOpsShellActions && window.AmiOpsShellActions.refreshData) {
                    await window.AmiOpsShellActions.refreshData();
                  }
                  if (window.AmiOpsShellActions && window.AmiOpsShellActions.refreshDriverWorkflowData) {
                    await window.AmiOpsShellActions.refreshDriverWorkflowData({ lastAction: 'assignment proof' });
                  }
                }"""
            )
            page.wait_for_timeout(5000)
            body = page.locator("body").inner_text().lower()
            primary_card = ""
            if page.locator('.driver-workflow-card:has-text("Primary Workflow")').count():
                primary_card = page.locator('.driver-workflow-card:has-text("Primary Workflow")').first.inner_text().lower()
            snapshot = page.evaluate(
                """() => {
                  const st = window.AmiOpsShellState || {};
                  const app = st.driverApp || {};
                  const wf = st.driverWorkflow || {};
                  const activeRide = wf.activeRide || {};
                  const earn = wf.earnings || {};
                  const queue = Array.isArray(app.tripQueue) ? app.tripQueue : [];
                  return {
                    earningsToday: Number(app.earningsToday || earn.earnings_today_usd || 0),
                    completedTrips: Number(app.completedTrips || earn.trip_count || 0),
                    activeTripId: String(app.activeTripId || ''),
                    driverId: String((wf.driverId || app.currentDriverId || '')),
                    queueLength: queue.length,
                    hasActiveRide: Boolean(activeRide.has_active_ride),
                    activeRideId: String((activeRide.ride || {}).id || ''),
                    acceptDisabled: document.querySelector('[data-driver-action="accept_trip"]')?.disabled === true
                  };
                }"""
            )
            marker = passenger_marker.lower()
            checks: dict[str, bool] = {
                "driver_bound": bool(str((snapshot or {}).get("driverId") or "").strip()),
                "no_uuid_leak": len(
                    re.findall(
                        r"[0-9a-f]{8}(?:-[0-9a-f]{4}){3}-[0-9a-f]{12}",
                        primary_card or body,
                    )
                )
                == 0,
            }
            if expect_assigned:
                checks["passenger_visible"] = marker in (primary_card or body)
                checks["active_trip_set"] = bool(str((snapshot or {}).get("activeTripId") or "").strip())
                checks["backend_active_ride"] = bool((snapshot or {}).get("hasActiveRide")) or bool(
                    str((snapshot or {}).get("activeRideId") or "").strip()
                )
                checks["queue_nonempty"] = int((snapshot or {}).get("queueLength") or 0) > 0
                checks["accept_enabled"] = not bool((snapshot or {}).get("acceptDisabled"))
                checks["not_awaiting_assignment"] = "awaiting assignment" not in (primary_card or "")
            if expect_cleared:
                checks["no_active_trip"] = not str((snapshot or {}).get("activeTripId") or "").strip()
                checks["no_passenger_in_primary"] = marker not in (primary_card or "")
            if expect_earnings:
                earnings_today = float((snapshot or {}).get("earningsToday") or 0)
                completed_trips = int((snapshot or {}).get("completedTrips") or 0)
                checks["earnings_nonzero"] = earnings_today > 0
                checks["completed_trips_positive"] = completed_trips >= 1
            return {"ok": all(checks.values()), "checks": checks, "snapshot": snapshot, "url": url}
        finally:
            context.close()
            browser.close()


def main() -> int:
    print("=== DRIVER ASSIGNMENT COMPLETION PROOF ===")
    flags: dict[str, bool] = {}

    flags["TEST_RESET_PASS"] = run_test_reset() == 0
    ensure_server_running(force_restart=True)
    time.sleep(2)

    client = httpx.Client(base_url=BASE, timeout=120.0)
    dtoken = _login(client, "dispatcher@amicor.local")
    dheaders = {"Authorization": f"Bearer {dtoken}"}
    rtoken = _login(client, "rider@amicor.local")
    rheaders = {"Authorization": f"Bearer {rtoken}"}
    driver_id, org_id = _find_james(client, dheaders)

    ride_id, request_id, _, rider_name = _create_ride(client, rheaders)
    flags["RIDE_CREATED"] = bool(ride_id)
    _assign_driver(client, dheaders, request_id, ride_id, driver_id, org_id)

    ride = client.get(f"/api/health-isf/rides/{ride_id}", headers=dheaders).json()
    flags["RIDE_ASSIGNED"] = str(ride.get("driver_id") or "") == driver_id

    active_ride = client.get(
        f"/api/health-isf/drivers/{driver_id}/active-ride",
        headers=dheaders,
        params={"organization_id": org_id},
    )
    flags["ACTIVE_RIDE_API_OK"] = active_ride.status_code == 200
    active_body = active_ride.json() if active_ride.status_code == 200 else {}
    flags["ACTIVE_RIDE_MATCHES"] = str((active_body.get("ride") or {}).get("id") or "") == ride_id

    assigned = client.get(
        f"/api/health-isf/drivers/{driver_id}/assigned-rides",
        headers=dheaders,
        params={"organization_id": org_id},
    )
    flags["ASSIGNED_RIDES_API_OK"] = assigned.status_code == 200
    flags["ASSIGNED_RIDES_CONTAINS_RIDE"] = any(
        str(row.get("id") or "") == ride_id for row in (assigned.json() if assigned.status_code == 200 else [])
    )

    browser_assigned = _browser_proof(passenger_marker=rider_name, expect_assigned=True)
    flags["BROWSER_ASSIGNED_PASS"] = bool(browser_assigned.get("ok"))
    if not flags["BROWSER_ASSIGNED_PASS"]:
        print("browser_assigned_checks:", json.dumps(browser_assigned.get("checks"), indent=2))

    _driver_lifecycle_complete(client, dheaders, driver_id, ride_id)

    completed = client.get(f"/api/health-isf/rides/{ride_id}", headers=dheaders).json()
    flags["RIDE_COMPLETED"] = str(completed.get("lifecycle_state") or completed.get("status") or "").lower() == "completed"

    earnings = client.get(f"/api/health-isf/drivers/{driver_id}/earnings", headers=dheaders).json()
    flags["EARNINGS_POSITIVE"] = float(earnings.get("earnings_lifetime_usd") or 0) > 0
    flags["TRIP_COUNT_POSITIVE"] = int(earnings.get("trip_count") or 0) >= 1

    completed_rides = client.get(
        f"/api/health-isf/drivers/{driver_id}/completed-rides",
        headers=dheaders,
        params={"limit": 10},
    ).json()
    flags["COMPLETED_RIDES_CONTAINS_RIDE"] = any(str(row.get("id") or "") == ride_id for row in completed_rides)

    billing = client.get("/api/health-isf/operations/billing-handoffs", headers=dheaders, params={"limit": 20}).json()
    flags["BILLING_HANDOFF_READY"] = any(
        str(row.get("ride_id") or "") == ride_id
        and str(row.get("billing_status") or row.get("handoff_status") or row.get("status") or "").lower() == "ready"
        for row in billing
    )

    revenue = client.get("/api/health-isf/operations/admin-revenue", headers=dheaders).json()
    flags["AMICOR_REVENUE_RECORDED"] = float(revenue.get("platform_revenue_total_usd") or 0) > 0

    active_after = client.get(
        f"/api/health-isf/drivers/{driver_id}/active-ride",
        headers=dheaders,
        params={"organization_id": org_id},
    ).json()
    flags["ACTIVE_RIDE_CLEARED"] = not bool(active_after.get("has_active_ride"))

    driver_row = client.get(f"/api/health-isf/drivers/{driver_id}", headers=dheaders).json()
    flags["DRIVER_AVAILABLE"] = str(driver_row.get("availability_state") or driver_row.get("status") or "").lower() in {
        "available",
        "online",
    }

    browser_done = _browser_proof(
        passenger_marker=rider_name,
        expect_assigned=False,
        expect_cleared=True,
        expect_earnings=True,
    )
    flags["BROWSER_POST_COMPLETE_PASS"] = bool(browser_done.get("ok"))
    if not flags["BROWSER_POST_COMPLETE_PASS"]:
        print("browser_post_complete_checks:", json.dumps(browser_done.get("checks"), indent=2))

    for key, value in flags.items():
        print(f"{key}={value}")

    result_pass = all(flags.values())
    print(f"RESULT={'PASS' if result_pass else 'FAIL'}")
    return 0 if result_pass else 1


if __name__ == "__main__":
    raise SystemExit(main())
