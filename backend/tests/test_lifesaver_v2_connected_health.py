"""Connected-health and home-test framework tests. Simulation only."""
from __future__ import annotations

import os
from datetime import datetime, timedelta, timezone
from pathlib import Path

os.environ.setdefault("AMICOR_SKIP_WMI_PLATFORM_QUERY", "1")

from fastapi.testclient import TestClient
from sqlalchemy import inspect, text

from app.auth import ensure_auth_schema, seed_default_users
from app.db.session import SessionLocal, engine
from app.main import app
from app.modules.health_isf.models import HealthISFRide
from app.modules.lifesaver.models import LifesaverAuditEvent, ensure_lifesaver_schema
from tests.lifesaver_test_helpers import auth_headers, bootstrap_profile, create_other_org_user, grant_consents

REPO = Path(__file__).resolve().parents[2]
PHASE5 = (
    "connected_device_readings",
    "home_test_status",
    "laboratory_result_documents",
    "provider_sharing",
    "care_circle_health_share",
)


def _client() -> TestClient:
    ensure_auth_schema()
    seed_default_users()
    ensure_lifesaver_schema()
    return TestClient(app)


def _ready(client: TestClient, headers: dict[str, str]) -> None:
    bootstrap_profile(client, headers)
    grant_consents(client, headers, PHASE5 + ("caregiver_sharing", "care_cloud_use", "audit_retention"))


def test_consent_required_and_revocation():
    client = _client()
    rider = auth_headers(client, "rider@amicor.local")
    bootstrap_profile(client, rider)
    client.post(
        "/api/lifesaver/consents",
        headers=rider,
        json={"consent_type": "connected_device_readings", "granted": False},
    )
    denied = client.post(
        "/api/lifesaver/connected-health/devices",
        headers=rider,
        json={"device_type": "thermometer"},
    )
    assert denied.status_code == 403
    grant_consents(client, rider, ("connected_device_readings",))
    created = client.post(
        "/api/lifesaver/connected-health/devices",
        headers=rider,
        json={"device_type": "thermometer", "device_alias": "Kitchen thermometer"},
    )
    assert created.status_code == 200, created.text
    client.post("/api/lifesaver/consents", headers=rider, json={"consent_type": "connected_device_readings", "granted": False})
    blocked = client.get("/api/lifesaver/connected-health/devices", headers=rider)
    assert blocked.status_code == 403


def test_simulated_pair_offline_unsupported_and_reading_review():
    client = _client()
    rider = auth_headers(client, "rider@amicor.local")
    _ready(client, rider)
    device = client.post(
        "/api/lifesaver/connected-health/devices",
        headers=rider,
        json={
            "device_type": "blood_pressure_monitor",
            "serial_last4": "7788",
            "client_request_id": "bp-1",
        },
    ).json()["data"]
    again = client.post(
        "/api/lifesaver/connected-health/devices",
        headers=rider,
        json={"device_type": "blood_pressure_monitor", "client_request_id": "bp-1"},
    ).json()["data"]
    assert again["id"] == device["id"]
    assert device["simulated"] is True
    assert device["real_connection"] is False
    assert device["serial_last4"] == "7788"
    paired = client.post(f"/api/lifesaver/connected-health/devices/{device['id']}/pair", headers=rider)
    assert paired.status_code == 200
    assert paired.json()["data"]["integration_status"] == "CONNECTED"
    offline = client.post(f"/api/lifesaver/connected-health/devices/{device['id']}/offline", headers=rider)
    assert offline.json()["data"]["integration_status"] == "OFFLINE"
    unsupported = client.post(
        "/api/lifesaver/connected-health/devices",
        headers=rider,
        json={"device_type": "unknown_unapproved_sensor"},
    ).json()["data"]
    assert unsupported["integration_status"] == "UNSUPPORTED"
    blocked_pair = client.post(
        f"/api/lifesaver/connected-health/devices/{unsupported['id']}/pair",
        headers=rider,
    )
    assert blocked_pair.status_code == 409
    reading = client.post(
        f"/api/lifesaver/connected-health/devices/{device['id']}/readings",
        headers=rider,
        json={"reading_kind": "blood_pressure", "value_primary": 118, "value_secondary": 76, "flag_for_review": True},
    ).json()["data"]
    assert reading["review_status"] == "NEEDS_HUMAN_REVIEW"
    assert reading["emergency_services_contacted"] is False
    assert reading["diagnosis_generated"] is False


