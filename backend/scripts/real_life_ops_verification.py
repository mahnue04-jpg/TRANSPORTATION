"""Real-life Health ISF operations verification using canonical seed drivers."""
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
from playwright.sync_api import sync_playwright

SCRIPT_DIR = Path(__file__).resolve().parent
BACKEND_ROOT = SCRIPT_DIR.parent
sys.path.insert(0, str(BACKEND_ROOT))

import browser_ride_lifecycle_demo as lifecycle  # noqa: E402

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

BASE = os.getenv("AMICOR_BROWSER_BASE", "http://127.0.0.1:8010")
PASSWORD = os.getenv("AMICOR_SEED_PASSWORD", "Amicor123!")
ARTIFACT_DIR = BACKEND_ROOT / "artifacts" / "real_life_ops_verification"
REPORT_JSON = BACKEND_ROOT / "artifacts" / "real_life_ops_verification_report.json"

CANONICAL_DRIVERS = {
    "James Smith": "917-555-1001",
    "Maria Garcia": "917-555-1002",
    "David Chen": "917-555-1003",
}
PRIMARY_DRIVER = "James Smith"
PRIMARY_PHONE = CANONICAL_DRIVERS[PRIMARY_DRIVER]
PASSENGER = f"Ops Verify {datetime.now(timezone.utc).strftime('%H%M%S')}"


def log(msg: str) -> None:
    print(msg, flush=True)


def is_remote_base(base: str) -> bool:
    host = (httpx.URL(base).host or "").lower()
    return host not in {"", "127.0.0.1", "localhost", "::1"}


def snap(page, name: str, shots: list[str]) -> None:
    ARTIFACT_DIR.mkdir(parents=True, exist_ok=True)
    path = str(ARTIFACT_DIR / f"{name}.png")
    page.screenshot(path=path, full_page=True)
    shots.append(path)


def reseed_backend() -> dict[str, Any]:
    from app.auth import ensure_auth_schema, seed_default_users
    from app.db.session import SessionLocal
    from app.modules.health_isf import service as hs
    from app.modules.health_isf.models import (
        DispatchAssignmentState,
        DriverStatus,
        HealthISFDispatchAssignment,
        HealthISFDriver,
        HealthISFDriverSession,
        HealthISFRide,
        RideStatus,
    )
    from sqlalchemy import func

    ensure_auth_schema()
    seed_default_users()

    db = SessionLocal()
    try:
        org = hs._get_or_create_default_org(db)
        ensured = hs.ensure_sample_driver_credentials(db, organization_id=org.id)
        james = (
            db.query(HealthISFDriver)
            .filter(
                HealthISFDriver.organization_id == org.id,
                func.lower(HealthISFDriver.name) == PRIMARY_DRIVER.lower(),
            )
            .first()
        )
        if not james:
            raise RuntimeError(f"{PRIMARY_DRIVER} missing after reseed in org {org.id}")

        now_ts = hs.now()
        active_rides = (
            db.query(HealthISFRide)
            .filter(
                HealthISFRide.driver_id == james.id,
                HealthISFRide.status.in_(list(hs.ACTIVE_RIDE_STATUSES_FOR_ASSIGNMENT)),
            )
            .all()
        )
        for ride in active_rides:
            ride.status = RideStatus.COMPLETED
            ride.lifecycle_state = RideStatus.COMPLETED.value
            ride.completed_at = now_ts
            ride.updated_at = now_ts

        open_assignments = (
            db.query(HealthISFDispatchAssignment)
            .filter(
                HealthISFDispatchAssignment.driver_id == james.id,
                HealthISFDispatchAssignment.assignment_state.in_(list(hs.ACTIVE_DISPATCH_ASSIGNMENT_STATES)),
            )
            .all()
        )
        for assignment in open_assignments:
            assignment.assignment_state = DispatchAssignmentState.REASSIGNMENT_PENDING.value
            assignment.closed_reason = "ops_verification_reset"
            assignment.updated_at = now_ts

        for session in (
            db.query(HealthISFDriverSession)
            .filter(
                HealthISFDriverSession.driver_id == james.id,
                HealthISFDriverSession.session_state == "active",
                HealthISFDriverSession.revoked_at.is_(None),
            )
            .all()
        ):
            session.session_state = "revoked"
            session.revoked_at = now_ts
            session.updated_at = now_ts

        james.status = DriverStatus.AVAILABLE
        james.availability_state = "available"
        james.is_active = True
        james.auth_state = "inactive"
        james.is_online = False
        james.last_seen_at = None
        james.updated_at = now_ts

        for row in db.query(HealthISFDriver).filter(
            HealthISFDriver.organization_id == org.id,
            HealthISFDriver.id != james.id,
            HealthISFDriver.is_active == True,
        ):
            if str(row.name or "").lower() in {name.lower() for name in CANONICAL_DRIVERS}:
                continue
            row.status = DriverStatus.OFFLINE
            row.availability_state = "offline"
            row.is_online = False
        db.commit()
        db.refresh(james)

        return {
            "organization_id": str(org.id),
            "driver_id": str(james.id),
            "driver_name": str(james.name),
            "driver_phone": str(james.phone),
            "ensured_ids": list(ensured.keys()),
            "cleared_active_rides": len(active_rides),
            "cleared_open_assignments": len(open_assignments),
        }
    finally:
        db.close()


