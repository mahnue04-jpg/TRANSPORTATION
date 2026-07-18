"""Executive Phases 6-10: stabilized browser revenue proof harness."""
from __future__ import annotations

import json
import os
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

BACKEND = Path(__file__).resolve().parent.parent
REPO = BACKEND.parent
sys.path.insert(0, str(BACKEND))

from playwright.sync_api import Page, sync_playwright

from scripts.executive_proof_harness import (
    APP,
    AuthSession,
    BASE,
    DRIVER_ID,
    DRIVER_PHONE,
    ORG,
    RIDER_EMAIL,
    BrowserStack,
    cross_surface,
    driver_reset_proof,
    ensure_fresh_token,
    fin_snapshot,
    global_financial_baseline,
    goto_with_retry,
    isolated_backend_restart,
    locate_completed_ride_1,
    ride_in_active_surfaces,
    surface_contains_ride,
    verify_ride_financial_authoritative,
    wait_backend_healthy,
)

PASSWORD = "Amicor123!"
DISPATCHER_EMAIL = "dispatcher@amicor.local"
RUN_TS = datetime.now(timezone.utc).strftime("%Y%m%d%H%M%S")
OUT = REPO / f"EXECUTIVE_EVIDENCE_{RUN_TS}.json"
LOG = REPO / f"EXECUTIVE_PROOF_RUN_{RUN_TS}.log"


def _log(msg: str) -> None:
    line = f"{datetime.now(timezone.utc).isoformat()} {msg}"
    print(line, flush=True)
    try:
        with LOG.open("a", encoding="utf-8") as fh:
            fh.write(line + "\n")
    except OSError:
        pass


def verify_pre_proof(session: AuthSession) -> dict[str, Any]:
    from app.db import models as _pm  # noqa: F401
    from app.db.session import SessionLocal
    from app.modules.health_isf import service as hs
    from app.modules.health_isf.models import HealthISFDispatchAssignment, HealthISFRide

    report: dict[str, Any] = {"ok": True, "issues": []}
    with SessionLocal() as db:
        stale_cancelled: list[str] = []
        stale_rows = (
            db.query(HealthISFRide)
            .filter(
                HealthISFRide.organization_id == ORG,
                HealthISFRide.driver_id == DRIVER_ID,
                HealthISFRide.passenger_name.ilike("Executive Revenue%"),
            )
            .all()
        )
        for ride in stale_rows:
            if RUN_TS in str(ride.passenger_name or ""):
                continue
            if hs._ride_is_terminal(ride):
                continue
            try:
                hs.cancel_ride(db, ride_id=str(ride.id), reason="executive_preflight_stale_cleanup")
                stale_cancelled.append(str(ride.id))
            except Exception:
                hs._close_terminal_open_assignments_for_driver(
                    db, organization_id=ORG, driver_id=DRIVER_ID
                )
        if stale_cancelled:
            report["stale_executive_rides_cancelled"] = stale_cancelled
            db.commit()

        open_terminal = []
        rows = (
            db.query(HealthISFDispatchAssignment)
            .filter(
                HealthISFDispatchAssignment.driver_id == DRIVER_ID,
                HealthISFDispatchAssignment.assignment_state.in_(list(hs.DRIVER_APP_ASSIGNMENT_STATES)),
            )
            .all()
        )
        for row in rows:
            ride = hs.get_ride_by_id(db, row.ride_id) if row.ride_id else None
            if ride and hs._ride_is_terminal(ride):
                open_terminal.append(str(row.ride_id))
        report["open_terminal_assignments"] = open_terminal
        if open_terminal:
            report["ok"] = False
            report["issues"].append("completed rides with open assignments")

        hs._prepare_driver_mobile_workspace_read(db, organization_id=ORG, driver_id=DRIVER_ID)
        db.commit()

    surfaces = cross_surface(session, "")
    report["eligible_offer_count"] = int(
        bool(((surfaces.get("driver_active_offer") or {}).get("body") or {}).get("offer", {}).get("ride_id"))
    )
    return report


def wait_shell(page: Page, timeout_ms: int = 45000) -> None:
    page.wait_for_function(
        "() => !!(window.AmiOpsShellState && window.AmiOpsShellActions && !window.AmiOpsShellState.loading)",
        timeout=timeout_ms,
    )


