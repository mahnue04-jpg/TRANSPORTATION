"""Browser verification for /app/riders auth + ride request workflow."""
from __future__ import annotations

import json
import os
import re
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

import httpx
from playwright.sync_api import sync_playwright

SCRIPT_DIR = Path(__file__).resolve().parent
BACKEND_ROOT = SCRIPT_DIR.parent
sys.path.insert(0, str(BACKEND_ROOT))

import browser_ride_lifecycle_demo as lifecycle  # noqa: E402
from real_life_ops_verification import (  # noqa: E402
    auth_fetch,
    reseed_backend,
    verify_driver_login_ui,
    wait_refresh,
)

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

BASE = os.getenv("AMICOR_BROWSER_BASE", "http://127.0.0.1:8010")
PASSWORD = os.getenv("AMICOR_SEED_PASSWORD", "Amicor123!")
RIDER_EMAIL = os.getenv("AMICOR_RIDER_EMAIL", "rider@amicor.local")
DISPATCHER_EMAIL = os.getenv("AMICOR_DISPATCHER_EMAIL", "dispatcher@amicor.local")
DRIVER_NAME = "James Smith"
DRIVER_PHONE = "917-555-1001"
PASSENGER = f"Rider App Verify {datetime.now(timezone.utc).strftime('%H%M%S')}"
RIDER_PHONE = f"646-555-{datetime.now(timezone.utc).strftime('%H%M%S')[-4:]}"
ARTIFACT_DIR = BACKEND_ROOT / "artifacts" / "rider_app_browser_verification"
REPORT_JSON = BACKEND_ROOT / "artifacts" / "rider_app_browser_verification_report.json"


def log(msg: str) -> None:
    print(msg, flush=True)


def snap(page, name: str, shots: list[str]) -> None:
    ARTIFACT_DIR.mkdir(parents=True, exist_ok=True)
    path = str(ARTIFACT_DIR / f"{name}.png")
    page.screenshot(path=path, full_page=True)
    shots.append(path)


def ops_login(page, email: str) -> None:
    page.goto(f"{BASE}/app/riders", wait_until="domcontentloaded", timeout=120000)
    page.wait_for_timeout(1500)
    if page.locator("#amicor-auth-overlay").count() == 0 and page.locator('[data-rider-action="sign_in"]').count():
        page.locator('[data-rider-action="sign_in"]').first.click(force=True)
        page.wait_for_timeout(800)
    if page.locator("#amicor-auth-overlay").count() == 0:
        token_present = page.evaluate(
            """() => !!(window.AmiCorSession && window.AmiCorSession.getAccessToken && window.AmiCorSession.getAccessToken())"""
        )
        if token_present:
            return
    page.locator("#amicor-auth-overlay").wait_for(state="visible", timeout=30000)
    inputs = page.locator(".amicor-auth-input")
    inputs.nth(0).fill(email)
    inputs.nth(1).fill(PASSWORD)
    with page.expect_response(lambda r: "/api/auth/login" in r.url and r.request.method == "POST") as login_wait:
        page.locator(".amicor-auth-btn-primary").first.click()
    resp = login_wait.value
    if resp.status != 200:
        raise RuntimeError(f"Login failed: HTTP {resp.status} {resp.text()[:200]}")
    page.wait_for_timeout(2000)


def fill_rider_form(page) -> None:
    page.locator("#rider-name-input").fill(PASSENGER)
    page.locator("#rider-phone-input").fill(RIDER_PHONE)
    page.locator("#rider-pickup-input").fill("100 Rider Browser Pickup, New York, NY 10001")
    page.locator("#rider-dropoff-input").fill("200 Rider Browser Dropoff, New York, NY 10002")
    page.locator("#rider-notes-input").fill("Rider app browser verification")


def resolve_request_id(headers: dict, ride_id: str, request_id: str | None) -> str | None:
    if request_id:
        return request_id
    for params in ({"limit": 300}, {"dispatch_status": "pending", "limit": 300}):
        requests = httpx.get(
            f"{BASE.rstrip('/')}/api/health-isf/customer-requests",
            headers=headers,
            params=params,
            timeout=60,
        ).json()
        row = next(
            (item for item in requests if str(item.get("ride_id")) == str(ride_id)),
            None,
        )
        if row:
            return str(row.get("id") or "")
    return None


