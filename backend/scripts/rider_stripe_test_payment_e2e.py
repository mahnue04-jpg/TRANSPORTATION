"""One-shot Stripe TEST MODE rider private-pay E2E. Does not print secrets."""
from __future__ import annotations

import os
import sys
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
BACKEND_ROOT = SCRIPT_DIR.parent
sys.path.insert(0, str(BACKEND_ROOT))


def _load_test_keys() -> tuple[str, str]:
    sk = os.getenv("STRIPE_SECRET_KEY", "").strip()
    pk = os.getenv("STRIPE_PUBLISHABLE_KEY", "").strip()
    candidates = [
        Path.home() / ".config" / "stripe" / "config.toml",
        Path.home() / "AppData" / "Roaming" / "stripe" / "config.toml",
    ]
    for cfg in candidates:
        if not cfg.exists():
            continue
        text = cfg.read_text(encoding="utf-8")
        for line in text.splitlines():
            s = line.strip()
            if s.startswith("test_mode_api_key") and not sk:
                sk = s.split("=", 1)[1].strip().strip("'").strip('"')
            if s.startswith("test_mode_pub_key") and not pk:
                pk = s.split("=", 1)[1].strip().strip("'").strip('"')
    envp = BACKEND_ROOT.parent / ".env"
    if envp.exists():
        for line in envp.read_text(encoding="utf-8", errors="ignore").splitlines():
            if line.startswith("STRIPE_SECRET_KEY=") and not sk:
                sk = line.split("=", 1)[1].strip().strip('"').strip("'")
            if line.startswith("STRIPE_PUBLISHABLE_KEY=") and not pk:
                pk = line.split("=", 1)[1].strip().strip('"').strip("'")
            if line.startswith("STRIPE_PAYMENT_WEBHOOK_SECRET=") and not os.getenv(
                "STRIPE_PAYMENT_WEBHOOK_SECRET"
            ):
                os.environ["STRIPE_PAYMENT_WEBHOOK_SECRET"] = (
                    line.split("=", 1)[1].strip().strip('"').strip("'")
                )
    return sk, pk


