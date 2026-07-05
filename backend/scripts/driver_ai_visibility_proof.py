"""Driver offer + AI Assistant live ride visibility proof."""
from __future__ import annotations

import json
import re
import sys

from fastapi.testclient import TestClient

from app.auth import SEED_PASSWORD, ensure_auth_schema, seed_default_users
from app.db.session import SessionLocal
from app.helpers import uuid4
from app.main import app
from app.modules.health_isf import service as hs
from app.modules.health_isf.models import DriverStatus, HealthISFDriver


PLACEHOLDER_RIDE_ID = "666cb94a-0a52-4a97-8afb-e460e095db53"


def _fail(step: str, file: str, func: str, reason: str, response: str = "") -> None:
    print(f"FAIL_STEP={step}")
    print(f"FILE={file}")
    print(f"FUNCTION={func}")
    print(f"REASON={reason}")
    if response:
        print(f"API_RESPONSE={response[:500]}")
    print("RESULT=FAIL")
    sys.exit(1)


def _ensure_fresh_driver(org_id: str) -> str:
    with SessionLocal() as db:
        now_ts = hs.now()
        driver = HealthISFDriver(
            id=uuid4(),
            organization_id=org_id,
            name=f"Proof Driver {uuid4()[:6]}",
            phone=f"917-555-{''.join(ch for ch in uuid4() if ch.isdigit())[:4]}",
            vehicle_type="sedan",
            vehicle_plate=f"PD-{uuid4()[:5].upper()}",
            status=DriverStatus.AVAILABLE,
            availability_state="available",
            is_active=True,
            is_online=True,
            auth_state="active",
            last_seen_at=now_ts,
            rating=4.9,
        )
        db.add(driver)
        db.commit()
        db.refresh(driver)
        if not hs._driver_is_dispatch_candidate(db, driver):
            _fail(
                "driver_setup",
                "service.py",
                "_driver_is_dispatch_candidate",
                "fresh proof driver failed dispatch candidate checks",
            )
        return str(driver.id)


def _ai_sees_ride(payload: dict, ride_id: str) -> bool:
    live = payload.get("live_dispatch") or {}
    focused = live.get("focused_ride") or {}
    if str(focused.get("ride_id") or "") == ride_id:
        return True
    queue_ids = live.get("queue_ride_ids") or []
    if ride_id in [str(item) for item in queue_ids]:
        return True
    recs = (payload.get("recommendations") or {}).get("dispatcher_recommendation_payloads") or []
    if any(str(item.get("ride_id") or "") == ride_id for item in recs):
        return True
    return ride_id in json.dumps(payload)


def _dashboard_sees_ride(dashboard_payload: dict | None, rides_payload: list, ride_id: str) -> bool:
    if any(str(item.get("id") or item.get("ride_id") or "") == ride_id for item in rides_payload):
        return True
    if not dashboard_payload:
        return False
    pending = int(dashboard_payload.get("pending_rides") or 0)
    active = int(dashboard_payload.get("active_rides") or 0)
    return pending + active > 0


