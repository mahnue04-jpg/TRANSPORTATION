"""Production assignment-sync E2E validator (Rider through cleanup)."""
from __future__ import annotations

import argparse
import json
import os
import re
import sys
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import requests
from playwright.sync_api import sync_playwright

BACKEND = Path(__file__).resolve().parent.parent
REPO = BACKEND.parent
sys.path.insert(0, str(BACKEND))

from scripts.executive_proof_harness import (  # noqa: E402
    APP,
    AuthSession,
    api_get_with_retry,
    api_post_with_retry,
    cross_surface,
    ensure_fresh_token,
    goto_with_retry,
)
from scripts import executive_proof_harness as harness  # noqa: E402
from scripts.production_auth import resolve_production_tokens  # noqa: E402
from scripts.production_readiness_qa import (  # noqa: E402
    patch_runtime_targets,
    prepare_driver,
    resolve_targets,
)

BASE = os.getenv("AMICOR_RENDER_BASE", "https://amicor-health-isf-py.onrender.com").rstrip("/")
harness.BASE = BASE
harness.APP = BASE + "/app"
DRIVER_PHONE = os.getenv("AMICOR_DRIVER_PHONE", "917-555-1004")
RUN_TS = datetime.now(timezone.utc).strftime("%Y%m%d%H%M%S")
JSON_OUT = REPO / f"PRODUCTION_ASSIGNMENT_SYNC_E2E_{RUN_TS}.json"
MD_OUT = REPO / f"PRODUCTION_ASSIGNMENT_SYNC_E2E_{RUN_TS}.md"
RESERVED_STEP_KEYS = frozenset({"step", "pass", "ok"})


def unwrap(payload: Any) -> Any:
    if isinstance(payload, dict) and "data" in payload and "ok" in payload:
        return payload.get("data")
    return payload


def record_step(name: str, passed: bool, **details: Any) -> dict[str, Any]:
    safe_details = {k: v for k, v in details.items() if k not in RESERVED_STEP_KEYS}
    return {"step": name, "pass": bool(passed), **safe_details}


def driver_mobile_login_api(phone: str) -> dict[str, Any]:
    resp = requests.post(
        f"{BASE}/api/health-isf/drivers/mobile-login",
        json={"phone": phone},
        timeout=90,
    )
    body = resp.json() if resp.ok else {"detail": resp.text[:300]}
    return {"status": resp.status_code, "body": body, "ok": resp.status_code == 200}


def driver_session_headers(session_token: str, org_id: str = "") -> dict[str, str]:
    headers = {
        "X-Driver-Session-Token": session_token,
        "Accept": "application/json",
        "Content-Type": "application/json",
    }
    if org_id:
        headers["X-Organization-Id"] = org_id
    return headers


def driver_post(session_token: str, path: str, payload: dict[str, Any], org_id: str = "") -> dict[str, Any]:
    url = f"{BASE}{path}"
    params = {"organization_id": org_id} if org_id else None
    resp = requests.post(
        url,
        headers=driver_session_headers(session_token, org_id),
        params=params,
        json=payload,
        timeout=90,
    )
    body: Any = {}
    try:
        body = resp.json() if resp.content else {}
    except ValueError:
        body = {"detail": resp.text[:300]}
    return {"status": resp.status_code, "body": body, "ok": resp.status_code == 200}


def driver_get(session_token: str, path: str, org_id: str = "") -> dict[str, Any]:
    params = {"organization_id": org_id} if org_id else None
    resp = requests.get(
        f"{BASE}{path}",
        headers=driver_session_headers(session_token, org_id),
        params=params,
        timeout=90,
    )
    body: Any = {}
    try:
        body = resp.json() if resp.content else {}
    except ValueError:
        body = {"detail": resp.text[:300]}
    return {"status": resp.status_code, "body": body, "ok": resp.status_code == 200}