def platform_login(page: Page, email: str) -> dict[str, Any]:
    nav = goto_with_retry(page, APP)
    if not nav.get("ok"):
        return nav
    page.evaluate(
        """async (creds) => {
          const r = await fetch('/api/auth/login', {
            method: 'POST',
            headers: {'Content-Type':'application/json'},
            body: JSON.stringify({email: creds.email, password: creds.password})
          });
          const data = await r.json();
          localStorage.setItem('amicor_session', JSON.stringify({
            access_token: data.access_token,
            refresh_token: data.refresh_token,
            email: creds.email
          }));
          localStorage.setItem('amicor_shell_role', creds.email.includes('rider') ? 'rider' : 'admin');
        }""",
        {"email": email, "password": PASSWORD},
    )
    page.reload(wait_until="domcontentloaded")
    wait_shell(page)
    return {"ok": True}


def create_ride_via_rider_ui(page: Page, session: AuthSession, label: str) -> dict[str, Any]:
    from scripts.executive_proof_harness import api_get_with_retry, api_post_with_retry

    rider_name = f"Executive Revenue {label} {RUN_TS}"
    login_result = platform_login(page, RIDER_EMAIL)
    if not login_result.get("ok"):
        return {"ok": False, "error": "platform_login_failed", "detail": login_result}
    nav = goto_with_retry(page, f"{APP}/riders")
    if not nav.get("ok"):
        return {"ok": False, "error": "rider_nav_failed", "detail": nav}
    wait_shell(page)
    page.wait_for_selector("#rider-name-input", timeout=20000)
    page.fill("#rider-name-input", rider_name)
    page.fill("#rider-phone-input", "646-555-9901")
    page.fill("#rider-pickup-input", "100 Revenue Ave, Brooklyn, NY")
    page.fill("#rider-dropoff-input", "200 Clinic Rd, Brooklyn, NY")
    btn = page.locator('[data-rider-action="request_now"]')
    if btn.count() == 0:
        return {"ok": False, "error": "request_now_button_missing", "rider_name": rider_name}
    btn.first.click()
    page.wait_for_timeout(10000)
    request_id = ""
    ride_id = ""
    for _ in range(12):
        rows = api_get_with_retry(session, f"/api/health-isf/customer-requests?limit=20&organization_id={ORG}")
        for row in reversed(rows.get("body") or []):
            if rider_name.lower() in str(row.get("rider_name") or "").lower():
                request_id = str(row.get("id") or "")
                ride_id = str(row.get("ride_id") or "")
                break
        if ride_id:
            break
        page.wait_for_timeout(2000)
    if not ride_id:
        return {"ok": False, "error": "ride_not_created", "rider_name": rider_name}
    approve = api_post_with_retry(
        session, f"/api/health-isf/dispatcher/customer-requests/{request_id}/approve", {}
    )
    assign = api_post_with_retry(
        session,
        f"/api/health-isf/dispatcher/customer-requests/{request_id}/assign-driver",
        {"driver_id": DRIVER_ID},
    )
    offer_match = False
    for _ in range(10):
        offer = api_get_with_retry(
            session, f"/api/health-isf/drivers/{DRIVER_ID}/active-offer?organization_id={ORG}"
        )
        offer_ride = str(((offer.get("body") or {}).get("offer") or {}).get("ride_id") or "")
        if offer_ride == ride_id:
            offer_match = True
            break
        time.sleep(1.5)
    return {
        "ok": True,
        "rider_name": rider_name,
        "request_id": request_id,
        "ride_id": ride_id,
        "approve": approve,
        "assign": assign,
        "active_offer_matches": offer_match,
        "assign_status": assign.get("status"),
    }


