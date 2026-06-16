import json
import urllib.request
import urllib.parse
import urllib.error
from pathlib import Path

BASE = "http://127.0.0.1:8010"
OUT = Path("live_workflow_evidence.json")


def req(method, path, body=None, token=None, timeout=30):
    headers = {"Content-Type": "application/json"}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    data = None
    if body is not None:
        data = json.dumps(body).encode("utf-8")
    r = urllib.request.Request(BASE + path, data=data, headers=headers, method=method)
    try:
        with urllib.request.urlopen(r, timeout=timeout) as resp:
            raw = resp.read().decode("utf-8")
            return resp.status, json.loads(raw) if raw else None
    except urllib.error.HTTPError as exc:
        raw = exc.read().decode("utf-8") if exc.fp else ""
        detail = raw
        try:
            parsed = json.loads(raw) if raw else {}
            detail = parsed.get("detail", raw)
        except Exception:
            parsed = {"raw": raw}
        raise RuntimeError(f"HTTP {exc.code} {method} {path} :: {detail}") from exc


def get(path, token=None, timeout=30):
    return req("GET", path, None, token, timeout)


def post(path, body, token=None, timeout=30):
    return req("POST", path, body, token, timeout)


def patch(path, body, token=None, timeout=30):
    return req("PATCH", path, body, token, timeout)


