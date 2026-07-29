"""Live production investigation: Current Trip state for drivers 1002/1004."""
from __future__ import annotations

import json
import sys
import time
from pathlib import Path
from urllib.parse import urlparse

import requests
from playwright.sync_api import sync_playwright

SCRIPT_DIR = Path(__file__).resolve().parent
BACKEND = SCRIPT_DIR.parent
REPO = BACKEND.parent
if str(BACKEND) not in sys.path:
    sys.path.insert(0, str(BACKEND))

from scripts import production_auth as pa

BASE = pa.BASE
EVIDENCE = REPO / "PRODUCTION_QA_EVIDENCE"
PHONES = ("917-555-1002", "917-555-1004")
ENDPOINTS = (
    "active-ride",
    "active-offer",
    "upcoming-schedule",
    "assigned-rides?limit=15",
    "live-workspace",
)


def _login(phone: str) -> tuple[str, str, dict]:
    r = requests.post(f"{BASE}/api/health-isf/drivers/mobile-login", json={"phone": phone}, timeout=120)
    r.raise_for_status()
    body = r.json()
    did = str(body["driver_id"])
    token = str(body["session_token"])
    return did, token, {"X-Driver-Session-Token": token}


def _ride_detail(ride_id: str, dheaders: dict) -> dict:
    r = requests.get(f"{BASE}/api/health-isf/rides/{ride_id}", headers=dheaders, timeout=120)
    return r.json() if r.ok else {"error": r.text[:500]}


def _summarize_ride(ride: dict | None) -> dict:
    if not ride:
        return {}
    return {
        "ride_id": ride.get("id"),
        "passenger_name": ride.get("passenger_name"),
        "driver_id": ride.get("driver_id"),
        "trip_leg": ride.get("trip_leg"),
        "service_date": ride.get("service_date"),
        "pickup_time": ride.get("pickup_time"),
        "lifecycle_state": ride.get("lifecycle_state"),
        "status": ride.get("status"),
        "dispatch_status": ride.get("dispatch_status"),
        "round_trip_group_id": ride.get("round_trip_group_id"),
        "dispatch_eligible_at": ride.get("dispatch_eligible_at"),
        "scheduling_summary": ride.get("scheduling_summary"),
    }


def _api_snapshot(driver_id: str, headers: dict) -> dict:
    snap: dict = {}
    for ep in ENDPOINTS:
        r = requests.get(f"{BASE}/api/health-isf/drivers/{driver_id}/{ep}", headers=headers, timeout=120)
        try:
            snap[ep.split("?")[0]] = {"status": r.status_code, "body": r.json()}
        except ValueError:
            snap[ep.split("?")[0]] = {"status": r.status_code, "raw": r.text[:2000]}
    return snap


def _browser_probe(phone: str, driver_id: str, token: str) -> dict:
    network: list[dict] = []
    clicks: list[dict] = []

    init = f"""
    localStorage.clear();
    sessionStorage.clear();
    localStorage.setItem('amicor_platform_role', 'driver');
    localStorage.setItem('amicor_shell_role', 'driver');
    localStorage.setItem('amicor_last_mobile_surface', 'driver');
    localStorage.setItem('amicor_driver_session', JSON.stringify({{
      driver_id: {json.dumps(driver_id)},
      driver_name: 'Driver',
      role: 'driver',
      session_token: {json.dumps(token)},
      session_id: '',
      organization_id: '',
      updated_at: new Date().toISOString()
    }}));
    """

    with sync_playwright() as pw:
        browser = pw.chromium.launch(headless=True)
        ctx = browser.new_context(viewport={"width": 390, "height": 844}, is_mobile=True)
        ctx.add_init_script(init)
        page = ctx.new_page()

        def on_response(resp):
            url = resp.url
            if "/api/health-isf/drivers/" not in url:
                return
            path = urlparse(url).path
            entry = {"path": path, "status": resp.status}
            try:
                if resp.ok:
                    entry["body"] = resp.json()
            except Exception:
                pass
            network.append(entry)

        page.on("response", on_response)
        page.goto(f"{BASE}/app/mobile", wait_until="domcontentloaded", timeout=120000)
        page.wait_for_timeout(20000)

        ui = page.evaluate(
            """() => {
              const app = (window.AmiOpsShellState && window.AmiOpsShellState.driverApp) || {};
              const wf = (window.AmiOpsShellState && window.AmiOpsShellState.driverWorkflow) || {};
              const buttons = Array.from(document.querySelectorAll('[data-driver-action]')).map((b) => ({
                action: b.getAttribute('data-driver-action'),
                tripId: b.getAttribute('data-trip-id') || '',
                disabled: !!b.disabled,
                text: (b.textContent || '').trim().slice(0, 80)
              }));
              return {
                tripQueue: app.tripQueue || [],
                activeTripId: app.activeTripId || '',
                mobileUiState: app.mobileUiState || '',
                shiftOnline: !!app.shiftOnline,
                upcomingSchedule: wf.upcomingSchedule || [],
                activeOffer: wf.activeOffer || null,
                activeRide: wf.activeRide || null,
                workflowDriverId: wf.driverId || '',
                bodyText: (document.querySelector('#page-content') || document.body).innerText.slice(0, 4000),
                buttons
              };
            }"""
        )

        for action in ("accept_trip", "start_route"):
            btn = page.locator(f'[data-driver-action="{action}"]:not([disabled])').first
            if btn.count() == 0:
                clicks.append({"action": action, "clicked": False, "reason": "button disabled or missing"})
                continue
            pre_net = len(network)
            try:
                btn.click(timeout=5000)
                page.wait_for_timeout(4000)
            except Exception as exc:
                clicks.append({"action": action, "clicked": False, "error": str(exc)})
                continue
            post = network[pre_net:]
            clicks.append({
                "action": action,
                "clicked": True,
                "network_after_click": post,
            })

        stamp = time.strftime("%Y%m%d%H%M%S", time.gmtime())
        png = EVIDENCE / f"CURRENT_TRIP_{phone.replace('-', '')}_{stamp}.png"
        page.screenshot(path=str(png), full_page=True)
        browser.close()

    return {"ui": ui, "network": network, "clicks": clicks, "screenshot": str(png)}


