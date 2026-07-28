#!/usr/bin/env python3
"""Warm production timing + browser verification for Driver Mobile read path."""
from __future__ import annotations

import json
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

import requests
from playwright.sync_api import sync_playwright

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO / "backend"))

BASE = "https://amicor-health-isf-py.onrender.com"
PHONE = "917-555-1004"
OUT = REPO / "PRODUCTION_QA_EVIDENCE" / f"DRIVER_READ_PERF_{datetime.now(timezone.utc).strftime('%Y%m%d%H%M%S')}.json"
SHOT = OUT.with_suffix(".png")

THRESHOLDS = {
    "mobile_login": 10.0,
    "active_ride": 3.0,
    "active_offer": 3.0,
    "live_workspace": 5.0,
    "assigned_rides": 5.0,
}


def main() -> int:
    report: dict = {"base": BASE, "phone": PHONE, "thresholds": THRESHOLDS}
    report["deploy_commit"] = requests.get(f"{BASE}/api/health/live", timeout=120).json().get("deploy_commit")

    # Warm instance
    requests.get(f"{BASE}/api/health/live", timeout=120)

    timings: dict[str, float] = {}
    t0 = time.perf_counter()
    login = requests.post(f"{BASE}/api/health-isf/drivers/mobile-login", json={"phone": PHONE}, timeout=120)
    timings["mobile_login"] = round(time.perf_counter() - t0, 3)
    login.raise_for_status()
    body = login.json()
    driver_id = body["driver_id"]
    headers = {"X-Driver-Session-Token": body["session_token"]}

    for label, path in [
        ("active_ride", f"/api/health-isf/drivers/{driver_id}/active-ride"),
        ("active_offer", f"/api/health-isf/drivers/{driver_id}/active-offer"),
        ("live_workspace", f"/api/health-isf/drivers/{driver_id}/live-workspace"),
        ("assigned_rides", f"/api/health-isf/drivers/{driver_id}/assigned-rides?limit=15"),
    ]:
        t1 = time.perf_counter()
        resp = requests.get(f"{BASE}{path}", headers=headers, timeout=120)
        timings[label] = round(time.perf_counter() - t1, 3)
        report[label] = {"status": resp.status_code, "ok": resp.ok}

    report["timings_seconds"] = timings
    report["timing_pass"] = {
        k: timings[k] <= THRESHOLDS[k] for k in THRESHOLDS if k in timings
    }

    browser: dict = {}
    with sync_playwright() as pw:
        page = pw.chromium.launch(headless=True).new_context(viewport={"width": 390, "height": 844}).new_page()
        page.goto(f"{BASE}/app/mobile", wait_until="domcontentloaded", timeout=180000)
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
        deadline = time.time() + 90
        while time.time() < deadline:
            snap = page.evaluate(
                """() => {
                  const app = window.AmiOpsShellState?.driverApp || {};
                  const err = document.querySelector('[data-driver-sync-error], .driver-sync-error, #driver-assignment-error');
                  const accept = document.querySelector('[data-driver-action="accept_trip"]');
                  return {
                    mobileUiState: app.mobileUiState,
                    syncError: err?.textContent?.trim() || null,
                    acceptDisabled: accept?.disabled,
                    activeTripId: app.activeTripId,
                    tripQueueLen: (app.tripQueue || []).length,
                  };
                }"""
            )
            browser["last_snap"] = snap
            if str(snap.get("mobileUiState") or "") != "loading_assignment":
                break
            time.sleep(3)
        page.screenshot(path=str(SHOT), full_page=True)
        browser["screenshot"] = str(SHOT)

    report["browser"] = browser
    snap = browser.get("last_snap") or {}
    report["browser_pass"] = bool(
        str(snap.get("mobileUiState") or "") != "loading_assignment"
        and not snap.get("syncError")
    )
    report["pass"] = all(report["timing_pass"].values()) and report["browser_pass"]

    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(report, indent=2), encoding="utf-8")
    print(str(OUT))
    print(str(SHOT))
    print(json.dumps(report, indent=2))
    return 0 if report["pass"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