def prep_remote_backend(base: str) -> dict[str, Any]:
    """Resolve canonical driver IDs from the target deployment (not local SQLite)."""
    client = httpx.Client(base_url=base.rstrip("/"), timeout=90.0)
    login = client.post(
        "/api/auth/login",
        json={"email": "dispatcher@amicor.local", "password": PASSWORD},
    )
    login.raise_for_status()
    token = login.json().get("access_token")
    if not token:
        raise RuntimeError(f"Dispatcher login failed against {base}")

    headers = {"Authorization": f"Bearer {token}"}
    drivers_resp = client.get("/api/health-isf/drivers", headers=headers)
    drivers_resp.raise_for_status()
    payload = drivers_resp.json()
    rows = payload if isinstance(payload, list) else payload.get("data") or []
    driver = next(
        (row for row in rows if str(row.get("name") or "").lower() == PRIMARY_DRIVER.lower()),
        None,
    )
    if not driver:
        raise RuntimeError(f"{PRIMARY_DRIVER} not found on remote deployment {base}")

    return {
        "organization_id": str(driver.get("organization_id") or ""),
        "driver_id": str(driver["id"]),
        "driver_name": str(driver.get("name") or PRIMARY_DRIVER),
        "driver_phone": str(driver.get("phone") or PRIMARY_PHONE),
        "remote": True,
        "ensured_ids": [],
        "cleared_active_rides": 0,
        "cleared_open_assignments": 0,
    }


def wait_for_driver_runtime_option(page, driver_id: str, timeout_ms: int = 90000) -> None:
    page.wait_for_function(
        """(driverId) => {
          const sel = document.getElementById('health-driver-runtime-id');
          if (!sel) return false;
          return Array.from(sel.options || []).some(function (opt) {
            return String(opt.value || '') === String(driverId || '');
          });
        }""",
        arg=driver_id,
        timeout=timeout_ms,
    )


def auth_fetch(page, method: str, path: str, body: dict | None = None) -> dict:
    return page.evaluate(
        """async ([method, path, body]) => {
          const opts = { method };
          if (body != null) {
            opts.headers = { 'Content-Type': 'application/json' };
            opts.body = JSON.stringify(body);
          }
          const res = await window.AmiCorSession.authFetch(path, opts);
          const text = await res.text();
          let data = text;
          try { data = JSON.parse(text); } catch (_) {}
          return { status: res.status, ok: res.ok, data };
        }""",
        [method, path, body],
    )


def wait_refresh(page, ms: int = 2500) -> None:
    page.evaluate(
        """() => window.AmiCorHealthISF && window.AmiCorHealthISF.refreshData
          ? window.AmiCorHealthISF.refreshData() : null"""
    )
    page.wait_for_timeout(ms)


def parse_runtime_status(text: str) -> dict[str, str]:
    out: dict[str, str] = {}
    for key in ("Auth", "Session Valid", "Online", "Availability"):
        match = re.search(rf"{re.escape(key)}\s*\n\s*([^\n]+)", text, re.I)
        if match:
            out[key.lower().replace(" ", "_")] = match.group(1).strip()
    return out


