"""Verify a ride appears on Driver Mobile for the assigned production driver."""
from __future__ import annotations

import json
import os
import sys
import time
from pathlib import Path

BASE = os.getenv("AMICOR_RENDER_BASE", "https://amicor-health-isf-py.onrender.com").rstrip("/")
RIDE_ID = sys.argv[1] if len(sys.argv) > 1 else "d76f9f43-102c-42d7-a156-ad65cd0e25fb"
DRIVER_PHONE = os.getenv("AMICOR_DRIVER_PHONE", "917-555-1005")
OUT = Path(__file__).resolve().parent.parent.parent / ".runtime" / "driver_mobile_assignment_sync_verify.json"


def main() -> int:
    import requests
    from playwright.sync_api import sync_playwright

    report: dict = {
        "ride_id": RIDE_ID,
        "driver_phone": DRIVER_PHONE,
        "base": BASE,
        "generated_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
    }

    login = requests.post(
        f"{BASE}/api/health-isf/drivers/mobile-login",
        json={"phone": DRIVER_PHONE},
        timeout=90,
    )
    report["mobile_login"] = {"status": login.status_code}
    if not login.ok:
        report["ok"] = False
        report["error"] = login.text[:300]
        OUT.parent.mkdir(parents=True, exist_ok=True)
        OUT.write_text(json.dumps(report, indent=2), encoding="utf-8")
        print(json.dumps(report, indent=2))
        return 1

    body = login.json()
    driver_id = str(body["driver_id"])
    session_token = str(body["session_token"])
    org_id = str(body.get("organization_id") or "")
    report["driver_id"] = driver_id
    report["organization_id"] = org_id

    headers = {"X-Driver-Session-Token": session_token, "Accept": "application/json"}
    active = requests.get(
        f"{BASE}/api/health-isf/drivers/{driver_id}/active-ride",
        headers=headers,
        params={"organization_id": org_id} if org_id else None,
        timeout=90,
    )
    active_body = active.json() if active.ok else {}
    ride = active_body.get("ride") or {}
    report["api_active_ride"] = {
        "status": active.status_code,
        "has_active_ride": active_body.get("has_active_ride"),
        "assignment_state": active_body.get("assignment_state"),
        "ride_id": str(ride.get("id") or ""),
        "ride_matches_target": str(ride.get("id") or "") == RIDE_ID,
    }

    init_script = f"""
    localStorage.setItem('amicor_platform_role', 'driver');
    localStorage.setItem('amicor_shell_role', 'driver');
    localStorage.setItem('amicor_last_mobile_surface', 'driver');
    localStorage.setItem('amicor_driver_session', JSON.stringify({{
      driver_id: {json.dumps(driver_id)},
      driver_name: {json.dumps(body.get('driver_name') or 'Driver')},
      role: 'driver',
      session_token: {json.dumps(session_token)},
      session_id: {json.dumps(body.get('session_id') or '')},
      organization_id: {json.dumps(org_id)},
      updated_at: new Date().toISOString()
    }}));
    localStorage.setItem('amicor_identity', JSON.stringify({{
      userId: 'stale-platform-user',
      email: 'staff@amicor.local',
      name: 'Stale Platform User',
      role: 'staff',
      accessToken: 'stale-platform-jwt-token',
      tokenExpiresAt: Date.now() + 3600000,
      runtimeHost: window.location.host
    }}));
    localStorage.setItem('amicor_session', JSON.stringify({{
      sessionId: 'stale-platform-session',
      createdAt: new Date().toISOString(),
      runtimeHost: window.location.host
    }}));
    """

    sync_failures: list[str] = []
    api_calls: list[dict] = []

    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=True)
        context = browser.new_context(viewport={"width": 390, "height": 844}, is_mobile=True, has_touch=True)
        context.add_init_script(init_script)
        page = context.new_page()

        def on_response(response):
            url = response.url
            if "/api/health-isf/drivers/" not in url:
                return
            api_calls.append({
                "url": url.split("?")[0].replace(BASE, ""),
                "status": response.status,
            })

        page.on("response", on_response)
        page.goto(f"{BASE}/app/mobile", wait_until="domcontentloaded", timeout=120000)
        page.wait_for_timeout(15000)

        content = page.locator("#page-content").inner_text(timeout=10000)
        body_text = page.locator("body").inner_text(timeout=10000)
        report["browser"] = {
            "url": page.url,
            "title": page.locator(".ops-topbar h2").inner_text(timeout=5000),
            "body_class": page.evaluate("() => document.body.className"),
            "mobile_ui_state": page.evaluate(
                "() => (window.AmiOpsShellState && window.AmiOpsShellState.driverApp && window.AmiOpsShellState.driverApp.mobileUiState) || null"
            ),
            "sync_warning": page.evaluate(
                "() => (window.AmiOpsShellState && window.AmiOpsShellState.driverApp && window.AmiOpsShellState.driverApp.syncWarning) || ''"
            ),
            "current_driver_id": page.evaluate(
                "() => (window.AmiOpsShellState && window.AmiOpsShellState.driverApp && window.AmiOpsShellState.driverApp.currentDriverId) || ''"
            ),
            "active_trip_id": page.evaluate(
                "() => (window.AmiOpsShellState && window.AmiOpsShellState.driverApp && window.AmiOpsShellState.driverApp.activeTripId) || ''"
            ),
            "trip_queue_ids": page.evaluate(
                "() => (window.AmiOpsShellState && window.AmiOpsShellState.driverApp && window.AmiOpsShellState.driverApp.tripQueue || []).map(t => t.tripId)"
            ),
            "has_accept_button": page.locator('[data-driver-action=\"accept_trip\"]').count() > 0,
            "accept_disabled": page.locator('[data-driver-action=\"accept_trip\"]').first.is_disabled()
            if page.locator('[data-driver-action=\"accept_trip\"]').count() > 0
            else None,
            "shows_awaiting_assignment": "Awaiting Assignment" in content,
            "shows_sync_failed": "Driver assignment sync failed" in body_text or "assignment sync failed" in body_text.lower(),
            "content_preview": content[:500],
        }
        report["browser_api_calls"] = api_calls
        browser = browser
        browser.close()

    report["ok"] = (
        report["api_active_ride"].get("ride_matches_target") is True
        and report["browser"]["shows_sync_failed"] is False
        and report["browser"]["has_accept_button"] is True
        and report["browser"]["shows_awaiting_assignment"] is False
        and str(RIDE_ID) in (report["browser"].get("trip_queue_ids") or [])
    )
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(report, indent=2, default=str), encoding="utf-8")
    print(json.dumps({"ok": report["ok"], "report_path": str(OUT)}, indent=2))
    return 0 if report["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
