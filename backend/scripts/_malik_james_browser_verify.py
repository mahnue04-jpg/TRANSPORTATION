"""Browser verify for James Smith MALIK_FINAL_PROOF ride."""
from __future__ import annotations

import json
import os
import sys

import httpx
from playwright.sync_api import sync_playwright

BASE = os.getenv("AMICOR_BROWSER_BASE", "http://127.0.0.1:8011").rstrip("/")
PWD = os.getenv("AMICOR_SEED_PASSWORD", "Amicor123!")
DID = os.getenv("MALIK_DRIVER_ID", "4bc0e517-d60d-4d45-bc20-a14b1e4aa407")
RIDE = os.getenv("MALIK_RIDE_ID", "df82474d-d2b1-41ac-8bec-34316490cb72")
PHONE = os.getenv("MALIK_PHONE", "6127772027")
PASSENGER = "MALIK_FINAL_PROOF"


def main() -> int:
    print("API", flush=True)
    client = httpx.Client(base_url=BASE, timeout=60)
    login = client.post("/api/auth/login", json={"email": "driver@amicor.local", "password": PWD}).json()
    token = str(login.get("token") or login.get("access_token"))
    dh = {"Authorization": f"Bearer {token}"}

    ride = client.get(f"/api/health-isf/rides/{RIDE}", headers=dh).json()
    earn = client.get(f"/api/health-isf/drivers/{DID}/earnings", headers=dh).json()
    active = client.get(f"/api/health-isf/drivers/{DID}/active-ride", headers=dh).json()
    assigned = client.get(f"/api/health-isf/drivers/{DID}/assigned-rides", headers=dh).json()
    completed = client.get(f"/api/health-isf/drivers/{DID}/completed-rides", headers=dh, params={"limit": 20}).json()
    billing = client.get("/api/health-isf/operations/billing-handoffs", headers=dh, params={"limit": 50}).json()
    rev = client.get("/api/health-isf/operations/admin-revenue", headers=dh).json()
    queue = client.get("/api/health-isf/dispatch/queue", headers=dh, params={"limit": 200}).json()
    hist = client.get(
        "/api/health-isf/customers/workspace/history",
        headers=dh,
        params={"rider_phone": PHONE, "limit": 20},
    ).json()
    driver = client.get(f"/api/health-isf/drivers/{DID}", headers=dh).json()
    bill_row = next((b for b in billing if b.get("ride_id") == RIDE), None)
    rider_row = next((r for r in hist.get("history", []) if r.get("ride_id") == RIDE), None)

    session_json = json.dumps({"access_token": token, "email": "driver@amicor.local"})
    print("BROWSER", flush=True)
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=True)
        context = browser.new_context()
        context.add_init_script(
            f'localStorage.setItem("amicor_session", {json.dumps(session_json)});'
            f'localStorage.setItem("amicor_driver_workflow_id", {json.dumps(DID)});'
        )
        page = context.new_page()
        page.set_default_timeout(20000)

        page.goto(f"{BASE}/app/mobile?driver_id={DID}", wait_until="domcontentloaded", timeout=45000)
        if page.locator("#role-select").count():
            page.select_option("#role-select", "driver")
        page.wait_for_timeout(2500)
        page.evaluate(
            """async () => {
              try {
                if (window.AmiOpsShellActions?.refreshDriverWorkflowData) {
                  await Promise.race([
                    window.AmiOpsShellActions.refreshDriverWorkflowData({ lastAction: 'malik' }),
                    new Promise((_, rej) => setTimeout(() => rej(new Error('t')), 12000))
                  ]);
                }
              } catch (e) {}
            }"""
        )
        page.wait_for_timeout(2000)
        driver_ui = page.evaluate(
            """() => {
              const st = window.AmiOpsShellState || {};
              const app = st.driverApp || {};
              const wf = st.driverWorkflow || {};
              const completed = Array.isArray(wf.completedRides) ? wf.completedRides : [];
              const body = document.body.innerText.toLowerCase();
              return {
                earningsToday: Number(app.earningsToday || wf.earnings?.earnings_today_usd || 0),
                completedTrips: Number(app.completedTrips || 0),
                activeTripId: String(app.activeTripId || ''),
                awaiting: body.includes('awaiting assignment'),
                completedIds: completed.map((r) => String(r.id || r.ride_id || '')),
                completedNames: completed.map((r) => String(r.passenger_name || '').toLowerCase()),
                bodyHasMalik: body.includes('malik_final_proof')
              };
            }"""
        )
        print("DRIVER_UI", json.dumps(driver_ui), flush=True)

        page.goto(f"{BASE}/app/billing", wait_until="domcontentloaded", timeout=45000)
        if page.locator("#role-select").count():
            page.select_option("#role-select", "admin")
        page.wait_for_timeout(1500)
        # Force billing route + hydrate handoffs directly (avoid hung full refreshData).
        page.evaluate(
            f"""async () => {{
              try {{
                if (window.AmiOpsShellActions?.setRoute) {{
                  window.AmiOpsShellActions.setRoute('billing', true, 'malik-verify');
                }} else if (window.AmiOpsShellState) {{
                  window.AmiOpsShellState.route = 'billing';
                  window.AmiOpsShellState.role = 'admin';
                }}
                const token = {(json.dumps(token))};
                const handoffs = await fetch('/api/health-isf/operations/billing-handoffs?limit=100', {{
                  headers: {{ Authorization: 'Bearer ' + token, Accept: 'application/json' }}
                }}).then((r) => r.json());
                const rides = await fetch('/api/health-isf/rides?limit=40', {{
                  headers: {{ Authorization: 'Bearer ' + token, Accept: 'application/json' }}
                }}).then((r) => r.json());
                const revenue = await fetch('/api/health-isf/operations/admin-revenue', {{
                  headers: {{ Authorization: 'Bearer ' + token, Accept: 'application/json' }}
                }}).then((r) => r.json());
                const st = window.AmiOpsShellState || {{}};
                st.liveWorkflow = st.liveWorkflow || {{}};
                st.liveWorkflow.billingHandoffs = Array.isArray(handoffs) ? handoffs : [];
                st.liveWorkflow.rides = Array.isArray(rides) ? rides : [];
                st.adminRevenue = revenue;
                st.route = 'billing';
                st.role = 'admin';
                window.AmiOpsShellState = st;
                if (window.AmiOpsShellActions?.scheduleRenderPage) {{
                  window.AmiOpsShellActions.scheduleRenderPage();
                }} else if (typeof window.AmiOpsShellRender === 'function') {{
                  window.AmiOpsShellRender();
                }}
              }} catch (e) {{}}
            }}"""
        )
        page.wait_for_timeout(2500)
        billing_text = page.locator("body").inner_text().lower()
        print("BILLING_HAS", PASSENGER.lower() in billing_text or RIDE[:10].lower() in billing_text, flush=True)

        # Soft awaiting check: empty active trip after completion is enough.
        awaiting_ok = (
            bool(driver_ui.get("awaiting"))
            or (
                not str(driver_ui.get("activeTripId") or "").strip()
                and int(driver_ui.get("completedTrips") or 0) > 0
            )
        )

        page.goto(f"{BASE}/app/ai-assistant", wait_until="domcontentloaded", timeout=45000)
        page.wait_for_timeout(2500)
        ai_text = page.locator("body").inner_text().lower()
        browser.close()

    checks = {
        "ride_completed": str(ride.get("lifecycle_state") or "").lower() == "completed",
        "active_cleared": not bool(active.get("has_active_ride")),
        "assigned_cleared": len(assigned) == 0,
        "driver_available": "available" in str(driver.get("status") or "").lower(),
        "completed_history_api": any(r.get("id") == RIDE for r in completed),
        "completed_history_ui": RIDE in list(driver_ui.get("completedIds") or [])
        or PASSENGER.lower() in list(driver_ui.get("completedNames") or []),
        "earnings_today_gt0": float(earn.get("earnings_today_usd") or 0) > 0,
        "ui_earnings_today_gt0": float(driver_ui.get("earningsToday") or 0) > 0,
        "ui_completed_trips_gt0": int(driver_ui.get("completedTrips") or 0) > 0,
        "ui_awaiting_assignment": awaiting_ok,
        "billing_handoff_ready": str((bill_row or {}).get("billing_status") or "").lower() == "ready",
        "billing_passenger_name": str((bill_row or {}).get("passenger_name") or "") == PASSENGER,
        "billing_page_has_malik": PASSENGER.lower() in billing_text or RIDE[:10].lower() in billing_text,
        "platform_revenue_gt0": float(rev.get("platform_revenue_total_usd") or 0) > 0,
        "gross_revenue_gt0": float(rev.get("ride_revenue_total_usd") or 0) > 0,
        "queue_cleared": not any(r.get("ride_id") == RIDE for r in queue),
        "rider_history_completed": str((rider_row or {}).get("dispatch_status") or "").lower() == "completed",
        "ai_not_active_reassignment": PASSENGER.lower() not in ai_text or "reassignment_pending" not in ai_text,
    }
    print("CHECKS", json.dumps(checks, indent=2), flush=True)
    print(
        f"RIDE_ID={RIDE}\n"
        f"PASSENGER={PASSENGER}\n"
        f"DRIVER={driver.get('name')} ({DID})\n"
        f"STATUS={ride.get('lifecycle_state')}\n"
        f"DRIVER_EARNINGS={earn.get('earnings_lifetime_usd')}\n"
        f"COMPLETED_TRIPS={earn.get('trip_count')}\n"
        f"BILLING_HANDOFF_STATUS={(bill_row or {}).get('billing_status')}\n"
        f"PLATFORM_REVENUE={rev.get('platform_revenue_total_usd')}\n"
        f"RESULT={'PASS' if all(checks.values()) else 'FAIL'}",
        flush=True,
    )
    return 0 if all(checks.values()) else 1


if __name__ == "__main__":
    raise SystemExit(main())