def test_home_test_lifecycle_expire_and_idempotency():
    client = _client()
    rider = auth_headers(client, "rider@amicor.local")
    _ready(client, rider)
    first = client.post(
        "/api/lifesaver/connected-health/kits",
        headers=rider,
        json={"test_category": "urine_collection_placeholder", "client_request_id": "kit-1"},
    ).json()["data"]
    second = client.post(
        "/api/lifesaver/connected-health/kits",
        headers=rider,
        json={"test_category": "urine_collection_placeholder", "client_request_id": "kit-1"},
    ).json()["data"]
    assert first["id"] == second["id"]
    kit_id = first["id"]
    for _ in range(3):
        stepped = client.post(f"/api/lifesaver/connected-health/kits/{kit_id}/transition", headers=rider, json={})
        assert stepped.status_code == 200, stepped.text
    assert stepped.json()["data"]["status"] == "COLLECTED"
    skip = client.post(
        f"/api/lifesaver/connected-health/kits/{kit_id}/transition",
        headers=rider,
        json={"status": "SHIPPED"},
    )
    assert skip.status_code == 409
    expired = client.post(
        "/api/lifesaver/connected-health/kits",
        headers=rider,
        json={
            "test_category": "oral_swab_placeholder",
            "expires_at": (datetime.now(timezone.utc) - timedelta(days=2)).isoformat(),
        },
    ).json()["data"]
    assert expired["status"] == "EXPIRED"
    blocked = client.post(
        f"/api/lifesaver/connected-health/kits/{expired['id']}/transition",
        headers=rider,
        json={},
    )
    assert blocked.status_code == 409


def test_result_intake_and_share_consents():
    client = _client()
    rider = auth_headers(client, "rider@amicor.local")
    bootstrap_profile(client, rider)
    grant_consents(client, rider, ("laboratory_result_documents",))
    client.post("/api/lifesaver/consents", headers=rider, json={"consent_type": "provider_sharing", "granted": False})
    client.post("/api/lifesaver/consents", headers=rider, json={"consent_type": "care_circle_health_share", "granted": False})
    created = client.post(
        "/api/lifesaver/connected-health/results",
        headers=rider,
        json={"source": "user_uploaded", "document_reference": "lab-ref-22", "flag_for_review": True},
    )
    assert created.status_code == 200, created.text
    result = created.json()["data"]
    assert result["diagnosis_generated"] is False
    assert result["emergency_services_contacted"] is False
    assert result["review_status"] == "NEEDS_HUMAN_REVIEW"
    provider = client.post(
        f"/api/lifesaver/connected-health/results/{result['id']}/provider-share",
        headers=rider,
    )
    assert provider.status_code == 403
    circle = client.post(
        f"/api/lifesaver/connected-health/results/{result['id']}/circle-share",
        headers=rider,
    )
    assert circle.status_code == 403
    grant_consents(client, rider, ("provider_sharing", "care_circle_health_share"))
    ok_provider = client.post(
        f"/api/lifesaver/connected-health/results/{result['id']}/provider-share",
        headers=rider,
    )
    assert ok_provider.status_code == 200
    assert ok_provider.json()["data"]["provider_share_status"] == "shared_simulated"
    ok_circle = client.post(
        f"/api/lifesaver/connected-health/results/{result['id']}/circle-share",
        headers=rider,
    )
    assert ok_circle.status_code == 200
    ack = client.post(
        f"/api/lifesaver/connected-health/results/{result['id']}/acknowledge",
        headers=rider,
    )
    assert ack.json()["data"]["user_acknowledged"] is True


