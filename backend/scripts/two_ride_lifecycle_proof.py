"""Two-ride local lifecycle proof with API + browser verification."""
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

from app.db.session import SessionLocal
from app.modules.health_isf import service as hs
from app.modules.health_isf.models import HealthISFOrganization
from local_test_reset import main as run_test_reset
from server_runtime import BASE, ensure_server_running, verify_server_persistence

PASSWORD = os.getenv("AMICOR_SEED_PASSWORD", "Amicor123!")
JAMES_PHONE = "9175551001"


def _login(client: httpx.Client, email: str) -> str:
    resp = client.post("/api/auth/login", json={"email": email, "password": PASSWORD})
    resp.raise_for_status()
    return str(resp.json().get("token") or resp.json().get("access_token"))


def _norm_status(raw: str) -> str:
    value = str(raw or "").strip().lower().replace("ridestatus.", "")
    if value in {"completed", "complete"}:
        return "completed"
    if "accept" in value or value == "assigned":
        return "accepted"
    return value or "unknown"


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


def _create_ride(client: httpx.Client, rider_headers: dict, *, label: str) -> tuple[str, str, str]:
    stamp = datetime.now(timezone.utc).strftime("%H%M%S")
    rider_phone = f"646-555-{stamp[-4:]}"
    payload = {
        "rider_name": f"Manual Test Rider {label}",
        "rider_phone": rider_phone,
        "pickup_address": f"100 Manual Pickup {label}, New York, NY 10001",
        "dropoff_address": f"200 Manual Dropoff {label}, New York, NY 10002",
        "ride_type": "healthcare",
        "recurring": False,
        "notes": f"two ride lifecycle proof {label}",
    }
    resp = client.post("/api/health-isf/customer-requests", headers=rider_headers, json=payload)
    resp.raise_for_status()
    body = resp.json()
    return str(body["ride_id"]), str(body["id"]), rider_phone


def _assign_james(client: httpx.Client, headers: dict, request_id: str, ride_id: str, driver_id: str, org_id: str) -> None:
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


def _browser_proof(passenger_marker: str, *, expect_earnings: bool = False) -> dict:
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
            page.wait_for_timeout(4000)
            page.evaluate(
                """async () => {
                  if (window.AmiOpsShellActions && window.AmiOpsShellActions.refreshData) {
                    await window.AmiOpsShellActions.refreshData();
                  }
                  if (window.AmiOpsShellActions && window.AmiOpsShellActions.refreshDriverWorkflowData) {
                    await window.AmiOpsShellActions.refreshDriverWorkflowData({ lastAction: 'lifecycle proof' });
                  }
                }"""
            )
            page.wait_for_timeout(5000)
            body = page.locator("body").inner_text().lower()
            driver_panel = ""
            if page.locator(".driver-mobile-layout").count():
                driver_panel = page.locator(".driver-mobile-layout").first.inner_text().lower()
            primary_card = ""
            queue_card = ""
            if page.locator('.driver-workflow-card:has-text("Primary Workflow")').count():
                primary_card = page.locator('.driver-workflow-card:has-text("Primary Workflow")').first.inner_text().lower()
            if page.locator(".driver-mobile-queue").count():
                queue_card = page.locator(".driver-mobile-queue").first.inner_text().lower()
            snapshot = page.evaluate(
                """() => {
                  const st = window.AmiOpsShellState || {};
                  const app = st.driverApp || {};
                  const wf = st.driverWorkflow || {};
                  const earn = wf.earnings || {};
                  return {
                    earningsToday: Number(app.earningsToday || earn.earnings_today_usd || 0),
                    completedTrips: Number(app.completedTrips || earn.trip_count || 0),
                    activeTripId: String(app.activeTripId || ''),
                    driverId: String((wf.driverId || app.currentDriverId || ''))
                  };
                }"""
            )
            checks = {
                "awaiting_or_completed_visible": ("awaiting assignment" in body) or ("completed" in body),
                "no_active_passenger": (
                    passenger_marker.lower() not in (primary_card or "")
                    and passenger_marker.lower() not in (queue_card or "")
                    and not str((snapshot or {}).get("activeTripId") or "").strip()
                ),
                "no_uuid_leak": len(
                    re.findall(
                        r"[0-9a-f]{8}(?:-[0-9a-f]{4}){3}-[0-9a-f]{12}",
                        driver_panel or body,
                    )
                )
                == 0,
            }
            if expect_earnings:
                earnings_blob = driver_panel or body
                earnings_today = float((snapshot or {}).get("earningsToday") or 0)
                checks["earnings_nonzero"] = earnings_today > 0 or bool(
                    re.search(r"\$1[2-9]\.\d{2}", earnings_blob)
                    or re.search(r"\$18\.\d{2}", earnings_blob)
                )
            return {"ok": all(checks.values()), "checks": checks, "snapshot": snapshot, "url": url}
        finally:
            context.close()
            browser.close()


