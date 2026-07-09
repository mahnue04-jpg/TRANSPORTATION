"""Temporary debug for rider customer-request dispatch flow."""
import httpx
from datetime import datetime, timezone
from app.auth import SEED_PASSWORD, ensure_auth_schema, seed_default_users
from app.db.session import SessionLocal
from app.modules.health_isf import service as hs

ensure_auth_schema()
seed_default_users()
BASE = "http://127.0.0.1:8010"
suffix = datetime.now(timezone.utc).strftime("%H%M%S")
r = httpx.post(f"{BASE}/api/auth/login", json={"email": "rider@amicor.local", "password": SEED_PASSWORD}, timeout=60)
r.raise_for_status()
rh = {"Authorization": f"Bearer {r.json()['access_token']}"}
create = httpx.post(
    f"{BASE}/api/health-isf/customer-requests",
    headers=rh,
    json={
        "rider_name": f"Debug {suffix}",
        "rider_phone": f"646555{suffix[-4:]}",
        "pickup_address": f"100 Pickup {suffix}",
        "dropoff_address": f"200 Dropoff {suffix}",
        "ride_type": "healthcare",
        "recurring": False,
    },
    timeout=60,
)
print("create", create.status_code, create.text[:300])
if create.status_code != 201:
    raise SystemExit(1)
row = create.json()
ride_id = row["ride_id"]
req_id = row["id"]
print("dispatch_status", row.get("dispatch_status"))

d = httpx.post(f"{BASE}/api/auth/login", json={"email": "dispatcher@amicor.local", "password": SEED_PASSWORD}, timeout=60)
dh = {"Authorization": f"Bearer {d.json()['access_token']}"}
approve = httpx.post(f"{BASE}/api/health-isf/dispatcher/customer-requests/{req_id}/approve", headers=dh, timeout=60)
print("approve", approve.status_code, approve.text[:400])
drivers = httpx.get(f"{BASE}/api/health-isf/drivers", headers=dh, timeout=60).json()
james = next(x for x in drivers if x.get("name") == "James Smith")
print("james", james["id"], james.get("availability_state"), james.get("status"))
auto = httpx.post(
    f"{BASE}/api/health-isf/dispatcher/customer-requests/{req_id}/auto-dispatch",
    headers=dh,
    json={"offer_timeout_seconds": 120},
    timeout=60,
)
print("auto", auto.status_code, auto.text[:500])
if auto.status_code == 200:
    accept = httpx.post(
        f"{BASE}/api/health-isf/drivers/{james['id']}/accept-ride",
        headers=dh,
        json={"ride_id": ride_id},
        timeout=60,
    )
    print("accept", accept.status_code, accept.text[:300])
