"""Financial engine auto-settlement on trip completion."""
from fastapi.testclient import TestClient
import pytest

from app.auth import SEED_PASSWORD, ensure_auth_schema, seed_default_users
from app.db.models import User as PlatformUser
from app.db.session import SessionLocal
from app.helpers import uuid4
from app.main import app
from app.modules.health_isf.financial_engine import TripFinancialEngine
from app.modules.health_isf.models import (
    DriverStatus,
    HealthISFBillingHandoff,
    HealthISFClaim,
    HealthISFDriver,
    HealthISFPaymentTransaction,
    HealthISFProvider,
    HealthISFRide,
    HealthISFTripDocument,
    HealthISFTripFinancialRecord,
    HealthISFWorkflowAuditLog,
)


@pytest.fixture(scope="module")
def client() -> TestClient:
    ensure_auth_schema()
    seed_default_users()
    return TestClient(app)


def _login_dispatcher(client: TestClient) -> dict:
    response = client.post(
        "/api/auth/login",
        json={"email": "dispatcher@amicor.local", "password": SEED_PASSWORD},
    )
    assert response.status_code == 200, response.text
    payload = response.json()
    token = payload.get("access_token") or payload.get("token")
    assert token
    return {"access_token": token}


def _dispatcher_org_id() -> str:
    with SessionLocal() as db:
        user = db.query(PlatformUser).filter(PlatformUser.email == "dispatcher@amicor.local").first()
        assert user is not None
        assert user.organization_id is not None
        return str(user.organization_id)


def _ensure_provider(organization_id: str) -> str:
    with SessionLocal() as db:
        existing = (
            db.query(HealthISFProvider)
            .filter(HealthISFProvider.organization_id == organization_id)
            .order_by(HealthISFProvider.created_at.desc())
            .first()
        )
        if existing:
            return str(existing.id)
        provider = HealthISFProvider(
            id=uuid4(),
            organization_id=organization_id,
            name=f"Financial Provider {uuid4()[:6]}",
            address="800 Financial Ave",
            phone="212-555-6499",
            service_type="clinic",
            is_active=True,
        )
        db.add(provider)
        db.commit()
        return str(provider.id)


def _ensure_driver(organization_id: str) -> str:
    with SessionLocal() as db:
        driver = HealthISFDriver(
            id=uuid4(),
            organization_id=organization_id,
            name=f"Financial Driver {uuid4()[:6]}",
            phone=f"212-555-{str(uuid4()).replace('-', '')[:4]}",
            vehicle_type="sedan",
            vehicle_plate=f"FN-{uuid4()[:5].upper()}",
            status=DriverStatus.AVAILABLE,
            is_active=True,
            rating=4.9,
        )
        db.add(driver)
        db.commit()
        return str(driver.id)


def _create_healthcare_request(client: TestClient, headers: dict) -> dict:
    response = client.post(
        "/api/health-isf/customer-requests",
        headers=headers,
        json={
            "rider_name": f"Financial Rider {uuid4()[:6]}",
            "rider_phone": "+1 212-555-8800",
            "pickup_address": "100 Financial Pickup St",
            "dropoff_address": "200 Financial Dropoff Ave",
            "ride_type": "healthcare",
        },
    )
    assert response.status_code == 201, response.text
    return response.json()


def _assign_and_complete(client: TestClient, headers: dict, request_id: str, driver_id: str, ride_id: str) -> None:
    approve = client.post(f"/api/health-isf/dispatcher/customer-requests/{request_id}/approve", headers=headers)
    assert approve.status_code == 200, approve.text
    assign = client.post(
        f"/api/health-isf/dispatcher/customer-requests/{request_id}/assign-driver",
        headers=headers,
        json={"driver_id": driver_id},
    )
    assert assign.status_code == 200, assign.text
    for state in [
        "en_route_pickup",
        "arrived_pickup",
        "rider_loaded",
        "trip_in_progress",
        "arrived_destination",
        "completed",
    ]:
        step = client.post(
            f"/api/health-isf/drivers/{driver_id}/route-progress",
            headers=headers,
            json={"ride_id": ride_id, "target_state": state},
        )
        assert step.status_code == 200, step.text