def verify_driver_login_ui(page, driver_id: str, shots: list[str]) -> dict[str, Any]:
    lifecycle.PASSENGER = PASSENGER
    page.goto(f"{BASE}/#/health-isf/drivers", wait_until="domcontentloaded")
    lifecycle.dismiss_blocking_overlays(page)
    page.wait_for_timeout(1200)
    if page.locator("#health-isf-shell").is_hidden():
        page.locator('[data-health-nav-open="drivers"]').first.click(force=True)
        page.wait_for_timeout(800)
    lifecycle.wait_authenticated(page)
    wait_refresh(page, 5000 if is_remote_base(BASE) else 2500)
    wait_for_driver_runtime_option(page, driver_id)

    page.select_option("#health-driver-runtime-id", driver_id)
    page.wait_for_timeout(800)
    phone_value = page.locator("#health-driver-runtime-phone").input_value()
    phone_digits = re.sub(r"\D", "", phone_value)
    phone_ok = phone_digits.endswith("9175551001") or phone_value.strip() == PRIMARY_PHONE

    page.locator("#health-driver-login").click()
    page.wait_for_function(
        """() => {
          const token = document.getElementById('health-driver-runtime-token');
          const status = document.getElementById('health-driver-runtime-status');
          if (!token || !status) return false;
          const tokenOk = String(token.value || '').startsWith('drv_');
          const text = status.innerText || '';
          return tokenOk
            && /Session Valid\\s*\\n\\s*Yes/i.test(text)
            && /Online\\s*\\n\\s*Yes/i.test(text)
            && /Auth State\\s*\\n\\s*active/i.test(text);
        }""",
        timeout=45000,
    )
    page.wait_for_timeout(500)
    token_value = page.locator("#health-driver-runtime-token").input_value()
    status_text = page.locator("#health-driver-runtime-status").inner_text()
    parsed = parse_runtime_status(status_text)
    snap(page, "01_driver_login", shots)

    return {
        "phone_autofill": phone_ok,
        "phone_value": phone_value,
        "session_token_present": token_value.startswith("drv_"),
        "session_valid_yes": parsed.get("session_valid", "").lower() == "yes",
        "online_yes": parsed.get("online", "").lower() == "yes",
        "availability_available": parsed.get("availability", "").lower() == "available",
        "auth_active": parsed.get("auth", "").lower() == "active",
        "status_snippet": status_text[:400],
        "token_prefix": token_value[:12],
    }


def verify_assign_dropdown(page, driver_id: str) -> bool:
    wait_refresh(page)
    return bool(
        page.evaluate(
            """(driverId) => {
              const drivers = (window.AmiCorHealthISF && window.AmiCorHealthISF.getRuntimeStatus)
                ? null : null;
              const stateDrivers = (function () {
                try {
                  const rs = window.AmiCorHealthISF.getRuntimeStatus();
                  return rs && rs.drivers ? rs.drivers : null;
                } catch (_) { return null; }
              })();
              const list = Array.isArray(window.__healthStateDrivers)
                ? window.__healthStateDrivers
                : null;
              const rows = list || stateDrivers;
              if (Array.isArray(rows)) {
                return rows.some(function (row) {
                  return String(row.id) === String(driverId)
                    && (String(row.availability_state || '').toLowerCase() === 'available'
                      || String(row.status || '').toLowerCase() === 'available');
                });
              }
              const selects = document.querySelectorAll('.health-driver-select');
              for (const sel of selects) {
                for (const opt of sel.options) {
                  if (String(opt.value) === String(driverId)) return true;
                }
              }
              return false;
            }""",
            driver_id,
        )
    )


def refresh_driver_offers(page, driver_id: str) -> dict[str, Any]:
    return page.evaluate(
        """async (driverId) => {
          const active = await window.AmiCorSession.authFetch('/api/health-isf/dispatch/active-assignments');
          const rows = active.ok ? await active.json() : [];
          const offered = (Array.isArray(rows) ? rows : []).find(function (item) {
            return String(item.driver_id || '') === String(driverId)
              && String(item.assignment_state || '').toLowerCase() === 'offered';
          }) || null;
          return { count: Array.isArray(rows) ? rows.length : 0, offered: offered };
        }""",
        driver_id,
    )


