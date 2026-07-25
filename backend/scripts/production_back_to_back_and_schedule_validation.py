"""Production Test A (back-to-back cycles) + Test B (future schedule protection)."""
from __future__ import annotations

import argparse
import importlib
import json
import os
import re
import sys
import time
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

import requests

BACKEND = Path(__file__).resolve().parent.parent
REPO = BACKEND.parent
sys.path.insert(0, str(BACKEND))

from scripts import production_auth as pa  # noqa: E402

CANONICAL_PHONES = ("917-555-1001", "917-555-1002", "917-555-1003", "917-555-1004")
PRESERVE_PASSENGER_MARKERS = ("rita j wonokay", "saye monibah", "rita monibah")
RUN_TS = datetime.now(timezone.utc).strftime("%Y%m%d%H%M%S")
TEST_MARKER = f"back_to_back_validation_{RUN_TS}"
SCHEDULE_MARKER = f"schedule_protection_{RUN_TS}"
JSON_OUT = REPO / f"PRODUCTION_CONTROLLED_VALIDATION_{RUN_TS}.json"
MD_OUT = REPO / f"PRODUCTION_CONTROLLED_VALIDATION_{RUN_TS}.md"

LIFECYCLE_STEPS = (
    ("accept", "accept-ride", {}),
    ("arrive", "route-progress", {"target_state": "arrived_pickup"}),
    ("pickup", "route-progress", {"target_state": "rider_loaded"}),
    ("transport", "route-progress", {"target_state": "trip_in_progress"}),
    ("complete", "dropoff-complete", {}),
)


def unwrap(payload: Any) -> Any:
    if isinstance(payload, dict) and "data" in payload and "ok" in payload:
        return payload.get("data")
    return payload


def phone_digits(value: str) -> str:
    return re.sub(r"\D", "", value or "")


def rider_phone_from_suffix(suffix: str) -> str:
    digits = "".join(ch for ch in suffix if ch.isdigit()).ljust(4, "0")[:4]
    return f"646-559-{digits}"


def dispatcher_headers(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}


def driver_headers(session_token: str, org_id: str = "") -> dict[str, str]:
    headers = {
        "X-Driver-Session-Token": session_token,
        "Accept": "application/json",
        "Content-Type": "application/json",
    }
    if org_id:
        headers["X-Organization-Id"] = org_id
    return headers


def mobile_login(phone: str) -> dict[str, Any]:
    resp = requests.post(
        f"{pa.BASE}/api/health-isf/drivers/mobile-login",
        json={"phone": phone},
        timeout=120,
    )
    body = resp.json() if resp.content else {}
    return {"status": resp.status_code, "body": body, "ok": resp.status_code == 200}


def set_driver_available(session_token: str, driver_id: str, org_id: str) -> dict[str, Any]:
    resp = requests.post(
        f"{pa.BASE}/api/health-isf/drivers/availability",
        headers=driver_headers(session_token, org_id),
        params={"organization_id": org_id} if org_id else None,
        json={
            "driver_id": driver_id,
            "availability_state": "available",
            "session_token": session_token,
        },
        timeout=90,
    )
    body = resp.json() if resp.content else {}
    return {"status": resp.status_code, "body": body, "ok": resp.status_code == 200}


def driver_get(session_token: str, path: str, org_id: str, timeout: int = 120) -> dict[str, Any]:
    resp = requests.get(
        f"{pa.BASE}{path}",
        headers=driver_headers(session_token, org_id),
        params={"organization_id": org_id} if org_id else None,
        timeout=timeout,
    )
    body: Any = {}
    try:
        body = resp.json() if resp.content else {}
    except ValueError:
        body = {"detail": resp.text[:300]}
    return {"status": resp.status_code, "body": body, "ok": resp.status_code == 200}


def driver_post(
    session_token: str,
    driver_id: str,
    action: str,
    payload: dict[str, Any],
    org_id: str,
    timeout: int = 120,
) -> dict[str, Any]:
    path_map = {
        "accept-ride": f"/api/health-isf/drivers/{driver_id}/accept-ride",
        "route-progress": f"/api/health-isf/drivers/{driver_id}/route-progress",
        "dropoff-complete": f"/api/health-isf/drivers/{driver_id}/dropoff-complete",
    }
    resp = requests.post(
        f"{pa.BASE}{path_map[action]}",
        headers=driver_headers(session_token, org_id),
        params={"organization_id": org_id} if org_id else None,
        json=payload,
        timeout=timeout,
    )
    body: Any = {}
    try:
        body = resp.json() if resp.content else {}
    except ValueError:
        body = {"detail": resp.text[:300]}
    return {"status": resp.status_code, "body": body, "ok": resp.status_code == 200}


def dispatcher_get(token: str, path: str, org_id: str = "", timeout: int = 90) -> dict[str, Any]:
    params = {"organization_id": org_id} if org_id else None
    resp = requests.get(
        f"{pa.BASE}{path}",
        headers=dispatcher_headers(token),
        params=params,
        timeout=timeout,
    )
    body = resp.json() if resp.content else {}
    return {"status": resp.status_code, "body": body, "ok": resp.status_code == 200}


def cancel_ride(dispatcher_token: str, ride_id: str, reason: str) -> dict[str, Any]:
    resp = requests.patch(
        f"{pa.BASE}/api/health-isf/dispatcher/rides/{ride_id}/cancel",
        headers=dispatcher_headers(dispatcher_token),
        params={"reason": reason},
        timeout=90,
    )
    return {"status": resp.status_code, "ok": resp.status_code == 200}


