"""Full post-login network trace for Driver 1004 on production.

Captures every driver mobile poll endpoint, websocket frames, and identifies
which response injects a reserved ride into the UI trip queue.
"""
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
if str(BACKEND) not in sys.path:
    sys.path.insert(0, str(BACKEND))

from scripts import production_auth as pa

BASE = pa.BASE
EVIDENCE = BACKEND.parent / "PRODUCTION_QA_EVIDENCE"
PHONE = "917-555-1004"
OWNER_PHONE = "917-555-1002"
TRACE_SECONDS = 70
POLL_INTERVAL_SEC = 5

WATCH_RIDE_IDS = {
    "a6722aae-4466-4080-9241-a358b143147a",  # Mahune outbound
    "cba6723a-764b-49a2-a5c9-fcb37a78cbfb",  # Mahune return
    "91ba3d7d-29c8-4bb8-8eea-493bcaab5d2d",  # Josephine outbound
    "c431b147-07f3-408c-b765-1540b8c2d623",  # Josephine return
}
DRIVER_ENDPOINTS = (
    "active-ride",
    "active-offer",
    "upcoming-schedule",
    "assigned-rides?limit=15",
    "live-workspace",
    "completion-snapshot?limit=50",
)


def _json_contains_watch_ids(payload: object) -> list[str]:
    text = json.dumps(payload, default=str)
    return [rid for rid in WATCH_RIDE_IDS if rid in text]


def _login_driver(phone: str) -> tuple[str, str, dict]:
    login = requests.post(f"{BASE}/api/health-isf/drivers/mobile-login", json={"phone": phone}, timeout=120)
    login.raise_for_status()
    body = login.json()
    driver_id = str(body["driver_id"])
    token = str(body["session_token"])
    headers = {"X-Driver-Session-Token": token}
    return driver_id, token, headers


def _poll_api_trace(driver_id: str, headers: dict) -> list[dict]:
    entries: list[dict] = []
    deadline = time.time() + TRACE_SECONDS
    seq = 0
    while time.time() < deadline:
        seq += 1
        stamp = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
        for path in DRIVER_ENDPOINTS:
            url = f"{BASE}/api/health-isf/drivers/{driver_id}/{path}"
            started = time.time()
            resp = requests.get(url, headers=headers, timeout=120)
            elapsed_ms = int((time.time() - started) * 1000)
            try:
                body = resp.json()
            except ValueError:
                body = {"raw": resp.text[:2000]}
            hits = _json_contains_watch_ids(body)
            entry = {
                "seq": seq,
                "timestamp_utc": stamp,
                "method": "GET",
                "path": f"/api/health-isf/drivers/{driver_id}/{path.split('?')[0]}",
                "status": resp.status_code,
                "elapsed_ms": elapsed_ms,
                "watch_ride_hits": hits,
                "body": body if hits else {"truncated": json.dumps(body, default=str)[:1500]},
            }
            entries.append(entry)
        time.sleep(POLL_INTERVAL_SEC)
    return entries