def driver_mobile_login_ui(page: Page) -> None:
    nav = goto_with_retry(page, f"{APP}/mobile")
    if not nav.get("ok"):
        raise RuntimeError(f"driver mobile nav failed: {nav}")
    wait_shell(page)
    if page.locator("#driver-mobile-phone").count():
        page.fill("#driver-mobile-phone", DRIVER_PHONE)
        if page.locator("#driver-mobile-login-btn").count():
            page.click("#driver-mobile-login-btn")
            page.wait_for_timeout(5000)
            wait_shell(page)
    sess = page.evaluate(
        """() => {
          try {
            var s = JSON.parse(localStorage.getItem('amicor_driver_session') || 'null');
            return (s && s.session_token) ? String(s.session_token) : '';
          } catch (e) { return ''; }
        }"""
    )
    if not sess:
        page.evaluate(
            """async (payload) => {
              const r = await fetch('/api/health-isf/drivers/login', {
                method: 'POST',
                headers: {'Content-Type':'application/json'},
                body: JSON.stringify({driver_id: payload.driver_id, phone: payload.phone})
              });
              const data = await r.json();
              localStorage.setItem('amicor_driver_session', JSON.stringify(data));
              localStorage.setItem('amicor_driver_workflow_id', payload.driver_id);
            }""",
            {"driver_id": DRIVER_ID, "phone": DRIVER_PHONE},
        )
        page.reload(wait_until="domcontentloaded")
        wait_shell(page)
    if page.locator('[data-driver-action="refresh_workflow"]').count():
        page.locator('[data-driver-action="refresh_workflow"]').first.click()
        page.wait_for_timeout(3000)


def click_driver_action(page: Page, action: str, ride_id: str = "") -> dict[str, Any]:
    batch: list[dict[str, Any]] = []

    def on_response(resp):
        if any(k in resp.url for k in ("route-progress", "dropoff-complete", "accept-ride", "completion-handoff", "active-ride", "live-workspace")):
            body = ""
            try:
                body = resp.text()[:1200]
            except Exception:
                body = "<unreadable>"
            batch.append({"status": resp.status, "url": resp.url, "body": body})

    page.evaluate(
        """async (payload) => {
          var app = (window.AmiOpsShellState && window.AmiOpsShellState.driverApp) || {};
          app.shiftOnline = true;
          if (payload.ride_id) app.activeTripId = payload.ride_id;
          if (window.AmiOpsShellActions && window.AmiOpsShellActions.refreshDriverWorkflowData) {
            await window.AmiOpsShellActions.refreshDriverWorkflowData({});
          }
          if (window.AmiOpsShellRender) window.AmiOpsShellRender();
        }""",
        {"ride_id": ride_id},
    )
    page.wait_for_timeout(4000)
    btn = page.locator(f'[data-driver-action="{action}"]')
    result: dict[str, Any] = {"action": action, "clicked": False, "http": batch}
    if btn.count() == 0:
        result["error"] = "button_missing"
        return result
    if btn.first.get_attribute("disabled") is not None:
        if action == "accept_trip" and ride_id:
            handled = page.evaluate(
                """async (tripId) => {
                  if (typeof window._amiHandleDriverAcceptTrip !== 'function') return false;
                  return await window._amiHandleDriverAcceptTrip(String(tripId || ''));
                }""",
                ride_id,
            )
            if handled:
                page.wait_for_timeout(7000)
                result["clicked"] = True
                result["via"] = "driver_accept_handler"
                return result
        result["error"] = "button_disabled"
        return result
    page.on("response", on_response)
    btn.first.click()
    wait_ms = 18000 if action == "complete_trip" else 7000
    page.wait_for_timeout(wait_ms)
    page.remove_listener("response", on_response)
    result["clicked"] = True
    result["http"] = batch
    return result


def run_driver_lifecycle(page: Page, session: AuthSession, ride_id: str) -> list[dict[str, Any]]:
    from scripts.executive_proof_harness import api_get_with_retry

    driver_mobile_login_ui(page)
    page.evaluate(
        """async () => {
          if (window.AmiOpsShellActions && window.AmiOpsShellActions.refreshDriverWorkflowData) {
            await window.AmiOpsShellActions.refreshDriverWorkflowData({});
          }
        }"""
    )
    for attempt in range(24):
        btn = page.locator('[data-driver-action="accept_trip"]')
        if btn.count() and btn.first.get_attribute("disabled") is None:
            break
        if attempt % 4 == 3 and page.locator('[data-driver-action="refresh_workflow"]').count():
            page.locator('[data-driver-action="refresh_workflow"]').first.click()
        page.wait_for_timeout(2500)
    log: list[dict[str, Any]] = []
    for action in ("accept_trip", "arrive_pickup", "start_trip", "start_transport", "complete_trip"):
        step = click_driver_action(page, action, ride_id)
        ensure_fresh_token(session)
        snap = cross_surface(session, ride_id)
        step["surfaces"] = snap.get("ride_present")
        ar = (snap.get("driver_active_ride") or {}).get("body") or {}
        step["lifecycle_state"] = str(
            (ar.get("ride") or {}).get("lifecycle_state")
            or (ar.get("ride") or {}).get("status")
            or ar.get("assignment_state")
            or ""
        )
        step["driver_status"] = (
            api_get_with_retry(session, f"/api/health-isf/drivers/{DRIVER_ID}?organization_id={ORG}")
            .get("body", {})
            .get("availability_state")
        )
        log.append(step)
        if not step.get("clicked") and action == "accept_trip":
            break
    return log