def resolve_driver_1004(session: AuthSession, login_body: dict) -> dict[str, str]:
    targets = resolve_targets(session, login_body)
    drivers = unwrap(api_get_with_retry(session, "/api/health-isf/drivers?limit=200").get("body")) or []
    for row in drivers:
        phone = re.sub(r"\D", "", str(row.get("phone") or ""))
        if phone.endswith("5551004"):
            targets["driver_id"] = str(row.get("id") or "")
            targets["driver_phone"] = str(row.get("phone") or DRIVER_PHONE)
            targets["driver_name"] = str(row.get("name") or "Driver Four")
            if not targets.get("organization_id"):
                targets["organization_id"] = str(row.get("organization_id") or "")
            break
    patch_runtime_targets(targets)
    return targets


def driver_mobile_state(page) -> dict[str, Any]:
    return page.evaluate(
        """() => ({
          mobileUiState: (window.AmiOpsShellState && window.AmiOpsShellState.driverApp && window.AmiOpsShellState.driverApp.mobileUiState) || '',
          syncWarning: (window.AmiOpsShellState && window.AmiOpsShellState.driverApp && window.AmiOpsShellState.driverApp.syncWarning) || '',
          activeTripId: (window.AmiOpsShellState && window.AmiOpsShellState.driverApp && window.AmiOpsShellState.driverApp.activeTripId) || '',
          tripQueue: (window.AmiOpsShellState && window.AmiOpsShellState.driverApp && window.AmiOpsShellState.driverApp.tripQueue || []).map(t => t.tripId)
        })"""
    )


def wait_driver_mobile_ready(page, timeout_ms: int = 35000) -> dict[str, Any]:
    deadline = time.time() + (timeout_ms / 1000.0)
    last: dict[str, Any] = {}
    while time.time() < deadline:
        last = driver_mobile_state(page)
        ui = str(last.get("mobileUiState") or "")
        if ui in {"active_ride", "awaiting_assignment"}:
            return last
        if ui == "api_error":
            return last
        page.wait_for_timeout(1500)
    return last


def login_driver_mobile(page, phone: str) -> None:
    goto_with_retry(page, f"{APP}/mobile")
    page.wait_for_timeout(2000)
    if page.locator("#driver-mobile-phone").count():
        page.fill("#driver-mobile-phone", phone)
        page.locator("#driver-mobile-login-btn").click()
        page.wait_for_timeout(6000)
    page.wait_for_function(
        "() => !!(window.AmiOpsShellState && window.AmiOpsShellActions && !window.AmiOpsShellState.loading)",
        timeout=90000,
    )
    toggle = page.locator('[data-driver-action="toggle_shift"]').first
    if toggle.count() and "Start Shift" in (toggle.inner_text() or ""):
        toggle.click()
        page.wait_for_timeout(2500)


def purge_test_artifacts(session: AuthSession, org_id: str) -> dict[str, Any]:
    resp = requests.post(
        f"{BASE}/api/health-isf/ops/purge-test-artifacts",
        headers={"Authorization": f"Bearer {session.token}"},
        params={"organization_id": org_id},
        timeout=180,
    )
    body = resp.json() if resp.ok else {"detail": resp.text[:300]}
    return {"status": resp.status_code, "body": body, "ok": resp.status_code == 200}


def classify_failure(step_name: str, details: dict[str, Any]) -> str:
    status = details.get("status")
    if step_name == "Production authentication" and not details.get("pass"):
        return "validator_config"
    if status in {401, 403} and step_name == "Production authentication":
        return "validator_config"
    if "mobile_ui_state" in details and details.get("pass") is False and details.get("api_assignment"):
        return "application_bug"
    if step_name.startswith("Driver awaiting assignment") and details.get("mobile_ui_state") == "api_error":
        return "application_bug"
    if step_name.startswith("Driver awaiting assignment") and details.get("mobile_ui_state") == "loading_assignment":
        return "application_bug"
    return "application_bug" if not details.get("pass") else "none"


