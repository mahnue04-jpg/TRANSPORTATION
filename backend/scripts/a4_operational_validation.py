from __future__ import annotations

import json
import time
import urllib.error
import urllib.request
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from uuid import uuid4

BASE_URL = "http://127.0.0.1:8000"
OUT_FILE = Path(__file__).resolve().parents[2] / "A4_OPERATIONAL_EVIDENCE.json"


@dataclass
class StepResult:
    name: str
    method: str
    path: str
    status: int | None
    ok: bool
    detail: str
    response: dict[str, Any] | list[Any] | str | None


def _request(method: str, path: str, body: dict[str, Any] | None = None, token: str | None = None, headers: dict[str, str] | None = None) -> tuple[int, Any]:
    req_headers = {"Content-Type": "application/json"}
    if token:
        req_headers["Authorization"] = f"Bearer {token}"
    if headers:
        req_headers.update(headers)
    data = None
    if body is not None:
        data = json.dumps(body).encode("utf-8")
    req = urllib.request.Request(f"{BASE_URL}{path}", method=method, headers=req_headers, data=data)
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            raw = resp.read().decode("utf-8")
            payload: Any
            try:
                payload = json.loads(raw) if raw else None
            except Exception:
                payload = raw
            return resp.getcode(), payload
    except urllib.error.HTTPError as exc:
        raw = exc.read().decode("utf-8")
        try:
            payload = json.loads(raw) if raw else None
        except Exception:
            payload = raw
        return exc.code, payload


def _wait_for_server(max_wait: int = 60) -> bool:
    started = time.time()
    while time.time() - started < max_wait:
        code, _ = _request("GET", "/api/health/live")
        if code == 200:
            return True
        time.sleep(1)
    return False