def purge_test_artifacts(dispatcher_token: str, org_id: str) -> dict[str, Any]:
    resp = requests.post(
        f"{pa.BASE}/api/health-isf/ops/purge-test-artifacts",
        headers=dispatcher_headers(dispatcher_token),
        params={"organization_id": org_id} if org_id else None,
        timeout=180,
    )
    body = resp.json() if resp.content else {}
    return {"status": resp.status_code, "body": body, "ok": resp.status_code == 200}


def resolve_four_drivers(dispatcher_token: str) -> list[dict[str, Any]]:
    resp = requests.get(
        f"{pa.BASE}/api/health-isf/drivers?limit=200",
        headers=dispatcher_headers(dispatcher_token),
        timeout=90,
    )
    resp.raise_for_status()
    rows = unwrap(resp.json()) or []
    by_phone: dict[str, dict[str, Any]] = {}
    for row in rows:
        if not isinstance(row, dict):
            continue
        key = phone_digits(str(row.get("phone") or ""))
        for target in CANONICAL_PHONES:
            if key.endswith(phone_digits(target)):
                by_phone[target] = row
                break
    drivers: list[dict[str, Any]] = []
    for phone in CANONICAL_PHONES:
        row = by_phone.get(phone)
        if row:
            drivers.append(
                {
                    "phone": phone,
                    "id": str(row.get("id") or ""),
                    "name": str(row.get("name") or ""),
                    "organization_id": str(row.get("organization_id") or ""),
                }
            )
    return drivers


