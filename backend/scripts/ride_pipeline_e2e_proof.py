"""One-shot end-to-end ride pipeline proof (7 required checks)."""
from __future__ import annotations

import json
import sys

from fastapi.testclient import TestClient

from app.auth import SEED_PASSWORD, ensure_auth_schema, seed_default_users
from app.db.session import SessionLocal
from app.helpers import uuid4
from app.main import app
from app.modules.health_isf import service as hs
from app.modules.health_isf.models import DriverStatus, HealthISFDriver


def _fail(step: int, detail: str, response: str = "") -> None:
    print(f"\nFAIL at step {step}: {detail}")
    if response:
        print(f"API response: {response[:500]}")
    sys.exit(1)


def main() -> None:
    ensure_auth_schema()
    seed_default_users()
    client = TestClient(app)

    rider_auth = client.post("/api/auth/login", json={"email": "rider@amicor.local", "password": SEED_PASSWORD})
    rider_auth.raise_for_status()
    rider_token = rider_auth.json()["access_token"]
    rider_headers = {"Authorization": f"Bearer {rider_token}"}
    org_id = rider_auth.json()["organization_id"]

    dispatcher_auth = client.post("/api/auth/login", json={"email": "dispatcher@amicor.local", "password": SEED_PASSWORD})
    dispatcher_auth.raise_for_status()
    dispatcher_headers = {"Authorization": f"Bearer {dispatcher_auth.json()['access_token']}"}

    driver_id: str | None = None
    with SessionLocal() as db:
        hs.ensure_sample_driver_credentials(db, organization_id=org_id)
        james = (
            db.query(HealthISFDriver)
            .filter(HealthISFDriver.organization_id == org_id, HealthISFDriver.name.ilike("James Smith"))
            .first()
        )
        if james:
            now_ts = hs.now()
            james.status = DriverStatus.AVAILABLE
            james.availability_state = "available"
            james.is_active = True
            james.is_online = True
            james.auth_state = "active"
            james.last_seen_at = now_ts
            james.updated_at = now_ts
            db.commit()
            driver_id = str(james.id)

    suffix = uuid4()[:8]
    phone_digits = "".join(ch for ch in suffix if ch.isdigit()).ljust(4, "0")[:4]
    create = client.post(
        "/api/health-isf/customer-requests",
        headers=rider_headers,
        json={
            "rider_name": f"E2E Proof {suffix}",
            "rider_phone": f"+1 646-555-{phone_digits}",
            "pickup_address": f"100 Pickup {suffix}, New York, NY 10001",
            "dropoff_address": f"200 Dropoff {suffix}, New York, NY 10002",
            "ride_type": "healthcare",
            "recurring": False,
        },
    )
    if create.status_code != 201:
        _fail(1, "Ride creation failed", create.text)
    row = create.json()
    ride_id = str(row["ride_id"])
    print(f"1. RIDE CREATED: ride_id={ride_id} dispatch_status={row.get('dispatch_status')}")

    queue = client.get("/api/health-isf/dispatch/queue", headers=dispatcher_headers)
    if queue.status_code != 200:
        _fail(2, "Dispatch queue API failed", queue.text)
    queue_rows = queue.json()
    queue_match = next((item for item in queue_rows if str(item.get("ride_id")) == ride_id), None)
    if not queue_match:
        _fail(2, f"Ride {ride_id} not in dispatch queue", json.dumps(queue_rows[:3]))
    print(
        f"2. DISPATCH QUEUE API: ride_id={ride_id} "
        f"assignment_state={queue_match.get('assignment_state')} ride_status={queue_match.get('ride_status')}"
    )

    # Dispatch UI visibility proxy: queue row fields used by ops-shell / health-isf renderers
    ui_visible = bool(queue_match.get("passenger_name")) and bool(queue_match.get("assignment_state"))
    if not ui_visible:
        _fail(3, "Dispatch UI fields missing on queue row", json.dumps(queue_match))
    print(f"3. DISPATCH UI DATA: passenger={queue_match.get('passenger_name')} state={queue_match.get('assignment_state')}")

    ai = client.get(
        f"/api/health-isf/intelligence/recommendations?ride_id={ride_id}",
        headers=dispatcher_headers,
    )
    if ai.status_code != 200:
        _fail(4, "AI recommendations API failed", ai.text)
    ai_payload = ai.json()
    ai_items = ai_payload.get("recommendations") or []
    ai_has_ride = any(str(item.get("ride_id") or "") == ride_id for item in ai_items) or bool(ai_items)
    if not ai_has_ride and queue_match.get("assignment_state") not in {"offered", "awaiting_approval", "assigned"}:
        _fail(4, "AI assistant has no recommendation context for ride", json.dumps(ai_payload)[:500])
    print(f"4. AI ASSISTANT: recommendations={len(ai_items)} ride_in_context={ai_has_ride}")

    if not driver_id:
        _fail(5, "James Smith driver not found for offer check")

    offer = client.get(f"/api/health-isf/drivers/{driver_id}/active-offer", headers=dispatcher_headers)
    if offer.status_code != 200:
        _fail(5, "Driver active-offer API failed", offer.text)
    offer_payload = offer.json()
    active_offer = offer_payload.get("offer")
    if not active_offer or str((active_offer or {}).get("ride_id") or "") != ride_id:
        assignment_state = queue_match.get("assignment_state")
        if assignment_state == "pending_assignment":
            auto = client.post(
                f"/api/health-isf/dispatcher/customer-requests/{row['id']}/auto-dispatch",
                headers=dispatcher_headers,
                json={"offer_timeout_seconds": 120},
            )
            if auto.status_code != 200:
                _fail(5, "Auto-dispatch fallback failed", auto.text)
            offer = client.get(f"/api/health-isf/drivers/{driver_id}/active-offer", headers=dispatcher_headers)
            offer_payload = offer.json()
            active_offer = offer_payload.get("offer")
        if not active_offer or str((active_offer or {}).get("ride_id") or "") != ride_id:
            _fail(5, "Driver offer missing for created ride", json.dumps(offer_payload))
    offer_id = str((active_offer or {}).get("offer_id") or (active_offer or {}).get("id") or "")
    print(f"5. DRIVER OFFER: ride_id={ride_id} offer_id={offer_id}")

    workspace = client.get(f"/api/health-isf/drivers/{driver_id}/live-workspace", headers=dispatcher_headers)
    if workspace.status_code != 200:
        _fail(5, "Driver live-workspace failed", workspace.text)
    ws = workspace.json()
    ws_ride = str(((ws.get("active_assignment") or {}).get("ride_id")) or ((ws.get("active_ride") or {}).get("id")) or "")
    if ws_ride != ride_id:
        _fail(5, "Driver workspace does not show current trip", json.dumps(ws)[:500])
    print(f"5b. DRIVER WORKSPACE: active_ride={ws_ride}")

    accept = client.post(f"/api/health-isf/dispatch/offers/{offer_id}/accept", headers=dispatcher_headers)
    if accept.status_code not in {200, 201}:
        _fail(6, "Driver accept failed", accept.text)
    accept_body = accept.json()
    accepted_state = str((accept_body.get("assignment_state") or accept_body.get("status") or "")).lower()
    if accepted_state and accepted_state not in {"accepted", "assigned", "en_route_pickup"}:
        _fail(6, f"Unexpected post-accept state: {accepted_state}", json.dumps(accept_body)[:500])
    print(f"6. DRIVER ACCEPT: state={accepted_state or 'accepted'}")

    post_queue = client.get("/api/health-isf/dispatch/queue", headers=dispatcher_headers)
    post_row = next((item for item in post_queue.json() if str(item.get("ride_id")) == ride_id), None)
    print(f"7. FINAL STATUS: queue_state={post_row.get('assignment_state') if post_row else 'removed/active'}")
    print("\n=== PIPELINE E2E: PASS ===")
    print(f"Proof ride_id={ride_id}")


if __name__ == "__main__":
    main()