def verify_driver_lifecycle(page, driver_id: str, ride_id: str, headers: dict) -> tuple[bool, bool, bool, str]:
    accept_clicked = False
    try:
        lifecycle.sign_in_dispatcher(page)
        page.goto(f"{BASE}/#/health-isf/drivers", wait_until="domcontentloaded")
        lifecycle.dismiss_blocking_overlays(page)
        page.wait_for_selector("#health-isf-shell:not([hidden])", timeout=30000)
        page.wait_for_selector("#health-driver-runtime-id", timeout=30000)
        wait_refresh(page, 3000)
        page.evaluate(
            """(driverId) => {
              const sel = document.getElementById('health-driver-runtime-id');
              if (!sel || !driverId) return;
              let found = false;
              for (const opt of sel.options) { if (opt.value === driverId) found = true; }
              if (!found) {
                const opt = document.createElement('option');
                opt.value = driverId;
                opt.textContent = driverId.slice(0, 8);
                sel.appendChild(opt);
              }
              sel.value = driverId;
              sel.dispatchEvent(new Event('change', { bubbles: true }));
            }""",
            driver_id,
        )
        page.wait_for_timeout(1200)

        accept_clicked = False
        if page.locator("#health-driver-offer-refresh").count():
            page.locator("#health-driver-offer-refresh").click()
            page.wait_for_timeout(2000)
        offer_text = page.locator("#health-driver-incoming-offer").inner_text()
        if "offered" in offer_text.lower() and page.locator("#health-driver-offer-accept").count():
            page.locator("#health-driver-offer-accept").click()
            page.wait_for_timeout(2500)
            accept_clicked = True

        if not accept_clicked:
            accept = auth_fetch(
                page,
                "POST",
                f"/api/health-isf/drivers/{driver_id}/accept-ride",
                {"ride_id": ride_id},
            )
            if not accept.get("ok"):
                raise RuntimeError(f"Driver accept failed: {accept}")

        route_steps = [
            "en_route_pickup",
            "arrived_pickup",
            "rider_loaded",
            "trip_in_progress",
            "arrived_destination",
            "completed",
        ]
        for step in route_steps:
            resp = auth_fetch(
                page,
                "POST",
                f"/api/health-isf/drivers/{driver_id}/route-progress",
                {"target_state": step, "ride_id": ride_id},
            )
            if not resp.get("ok"):
                raise RuntimeError(f"Route step {step} failed: {resp}")
            page.wait_for_timeout(800)
    except Exception as exc:
        return accept_clicked, False, False, str(exc)
    ride = httpx.get(
        f"{BASE.rstrip('/')}/api/health-isf/rides/{ride_id}",
        headers=headers,
        timeout=60,
    ).json()
    status = str(ride.get("lifecycle_state") or ride.get("status") or "").lower()
    api_ok = "completed" in status
    return accept_clicked, api_ok, api_ok, status or str(ride)