def main() -> int:
    tokens = pa.resolve_production_tokens()
    deploy = requests.get(f"{BASE}/api/runtime/version", timeout=60)
    deploy_body = deploy.json() if deploy.ok else {}

    driver_id, token, headers = _login_driver(PHONE)
    owner_id, _, owner_headers = _login_driver(OWNER_PHONE)

    api_poll_log = _poll_api_trace(driver_id, headers)

    injection_hits = [e for e in api_poll_log if e.get("watch_ride_hits")]
    network_log: list[dict] = []
    ws_log: list[dict] = []

    init = f"""
    localStorage.clear();
    sessionStorage.clear();
    localStorage.setItem('amicor_platform_role', 'driver');
    localStorage.setItem('amicor_shell_role', 'driver');
    localStorage.setItem('amicor_last_mobile_surface', 'driver');
    localStorage.setItem('amicor_driver_session', JSON.stringify({{
      driver_id: {json.dumps(driver_id)},
      driver_name: 'Driver 1004',
      role: 'driver',
      session_token: {json.dumps(token)},
      session_id: '',
      organization_id: '',
      updated_at: new Date().toISOString()
    }}));
    """

    stamp = time.strftime("%Y%m%d%H%M%S", time.gmtime())
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=True)
        context = browser.new_context(viewport={"width": 390, "height": 844}, is_mobile=True)
        context.add_init_script(init)
        page = context.new_page()

        def on_response(response):
            url = response.url
            if "/api/" not in url and "/ws" not in url and "websocket" not in url:
                return
            path = urlparse(url).path
            entry: dict = {
                "timestamp_utc": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
                "path": path,
                "status": response.status,
                "url": url,
            }
            try:
                if response.ok and "json" in (response.headers.get("content-type") or ""):
                    payload = response.json()
                    hits = _json_contains_watch_ids(payload)
                    entry["watch_ride_hits"] = hits
                    if hits:
                        entry["body"] = payload
                    else:
                        entry["body_preview"] = json.dumps(payload, default=str)[:1200]
            except Exception as exc:
                entry["parse_error"] = str(exc)
            network_log.append(entry)

        def on_websocket(ws):
            ws_log.append({"event": "websocket_open", "url": ws.url, "timestamp_utc": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())})

            def frame_received(payload):
                text = payload if isinstance(payload, str) else str(payload)
                hits = [rid for rid in WATCH_RIDE_IDS if rid in text]
                if hits or "ride" in text.lower():
                    ws_log.append({
                        "event": "websocket_frame",
                        "url": ws.url,
                        "watch_ride_hits": hits,
                        "preview": text[:2000],
                        "timestamp_utc": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
                    })

            ws.on("framereceived", frame_received)

        page.on("response", on_response)
        page.on("websocket", on_websocket)
        page.goto(f"{BASE}/app/mobile", wait_until="domcontentloaded", timeout=120000)
        page.wait_for_timeout(TRACE_SECONDS * 1000)

        ui_state = page.evaluate(
            """() => ({
              tripQueue: (window.AmiOpsShellState && window.AmiOpsShellState.driverApp && window.AmiOpsShellState.driverApp.tripQueue) || [],
              activeTripId: (window.AmiOpsShellState && window.AmiOpsShellState.driverApp && window.AmiOpsShellState.driverApp.activeTripId) || '',
              workflowDriverId: (window.AmiOpsShellState && window.AmiOpsShellState.driverWorkflow && window.AmiOpsShellState.driverWorkflow.driverId) || '',
              hasAcceptTrip: !!document.querySelector('[data-driver-action="accept_trip"]:not([disabled])'),
              body: (document.querySelector('#page-content') || document.body).innerText.slice(0, 3000)
            })"""
        )
        png = EVIDENCE / f"DRIVER1004_FULL_TRACE_{stamp}.png"
        page.screenshot(path=str(png), full_page=True)
        browser.close()

    browser_injection = [e for e in network_log if e.get("watch_ride_hits")]
    ws_injection = [e for e in ws_log if e.get("watch_ride_hits")]

    report = {
        "timestamp_utc": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "production_base": BASE,
        "deploy_version": deploy_body,
        "driver_1004_id": driver_id,
        "driver_1002_id": owner_id,
        "watch_ride_ids": sorted(WATCH_RIDE_IDS),
        "api_poll_log": api_poll_log,
        "api_injection_hits": injection_hits,
        "browser_network_log": network_log,
        "browser_injection_hits": browser_injection,
        "websocket_log": ws_log,
        "websocket_injection_hits": ws_injection,
        "ui_state": ui_state,
        "screenshot": str(png),
        "verdict": {
            "api_leak_endpoints": sorted({e["path"] for e in injection_hits}),
            "browser_leak_endpoints": sorted({e["path"] for e in browser_injection}),
            "trip_queue_len": len(ui_state.get("tripQueue") or []),
            "accept_trip_enabled": bool(ui_state.get("hasAcceptTrip")),
        },
    }

    EVIDENCE.mkdir(parents=True, exist_ok=True)
    out = EVIDENCE / f"DRIVER1004_FULL_TRACE_{stamp}.json"
    out.write_text(json.dumps(report, indent=2, default=str), encoding="utf-8")
    print(json.dumps(report["verdict"], indent=2))
    print(f"evidence={out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
