#!/usr/bin/env python3
"""Verify production Driver Mobile Accept Trip and Rider auth UI blockers (no new rides)."""
from __future__ import annotations

import json
import os
import re
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import requests
from playwright.sync_api import sync_playwright

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO / "backend"))

from scripts.executive_proof_harness import APP, goto_with_retry  # noqa: E402

BASE = os.getenv("AMICOR_RENDER_BASE", "https://amicor-health-isf-py.onrender.com").rstrip("/")
DRIVER_PHONE = os.getenv("AMICOR_DRIVER_PHONE", "917-555-1004")
RIDER_EMAIL = os.getenv("AMICOR_RIDER_EMAIL", "rider@amicor.local")
RUN_TS = datetime.now(timezone.utc).strftime("%Y%m%d%H%M%S")
OUT = REPO / "PRODUCTION_QA_EVIDENCE" / f"PRODUCTION_UI_SESSION_BLOCKERS_{RUN_TS}.json"


def driver_session() -> dict[str, str]:
    resp = requests.post(
        f"{BASE}/api/health-isf/drivers/mobile-login",
        json={"phone": DRIVER_PHONE},
        timeout=120,
    )
    resp.raise_for_status()
    body = resp.json()
    return {
        "driver_id": str(body["driver_id"]),
        "session_token": str(body["session_token"]),
        "organization_id": str(body.get("organization_id") or ""),
    }


def driver_headers(session: dict[str, str]) -> dict[str, str]:
    headers = {
        "X-Driver-Session-Token": session["session_token"],
        "Accept": "application/json",
    }
    if session.get("organization_id"):
        headers["X-Organization-Id"] = session["organization_id"]
    return headers


def find_existing_ride(session: dict[str, str]) -> dict[str, Any]:
    did = session["driver_id"]
    headers = driver_headers(session)
    rides = requests.get(
        f"{BASE}/api/health-isf/drivers/{did}/assigned-rides",
        headers=headers,
        params={"limit": 10, "mobile_light": 1},
        timeout=120,
    ).json()
    active = requests.get(
        f"{BASE}/api/health-isf/drivers/{did}/active-ride",
        headers=headers,
        timeout=120,
    ).json()
    ride_id = ""
    if isinstance(rides, list):
        for row in rides:
            status = str(row.get("lifecycle_state") or row.get("status") or "").lower()
            if status not in {"completed", "cancelled", "declined"}:
                ride_id = str(row.get("id") or "")
                break
    if not ride_id:
        ride_id = str((active.get("ride") or {}).get("id") or "")
    return {
        "ride_id": ride_id,
        "assigned_rides": rides if isinstance(rides, list) else [],
        "active_ride": active,
    }


def wake_service() -> str:
    live = requests.get(f"{BASE}/api/health/live", timeout=180).json()
    return str(live.get("deploy_commit") or "")


def rider_platform_login(page, password: str) -> bool:
    if not password:
        return False
    resp = requests.post(
        f"{BASE}/api/auth/login",
        json={"email": RIDER_EMAIL, "password": password},
        timeout=120,
    )
    if resp.status_code != 200:
        return False
    token = str(resp.json().get("access_token") or "")
    if not token:
        return False
    page.goto(f"{APP}/riders", wait_until="domcontentloaded", timeout=120000)
    page.evaluate(
        """(token) => {
          if (window.AmiCorSession && typeof window.AmiCorSession.restore === 'function') {
            window.AmiCorSession.restore();
          }
          if (window.AmiCorSession && typeof window.AmiCorSession.applyAuthTokens === 'function') {
            window.AmiCorSession.applyAuthTokens({ accessToken: token, role: 'rider' });
          }
          try {
            localStorage.setItem('amicor_session', JSON.stringify({ accessToken: token, role: 'rider' }));
          } catch (_) {}
        }""",
        token,
    )
    page.reload(wait_until="domcontentloaded")
    page.wait_for_timeout(5000)
    return True