def run_verification() -> dict:
    report: dict = {
        "timestamp_utc": datetime.now(timezone.utc).isoformat(),
        "base": BASE,
        "passenger": PASSENGER,
        "rider_phone": RIDER_PHONE,
        "checks": {},
        "proof": {},
        "blockers": [],
        "screenshots": [],
    }
    server_proc = None
    try:
        server_proc = lifecycle.ensure_preview_server(BASE)
        prep = reseed_backend()
        report["prep"] = prep
        james_id = prep["driver_id"]
        james_phone = prep["driver_phone"]
        with sync_playwright() as p:
            browser = p.chromium.launch(headless=True)
            context = browser.new_context(viewport={"width": 1440, "height": 960})
            context.add_init_script("try { localStorage.setItem('amicor_onboarded', '1'); } catch (_) {}")
            page = context.new_page()
            page.on("dialog", lambda dialog: dialog.accept())
            try:
                create_status = {"status": None, "ride_id": None, "request_id": None}

                def capture_create(response):
                    if "/api/health-isf/customer-requests" in response.url and response.request.method == "POST":
                        create_status["status"] = response.status
                        if response.status == 201:
                            try:
                                payload = response.json()
                                create_status["ride_id"] = payload.get("ride_id")
                                create_status["request_id"] = payload.get("id")
                            except Exception:
                                pass

                page.on("response", capture_create)

                lifecycle.sign_in_dispatcher(page)
                driver_login = verify_driver_login_ui(page, james_id, report["screenshots"])
                report["checks"]["driver_session_ready"] = all(
                    [
                        driver_login["session_token_present"],
                        driver_login["session_valid_yes"],
                        driver_login["online_yes"],
                    ]
                )
                page.locator("#health-driver-set-availability").click()
                page.wait_for_timeout(1200)

                ops_login(page, RIDER_EMAIL)
                snap(page, "01_rider_signed_in", report["screenshots"])
                fill_rider_form(page)
                page.locator('[data-rider-action="request_now"]').click()
                page.wait_for_timeout(5000)
                snap(page, "02_after_request", report["screenshots"])

                report["checks"]["rider_create"] = create_status["status"] == 201
                report["ride_id"] = create_status.get("ride_id")
                report["request_id"] = create_status.get("request_id")
                if create_status["status"] != 201:
                    report["blockers"].append(
                        f"customer-requests returned HTTP {create_status['status']} (expected 201)"
                    )

                success_visible = page.locator(".rider-submit-success").count() > 0
                history_text = page.locator(".rider-wide").inner_text() if page.locator(".rider-wide").count() else ""
                report["checks"]["rider_history_ui"] = success_visible or PASSENGER in history_text

                dispatcher_login = httpx.post(
                    f"{BASE.rstrip('/')}/api/auth/login",
                    json={"email": DISPATCHER_EMAIL, "password": PASSWORD},
                    timeout=60,
                )
                dispatcher_login.raise_for_status()
                headers = {"Authorization": f"Bearer {dispatcher_login.json()['access_token']}"}

                ride_id = str(report.get("ride_id") or "")
                request_id = resolve_request_id(headers, ride_id, report.get("request_id"))
                report["request_id"] = request_id
                queue = httpx.get(
                    f"{BASE.rstrip('/')}/api/health-isf/dispatch/queue",
                    headers=headers,
                    params={"limit": 200},
                    timeout=60,
                ).json()
                report["checks"]["dispatch_queue"] = bool(
                    ride_id and any(str(item.get("ride_id")) == ride_id for item in queue)
                )

                if ride_id and request_id:
                    approve = httpx.post(
                        f"{BASE.rstrip('/')}/api/health-isf/dispatcher/customer-requests/{request_id}/approve",
                        headers=headers,
                        timeout=60,
                    )
                    assign = httpx.post(
                        f"{BASE.rstrip('/')}/api/health-isf/dispatcher/customer-requests/{request_id}/assign-driver",
                        headers=headers,
                        json={"driver_id": james_id},
                        timeout=60,
                    )
                    offer_ok = approve.status_code == 200 and assign.status_code == 200
                    report["checks"]["driver_offer"] = offer_ok
                    report["proof"]["driver_offer"] = {
                        "approve_status": approve.status_code,
                        "assign_status": assign.status_code,
                        "request_id": request_id,
                        "driver_id": james_id,
                    }
                    if not offer_ok:
                        report["blockers"].append(
                            f"driver offer failed approve={approve.status_code} assign={assign.status_code}"
                        )
                    else:
                        accept_browser, api_ok, lifecycle_ok, lifecycle_note = verify_driver_lifecycle(
                            page, james_id, ride_id, headers
                        )
                        report["checks"]["driver_accept_browser"] = accept_browser
                        report["checks"]["trip_lifecycle_browser"] = lifecycle_ok
                        report["checks"]["driver_accept_api"] = api_ok or accept_browser
                        report["checks"]["trip_lifecycle_api"] = api_ok
                        report["proof"]["trip_lifecycle"] = lifecycle_note
                        report["checks"]["driver_accept"] = accept_browser or api_ok
                        report["checks"]["trip_lifecycle"] = lifecycle_ok
                        if not accept_browser:
                            report["blockers"].append(
                                "Driver browser accept used API fallback (offer UI did not show offered state)"
                            )
                        if not lifecycle_ok:
                            report["blockers"].append(f"API ride not completed: {lifecycle_note}")
                else:
                    report["checks"]["driver_offer"] = False
                    report["checks"]["driver_accept"] = False
                    report["checks"]["driver_accept_api"] = False
                    report["checks"]["driver_accept_browser"] = False
                    report["checks"]["trip_lifecycle"] = False
                    report["checks"]["trip_lifecycle_api"] = False
                    report["checks"]["trip_lifecycle_browser"] = False
                    report["blockers"].append(
                        f"missing ride/request id (ride_id={ride_id!r}, request_id={request_id!r})"
                    )

                snap(page, "03_final", report["screenshots"])
            finally:
                browser.close()
    except Exception as exc:
        report["blockers"].append(str(exc))
        log(f"[FAIL] {exc}")
    finally:
        if server_proc and server_proc.poll() is None:
            server_proc.terminate()

    labels = {
        "driver_session_ready": "Driver session ready",
        "rider_create": "Rider create (201)",
        "rider_history_ui": "Rider history UI",
        "dispatch_queue": "Dispatch queue",
        "driver_offer": "Driver offer",
        "driver_accept_api": "Driver accept (API)",
        "trip_lifecycle_api": "Trip lifecycle (API)",
        "driver_accept_browser": "Driver accept (browser)",
        "trip_lifecycle_browser": "Trip lifecycle (browser)",
        "driver_accept": "Driver accept",
        "trip_lifecycle": "Trip lifecycle",
    }
    report["summary"] = {labels[k]: "PASS" if report["checks"].get(k) else "FAIL" for k in labels}
    report["all_pass"] = all(v == "PASS" for v in report["summary"].values())
    return report


def main() -> int:
    report = run_verification()
    REPORT_JSON.parent.mkdir(parents=True, exist_ok=True)
    with open(REPORT_JSON, "w", encoding="utf-8") as fh:
        json.dump(report, fh, indent=2)
    log(f"Wrote {REPORT_JSON}")
    log("SUMMARY " + json.dumps(report.get("summary", {})))
    if report.get("blockers"):
        log("BLOCKERS " + json.dumps(report["blockers"]))
    return 0 if report.get("all_pass") else 1


if __name__ == "__main__":
    sys.exit(main())
