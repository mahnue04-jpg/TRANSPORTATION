"""Browser check: driver mobile route shows same active ride as API."""
from __future__ import annotations

import json

import httpx
from playwright.sync_api import sync_playwright

BASE = "http://127.0.0.1:8010"
MARIA = "767627cb-a3f5-4e13-a32b-ad12570a8ec4"
PASSWORD = "Amicor123!"


def main() -> None:
    with httpx.Client(base_url=BASE, timeout=60.0) as client:
        auth = client.post(
            "/api/auth/login",
            json={"email": "dispatcher@amicor.local", "password": PASSWORD},
        ).json()
        token = auth["access_token"]
        active = client.get(
            f"/api/health-isf/drivers/{MARIA}/active-ride",
            headers={"Authorization": f"Bearer {token}"},
        ).json()
    ride_id = (active.get("ride") or {}).get("id")
    print("API_ACTIVE_RIDE", ride_id)

    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=True)
        page = browser.new_page()
        page.goto(f"{BASE}/app/mobile", wait_until="domcontentloaded")
        page.evaluate(
            """(payload) => {
              localStorage.setItem('amicor_onboarded', '1');
              localStorage.setItem('amicor_session', JSON.stringify({
                access_token: payload.token,
                token_type: 'bearer'
              }));
              localStorage.setItem('amicor_identity', JSON.stringify({
                email: 'dispatcher@amicor.local',
                display_name: 'Dispatcher',
                role: 'dispatcher'
              }));
              localStorage.setItem('amicor_driver_workflow_id', payload.driverId);
              localStorage.setItem('amicor_driver_session', JSON.stringify({
                driver_id: payload.driverId,
                driver_name: 'Maria Garcia',
                role: 'driver'
              }));
              sessionStorage.setItem('amicor_shell_session_v1', JSON.stringify({
                role: 'driver',
                route: 'mobile',
                roleRoutes: { driver: 'mobile' }
              }));
            }""",
            {"token": token, "driverId": MARIA},
        )
        page.reload(wait_until="domcontentloaded")
        page.wait_for_timeout(10000)
        body = page.inner_text("body")
        short = str(ride_id)[:8].lower() if ride_id else ""
        visible = bool(short and short in body.lower())
        print("MARIA_VISIBLE", "Maria Garcia" in body)
        print("BROWSER_RIDE_VISIBLE", visible)
        if not visible:
            print("BODY_SNIPPET", body[:900].replace("\n", " "))
            browser.close()
            raise SystemExit(1)
        browser.close()
        print("BROWSER_DRIVER_MOBILE_PASS")


if __name__ == "__main__":
    main()
