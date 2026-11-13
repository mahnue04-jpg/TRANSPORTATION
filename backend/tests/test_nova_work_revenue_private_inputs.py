"""Client work-input storage boundary tests.

All files and credentials are synthetic. Tests never access external S3 or
any real customer data. Production behavior is required to fail closed.
"""
from pathlib import Path
from types import SimpleNamespace
import hashlib

import pytest

from app.core.nova.work_revenue import work_inputs
from app.core.nova.work_revenue.service import NovaWorkError


def _row(storage_ref, content=b"Name\nAda\n"):
    return SimpleNamespace(
        storage_ref=storage_ref, sha256=hashlib.sha256(content).hexdigest(),
        file_size=len(content),
    )


def test_production_upload_rejects_local_disk_without_private_storage(monkeypatch, tmp_path):
    monkeypatch.setenv("AMICOR_ENVIRONMENT", "production")
    monkeypatch.setenv("PLATFORM_OPS_DOCUMENT_STORAGE", "local_dev")
    monkeypatch.setenv("NOVA_WORK_INPUT_DIR", str(tmp_path))
    with pytest.raises(NovaWorkError, match="Private customer-file storage required"):
        work_inputs._persist_work_bytes(
            organization_id="org", engagement_id="eng", input_id="input-1",
            filename="records.csv", content_type="text/csv", content=b"Name\nAda\n",
        )
    assert list(tmp_path.rglob("*")) == []


def test_production_rejects_legacy_local_file_even_if_present(monkeypatch, tmp_path):
    content = b"Name\nAda\n"
    filename = tmp_path / "existing.csv"
    filename.write_bytes(content)
    monkeypatch.setenv("AMICOR_ENVIRONMENT", "production")
    with pytest.raises(NovaWorkError, match="secure migration required"):
        work_inputs.read_work_input_bytes(_row(str(filename), content))


class SyntheticStore:
    def __init__(self):
        self.data = {}
        self.deleted = []

    def store(self, *, organization_id, application_id, category, filename, content_type, stream):
        key = f"{organization_id}/{application_id}/{category}/{filename}"
        data = stream.read()
        self.data[key] = data
        return "synthetic-private", key, len(data)

    def retrieve(self, *, storage_ref):
        return self.data[storage_ref], "text/csv"

    def delete(self, *, storage_ref):
        self.deleted.append(storage_ref)
        self.data.pop(storage_ref, None)


def test_private_round_trip_with_integrity_verified(monkeypatch):
    store = SyntheticStore()
    monkeypatch.setenv("AMICOR_ENVIRONMENT", "production")
    monkeypatch.setenv("PLATFORM_OPS_DOCUMENT_STORAGE", "s3_private")
    monkeypatch.setattr(work_inputs, "S3PrivateDocumentStorage", lambda: store)
    content = b"Name\nAda\n"
    ref = work_inputs._persist_work_bytes(
        organization_id="org", engagement_id="eng", input_id="input-1",
        filename="records.csv", content_type="text/csv", content=content,
    )
    assert ref.startswith("s3-private:")
    assert work_inputs.read_work_input_bytes(_row(ref, content)) == content
    assert store.deleted == []


def test_private_upload_corrupt_readback_fails_and_cleans_up(monkeypatch):
    store = SyntheticStore()
    monkeypatch.setenv("AMICOR_ENVIRONMENT", "production")
    monkeypatch.setenv("PLATFORM_OPS_DOCUMENT_STORAGE", "s3_private")
    monkeypatch.setattr(work_inputs, "S3PrivateDocumentStorage", lambda: store)
    store.retrieve = lambda *, storage_ref: (b"tampered", "text/csv")
    with pytest.raises(NovaWorkError, match="verification failed"):
        work_inputs._persist_work_bytes(
            organization_id="org", engagement_id="eng", input_id="input-2",
            filename="records.csv", content_type="text/csv", content=b"Name\nAda\n",
        )
    assert store.data == {}
    assert len(store.deleted) == 1


def test_private_read_corruption_is_never_silently_accepted(monkeypatch):
    store = SyntheticStore()
    monkeypatch.setenv("AMICOR_ENVIRONMENT", "production")
    monkeypatch.setenv("PLATFORM_OPS_DOCUMENT_STORAGE", "s3_private")
    monkeypatch.setattr(work_inputs, "S3PrivateDocumentStorage", lambda: store)
    ref = work_inputs._persist_work_bytes(
        organization_id="org", engagement_id="eng", input_id="input-3",
        filename="records.csv", content_type="text/csv", content=b"Name\nAda\n",
    )
    store.data[ref.split(":", 1)[1]] = b"wrong"
    with pytest.raises(NovaWorkError, match="integrity verification failed"):
        work_inputs.read_work_input_bytes(_row(ref))


def test_development_legacy_work_inputs_remain_readable(monkeypatch, tmp_path):
    monkeypatch.setenv("AMICOR_ENVIRONMENT", "development")
    monkeypatch.delenv("ENVIRONMENT", raising=False)
    monkeypatch.delenv("NOVA_WORK_INPUT_S3_ENABLED", raising=False)
    content = b"Name\nAda\n"
    path = tmp_path / "legacy.csv"
    path.write_bytes(content)
    assert work_inputs.read_work_input_bytes(_row(str(path), content)) == content