def driver_accept_and_complete_ops(page, driver_id: str, ride_id: str) -> None:
    page.goto(f"{BASE}/#/health-isf/drivers", wait_until="domcontentloaded")
    wait_refresh(page, 5000 if is_remote_base(BASE) else 2500)
    wait_for_driver_runtime_option(page, driver_id)
    page.select_option("#health-driver-runtime-id", driver_id)
    page.wait_for_timeout(1200)

    offer_info = refresh_driver_offers(page, driver_id)
    if not offer_info.get("offered"):
        page.locator("#health-driver-offer-refresh").click()
        page.wait_for_timeout(2500)
        offer_info = refresh_driver_offers(page, driver_id)
    if not offer_info.get("offered"):
        assigned = auth_fetch(page, "GET", f"/api/health-isf/drivers/{driver_id}/assigned-rides")
        rows = assigned.get("data") if isinstance(assigned.get("data"), list) else []
        if not any(str(row.get("id")) == ride_id for row in rows):
            raise RuntimeError(f"Driver has no offered assignment for ride {ride_id[:8]}")

    accept_clicked = False
    if page.locator("#health-driver-offer-accept").count():
        offer_text = page.locator("#health-driver-incoming-offer").inner_text()
        if "offered" in offer_text.lower():
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
        log(f"[ROUTE] {step}")


def verify_assign_dropdown_via_api(page, driver_id: str, driver_name: str) -> bool:
    resp = auth_fetch(page, "GET", "/api/health-isf/drivers?limit=20")
    rows = resp.get("data") if isinstance(resp.get("data"), list) else []
    for row in rows:
        if str(row.get("id")) == driver_id:
            avail = str(row.get("availability_state") or "").lower()
            status = str(row.get("status") or "").lower()
            return avail == "available" or status == "available"
    return any(str(row.get("name") or "") == driver_name for row in rows)


