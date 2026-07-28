#!/usr/bin/env python3
"""Driver-session production verification for auto-dispatch (no dispatcher JWT required)."""
from __future__ import annotations

import json
import time
from datetime import datetime, timezone
from pathlib import Path

import requests
from playwright.sync_api import sync_playwright

BASE = "https://amicor-health-isf-py.onrender.com"
RIDE_ID = "41c50fb9-7bfa-4f8e-8b88-318cbe5b75fd"
PHONE = "917-555-1004"
OUT = Path(__file__).resolve().parents[2] / "PRODUCTION_QA_EVIDENCE" / f"AUTODISPATCH_DRIVER_VERIFY_{datetime.now(timezone.utc).strftime('%Y%m%d%H%M%S')}.json"


def main() -> int:
    report: dict = {"ride_id": RIDE_ID}
    health = requests.get(f"{BASE}/api/health/live", timeout=240).json()
    report["deploy_commit"] = health.get("deploy_commit")

    t0 = time.perf_counter()
    login = requests.post(
        f"{BASE}/api/health-isf/drivers/mobile-login",
        json={"phone": PHONE},
        timeout=240,
    ).json()
    report["timings"] = {"mobile_login": round(time.perf_counter() - t0, 3)}
    driver_id = login["driver_id"]
    h = {"X-Driver-Session-Token": login["session_token"], "Accept": "application/json"}

    for label, path in [
        ("active_ride", f"/api/health-isf/drivers/{driver_id}/active-ride"),
        ("active_offer", f"/api/health-isf/drivers/{driver_id}/active-offer"),
        ("live_workspace", f"/api/health-isf/drivers/{driver_id}/live-workspace"),
    ]:
        t1 = time.perf_counter()
        r = requests.get(f"{BASE}{path}", headers=h, timeout=240)
        report["timings"][label] = round(time.perf_counter() - t1, 3)
        report[label] = {"status": r.status_code, "body": r.json() if r.status_code == 200 else r.text[:300]}

    browser: dict = {}
    with sync_playwright() as pw:
        page = pw.chromium.launch(headless=True).new_context().new_page()
        page.goto(f"{BASE}/app/mobile", wait_until="domcontentloaded", timeout=240000)
        page.fill("#driver-mobile-phone", PHONE)
        page.click("#driver-mobile-login-btn")
        page.wait_for_function(
            "() => !!(window.AmiOpsShellState?.driverApp?.currentDriverId)",
            timeout=120000,
        )
        page.evaluate(
            """async () => {
              if (window.AmiOpsShellActions?.refreshDriverWorkflowData) {
                await window.AmiOpsShellActions.refreshDriverWorkflowData({ forceReset: true });
              }
            }"""
        )
        deadline = time.time() + 300
        while time.time() < deadline:
            snap = page.evaluate(
                """() => {
                  const app = window.AmiOpsShellState?.driverApp || {};
                  const trip = (app.tripQueue || []).find(t => t.tripId === app.activeTripId) || (app.tripQueue || [])[0] || null;
                  const accept = document.querySelector('[data-driver-action="accept_trip"]');
                  return {
                    activeTripId: app.activeTripId,
                    tripStatus: trip?.status,
                    riderName: trip?.patient,
                    pickup: trip?.pickup,
                    dropoff: trip?.dropoff,
                    acceptDisabled: accept?.disabled,
                    mobileUiState: app.mobileUiState,
                  };
                }"""
            )
            browser["snap"] = snap
            if snap.get("activeTripId") and snap.get("acceptDisabled") is False:
                break
            time.sleep(8)
        browser["final"] = browser.get("snap")
        shot = OUT.with_suffix(".png")
        page.screenshot(path=str(shot), full_page=True)
        browser["screenshot"] = str(shot)

    report["browser"] = browser
    offer_ride = (((report.get("active_offer") or {}).get("body") or {}).get("offer") or {}).get("ride_id")
    report["pass"] = bool(
        browser.get("final", {}).get("activeTripId")
        and browser.get("final", {}).get("acceptDisabled") is False
        and (browser.get("final", {}).get("activeTripId") == RIDE_ID or offer_ride == RIDE_ID)
    )
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(report, indent=2, default=str), encoding="utf-8")
    print(OUT)
    print(json.dumps(report, indent=2))
    return 0 if report["pass"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
