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
              var expiresAt = Date.now() + 24 * 60 * 60 * 1000;
              var runtimeHost = 'local-dev:8010';
              localStorage.setItem('amicor_onboarded', '1');
              localStorage.setItem('amicor_session', JSON.stringify({
                id: 'browser_driver_check',
                expiresAt: expiresAt,
                runtimeHost: runtimeHost
              }));
              localStorage.setItem('amicor_identity', JSON.stringify({
                email: payload.email,
                display_name: payload.name,
                role: payload.role,
                accessToken: payload.token,
                organizationId: payload.orgId,
                tokenExpiresAt: expiresAt,
                runtimeHost: runtimeHost
              }));
              localStorage.setItem('amicor_runtime_marker', JSON.stringify({
                runtimeHost: runtimeHost,
                updatedAt: new Date().toISOString()
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
              if (window.AmiCorSession && typeof window.AmiCorSession.start === 'function') {
                window.AmiCorSession.start({
                  email: payload.email,
                  name: payload.name,
                  role: payload.role,
                  accessToken: payload.token,
                  organizationId: payload.orgId,
                  tokenExpiresAt: expiresAt
                });
              }
            }""",
            {
                "token": token,
                "driverId": MARIA,
                "email": "dispatcher@amicor.local",
                "name": "Dispatcher",
                "role": "dispatcher",
                "orgId": auth.get("organization_id") or "ca8d0c7c-1fff-4465-99d7-75a1fc51543e",
            },
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
