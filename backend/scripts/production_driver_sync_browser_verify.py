#!/usr/bin/env python3
"""Production browser verification: Rider -> Dispatch -> Driver Primary Workflow (stop before Accept Trip)."""
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
OUT_DIR = REPO / "PRODUCTION_QA_EVIDENCE"
JSON_OUT = OUT_DIR / f"PRODUCTION_DRIVER_SYNC_BROWSER_{RUN_TS}.json"
MD_OUT = OUT_DIR / f"PRODUCTION_DRIVER_SYNC_BROWSER_{RUN_TS}.md"


def unwrap(payload: Any) -> Any:
    if isinstance(payload, dict) and "data" in payload and "ok" in payload:
        return payload.get("data")
    return payload


def step(name: str, passed: bool, **details: Any) -> dict[str, Any]:
    return {"step": name, "pass": bool(passed), **details}


def driver_headers(session_token: str, org_id: str = "") -> dict[str, str]:
    headers = {"X-Driver-Session-Token": session_token, "Accept": "application/json"}
    if org_id:
        headers["X-Organization-Id"] = org_id
    return headers


def timed_get(path: str, session_token: str, org_id: str = "", timeout: int = 120) -> dict[str, Any]:
    start = time.perf_counter()
    try:
        resp = requests.get(
            f"{BASE}{path}",
            headers=driver_headers(session_token, org_id),
            params={"organization_id": org_id} if org_id else None,
            timeout=timeout,
        )
        elapsed_ms = int((time.perf_counter() - start) * 1000)
        body: Any = {}
        try:
            body = resp.json() if resp.content else {}
        except ValueError:
            body = {"detail": resp.text[:300]}
        return {
            "path": path,
            "status": resp.status_code,
            "elapsed_ms": elapsed_ms,
            "ok": resp.status_code < 400,
            "count": len(body) if isinstance(body, list) else None,
            "bytes": len(resp.content),
        }
    except requests.RequestException as exc:
        elapsed_ms = int((time.perf_counter() - start) * 1000)
        return {"path": path, "status": 0, "elapsed_ms": elapsed_ms, "ok": False, "error": str(exc)}


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


def wait_primary_workflow(page, ride_id: str, timeout_ms: int = 45000) -> dict[str, Any]:
    deadline = time.time() + (timeout_ms / 1000.0)
    last: dict[str, Any] = {}
    while time.time() < deadline:
        body_text = page.locator("body").inner_text(timeout=10000)
        accept = page.locator('[data-driver-action="accept_trip"]').first
        last = {
            "mobile_ui_state": page.evaluate(
                "() => (window.AmiOpsShellState && window.AmiOpsShellState.driverApp && window.AmiOpsShellState.driverApp.mobileUiState) || ''"
            ),
            "sync_warning": page.evaluate(
                "() => (window.AmiOpsShellState && window.AmiOpsShellState.driverApp && window.AmiOpsShellState.driverApp.syncWarning) || ''"
            ),
            "active_trip_id": page.evaluate(
                "() => (window.AmiOpsShellState && window.AmiOpsShellState.driverApp && window.AmiOpsShellState.driverApp.activeTripId) || ''"
            ),
            "trip_queue_ids": page.evaluate(
                "() => (window.AmiOpsShellState && window.AmiOpsShellState.driverApp && window.AmiOpsShellState.driverApp.tripQueue || []).map(t => t.tripId)"
            ),
            "has_accept_button": accept.count() > 0,
            "accept_disabled": accept.is_disabled() if accept.count() > 0 else None,
            "accept_visible": accept.count() > 0 and accept.is_visible(),
            "shows_sync_failed": "assignment sync failed" in body_text.lower(),
            "shows_primary_workflow": "Shift and Medical Transport Workflow" in body_text,
            "shows_awaiting_only": "Awaiting Assignment" in body_text and "Accept Trip" not in body_text,
            "body_has_ride_id": ride_id[:8].lower() in body_text.lower(),
        }
        ready = (
            not last["shows_sync_failed"]
            and last["shows_primary_workflow"]
            and last["has_accept_button"]
            and last["accept_visible"]
            and not last["accept_disabled"]
            and (
                ride_id == last["active_trip_id"]
                or ride_id in (last["trip_queue_ids"] or [])
                or last["body_has_ride_id"]
            )
        )
        if ready:
            last["ready"] = True
            return last
        page.wait_for_timeout(1500)
    last["ready"] = False
    return last


