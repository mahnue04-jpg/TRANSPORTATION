"""Phase 2C production secure document storage tests.

Phase 2A/2B activation, dispatch, STS/MHCP, and PII controls must remain intact.
"""
from __future__ import annotations

from datetime import date, timedelta
from io import BytesIO
from types import SimpleNamespace
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import inspect

from app.auth import SEED_PASSWORD, ensure_auth_schema, seed_default_users
from app.db.models import User as PlatformUser
from app.db.session import SessionLocal
from app.helpers import uuid4 as make_uuid
from app.main import app
from app.modules.approval_engine.eligibility import (
    dispatch_gate_enabled,
    driver_blocked_from_live_dispatch,
    sts_mhcp_dispatch_enabled,
)
from app.modules.approval_engine.external_verification import ExternalVerificationRecord
from app.modules.health_isf.models import HealthISFDriver
from app.modules.platform_ops.models import (
    PlatformDriverOnboardingAuditEvent,
    ensure_platform_ops_schema,
)
from app.modules.platform_ops.secure_storage import (
    S3PrivateDocumentStorage,
    SecureStorageNotConfigured,
    assert_production_storage_allowed,
    s3_configuration_status,
    s3_credentials_present,
    s3_endpoint_url,
    secure_document_storage_readiness,
    validate_document_upload,
)
from app.modules.platform_ops.storage import (
    LocalDocumentStorage,
    assert_safe_storage_ref,
    get_document_storage,
)
from app.modules.approval_engine.models import ensure_approval_engine_schema


@pytest.fixture(scope="module")
def client() -> TestClient:
    ensure_auth_schema()
    seed_default_users()
    ensure_platform_ops_schema()
    ensure_approval_engine_schema()
    return TestClient(app)


def _login(client: TestClient, email: str) -> str:
    response = client.post("/api/auth/login", json={"email": email, "password": SEED_PASSWORD})
    assert response.status_code == 200, response.text
    return response.json()["access_token"]