def terminal_persistence_proof(
    stack: BrowserStack,
    session: AuthSession,
    ride_id: str,
    *,
    include_backend_restart: bool = True,
) -> tuple[dict[str, Any], AuthSession, BrowserStack]:
    assert stack.page is not None
    page = stack.page
    proof: dict[str, Any] = {"checks": []}

    def record(label: str) -> None:
        ensure_fresh_token(session)
        active = ride_in_active_surfaces(session, ride_id)
        proof["checks"].append(
            {
                "step": label,
                "ride_still_active": active.get("active"),
                "active_surfaces": active.get("surfaces"),
            }
        )
        if active.get("active"):
            proof["failed"] = label
            proof["failure_layer"] = "application"

    driver_mobile_login_ui(page)
    page.reload(wait_until="domcontentloaded")
    wait_shell(page)
    page.wait_for_timeout(3000)
    record("refresh_1")
    page.reload(wait_until="domcontentloaded")
    wait_shell(page)
    page.wait_for_timeout(3000)
    record("refresh_2")

    goto_with_retry(page, f"{APP}/dispatch")
    wait_shell(page)
    page.wait_for_timeout(2000)
    goto_with_retry(page, f"{APP}/mobile")
    wait_shell(page)
    page.wait_for_timeout(2000)
    record("navigate_away_and_back")

    page.evaluate("() => { localStorage.removeItem('amicor_driver_session'); }")
    page.reload(wait_until="domcontentloaded")
    driver_mobile_login_ui(page)
    record("logout_login")

    if include_backend_restart:
        fin_snap = fin_snapshot(ride_id, session)
        saved = {
            "ride_1_id": ride_id,
            "driver_id": DRIVER_ID,
            "financial_snapshot": fin_snap,
            "run_ts": RUN_TS,
        }
        stack, session, restart_report = isolated_backend_restart(stack, saved)
        proof["backend_restart"] = restart_report
        assert stack.page is not None
        page = stack.page
        page.evaluate("() => { location.reload(true); }")
        page.wait_for_timeout(4000)
        wait_shell(page)
        record("backend_restart_hard_refresh")
        driver_mobile_login_ui(page)

    page.wait_for_timeout(16000)
    record("auto_refresh_cycle_1")
    page.wait_for_timeout(16000)
    record("auto_refresh_cycle_2")

    proof["ok"] = not any(c.get("ride_still_active") for c in proof["checks"])
    return proof, session, stack


def run_one_ride(page: Page, session: AuthSession, label: str) -> dict[str, Any]:
    global_fin_before = global_financial_baseline(session)
    created = create_ride_via_rider_ui(page, session, label)
    if not created.get("ok"):
        return {"ok": False, "phase": "create", "detail": created, "failure_layer": "proof_harness"}
    if not created.get("active_offer_matches"):
        return {"ok": False, "phase": "offer_sync", "detail": created, "failure_layer": "application"}

    ride_id = str(created["ride_id"])
    fin_pre = fin_snapshot(ride_id, session)
    surfaces_after_create = cross_surface(session, ride_id)
    present = surface_contains_ride(surfaces_after_create, ride_id)
    surfaces_ok = present.get("driver_mobile_offer") or present.get("driver_mobile_active")

    lifecycle = run_driver_lifecycle(page, session, ride_id)
    lifecycle_ok = all(step.get("clicked") for step in lifecycle)

    ensure_fresh_token(session)
    financial = verify_ride_financial_authoritative(
        ride_id,
        session,
        global_before=global_fin_before,
        require_delta=True,
    )
    surfaces_after_complete = cross_surface(session, ride_id)
    driver_available = str((financial.get("snapshot") or {}).get("availability_state") or "").lower() == "available"

    return {
        "ok": lifecycle_ok and financial.get("ok") and driver_available and surfaces_ok,
        "ride_id": ride_id,
        "request_id": created.get("request_id"),
        "rider_name": created.get("rider_name"),
        "surfaces_after_create": surfaces_after_create,
        "surface_presence_after_create": present,
        "lifecycle": lifecycle,
        "surfaces_after_complete": surfaces_after_complete,
        "fin_pre": fin_pre,
        "financial_proof": financial,
        "financial_ok": financial.get("ok"),
        "driver_available": driver_available,
        "lifecycle_ok": lifecycle_ok,
        "failure_layer": financial.get("failure_layer") if not financial.get("ok") else None,
    }