def test_tenant_idor_and_audit_redaction():
    client = _client()
    rider = auth_headers(client, "rider@amicor.local")
    _ready(client, rider)
    device = client.post(
        "/api/lifesaver/connected-health/devices",
        headers=rider,
        json={"device_type": "pulse_oximeter"},
    ).json()["data"]
    client.post(
        f"/api/lifesaver/connected-health/devices/{device['id']}/readings",
        headers=rider,
        json={"reading_kind": "spo2", "value_primary": 96.42},
    )
    create_other_org_user()
    other = auth_headers(client, "lifesaver.other@example.local")
    bootstrap_profile(client, other)
    grant_consents(client, other, PHASE5)
    stolen = client.get(
        f"/api/lifesaver/connected-health/devices/{device['id']}/readings",
        headers=other,
    )
    assert stolen.status_code == 404
    audits = client.get("/api/lifesaver/audit", headers=rider)
    assert audits.status_code == 200
    blob = audits.text
    assert "96.42" not in blob
    assert "value_primary" not in blob


def test_hub_summary_and_ecosystem_placeholders():
    client = _client()
    rider = auth_headers(client, "rider@amicor.local")
    _ready(client, rider)
    client.post(
        "/api/lifesaver/connected-health/devices",
        headers=rider,
        json={"device_type": "blood_pressure_monitor"},
    )
    client.post(
        "/api/lifesaver/connected-health/kits",
        headers=rider,
        json={"test_category": "saliva_collection_placeholder"},
    )
    kit = client.get("/api/lifesaver/connected-health/kits", headers=rider).json()["data"][0]
    for _ in range(3):
        client.post(f"/api/lifesaver/connected-health/kits/{kit['id']}/transition", headers=rider, json={})
    summary = client.get("/api/lifesaver/connected-health/hub-summary", headers=rider).json()["data"]
    assert summary["emergency_services_contacted"] is False
    assert summary["diagnoses"] is False
    assert any("simulated" in card.lower() or "collection" in card.lower() for card in summary["cards"])
    twin = client.get("/api/lifesaver/home-hub-agent/twin", headers=rider).json()["data"]
    assert twin.get("emergency_services_contacted") is False
    eco = client.get("/api/lifesaver/connected-health/ecosystem", headers=rider).json()["data"]
    assert eco["activated"] is False
    for hook in eco["hooks"].values():
        assert hook["activated"] is False
        assert hook["writes_external"] is False
        assert hook["real_notification"] is False


def test_no_frozen_writes_or_external_side_effects():
    client = _client()
    rider = auth_headers(client, "rider@amicor.local")
    _ready(client, rider)
    names = set(inspect(engine).get_table_names())
    with SessionLocal() as db:
        rides = db.query(HealthISFRide).count()
        audits = db.query(LifesaverAuditEvent).count()
    freight = 0
    if "nova_freight_shipments" in names:
        with engine.connect() as conn:
            freight = int(conn.execute(text("SELECT COUNT(*) FROM nova_freight_shipments")).scalar() or 0)
    client.post("/api/lifesaver/connected-health/devices", headers=rider, json={"device_type": "weight_scale"})
    client.post(
        "/api/lifesaver/connected-health/results",
        headers=rider,
        json={"source": "externally_supplied", "document_reference": "ref-aa"},
    )
    with SessionLocal() as db:
        assert db.query(HealthISFRide).count() == rides
        assert db.query(LifesaverAuditEvent).count() >= audits
    if "nova_freight_shipments" in names:
        with engine.connect() as conn:
            assert int(conn.execute(text("SELECT COUNT(*) FROM nova_freight_shipments")).scalar() or 0) == freight
    banned = (
        "from app.modules.health_isf",
        "from app.core.nova",
        "import stripe",
        "sk_live_",
        "socket.socket",
    )
    root = REPO / "backend" / "app" / "modules" / "lifesaver" / "connected_health"
    for path in root.rglob("*.py"):
        text_blob = path.read_text(encoding="utf-8")
        for token_name in banned:
            assert token_name not in text_blob, f"{path} contains {token_name}"
    js = (REPO / "backend" / "static" / "lifesaver" / "lifesaver.js").read_text(encoding="utf-8")
    css = (REPO / "backend" / "static" / "lifesaver" / "lifesaver.css").read_text(encoding="utf-8")
    assert "CONNECTED HEALTH" in js
    assert "HOME TESTS" in js
    assert "SIMULATION — NOT CONNECTED TO A REAL MEDICAL DEVICE" in js
    assert "connected-health-panel" in css
    assert "min-height: var(--ls-tap)" in css