def main() -> int:
    sk, pk = _load_test_keys()
    if not sk.startswith("sk_test_") or not pk.startswith("pk_test_"):
        print("E2E_PASS=false DETAIL=missing_stripe_test_keys")
        return 1
    os.environ["STRIPE_SECRET_KEY"] = sk
    os.environ["STRIPE_PUBLISHABLE_KEY"] = pk
    os.environ.setdefault("STRIPE_PAYMENT_WEBHOOK_SECRET", "whsec_amicor_local_e2e_only")
    os.environ["AMICOR_PUBLIC_URL"] = "https://amicor-health-isf-py.onrender.com"

    from fastapi.testclient import TestClient
    from stripe import StripeClient

    from app.auth import SEED_PASSWORD, ensure_auth_schema, seed_default_users
    from app.db.models import User as PlatformUser
    from app.db.session import SessionLocal
    from app.helpers import now, uuid4
    from app.main import app
    from app.modules.health_isf.models import (
        CustomerRequestStatus,
        HealthISFCustomerRideRequest,
        HealthISFProvider,
        HealthISFRide,
        RideStatus,
    )
    from app.modules.payments.models import (
        PAYMENT_SUCCEEDED,
        AmicorCustomerPayment,
        ensure_payments_test_schema,
    )
    from app.modules.payments.rider_checkout import (
        LiveStripePaymentIntentClient,
        get_stripe_payment_client,
        set_stripe_payment_client_override,
    )
    from app.modules.payments.stripe_payments import process_verified_payment_event

    ensure_auth_schema()
    seed_default_users()
    ensure_payments_test_schema()
    set_stripe_payment_client_override(None)
    client = get_stripe_payment_client()
    assert isinstance(client, LiveStripePaymentIntentClient)

    tc = TestClient(app)
    login = tc.post(
        "/api/auth/login",
        json={"email": "dispatcher@amicor.local", "password": SEED_PASSWORD},
    )
    assert login.status_code == 200, login.text
    token = login.json().get("access_token") or login.json().get("token")
    headers = {"Authorization": f"Bearer {token}"}

    with SessionLocal() as db:
        user = db.query(PlatformUser).filter(PlatformUser.email == "dispatcher@amicor.local").one()
        org = str(user.organization_id)
        if not db.query(HealthISFProvider).filter(HealthISFProvider.organization_id == org).first():
            db.add(
                HealthISFProvider(
                    id=uuid4(),
                    organization_id=org,
                    name="E2E Clinic",
                    address="1 Main",
                    phone="6125550100",
                    service_type="clinic",
                    is_active=True,
                    created_at=now(),
                    updated_at=now(),
                )
            )
            db.commit()

    checkout = tc.post(
        "/api/payments/rider/checkout",
        headers=headers,
        json={
            "rider_name": "Stripe E2E Rider",
            "rider_phone": "6125550111",
            "pickup_address": "100 Nicollet Mall, Minneapolis, MN",
            "dropoff_address": "4300 Glumack Dr, St Paul, MN",
            "ride_type": "healthcare",
            "pickup_latitude": 44.9778,
            "pickup_longitude": -93.2650,
            "dropoff_latitude": 44.8848,
            "dropoff_longitude": -93.2223,
        },
    )
    assert checkout.status_code == 200, checkout.text
    body = checkout.json()
    assert body["return_url"].startswith("https://amicor-health-isf-py.onrender.com/app/riders?")
    assert "payment_return=1" in body["return_url"]
    assert body["client_secret"]
    pi = body["stripe_payment_intent_id"]
    print(f"CHECKOUT_OK pi_prefix={pi[:10]} return_url_ok=true")

    sc = StripeClient(sk)
    confirmed = sc.v1.payment_intents.confirm(
        pi,
        {
            "payment_method": "pm_card_visa",
            "return_url": body["return_url"],
        },
    )
    status = confirmed.get("status") if isinstance(confirmed, dict) else getattr(confirmed, "status", None)
    print(f"CONFIRM_STATUS {status}")
    assert status in {"succeeded", "requires_action", "processing"}, status

    event = {
        "id": f"evt_e2e_{uuid4().replace('-', '')[:18]}",
        "object": "event",
        "type": "payment_intent.succeeded",
        "data": {
            "object": {
                "id": pi,
                "object": "payment_intent",
                "amount": body["amount_minor"],
                "amount_received": body["amount_minor"],
                "currency": "usd",
                "status": "succeeded",
                "metadata": {
                    "service_type": "RIDE",
                    "ride_id": body["ride_id"],
                    "request_id": body["request_id"],
                    "internal_service_id": body["ride_id"],
                },
            }
        },
    }
    with SessionLocal() as db:
        result = process_verified_payment_event(db, event)
        print(
            f"WEBHOOK_RESULT {result.get('processing_result')} duplicate={result.get('duplicate')}"
        )
        result2 = process_verified_payment_event(db, event)
        print(f"WEBHOOK_REPLAY_DUP {result2.get('duplicate')}")
        pay = db.query(AmicorCustomerPayment).filter_by(stripe_payment_intent_id=pi).one()
        ride = db.query(HealthISFRide).filter_by(id=body["ride_id"]).one()
        req = db.query(HealthISFCustomerRideRequest).filter_by(id=body["request_id"]).one()
        assert pay.payment_status == PAYMENT_SUCCEEDED
        assert pay.ride_id == body["ride_id"]
        assert ride.lifecycle_state != RideStatus.AWAITING_PAYMENT.value
        assert req.dispatch_status != CustomerRequestStatus.AWAITING_PAYMENT.value
        print(
            "DB_PAID=true",
            f"ride={body['ride_id'][:8]}",
            f"lifecycle={ride.lifecycle_state}",
            f"dispatch={req.dispatch_status}",
        )

    status_api = tc.get(f"/api/payments/rider/payment-status/{body['request_id']}", headers=headers)
    assert status_api.status_code == 200
    assert status_api.json()["payment_status"] == "succeeded"
    assert status_api.json()["released_to_dispatch"] is True
    print("STATUS_API_OK")
    print("E2E_PASS=true")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as exc:
        print(f"E2E_PASS=false DETAIL={type(exc).__name__}: {exc}")
        raise
