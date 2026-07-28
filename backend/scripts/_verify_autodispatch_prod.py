#!/usr/bin/env python3
"""Post-deploy verification: sweep pending ride, trace audit, driver mobile Accept Trip enabled."""
from __future__ import annotations

import json
import os
import time
from datetime import datetime, timezone
from pathlib import Path

import requests
from playwright.sync_api import sync_playwright

BASE = os.getenv("AMICOR_PUBLIC_URL", "https://amicor-health-isf-py.onrender.com")
RIDE_ID = os.getenv("TRACE_RIDE_ID", "41c50fb9-7bfa-4f8e-8b88-318cbe5b75fd")
PASSWORD = os.getenv("AMICOR_SEED_PASSWORD", "Amicor123!")
SYNC_KEY = os.getenv("AMICOR_DEPLOYMENT_SYNC_KEY", PASSWORD).strip()
DRIVER_PHONE = "917-555-1004"
OUT = Path(__file__).resolve().parents[2] / "PRODUCTION_QA_EVIDENCE" / f"AUTODISPATCH_VERIFY_{datetime.now(timezone.utc).strftime('%Y%m%d%H%M%S')}.json"


def login(email: str) -> tuple[str, dict]:
    r = requests.post(f"{BASE}/api/auth/login", json={"email": email, "password": PASSWORD}, timeout=240)
    if r.status_code != 200 and SYNC_KEY:
        requests.post(f"{BASE}/api/auth/deployment/sync-seed-users", headers={"X-Amicor-Deployment-Key": SYNC_KEY}, timeout=240)
        r = requests.post(f"{BASE}/api/auth/login", json={"email": email, "password": PASSWORD}, timeout=240)
    r.raise_for_status()
    body = r.json()
    return body["access_token"], body


def timed_get(path: str, headers: dict, **params) -> tuple[int, object, float]:
    t0 = time.perf_counter()
    r = requests.get(f"{BASE}{path}", headers=headers, params=params or None, timeout=240)
    elapsed = time.perf_counter() - t0
    try:
        body = r.json()
    except Exception:
        body = r.text[:500]
    return r.status_code, body, elapsed


def main() -> int:
    report: dict = {"ride_id": RIDE_ID, "base": BASE, "timings": {}}
    health = requests.get(f"{BASE}/api/health/live", timeout=240).json()
    report["deploy_commit"] = health.get("deploy_commit")
    report["readiness"] = requests.get(f"{BASE}/api/health/readiness", timeout=240).json()

    token, disp = login("dispatcher@amicor.local")
    h = {"Authorization": f"Bearer {token}"}
    org_id = str(disp.get("organization_id") or "")

    # Sweep pending immediate requests via dispatch queue read
    status, queue, elapsed = timed_get("/api/health-isf/dispatch/queue", h, limit=200)
    report["timings"]["dispatch_queue_sweep"] = round(elapsed, 3)
    report["dispatch_queue_hit"] = status

    for label, path in [
        ("ride", f"/api/health-isf/rides/{RIDE_ID}"),
        ("dispatch_history", f"/api/health-isf/rides/{RIDE_ID}/dispatch-history"),
    ]:
        status, body, elapsed = timed_get(path, h)
        report["timings"][label] = round(elapsed, 3)
        report[label] = {"status": status, "body": body}

    reqs_status, reqs, _ = timed_get("/api/health-isf/customer-requests", h, limit=200)
    report["customer_request"] = next((row for row in (reqs if isinstance(reqs, list) else []) if str(row.get("ride_id") or "") == RIDE_ID), None)

    drivers_status, drivers, _ = timed_get("/api/health-isf/drivers", h, limit=200)
    driver_1004 = next((d for d in (drivers if isinstance(drivers, list) else []) if "1004" in str(d.get("phone") or "")), None)
    report["driver_1004"] = driver_1004
    if driver_1004:
        did = driver_1004["id"]
        for label, path in [
            ("driver_active_offer", f"/api/health-isf/drivers/{did}/active-offer"),
            ("driver_active_ride", f"/api/health-isf/drivers/{did}/active-ride"),
        ]:
            status, body, elapsed = timed_get(path, h)
            report["timings"][label] = round(elapsed, 3)
            report[label] = {"status": status, "body": body}

    browser: dict = {}
    with sync_playwright() as pw:
        page = pw.chromium.launch(headless=True).new_context().new_page()
        page.goto(f"{BASE}/app/mobile", wait_until="domcontentloaded", timeout=240000)
        page.fill("#driver-mobile-phone", DRIVER_PHONE)
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
                    acceptDisabled: accept?.disabled,
                    mobileUiState: app.mobileUiState,
                  };
                }"""
            )
            browser["snap"] = snap
            if snap.get("activeTripId") == RIDE_ID or (snap.get("activeTripId") and not snap.get("acceptDisabled")):
                break
            time.sleep(8)
        browser["final"] = browser.get("snap")
        browser["body_snippet"] = page.evaluate("() => document.body.innerText.slice(0, 1200)")
        if browser.get("final", {}).get("activeTripId"):
            screenshot = OUT.with_suffix(".png")
            page.screenshot(path=str(screenshot), full_page=True)
            browser["screenshot"] = str(screenshot)

    report["browser"] = browser
    audit = report.get("dispatch_history", {}).get("body")
    report["audit_actions"] = [row.get("action") for row in audit] if isinstance(audit, list) else []
    report["pass"] = bool(
        browser.get("final", {}).get("activeTripId")
        and browser.get("final", {}).get("acceptDisabled") is False
    )

    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(report, indent=2, default=str), encoding="utf-8")
    print(OUT)
    print(json.dumps(report, indent=2)[:10000])
    return 0 if report["pass"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
