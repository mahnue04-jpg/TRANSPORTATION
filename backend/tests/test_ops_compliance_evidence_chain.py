from __future__ import annotations

import hashlib
from datetime import datetime, timedelta, timezone
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient

from app.auth import SEED_PASSWORD, ensure_auth_schema, seed_default_users
from app.db.models import ComplianceExportBundle, ComplianceSignedAccessGrant, ComplianceSupervisorHandoffEvent
from app.db.session import SessionLocal
from app.helpers import json_dumps, json_loads_or
from app.main import app


@pytest.fixture(scope="module")
def client() -> TestClient:
    ensure_auth_schema()
    seed_default_users()
    return TestClient(app)


def _login(client: TestClient, email: str) -> str:
    response = client.post(
        "/api/auth/login",
        json={"email": email, "password": SEED_PASSWORD},
    )
    assert response.status_code == 200, response.text
    return response.json()["access_token"]


def _headers(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


def _upsert_profile(client: TestClient, token: str, driver_id: str) -> None:
    response = client.post(
        "/api/ops/compliance/profile/upsert",
        headers=_headers(token),
        json={
            "driver_id": driver_id,
            "onboarding_status": "pending",
            "compliance_status": "pending",
            "approval_status": "pending",
            "background_check_status": "pending",
            "medical_transport_certified": False,
            "training_completed": False,
        },
    )
    assert response.status_code == 200, response.text


def _upload_doc(client: TestClient, token: str, driver_id: str, doc_type: str, exp_days: int = 30) -> str:
    response = client.post(
        "/api/ops/compliance/documents/upload-metadata",
        headers=_headers(token),
        json={
            "driver_id": driver_id,
            "type": doc_type,
            "expiration_date": (datetime.now(timezone.utc) + timedelta(days=exp_days)).isoformat(),
        },
    )
    assert response.status_code == 200, response.text
    return str(response.json()["document"]["document_id"])


def _append_evidence(client: TestClient, token: str, driver_id: str, document_id: str, **extra: object) -> dict:
    body = {
        "driver_id": driver_id,
        "document_id": document_id,
        "mime_type": "application/pdf",
        "storage_provider": "secure_local",
        "retention_class": "regulatory",
        "encryption_status": "encrypted_at_rest",
    }
    body.update(extra)
    response = client.post(
        "/api/ops/compliance/documents/evidence/append",
        headers=_headers(token),
        json=body,
    )
    assert response.status_code == 200, response.text
    return response.json()


def test_auth_boundary_evidence_endpoints(client: TestClient) -> None:
    response = client.post(
        "/api/ops/compliance/documents/evidence/append",
        json={"driver_id": "d1", "document_id": "doc-1"},
    )
    assert response.status_code in {401, 403}


def test_immutable_linkage_and_integrity(client: TestClient) -> None:
    admin_token = _login(client, "admin@amicor.local")
    driver_id = f"driver-{uuid4().hex[:8]}"
    _upsert_profile(client, admin_token, driver_id)
    doc1 = _upload_doc(client, admin_token, driver_id, "driver_license")

    _append_evidence(client, admin_token, driver_id, doc1, lineage_root_id=doc1)

    doc2 = _upload_doc(client, admin_token, driver_id, "driver_license")
    _append_evidence(client, admin_token, driver_id, doc2, replaces_document_id=doc1, lineage_root_id=doc1)

    integrity = client.get(
        f"/api/ops/compliance/documents/integrity?document_id={doc2}",
        headers=_headers(admin_token),
    )
    assert integrity.status_code == 200, integrity.text
    payload = integrity.json()
    assert payload["integrity_valid"] is True
    assert payload["replay_safe"] is True

    summary = client.get("/api/ops/compliance/dashboard-summary", headers=_headers(admin_token))
    assert summary.status_code == 200, summary.text
    phase25 = (summary.json().get("phase25") or {})
    lineage = phase25.get("document_lineage_viewer") or []
    assert any(row.get("lineage_root_id") == doc1 for row in lineage)


def test_signed_access_expiration_and_revoke(client: TestClient) -> None:
    admin_token = _login(client, "admin@amicor.local")
    driver_id = f"driver-{uuid4().hex[:8]}"
    _upsert_profile(client, admin_token, driver_id)
    doc = _upload_doc(client, admin_token, driver_id, "insurance")
    _append_evidence(client, admin_token, driver_id, doc)

    grant_resp = client.post(
        "/api/ops/compliance/documents/signed-access/generate",
        headers=_headers(admin_token),
        json={"document_id": doc, "access_reason": "regulatory retrieval", "ttl_minutes": 5},
    )
    assert grant_resp.status_code == 200, grant_resp.text
    signed_access_id = str(grant_resp.json()["signed_access_id"])

    with SessionLocal() as db:
        row = db.query(ComplianceSignedAccessGrant).filter(ComplianceSignedAccessGrant.signed_access_id == signed_access_id).first()
        assert row is not None
        row.expires_at = datetime.now(timezone.utc) - timedelta(minutes=1)
        db.commit()

    expired = client.post(
        "/api/ops/compliance/documents/signed-access/retrieve",
        headers=_headers(admin_token),
        json={"signed_access_id": signed_access_id, "access_reason": "test expired path"},
    )
    assert expired.status_code == 403
    assert "expired" in expired.text

    grant_resp_2 = client.post(
        "/api/ops/compliance/documents/signed-access/generate",
        headers=_headers(admin_token),
        json={"document_id": doc, "access_reason": "second grant", "ttl_minutes": 5},
    )
    signed_access_id_2 = str(grant_resp_2.json()["signed_access_id"])
    revoke = client.post(
        "/api/ops/compliance/documents/signed-access/revoke",
        headers=_headers(admin_token),
        json={"signed_access_id": signed_access_id_2},
    )
    assert revoke.status_code == 200, revoke.text
    revoked_access = client.post(
        "/api/ops/compliance/documents/signed-access/retrieve",
        headers=_headers(admin_token),
        json={"signed_access_id": signed_access_id_2, "access_reason": "revoked path"},
    )
    assert revoked_access.status_code == 403


def test_role_scoped_retrieval_medical_limited(client: TestClient) -> None:
    admin_token = _login(client, "admin@amicor.local")
    medical_token = _login(client, "medical@amicor.local")

    driver_id = f"driver-{uuid4().hex[:8]}"
    _upsert_profile(client, admin_token, driver_id)
    doc = _upload_doc(client, admin_token, driver_id, "insurance")
    _append_evidence(client, admin_token, driver_id, doc)

    grant = client.post(
        "/api/ops/compliance/documents/signed-access/generate",
        headers=_headers(admin_token),
        json={"document_id": doc, "access_reason": "medical review", "ttl_minutes": 10},
    )
    assert grant.status_code == 200, grant.text

    response = client.post(
        "/api/ops/compliance/documents/signed-access/retrieve",
        headers=_headers(medical_token),
        json={"signed_access_id": grant.json()["signed_access_id"], "access_reason": "medical attempt"},
    )
    assert response.status_code == 403


def test_export_checksum_integrity(client: TestClient) -> None:
    admin_token = _login(client, "admin@amicor.local")
    response = client.post(
        "/api/ops/compliance/exports/generate",
        headers=_headers(admin_token),
        json={"export_scope": "driver_regulatory_bundle", "retention_class": "regulatory"},
    )
    assert response.status_code == 200, response.text
    export_id = response.json()["export_id"]
    api_checksum = response.json()["checksum"]

    with SessionLocal() as db:
        row = db.query(ComplianceExportBundle).filter(ComplianceExportBundle.export_id == export_id).first()
        assert row is not None
        payload = json_loads_or(row.payload_json, {})
        recomputed = hashlib.sha256(json_dumps(payload).encode("utf-8")).hexdigest()
        assert recomputed == row.checksum
        assert recomputed == api_checksum


def test_supervisor_dual_review_enforcement(client: TestClient) -> None:
    support_token = _login(client, "driversupport@amicor.local")
    supervisor_token = _login(client, "supervisor@amicor.local")
    driver_id = f"driver-{uuid4().hex[:8]}"
    _upsert_profile(client, support_token, driver_id)

    invalid_secondary = client.post(
        "/api/ops/compliance/supervisor-handoff/transition",
        headers=_headers(supervisor_token),
        json={
            "driver_id": driver_id,
            "stage": "secondary_confirmation",
            "escalation_notes": "needs second signoff",
        },
    )
    assert invalid_secondary.status_code == 422

    non_supervisor_approve = client.post(
        "/api/ops/compliance/supervisor-handoff/transition",
        headers=_headers(support_token),
        json={
            "driver_id": driver_id,
            "stage": "approved",
            "escalation_notes": "attempt without supervisor",
        },
    )
    assert non_supervisor_approve.status_code == 403


def test_retention_classification_behavior(client: TestClient) -> None:
    support_token = _login(client, "driversupport@amicor.local")
    supervisor_token = _login(client, "supervisor@amicor.local")
    driver_id = f"driver-{uuid4().hex[:8]}"
    _upsert_profile(client, support_token, driver_id)
    doc = _upload_doc(client, support_token, driver_id, "certification")
    _append_evidence(client, support_token, driver_id, doc, retention_class="legal_hold")

    hold = client.post(
        "/api/ops/compliance/retention/apply",
        headers=_headers(support_token),
        json={
            "document_id": doc,
            "retention_class": "legal_hold",
            "action_type": "retention_class_applied",
            "legal_hold": True,
        },
    )
    assert hold.status_code == 200, hold.text

    release_fail = client.post(
        "/api/ops/compliance/retention/apply",
        headers=_headers(support_token),
        json={
            "document_id": doc,
            "retention_class": "operational",
            "action_type": "release_legal_hold",
            "release_reason": "not allowed",
        },
    )
    assert release_fail.status_code == 403

    release_ok = client.post(
        "/api/ops/compliance/retention/apply",
        headers=_headers(supervisor_token),
        json={
            "document_id": doc,
            "retention_class": "operational",
            "action_type": "release_legal_hold",
            "release_reason": "manual supervised release",
        },
    )
    assert release_ok.status_code == 200, release_ok.text


def test_replay_safe_hydration_and_append_sequence(client: TestClient) -> None:
    supervisor_token = _login(client, "supervisor@amicor.local")
    driver_id = f"driver-{uuid4().hex[:8]}"
    _upsert_profile(client, supervisor_token, driver_id)

    for stage in ["review_started", "compliance_verified", "supervisor_review"]:
        response = client.post(
            "/api/ops/compliance/supervisor-handoff/transition",
            headers=_headers(supervisor_token),
            json={"driver_id": driver_id, "stage": stage, "escalation_notes": f"{stage} note"},
        )
        assert response.status_code == 200, response.text

    summary = client.get("/api/ops/compliance/dashboard-summary", headers=_headers(supervisor_token))
    assert summary.status_code == 200, summary.text
    payload = summary.json()
    assert payload["governance"]["replay_safe"] is True
    assert payload["governance"]["append_only"] is True

    queue = (((payload.get("phase25") or {}).get("supervisor_review_queue")) or [])
    sequences = [int(row.get("sequence", 0) or 0) for row in queue if row.get("driver_id") == driver_id]
    if sequences:
        assert sequences == sorted(sequences, reverse=True)

    with SessionLocal() as db:
        rows = (
            db.query(ComplianceSupervisorHandoffEvent)
            .filter(ComplianceSupervisorHandoffEvent.target_driver_id == driver_id)
            .order_by(ComplianceSupervisorHandoffEvent.sequence.asc())
            .all()
        )
        assert len(rows) >= 3
        ordered = [row.sequence for row in rows]
        assert ordered == sorted(ordered)


def test_policy_pack_routing(client: TestClient) -> None:
    compliance_token = _login(client, "compliance@amicor.local")
    ok = client.post(
        "/api/ops/compliance/policy-pack/evaluate",
        headers=_headers(compliance_token),
        json={"jurisdiction": "Minnesota", "transport_type": "non_emergency", "medical_transport_class": "NEMT"},
    )
    assert ok.status_code == 200, ok.text
    pack = ok.json()["policy_pack"]
    assert pack["jurisdiction"] == "Minnesota"
    assert pack["operator_configurable"] is True

    invalid = client.post(
        "/api/ops/compliance/policy-pack/evaluate",
        headers=_headers(compliance_token),
        json={"jurisdiction": "Illinois", "transport_type": "non_emergency", "medical_transport_class": "NEMT"},
    )
    assert invalid.status_code == 422