def main() -> int:
    tokens = pa.resolve_production_tokens()
    dheaders = {"Authorization": f"Bearer {tokens['dispatcher_token']}"}
    live = requests.get(f"{BASE}/api/health/live", timeout=60).json()
    report: dict = {
        "timestamp_utc": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "deploy_commit": live.get("deploy_commit"),
        "drivers": {},
    }

    for phone in PHONES:
        driver_id, token, headers = _login(phone)
        snap = _api_snapshot(driver_id, headers)
        browser = _browser_probe(phone, driver_id, token)

        ride_ids: set[str] = set()
        for key in ("active-ride", "live-workspace", "active-offer"):
            body = snap.get(key, {}).get("body") or {}
            if isinstance(body, dict):
                ride = body.get("ride") or body.get("active_ride")
                if isinstance(ride, dict) and ride.get("id"):
                    ride_ids.add(str(ride["id"]))
                offer = body.get("offer")
                if isinstance(offer, dict) and offer.get("ride_id"):
                    ride_ids.add(str(offer["ride_id"]))
        assigned = snap.get("assigned-rides", {}).get("body")
        if isinstance(assigned, list):
            for row in assigned:
                if row.get("id"):
                    ride_ids.add(str(row["id"]))

        for trip in browser["ui"].get("tripQueue") or []:
            if trip.get("tripId"):
                ride_ids.add(str(trip["tripId"]))

        active_trip_id = browser["ui"].get("activeTripId") or ""
        if active_trip_id:
            ride_ids.add(active_trip_id)

        ride_details = {rid: _ride_detail(rid, dheaders) for rid in sorted(ride_ids) if rid}

        report["drivers"][phone] = {
            "driver_id": driver_id,
            "api": snap,
            "browser": browser,
            "ride_details": {rid: _summarize_ride(r) for rid, r in ride_details.items()},
            "current_trip_ride_id": active_trip_id or (browser["ui"].get("tripQueue") or [{}])[0].get("tripId") if browser["ui"].get("tripQueue") else "",
        }

    stamp = time.strftime("%Y%m%d%H%M%S", time.gmtime())
    EVIDENCE.mkdir(parents=True, exist_ok=True)
    out = EVIDENCE / f"CURRENT_TRIP_INVESTIGATION_{stamp}.json"
    out.write_text(json.dumps(report, indent=2, default=str), encoding="utf-8")
    print(json.dumps({
        "evidence": str(out),
        "1002_current": report["drivers"]["917-555-1002"].get("current_trip_ride_id"),
        "1004_current": report["drivers"]["917-555-1004"].get("current_trip_ride_id"),
        "1002_queue": len(report["drivers"]["917-555-1002"]["browser"]["ui"].get("tripQueue") or []),
        "1004_queue": len(report["drivers"]["917-555-1004"]["browser"]["ui"].get("tripQueue") or []),
    }, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