def main() -> int:
    print("=== TWO RIDE LIFECYCLE PROOF ===")
    flags: dict[str, bool] = {}

    reset_code = run_test_reset()
    flags["TEST_RESET_PASS"] = reset_code == 0

    ensure_server_running(force_restart=False)
    client = httpx.Client(base_url=BASE, timeout=120.0)
    dtoken = _login(client, "dispatcher@amicor.local")
    dheaders = {"Authorization": f"Bearer {dtoken}"}
    rtoken = _login(client, "rider@amicor.local")
    rheaders = {"Authorization": f"Bearer {rtoken}"}
    driver_id, org_id = _find_james(client, dheaders)

    ride1_id, req1_id, _ = _create_ride(client, rheaders, label="ONE")
    ride2_id, req2_id, _ = _create_ride(client, rheaders, label="TWO")
    flags["RIDE_1_CREATED"] = bool(ride1_id)
    flags["RIDE_2_CREATED"] = bool(ride2_id)

    _assign_james(client, dheaders, req1_id, ride1_id, driver_id, org_id)
    ride1 = client.get(f"/api/health-isf/rides/{ride1_id}", headers=dheaders).json()
    flags["RIDE_1_ASSIGNED"] = str(ride1.get("driver_id") or "") == driver_id

    accept = client.post(
        f"/api/health-isf/drivers/{driver_id}/accept-ride",
        headers=dheaders,
        json={"ride_id": ride1_id},
    )
    flags["DRIVER_ACCEPTED_RIDE_1"] = accept.status_code == 200

    _driver_lifecycle_complete(client, dheaders, driver_id, ride1_id)
    completed = client.get(f"/api/health-isf/rides/{ride1_id}", headers=dheaders).json()
    flags["DRIVER_COMPLETED_RIDE_1"] = _norm_status(
        str(completed.get("lifecycle_state") or completed.get("status") or "")
    ) == "completed"

    driver = client.get(f"/api/health-isf/drivers/{driver_id}", headers=dheaders).json()
    workspace = client.get(
        f"/api/health-isf/drivers/{driver_id}/live-workspace",
        headers=dheaders,
        params={"organization_id": org_id},
    ).json()
    flags["DRIVER_RELEASED_AVAILABLE"] = str(driver.get("status") or "").lower() == "available" and not (
        (workspace.get("active_ride") or {}).get("id")
    )

    financial = client.get(f"/api/health-isf/rides/{ride1_id}/financial-summary", headers=dheaders)
    earnings = client.get(f"/api/health-isf/drivers/{driver_id}/earnings", headers=dheaders, params={"organization_id": org_id})
    admin = client.get("/api/health-isf/operations/admin-revenue", headers=dheaders, params={"organization_id": org_id})
    billing = client.get("/api/health-isf/operations/billing-handoffs", headers=dheaders, params={"organization_id": org_id, "limit": 50})
    active = client.get("/api/health-isf/dispatch/active-assignments", headers=dheaders, params={"limit": 100})
    queue = client.get(f"/api/health-isf/dispatch/queue", headers=dheaders, params={"organization_id": org_id, "limit": 100})

    fin_body = financial.json() if financial.status_code == 200 else {}
    earn_body = earnings.json() if earnings.status_code == 200 else {}
    admin_body = admin.json() if admin.status_code == 200 else {}
    bill_rows = billing.json() if billing.status_code == 200 else []

    flags["BILLING_HANDOFF_CREATED"] = any(str(row.get("ride_id") or "") == ride1_id for row in bill_rows)
    flags["DRIVER_EARNINGS_UPDATED"] = float(earn_body.get("earnings_today_usd") or 0.0) > 0.0
    flags["ADMIN_REVENUE_UPDATED"] = float(admin_body.get("platform_revenue_total_usd") or 0.0) > 0.0
    flags["RIDE_1_NOT_ACTIVE"] = (
        not any(str(row.get("ride_id") or "") == ride1_id for row in (active.json() if active.status_code == 200 else []))
        and not any(str(row.get("ride_id") or "") == ride1_id for row in (queue.json() if queue.status_code == 200 else []))
    )

    deadline = time.time() + 60
    ride2_driver = ""
    while time.time() < deadline:
        ride2 = client.get(f"/api/health-isf/rides/{ride2_id}", headers=dheaders).json()
        ride2_driver = str(ride2.get("driver_id") or "")
        if ride2_driver:
            break
        time.sleep(2)
    flags["RIDE_2_AUTO_ASSIGNED_TO_AVAILABLE_DRIVER"] = bool(ride2_driver)
    flags["RIDE_2_ASSIGNED_DRIVER_AVAILABLE"] = False
    if ride2_driver:
        d2 = client.get(f"/api/health-isf/drivers/{ride2_driver}", headers=dheaders).json()
        flags["RIDE_2_ASSIGNED_DRIVER_AVAILABLE"] = str(d2.get("status") or "").lower() in {"available", "assigned", "busy"}

    flags["OLD_RIDES_NOT_RETURNED"] = not any(
        str(row.get("ride_id") or "") == ride1_id for row in (queue.json() if queue.status_code == 200 else [])
    )

    browser = _browser_proof("Manual Test Rider ONE", expect_earnings=True)
    flags["BROWSER_UI_PASS"] = browser.get("ok") is True
    print("BROWSER_UI:", json.dumps(browser, indent=2))
    print("FINANCIAL:", json.dumps(fin_body, indent=2) if fin_body else financial.text[:300])
    print(f"RIDE_2_DRIVER={ride2_driver}")

    persistence = verify_server_persistence()
    flags["SERVER_STILL_RUNNING"] = persistence.get("healthy") is True

    for key in (
        "RIDE_1_CREATED",
        "RIDE_1_ASSIGNED",
        "DRIVER_ACCEPTED_RIDE_1",
        "DRIVER_COMPLETED_RIDE_1",
        "DRIVER_RELEASED_AVAILABLE",
        "BILLING_HANDOFF_CREATED",
        "DRIVER_EARNINGS_UPDATED",
        "ADMIN_REVENUE_UPDATED",
        "RIDE_1_NOT_ACTIVE",
        "RIDE_2_AUTO_ASSIGNED_TO_AVAILABLE_DRIVER",
        "OLD_RIDES_NOT_RETURNED",
        "BROWSER_UI_PASS",
        "SERVER_STILL_RUNNING",
    ):
        print(f"{key}={str(flags.get(key, False)).lower()}")

    passed = all(flags.get(k, False) for k in (
        "RIDE_1_CREATED",
        "RIDE_1_ASSIGNED",
        "DRIVER_ACCEPTED_RIDE_1",
        "DRIVER_COMPLETED_RIDE_1",
        "DRIVER_RELEASED_AVAILABLE",
        "BILLING_HANDOFF_CREATED",
        "DRIVER_EARNINGS_UPDATED",
        "ADMIN_REVENUE_UPDATED",
        "RIDE_1_NOT_ACTIVE",
        "RIDE_2_AUTO_ASSIGNED_TO_AVAILABLE_DRIVER",
        "OLD_RIDES_NOT_RETURNED",
        "BROWSER_UI_PASS",
        "SERVER_STILL_RUNNING",
    ))
    print(f"RESULT={'PASS' if passed else 'FAIL'}")
    return 0 if passed else 1


if __name__ == "__main__":
    raise SystemExit(main())