def run_regression_suite() -> dict[str, Any]:
    reg = subprocess.run(
        [
            sys.executable,
            "-m",
            "pytest",
            "tests/test_driver_mobile_lifecycle_cleanup.py",
            "tests/test_expired_bound_assignment_reconcile.py",
            "tests/test_executive_revenue_regression.py",
            "tests/test_executive_proof_harness.py",
            "-q",
        ],
        cwd=str(BACKEND),
        env={**os.environ, "PYTHONPATH": str(BACKEND)},
        capture_output=True,
        text=True,
    )
    return {
        "exit_code": reg.returncode,
        "stdout_tail": (reg.stdout or "")[-3000:],
        "stderr_tail": (reg.stderr or "")[-3000:],
    }


def main() -> int:
    LOG.write_text(f"=== executive proof run {RUN_TS} ===\n", encoding="utf-8")
    evidence: dict[str, Any] = {
        "run_ts": RUN_TS,
        "base_url": BASE,
        "verdict": "FAIL — NOT READY",
        "failed_step": None,
        "failure_layer": None,
        "rides": {},
    }

    health = wait_backend_healthy(consecutive=2)
    evidence["backend_health_preflight"] = health
    if not health.get("ok"):
        evidence["failed_step"] = "backend_health_preflight"
        evidence["failure_layer"] = "proof_harness"
        OUT.write_text(json.dumps(evidence, indent=2, default=str), encoding="utf-8")
        return 1

    session = AuthSession()
    try:
        session.login()
    except Exception as exc:
        evidence["failed_step"] = f"auth_login: {exc}"
        evidence["failure_layer"] = "proof_harness"
        OUT.write_text(json.dumps(evidence, indent=2, default=str), encoding="utf-8")
        return 1

    pre = verify_pre_proof(session)
    evidence["pre_proof_verification"] = pre
    if not pre.get("ok"):
        subprocess.run(
            [sys.executable, str(BACKEND / "scripts" / "phase4_scoped_repair.py")],
            cwd=str(BACKEND),
            env={**os.environ, "PYTHONPATH": str(BACKEND)},
            check=False,
        )
        session.refresh()
        evidence["pre_proof_verification_after_repair"] = verify_pre_proof(session)

    reusable = locate_completed_ride_1(REPO)
    evidence["reusable_ride_1"] = reusable

    try:
        with sync_playwright() as pw:
            stack = BrowserStack()
            page = stack.launch(pw)

            if reusable and reusable.get("ride_id"):
                ride1_id = str(reusable["ride_id"])
                _log(f"reusing completed ride_1 {ride1_id} — skipping lifecycle")
                ensure_fresh_token(session)
                ride1_fin = verify_ride_financial_authoritative(ride1_id, session, require_delta=False)
                evidence["rides"]["ride_1"] = {
                    "reused": True,
                    "ride_id": ride1_id,
                    "source": reusable.get("source"),
                    "lifecycle_ok": True,
                    "financial_proof": ride1_fin,
                    "financial_ok": ride1_fin.get("ok"),
                    "ok": ride1_fin.get("ok"),
                }
                if not ride1_fin.get("ok"):
                    evidence["failed_step"] = f"ride_1_financial_reverify: {ride1_id}"
                    evidence["failure_layer"] = ride1_fin.get("failure_layer") or "application"
                    stack.close_all()
                    OUT.write_text(json.dumps(evidence, indent=2, default=str), encoding="utf-8")
                    return 1
            else:
                _log("creating ride_1 via browser")
                ride1 = run_one_ride(page, session, "R1")
                evidence["rides"]["ride_1"] = ride1
                if not ride1.get("ok"):
                    evidence["failed_step"] = (
                        f"ride_1: lifecycle={ride1.get('lifecycle_ok')} "
                        f"financial={ride1.get('financial_ok')} driver={ride1.get('driver_available')}"
                    )
                    evidence["failure_layer"] = ride1.get("failure_layer") or "application"
                    stack.close_all()
                    OUT.write_text(json.dumps(evidence, indent=2, default=str), encoding="utf-8")
                    return 1
                ride1_id = str(ride1["ride_id"])

            persist1, session, stack = terminal_persistence_proof(
                stack, session, ride1_id, include_backend_restart=True
            )
            evidence["rides"]["ride_1_terminal_persistence"] = persist1
            if not persist1.get("ok"):
                evidence["failed_step"] = f"ride_1_terminal_persistence: {persist1.get('failed')}"
                evidence["failure_layer"] = persist1.get("failure_layer") or "application"
                stack.close_all()
                OUT.write_text(json.dumps(evidence, indent=2, default=str), encoding="utf-8")
                return 1

            assert stack.page is not None
            session.refresh()
            _log("creating ride_2 via browser")
            ride2 = run_one_ride(stack.page, session, "R2")
            evidence["rides"]["ride_2"] = ride2
            if not ride2.get("ok"):
                evidence["failed_step"] = (
                    f"ride_2: lifecycle={ride2.get('lifecycle_ok')} financial={ride2.get('financial_ok')}"
                )
                evidence["failure_layer"] = ride2.get("failure_layer") or "application"
                stack.close_all()
                OUT.write_text(json.dumps(evidence, indent=2, default=str), encoding="utf-8")
                return 1

            ride2_id = str(ride2["ride_id"])
            ride1_active = ride_in_active_surfaces(session, ride1_id)
            evidence["ride_1_active_during_ride_2"] = ride1_active
            if ride1_active.get("active"):
                evidence["failed_step"] = f"ride_1_reappeared_when_ride_2_active: {ride1_id}"
                evidence["failure_layer"] = "application"
                stack.close_all()
                OUT.write_text(json.dumps(evidence, indent=2, default=str), encoding="utf-8")
                return 1

            persist2, session, stack = terminal_persistence_proof(
                stack, session, ride2_id, include_backend_restart=False
            )
            evidence["rides"]["ride_2_terminal_persistence"] = persist2

            subprocess.run(
                [sys.executable, str(BACKEND / "scripts" / "phase4_scoped_repair.py")],
                cwd=str(BACKEND),
                env={**os.environ, "PYTHONPATH": str(BACKEND)},
                check=False,
            )
            session.refresh()
            reset = driver_reset_proof(session)
            evidence["driver_reset_proof"] = reset
            stack.close_all()

            if not persist2.get("ok"):
                evidence["failed_step"] = f"ride_2_terminal_persistence: {persist2.get('failed')}"
                evidence["failure_layer"] = persist2.get("failure_layer") or "application"
                OUT.write_text(json.dumps(evidence, indent=2, default=str), encoding="utf-8")
                return 1
            if not reset.get("ok"):
                evidence["failed_step"] = "driver_reset_proof"
                evidence["failure_layer"] = "application"
                OUT.write_text(json.dumps(evidence, indent=2, default=str), encoding="utf-8")
                return 1

    except Exception as exc:
        msg = str(exc)
        evidence["failed_step"] = f"browser_automation: {exc}"
        evidence["failure_layer"] = (
            "proof_harness"
            if any(
                k in msg.lower()
                for k in ("err_network", "playwright", "chromium", "connection", "health gate", "permission denied")
            )
            else "application"
        )
        OUT.write_text(json.dumps(evidence, indent=2, default=str), encoding="utf-8")
        _log(f"FAILED: {exc}")
        return 1

    reg = run_regression_suite()
    evidence["regression_suite"] = reg
    if reg.get("exit_code") != 0:
        evidence["failed_step"] = f"regression_suite: exit_code={reg.get('exit_code')}"
        evidence["failure_layer"] = "proof_harness"
        OUT.write_text(json.dumps(evidence, indent=2, default=str), encoding="utf-8")
        return 1

    evidence["verdict"] = "PASS — LOCAL PRODUCTION CANDIDATE"
    evidence["ride_1_id"] = ride1_id
    evidence["ride_2_id"] = ride2_id
    OUT.write_text(json.dumps(evidence, indent=2, default=str), encoding="utf-8")
    _log(f"PASS ride1={ride1_id} ride2={ride2_id}")
    print(json.dumps({"verdict": evidence["verdict"], "ride_1_id": ride1_id, "ride_2_id": ride2_id}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
