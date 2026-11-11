"""Read-only staging preflight refuses missing infrastructure without secrets."""
import sqlalchemy as sa
import pytest

from app.core.nova.work_revenue import operations_staging_preflight as preflight
from app.core.nova.work_revenue.operations_customer_csv_jobs import CustomerCSVBlocked


def test_preflight_denies_missing_staging_worker(monkeypatch):
    monkeypatch.setattr(preflight, "_stage_only_config",
                        lambda: (_ for _ in ()).throw(CustomerCSVBlocked("blocked", 503)))
    result = preflight.run_preflight()
    assert result == {
        "ready": False,
        "checks": {"staging_worker_configuration": "BLOCKED"},
    }


def test_preflight_requires_real_schema_and_bucket(monkeypatch):
    monkeypatch.setattr(preflight, "_stage_only_config",
                        lambda: ("sqlite://", "owner@example.invalid"))
    result = preflight.run_preflight()
    assert result["ready"] is False
    assert result["checks"]["isolated_database_schema"] == "BLOCKED"


def test_preflight_bucket_rejects_unapproved_name_before_network(monkeypatch):
    monkeypatch.setenv("PLATFORM_OPS_DOCUMENT_STORAGE", "s3_private")
    monkeypatch.setattr(preflight.storage, "s3_bucket", lambda: "amicor-prod")
    with pytest.raises(CustomerCSVBlocked, match="Dedicated Operations"):
        preflight._check_bucket()


def test_preflight_bucket_requires_public_access_block_and_encryption(monkeypatch):
    monkeypatch.setenv("PLATFORM_OPS_DOCUMENT_STORAGE", "s3_private")
    monkeypatch.setattr(preflight.storage, "s3_bucket",
                        lambda: "nova-operations-staging-only")
    monkeypatch.setattr(preflight.storage, "s3_configuration_status",
                        lambda: {"status": "READY"})
    class StubClient:
        def get_public_access_block(self, *, Bucket):
            return {"PublicAccessBlockConfiguration": {
                "BlockPublicAcls": True, "IgnorePublicAcls": True,
                "BlockPublicPolicy": True, "RestrictPublicBuckets": False,
            }}
        def get_bucket_encryption(self, *, Bucket):
            return {"ServerSideEncryptionConfiguration": {"Rules": []}}
    monkeypatch.setattr(preflight.storage, "S3PrivateDocumentStorage",
                        lambda: type("Store", (), {"_client": StubClient()})())
    with pytest.raises(CustomerCSVBlocked, match="four S3"):
        preflight._check_bucket()


def test_preflight_storage_metadata_read_only(monkeypatch):
    monkeypatch.setenv("PLATFORM_OPS_DOCUMENT_STORAGE", "s3_private")
    monkeypatch.setattr(preflight.storage, "s3_bucket",
                        lambda: "nova-operations-staging-only")
    monkeypatch.setattr(preflight.storage, "s3_configuration_status",
                        lambda: {"status": "READY"})
    calls = []
    class StubClient:
        def get_public_access_block(self, *, Bucket):
            calls.append("read-access")
            return {"PublicAccessBlockConfiguration": {
                "BlockPublicAcls": True, "IgnorePublicAcls": True,
                "BlockPublicPolicy": True, "RestrictPublicBuckets": True,
            }}
        def get_bucket_encryption(self, *, Bucket):
            calls.append("read-encryption")
            return {"ServerSideEncryptionConfiguration": {
                "Rules": [{"ApplyServerSideEncryptionByDefault": {
                    "SSEAlgorithm": "AES256",
                }}],
            }}
    monkeypatch.setattr(preflight.storage, "S3PrivateDocumentStorage",
                        lambda: type("Store", (), {"_client": StubClient()})())
    preflight._check_bucket()
    assert calls == ["read-access", "read-encryption"]