def test_financial_engine_on_trip_completion(client: TestClient) -> None:
    auth = _login_dispatcher(client)
    headers = {"Authorization": f"Bearer {auth['access_token']}"}
    org_id = _dispatcher_org_id()
    _ensure_provider(org_id)
    driver_id = _ensure_driver(org_id)

    req = _create_healthcare_request(client, headers)
    _assign_and_complete(client, headers, req["id"], driver_id, req["ride_id"])

    summary = client.get(f"/api/health-isf/rides/{req['ride_id']}/financial-summary", headers=headers)
    assert summary.status_code == 200, summary.text
    financial = summary.json()
    assert financial["ride_price_usd"] > 0
    assert financial["driver_pay_usd"] > 0
    assert financial["platform_revenue_usd"] >= 0
    assert financial["payment_transaction_id"]
    assert financial["payout_id"]
    assert financial["billing_handoff_id"]
    assert financial["claim_id"]
    assert financial["is_healthcare"] is True

    handoff = client.get(f"/api/health-isf/rides/{req['ride_id']}/completion-handoff", headers=headers)
    assert handoff.status_code == 200, handoff.text
    handoff_payload = handoff.json()
    assert handoff_payload["ride_price_usd"] == financial["ride_price_usd"]
    assert handoff_payload["driver_pay_usd"] == financial["driver_pay_usd"]

    earnings = client.get(f"/api/health-isf/drivers/{driver_id}/earnings", headers=headers)
    assert earnings.status_code == 200, earnings.text
    assert earnings.json()["earnings_lifetime_usd"] >= financial["driver_pay_usd"]

    admin_revenue = client.get("/api/health-isf/operations/admin-revenue", headers=headers)
    assert admin_revenue.status_code == 200, admin_revenue.text
    assert admin_revenue.json()["completed_trip_count"] >= 1

    with SessionLocal() as db:
        record = (
            db.query(HealthISFTripFinancialRecord)
            .filter(HealthISFTripFinancialRecord.ride_id == req["ride_id"])
            .first()
        )
        assert record is not None
        assert db.query(HealthISFPaymentTransaction).filter(HealthISFPaymentTransaction.ride_id == req["ride_id"]).count() == 1
        assert db.query(HealthISFClaim).filter(HealthISFClaim.ride_id == req["ride_id"]).count() == 1
        assert db.query(HealthISFBillingHandoff).filter(HealthISFBillingHandoff.ride_id == req["ride_id"]).count() == 1
        audit = (
            db.query(HealthISFWorkflowAuditLog)
            .filter(
                HealthISFWorkflowAuditLog.organization_id == org_id,
                HealthISFWorkflowAuditLog.event_type == "ai.action.executed",
            )
            .order_by(HealthISFWorkflowAuditLog.created_at.desc())
            .first()
        )
        assert audit is not None
        assert req["ride_id"] in str(audit.payload or "")

    # Idempotent re-run should not duplicate records
    with SessionLocal() as db:
        financial_row = TripFinancialEngine.get_financial_record_for_ride(db, ride_id=req["ride_id"])
        assert financial_row is not None
        before_count = db.query(HealthISFTripFinancialRecord).filter(HealthISFTripFinancialRecord.ride_id == req["ride_id"]).count()
        assert before_count == 1
        ride_row = db.query(HealthISFRide).filter(HealthISFRide.id == req["ride_id"]).first()
        assert ride_row is not None
        TripFinancialEngine.process_trip_completion(db, ride_row)
        db.commit()
        assert (
            db.query(HealthISFTripFinancialRecord)
            .filter(HealthISFTripFinancialRecord.ride_id == req["ride_id"])
            .count()
            == 1
        )
        assert (
            db.query(HealthISFBillingHandoff)
            .filter(HealthISFBillingHandoff.ride_id == req["ride_id"])
            .count()
            == 1
        )
        assert (
            db.query(HealthISFPaymentTransaction)
            .filter(HealthISFPaymentTransaction.ride_id == req["ride_id"])
            .count()
            == 1
        )
        docs = (
            db.query(HealthISFTripDocument)
            .filter(HealthISFTripDocument.ride_id == req["ride_id"])
            .all()
        )
        assert len(docs) == 3
        assert {row.document_type for row in docs} == {
            "trip_receipt",
            "driver_payout_statement",
            "billing_record",
        }