def main():
    steps = []

    st, login = post("/api/auth/login", {"email": "dispatcher@amicor.local", "password": "Amicor123!"})
    token = login["access_token"]
    steps.append({"step": "auth_login", "status": st, "user": "dispatcher@amicor.local"})

    st, providers = get("/api/health-isf/providers", token)
    provider_id = providers[0]["id"] if providers else None
    steps.append({"step": "provider_resolved", "status": st, "provider_id": provider_id, "provider_count": len(providers or [])})

    st, drivers = get("/api/health-isf/drivers", token)
    assignable = [
        d for d in (drivers or [])
        if str(d.get("status", "")).lower() in {"available", "unavailable"}
    ]
    driver_id = assignable[0]["id"] if assignable else None
    if not driver_id:
        candidate = {
            "name": "CEO Live Driver",
            "phone": "+1 212-555-7711",
            "vehicle_type": "sedan",
            "vehicle_plate": "CEO-7711",
        }
        created_ok = False
        try:
            st_create, created_driver = post("/api/health-isf/drivers", candidate, token)
            driver_id = created_driver.get("id")
            created_ok = True
            steps.append({"step": "driver_created_for_workflow", "status": st_create, "driver_id": driver_id})
        except Exception:
            # Retry with unique identity if the plate/phone already exists.
            suffix = "".join(["8", "1", "2", "4"])
            candidate["phone"] = f"+1 212-555-{suffix}"
            candidate["vehicle_plate"] = f"CEO-{suffix}"
            st_create, created_driver = post("/api/health-isf/drivers", candidate, token)
            driver_id = created_driver.get("id")
            created_ok = True
            steps.append({"step": "driver_created_for_workflow", "status": st_create, "driver_id": driver_id})

        if created_ok and driver_id:
            st_set, driver_after = post(
                f"/api/health-isf/drivers/{driver_id}/set-status",
                {"status": "available"},
                token,
            )
            steps.append({
                "step": "driver_set_available",
                "status": st_set,
                "driver_id": driver_id,
                "driver_status": driver_after.get("status") if isinstance(driver_after, dict) else None,
            })

    steps.append({"step": "driver_resolved", "status": st, "driver_id": driver_id, "assignable_count": len(assignable)})

    rider_phone = "+1 212-555-" + "".join(["6", "6", "1", "1"])
    ride_payload = {
        "pickup_address": "100 CEO Evidence Way, New York, NY",
        "dropoff_address": "900 Completion Blvd, New York, NY",
        "rider_name": "CEO Live Test Rider",
        "rider_phone": rider_phone,
        "ride_type": "healthcare",
        "provider_id": provider_id,
        "notes": "CEO live workflow evidence run",
    }
    st, created = post("/api/health-isf/customer-requests", ride_payload, token)
    ride_id = created["ride_id"]
    request_id = created["id"]
    steps.append({"step": "ride_created", "status": st, "ride_id": ride_id, "request_id": request_id})

    st, queue = get("/api/health-isf/customer-requests?dispatch_status=pending", token)
    queue_hit = any(item.get("id") == request_id for item in (queue or []))
    steps.append({"step": "ride_visible_dispatch", "status": st, "request_in_dispatch_queue": queue_hit, "queue_size": len(queue or [])})

    st, approved = post(f"/api/health-isf/dispatcher/customer-requests/{request_id}/approve", {}, token)
    steps.append({"step": "request_approved", "status": st, "dispatch_status": approved.get("dispatch_status") if isinstance(approved, dict) else None})

    st, assigned = post(f"/api/health-isf/dispatcher/customer-requests/{request_id}/assign-driver", {"driver_id": driver_id}, token)
    steps.append({"step": "driver_assigned", "status": st, "assigned_driver_id": assigned.get("driver_id") if isinstance(assigned, dict) else driver_id})

    st, offer = get(f"/api/health-isf/drivers/{driver_id}/active-offer", token)
    steps.append({"step": "driver_receives_ride", "status": st, "offer_present": bool((offer or {}).get("offer")), "offer_ride_id": (offer or {}).get("offer", {}).get("ride_id") if isinstance((offer or {}).get("offer"), dict) else None})

    st, accepted = post(f"/api/health-isf/drivers/{driver_id}/accept-ride", {"ride_id": ride_id}, token)
    steps.append({"step": "driver_accepts_ride", "status": st, "ride_status": accepted.get("status") if isinstance(accepted, dict) else None, "lifecycle_state": accepted.get("lifecycle_state") if isinstance(accepted, dict) else None})

    st, arrived = post(f"/api/health-isf/drivers/{driver_id}/arrived-pickup", {"ride_id": ride_id}, token)
    steps.append({"step": "driver_marks_arrived", "status": st, "ride_status": arrived.get("status") if isinstance(arrived, dict) else None, "lifecycle_state": arrived.get("lifecycle_state") if isinstance(arrived, dict) else None})

    st, pickup = post(f"/api/health-isf/drivers/{driver_id}/pickup-complete", {"ride_id": ride_id}, token)
    steps.append({"step": "driver_marks_pickup", "status": st, "ride_status": pickup.get("status") if isinstance(pickup, dict) else None, "lifecycle_state": pickup.get("lifecycle_state") if isinstance(pickup, dict) else None})

    st, completed = post(f"/api/health-isf/drivers/{driver_id}/dropoff-complete", {"ride_id": ride_id}, token)
    steps.append({"step": "driver_completes_trip", "status": st, "ride_status": completed.get("status") if isinstance(completed, dict) else None, "lifecycle_state": completed.get("lifecycle_state") if isinstance(completed, dict) else None, "completed_at": completed.get("completed_at") if isinstance(completed, dict) else None})

    st, rider_active = get(f"/api/health-isf/customers/workspace/live-tracking?rider_phone={urllib.parse.quote(rider_phone)}", token)
    steps.append({"step": "rider_screen_api_state", "status": st, "has_active_ride": bool((rider_active or {}).get("active_ride")), "active_ride_id": (rider_active or {}).get("active_ride", {}).get("id") if isinstance((rider_active or {}).get("active_ride"), dict) else None, "timeline_count": len((rider_active or {}).get("timeline") or [])})

    st, handoff = get(f"/api/health-isf/rides/{ride_id}/completion-handoff", token)
    steps.append({"step": "billing_completion_handoff", "status": st, "provider_queue_ready": (handoff or {}).get("provider_queue_ready"), "billing_queue_ready": (handoff or {}).get("billing_queue_ready"), "trip_id": (handoff or {}).get("trip_id"), "payout_id": (handoff or {}).get("payout_id"), "completion_artifact_id": (handoff or {}).get("completion_artifact_id")})

    OUT.write_text(json.dumps({"ride_id": ride_id, "request_id": request_id, "driver_id": driver_id, "provider_id": provider_id, "rider_phone": rider_phone, "steps": steps}, indent=2), encoding="utf-8")
    print(str(OUT))


if __name__ == "__main__":
    main()