def write_report(report: dict[str, Any]) -> None:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    JSON_OUT.write_text(json.dumps(report, indent=2, default=str), encoding="utf-8")
    timing = report.get("endpoint_timing") or {}
    lines = [
        "# Production Driver Sync Browser Verification",
        "",
        f"**Run:** {report['run_ts']}",
        f"**Deploy commit:** `{report.get('deploy_commit', 'unknown')}`",
        f"**Verdict:** **{report['verdict']}**",
        f"**Ride ID:** `{report.get('ride_id', 'n/a')}`",
        "",
        "## Endpoint timing (assigned-rides)",
        "",
        f"- Full `assigned-rides`: **{timing.get('assigned_rides_full_ms', 'n/a')} ms**",
        f"- Light `assigned-rides?limit=15`: **{timing.get('assigned_rides_limit15_ms', 'n/a')} ms**",
        f"- `active-ride`: **{timing.get('active_ride_ms', 'n/a')} ms**",
        "",
        "## Why assigned-rides was slow (pre-fix)",
        "",
        report.get("assigned_rides_root_cause", ""),
        "",
        "## Steps",
        "",
        "| Step | Result |",
        "|------|--------|",
    ]
    for stage in report.get("stages", []):
        lines.append(f"| {stage.get('step')} | {'PASS' if stage.get('pass') else 'FAIL'} |")
    lines.extend(["", f"Evidence: `{JSON_OUT.name}`", ""])
    MD_OUT.write_text("\n".join(lines), encoding="utf-8")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--env-file", default=".runtime/production.env")
    args = parser.parse_args()
    if args.env_file:
        os.environ["AMICOR_PRODUCTION_ENV_FILE"] = args.env_file
        try:
            from dotenv import load_dotenv

            load_dotenv(args.env_file, override=True)
        except ImportError:
            pass
        import importlib
        from scripts import production_auth as prod_auth

        importlib.reload(prod_auth)
        resolve_fn = prod_auth.resolve_production_tokens
    else:
        resolve_fn = resolve_production_tokens

    report: dict[str, Any] = {
        "run_ts": RUN_TS,
        "base": BASE,
        "driver_phone": DRIVER_PHONE,
        "stages": [],
        "verdict": "FAIL",
        "ride_id": "",
        "request_id": "",
        "endpoint_timing": {},
        "assigned_rides_root_cause": (
            "Before this fix, `GET /drivers/{id}/assigned-rides` was on the critical path for every "
            "Driver Mobile sync. The handler called `list_driver_assigned_rides()` which runs dispatch "
            "preparation (`_prepare_driver_mobile_workspace_read`, `expire_stale_dispatch_offers`, "
            "`_offer_newest_queue_ride_to_driver`) and then built each row with "
            "`TripFinancialEngine.get_ride_financial_summary()` (N+1 DB work per ride, up to 100 rides). "
            "The frontend waited for all four probes in parallel inside a 30s bootstrap timeout; "
            "with 20s fetch timeouts and 2 retries, a slow assigned-rides alone could consume 60–120s "
            "and fail the whole sync even when active-ride/active-offer already had the offer."
        ),
    }

    live = requests.get(f"{BASE}/api/health/live", timeout=120).json()
    report["deploy_commit"] = live.get("deploy_commit")

    auth = resolve_fn()
    auth_step = step(
        "Production authentication",
        bool(auth.get("ok")),
        auth_method=auth.get("auth_method"),
        audit=auth.get("audit"),
        error=auth.get("error"),
    )
    report["stages"].append(auth_step)
    if not auth.get("ok"):
        write_report(report)
        print(json.dumps({"verdict": "FAIL", "step": "Production authentication", "audit": auth.get("audit")}, indent=2))
        return 1

    dispatcher = AuthSession(email=str(auth.get("dispatcher_email") or "dispatcher@amicor.local"))
    dispatcher.token = str(auth["dispatcher_token"])
    rider_token = str(auth["rider_token"])
    session_probe = requests.get(
        f"{BASE}/api/auth/session",
        headers={"Authorization": f"Bearer {dispatcher.token}"},
        timeout=30,
    )
    targets = resolve_driver_1004(dispatcher, session_probe.json() if session_probe.ok else {})

    login_resp = requests.post(
        f"{BASE}/api/health-isf/drivers/mobile-login",
        json={"phone": targets["driver_phone"]},
        timeout=120,
    )
    login_body = login_resp.json() if login_resp.ok else {}
    driver_session = str(login_body.get("session_token") or "")
    org_id = str(login_body.get("organization_id") or targets.get("organization_id") or "")
    driver_id = str(login_body.get("driver_id") or targets.get("driver_id") or "")
    report["stages"].append(
        step(
            "Driver mobile session",
            login_resp.ok and bool(driver_session),
            status=login_resp.status_code,
            driver_id=driver_id,
        )
    )
    if not login_resp.ok:
        write_report(report)
        return 1

    timing = {
        "active_ride_ms": timed_get(
            f"/api/health-isf/drivers/{driver_id}/active-ride", driver_session, org_id
        ).get("elapsed_ms"),
        "assigned_rides_full_ms": timed_get(
            f"/api/health-isf/drivers/{driver_id}/assigned-rides", driver_session, org_id
        ).get("elapsed_ms"),
        "assigned_rides_limit15_ms": timed_get(
            f"/api/health-isf/drivers/{driver_id}/assigned-rides?limit=15", driver_session, org_id
        ).get("elapsed_ms"),
    }
    report["endpoint_timing"] = timing

    prepare_driver(dispatcher, targets)
    requests.post(
        f"{BASE}/api/health-isf/drivers/availability",
        headers=driver_headers(driver_session, org_id),
        params={"organization_id": org_id} if org_id else None,
        json={
            "driver_id": driver_id,
            "availability_state": "available",
            "session_token": driver_session,
        },
        timeout=90,
    )

    marker = uuid.uuid4().hex[:8]
    rider_name = f"Driver Sync Browser {RUN_TS}"
    phone_digits = "".join(ch for ch in marker if ch.isdigit()).ljust(4, "0")[:4]
    create = requests.post(
        f"{BASE}/api/health-isf/customer-requests",
        headers={"Authorization": f"Bearer {rider_token}", "Content-Type": "application/json"},
        json={
            "rider_name": rider_name,
            "rider_phone": f"646-558-{phone_digits}",
            "pickup_address": f"100 Immediate Sync St {marker}, Brooklyn, NY",
            "dropoff_address": f"200 Immediate Clinic {marker}, Brooklyn, NY",
            "ride_type": "healthcare",
            "recurring": False,
        },
        timeout=120,
    )
    create_body = unwrap(create.json()) if create.ok else {}
    ride_id = str(create_body.get("ride_id") or "")
    request_id = str(create_body.get("id") or "")
    report["ride_id"] = ride_id
    report["request_id"] = request_id
    report["stages"].append(
        step("Rider immediate trip created", create.ok and bool(ride_id), status=create.status_code)
    )
    if not ride_id:
        write_report(report)
        return 1

    approve = api_post_with_retry(
        dispatcher,
        f"/api/health-isf/dispatcher/customer-requests/{request_id}/approve",
        {},
    )
    auto_dispatch = api_post_with_retry(
        dispatcher,
        f"/api/health-isf/dispatcher/customer-requests/{request_id}/auto-dispatch",
        {"offer_timeout_seconds": 120},
    )
    dispatch_snap = cross_surface(dispatcher, ride_id)
    queue_rows = unwrap((dispatch_snap.get("dispatch_queue") or {}).get("body")) or []
    in_queue = any(str(row.get("ride_id") or "") == ride_id for row in queue_rows if isinstance(row, dict))
    report["stages"].append(
        step(
            "Dispatch receives trip",
            approve.get("status") == 200 and in_queue,
            approve_status=approve.get("status"),
            auto_dispatch_status=auto_dispatch.get("status"),
            in_queue=in_queue,
        )
    )

    assign = api_post_with_retry(
        dispatcher,
        f"/api/health-isf/dispatcher/customer-requests/{request_id}/assign-driver",
        {"driver_id": driver_id},
    )
    active_resp = requests.get(
        f"{BASE}/api/health-isf/drivers/{driver_id}/active-ride",
        headers=driver_headers(driver_session, org_id),
        params={"organization_id": org_id} if org_id else None,
        timeout=90,
    )
    active_body = unwrap(active_resp.json()) if active_resp.ok else {}
    active_ride = active_body.get("ride") if isinstance(active_body.get("ride"), dict) else {}
    active_ride_id = str(active_ride.get("id") or "")
    assignment_state = str(active_body.get("assignment_state") or "").lower()
    assignment_ok = (
        active_body.get("has_active_ride") is True
        and active_ride_id == ride_id
        and assignment_state in {"offered", "assigned", "accepted"}
    )
    report["stages"].append(
        step(
            "Driver assignment (API)",
            assignment_ok or assign.get("status") == 200,
            assign_status=assign.get("status"),
            assignment_state=assignment_state,
            active_ride_id=active_ride_id,
        )
    )
    if not assignment_ok and assign.get("status") != 200:
        write_report(report)
        return 1

    screenshot_path = OUT_DIR / f"PRODUCTION_DRIVER_SYNC_BROWSER_{RUN_TS}.png"
    browser_state: dict[str, Any] = {}
    with sync_playwright() as pw:
        browser = pw.chromium.launch(headless=True)
        page = browser.new_page(viewport={"width": 390, "height": 844}, is_mobile=True, has_touch=True)
        try:
            login_driver_mobile(page, targets["driver_phone"])
            browser_state = wait_primary_workflow(page, ride_id, timeout_ms=45000)
            page.screenshot(path=str(screenshot_path), full_page=True)
        except Exception as exc:
            browser_state = {"error": str(exc)[:300], "ready": False}
            try:
                page.screenshot(path=str(screenshot_path), full_page=True)
            except Exception:
                pass
        browser.close()

    report["browser"] = browser_state
    report["screenshot"] = str(screenshot_path)
    ui_pass = bool(browser_state.get("ready"))
    report["stages"].append(
        step(
            "Driver Primary Workflow + Accept Trip visible (browser)",
            ui_pass,
            **{k: v for k, v in browser_state.items() if k != "ready"},
        )
    )
    report["manual_handoff"] = {
        "ride_id": ride_id,
        "driver_phone": targets["driver_phone"],
        "instruction": "Accept Trip and complete workflow manually in /app/mobile",
        "accept_not_clicked_by_automation": True,
    }

    passed = sum(1 for s in report["stages"] if s.get("pass"))
    report["passed_steps"] = passed
    report["total_steps"] = len(report["stages"])
    report["verdict"] = "PASS" if passed == len(report["stages"]) and passed > 0 else "FAIL"
    write_report(report)
    print(
        json.dumps(
            {
                "verdict": report["verdict"],
                "ride_id": ride_id,
                "deploy_commit": report.get("deploy_commit"),
                "endpoint_timing": timing,
                "json": str(JSON_OUT),
                "md": str(MD_OUT),
                "screenshot": str(screenshot_path),
            },
            indent=2,
        )
    )
    return 0 if report["verdict"] == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