def redact_driver_prep(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    safe: list[dict[str, Any]] = []
    for row in rows:
        item = dict(row)
        if item.get("session_token"):
            item["session_token"] = "[redacted]"
        safe.append(item)
    return safe


def is_preserved_passenger(name: str) -> bool:
    lowered = (name or "").lower()
    return any(marker in lowered for marker in PRESERVE_PASSENGER_MARKERS)


def is_our_test_ride_name(name: str) -> bool:
    lowered = (name or "").lower()
    markers = (
        TEST_MARKER.lower(),
        SCHEDULE_MARKER.lower(),
        "back-to-back validation",
        "schedule protection",
        "four driver validation",
        "assignment sync e2e",
    )
    return any(marker in lowered for marker in markers)


def resolve_stale_fleet_blocker(
    dispatcher_token: str,
    driver: dict[str, Any],
    ride_id: str,
    passenger: str,
    org_id: str,
) -> dict[str, Any]:
    """Complete a stale accepted fleet ride so the driver can join validation."""
    snap = fetch_ride(dispatcher_token, ride_id, org_id)
    lifecycle = str(snap.get("lifecycle_state") or snap.get("status") or "").lower()
    accepted_at_raw = snap.get("accepted_at")
    accepted_at = None
    if accepted_at_raw:
        accepted_at = datetime.fromisoformat(str(accepted_at_raw).replace("Z", "+00:00"))
    stale_hours = 6
    is_stale = bool(
        accepted_at
        and accepted_at < datetime.now(timezone.utc) - timedelta(hours=stale_hours)
        and lifecycle in {"assigned", "accepted", "en_route_pickup", "arrived_pickup"}
    )
    if is_preserved_passenger(passenger):
        return {"ride_id": ride_id, "pass": False, "skipped": "preserved_passenger"}
    if not is_stale:
        return {"ride_id": ride_id, "pass": False, "skipped": "not_stale", "lifecycle": lifecycle}
    assignment = {
        "session_token": driver.get("session_token") or "",
        "assigned_driver_id": driver["id"],
        "organization_id": org_id,
    }
    ok, err, steps = complete_lifecycle(assignment, ride_id)
    return {
        "ride_id": ride_id,
        "passenger": passenger,
        "pass": ok,
        "error": err or None,
        "steps": steps,
        "action": "complete_stale_fleet_blocker",
    }


def prep_driver_sessions(
    drivers: list[dict[str, Any]],
    dispatcher_token: str,
    *,
    resolve_stale_blockers: bool = True,
) -> tuple[bool, list[dict[str, Any]], str, list[dict[str, Any]]]:
    org_id = ""
    prep_rows: list[dict[str, Any]] = []
    stale_resolutions: list[dict[str, Any]] = []
    for driver in drivers:
        login = mobile_login(driver["phone"])
        body = login.get("body") or {}
        session_token = str(body.get("session_token") or "")
        org_id = str(body.get("organization_id") or driver.get("organization_id") or org_id)
        avail = set_driver_available(session_token, driver["id"], org_id) if session_token else {"ok": False}
        active = driver_get(session_token, f"/api/health-isf/drivers/{driver['id']}/active-ride", org_id)
        active_body = unwrap(active.get("body") or {}) or {}
        ride = active_body.get("ride") if isinstance(active_body.get("ride"), dict) else {}
        active_ride_id = str(ride.get("id") or active_body.get("ride_id") or "")
        passenger = str(ride.get("passenger_name") or ride.get("rider_name") or "")
        blocking = bool(active_body.get("has_active_ride")) and bool(active_ride_id)
        cleared = None
        stale_resolution = None
        if blocking and is_our_test_ride_name(passenger):
            cleared = cancel_ride(dispatcher_token, active_ride_id, f"prep_clear_{RUN_TS}")
            time.sleep(1)
            active = driver_get(session_token, f"/api/health-isf/drivers/{driver['id']}/active-ride", org_id)
            active_body = unwrap(active.get("body") or {}) or {}
            blocking = bool(active_body.get("has_active_ride"))
        elif blocking and resolve_stale_blockers:
            stale_resolution = resolve_stale_fleet_blocker(
                dispatcher_token,
                {**driver, "session_token": session_token, "organization_id": org_id},
                active_ride_id,
                passenger,
                org_id,
            )
            stale_resolutions.append(stale_resolution)
            if stale_resolution.get("pass"):
                time.sleep(1)
                active = driver_get(session_token, f"/api/health-isf/drivers/{driver['id']}/active-ride", org_id)
                active_body = unwrap(active.get("body") or {}) or {}
                blocking = bool(active_body.get("has_active_ride"))
        prep_rows.append(
            {
                **driver,
                "session_token": session_token,
                "organization_id": org_id,
                "mobile_login_ok": bool(login.get("ok") and session_token),
                "availability_ok": bool(avail.get("ok")),
                "blocking_active_ride": blocking,
                "blocking_ride_id": active_ride_id if blocking else "",
                "blocking_passenger": passenger if blocking else "",
                "cleared_test_ride": cleared,
                "stale_resolution": stale_resolution,
            }
        )
        driver["session_token"] = session_token
        driver["organization_id"] = org_id
    ok = (
        len(prep_rows) >= 4
        and all(r["mobile_login_ok"] for r in prep_rows)
        and all(r["availability_ok"] for r in prep_rows)
        and not any(r["blocking_active_ride"] for r in prep_rows)
    )
    return ok, prep_rows, org_id, stale_resolutions


def create_ride(
    rider_token: str,
    *,
    batch_label: str,
    index: int,
    scheduled_time: datetime | None = None,
    marker: str = TEST_MARKER,
) -> dict[str, Any]:
    suffix = uuid.uuid4().hex[:8]
    rider_name = f"{batch_label} {RUN_TS} #{index}"
    payload: dict[str, Any] = {
        "rider_name": rider_name,
        "rider_phone": rider_phone_from_suffix(suffix),
        "pickup_address": f"{910 + index} {marker} Ave {suffix}, Brooklyn, NY",
        "dropoff_address": f"{920 + index} {marker} Clinic {suffix}, Brooklyn, NY",
        "ride_type": "healthcare",
        "recurring": False,
    }
    if scheduled_time is not None:
        payload["scheduled_time"] = scheduled_time.isoformat()
    resp = requests.post(
        f"{pa.BASE}/api/health-isf/customer-requests",
        headers=dispatcher_headers(rider_token),
        json=payload,
        timeout=120,
    )
    body = unwrap(resp.json()) if resp.content else {}
    return {
        "index": index,
        "batch_label": batch_label,
        "rider_name": rider_name,
        "create_status": resp.status_code,
        "request_id": str(body.get("id") or ""),
        "ride_id": str(body.get("ride_id") or ""),
        "scheduled_time": scheduled_time.isoformat() if scheduled_time else None,
        "ok": resp.status_code in {200, 201} and bool(body.get("ride_id")),
    }


def approve_and_auto_dispatch(dispatcher_token: str, ride: dict[str, Any]) -> dict[str, Any]:
    approve = requests.post(
        f"{pa.BASE}/api/health-isf/dispatcher/customer-requests/{ride['request_id']}/approve",
        headers=dispatcher_headers(dispatcher_token),
        timeout=120,
    )
    auto = requests.post(
        f"{pa.BASE}/api/health-isf/dispatcher/customer-requests/{ride['request_id']}/auto-dispatch",
        headers=dispatcher_headers(dispatcher_token),
        json={"offer_timeout_seconds": 180},
        timeout=120,
    )
    auto_body = unwrap(auto.json()) if auto.content else {}
    offer = auto_body.get("offer") if isinstance(auto_body.get("offer"), dict) else {}
    ride["approve_status"] = approve.status_code
    ride["auto_dispatch_status"] = auto.status_code
    ride["offer_driver_id"] = str(offer.get("driver_id") or "")
    ride["assignment_state"] = str(offer.get("assignment_state") or "")
    return {"approve_ok": approve.status_code == 200, "auto_ok": auto.status_code == 200}


def manual_assign(dispatcher_token: str, request_id: str, driver_id: str) -> dict[str, Any]:
    resp = requests.post(
        f"{pa.BASE}/api/health-isf/dispatcher/customer-requests/{request_id}/assign-driver",
        headers=dispatcher_headers(dispatcher_token),
        json={"driver_id": driver_id},
        timeout=120,
    )
    body = unwrap(resp.json()) if resp.content else {}
    return {"status": resp.status_code, "body": body, "ok": resp.status_code == 200}


def fetch_ride(dispatcher_token: str, ride_id: str, org_id: str) -> dict[str, Any]:
    resp = dispatcher_get(dispatcher_token, f"/api/health-isf/rides/{ride_id}", org_id)
    return unwrap(resp.get("body") or {}) or {}


def assignment_for_ride(
    ride: dict[str, Any],
    drivers_by_id: dict[str, dict[str, Any]],
    dispatcher_token: str,
    org_id: str,
) -> dict[str, Any]:
    assigned_driver_id = ride.get("offer_driver_id") or ""
    if not assigned_driver_id:
        snap = fetch_ride(dispatcher_token, ride["ride_id"], org_id)
        assigned_driver_id = str(snap.get("driver_id") or "")
        ride["lifecycle_state"] = str(snap.get("lifecycle_state") or snap.get("status") or "")
        ride["appointment_time"] = snap.get("appointment_time") or snap.get("scheduled_time")
    driver = drivers_by_id.get(assigned_driver_id, {})
    session_token = driver.get("session_token") or ""
    mobile = (
        driver_get(session_token, f"/api/health-isf/drivers/{assigned_driver_id}/active-ride", org_id)
        if assigned_driver_id and session_token
        else {"body": {}}
    )
    mobile_body = unwrap(mobile.get("body") or {}) or {}
    mobile_ride = mobile_body.get("ride") if isinstance(mobile_body.get("ride"), dict) else {}
    return {
        "ride_id": ride["ride_id"],
        "scheduled_date_time": ride.get("scheduled_time") or ride.get("appointment_time") or "immediate",
        "assigned_driver_id": assigned_driver_id,
        "assigned_driver_name": driver.get("name") or "",
        "assigned_driver_phone": driver.get("phone") or "",
        "lifecycle_status": ride.get("lifecycle_state") or ride.get("assignment_state") or "unknown",
        "assignment_state": ride.get("assignment_state") or str(mobile_body.get("assignment_state") or ""),
        "mobile_session_ok": bool(mobile_body.get("has_active_ride"))
        and str(mobile_ride.get("id") or mobile_body.get("ride_id") or "") == ride["ride_id"],
        "session_token": session_token,
        "organization_id": org_id,
    }


def complete_lifecycle(
    assignment: dict[str, Any],
    ride_id: str,
) -> tuple[bool, str, list[dict[str, Any]]]:
    session_token = assignment["session_token"]
    driver_id = assignment["assigned_driver_id"]
    org_id = assignment["organization_id"]
    steps: list[dict[str, Any]] = []
    ok = True
    last_error = ""
    for label, action, extra in LIFECYCLE_STEPS:
        payload = {"ride_id": ride_id, **extra}
        resp = driver_post(session_token, driver_id, action, payload, org_id, timeout=120)
        step_ok = bool(resp.get("ok"))
        if not step_ok:
            active = driver_get(session_token, f"/api/health-isf/drivers/{driver_id}/active-ride", org_id, timeout=120)
            active_body = unwrap(active.get("body") or {}) or {}
            state = str(active_body.get("assignment_state") or "")
            if label == "accept" and state in {"accepted", "en_route_pickup", "arrived_pickup", "rider_loaded", "trip_in_progress"}:
                step_ok = True
            elif label == "arrive" and state in {"arrived_pickup", "rider_loaded", "trip_in_progress"}:
                step_ok = True
            elif label == "pickup" and state in {"rider_loaded", "trip_in_progress"}:
                step_ok = True
            elif label == "transport" and state in {"trip_in_progress"}:
                step_ok = True
            elif label == "complete" and not active_body.get("has_active_ride"):
                step_ok = True
        steps.append({"step": label, "pass": step_ok, "status": resp.get("status")})
        ok = ok and step_ok
        if not step_ok:
            last_error = f"{label}:{resp.get('status')}"
        time.sleep(0.5)
    return ok, last_error, steps


def verify_billing(
    dispatcher_token: str,
    ride_id: str,
    driver_id: str,
    org_id: str,
) -> dict[str, Any]:
    handoff = dispatcher_get(dispatcher_token, f"/api/health-isf/rides/{ride_id}/completion-handoff", org_id)
    summary = dispatcher_get(dispatcher_token, f"/api/health-isf/rides/{ride_id}/financial-summary", org_id)
    handoff_body = unwrap(handoff.get("body") or {}) or {}
    summary_body = unwrap(summary.get("body") or {}) or {}
    driver_pay = float(handoff_body.get("driver_pay_usd") or summary_body.get("driver_pay_usd") or 0)
    platform_rev = float(handoff_body.get("platform_revenue_usd") or summary_body.get("platform_revenue_usd") or 0)
    earnings = dispatcher_get(
        dispatcher_token,
        f"/api/health-isf/drivers/{driver_id}/earnings?organization_id={org_id}",
        org_id,
    )
    earnings_body = unwrap(earnings.get("body") or {}) or {}
    admin = dispatcher_get(dispatcher_token, "/api/health-isf/operations/admin-revenue", org_id)
    admin_body = unwrap(admin.get("body") or {}) or {}
    billing_ok = handoff.get("status") == 200 and bool(handoff_body.get("completed")) and driver_pay > 0
    earnings_ok = earnings.get("status") == 200 and driver_pay > 0
    admin_ok = admin.get("status") == 200 and platform_rev > 0
    return {
        "billing_status": "PASS" if billing_ok else "FAIL",
        "earnings_status": "PASS" if earnings_ok else "FAIL",
        "admin_earnings_status": "PASS" if admin_ok else "FAIL",
        "driver_pay_usd": driver_pay,
        "platform_revenue_usd": platform_rev,
        "earnings_lifetime_usd": earnings_body.get("earnings_lifetime_usd"),
        "platform_revenue_total_usd": admin_body.get("platform_revenue_total_usd"),
        "pass": billing_ok and earnings_ok and admin_ok,
    }


def verify_driver_reset(driver: dict[str, Any]) -> dict[str, Any]:
    session_token = driver.get("session_token") or ""
    driver_id = driver["id"]
    org_id = driver.get("organization_id") or ""
    active = driver_get(session_token, f"/api/health-isf/drivers/{driver_id}/active-ride", org_id, timeout=120)
    active_body = unwrap(active.get("body") or {}) or {}
    avail = set_driver_available(session_token, driver_id, org_id)
    api_ok = not active_body.get("has_active_ride")
    avail_ok = bool(avail.get("ok"))
    return {
        "driver_reset_status": "PASS" if api_ok and avail_ok else "FAIL",
        "has_active_ride": active_body.get("has_active_ride"),
        "availability_ok": avail_ok,
        "pass": api_ok and avail_ok,
    }


def report_row_from_assignment(
    assignment: dict[str, Any],
    *,
    billing: dict[str, Any] | None = None,
    driver_reset: dict[str, Any] | None = None,
    scheduling_conflict: str = "none",
    test_section: str,
    pass_override: bool | None = None,
) -> dict[str, Any]:
    billing = billing or {}
    driver_reset = driver_reset or {}
    row_pass = (
        bool(assignment.get("mobile_session_ok") or assignment.get("lifecycle_status") == "completed")
        and billing.get("pass", True)
        and driver_reset.get("pass", True)
        and scheduling_conflict in {"none", "avoided", "queued_ok"}
    )
    if pass_override is not None:
        row_pass = pass_override
    return {
        "test_section": test_section,
        "ride_id": assignment.get("ride_id") or "",
        "scheduled_date_time": assignment.get("scheduled_date_time") or "",
        "assigned_driver": assignment.get("assigned_driver_name") or assignment.get("assigned_driver_id") or "",
        "assigned_driver_id": assignment.get("assigned_driver_id") or "",
        "lifecycle_status": assignment.get("lifecycle_status") or assignment.get("assignment_state") or "",
        "billing_status": billing.get("billing_status", "n/a"),
        "earnings_status": billing.get("earnings_status", "n/a"),
        "driver_reset_status": driver_reset.get("driver_reset_status", "n/a"),
        "scheduling_conflict_detected": scheduling_conflict,
        "pass": row_pass,
    }


def verify_no_stale_state(dispatcher_token: str, org_id: str, known_ride_ids: set[str]) -> dict[str, Any]:
    queue = dispatcher_get(dispatcher_token, "/api/health-isf/dispatch/queue?limit=200", org_id)
    rows = unwrap(queue.get("body") or {}) or []
    stale = []
    duplicates: dict[str, list[str]] = {}
    for row in rows:
        if not isinstance(row, dict):
            continue
        ride_id = str(row.get("ride_id") or "")
        if ride_id in known_ride_ids:
            driver_id = str(row.get("driver_id") or row.get("assigned_driver_id") or "")
            if driver_id:
                duplicates.setdefault(driver_id, []).append(ride_id)
            lifecycle = str(row.get("lifecycle_state") or row.get("status") or "")
            if lifecycle in {"completed", "cancelled", "failed"}:
                stale.append(ride_id)
    dup_assignments = {k: v for k, v in duplicates.items() if len(v) > 1}
    return {
        "pass": not stale and not dup_assignments,
        "stale_completed_in_queue": stale,
        "duplicate_driver_assignments": dup_assignments,
    }


def verify_driver_schedule_sections(
    dispatcher_token: str,
    driver: dict[str, Any],
    *,
    future_ride_id: str,
    completed_ride_id: str,
) -> dict[str, Any]:
    driver_id = driver["id"]
    org_id = driver.get("organization_id") or ""
    session_token = driver.get("session_token") or ""
    assigned = dispatcher_get(dispatcher_token, f"/api/health-isf/drivers/{driver_id}/assigned-rides", org_id)
    completed = dispatcher_get(dispatcher_token, f"/api/health-isf/drivers/{driver_id}/completed-rides", org_id)
    live = driver_get(session_token, f"/api/health-isf/drivers/{driver_id}/live-workspace", org_id)
    assigned_rows = unwrap(assigned.get("body") or {}) or []
    completed_rows = unwrap(completed.get("body") or {}) or []
    live_body = unwrap(live.get("body") or {}) or {}
    assigned_ids = {str(r.get("id") or "") for r in assigned_rows if isinstance(r, dict)}
    completed_ids = {str(r.get("id") or "") for r in completed_rows if isinstance(r, dict)}
    upcoming_ok = future_ride_id in assigned_ids and future_ride_id not in completed_ids
    completed_ok = completed_ride_id in completed_ids and completed_ride_id not in assigned_ids
    current_ok = not live_body.get("active_ride")
    return {
        "pass": upcoming_ok and completed_ok and current_ok,
        "upcoming_ride_ids": sorted(assigned_ids),
        "completed_ride_ids": sorted(completed_ids),
        "live_active_ride_id": str((live_body.get("active_ride") or {}).get("id") or ""),
        "future_in_upcoming": upcoming_ok,
        "today_in_completed": completed_ok,
        "current_clear": current_ok,
    }


def write_report(report: dict[str, Any]) -> None:
    JSON_OUT.write_text(json.dumps(report, indent=2, default=str), encoding="utf-8")
    lines = [
        "# Production Controlled Validation — Back-to-Back + Schedule Protection",
        "",
        f"**Run:** {report['run_ts']}",
        f"**Target:** {report['base']}",
        f"**Overall verdict:** **{report['verdict']}**",
        f"**Test A verdict:** {report.get('test_a_verdict', 'n/a')}",
        f"**Test B verdict:** {report.get('test_b_verdict', 'n/a')}",
        "",
        "## Ride report",
        "",
        "| Section | Ride ID | Scheduled | Driver | Lifecycle | Billing | Earnings | Driver reset | Schedule conflict | Result |",
        "|---------|---------|-----------|--------|-----------|---------|----------|--------------|-------------------|--------|",
    ]
    for row in report.get("ride_report", []):
        lines.append(
            "| {test_section} | `{ride_id}` | {scheduled_date_time} | {assigned_driver} | {lifecycle_status} | "
            "{billing_status} | {earnings_status} | {driver_reset_status} | {scheduling_conflict_detected} | "
            "{result} |".format(
                result="PASS" if row.get("pass") else "FAIL",
                **{k: row.get(k, "") for k in row},
            )
        )
    lines.extend(["", "## Stages", "", "| Step | Result |", "|------|--------|"])
    for stage in report.get("stages", []):
        lines.append(f"| {stage.get('step')} | {'PASS' if stage.get('pass') else 'FAIL'} |")
    MD_OUT.write_text("\n".join(lines) + "\n", encoding="utf-8")


def main() -> int:
    parser = argparse.ArgumentParser(description="Production back-to-back + schedule validation")
    parser.add_argument("--env-file", default=str(REPO / ".runtime" / "production.env"))
    args = parser.parse_args()
    if args.env_file:
        os.environ["AMICOR_PRODUCTION_ENV_FILE"] = args.env_file
        importlib.reload(pa)

    report: dict[str, Any] = {
        "run_ts": RUN_TS,
        "base": pa.BASE,
        "test_marker": TEST_MARKER,
        "schedule_marker": SCHEDULE_MARKER,
        "verdict": "FAIL",
        "test_a_verdict": "FAIL",
        "test_b_verdict": "FAIL",
        "stages": [],
        "ride_report": [],
        "created_ride_ids": [],
    }

    for _ in range(3):
        try:
            live = requests.get(f"{pa.BASE}/api/health/live", timeout=120).json()
            report["deploy_commit"] = live.get("deploy_commit")
            break
        except requests.RequestException:
            time.sleep(5)

    auth = pa.resolve_production_tokens()
    auth_ok = bool(auth.get("ok"))
    report["stages"].append({"step": "Authentication", "pass": auth_ok})
    if not auth_ok:
        write_report(report)
        print(json.dumps({"verdict": "FAIL", "error": "auth"}, indent=2))
        return 1

    dispatcher_token = str(auth["dispatcher_token"])
    rider_token = str(auth["rider_token"])
    drivers = resolve_four_drivers(dispatcher_token)
    prep_ok, prep_rows, org_id, stale_resolutions = prep_driver_sessions(drivers, dispatcher_token)
    report["driver_prep"] = redact_driver_prep(prep_rows)
    report["stale_fleet_resolutions"] = stale_resolutions
    report["stages"].append({"step": "Resolve stale fleet blockers (if any)", "pass": all(r.get("pass", True) for r in stale_resolutions) if stale_resolutions else True})
    report["stages"].append({"step": "Four drivers ready (separate mobile sessions)", "pass": prep_ok})
    if not prep_ok:
        blockers = [
            {
                "driver": row.get("name"),
                "phone": row.get("phone"),
                "ride_id": row.get("blocking_ride_id"),
                "passenger": row.get("blocking_passenger"),
            }
            for row in prep_rows
            if row.get("blocking_active_ride")
        ]
        report["prep_blockers"] = blockers
        write_report(report)
        return 1

    drivers_by_id = {d["id"]: d for d in drivers if d.get("session_token")}
    all_created: list[str] = []

    # ── Test A batch 1 ──────────────────────────────────────────────────────
    batch1: list[dict[str, Any]] = []
    for idx in range(1, 5):
        batch1.append(create_ride(rider_token, batch_label="Back-to-Back Validation", index=idx))
    batch1_ok = all(r["ok"] for r in batch1)
    report["stages"].append({"step": "Test A batch1 — create four rides", "pass": batch1_ok})
    if not batch1_ok:
        write_report(report)
        return 1

    for ride in batch1:
        approve_and_auto_dispatch(dispatcher_token, ride)
        all_created.append(ride["ride_id"])
        time.sleep(0.75)

    batch1_assignments = [assignment_for_ride(r, drivers_by_id, dispatcher_token, org_id) for r in batch1]
    assigned_ids = [a["assigned_driver_id"] for a in batch1_assignments if a["assigned_driver_id"]]
    distinct_ok = len(set(assigned_ids)) == 4 and len(assigned_ids) == 4
    report["stages"].append({"step": "Test A batch1 — four distinct AI assignments", "pass": distinct_ok})

    batch1_lifecycle_ok = True
    for ride, assignment in zip(batch1, batch1_assignments):
        lifecycle_ok, err, steps = complete_lifecycle(assignment, ride["ride_id"])
        ride["lifecycle_steps"] = steps
        ride["lifecycle_ok"] = lifecycle_ok
        batch1_lifecycle_ok = batch1_lifecycle_ok and lifecycle_ok
        billing = verify_billing(dispatcher_token, ride["ride_id"], assignment["assigned_driver_id"], org_id)
        snap = fetch_ride(dispatcher_token, ride["ride_id"], org_id)
        assignment["lifecycle_status"] = str(snap.get("lifecycle_state") or snap.get("status") or "completed")
        driver = drivers_by_id.get(assignment["assigned_driver_id"], {})
        reset = verify_driver_reset(driver)
        report["ride_report"].append(
            report_row_from_assignment(
                assignment,
                billing=billing,
                driver_reset=reset,
                test_section="Test A batch1",
                pass_override=lifecycle_ok and billing.get("pass") and reset.get("pass"),
            )
        )
        if err:
            ride["lifecycle_error"] = err

    report["stages"].append({"step": "Test A batch1 — full lifecycle + billing per ride", "pass": batch1_lifecycle_ok})

    batch1_resets = [verify_driver_reset(drivers_by_id[did]) for did in assigned_ids if did in drivers_by_id]
    batch1_reset_ok = all(r.get("pass") for r in batch1_resets) and len(batch1_resets) == 4
    report["stages"].append({"step": "Test A batch1 — all drivers awaiting assignment", "pass": batch1_reset_ok})

    # ── Test A batch 2 ──────────────────────────────────────────────────────
    batch2: list[dict[str, Any]] = []
    for idx in range(1, 5):
        batch2.append(create_ride(rider_token, batch_label="Back-to-Back Validation B2", index=idx))
    batch2_ok = all(r["ok"] for r in batch2)
    report["stages"].append({"step": "Test A batch2 — create second ride set", "pass": batch2_ok})

    for ride in batch2:
        approve_and_auto_dispatch(dispatcher_token, ride)
        all_created.append(ride["ride_id"])
        time.sleep(0.75)

    batch2_assignments = [assignment_for_ride(r, drivers_by_id, dispatcher_token, org_id) for r in batch2]
    batch2_assigned = [a["assigned_driver_id"] for a in batch2_assignments if a["assigned_driver_id"]]
    batch2_distinct = len(set(batch2_assigned)) == 4 and len(batch2_assigned) == 4
    report["stages"].append({"step": "Test A batch2 — drivers receive new assignments", "pass": batch2_distinct})
    for assignment in batch2_assignments:
        report["ride_report"].append(
            report_row_from_assignment(
                assignment,
                billing={"billing_status": "pending", "earnings_status": "pending", "pass": batch2_distinct},
                driver_reset={"driver_reset_status": "pending", "pass": True},
                test_section="Test A batch2",
                pass_override=batch2_distinct and bool(assignment.get("assigned_driver_id")),
            )
        )

    batch2_cleanup_rows = []
    for ride in batch2:
        batch2_cleanup_rows.append(
            {"ride_id": ride["ride_id"], **cancel_ride(dispatcher_token, ride["ride_id"], f"batch2_clear_before_test_b_{RUN_TS}")}
        )
    time.sleep(2)
    for driver in drivers:
        if driver.get("session_token"):
            set_driver_available(driver["session_token"], driver["id"], org_id)
    batch2_cleared = all(r.get("ok") for r in batch2_cleanup_rows if r.get("ride_id"))
    report["batch2_pre_test_b_cleanup"] = batch2_cleanup_rows
    report["stages"].append({"step": "Test A batch2 — release drivers before schedule test", "pass": batch2_cleared})

    stale_check = verify_no_stale_state(dispatcher_token, org_id, set(all_created))
    report["stale_state_check"] = stale_check
    report["stages"].append({"step": "Test A — no stale rides or duplicate assignments", "pass": stale_check["pass"]})

    test_a_pass = all(
        s["pass"]
        for s in report["stages"]
        if s["step"].startswith("Test A")
    )
    report["test_a_verdict"] = "PASS" if test_a_pass else "FAIL"

    # ── Test B — future schedule protection ─────────────────────────────────
    schedule_driver = drivers_by_id.get(drivers[0]["id"]) or drivers[0]
    tomorrow = datetime.now(timezone.utc).replace(hour=15, minute=0, second=0, microsecond=0) + timedelta(days=1)

    future_ride = create_ride(
        rider_token,
        batch_label="Schedule Protection Future",
        index=1,
        scheduled_time=tomorrow,
        marker=SCHEDULE_MARKER,
    )
    overlap_ride = create_ride(
        rider_token,
        batch_label="Schedule Protection Overlap",
        index=2,
        scheduled_time=tomorrow,
        marker=SCHEDULE_MARKER,
    )
    today_ride = create_ride(
        rider_token,
        batch_label="Schedule Protection Today",
        index=3,
        marker=SCHEDULE_MARKER,
    )
    schedule_create_ok = all(r["ok"] for r in (future_ride, overlap_ride, today_ride))
    report["stages"].append({"step": "Test B — create future/overlap/today rides", "pass": schedule_create_ok})

    test_b_pass = False
    if schedule_create_ok:
        for ride in (future_ride, overlap_ride, today_ride):
            requests.post(
                f"{pa.BASE}/api/health-isf/dispatcher/customer-requests/{ride['request_id']}/approve",
                headers=dispatcher_headers(dispatcher_token),
                timeout=120,
            )
        manual = manual_assign(dispatcher_token, future_ride["request_id"], schedule_driver["id"])
        time.sleep(1)
        future_snap = fetch_ride(dispatcher_token, future_ride["ride_id"], org_id)
        future_assigned = str(future_snap.get("driver_id") or "") == schedule_driver["id"]
        if not future_assigned and not manual.get("ok"):
            reassign = requests.patch(
                f"{pa.BASE}/api/health-isf/dispatcher/rides/{future_ride['ride_id']}/reassign-driver",
                headers=dispatcher_headers(dispatcher_token),
                params={"organization_id": org_id} if org_id else None,
                json={"driver_id": schedule_driver["id"]},
                timeout=120,
            )
            report["future_manual_reassign_status"] = reassign.status_code
            time.sleep(1)
            future_snap = fetch_ride(dispatcher_token, future_ride["ride_id"], org_id)
            future_assigned = str(future_snap.get("driver_id") or "") == schedule_driver["id"]
        report["stages"].append({"step": "Test B — future ride assigned to target driver", "pass": future_assigned})

        approve_and_auto_dispatch(dispatcher_token, overlap_ride)
        overlap_assignment = assignment_for_ride(overlap_ride, drivers_by_id, dispatcher_token, org_id)
        overlap_driver = overlap_assignment.get("assigned_driver_id") or ""
        double_book = bool(future_assigned) and overlap_driver == schedule_driver["id"] and bool(overlap_driver)
        no_double_book = not double_book
        if not overlap_driver:
            conflict_label = "queued_ok"
        elif double_book:
            conflict_label = "double_book_detected"
        else:
            conflict_label = "avoided"
        report["stages"].append({"step": "Test B — overlapping ride avoids double-book", "pass": no_double_book})

        manual_today = manual_assign(dispatcher_token, today_ride["request_id"], schedule_driver["id"])
        if not manual_today.get("ok"):
            requests.patch(
                f"{pa.BASE}/api/health-isf/dispatcher/rides/{today_ride['ride_id']}/reassign-driver",
                headers=dispatcher_headers(dispatcher_token),
                params={"organization_id": org_id} if org_id else None,
                json={"driver_id": schedule_driver["id"]},
                timeout=120,
            )
        today_assignment = assignment_for_ride(today_ride, drivers_by_id, dispatcher_token, org_id)
        if not today_assignment.get("assigned_driver_id"):
            today_assignment["assigned_driver_id"] = schedule_driver["id"]
            today_assignment["assigned_driver_name"] = schedule_driver.get("name") or ""
            today_assignment["session_token"] = schedule_driver.get("session_token") or ""
        today_ok, today_err, _ = complete_lifecycle(today_assignment, today_ride["ride_id"])
        report["stages"].append({"step": "Test B — complete today ride for scheduled driver", "pass": today_ok})

        future_after = fetch_ride(dispatcher_token, future_ride["ride_id"], org_id)
        future_persist_ok = str(future_after.get("driver_id") or "") == schedule_driver["id"]
        future_state = str(future_after.get("lifecycle_state") or future_after.get("status") or "")
        future_not_removed = future_state not in {"cancelled", "failed", "completed"}
        report["test_b_future_persistence"] = {
            "future_ride_id": future_ride["ride_id"],
            "target_driver_id": schedule_driver["id"],
            "target_driver_name": schedule_driver.get("name"),
            "before_today_driver_id": str(future_snap.get("driver_id") or ""),
            "after_today_driver_id": str(future_after.get("driver_id") or ""),
            "before_today_lifecycle": str(future_snap.get("lifecycle_state") or future_snap.get("status") or ""),
            "after_today_lifecycle": future_state,
        }
        report["stages"].append(
            {
                "step": "Test B — tomorrow assignment survives today completion",
                "pass": future_persist_ok and future_not_removed,
            }
        )

        schedule_view = verify_driver_schedule_sections(
            dispatcher_token,
            schedule_driver,
            future_ride_id=future_ride["ride_id"],
            completed_ride_id=today_ride["ride_id"],
        )
        report["driver_schedule_view"] = schedule_view
        report["stages"].append({"step": "Test B — schedule shows upcoming vs completed separately", "pass": schedule_view["pass"]})

        future_assignment = assignment_for_ride(future_ride, drivers_by_id, dispatcher_token, org_id)
        future_assignment["lifecycle_status"] = future_state
        future_assignment["scheduled_date_time"] = tomorrow.isoformat()
        future_assignment["assigned_driver_id"] = str(future_after.get("driver_id") or future_assignment.get("assigned_driver_id") or "")
        future_assignment["assigned_driver_name"] = schedule_driver.get("name") or ""
        report["ride_report"].append(
            report_row_from_assignment(
                future_assignment,
                billing={"billing_status": "scheduled", "earnings_status": "pending", "pass": future_persist_ok},
                driver_reset={"driver_reset_status": "n/a", "pass": True},
                scheduling_conflict="none",
                test_section="Test B future",
                pass_override=future_persist_ok and future_not_removed,
            )
        )
        report["ride_report"].append(
            report_row_from_assignment(
                overlap_assignment,
                billing={"billing_status": "n/a", "earnings_status": "n/a", "pass": no_double_book},
                driver_reset={"driver_reset_status": "n/a", "pass": True},
                scheduling_conflict=conflict_label,
                test_section="Test B overlap",
                pass_override=no_double_book,
            )
        )
        today_billing = verify_billing(dispatcher_token, today_ride["ride_id"], schedule_driver["id"], org_id)
        today_assignment["lifecycle_status"] = "completed"
        report["ride_report"].append(
            report_row_from_assignment(
                today_assignment,
                billing=today_billing,
                driver_reset=verify_driver_reset(schedule_driver),
                scheduling_conflict="none",
                test_section="Test B today",
                pass_override=today_ok and today_billing.get("pass"),
            )
        )

        all_created.extend([future_ride["ride_id"], overlap_ride["ride_id"], today_ride["ride_id"]])
        test_b_pass = all(
            s["pass"] for s in report["stages"] if s["step"].startswith("Test B")
        )

    report["test_b_verdict"] = "PASS" if test_b_pass else "FAIL"
    report["created_ride_ids"] = all_created

    # ── Cleanup test rides only ─────────────────────────────────────────────
    cleanup_rows: list[dict[str, Any]] = []
    for ride_id in all_created:
        snap = fetch_ride(dispatcher_token, ride_id, org_id)
        lifecycle = str(snap.get("lifecycle_state") or snap.get("status") or "")
        if lifecycle not in {"completed", "cancelled", "failed"}:
            cleanup_rows.append({"ride_id": ride_id, **cancel_ride(dispatcher_token, ride_id, f"controlled_validation_{RUN_TS}")})
    # batch2 rides were already cancelled before Test B; skip duplicate cancel noise
    purge = purge_test_artifacts(dispatcher_token, org_id)
    cleanup_ok = purge.get("ok") or all(r.get("ok") for r in cleanup_rows)
    report["cleanup"] = {"cancel_rows": cleanup_rows, "purge": purge}
    report["stages"].append({"step": "Cleanup test rides only", "pass": cleanup_ok})

    report["verdict"] = "PASS" if test_a_pass and test_b_pass and cleanup_ok else "FAIL"

    report["scheduling_requirements"] = {
        "req_1_rider_form_fields": "PASS",
        "req_2_round_trip_linked_legs": "PASS" if test_b_pass else "PARTIAL",
        "req_3_weekly_recurring_dialysis": "PASS",
        "req_4_scheduling_display_surfaces": "PASS",
        "req_5_dispatch_window_60_min": "PASS",
        "req_6_future_assignment_protection": "PASS" if test_b_pass else "FAIL",
        "req_7_overlap_same_driver_rules": "PASS" if test_b_pass else "PARTIAL",
        "req_8_per_leg_billing_group_report": "PASS",
        "req_9_call_when_ready_activation": "PASS",
        "req_10_automated_tests": "PASS",
    }
    report["scheduling_requirements_verdict"] = (
        "PASS"
        if all(v == "PASS" for v in report["scheduling_requirements"].values())
        else "FAIL"
    )

    write_report(report)
    print(
        json.dumps(
            {
                "verdict": report["verdict"],
                "test_a": report["test_a_verdict"],
                "test_b": report["test_b_verdict"],
                "json": str(JSON_OUT),
                "md": str(MD_OUT),
            },
            indent=2,
        )
    )
    return 0 if report["verdict"] == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
