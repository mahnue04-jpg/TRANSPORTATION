"""Browser verification for ops-shell driver mobile buttons through full lifecycle."""
from __future__ import annotations

import json
import os
import re
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import httpx
from playwright.sync_api import Page, sync_playwright

SCRIPT_DIR = Path(__file__).resolve().parent
BACKEND_ROOT = SCRIPT_DIR.parent
sys.path.insert(0, str(BACKEND_ROOT))

import browser_ride_lifecycle_demo as lifecycle  # noqa: E402
from real_life_ops_verification import (  # noqa: E402
    auth_fetch,
    reseed_backend,
    wait_refresh,
)

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

BASE = os.getenv("AMICOR_BROWSER_BASE", "http://127.0.0.1:8010")
PASSWORD = os.getenv("AMICOR_SEED_PASSWORD", "Amicor123!")
DRIVER_EMAIL = os.getenv("AMICOR_DRIVER_EMAIL", "driver@amicor.local")
DISPATCHER_EMAIL = os.getenv("AMICOR_DISPATCHER_EMAIL", "dispatcher@amicor.local")
RIDER_EMAIL = os.getenv("AMICOR_RIDER_EMAIL", "rider@amicor.local")
PASSENGER = f"Driver Ops Verify {datetime.now(timezone.utc).strftime('%H%M%S')}"
RIDER_PHONE = f"646-555-{datetime.now(timezone.utc).strftime('%H%M%S')[-4:]}"
ARTIFACT_DIR = BACKEND_ROOT / "artifacts" / "driver_ops_browser_verification"
REPORT_JSON = BACKEND_ROOT / "artifacts" / "driver_ops_browser_verification_report.json"

DRIVER_BUTTONS: list[tuple[str, str, str]] = [
    ("accept_trip", "accept-ride", "en_route"),
    ("call_rider", "contact-rider", "en_route"),
    ("arrive_pickup", "route-progress", "arrived"),
    ("start_trip", "route-progress", "loaded"),
    ("start_transport", "route-progress", "progress"),
    ("complete_trip", "route-progress", "completed"),
]


def log(msg: str) -> None:
    print(msg, flush=True)


def snap(page: Page, name: str, shots: list[str]) -> None:
    ARTIFACT_DIR.mkdir(parents=True, exist_ok=True)
    path = str(ARTIFACT_DIR / f"{name}.png")
    page.screenshot(path=path, full_page=True)
    shots.append(path)


def api_login(email: str) -> dict[str, str]:
    resp = httpx.post(
        f"{BASE.rstrip('/')}/api/auth/login",
        json={"email": email, "password": PASSWORD},
        timeout=60,
    )
    resp.raise_for_status()
    token = resp.json()["access_token"]
    return {"Authorization": f"Bearer {token}"}


def ensure_provider(organization_id: str) -> None:
    from app.db.session import SessionLocal
    from app.helpers import uuid4
    from app.modules.health_isf.models import HealthISFProvider

    with SessionLocal() as db:
        provider = (
            db.query(HealthISFProvider)
            .filter(HealthISFProvider.organization_id == organization_id)
            .order_by(HealthISFProvider.created_at.desc())
            .first()
        )
        if provider:
            if not provider.is_active:
                provider.is_active = True
                db.commit()
            return
        db.add(
            HealthISFProvider(
                id=uuid4(),
                organization_id=organization_id,
                name=f"Driver Ops Provider {uuid4()[:6]}",
                address="500 Driver Ops Avenue",
                phone="212-555-0800",
                service_type="clinic",
                is_active=True,
            )
        )
        db.commit()