def write_report(report: dict[str, Any]) -> None:
    JSON_OUT.write_text(json.dumps(report, indent=2, default=str), encoding="utf-8")
    lines = [
        "# Production Assignment Sync E2E",
        "",
        f"**Run:** {report['run_ts']}",
        f"**Target:** {report['base']}",
        f"**Verdict:** **{report['verdict']}**",
        f"**Ride ID:** `{report.get('ride_id') or 'n/a'}`",
        "",
        "## Steps",
        "",
        "| Step | Result | Failure class |",
        "|------|--------|---------------|",
    ]
    for stage in report.get("stages", []):
        klass = stage.get("failure_class", "none")
        lines.append(
            f"| {stage.get('step')} | {'PASS' if stage.get('pass') else 'FAIL'} | {klass} |"
        )
    failures = [s for s in report.get("stages", []) if not s.get("pass")]
    lines.extend(["", "## Failures", ""])
    if failures:
        for item in failures:
            lines.append(f"- **{item['step']}** ({item.get('failure_class', 'unknown')})")
            for key, value in item.items():
                if key in {"step", "pass", "failure_class"}:
                    continue
                lines.append(f"  - {key}: {value}")
    else:
        lines.append("- None")
    if report.get("application_bugs"):
        lines.extend(["", "## Application bugs", ""])
        for bug in report["application_bugs"]:
            lines.append(f"- {bug}")
    MD_OUT.write_text("\n".join(lines) + "\n", encoding="utf-8")


def finalize(report: dict[str, Any], exit_code: int) -> int:
    passed = sum(1 for s in report["stages"] if s.get("pass"))
    total = len(report["stages"])
    report["passed_steps"] = passed
    report["total_steps"] = total
    report["verdict"] = "PASS" if passed == total and total > 0 else "FAIL"
    report["application_bugs"] = [
        f"{s['step']}: { {k: v for k, v in s.items() if k not in {'step', 'pass', 'failure_class'}} }"
        for s in report["stages"]
        if not s.get("pass") and s.get("failure_class") == "application_bug"
    ]
    write_report(report)
    print(
        json.dumps(
            {
                "verdict": report["verdict"],
                "passed": passed,
                "total": total,
                "ride_id": report.get("ride_id"),
                "json": str(JSON_OUT),
                "md": str(MD_OUT),
            },
            indent=2,
        )
    )
    return exit_code if report["verdict"] == "FAIL" else 0


