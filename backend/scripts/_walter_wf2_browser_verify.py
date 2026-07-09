"""Browser verification for WF2 Driver 2 + Walter ride completion UI."""
from __future__ import annotations

import json
import os
import sys

import httpx
from playwright.sync_api import sync_playwright

SCRIPT_DIR = __file__.replace("\\", "/")
sys.path.insert(0, os.path.dirname(os.path.dirname(SCRIPT_DIR)) if False else os.path.join(os.path.dirname(__file__), ".."))

BASE = os.getenv("AMICOR_BROWSER_BASE", "http://127.0.0.1:8011").rstrip("/")
PWD = os.getenv("AMICOR_SEED_PASSWORD", "Amicor123!")
DID = "0431eca9-cf95-46f6-bb46-7c789480eb43"
RIDE = "4dca210f-b2dd-42c6-a486-3b29e447e96b"


def main() -> int:
    client = httpx.Client(base_url=BASE, timeout=60)
    login = client.post("/api/auth/login", json={"email": "driver@amicor.local", "password": PWD}).json()
    token = str(login.get("token") or login.get("access_token"))
    ride = client.get(f"/api/health-isf/rides/{RIDE}", headers={"Authorization": f"Bearer {token}"}).json()
    earnings = client.get(
        f"/api/health-isf/drivers/{DID}/earnings",
        headers={"Authorization": f"Bearer {token}"},
    ).json()

    url = f"{BASE}/static/ops-shell.html?platform_reset=1&driver_id={DID}"
    session_json = json.dumps({"access_token": token, "email": "driver@amicor.local"})

    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=True)
        context = browser.new_context()
        context.add_init_script(
            f'localStorage.setItem("amicor_session", {json.dumps(session_json)});'
            f'localStorage.setItem("amicor_driver_workflow_id", {json.dumps(DID)});'
        )
        page = context.new_page()
        page.goto(url, wait_until="domcontentloaded", timeout=90000)
        if page.locator("#role-select").count():
            page.select_option("#role-select", "driver")
        page.wait_for_timeout(2000)
        page.evaluate(
            """async () => {
              if (window.AmiOpsShellActions?.refreshData) await window.AmiOpsShellActions.refreshData();
              if (window.AmiOpsShellActions?.refreshDriverWorkflowData) {
                await window.AmiOpsShellActions.refreshDriverWorkflowData({ lastAction: 'walter verify' });
              }
            }"""
        )
        page.wait_for_timeout(5000)
        driver_snap = page.evaluate(
            """() => {
              const st = window.AmiOpsShellState || {};
              const app = st.driverApp || {};
              const wf = st.driverWorkflow || {};
              const completed = Array.isArray(wf.completedRides) ? wf.completedRides : [];
              return {
                earningsToday: Number(app.earningsToday || wf.earnings?.earnings_today_usd || 0),
                earningsLifetime: Number(app.earningsLifetime || wf.earnings?.earnings_lifetime_usd || 0),
                completedTrips: Number(app.completedTrips || wf.earnings?.trip_count || 0),
                activeTripId: String(app.activeTripId || ''),
                driverId: String(app.currentDriverId || wf.driverId || ''),
                completedRideIds: completed.map((r) => String(r.id || r.ride_id || '')),
                body: document.body.innerText.slice(0, 5000).toLowerCase()
              };
            }"""
        )
        driver_body = str(driver_snap.get("body") or "")

        page.select_option("#role-select", "admin")
        page.wait_for_timeout(1000)
        page.goto(f"{BASE}/app/billing?platform_reset=1", wait_until="domcontentloaded", timeout=90000)
        page.wait_for_timeout(2000)
        page.evaluate(
            "async () => { if (window.AmiOpsShellActions?.refreshData) await window.AmiOpsShellActions.refreshData(); }"
        )
        page.wait_for_timeout(4000)
        billing_text = page.locator("body").inner_text().lower()
        browser.close()

    checks = {
        "api_ride_completed": str(ride.get("lifecycle_state") or "").lower() == "completed",
        "api_earnings_positive": float(earnings.get("earnings_lifetime_usd") or 0) > 0,
        "driver_bound": str(driver_snap.get("driverId") or "") == DID,
        "ui_earnings_positive": float(driver_snap.get("earningsLifetime") or 0) > 0,
        "ui_completed_trips": int(driver_snap.get("completedTrips") or 0) >= 1,
        "ui_active_cleared": not str(driver_snap.get("activeTripId") or "").strip(),
        "ui_completed_contains_ride": RIDE in list(driver_snap.get("completedRideIds") or []),
        "ui_walter_visible": "walter" in driver_body or "wonokay" in driver_body or "humboldt" in driver_body,
        "billing_walter_visible": "walter" in billing_text or "wonokay" in billing_text or "humboldt" in billing_text,
        "billing_revenue_visible": "revenue" in billing_text and ("$" in billing_text or "usd" in billing_text),
    }
    print("API", json.dumps({"ride": ride.get("lifecycle_state"), "earnings": earnings}, indent=2))
    print("UI", json.dumps(driver_snap, indent=2)[:2000])
    print("CHECKS", json.dumps(checks, indent=2))
    ok = all(checks.values())
    print("RESULT", "PASS" if ok else "FAIL")
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
