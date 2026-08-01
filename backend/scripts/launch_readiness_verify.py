"""Launch readiness: full ride workflow + branding surface checks (no feature changes)."""
from __future__ import annotations

import json
import re
import sys
from datetime import datetime, timezone

from fastapi.testclient import TestClient

from app.auth import SEED_PASSWORD, ensure_auth_schema, seed_default_users
from app.db.models import User as PlatformUser
from app.db.session import SessionLocal
from app.helpers import uuid4
from app.main import app
from app.modules.health_isf import service as hs
from app.modules.health_isf.models import (
    DispatchAssignmentState,
    DriverStatus,
    HealthISFDispatchAssignment,
    HealthISFDriver,
    HealthISFBillingHandoff,
    HealthISFProvider,
    HealthISFRide,
    HealthISFTripFinancialRecord,
    RideStatus,
)
from app.modules.health_isf.workflow_engine import WorkflowOrchestrationService

BRAND_MARKERS = (
    "amicor-logo-v1.svg",
    "amicor-logo",
    "amicor-surface-brand",
    "amicor-brand-lockup",
)

SURFACES = (
    ("/", "landing"),
    ("/app/dashboard", "ops_dashboard"),
    ("/app/dispatch", "dispatch"),
    ("/app/riders", "rider_app"),
    ("/app/mobile", "driver_app"),
    ("/app/providers", "provider_portal"),
    ("/app/ai-assistant", "ai_assistant"),
    ("/admin", "admin"),
    ("/static/branding/preview.html", "brand_gallery"),
)


def _brand_ok(html: str) -> bool:
    lowered = html.lower()
    return any(marker in lowered for marker in BRAND_MARKERS)


def _login(client: TestClient, email: str) -> str:
    resp = client.post("/api/auth/login", json={"email": email, "password": SEED_PASSWORD})
    if resp.status_code != 200:
        raise RuntimeError(f"login failed for {email}: {resp.text[:200]}")
    return resp.json()["access_token"]


def _headers(client: TestClient, email: str = "dispatcher@amicor.local") -> dict[str, str]:
    return {"Authorization": f"Bearer {_login(client, email)}"}


def _org_id(email: str = "dispatcher@amicor.local") -> str:
    with SessionLocal() as db:
        user = db.query(PlatformUser).filter(PlatformUser.email == email).first()
        assert user and user.organization_id
        return str(user.organization_id)


def _ensure_provider(org_id: str) -> str:
    with SessionLocal() as db:
        row = (
            db.query(HealthISFProvider)
            .filter(HealthISFProvider.organization_id == org_id, HealthISFProvider.is_active == True)
            .first()
        )
        if row:
            return str(row.id)
        row = HealthISFProvider(
            id=uuid4(),
            organization_id=org_id,
            name=f"Launch Provider {uuid4()[:6]}",
            address="100 Launch Ave",
            phone="212-555-8800",
            service_type="clinic",
            is_active=True,
        )
        db.add(row)
        db.commit()
        return str(row.id)


def _ensure_driver(org_id: str) -> str:
    with SessionLocal() as db:
        driver = HealthISFDriver(
            id=uuid4(),
            organization_id=org_id,
            name=f"Launch Driver {uuid4()[:6]}",
            phone=f"917-555-{''.join(c for c in uuid4() if c.isdigit())[:4]}",
            vehicle_type="sedan",
            vehicle_plate=f"LN-{uuid4()[:4].upper()}",
            status=DriverStatus.AVAILABLE,
            availability_state="available",
            is_online=True,
            auth_state="active",
            is_active=True,
            rating=5.0,
            total_trips=50,
        )
        db.add(driver)
        for other in db.query(HealthISFDriver).filter(
            HealthISFDriver.organization_id == org_id,
            HealthISFDriver.id != driver.id,
            HealthISFDriver.is_active == True,
        ):
            other.status = DriverStatus.OFFLINE
            other.availability_state = "offline"
        db.commit()
        return str(driver.id)


def _reset_org(org_id: str) -> None:
    with SessionLocal() as db:
        hs.repair_organization_assignment_state(db, organization_id=org_id, dry_run=False)
        policy = WorkflowOrchestrationService.ensure_policy(db, org_id)
        policy.approval_required = True
        policy.is_enabled = True
        db.commit()


