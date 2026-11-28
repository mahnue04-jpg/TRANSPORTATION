"""Synthetic private-storage probe. No network, bucket name, or customer file."""

from __future__ import annotations

import json

import pytest
from fastapi.testclient import TestClient

from app.auth import UserContext, get_current_user_context
from app.core.nova.work_revenue import operations_private_storage as storage
from app.core.nova.work_revenue.operations_owner_storage_probe import (
    router as owner_router,
)
from app.core.nova.work_revenue.operations_private_storage import (
    SYNTHETIC_PROBE_BODY,
    run_synthetic_storage_probe,
)
from app.core.nova.work_revenue.owner_auth import require_work_revenue_owner
from app.db.session import get_db
from app.main import app
from app.modules.platform_ops.secure_storage import SecureStorageNotConfigured
from botocore.exceptions import ClientError


class _Memory:
    def __init__(self, *, body=None, content_type="text/plain", delete_error="", stick=False, missing_code="NoSuchKey"):
        self.body = SYNTHETIC_PROBE_BODY if body is None else body
        self.content_type = content_type
        self.delete_error = delete_error
        self.stick = stick
        self.missing_code = missing_code
        self.objects = {}

    def store(self, **kwargs):
        payload = kwargs["stream"].read()
        assert payload == SYNTHETIC_PROBE_BODY
        self.objects["ref-1"] = payload
        return ("hidden-object-key", "ref-1", len(payload))

    def retrieve(self, *, storage_ref):
        if storage_ref not in self.objects:
            status = 404 if self.missing_code in {"NoSuchKey", "404", "NotFound"} else 403
            raise ClientError(
                {
                    "Error": {"Code": self.missing_code, "Message": "object lookup failed"},
                    "ResponseMetadata": {"HTTPStatusCode": status},
                },
                "GetObject",
            )
        return self.body, self.content_type

    def delete(self, *, storage_ref):
        if self.delete_error:
            raise RuntimeError(self.delete_error)
        if not self.stick:
            self.objects.pop(storage_ref, None)


def test_probe_uploads_reads_and_deletes_without_leaking_location(monkeypatch):
    fake = _Memory()
    monkeypatch.setattr(storage, "OperationsPrivateArtifactStorage", lambda: fake)
    report = run_synthetic_storage_probe()
    dumped = json.dumps(report)
    assert report == {
        "ok": True,
        "uploaded": True,
        "retrieved": True,
        "verified": True,
        "deleted": True,
        "absent_after_delete": True,
        "synthetic": True,
        "public_url": None,
    }
    assert "hidden-object-key" not in dumped
    assert "ref-1" not in dumped
    assert fake.objects == {}


def test_probe_rejects_mismatched_bytes_and_a_failed_delete(monkeypatch):
    mismatch = _Memory(body=b"different")
    monkeypatch.setattr(storage, "OperationsPrivateArtifactStorage", lambda: mismatch)
    report = run_synthetic_storage_probe()
    assert report["ok"] is False
    assert report["verified"] is False
    assert report["deleted"] is True

    failed = _Memory(delete_error="operations-private-fixture secret")
    monkeypatch.setattr(storage, "OperationsPrivateArtifactStorage", lambda: failed)
    report = run_synthetic_storage_probe()
    assert report["deleted"] is False
    assert report["ok"] is False
    assert "operations-private-fixture" not in json.dumps(report)


def test_probe_requires_absence_after_delete(monkeypatch):
    monkeypatch.setattr(storage, "OperationsPrivateArtifactStorage", lambda: _Memory(stick=True))
    report = run_synthetic_storage_probe()
    assert report["deleted"] is True
    assert report["absent_after_delete"] is False
    assert report["ok"] is False


def test_access_denied_after_delete_is_not_absence(monkeypatch, caplog):
    monkeypatch.setattr(
        storage,
        "OperationsPrivateArtifactStorage",
        lambda: _Memory(missing_code="AccessDenied"),
    )
    with caplog.at_level("WARNING"):
        report = run_synthetic_storage_probe()
    assert report["deleted"] is True
    assert report["absent_after_delete"] is False
    assert report["ok"] is False
    assert "operation=confirm_deleted" in caplog.text
    assert "error_code=AccessDenied" in caplog.text
    assert "http_status=403" in caplog.text


def test_store_error_escapes_without_a_partial_success(monkeypatch):
    class Broken:
        def store(self, **kwargs):
            raise SecureStorageNotConfigured("bucket-name-must-not-leak")

    monkeypatch.setattr(storage, "OperationsPrivateArtifactStorage", lambda: Broken())
    with pytest.raises(SecureStorageNotConfigured):
        run_synthetic_storage_probe()


@pytest.fixture
def client():
    application = TestClient(app)
    application.app.dependency_overrides.clear()
    try:
        yield application
    finally:
        application.app.dependency_overrides.clear()


def test_owner_probe_returns_synthetic_report_without_storage_details(client, monkeypatch):
    owner = UserContext(
        user_id="owner-1", email="owner@example.invalid", role="admin", organization_id="org-1",
    )
    client.app.dependency_overrides[require_work_revenue_owner] = lambda: owner
    monkeypatch.setattr(
        "app.core.nova.work_revenue.operations_owner_storage_probe.run_synthetic_storage_probe",
        lambda: {
            "ok": True, "uploaded": True, "retrieved": True, "verified": True,
            "deleted": True, "absent_after_delete": True, "synthetic": True, "public_url": None,
        },
    )
    response = client.post(
        "/api/nova/work/operations/owner/storage-probe",
        headers={"X-Nova-Owner-Action": "run-synthetic-storage-probe"},
    )
    assert response.status_code == 200
    assert response.json()["ok"] is True
    assert "bucket" not in response.text


def test_owner_probe_requires_explicit_action_and_rejects_customers(client, monkeypatch):
    called = {"probe": False}

    def fail_probe():
        called["probe"] = True
        raise AssertionError("probe must not run")

    monkeypatch.setattr(
        "app.core.nova.work_revenue.operations_owner_storage_probe.run_synthetic_storage_probe",
        fail_probe,
    )
    owner = UserContext(
        user_id="owner-1", email="owner@example.invalid", role="admin", organization_id="org-1",
    )
    client.app.dependency_overrides[require_work_revenue_owner] = lambda: owner
    assert client.post("/api/nova/work/operations/owner/storage-probe").status_code == 403

    customer = UserContext(
        user_id="user-1", email="buyer@example.invalid", role="staff", organization_id="org-1",
    )
    client.app.dependency_overrides.clear()
    client.app.dependency_overrides[get_current_user_context] = lambda: customer
    client.app.dependency_overrides[get_db] = lambda: object()
    monkeypatch.setattr(
        "app.core.nova.work_revenue.router.customer_access",
        lambda *args, **kwargs: {"nova_saas_customer": True},
    )
    denied = client.post(
        "/api/nova/work/operations/owner/storage-probe",
        headers={"X-Nova-Owner-Action": "run-synthetic-storage-probe"},
    )
    assert denied.status_code == 403
    assert called["probe"] is False
    assert owner_router.prefix == "/api/nova/work/operations/owner"