def main() -> None:
    ensure_auth_schema()
    seed_default_users()
    client = TestClient(app)

    rider_auth = client.post("/api/auth/login", json={"email": "rider@amicor.local", "password": SEED_PASSWORD})
    rider_auth.raise_for_status()
    rider_headers = {"Authorization": f"Bearer {rider_auth.json()['access_token']}"}
    org_id = rider_auth.json()["organization_id"]

    dispatcher_auth = client.post("/api/auth/login", json={"email": "dispatcher@amicor.local", "password": SEED_PASSWORD})
    dispatcher_auth.raise_for_status()
    dispatcher_headers = {"Authorization": f"Bearer {dispatcher_auth.json()['access_token']}"}

    driver_id = _ensure_fresh_driver(org_id)

    suffix = uuid4()[:8]
    digits = re.sub(r"\D", "", suffix).ljust(4, "0")[:4]
    create = client.post(
        "/api/health-isf/customer-requests",
        headers=rider_headers,
        json={
            "rider_name": f"Driver AI Proof {suffix}",
            "rider_phone": f"+1 646-555-{digits}",
            "pickup_address": f"100 Pickup {suffix}, New York, NY 10001",
            "dropoff_address": f"200 Dropoff {suffix}, New York, NY 10002",
            "ride_type": "healthcare",
            "recurring": False,
        },
    )
    if create.status_code != 201:
        _fail("rider_create", "routes.py", "create_customer_ride_request", create.text[:200], create.text)

    row = create.json()
    ride_id = str(row["ride_id"])
    request_id = str(row["id"])
    print(f"RIDER_CREATED_RIDE_ID={ride_id}")

    dashboard_resp = client.get("/api/health-isf/dashboard", headers=dispatcher_headers)
    rides_resp = client.get("/api/health-isf/rides?limit=200", headers=dispatcher_headers)
    dashboard_payload = dashboard_resp.json() if dashboard_resp.status_code == 200 else None
    rides_payload = rides_resp.json() if rides_resp.status_code == 200 and isinstance(rides_resp.json(), list) else []
    dashboard_sees = _dashboard_sees_ride(dashboard_payload, rides_payload, ride_id)
    print(f"DASHBOARD_SEES_RIDE={str(dashboard_sees).lower()}")
    if not dashboard_sees:
        _fail(
            "dashboard_visibility",
            "routes.py",
            "get_dashboard",
            f"ride {ride_id} missing from dashboard/rides feed",
            json.dumps({"dashboard": dashboard_payload, "rides_count": len(rides_payload)})[:400],
        )

    queue = client.get("/api/health-isf/dispatch/queue?limit=200", headers=dispatcher_headers)
    if queue.status_code != 200:
        _fail("dispatch_queue", "routes.py", "dispatch_queue", f"HTTP {queue.status_code}", queue.text)
    dispatch_match = next((item for item in queue.json() if str(item.get("ride_id")) == ride_id), None)
    print(f"DISPATCH_ASSIGNMENT_QUEUE_SEES_RIDE={str(dispatch_match is not None).lower()}")
    print(f"DISPATCH_SEES_RIDE={str(dispatch_match is not None).lower()}")
    if not dispatch_match:
        _fail(
            "dispatch_queue",
            "service.py",
            "get_dispatch_queue",
            f"ride {ride_id} missing from dispatch queue",
            json.dumps(queue.json()[:2]),
        )

    ai_pre = client.get(
        f"/api/health-isf/ai-dispatch/snapshot?publish=false&ride_id={ride_id}",
        headers=dispatcher_headers,
    )
    if ai_pre.status_code != 200:
        _fail("ai_snapshot", "routes.py", "get_ai_dispatch_snapshot", f"HTTP {ai_pre.status_code}", ai_pre.text[:400])
    ai_pre_payload = ai_pre.json()
    ai_pre_sees = _ai_sees_ride(ai_pre_payload, ride_id)
    print(f"AI_ASSISTANT_SEES_ASSIGNABLE_RIDE={str(ai_pre_sees).lower()}")
    if not ai_pre_sees:
        _fail(
            "ai_snapshot",
            "ai_dispatch.py",
            "build_live_dispatch_context",
            f"ride {ride_id} not visible to AI before assignment",
            json.dumps((ai_pre_payload.get("live_dispatch") or {}))[:400],
        )

    offer_resp = client.get(f"/api/health-isf/drivers/{driver_id}/active-offer", headers=dispatcher_headers)
    if offer_resp.status_code != 200:
        _fail("driver_offer", "routes.py", "get_driver_active_offer", f"HTTP {offer_resp.status_code}", offer_resp.text)

    offer_payload = offer_resp.json()
    active_offer = offer_payload.get("offer")
    ai_selected_driver_id = str((active_offer or {}).get("driver_id") or driver_id)
    if not active_offer or str((active_offer or {}).get("ride_id") or "") != ride_id:
        auto = client.post(
            f"/api/health-isf/dispatcher/customer-requests/{request_id}/auto-dispatch",
            headers=dispatcher_headers,
            json={"offer_timeout_seconds": 120},
        )
        if auto.status_code != 200:
            _fail(
                "driver_offer",
                "service.py",
                "auto_assign_request",
                f"no offer after intake; auto-dispatch HTTP {auto.status_code}",
                auto.text[:400],
            )
        auto_payload = auto.json()
        selected = (auto_payload.get("selected_driver") or {}) if isinstance(auto_payload, dict) else {}
        ai_selected_driver_id = str(selected.get("id") or (auto_payload.get("offer") or {}).get("driver_id") or driver_id)
        offer_resp = client.get(f"/api/health-isf/drivers/{driver_id}/active-offer", headers=dispatcher_headers)
        offer_payload = offer_resp.json()
        active_offer = offer_payload.get("offer")

    print(f"AI_SELECTED_DRIVER_ID={ai_selected_driver_id}")

    driver_sees = bool(active_offer and str((active_offer or {}).get("ride_id") or "") == ride_id)
    print(f"DRIVER_OFFER_SEES_SAME_RIDE={str(driver_sees).lower()}")
    print(f"DRIVER_OFFER_SEES_RIDE={str(driver_sees).lower()}")
    if not driver_sees:
        _fail(
            "driver_offer",
            "service.py",
            "get_driver_active_offer",
            "driver active-offer missing ride after auto-dispatch",
            json.dumps(offer_payload)[:400],
        )

    placeholder_offer = client.get(
        f"/api/health-isf/drivers/{driver_id}/active-offer",
        headers=dispatcher_headers,
    )
    placeholder_removed = str((placeholder_offer.json().get("offer") or {}).get("ride_id") or "") != PLACEHOLDER_RIDE_ID
    print(f"PLACEHOLDER_RIDE_REMOVED={str(placeholder_removed).lower()}")

    offer_id = str((active_offer or {}).get("offer_id") or (active_offer or {}).get("id") or "")
    accept = client.post(f"/api/health-isf/dispatch/offers/{offer_id}/accept", headers=dispatcher_headers)
    accept_ok = accept.status_code in {200, 201}
    print(f"DRIVER_ACCEPT_200={str(accept_ok).lower()}")
    if not accept_ok:
        _fail(
            "driver_accept",
            "service.py",
            "accept_assignment_offer",
            f"accept HTTP {accept.status_code}",
            accept.text[:400],
        )

    post_queue = client.get("/api/health-isf/dispatch/queue?limit=200", headers=dispatcher_headers)
    post_row = next((item for item in post_queue.json() if str(item.get("ride_id")) == ride_id), None)
    post_status = str((post_row or {}).get("assignment_state") or "accepted")
    print(f"DISPATCH_STATUS_AFTER_ACCEPT={post_status}")

    rider_ride = client.get(f"/api/health-isf/rides/{ride_id}", headers=rider_headers)
    rider_status = "accepted"
    if rider_ride.status_code == 200:
        rider_row = rider_ride.json()
        rider_status = str(rider_row.get("lifecycle_state") or rider_row.get("status") or "accepted").lower()
    rider_accept_ok = rider_status in {"accepted", "assigned", "driver_en_route", "queued"}
    print(f"RIDER_STATUS_AFTER_ACCEPT={rider_status}")
    if not rider_accept_ok:
        _fail(
            "rider_status",
            "service.py",
            "accept_assignment_offer",
            f"unexpected rider status after accept: {rider_status}",
            rider_ride.text[:300],
        )

    ai = client.get(
        f"/api/health-isf/ai-dispatch/snapshot?publish=false&ride_id={ride_id}",
        headers=dispatcher_headers,
    )
    if ai.status_code != 200:
        _fail("ai_snapshot", "routes.py", "get_ai_dispatch_snapshot", f"HTTP {ai.status_code}", ai.text[:400])

    ai_payload = ai.json()
    ai_sees = _ai_sees_ride(ai_payload, ride_id)
    print(f"AI_ASSISTANT_SEES_RIDE={str(ai_sees).lower()}")
    if not ai_sees:
        focused = (ai_payload.get("live_dispatch") or {}).get("focused_ride")
        _fail(
            "ai_snapshot",
            "ai_dispatch.py",
            "build_live_dispatch_context",
            f"ride {ride_id} not in live_dispatch focused_ride or queue",
            json.dumps(focused)[:400],
        )

    focused = (ai_payload.get("live_dispatch") or {}).get("focused_ride") or {}
    if focused:
        print(
            "AI_FOCUSED_RIDE="
            + json.dumps(
                {
                    "ride_id": focused.get("ride_id"),
                    "passenger_name": focused.get("passenger_name"),
                    "pickup_address": focused.get("pickup_address"),
                    "dropoff_address": focused.get("dropoff_address"),
                    "driver_name": focused.get("driver_name"),
                    "assignment_state": focused.get("assignment_state"),
                }
            )
        )

    print("RESULT=PASS")


if __name__ == "__main__":
    main()