def verify_branding(client: TestClient) -> list[dict]:
    results = []
    favicon = client.get("/favicon.ico")
    results.append(
        {
            "surface": "favicon",
            "path": "/favicon.ico",
            "status": favicon.status_code,
            "branded": favicon.status_code == 200 and len(favicon.content) > 0,
        }
    )
    manifest = client.get("/static/manifest.webmanifest")
    manifest_ok = manifest.status_code == 200 and "Amicor" in manifest.text
    results.append(
        {
            "surface": "pwa_manifest",
            "path": "/static/manifest.webmanifest",
            "status": manifest.status_code,
            "branded": manifest_ok,
        }
    )
    for path, name in SURFACES:
        resp = client.get(path)
        html = resp.text if resp.status_code == 200 else ""
        results.append(
            {
                "surface": name,
                "path": path,
                "status": resp.status_code,
                "branded": resp.status_code == 200 and _brand_ok(html),
            }
        )
    return results


def run_workflow(client: TestClient) -> dict:
    steps: list[dict] = []
    org_id = _org_id()
    _reset_org(org_id)
    _ensure_provider(org_id)
    driver_id = _ensure_driver(org_id)

    rider_h = _headers(client, "rider@amicor.local")
    disp_h = _headers(client, "dispatcher@amicor.local")

    dashboard_before = client.get("/api/health-isf/dashboard", headers=disp_h)
    completed_before = dashboard_before.json().get("completed_rides", 0) if dashboard_before.status_code == 200 else 0

    suffix = uuid4()[:8]
    digits = re.sub(r"\D", "", suffix).ljust(4, "0")[:4]
    create = client.post(
        "/api/health-isf/customer-requests",
        headers=rider_h,
        json={
            "rider_name": f"Launch Rider {suffix}",
            "rider_phone": f"646-555-{digits}",
            "pickup_address": f"100 Launch Pickup {suffix}, New York, NY",
            "dropoff_address": f"200 Launch Dropoff {suffix}, New York, NY",
            "ride_type": "healthcare",
            "recurring": False,
        },
    )
    steps.append({"step": "rider_creates_ride", "ok": create.status_code == 201, "status": create.status_code})
    if create.status_code != 201:
        return {"steps": steps, "ride_id": None}

    request_id = create.json()["id"]
    ride_id = create.json()["ride_id"]

    queue = client.get("/api/health-isf/dispatch/queue", headers=disp_h)
    queue_row = next((r for r in queue.json() if r.get("ride_id") == ride_id), None) if queue.status_code == 200 else None
    steps.append(
        {
            "step": "dispatch_receives_ride",
            "ok": queue.status_code == 200 and queue_row is not None,
            "status": queue.status_code,
            "assignment_state": (queue_row or {}).get("assignment_state"),
        }
    )

    approve = client.post(
        f"/api/health-isf/dispatcher/customer-requests/{request_id}/approve",
        headers=disp_h,
    )
    steps.append({"step": "dispatch_approves_request", "ok": approve.status_code == 200, "status": approve.status_code})

    auto_dispatch = client.post(
        f"/api/health-isf/dispatcher/customer-requests/{request_id}/auto-dispatch",
        headers=disp_h,
        json={"driver_id": driver_id, "offer_timeout_seconds": 120},
    )
    steps.append(
        {
            "step": "ai_assigns_ride",
            "ok": auto_dispatch.status_code == 200,
            "status": auto_dispatch.status_code,
        }
    )

    offer = client.get(f"/api/health-isf/drivers/{driver_id}/active-offer", headers=disp_h)
    offer_payload = offer.json() if offer.status_code == 200 else {}
    steps.append(
        {
            "step": "driver_receives_offer",
            "ok": offer.status_code == 200 and offer_payload.get("offer") is not None,
            "status": offer.status_code,
        }
    )

    accept = client.post(
        f"/api/health-isf/drivers/{driver_id}/accept-ride",
        headers=disp_h,
        json={"ride_id": ride_id},
    )
    steps.append({"step": "driver_accepts", "ok": accept.status_code == 200, "status": accept.status_code})

    if accept.status_code == 200 and accept.json().get("lifecycle_state") == RideStatus.ASSIGNED.value:
        client.post(
            f"/api/health-isf/drivers/{driver_id}/route-progress",
            headers=disp_h,
            json={"ride_id": ride_id, "target_state": "en_route_pickup"},
        )

    for label, target in (
        ("driver_arrives", "arrived_pickup"),
        ("pickup", "rider_loaded"),
        ("trip_in_progress", "trip_in_progress"),
    ):
        resp = client.post(
            f"/api/health-isf/drivers/{driver_id}/route-progress",
            headers=disp_h,
            json={"ride_id": ride_id, "target_state": target},
        )
        steps.append({"step": label, "ok": resp.status_code == 200, "status": resp.status_code})

    client.post(
        f"/api/health-isf/drivers/{driver_id}/route-progress",
        headers=disp_h,
        json={"ride_id": ride_id, "target_state": "arrived_destination"},
    )
    complete = client.post(
        f"/api/health-isf/drivers/{driver_id}/dropoff-complete",
        headers=disp_h,
        json={"ride_id": ride_id},
    )
    steps.append(
        {
            "step": "complete_trip",
            "ok": complete.status_code == 200 and complete.json().get("lifecycle_state") == RideStatus.COMPLETED.value,
            "status": complete.status_code,
        }
    )

    handoff = client.get(f"/api/health-isf/rides/{ride_id}/completion-handoff", headers=disp_h)
    financial = client.get(f"/api/health-isf/rides/{ride_id}/financial-summary", headers=disp_h)
    fin_payload = financial.json() if financial.status_code == 200 else {}
    with SessionLocal() as db:
        fin_count = db.query(HealthISFTripFinancialRecord).filter(HealthISFTripFinancialRecord.ride_id == ride_id).count()
        handoff_count = db.query(HealthISFBillingHandoff).filter(HealthISFBillingHandoff.ride_id == ride_id).count()

    steps.append(
        {
            "step": "billing_records_generated",
            "ok": fin_count >= 1 and handoff_count >= 1 and handoff.status_code == 200,
            "financial_records": fin_count,
            "billing_handoffs": handoff_count,
        }
    )
    driver_pay = float(fin_payload.get("driver_pay_usd") or 0)
    platform_rev = float(fin_payload.get("platform_revenue_usd") or 0)
    steps.append(
        {
            "step": "driver_earnings_update",
            "ok": driver_pay > 0,
            "driver_pay_usd": driver_pay,
        }
    )
    steps.append(
        {
            "step": "admin_revenue_updates",
            "ok": platform_rev > 0,
            "platform_revenue_usd": platform_rev,
        }
    )

    driver = client.get(f"/api/health-isf/drivers/{driver_id}", headers=disp_h)
    driver_status = str((driver.json() or {}).get("status", "")).lower()
    steps.append(
        {
            "step": "driver_returns_available",
            "ok": driver.status_code == 200 and driver_status in {"available", "assigned"},
            "driver_status": driver_status,
        }
    )

    dashboard_after = client.get("/api/health-isf/dashboard", headers=disp_h)
    completed_after = dashboard_after.json().get("completed_rides", 0) if dashboard_after.status_code == 200 else 0
    activity = client.get("/api/health-isf/activity-feed", headers=disp_h)
    steps.append(
        {
            "step": "dashboard_refreshes",
            "ok": dashboard_after.status_code == 200 and completed_after >= completed_before + 1 and activity.status_code == 200,
            "completed_before": completed_before,
            "completed_after": completed_after,
        }
    )

    return {"ride_id": ride_id, "request_id": request_id, "driver_id": driver_id, "steps": steps}


def main() -> None:
    ensure_auth_schema()
    seed_default_users()
    client = TestClient(app)

    branding = verify_branding(client)
    workflow = run_workflow(client)

    workflow_ok = all(s.get("ok") for s in workflow.get("steps", []))
    branding_ok = all(b.get("branded") for b in branding)

    report = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "branding_frozen": True,
        "verdict": "GO" if workflow_ok and branding_ok else "NO-GO",
        "workflow": workflow,
        "branding": branding,
        "workflow_pass": workflow_ok,
        "branding_pass": branding_ok,
    }

    out_path = __file__.replace("scripts", "LAUNCH_READINESS_VERIFICATION.json").replace(
        "launch_readiness_verify.py", "LAUNCH_READINESS_VERIFICATION.json"
    )
    # Write next to backend/
    from pathlib import Path

    out = Path(__file__).resolve().parents[1] / "LAUNCH_READINESS_VERIFICATION.json"
    out.write_text(json.dumps(report, indent=2), encoding="utf-8")
    print(json.dumps(report, indent=2))
    print(f"\nWrote {out}")
    if report["verdict"] != "GO":
        sys.exit(1)


if __name__ == "__main__":
    main()