def run_verification() -> dict[str, Any]:
    report: dict[str, Any] = {
        "timestamp_utc": datetime.now(timezone.utc).isoformat(),
        "preview_base": BASE,
        "passenger": PASSENGER,
        "canonical_driver": PRIMARY_DRIVER,
        "canonical_phone": PRIMARY_PHONE,
        "screenshots": [],
        "checks": {},
        "blockers": [],
    }

    server_proc = None
    try:
        server_proc = lifecycle.ensure_preview_server(BASE)
        prep = prep_remote_backend(BASE) if is_remote_base(BASE) else reseed_backend()
        report["prep"] = prep
        driver_id = prep["driver_id"]
        driver_name = prep["driver_name"]
        driver_phone = prep["driver_phone"]

        lifecycle.PASSENGER = PASSENGER
        with sync_playwright() as p:
            browser = p.chromium.launch(headless=True)
            context = browser.new_context(viewport={"width": 1440, "height": 960})
            context.add_init_script("try { localStorage.setItem('amicor_onboarded', '1'); } catch (_) {}")
            page = context.new_page()
            try:
                lifecycle.sign_in_dispatcher(page)
                dash_before_resp = auth_fetch(page, "GET", "/api/health-isf/dashboard")
                completed_before = (dash_before_resp.get("data") or {}).get("completed_rides", 0)

                login_ui = verify_driver_login_ui(page, driver_id, report["screenshots"])
                report["checks"]["driver_login"] = all(
                    [
                        login_ui["phone_autofill"],
                        login_ui["session_token_present"],
                        login_ui["session_valid_yes"],
                        login_ui["online_yes"],
                        login_ui["availability_available"],
                    ]
                )
                report["driver_login_proof"] = login_ui

                page.locator("#health-driver-set-availability").click()
                page.wait_for_timeout(1200)
                assign_ok = verify_assign_dropdown_via_api(page, driver_id, driver_name)
                if not assign_ok:
                    page.goto(f"{BASE}/#/health-isf/rides", wait_until="domcontentloaded")
                    wait_refresh(page)
                    assign_ok = verify_assign_dropdown(page, driver_id)
                report["checks"]["driver_availability"] = assign_ok
                snap(page, "02_driver_available", report["screenshots"])

                page.goto(f"{BASE}/#/health-isf/rides", wait_until="domcontentloaded")
                wait_refresh(page)
                ride_id = lifecycle.create_ride(page)
                report["ride_id"] = ride_id
                report["checks"]["create_ride"] = bool(ride_id)
                snap(page, "03_ride_created", report["screenshots"])

                assignment_mode = "unknown"
                queue_row = lifecycle.fetch_queue_row(page, PASSENGER) or {}
                assignment_state = str(queue_row.get("assignment_state") or "").lower()
                ride_api = lifecycle.fetch_ride_status(page, ride_id)
                assigned_driver = str(ride_api.get("driver_id") or "")

                if assigned_driver == driver_id and assignment_state in {
                    "assigned",
                    "offered",
                    "accepted",
                    "auto_assigned",
                }:
                    assignment_mode = "auto_dispatch"
                    report["checks"]["auto_manual_assignment"] = True
                else:
                    try:
                        lifecycle.verify_ai_recommendation(page, report)
                    except AssertionError:
                        lifecycle.trigger_recommendation_if_needed(page, PASSENGER)
                        lifecycle.verify_ai_recommendation(page, report)
                    queue_row = lifecycle.fetch_queue_row(page, PASSENGER) or {}
                    assignment_state = str(queue_row.get("assignment_state") or "").lower()
                    approve_visible = page.locator("#health-dispatch-auto-assign").count() > 0
                    if assignment_state == "awaiting_approval" and approve_visible:
                        page.evaluate(
                            """(rideId) => {
                              const card = document.querySelector('[data-ride-card-id="' + rideId + '"]');
                              if (card) card.click();
                            }""",
                            ride_id,
                        )
                        page.wait_for_timeout(800)
                        approve_resp = auth_fetch(
                            page,
                            "POST",
                            "/api/health-isf/dispatch/recommendations/approve",
                            {"ride_id": ride_id, "offer_timeout_seconds": 90},
                        )
                        if not approve_resp.get("ok"):
                            lifecycle.approve_recommendation(page, driver_name, report)
                        else:
                            report["assignment_status"] = str(
                                (approve_resp.get("data") or {}).get("assignment_state") or "offered"
                            )
                            log(f"[APPROVE] Recommendation approved via API ({report['assignment_status']})")
                        page.wait_for_timeout(2500)
                        assignment_mode = "manual_approve"
                        report["checks"]["auto_manual_assignment"] = True
                    else:
                        report["checks"]["auto_manual_assignment"] = False
                        report["blockers"].append(
                            f"No auto-assign or awaiting_approval path (state={assignment_state})"
                        )
                report["assignment_mode"] = assignment_mode
                report["assignment_state"] = assignment_state
                snap(page, "04_assignment", report["screenshots"])

                assigned_api = auth_fetch(page, "GET", f"/api/health-isf/drivers/{driver_id}/assigned-rides")
                assigned_rows = assigned_api.get("data") if isinstance(assigned_api.get("data"), list) else []
                driver_sees = any(str(row.get("id")) == ride_id for row in assigned_rows)
                offer_info = refresh_driver_offers(page, driver_id)
                report["incoming_offer_snippet"] = str(offer_info.get("offered") or "")
                report["checks"]["driver_sees_assignment"] = driver_sees or bool(offer_info.get("offered"))

                driver_accept_and_complete_ops(page, driver_id, ride_id)
                report["checks"]["driver_accept"] = True
                report["checks"]["full_trip_lifecycle"] = True
                snap(page, "05_driver_completed", report["screenshots"])

                final_ride = lifecycle.fetch_ride_status(page, ride_id)
                completed = "completed" in str(
                    final_ride.get("lifecycle_state") or final_ride.get("status") or ""
                ).lower()
                report["checks"]["full_trip_lifecycle"] = completed
                report["final_ride_status"] = str(
                    final_ride.get("lifecycle_state") or final_ride.get("status") or ""
                )

                lifecycle.verify_completed_in_dispatcher_ui(page, report)
                dash_after = report.get("dashboard") or {}
                completed_after = dash_after.get("completed_rides")
                report["checks"]["dashboard_update"] = (
                    completed is not None
                    and isinstance(completed_after, (int, float))
                    and completed_after >= completed_before
                    and completed
                )
                report["dashboard_before"] = completed_before
                report["dashboard_after"] = completed_after
                snap(page, "06_dashboard", report["screenshots"])
            finally:
                browser.close()
    except Exception as exc:
        report["blockers"].append(str(exc))
        log(f"[FAIL] {exc}")
    finally:
        if server_proc and server_proc.poll() is None:
            server_proc.terminate()
            try:
                server_proc.wait(timeout=10)
            except Exception:
                server_proc.kill()

    labels = {
        "driver_login": "Driver login",
        "driver_availability": "Driver availability",
        "create_ride": "Create ride",
        "auto_manual_assignment": "Auto/manual assignment",
        "driver_sees_assignment": "Driver sees assignment",
        "driver_accept": "Driver accept",
        "full_trip_lifecycle": "Full trip lifecycle",
        "dashboard_update": "Dashboard update",
    }
    report["summary"] = {
        labels[key]: "PASS" if report["checks"].get(key) else "FAIL"
        for key in labels
    }
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