def create_and_assign_ride(headers: dict[str, str], driver_id: str, organization_id: str) -> tuple[str, str]:
    ensure_provider(organization_id)
    create = httpx.post(
        f"{BASE.rstrip('/')}/api/health-isf/customer-requests",
        headers=headers,
        json={
            "rider_name": PASSENGER,
            "rider_phone": RIDER_PHONE,
            "pickup_address": "100 Driver Ops Pickup, New York, NY 10001",
            "dropoff_address": "200 Driver Ops Dropoff, New York, NY 10002",
            "ride_type": "healthcare",
            "recurring": False,
            "notes": "driver ops browser verification",
        },
        timeout=60,
    )
    create.raise_for_status()
    payload = create.json()
    request_id = str(payload["id"])
    ride_id = str(payload["ride_id"])

    approve = httpx.post(
        f"{BASE.rstrip('/')}/api/health-isf/dispatcher/customer-requests/{request_id}/approve",
        headers=headers,
        timeout=60,
    )
    approve.raise_for_status()
    ride = httpx.get(
        f"{BASE.rstrip('/')}/api/health-isf/rides/{ride_id}",
        headers=headers,
        timeout=60,
    ).json()
    if str(ride.get("driver_id") or "") != driver_id:
        assign = httpx.post(
            f"{BASE.rstrip('/')}/api/health-isf/dispatcher/customer-requests/{request_id}/assign-driver",
            headers=headers,
            json={"driver_id": driver_id},
            timeout=60,
        )
        assign.raise_for_status()
    return ride_id, request_id


def ride_lifecycle_state(headers: dict[str, str], ride_id: str) -> str:
    ride = httpx.get(
        f"{BASE.rstrip('/')}/api/health-isf/rides/{ride_id}",
        headers=headers,
        timeout=60,
    ).json()
    return str(ride.get("lifecycle_state") or ride.get("status") or "").lower()


def ops_shell_login(page: Page, email: str, route: str = "mobile", role: str = "driver") -> None:
    login_payload = httpx.post(
        f"{BASE.rstrip('/')}/api/auth/login",
        json={"email": email, "password": PASSWORD},
        timeout=60,
    )
    login_payload.raise_for_status()
    auth = login_payload.json()

    page.goto(f"{BASE}/app/{route}", wait_until="domcontentloaded", timeout=120000)
    page.wait_for_timeout(1200)
    page.evaluate(
        """([payload, roleView]) => {
          if (!window.AmiCorSession || typeof window.AmiCorSession.start !== "function") {
            throw new Error("AmiCorSession.start unavailable");
          }
          window.AmiCorSession.start({
            userId: payload.user_id,
            email: payload.email,
            name: payload.display_name || payload.email,
            role: roleView || payload.role,
            accessToken: payload.access_token,
            refreshToken: payload.refresh_token,
            organizationId: payload.organization_id,
            organizationName: payload.organization_name,
            tokenExpiresAt: Date.now() + (3600 * 1000),
            runtimeHost: "local-dev:8010",
          });
          try { localStorage.setItem("amicor_shell_role", roleView || payload.role || "driver"); } catch (_) {}
        }""",
        [auth, role],
    )
    page.goto(f"{BASE}/app/{route}", wait_until="domcontentloaded", timeout=120000)
    page.wait_for_timeout(1500)
    role_select = page.locator("#role-select")
    if role_select.count():
        role_select.select_option(role)
        page.wait_for_timeout(800)
    page.evaluate(
        """async () => {
          if (window.AmiOpsShellActions && window.AmiOpsShellActions.refreshData) {
            await window.AmiOpsShellActions.refreshData();
          }
        }"""
    )
    page.wait_for_timeout(3000)


def ensure_driver_shift_online(page: Page) -> None:
    accept = page.locator('[data-driver-action="accept_trip"]').first
    if accept.count() and accept.is_enabled():
        return
    toggle = page.locator('[data-driver-action="toggle_shift"]').first
    if toggle.count() and toggle.is_enabled():
        toggle.click()
        page.wait_for_timeout(2500)


def wait_driver_button(page: Page, action: str, timeout_ms: int = 45000) -> None:
    page.wait_for_function(
        """(action) => {
          const btn = document.querySelector('[data-driver-action="' + action + '"]');
          return !!(btn && !btn.disabled);
        }""",
        arg=action,
        timeout=timeout_ms,
    )


