"""Verify rider surface session isolation vs driver mobile in one browser session."""
from __future__ import annotations

import json
import os
import time
from pathlib import Path

BASE = os.getenv("AMICOR_RENDER_BASE", "https://amicor-health-isf-py.onrender.com").rstrip("/")
OUT = Path(__file__).resolve().parent.parent.parent / ".runtime" / "rider_session_isolation_verify.json"

INIT_SCRIPT = """
(() => {
  const expires = Date.now() + (8 * 60 * 60 * 1000);
  localStorage.setItem('amicor_platform_role', 'driver');
  localStorage.setItem('amicor_shell_role', 'driver');
  localStorage.setItem('amicor_last_mobile_surface', 'driver');
  localStorage.setItem('amicor_driver_session', JSON.stringify({
    driver_id: 'session-isolation-proof-driver',
    driver_name: 'Isolation Proof Driver',
    role: 'driver',
    session_token: 'session-isolation-proof-token',
    session_id: 'session-isolation-proof-session',
    organization_id: '308dc05a-6781-4ef7-91fc-ff22606937e3',
    updated_at: new Date().toISOString()
  }));
  localStorage.setItem('amicor_identity', JSON.stringify({
    userId: 'session-isolation-proof-user',
    email: 'driver@amicor.local',
    name: 'Isolation Proof Driver',
    role: 'driver',
    accessToken: 'session-isolation-proof-jwt',
    tokenExpiresAt: expires,
    runtimeHost: window.location.host
  }));
  localStorage.setItem('amicor_session', JSON.stringify({
    sessionId: 'session-isolation-proof-sess',
    createdAt: new Date().toISOString(),
    runtimeHost: window.location.host
  }));
  sessionStorage.setItem('amicor_ops_shell_state', JSON.stringify({
    route: 'mobile',
    platformRole: 'driver',
    roleRoutes: { driver: 'mobile' }
  }));
})();
"""


def read_user_pill(page) -> dict:
    return {
        "name": page.locator("#ops-user-name").inner_text(timeout=5000),
        "role": page.locator("#ops-user-role").inner_text(timeout=5000),
        "role_badge": page.locator("#role-badge").inner_text(timeout=5000),
    }


def main() -> int:
    from playwright.sync_api import sync_playwright

    report: dict = {
        "base": BASE,
        "generated_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "checks": {},
    }

    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=True)
        context = browser.new_context(
            viewport={"width": 390, "height": 844},
            is_mobile=True,
            has_touch=True,
        )
        context.add_init_script(INIT_SCRIPT)
        page = context.new_page()

        page.goto(f"{BASE}/app/mobile", wait_until="domcontentloaded", timeout=120000)
        page.wait_for_timeout(3500)
        mobile = {
            "url": page.url,
            "body_class": page.evaluate("() => document.body.className"),
            "title": page.locator(".ops-topbar h2").inner_text(timeout=5000),
            "user_pill": read_user_pill(page),
            "has_driver_login": page.locator("#driver-mobile-login-panel").count() > 0,
        }
        mobile["ok"] = (
            mobile["url"].endswith("/app/mobile")
            and "driver-mobile-app" in mobile["body_class"]
            and mobile["title"] == "Driver Mobile"
            and "Isolation Proof Driver" in mobile["user_pill"]["name"]
        )

        page.goto(f"{BASE}/app/riders", wait_until="domcontentloaded", timeout=120000)
        page.wait_for_selector("#rider-name-input", timeout=30000)
        page.wait_for_timeout(1500)
        riders = {
            "url": page.url,
            "body_class": page.evaluate("() => document.body.className"),
            "title": page.locator(".ops-topbar h2").inner_text(timeout=5000),
            "user_pill": read_user_pill(page),
            "has_rider_form": page.locator("#rider-name-input").count() > 0,
            "has_auth_banner": page.locator(".rider-auth-required").count() > 0,
            "route_state": page.evaluate(
                "() => (window.AmiOpsShellState && window.AmiOpsShellState.route) || null"
            ),
        }
        pill = riders["user_pill"]
        riders["ok"] = (
            riders["url"].endswith("/app/riders")
            and "rider-app-surface" in riders["body_class"]
            and riders["title"] == "Rider App"
            and riders["route_state"] == "riders"
            and riders["has_rider_form"]
            and pill["name"] == "Signed Out"
            and pill["role"] == "Rider"
            and pill["role_badge"] == "role: rider"
            and "Isolation Proof Driver" not in pill["name"]
            and "Driver" not in pill["role"]
            and riders["has_auth_banner"]
        )

        page.goto(f"{BASE}/app/mobile", wait_until="domcontentloaded", timeout=120000)
        page.wait_for_timeout(2500)
        mobile_return = {
            "url": page.url,
            "user_pill": read_user_pill(page),
        }
        mobile_return["ok"] = (
            mobile_return["url"].endswith("/app/mobile")
            and "Isolation Proof Driver" in mobile_return["user_pill"]["name"]
        )

        browser.close()

    report["mobile"] = mobile
    report["riders"] = riders
    report["mobile_return"] = mobile_return
    report["ok"] = mobile["ok"] and riders["ok"] and mobile_return["ok"]

    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(report, indent=2), encoding="utf-8")
    print(json.dumps({"ok": report["ok"], "report_path": str(OUT)}, indent=2))
    return 0 if report["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