def main() -> int:
    report: dict[str, Any] = {
        "run_ts": RUN_TS,
        "base": BASE,
        "deploy_commit": wake_service(),
        "driver_phone": DRIVER_PHONE,
        "verdict": "FAIL",
    }
    session = driver_session()
    ride_ctx = find_existing_ride(session)
    ride_id = ride_ctx["ride_id"]
    report["driver_id"] = session["driver_id"]
    report["ride_id"] = ride_id
    report["ride_context"] = ride_ctx
    if not ride_id:
        report["blocker"] = "No existing assigned ride found for driver."
        OUT.parent.mkdir(parents=True, exist_ok=True)
        OUT.write_text(json.dumps(report, indent=2), encoding="utf-8")
        print(json.dumps({"verdict": report["verdict"], "json": str(OUT)}, indent=2))
        return 1

    accept_api: dict[str, Any] = {"skipped": True}
    rider_ok = False
    with sync_playwright() as pw:
        browser = pw.chromium.launch(headless=True)
        page = browser.new_page()

        goto_with_retry(page, f"{APP}/mobile")
        page.wait_for_timeout(3000)
        if page.locator("#driver-mobile-phone").count():
            page.fill("#driver-mobile-phone", DRIVER_PHONE)
            page.locator("#driver-mobile-login-btn").click()
        page.wait_for_function(
            "() => !!(window.AmiOpsShellState && window.AmiOpsShellActions && !window.AmiOpsShellState.loading)",
            timeout=120000,
        )
        page.wait_for_timeout(8000)
        toggle = page.locator('[data-driver-action="toggle_shift"]').first
        if toggle.count() and "Start Shift" in (toggle.inner_text() or ""):
            toggle.click()
            page.wait_for_timeout(2000)

        accept_btn = page.locator('[data-driver-action="accept_trip"]').first
        report["driver_ui_before"] = page.evaluate(
            """() => ({
              activeTripId: (window.AmiOpsShellState?.driverApp?.activeTripId) || '',
              shiftOnline: !!window.AmiOpsShellState?.driverApp?.shiftOnline,
              boundActions: Array.from(document.querySelectorAll('[data-driver-action]')).map((btn) => ({
                action: btn.getAttribute('data-driver-action'),
                disabled: btn.disabled,
                tripId: btn.getAttribute('data-trip-id') || ''
              }))
            })"""
        )
        report["driver_accept_disabled"] = accept_btn.is_disabled() if accept_btn.count() else None

        clicked = "none"
        try:
            with page.expect_response(
                lambda r: "/accept-ride" in r.url,
                timeout=60000,
            ) as resp_info:
                if accept_btn.count() and not accept_btn.is_disabled():
                    accept_btn.click()
                    clicked = "accept_trip"
                else:
                    page.locator('[data-driver-action="accept_trip"]').first.click(force=True)
                    clicked = "accept_trip_force"
            api_resp = resp_info.value
            accept_api = {
                "clicked": clicked,
                "url": api_resp.url,
                "status": api_resp.status,
                "body": api_resp.json(),
            }
        except Exception as exc:
            accept_api = {"clicked": clicked, "error": str(exc)}

        page.wait_for_timeout(3000)
        report["driver_ui_after"] = page.evaluate(
            """() => ({
              activeTripId: (window.AmiOpsShellState?.driverApp?.activeTripId) || '',
              tripStatus: (window.AmiOpsShellState?.driverApp?.tripQueue || [])[0]?.status || '',
              lastStatusUpdate: (window.AmiOpsShellState?.driverApp?.lastStatusUpdate) || ''
            })"""
        )
        report["accept_trip_api"] = accept_api

        password = os.getenv("AMICOR_RIDER_PASSWORD") or os.getenv("AMICOR_SEED_PASSWORD") or ""
        report["rider_api_login"] = rider_platform_login(page, password)
        rider_probe = page.evaluate(
            """() => ({
              tokenPresent: !!(window.AmiOpsShellActions?.getAccessToken?.()),
              signInRequiredVisible: !!document.querySelector('.rider-auth-required'),
              signedInBannerVisible: !!document.querySelector('.rider-auth-session'),
              signOutVisible: !!Array.from(document.querySelectorAll('[data-rider-action="sign_out"]')).some((el) => el.offsetParent !== null)
            })"""
        )
        report["rider_session_source"] = "AmiCorSession.getAccessToken() via AmiOpsShellActions.getAccessToken()"
        report["rider_ui"] = rider_probe
        if rider_probe.get("signedInBannerVisible") and rider_probe.get("signOutVisible"):
            page.locator('[data-rider-action="sign_out"]').first.click()
            page.wait_for_timeout(2000)
            after_sign_out = page.evaluate(
                """() => ({
                  tokenPresent: !!(window.AmiOpsShellActions?.getAccessToken?.()),
                  signInRequiredVisible: !!document.querySelector('.rider-auth-required'),
                  signedInBannerVisible: !!document.querySelector('.rider-auth-session')
                })"""
            )
            report["rider_after_sign_out"] = after_sign_out
            rider_ok = bool(after_sign_out.get("signInRequiredVisible")) and not after_sign_out.get("signedInBannerVisible")
        browser.close()

    driver_ok = accept_api.get("status") in {200, 201, 409}
    report["verdict"] = "PASS" if driver_ok and rider_ok else "FAIL"
    if not rider_ok:
        report["remaining_blocker"] = "Rider sign-out UI verification failed or rider login password unavailable."
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(report, indent=2), encoding="utf-8")
    print(json.dumps({"verdict": report["verdict"], "json": str(OUT)}, indent=2))
    return 0 if report["verdict"] == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