def main() -> int:
    started_at = datetime.now(timezone.utc).isoformat()
    steps: list[StepResult] = []
    failures: list[dict[str, Any]] = []
    endpoints: list[dict[str, str]] = []
    entity_ids: dict[str, str] = {}
    readiness = "PASS"

    if not _wait_for_server():
        report = {
            "started_at": started_at,
            "completed_at": datetime.now(timezone.utc).isoformat(),
            "readiness": "FAIL",
            "blocking_issue": "Server did not become healthy at /api/health/live",
            "steps": [],
        }
        OUT_FILE.write_text(json.dumps(report, indent=2), encoding="utf-8")
        print(json.dumps(report, indent=2))
        return 1

    # 1) Fresh tenant attempt via public API register
    tenant_name = f"Pilot Tenant {uuid4().hex[:6]}"
    rider_email = f"pilot.a4.{uuid4().hex[:8]}@example.com"
    rider_password = "PilotA4Pass!234"
    reg_body = {
        "email": rider_email,
        "password": rider_password,
        "display_name": "Pilot Rider A4",
        "role": "staff",
        "organization_name": tenant_name,
    }
    code, payload = _request("POST", "/api/auth/register", reg_body)
    endpoints.append({"method": "POST", "path": "/api/auth/register"})
    steps.append(StepResult("create_fresh_tenant_attempt", "POST", "/api/auth/register", code, code == 201, "register rider with tenant name", payload))
    if code != 201:
        failures.append({
            "step": "create_fresh_tenant_attempt",
            "status": code,
            "root_cause": "Public register failed",
            "response": payload,
        })

    # Rider login
    code, payload = _request("POST", "/api/auth/login", {"email": rider_email, "password": rider_password})
    endpoints.append({"method": "POST", "path": "/api/auth/login"})
    rider_token = payload.get("access_token") if isinstance(payload, dict) else None
    rider_org_id = payload.get("organization_id") if isinstance(payload, dict) else None
    steps.append(StepResult("login_rider", "POST", "/api/auth/login", code, code == 200 and bool(rider_token), "login fresh rider", payload))
    if code != 200 or not rider_token:
        failures.append({"step": "login_rider", "status": code, "root_cause": "Cannot login rider", "response": payload})
        readiness = "FAIL"

    # 1b) Register tenant-scoped dispatcher for write operations in the same org
    dispatcher_email = f"pilot.dispatcher.a4.{uuid4().hex[:8]}@example.com"
    dispatcher_password = "PilotA4Dispatch!234"
    dispatcher_reg = {
        "email": dispatcher_email,
        "password": dispatcher_password,
        "display_name": "Pilot Dispatcher A4",
        "role": "dispatcher",
        "organization_name": tenant_name,
    }
    code, payload = _request("POST", "/api/auth/register", dispatcher_reg)
    endpoints.append({"method": "POST", "path": "/api/auth/register"})
    steps.append(StepResult("register_dispatcher", "POST", "/api/auth/register", code, code == 201, "register tenant dispatcher", payload))
    if code != 201:
        failures.append({"step": "register_dispatcher", "status": code, "root_cause": "Cannot register tenant dispatcher", "response": payload})

    # Dispatcher login (tenant-scoped account)
    code, payload = _request("POST", "/api/auth/login", {"email": dispatcher_email, "password": dispatcher_password})
    endpoints.append({"method": "POST", "path": "/api/auth/login"})
    dispatcher_token = payload.get("access_token") if isinstance(payload, dict) else None
    dispatcher_org_id = payload.get("organization_id") if isinstance(payload, dict) else None
    steps.append(StepResult("login_dispatcher", "POST", "/api/auth/login", code, code == 200 and bool(dispatcher_token), "login tenant dispatcher", payload))
    if code != 200 or not dispatcher_token:
        failures.append({"step": "login_dispatcher", "status": code, "root_cause": "Cannot login dispatcher", "response": payload})
        readiness = "FAIL"

    if rider_org_id and dispatcher_org_id and rider_org_id != dispatcher_org_id:
        failures.append({
            "step": "fresh_tenant_validation",
            "status": 409,
            "root_cause": "Fresh tenant validation failed; rider and dispatcher do not share the same tenant scope",
            "evidence": {"rider_org_id": rider_org_id, "dispatcher_org_id": dispatcher_org_id},
        })
        readiness = "FAIL"

    # 2) Create provider
    provider_body = {
        "name": f"A4 Provider {uuid4().hex[:6]}",
        "address": "100 A4 Provider Lane",
        "phone": f"212-555-{str(uuid4().hex)[:4]}",
        "service_type": "clinic",
    }
    code, payload = _request("POST", "/api/health-isf/providers", provider_body, dispatcher_token)
    endpoints.append({"method": "POST", "path": "/api/health-isf/providers"})
    provider_id = payload.get("id") if isinstance(payload, dict) else None
    if provider_id:
        entity_ids["provider_id"] = provider_id
    steps.append(StepResult("create_provider", "POST", "/api/health-isf/providers", code, code == 201, "create provider", payload))

    # 3) Create driver
    driver_body = {
        "name": f"A4 Driver {uuid4().hex[:6]}",
        "phone": f"917-555-{str(uuid4().hex)[:4]}",
        "vehicle_type": "sedan",
        "vehicle_plate": f"A4D-{uuid4().hex[:5].upper()}",
    }
    code, payload = _request("POST", "/api/health-isf/drivers", driver_body, dispatcher_token)
    endpoints.append({"method": "POST", "path": "/api/health-isf/drivers"})
    driver_id = payload.get("id") if isinstance(payload, dict) else None
    if driver_id:
        entity_ids["driver_id"] = driver_id
    steps.append(StepResult("create_driver", "POST", "/api/health-isf/drivers", code, code == 201, "create driver", payload))

    # Driver must be available for dispatcher assignment.
    if driver_id:
        code, payload = _request("POST", f"/api/health-isf/drivers/{driver_id}/set-status", {"status": "available"}, dispatcher_token)
        endpoints.append({"method": "POST", "path": "/api/health-isf/drivers/{driver_id}/set-status"})
        steps.append(StepResult("set_driver_available", "POST", f"/api/health-isf/drivers/{driver_id}/set-status", code, code == 200, "set driver available", payload))

    # 4) Create vehicle
    vehicle_body = {
        "vehicle_type": "van",
        "vehicle_plate": f"A4V-{uuid4().hex[:5].upper()}",
        "capacity": 6,
    }
    code, payload = _request("POST", "/api/health-isf/vehicles", vehicle_body, dispatcher_token)
    endpoints.append({"method": "POST", "path": "/api/health-isf/vehicles"})
    vehicle_id = payload.get("id") if isinstance(payload, dict) else None
    if vehicle_id:
        entity_ids["vehicle_id"] = vehicle_id
    steps.append(StepResult("create_vehicle", "POST", "/api/health-isf/vehicles", code, code == 201, "create vehicle", payload))

    # 5) Create rider (already created via auth register)
    entity_ids["rider_email"] = rider_email

    # 6) Create ride request as rider via public customer-requests API
    request_body = {
        "pickup_address": "1 Pilot Start St",
        "dropoff_address": "2 Pilot End Ave",
        "rider_name": "Pilot Rider A4",
        "rider_phone": "+1 917-555-0101",
        "ride_type": "healthcare",
        "recurring": False,
        "notes": "A4 operational validation",
    }
    code, payload = _request("POST", "/api/health-isf/customer-requests", request_body, rider_token, headers={"X-Idempotency-Key": f"a4-req-{uuid4().hex}"})
    endpoints.append({"method": "POST", "path": "/api/health-isf/customer-requests"})
    ride_id = payload.get("ride_id") if isinstance(payload, dict) else None
    request_id = payload.get("id") if isinstance(payload, dict) else None
    if ride_id:
        entity_ids["ride_id"] = ride_id
    if request_id:
        entity_ids["customer_request_id"] = request_id
    steps.append(StepResult("create_ride_request", "POST", "/api/health-isf/customer-requests", code, code == 201 and bool(ride_id), "create ride request from rider context", payload))

    # Idempotency check (rides endpoint)
    idem_key = f"a4-ride-{uuid4().hex}"
    ride_body = {
        "provider_id": provider_id,
        "passenger_name": "Idempotency Rider",
        "passenger_phone": "+1 917-555-7777",
        "pickup_address": "10 Idem Start",
        "dropoff_address": "20 Idem End",
        "service_type": "medical_transport",
    }
    c1, p1 = _request("POST", "/api/health-isf/rides", ride_body, dispatcher_token, headers={"X-Idempotency-Key": idem_key})
    c2, p2 = _request("POST", "/api/health-isf/rides", ride_body, dispatcher_token, headers={"X-Idempotency-Key": idem_key})
    idem_ok = c1 in (200, 201) and c2 in (200, 201) and isinstance(p1, dict) and isinstance(p2, dict) and p1.get("id") == p2.get("id")
    steps.append(StepResult("idempotency_protection", "POST", "/api/health-isf/rides", c2, idem_ok, "duplicate idempotency-key request returns same ride", {"first": p1, "second": p2, "statuses": [c1, c2]}))
    endpoints.append({"method": "POST", "path": "/api/health-isf/rides"})

    # 7) dispatch assignment
    if ride_id and driver_id:
        code, payload = _request("PATCH", f"/api/health-isf/rides/{ride_id}/assign-driver", {"driver_id": driver_id}, dispatcher_token)
        endpoints.append({"method": "PATCH", "path": "/api/health-isf/rides/{ride_id}/assign-driver"})
        steps.append(StepResult("dispatch_assign_driver", "PATCH", f"/api/health-isf/rides/{ride_id}/assign-driver", code, code == 200, "assign driver", payload))

        # 8) start ride (driver accept)
        code, payload = _request("POST", f"/api/health-isf/drivers/{driver_id}/accept-ride", {"ride_id": ride_id}, dispatcher_token)
        endpoints.append({"method": "POST", "path": "/api/health-isf/drivers/{driver_id}/accept-ride"})
        steps.append(StepResult("start_ride_accept", "POST", f"/api/health-isf/drivers/{driver_id}/accept-ride", code, code == 200, "driver accepts ride", payload))

        # 9) progress statuses
        code1, p1 = _request("POST", f"/api/health-isf/drivers/{driver_id}/arrived-pickup", {"ride_id": ride_id}, dispatcher_token)
        code2, p2 = _request("POST", f"/api/health-isf/drivers/{driver_id}/pickup-complete", {"ride_id": ride_id}, dispatcher_token)
        code_mid, p_mid = _request("PATCH", f"/api/health-isf/rides/{ride_id}/status", {"status": "in_progress"}, dispatcher_token)
        code3, p3 = _request("POST", f"/api/health-isf/drivers/{driver_id}/dropoff-complete", {"ride_id": ride_id}, dispatcher_token)
        endpoints.append({"method": "POST", "path": "/api/health-isf/drivers/{driver_id}/arrived-pickup"})
        endpoints.append({"method": "POST", "path": "/api/health-isf/drivers/{driver_id}/pickup-complete"})
        endpoints.append({"method": "PATCH", "path": f"/api/health-isf/rides/{ride_id}/status"})
        endpoints.append({"method": "POST", "path": "/api/health-isf/drivers/{driver_id}/dropoff-complete"})
        progress_ok = code1 == 200 and code2 == 200 and code_mid == 200 and code3 == 200
        steps.append(StepResult("progress_ride_statuses", "MIXED", f"/api/health-isf/drivers/{driver_id}/arrived-pickup + pickup-complete + rides/{ride_id}/status + dropoff-complete", code3, progress_ok, "progress ride through arrived/onboard/in-progress/dropoff states", {"arrived": {"status": code1, "resp": p1}, "pickup_complete": {"status": code2, "resp": p2}, "set_in_progress": {"status": code_mid, "resp": p_mid}, "dropoff_complete": {"status": code3, "resp": p3}}))

        # 10) verify final ride status
        code, payload = _request("GET", f"/api/health-isf/rides/{ride_id}", token=dispatcher_token)
        endpoints.append({"method": "GET", "path": "/api/health-isf/rides/{ride_id}"})
        is_completed = isinstance(payload, dict) and str(payload.get("status", "")).lower() == "completed"
        steps.append(StepResult("verify_ride_completed", "GET", f"/api/health-isf/rides/{ride_id}", code, code == 200 and is_completed, "verify ride is completed", payload))

        # Authorization enforcement check
        code, payload = _request("POST", "/api/health-isf/providers", provider_body, rider_token)
        steps.append(StepResult("authorization_enforcement", "POST", "/api/health-isf/providers", code, code == 403, "rider cannot call write endpoint", payload))
    else:
        failures.append({"step": "dispatch_and_lifecycle", "root_cause": "missing ride_id or driver_id due earlier failures"})

    for step in steps:
        if not step.ok:
            failures.append({
                "step": step.name,
                "status": step.status,
                "detail": step.detail,
                "response": step.response,
            })

    # recurring ride generation check through public APIs
    if provider_id and dispatcher_token:
        schedule_body = {
            "provider_id": provider_id,
            "passenger_name": "A4 Recurring",
            "passenger_phone": "+1 917-555-0202",
            "pickup_address": "30 Recurring Start",
            "dropoff_address": "40 Recurring End",
            "service_type": "medical_transport",
            "start_date": datetime.now(timezone.utc).isoformat(),
            "frequency": "daily",
            "interval_count": 1,
            "weekdays": [],
            "pickup_time_local": "08:30",
            "horizon_days": 3,
        }
        code, payload = _request("POST", "/api/health-isf/recurring/schedules", schedule_body, dispatcher_token)
        endpoints.append({"method": "POST", "path": "/api/health-isf/recurring/schedules"})
        schedule_id = payload.get("id") if isinstance(payload, dict) else None
        rides_generated = payload.get("generated_ride_count") if isinstance(payload, dict) else None
        steps.append(StepResult("recurring_generation", "POST", "/api/health-isf/recurring/schedules", code, code == 201 and bool(schedule_id) and int(rides_generated or 0) >= 1, "create recurring schedule and confirm generated rides", payload))
        if schedule_id:
            entity_ids["recurring_schedule_id"] = schedule_id

    if failures:
        readiness = "FAIL"

    report = {
        "started_at": started_at,
        "completed_at": datetime.now(timezone.utc).isoformat(),
        "readiness": readiness,
        "base_url": BASE_URL,
        "endpoints_exercised": endpoints,
        "entity_ids": entity_ids,
        "steps": [
            {
                "name": s.name,
                "method": s.method,
                "path": s.path,
                "status": s.status,
                "ok": s.ok,
                "detail": s.detail,
                "response": s.response,
            }
            for s in steps
        ],
        "failures": failures,
        "root_cause_summary": [],
        "pilot_readiness_assessment": "FAIL" if readiness == "FAIL" else "PASS",
    }

    OUT_FILE.write_text(json.dumps(report, indent=2), encoding="utf-8")
    print(json.dumps(report, indent=2))
    return 0 if readiness == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
