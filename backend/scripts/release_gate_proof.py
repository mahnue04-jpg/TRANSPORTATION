"""Release-gate browser + API proof for cross-surface ride synchronization."""
from __future__ import annotations

import json
import os
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

import httpx
from playwright.sync_api import sync_playwright

BACKEND = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BACKEND))

from app.auth import SEED_PASSWORD, ensure_auth_schema, seed_default_users
from app.db.session import SessionLocal
from app.helpers import uuid4
from app.modules.health_isf import service as hs
from app.modules.health_isf.models import (
    DispatchAssignmentState,
    DriverStatus,
    HealthISFBillingHandoff,
    HealthISFDispatchAssignment,
    HealthISFDriver,
    HealthISFPaymentTransaction,
    HealthISFRide,
    RideStatus,
)

ensure_auth_schema()
seed_default_users()

BASE = os.getenv("AMICOR_BROWSER_BASE", "http://127.0.0.1:8010")
PASSWORD = os.getenv("AMICOR_SEED_PASSWORD", SEED_PASSWORD)
ORG = "ca8d0c7c-1fff-4465-99d7-75a1fc51543e"
MARIA = "767627cb-a3f5-4e13-a32b-ad12570a8ec4"
ARTIFACT = BACKEND / "artifacts" / "release_gate_proof.json"


def log(msg: str) -> None:
    print(msg, flush=True)


def login(client: httpx.Client, email: str) -> str:
    r = client.post("/api/auth/login", json={"email": email, "password": PASSWORD})
    r.raise_for_status()
    return r.json()["access_token"]