def _auth(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


def _org_id() -> str:
    with SessionLocal() as db:
        user = db.query(PlatformUser).filter(PlatformUser.email == "admin@amicor.local").first()
        assert user and user.organization_id
        return str(user.organization_id)


def _unique_phone() -> str:
    return f"917{uuid4().int % 10_000_000:07d}"


def _complete_payload(org_id: str) -> dict:
    today = date.today()
    return {
        "organization_id": org_id,
        "legal_first_name": "Taylor",
        "legal_last_name": "Applicant",
        "date_of_birth": "1990-04-12",
        "email": f"driver-{uuid4().hex[:8]}@example.com",
        "mobile_phone": _unique_phone(),
        "home_address": "100 Main St",
        "city": "Minneapolis",
        "state": "MN",
        "zip_code": "55401",
        "emergency_contact_name": "Casey Contact",
        "emergency_contact_phone": "612-555-0199",
        "drivers_license_number": "D123456789",
        "license_issuing_state": "MN",
        "license_expiration_date": (today + timedelta(days=400)).isoformat(),
        "years_driving_experience": 8,
        "employment_type": "independent_contractor",
        "declaration_valid_license": True,
        "declaration_mvr_authorization": True,
        "declaration_background_authorization": True,
        "declaration_drug_alcohol_policy": True,
        "declaration_truthful_information": True,
        "electronic_signature": "Taylor Applicant",
        "signed_date": today.isoformat(),
    }


def _create_draft(client: TestClient, org_id: str) -> tuple[str, str]:
    created = client.post(
        "/api/platform-ops/driver-onboarding/applications",
        json=_complete_payload(org_id),
    )
    assert created.status_code == 200, created.text
    return created.json()["application"]["id"], created.json()["applicant_access_token"]


def test_production_refuses_upload_without_secure_storage(client: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("AMICOR_ENVIRONMENT", "production")
    monkeypatch.setenv("PLATFORM_OPS_DOCUMENT_STORAGE", "local_dev")
    org_id = _org_id()
    app_id, token = _create_draft(client, org_id)
    upload = client.post(
        f"/api/platform-ops/driver-onboarding/applications/{app_id}/documents?category=drivers_license_front",
        headers={"X-Applicant-Token": token},
        files={"file": ("placeholder.txt", BytesIO(b"placeholder-not-real-pii"), "text/plain")},
    )
    assert upload.status_code == 503, upload.text
    assert "COMPLIANCE_STORAGE_BLOCKED" in upload.text


def test_production_never_falls_back_to_local_disk(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("AMICOR_ENVIRONMENT", "production")
    monkeypatch.setenv("PLATFORM_OPS_DOCUMENT_STORAGE", "local_dev")
    with pytest.raises(SecureStorageNotConfigured, match="COMPLIANCE_STORAGE_BLOCKED"):
        get_document_storage()
    monkeypatch.setenv("PLATFORM_OPS_DOCUMENT_STORAGE", "render_disk")
    with pytest.raises(SecureStorageNotConfigured, match="COMPLIANCE_STORAGE_BLOCKED"):
        get_document_storage()
    monkeypatch.setenv("PLATFORM_OPS_DOCUMENT_STORAGE", "s3_private")
    monkeypatch.delenv("AMICOR_DOCUMENT_S3_BUCKET", raising=False)
    monkeypatch.delenv("AMICOR_DOCUMENT_S3_ACCESS_KEY", raising=False)
    monkeypatch.delenv("AMICOR_DOCUMENT_S3_SECRET_KEY", raising=False)
    monkeypatch.delenv("AWS_ACCESS_KEY_ID", raising=False)
    monkeypatch.delenv("AWS_SECRET_ACCESS_KEY", raising=False)
    with pytest.raises(SecureStorageNotConfigured):
        assert_production_storage_allowed("s3_private")
    assert s3_configuration_status()["status"] == "BLOCKED"
    storage = None
    try:
        storage = get_document_storage()
    except SecureStorageNotConfigured:
        storage = None
    assert storage is None or not isinstance(storage, LocalDocumentStorage)


def test_unauthorized_roles_cannot_download_sensitive_documents(client: TestClient) -> None:
    org_id = _org_id()
    admin_token = _login(client, "admin@amicor.local")
    dispatcher_token = _login(client, "dispatcher@amicor.local")
    app_id, token = _create_draft(client, org_id)
    upload = client.post(
        f"/api/platform-ops/driver-onboarding/applications/{app_id}/documents?category=drivers_license_front",
        headers={"X-Applicant-Token": token},
        files={"file": ("placeholder.txt", BytesIO(b"placeholder-not-real-pii"), "text/plain")},
    )
    assert upload.status_code == 200, upload.text
    document_id = upload.json()["id"]
    denied = client.get(
        f"/api/platform-ops/driver-onboarding/applications/{app_id}/documents/{document_id}/download",
        headers=_auth(dispatcher_token),
    )
    assert denied.status_code == 403
    allowed = client.get(
        f"/api/platform-ops/driver-onboarding/applications/{app_id}/documents/{document_id}/download",
        headers=_auth(admin_token),
    )
    assert allowed.status_code == 200
    assert allowed.content == b"placeholder-not-real-pii"


def test_authorized_document_retrieval_is_audited(client: TestClient) -> None:
    org_id = _org_id()
    admin_token = _login(client, "admin@amicor.local")
    app_id, token = _create_draft(client, org_id)
    upload = client.post(
        f"/api/platform-ops/driver-onboarding/applications/{app_id}/documents?category=proof_of_auto_insurance",
        headers={"X-Applicant-Token": token},
        files={"file": ("placeholder.txt", BytesIO(b"placeholder-not-real-pii"), "text/plain")},
    )
    document_id = upload.json()["id"]
    download = client.get(
        f"/api/platform-ops/driver-onboarding/applications/{app_id}/documents/{document_id}/download",
        headers=_auth(admin_token),
    )
    assert download.status_code == 200
    with SessionLocal() as db:
        events = (
            db.query(PlatformDriverOnboardingAuditEvent)
            .filter(
                PlatformDriverOnboardingAuditEvent.application_id == app_id,
                PlatformDriverOnboardingAuditEvent.event_type == "document_inspected",
            )
            .all()
        )
        assert events
        latest = events[-1]
        assert latest.actor_user_id
        assert document_id in (latest.metadata_json or "")
        assert "placeholder-not-real-pii" not in (latest.metadata_json or "")
        assert "D123456789" not in (latest.metadata_json or "")


def test_unsafe_file_types_are_rejected(client: TestClient) -> None:
    org_id = _org_id()
    app_id, token = _create_draft(client, org_id)
    upload = client.post(
        f"/api/platform-ops/driver-onboarding/applications/{app_id}/documents?category=drivers_license_front",
        headers={"X-Applicant-Token": token},
        files={"file": ("malware.exe", BytesIO(b"MZ-not-a-real-binary"), "application/x-msdownload")},
    )
    assert upload.status_code == 400, upload.text
    assert "Unsafe" in upload.text
    with pytest.raises(ValueError, match="Unsafe"):
        validate_document_upload(
            filename="page.html",
            content_type="text/html",
            file_bytes=b"<script>alert(1)</script>",
        )


def test_invalid_and_oversized_uploads_are_rejected(client: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("AMICOR_DOCUMENT_MAX_BYTES", "32")
    org_id = _org_id()
    app_id, token = _create_draft(client, org_id)
    empty = client.post(
        f"/api/platform-ops/driver-onboarding/applications/{app_id}/documents?category=drivers_license_front",
        headers={"X-Applicant-Token": token},
        files={"file": ("placeholder.txt", BytesIO(b""), "text/plain")},
    )
    assert empty.status_code == 400
    oversized = client.post(
        f"/api/platform-ops/driver-onboarding/applications/{app_id}/documents?category=drivers_license_front",
        headers={"X-Applicant-Token": token},
        files={"file": ("placeholder.txt", BytesIO(b"x" * 64), "text/plain")},
    )
    assert oversized.status_code == 400, oversized.text
    assert "exceeds" in oversized.text.lower() or "limit" in oversized.text.lower()


def test_object_keys_cannot_be_manipulated_for_path_traversal(tmp_path) -> None:
    storage = LocalDocumentStorage(base_dir=tmp_path)
    backend, ref, size = storage.store(
        organization_id="org",
        application_id="app",
        category="drivers_license_front",
        filename="placeholder.txt",
        content_type="text/plain",
        stream=BytesIO(b"placeholder-not-real-pii"),
    )
    assert backend == "local_dev"
    assert size > 0
    assert ".." not in ref
    assert ref.endswith(".txt")
    with pytest.raises(ValueError, match="Invalid storage reference"):
        assert_safe_storage_ref("../etc/passwd")
    with pytest.raises(ValueError, match="Invalid storage reference"):
        storage.retrieve(storage_ref="../../etc/passwd")
    with pytest.raises(ValueError, match="Invalid storage reference"):
        storage.retrieve(storage_ref="/etc/passwd")
    with pytest.raises(ValueError, match="Invalid storage reference"):
        storage.retrieve(storage_ref="org\\..\\secret.txt")


def test_secrets_and_document_contents_are_not_in_api_responses(client: TestClient) -> None:
    org_id = _org_id()
    admin_token = _login(client, "admin@amicor.local")
    app_id, token = _create_draft(client, org_id)
    upload = client.post(
        f"/api/platform-ops/driver-onboarding/applications/{app_id}/documents?category=vehicle_registration",
        headers={"X-Applicant-Token": token},
        files={"file": ("placeholder.txt", BytesIO(b"placeholder-not-real-pii"), "text/plain")},
    )
    assert upload.status_code == 200, upload.text
    body = upload.json()
    assert "storage_ref" not in body
    assert "placeholder-not-real-pii" not in str(body)
    assert "AMICOR_DOCUMENT_S3_SECRET_KEY" not in str(body)
    detail = client.get(
        f"/api/platform-ops/driver-onboarding/applications/{app_id}",
        headers=_auth(admin_token),
    )
    assert detail.status_code == 200
    dumped = detail.text
    assert "storage_ref" not in dumped
    assert "placeholder-not-real-pii" not in dumped
    assert "AWS_SECRET_ACCESS_KEY" not in dumped
    status = client.get(
        "/api/platform-ops/driver-onboarding/storage-status",
        headers=_auth(admin_token),
    )
    assert status.status_code == 200
    assert status.json()["state"] in {"READY", "BLOCKED"}
    assert "secret" not in status.text.lower() or "do not invent" in status.text.lower()
    assert s3_configuration_status()["public_urls"] == "never"


def test_phase2a_activation_dispatch_sts_and_ai_controls_remain(client: TestClient) -> None:
    assert dispatch_gate_enabled() is False
    assert sts_mhcp_dispatch_enabled() is False
    org_id = _org_id()
    admin_token = _login(client, "admin@amicor.local")
    app_id, token = _create_draft(client, org_id)
    for category in (
        "drivers_license_front",
        "drivers_license_back",
        "vehicle_registration",
        "proof_of_auto_insurance",
        "independent_contractor_agreement",
    ):
        client.post(
            f"/api/platform-ops/driver-onboarding/applications/{app_id}/documents?category={category}",
            headers={"X-Applicant-Token": token},
            files={"file": ("placeholder.txt", BytesIO(b"placeholder-not-real-pii"), "text/plain")},
        )
    from tests.work_setup_testutil import complete_secure_work_setup

    complete_secure_work_setup(client, app_id, token, legal_name="Taylor Applicant")
    client.post(
        f"/api/platform-ops/driver-onboarding/applications/{app_id}/submit",
        headers={"X-Applicant-Token": token},
        json={"confirmation": True},
    )
    for status_name in ("under_review", "background_review"):
        client.post(
            f"/api/platform-ops/driver-onboarding/applications/{app_id}/status",
            headers=_auth(admin_token),
            json={"to_status": status_name, "confirm": True},
        )
    approve = client.post(
        f"/api/platform-ops/driver-onboarding/applications/{app_id}/approve",
        headers=_auth(admin_token),
        json={"confirm": True},
    )
    assert approve.status_code == 200, approve.text
    blocked = client.post(
        f"/api/platform-ops/driver-onboarding/applications/{app_id}/activate",
        headers=_auth(admin_token),
        json={"confirm": True},
    )
    assert blocked.status_code in {400, 409}
    assert "COMPLIANCE_ACTIVATION_BLOCKED" in blocked.text
    with pytest.raises(ValueError, match="AI must not manufacture"):
        ExternalVerificationRecord(
            requirement_key="mvr",
            status="CLEARED",
            evidence_source="invented",
            provider_key="manual-test",
            reviewer_source="AI",
        ).normalized()
    with SessionLocal() as db:
        driver = HealthISFDriver(
            id=make_uuid(),
            organization_id=org_id,
            name="Legacy",
            phone=_unique_phone(),
            vehicle_type="sedan",
            vehicle_plate=f"LEG{uuid4().hex[:5].upper()}",
            is_active=True,
        )
        db.add(driver)
        db.commit()
        hold = driver_blocked_from_live_dispatch(
            db, organization_id=org_id, driver_id=driver.id, ride=SimpleNamespace(service_type="STS medical")
        )
        assert hold["blocked"] is True


def test_no_ssn_tin_or_bank_columns_introduced() -> None:
    ensure_platform_ops_schema()
    ensure_approval_engine_schema()
    with SessionLocal() as db:
        inspector = inspect(db.bind)
        forbidden = {
            "ssn",
            "tin",
            "ein",
            "itin",
            "social_security_number",
            "bank_account_number",
            "routing_number",
            "account_number",
        }
        for table in inspector.get_table_names():
            columns = {col["name"].lower() for col in inspector.get_columns(table)}
            assert not (columns & forbidden), f"{table} introduced sensitive columns: {columns & forbidden}"


def test_storage_readiness_gate_blocks_real_documents_by_default(client: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("PLATFORM_OPS_DOCUMENT_STORAGE", "local_dev")
    monkeypatch.delenv("AMICOR_ENVIRONMENT", raising=False)
    readiness = secure_document_storage_readiness()
    assert readiness["state"] == "BLOCKED"
    assert readiness["real_document_onboarding_allowed"] is False
    assert readiness["activates_driver"] is False
    monkeypatch.setenv("PLATFORM_OPS_DOCUMENT_STORAGE", "encrypted_private")
    monkeypatch.setenv("PLATFORM_OPS_DOCUMENT_ENCRYPTION_KEY", "phase2c-test-encryption-key-32chars!!")
    ready = secure_document_storage_readiness()
    assert ready["state"] == "READY"
    assert ready["real_document_onboarding_allowed"] is True
    assert ready["activates_driver"] is False
    org_id = _org_id()
    admin_token = _login(client, "admin@amicor.local")
    created = client.post(
        "/api/approval-engine/driver-001/prepare",
        headers=_auth(admin_token),
        json={"reuse_existing": True},
    )
    assert created.status_code == 200, created.text
    if created.json().get("case") or created.json().get("exists"):
        status = client.get("/api/approval-engine/driver-001", headers=_auth(admin_token))
        if status.status_code == 200 and status.json().get("readiness_view"):
            items = {row["key"]: row for row in status.json()["readiness_view"]["items"]}
            assert "secure_document_storage" in items
            assert items["secure_document_storage"]["state"] in {"READY", "BLOCKED"}


def _s3_private_test_credentials(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("PLATFORM_OPS_DOCUMENT_STORAGE", "s3_private")
    monkeypatch.setenv("AMICOR_DOCUMENT_S3_BUCKET", "amicor-docs-test")
    monkeypatch.setenv("AMICOR_DOCUMENT_S3_REGION", "us-east-1")
    monkeypatch.setenv("AMICOR_DOCUMENT_S3_ACCESS_KEY", "test-not-a-real-key")
    monkeypatch.setenv("AMICOR_DOCUMENT_S3_SECRET_KEY", "test-not-a-real-secret")


def test_s3_custom_endpoint_absent_preserves_aws_s3(monkeypatch: pytest.MonkeyPatch) -> None:
    _s3_private_test_credentials(monkeypatch)
    monkeypatch.delenv("AMICOR_DOCUMENT_S3_ENDPOINT", raising=False)
    assert s3_credentials_present() is True
    assert s3_endpoint_url() is None
    assert s3_configuration_status()["status"] == "READY"
    captured: dict = {}

    def fake_client(service, **kwargs):
        captured["service"] = service
        captured["kwargs"] = kwargs
        return SimpleNamespace()

    import boto3

    monkeypatch.setattr(boto3, "client", fake_client)
    S3PrivateDocumentStorage()
    assert captured["service"] == "s3"
    assert "endpoint_url" not in captured["kwargs"]
    assert captured["kwargs"]["region_name"] == "us-east-1"


def test_s3_custom_https_endpoint_passed_to_boto3(monkeypatch: pytest.MonkeyPatch) -> None:
    _s3_private_test_credentials(monkeypatch)
    monkeypatch.setenv("AMICOR_DOCUMENT_S3_ENDPOINT", "https://s3-compatible.example.test/")
    assert s3_endpoint_url() == "https://s3-compatible.example.test"
    assert s3_configuration_status()["status"] == "READY"
    captured: dict = {}

    def fake_client(service, **kwargs):
        captured["kwargs"] = kwargs
        return SimpleNamespace()

    import boto3

    monkeypatch.setattr(boto3, "client", fake_client)
    S3PrivateDocumentStorage()
    assert captured["kwargs"]["endpoint_url"] == "https://s3-compatible.example.test"


def test_s3_http_endpoint_rejected_tls_required(monkeypatch: pytest.MonkeyPatch) -> None:
    _s3_private_test_credentials(monkeypatch)
    monkeypatch.setenv("AMICOR_DOCUMENT_S3_ENDPOINT", "http://insecure.example.test")
    status = s3_configuration_status()
    assert status["status"] == "BLOCKED"
    assert "https://" in status["reason"]
    with pytest.raises(SecureStorageNotConfigured, match="https://"):
        s3_endpoint_url()
    with pytest.raises(SecureStorageNotConfigured, match="COMPLIANCE_STORAGE_BLOCKED"):
        S3PrivateDocumentStorage()