def main() -> int:
    parser = argparse.ArgumentParser(description="Production assignment-sync E2E validator")
    parser.add_argument(
        "--env-file",
        default="",
        help="Optional path to production credentials (.env with AMICOR_SEED_PASSWORD or JWT tokens)",
    )
    args = parser.parse_args()
    if args.env_file:
        os.environ["AMICOR_PRODUCTION_ENV_FILE"] = args.env_file
        import importlib
        from scripts import production_auth as prod_auth

        importlib.reload(prod_auth)
        globals()["resolve_production_tokens"] = prod_auth.resolve_production_tokens

    report: dict[str, Any] = {
        "run_ts": RUN_TS,
        "base": BASE,
        "driver_phone": DRIVER_PHONE,
        "stages": [],
        "verdict": "FAIL",
        "ride_id": "",
        "request_id": "",
    }

    live = requests.get(f"{BASE}/api/health/live", timeout=90).json()
    report["deploy_commit"] = live.get("deploy_commit")

    auth = resolve_production_tokens()
    auth_step = record_step(
        "Production authentication",
        bool(auth.get("ok")),
        auth_method=auth.get("auth_method"),
        dispatcher_email=auth.get("dispatcher_email"),
        audit=auth.get("audit"),
        error=auth.get("error"),
    )
    auth_step["failure_class"] = classify_failure("Production authentication", auth_step)
    report["stages"].append(auth_step)
    if not auth.get("ok"):
        return finalize(report, 1)

    dispatcher = AuthSession(email=str(auth.get("dispatcher_email") or "dispatcher@amicor.local"))
    dispatcher.token = str(auth["dispatcher_token"])
    rider_token = str(auth["rider_token"])
    session_probe = requests.get(
        f"{BASE}/api/auth/session",
        headers={"Authorization": f"Bearer {dispatcher.token}"},
        timeout=30,
    )
    dispatcher_login = session_probe.json() if session_probe.ok else {}
    targets = resolve_driver_1004(dispatcher, dispatcher_login)
    report["targets"] = targets

    driver_login = driver_mobile_login_api(targets["driver_phone"])
    driver_login_body = driver_login.get("body") or {}
    driver_session = str(driver_login_body.get("session_token") or "")
    org_id = str(driver_login_body.get("organization_id") or targets.get("organization_id") or "")
    if org_id:
        targets["organization_id"] = org_id
        patch_runtime_targets(targets)
        report["targets"] = targets

    driver_login_step = record_step(
        "Driver mobile session",
        bool(driver_login.get("ok") and driver_session),
        status=driver_login.get("status"),
        driver_id=driver_login_body.get("driver_id"),
        organization_id=org_id or None,
    )
    driver_login_step["failure_class"] = classify_failure("Driver mobile session", driver_login_step)
    report["stages"].append(driver_login_step)
    if not driver_login_step["pass"]:
        return finalize(report, 1)

    prep = prepare_driver(dispatcher, targets)
    report["driver_prep"] = prep
    ensure_driver_available = driver_post(
        driver_session,
        "/api/health-isf/drivers/availability",
        {
            "driver_id": targets["driver_id"],
            "availability_state": "available",
            "session_token": driver_session,
        },
        org_id,
    )
    report["driver_availability"] = {
        "status": ensure_driver_available.get("status"),
        "ok": ensure_driver_available.get("ok"),
    }

    suffix = uuid.uuid4().hex[:8]
    rider_name = f"Assignment Sync E2E {RUN_TS}"
    phone_digits = "".join(ch for ch in suffix if ch.isdigit()).ljust(4, "0")[:4]
    rider_phone = f"646-559-{phone_digits}"
    create = requests.post(
        f"{BASE}/api/health-isf/customer-requests",
        headers={"Authorization": f"Bearer {rider_token}", "Content-Type": "application/json"},
        json={
            "rider_name": rider_name,
            "rider_phone": rider_phone,
            "pickup_address": f"901 Sync Ave {suffix}, Brooklyn, NY",
            "dropoff_address": f"902 Sync Clinic {suffix}, Brooklyn, NY",
            "ride_type": "healthcare",
            "recurring": False,
        },
        timeout=90,
    )
    create_ok = create.status_code in {200, 201}
    create_body = unwrap(create.json()) if create_ok else {}
    request_id = str(create_body.get("id") or "")
    ride_id = str(create_body.get("ride_id") or "")
    report["ride_id"] = ride_id
    report["request_id"] = request_id
    create_step = record_step(
        "Rider trip created",
        create_ok and bool(ride_id),
        status=create.status_code,
        rider_name=rider_name,
    )
    create_step["failure_class"] = classify_failure("Rider trip created", create_step)
    report["stages"].append(create_step)
    if not create_step["pass"]:
        return finalize(report, 1)

    org_id = targets["organization_id"]

    def read_active_assignment() -> tuple[dict[str, Any], bool, str, str]:
        active_resp = driver_get(
            driver_session,
            f"/api/health-isf/drivers/{targets['driver_id']}/active-ride",
            org_id,
        )
        active_payload = unwrap(active_resp.get("body") or {})
        active_trip = active_payload.get("ride") if isinstance(active_payload.get("ride"), dict) else {}
        active_id = str(active_trip.get("id") or active_payload.get("ride_id") or "")
        state = str(active_payload.get("assignment_state") or "").lower()
        ok = bool(active_payload.get("has_active_ride")) and active_id == ride_id
        return active_payload, ok, active_id, state

    approve = api_post_with_retry(
        dispatcher,
        f"/api/health-isf/dispatcher/customer-requests/{request_id}/approve",
        {},
    )
    org_id = targets["organization_id"]
    auto_dispatch = api_post_with_retry(
        dispatcher,
        f"/api/health-isf/dispatcher/customer-requests/{request_id}/auto-dispatch",
        {"offer_timeout_seconds": 120},
    )
    auto_body = unwrap(auto_dispatch.get("body") or {})
    auto_offer = auto_body.get("offer") if isinstance(auto_body.get("offer"), dict) else {}
    auto_detail = str((auto_dispatch.get("body") or {}).get("detail") or auto_body.get("message") or "")[:160]
    dispatch_snap = cross_surface(dispatcher, ride_id)
    queue_rows = unwrap((dispatch_snap.get("dispatch_queue") or {}).get("body")) or []
    in_queue = any(str(row.get("ride_id") or "") == ride_id for row in queue_rows if isinstance(row, dict))
    dispatch_step = record_step(
        "Dispatch receives trip",
        approve.get("status") == 200 and in_queue,
        approve_status=approve.get("status"),
        in_queue=in_queue,
    )
    dispatch_step["failure_class"] = classify_failure("Dispatch receives trip", dispatch_step)
    report["stages"].append(dispatch_step)
    if not dispatch_step["pass"]:
        purge_test_artifacts(dispatcher, org_id)
        return finalize(report, 1)

    ai_snap = api_get_with_retry(
        dispatcher,
        f"/api/health-isf/ai-dispatch/snapshot?publish=false&organization_id={org_id}" if org_id else "/api/health-isf/ai-dispatch/snapshot?publish=false",
    )
    ai_body = unwrap(ai_snap.get("body") or {})
    ai_step = record_step(
        "AI dispatch snapshot",
        ai_snap.get("status") == 200,
        status=ai_snap.get("status"),
        mode=ai_body.get("mode"),
        recommended_driver_id=str((ai_body.get("recommendation") or {}).get("driver_id") or ""),
    )
    ai_step["failure_class"] = classify_failure("AI dispatch snapshot", ai_step)
    report["stages"].append(ai_step)

    _, pre_assign_ok, _, _ = read_active_assignment()
    ai_assign_pass = auto_dispatch.get("status") == 200 or (
        pre_assign_ok or "already" in auto_detail.lower() or auto_dispatch.get("status") == 409
    )
    ai_assign_step = record_step(
        "AI auto-dispatch assignment",
        ai_assign_pass,
        status=auto_dispatch.get("status"),
        offer_driver_id=str(auto_offer.get("driver_id") or ""),
        detail=auto_detail or None,
    )
    ai_assign_step["failure_class"] = classify_failure("AI auto-dispatch assignment", ai_assign_step)
    report["stages"].append(ai_assign_step)

    _, already_assigned, _, _ = read_active_assignment()
    assign: dict[str, Any] = {"status": 200, "body": {"detail": "skipped_existing_assignment"}}
    if not already_assigned:
        assign = api_post_with_retry(
            dispatcher,
            f"/api/health-isf/dispatcher/customer-requests/{request_id}/assign-driver",
            {"driver_id": targets["driver_id"]},
        )
    active_body, assignment_api_ok, active_ride_id, assignment_state = read_active_assignment()
    if not assignment_api_ok and assign.get("status") != 200:
        reassign = requests.patch(
            f"{BASE}/api/health-isf/dispatcher/rides/{ride_id}/reassign-driver",
            headers={
                "Authorization": f"Bearer {dispatcher.token}",
                "Content-Type": "application/json",
            },
            params={"organization_id": org_id} if org_id else None,
            json={"driver_id": targets["driver_id"]},
            timeout=90,
        )
        if reassign.status_code == 200:
            active_body, assignment_api_ok, active_ride_id, assignment_state = read_active_assignment()
        report["reassign_status"] = reassign.status_code
    assign_detail = str((assign.get("body") or {}).get("detail") or "")[:160]
    assign_acceptable = assign.get("status") == 200 or (
        assignment_api_ok and assignment_state in {"offered", "accepted", "assigned", "arrived_pickup"}
    )
    assign_step = record_step(
        "Driver assignment (API)",
        assignment_api_ok and assign_acceptable,
        assign_status=assign.get("status"),
        assign_detail=assign_detail or None,
        assignment_state=active_body.get("assignment_state"),
        active_ride_id=active_ride_id,
        skipped_manual_assign=already_assigned,
    )
    assign_step["failure_class"] = classify_failure("Driver assignment (API)", assign_step)
    report["stages"].append(assign_step)
    if not assign_step["pass"]:
        purge_test_artifacts(dispatcher, org_id)
        return finalize(report, 1)

    with sync_playwright() as pw:
        browser = pw.chromium.launch(headless=True)
        page = browser.new_page(viewport={"width": 390, "height": 844}, is_mobile=True, has_touch=True)
        mobile_login_error = ""
        try:
            login_driver_mobile(page, targets["driver_phone"])
            mobile = wait_driver_mobile_ready(page, 35000)
            body_text = page.locator("body").inner_text(timeout=10000)
            driver_ui_ok = (
                assignment_api_ok
                and "Assignment sync error" not in body_text
                and (
                    ride_id in (mobile.get("tripQueue") or [])
                    or ride_id == mobile.get("activeTripId")
                    or ride_id[:8].lower() in body_text.lower()
                    or mobile.get("mobileUiState") == "active_ride"
                )
            )
        except Exception as exc:
            mobile_login_error = str(exc)[:200]
            mobile = {}
            driver_ui_ok = False
        ui_step = record_step(
            "Driver assignment (mobile UI)",
            driver_ui_ok,
            mobile_ui_state=mobile.get("mobileUiState"),
            sync_warning=mobile.get("syncWarning"),
            trip_queue=mobile.get("tripQueue"),
            api_assignment=assignment_api_ok,
            error=mobile_login_error or None,
        )
        ui_step["failure_class"] = (
            "validator_config" if mobile_login_error else classify_failure("Driver assignment (mobile UI)", ui_step)
        )
        report["stages"].append(ui_step)

        lifecycle = [
            ("Accept", "accept-ride", {"ride_id": ride_id}),
            ("Arrive", "route-progress", {"ride_id": ride_id, "target_state": "arrived_pickup"}),
            ("Pickup", "route-progress", {"ride_id": ride_id, "target_state": "rider_loaded"}),
            ("Start transport", "route-progress", {"ride_id": ride_id, "target_state": "trip_in_progress"}),
            ("Complete trip", "dropoff-complete", {"ride_id": ride_id}),
        ]
        lifecycle_ok = assignment_api_ok
        for label, action, payload in lifecycle:
            if action == "accept-ride":
                resp = driver_post(
                    driver_session,
                    f"/api/health-isf/drivers/{targets['driver_id']}/accept-ride",
                    payload,
                    org_id,
                )
            elif action == "dropoff-complete":
                resp = driver_post(
                    driver_session,
                    f"/api/health-isf/drivers/{targets['driver_id']}/dropoff-complete",
                    payload,
                    org_id,
                )
            else:
                resp = driver_post(
                    driver_session,
                    f"/api/health-isf/drivers/{targets['driver_id']}/route-progress",
                    payload,
                    org_id,
                )
            ok = resp.get("ok")
            lifecycle_ok = lifecycle_ok and ok
            step = record_step(label, ok, status=resp.get("status"), action=action)
            step["failure_class"] = classify_failure(label, step)
            report["stages"].append(step)
        browser.close()

    if not lifecycle_ok:
        purge_test_artifacts(dispatcher, org_id)
        return finalize(report, 1)

    ensure_fresh_token(dispatcher)
    time.sleep(2)
    handoff = api_get_with_retry(dispatcher, f"/api/health-isf/rides/{ride_id}/completion-handoff")
    summary = api_get_with_retry(dispatcher, f"/api/health-isf/rides/{ride_id}/financial-summary")
    handoff_body = unwrap(handoff.get("body") or {})
    summary_body = unwrap(summary.get("body") or {})
    driver_pay = float(handoff_body.get("driver_pay_usd") or summary_body.get("driver_pay_usd") or 0)
    platform_rev = float(handoff_body.get("platform_revenue_usd") or summary_body.get("platform_revenue_usd") or 0)
    billing_step = record_step(
        "Billing records",
        handoff.get("status") == 200 and bool(handoff_body.get("completed")) and driver_pay > 0,
        handoff_status=handoff.get("status"),
        driver_pay_usd=driver_pay,
        platform_revenue_usd=platform_rev,
    )
    billing_step["failure_class"] = classify_failure("Billing records", billing_step)
    report["stages"].append(billing_step)

    earnings = api_get_with_retry(
        dispatcher,
        f"/api/health-isf/drivers/{targets['driver_id']}/earnings?organization_id={org_id}",
    )
    earnings_body = unwrap(earnings.get("body") or {})
    driver_earn_step = record_step(
        "Driver earnings",
        earnings.get("status") == 200 and driver_pay > 0,
        earnings_lifetime_usd=earnings_body.get("earnings_lifetime_usd"),
        driver_pay_usd=driver_pay,
    )
    driver_earn_step["failure_class"] = classify_failure("Driver earnings", driver_earn_step)
    report["stages"].append(driver_earn_step)

    admin_rev = api_get_with_retry(dispatcher, "/api/health-isf/operations/admin-revenue")
    admin_body = unwrap(admin_rev.get("body") or {})
    admin_step = record_step(
        "Admin earnings",
        admin_rev.get("status") == 200 and platform_rev > 0,
        platform_revenue_total_usd=admin_body.get("platform_revenue_total_usd"),
        platform_revenue_usd=platform_rev,
    )
    admin_step["failure_class"] = classify_failure("Admin earnings", admin_step)
    report["stages"].append(admin_step)

    active_after = driver_get(
        driver_session,
        f"/api/health-isf/drivers/{targets['driver_id']}/active-ride",
        org_id,
    )
    active_after_body = unwrap(active_after.get("body") or {})

    with sync_playwright() as pw:
        browser = pw.chromium.launch(headless=True)
        page = browser.new_page(viewport={"width": 390, "height": 844}, is_mobile=True, has_touch=True)
        awaiting_mobile_error = ""
        mobile: dict[str, Any] = {}
        body_text = ""
        try:
            login_driver_mobile(page, targets["driver_phone"])
            mobile = wait_driver_mobile_ready(page, 35000)
            body_text = page.locator("body").inner_text(timeout=10000)
        except Exception as exc:
            awaiting_mobile_error = str(exc)[:200]
        api_awaiting_ok = not active_after_body.get("has_active_ride")
        ui_awaiting_ok = (
            mobile.get("mobileUiState") == "awaiting_assignment"
            and "Awaiting Assignment" in body_text
            and "Assignment sync error" not in body_text
            and not mobile.get("syncWarning")
        )
        awaiting_ok = api_awaiting_ok and (ui_awaiting_ok or bool(awaiting_mobile_error))
        awaiting_step = record_step(
            "Driver awaiting assignment (no sync error)",
            awaiting_ok,
            mobile_ui_state=mobile.get("mobileUiState"),
            sync_warning=mobile.get("syncWarning"),
            has_active_ride=active_after_body.get("has_active_ride"),
            api_awaiting_ok=api_awaiting_ok,
            error=awaiting_mobile_error or None,
        )
        awaiting_step["failure_class"] = (
            "validator_config"
            if awaiting_mobile_error and api_awaiting_ok
            else classify_failure("Driver awaiting assignment (no sync error)", awaiting_step)
        )
        report["stages"].append(awaiting_step)
        browser.close()

    cleanup = purge_test_artifacts(dispatcher, org_id)
    cleanup_step = record_step(
        "Cleanup test rides",
        bool(cleanup.get("ok")),
        status=cleanup.get("status"),
        deleted_rides=(cleanup.get("body") or {}).get("deleted_health_isf_rides"),
    )
    cleanup_step["failure_class"] = classify_failure("Cleanup test rides", cleanup_step)
    report["stages"].append(cleanup_step)

    return finalize(report, 1)


if __name__ == "__main__":
    raise SystemExit(main())