def hdr(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


def cleanup_env() -> dict:
    counts = {"rides_closed": 0, "assignments_closed": 0}
    with SessionLocal() as db:
        now_ts = hs.now()
        for ride in db.query(HealthISFRide).filter(HealthISFRide.organization_id == ORG).all():
            if hs._ride_is_terminal(ride):
                continue
            ride.status = RideStatus.CANCELLED.value
            ride.lifecycle_state = RideStatus.CANCELLED.value
            ride.updated_at = now_ts
            counts["rides_closed"] += 1
            counts["assignments_closed"] += hs._close_active_assignments_for_ride(
                db,
                ride_id=str(ride.id),
                target_state=DispatchAssignmentState.DROPOFF_COMPLETE.value,
                reason="release_gate_cleanup",
            )
        for assignment in db.query(HealthISFDispatchAssignment).filter(
            HealthISFDispatchAssignment.organization_id == ORG,
            HealthISFDispatchAssignment.assignment_state.in_(list(hs.DRIVER_APP_ASSIGNMENT_STATES)),
        ).all():
            hs._close_dispatch_assignment_record(
                db,
                assignment,
                target_state=DispatchAssignmentState.DROPOFF_COMPLETE.value,
                reason="release_gate_cleanup",
            )
            counts["assignments_closed"] += 1
        maria = db.query(HealthISFDriver).filter(HealthISFDriver.id == MARIA).first()
        if maria:
            maria.status = DriverStatus.AVAILABLE
            maria.availability_state = "available"
            maria.is_online = True
            maria.auth_state = "active"
            maria.last_seen_at = now_ts
        db.commit()
    return counts


def capture_step(client: httpx.Client, token: str, ride_id: str, label: str) -> dict:
    queue = client.get("/api/health-isf/dispatch/queue", headers=hdr(token), params={"limit": 200}).json()
    active = client.get(
        "/api/health-isf/dispatch/active-assignments", headers=hdr(token), params={"limit": 200}
    ).json()
    driver = client.get(f"/api/health-isf/drivers/{MARIA}/active-ride", headers=hdr(token)).json()
    ride = client.get(f"/api/health-isf/rides/{ride_id}", headers=hdr(token)).json()
    ai = client.get("/api/health-isf/ai-dispatch/snapshot?publish=false", headers=hdr(token)).json()
    assignment = (
        db_assignment(ride_id)
    )
    return {
        "step": label,
        "ride_id": ride_id,
        "assignment_id": assignment.get("id"),
        "driver_id": str(ride.get("driver_id") or MARIA),
        "lifecycle_state": ride.get("lifecycle_state"),
        "status": ride.get("status"),
        "assignment_state": assignment.get("state"),
        "dispatch_queue_contains": any(str(x.get("ride_id")) == ride_id for x in queue),
        "dispatch_queue_count": len(queue),
        "active_assignments_contains": any(str(x.get("ride_id")) == ride_id for x in active),
        "driver_active_ride_id": (driver.get("ride") or {}).get("id"),
        "driver_has_active": driver.get("has_active_ride"),
        "ai_contains_ride": ride_id in json.dumps(ai),
    }


def db_assignment(ride_id: str) -> dict:
    with SessionLocal() as db:
        row = (
            db.query(HealthISFDispatchAssignment)
            .filter(HealthISFDispatchAssignment.ride_id == ride_id)
            .order_by(HealthISFDispatchAssignment.updated_at.desc())
            .first()
        )
        if not row:
            return {}
        return {"id": str(row.id), "state": row.assignment_state}


def main() -> int:
    proof: dict = {"pass": False, "steps": [], "cleanup": {}, "errors": []}
    cleanup = cleanup_env()
    proof["cleanup"] = cleanup
    log(f"CLEANUP {json.dumps(cleanup)}")

    suffix = uuid4()[:8]
    phone_digits = "".join(ch for ch in suffix if ch.isdigit()).ljust(4, "0")[:4]
    rider_name = f"Release Validation {suffix}"

    with httpx.Client(base_url=BASE, timeout=60.0) as client:
        dispatcher_token = login(client, "dispatcher@amicor.local")
        rider_token = login(client, "rider@amicor.local")
        dt = hdr(dispatcher_token)
        rt = hdr(rider_token)

        create = client.post(
            "/api/health-isf/customer-requests",
            headers=rt,
            json={
                "rider_name": rider_name,
                "rider_phone": f"612-555-{phone_digits}",
                "pickup_address": "2819 Aldrich Ave N, Minneapolis, MN 55411",
                "dropoff_address": "HCMC, Minneapolis, MN",
                "ride_type": "healthcare",
                "recurring": False,
            },
        )
        if create.status_code != 201:
            proof["errors"].append(f"create failed {create.status_code} {create.text}")
            ARTIFACT.write_text(json.dumps(proof, indent=2), encoding="utf-8")
            return 1
        request_id = create.json()["id"]
        ride_id = create.json()["ride_id"]
        proof["ride_one"] = ride_id
        proof["steps"].append(capture_step(client, dispatcher_token, ride_id, "rider_request_submitted"))

        approve = client.post(f"/api/health-isf/dispatcher/customer-requests/{request_id}/approve", headers=dt)
        if approve.status_code != 200:
            proof["errors"].append(f"approve failed {approve.text}")
            ARTIFACT.write_text(json.dumps(proof, indent=2), encoding="utf-8")
            return 1
        ride_before = client.get(f"/api/health-isf/rides/{ride_id}", headers=dt).json()
        if str(ride_before.get("driver_id") or "") != MARIA:
            assign = client.post(
                f"/api/health-isf/dispatcher/customer-requests/{request_id}/assign-driver",
                headers=dt,
                json={"driver_id": MARIA},
            )
            if assign.status_code not in {200, 400}:
                proof["errors"].append(f"assign failed {assign.status_code} {assign.text}")
                ARTIFACT.write_text(json.dumps(proof, indent=2), encoding="utf-8")
                return 1
            if assign.status_code == 400 and "already has an assigned driver" in assign.text:
                reassign = client.patch(
                    f"/api/health-isf/dispatcher/rides/{ride_id}/reassign-driver",
                    headers=dt,
                    json={"driver_id": MARIA},
                )
                if reassign.status_code != 200:
                    proof["errors"].append(f"reassign failed {reassign.text}")
                    ARTIFACT.write_text(json.dumps(proof, indent=2), encoding="utf-8")
                    return 1

        proof["steps"].append(capture_step(client, dispatcher_token, ride_id, "dispatch_assigned"))

        accept = client.post(
            f"/api/health-isf/drivers/{MARIA}/accept-ride",
            headers=dt,
            json={"ride_id": ride_id},
        )
        if accept.status_code != 200:
            proof["errors"].append(f"accept failed {accept.status_code} {accept.text}")
            ARTIFACT.write_text(json.dumps(proof, indent=2), encoding="utf-8")
            return 1
        proof["steps"].append(capture_step(client, dispatcher_token, ride_id, "driver_accepted"))

        for target, label in [
            ("en_route_pickup", "en_route_pickup"),
            ("arrived_pickup", "arrived_pickup"),
            ("rider_loaded", "rider_loaded"),
            ("trip_in_progress", "start_transport"),
            ("arrived_destination", "arrived_destination"),
            ("completed", "completed"),
        ]:
            step = client.post(
                f"/api/health-isf/drivers/{MARIA}/route-progress",
                headers=dt,
                json={"ride_id": ride_id, "target_state": target},
            )
            if step.status_code != 200:
                proof["errors"].append(f"{label} failed {step.status_code} {step.text}")
                ARTIFACT.write_text(json.dumps(proof, indent=2), encoding="utf-8")
                return 1
            proof["steps"].append(capture_step(client, dispatcher_token, ride_id, label))

        earnings_before = client.get(f"/api/health-isf/drivers/{MARIA}/earnings", headers=dt).json()
        handoffs = client.get("/api/health-isf/operations/billing-handoffs", headers=dt, params={"limit": 200}).json()
        handoff_hits = [row for row in handoffs if str(row.get("ride_id")) == ride_id]
        payments = client.get("/api/health-isf/operations/payment-records", headers=dt, params={"limit": 200})
        payment_rows = payments.json() if payments.status_code == 200 else []

        with SessionLocal() as db:
            billing_count = db.query(HealthISFBillingHandoff).filter(HealthISFBillingHandoff.ride_id == ride_id).count()
            payment_count = db.query(HealthISFPaymentTransaction).filter(
                HealthISFPaymentTransaction.ride_id == ride_id
            ).count()

        post = capture_step(client, dispatcher_token, ride_id, "post_completion")
        post.update(
            {
                "billing_handoffs_for_ride": len(handoff_hits),
                "billing_handoffs_db": billing_count,
                "payment_records_db": payment_count,
                "driver_active_empty": post["driver_has_active"] is False or post["driver_active_ride_id"] != ride_id,
                "dispatch_queue_excludes_ride": post["dispatch_queue_contains"] is False,
            }
        )
        proof["post_completion"] = post
        proof["earnings_before"] = earnings_before

        suffix2 = uuid4()[:8]
        phone2 = "".join(ch for ch in suffix2 if ch.isdigit()).ljust(4, "1")[:4]
        create2 = client.post(
            "/api/health-isf/customer-requests",
            headers=rt,
            json={
                "rider_name": f"Release Validation Two {suffix2}",
                "rider_phone": f"612-555-{phone2}",
                "pickup_address": "100 Second St, Minneapolis, MN",
                "dropoff_address": "200 Clinic Rd, Minneapolis, MN",
                "ride_type": "healthcare",
                "recurring": False,
            },
        )
        request2 = create2.json()["id"]
        ride_two = create2.json()["ride_id"]
        client.post(f"/api/health-isf/dispatcher/customer-requests/{request2}/approve", headers=dt)
        ride2_before = client.get(f"/api/health-isf/rides/{ride_two}", headers=dt).json()
        if str(ride2_before.get("driver_id") or "") != MARIA:
            client.post(
                f"/api/health-isf/dispatcher/customer-requests/{request2}/assign-driver",
                headers=dt,
                json={"driver_id": MARIA},
            )
        active_two = client.get(f"/api/health-isf/drivers/{MARIA}/active-ride", headers=dt).json()
        proof["ride_two"] = ride_two
        proof["second_ride_auto"] = {
            "driver_active_ride_id": (active_two.get("ride") or {}).get("id"),
            "pass": (active_two.get("ride") or {}).get("id") == ride_two,
        }

        # Browser surface check (driver mobile binds Maria, not stale driver)
        browser_ok = True
        try:
            with sync_playwright() as p:
                browser = p.chromium.launch(headless=True)
                page = browser.new_page()
                page.goto(f"{BASE}/app/mobile?driver_id={MARIA}", wait_until="domcontentloaded")
                page.evaluate(
                    """(payload) => {
                      var expiresAt = Date.now() + 24 * 60 * 60 * 1000;
                      var runtimeHost = 'local-dev:8010';
                      localStorage.setItem('amicor_onboarded', '1');
                      localStorage.setItem('amicor_session', JSON.stringify({
                        id: 'release_gate_browser',
                        expiresAt: expiresAt,
                        runtimeHost: runtimeHost
                      }));
                      localStorage.setItem('amicor_identity', JSON.stringify({
                        email: 'dispatcher@amicor.local',
                        display_name: 'Dispatcher',
                        role: 'dispatcher',
                        accessToken: payload.token,
                        organizationId: payload.orgId,
                        tokenExpiresAt: expiresAt,
                        runtimeHost: runtimeHost
                      }));
                      localStorage.setItem('amicor_runtime_marker', JSON.stringify({
                        runtimeHost: runtimeHost,
                        updatedAt: new Date().toISOString()
                      }));
                      localStorage.setItem('amicor_driver_session', JSON.stringify({
                        driver_id: payload.driverId,
                        driver_name: 'Maria Garcia',
                        role: 'driver'
                      }));
                      localStorage.setItem('amicor_driver_workflow_id', payload.driverId);
                      sessionStorage.setItem('amicor_shell_session_v1', JSON.stringify({
                        role: 'driver',
                        route: 'mobile',
                        roleRoutes: { driver: 'mobile' }
                      }));
                      if (window.AmiCorSession && typeof window.AmiCorSession.start === 'function') {
                        window.AmiCorSession.start({
                          email: 'dispatcher@amicor.local',
                          name: 'Dispatcher',
                          role: 'dispatcher',
                          accessToken: payload.token,
                          organizationId: payload.orgId,
                          tokenExpiresAt: expiresAt
                        });
                      }
                    }""",
                    {
                        "token": dispatcher_token,
                        "driverId": MARIA,
                        "orgId": ORG,
                    },
                )
                page.reload(wait_until="domcontentloaded")
                page.wait_for_timeout(8000)
                body = page.inner_text("body")
                browser_ok = ride_two[:8].lower() in body.lower() or ride_id[:8].lower() in body.lower()
                proof["browser_driver_mobile_contains_ride"] = browser_ok
                browser.close()
        except Exception as exc:
            proof["browser_error"] = str(exc)
            browser_ok = False

        gates = [
            post["dispatch_queue_excludes_ride"],
            post["driver_active_empty"] or proof["second_ride_auto"]["pass"],
            billing_count == 1,
            payment_count == 1,
            proof["second_ride_auto"]["pass"],
            browser_ok,
            len(proof["errors"]) == 0,
        ]
        proof["pass"] = all(gates)
        proof["gates"] = {
            "completed_ride_off_dispatch_queue": post["dispatch_queue_excludes_ride"],
            "billing_handoff_unique": billing_count == 1,
            "payment_record_unique": payment_count == 1,
            "second_ride_visible": proof["second_ride_auto"]["pass"],
            "browser_driver_surface": browser_ok,
        }

    ARTIFACT.parent.mkdir(parents=True, exist_ok=True)
    ARTIFACT.write_text(json.dumps(proof, indent=2, default=str), encoding="utf-8")
    log(f"PROOF written to {ARTIFACT}")
    log(f"RELEASE_GATE={'PASS' if proof['pass'] else 'FAIL'}")
    return 0 if proof["pass"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