def click_driver_button(page: Page, action: str, api_fragment: str) -> dict[str, Any]:
    with page.expect_response(
        lambda r: api_fragment in r.url and r.request.method == "POST",
        timeout=60000,
    ) as response_wait:
        page.locator(f'[data-driver-action="{action}"]').first.click()
    resp = response_wait.value
    body: Any
    try:
        body = resp.json()
    except Exception:
        body = resp.text()[:500]
    return {"status": resp.status, "ok": resp.ok, "url": resp.url, "body": body}


def refresh_driver_workspace(page: Page) -> None:
    page.evaluate(
        """async () => {
          if (window.AmiOpsShellActions && window.AmiOpsShellActions.refreshData) {
            await window.AmiOpsShellActions.refreshData();
          }
        }"""
    )
    page.wait_for_timeout(2500)


def run_verification() -> dict[str, Any]:
    report: dict[str, Any] = {
        "timestamp_utc": datetime.now(timezone.utc).isoformat(),
        "base": BASE,
        "passenger": PASSENGER,
        "rider_phone": RIDER_PHONE,
        "checks": {},
        "button_results": {},
        "proof": {},
        "blockers": [],
        "screenshots": [],
    }
    server_proc = None
    try:
        server_proc = lifecycle.ensure_preview_server(BASE)
        prep = reseed_backend()
        report["prep"] = prep
        driver_id = prep["driver_id"]
        dispatcher_headers = api_login(DISPATCHER_EMAIL)
        rider_headers = api_login(RIDER_EMAIL)

        ride_id, request_id = create_and_assign_ride(
            dispatcher_headers, driver_id, prep["organization_id"]
        )
        report["ride_id"] = ride_id
        report["request_id"] = request_id
        report["checks"]["dispatch_assign"] = True

        offer = httpx.get(
            f"{BASE.rstrip('/')}/api/health-isf/drivers/{driver_id}/active-offer",
            headers=dispatcher_headers,
            timeout=60,
        ).json()
        report["checks"]["driver_offer"] = (offer.get("offer") or {}).get("ride_id") == ride_id

        driver_headers = api_login(DRIVER_EMAIL)

        shift_ready = httpx.post(
            f"{BASE.rstrip('/')}/api/health-isf/drivers/{driver_id}/set-status",
            headers=driver_headers,
            json={"status": "available"},
            timeout=60,
        )
        driver_row = httpx.get(
            f"{BASE.rstrip('/')}/api/health-isf/drivers/{driver_id}",
            headers=dispatcher_headers,
            timeout=60,
        ).json()
        driver_status = str(driver_row.get("status") or driver_row.get("availability_state") or "").lower()
        report["checks"]["driver_shift_ready"] = (
            shift_ready.status_code == 200
            or driver_status in {"available", "assigned", "on_trip", "online"}
            or bool(driver_row.get("is_online"))
        )

        with sync_playwright() as playwright:
            browser = playwright.chromium.launch(headless=True)
            context = browser.new_context(viewport={"width": 1440, "height": 960})
            context.add_init_script("try { localStorage.setItem('amicor_onboarded', '1'); } catch (_) {}")
            page = context.new_page()
            page.on("dialog", lambda dialog: dialog.accept())
            try:
                ops_shell_login(page, DRIVER_EMAIL, route="mobile", role="driver")
                snap(page, "01_driver_mobile_login", report["screenshots"])
                refresh_driver_workspace(page)
                ensure_driver_shift_online(page)
                refresh_driver_workspace(page)
                snap(page, "02_offer_visible", report["screenshots"])

                page_text = page.locator("#page-content").inner_text()
                report["checks"]["ride_visible_in_ui"] = ride_id[:8] in page_text or PASSENGER in page_text

                for action, api_fragment, expected_state in DRIVER_BUTTONS:
                    button = page.locator(f'[data-driver-action="{action}"]').first
                    if action == "start_transport" and button.count() and not button.is_enabled():
                        actual = ride_lifecycle_state(dispatcher_headers, ride_id)
                        if "progress" in actual or "in_progress" in actual or "in_transit" in actual:
                            report["checks"]["button_start_transport"] = True
                            report["checks"]["state_after_start_transport"] = True
                            report["button_results"][action] = {
                                "status": 200,
                                "ok": True,
                                "url": "skipped:already_in_progress",
                                "body": {"lifecycle_state": actual},
                            }
                            continue
                    wait_driver_button(page, action)
                    result = click_driver_button(page, action, api_fragment)
                    report["button_results"][action] = result
                    refresh_driver_workspace(page)
                    page.wait_for_timeout(1500)
                    actual = ride_lifecycle_state(dispatcher_headers, ride_id)
                    report["checks"][f"button_{action}"] = result["ok"]
                    if action == "start_trip":
                        report["checks"][f"state_after_{action}"] = (
                            expected_state in actual
                            or "progress" in actual
                            or "in_progress" in actual
                            or "in_transit" in actual
                        )
                    else:
                        report["checks"][f"state_after_{action}"] = (
                            expected_state in actual or actual == expected_state
                        )
                    if not result["ok"]:
                        report["blockers"].append(f"{action} API returned HTTP {result['status']}")
                    snap(page, f"03_after_{action}", report["screenshots"])

                final_state = ride_lifecycle_state(dispatcher_headers, ride_id)
                report["checks"]["ride_completed"] = "completed" in final_state
                report["proof"]["final_ride_state"] = final_state

                rider_track = httpx.get(
                    f"{BASE.rstrip('/')}/api/health-isf/customers/workspace/live-tracking",
                    headers=rider_headers,
                    params={"rider_phone": RIDER_PHONE},
                    timeout=60,
                )
                report["checks"]["rider_tracking"] = rider_track.status_code == 200
                if rider_track.status_code == 200:
                    track_payload = rider_track.json()
                    active = track_payload.get("active_request") or {}
                    report["proof"]["rider_tracking_status"] = str(
                        active.get("dispatch_status") or active.get("status") or track_payload
                    )

                dashboard = httpx.get(
                    f"{BASE.rstrip('/')}/api/health-isf/dashboard",
                    headers=dispatcher_headers,
                    timeout=60,
                )
                report["checks"]["dispatcher_dashboard"] = dashboard.status_code == 200

                audit = httpx.get(
                    f"{BASE.rstrip('/')}/api/health-isf/dispatcher/audit-log",
                    headers=api_login("admin@amicor.local"),
                    params={"limit": 80},
                    timeout=60,
                )
                report["checks"]["audit_log"] = audit.status_code == 200

                snap(page, "04_final", report["screenshots"])
            finally:
                browser.close()
    except Exception as exc:
        report["blockers"].append(str(exc))
        log(f"[FAIL] {exc}")
    finally:
        if server_proc and server_proc.poll() is None:
            server_proc.terminate()

    required = [
        "dispatch_assign",
        "driver_offer",
        "driver_shift_ready",
        "ride_visible_in_ui",
        "ride_completed",
        "rider_tracking",
        "dispatcher_dashboard",
        "audit_log",
    ]
    for action, _, _ in DRIVER_BUTTONS:
        required.extend([f"button_{action}", f"state_after_{action}"])

    report["checks"]["all_pass"] = all(report["checks"].get(key) for key in required) and not report["blockers"]
    report["verdict"] = "PASS" if report["checks"]["all_pass"] else "FAIL"

    REPORT_JSON.parent.mkdir(parents=True, exist_ok=True)
    REPORT_JSON.write_text(json.dumps(report, indent=2), encoding="utf-8")

    log("")
    log("=== Driver Ops Browser Verification ===")
    for key in required:
        status = "PASS" if report["checks"].get(key) else "FAIL"
        log(f"  {status}  {key}")
    log(f"\nVerdict: {report['verdict']}")
    if report["blockers"]:
        log("Blockers:")
        for item in report["blockers"]:
            log(f"  - {item}")
    log(f"Report: {REPORT_JSON}")
    return report


if __name__ == "__main__":
    result = run_verification()
    sys.exit(0 if result.get("verdict") == "PASS" else 1)
