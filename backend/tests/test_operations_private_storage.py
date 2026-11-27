from io import BytesIO

import boto3
import pytest

from app.core.nova.work_revenue import operations_customer_csv_jobs as jobs
from app.core.nova.work_revenue.operations_private_storage import OperationsPrivateArtifactStorage


@pytest.fixture
def production(monkeypatch):
    monkeypatch.setenv("APP_ENV", "production")
    monkeypatch.setenv("AMICOR_ENVIRONMENT", "production")
    monkeypatch.setenv("PLATFORM_OPS_DOCUMENT_STORAGE", "s3_private")
    monkeypatch.setenv("AMICOR_DOCUMENT_S3_BUCKET", "existing-other-product-bucket")
    monkeypatch.setenv("AMICOR_DOCUMENT_S3_ACCESS_KEY", "unrelated-test-key")
    monkeypatch.setenv("AMICOR_DOCUMENT_S3_SECRET_KEY", "unrelated-test-secret")
    monkeypatch.setenv("NOVA_OPERATIONS_PRIVATE_S3_BUCKET", "operations-private-fixture")
    monkeypatch.setenv("NOVA_OPERATIONS_PRIVATE_S3_REGION", "us-east-1")
    monkeypatch.setenv("NOVA_OPERATIONS_PRIVATE_S3_ACCESS_KEY", "operations-test-key")
    monkeypatch.setenv("NOVA_OPERATIONS_PRIVATE_S3_SECRET_KEY", "operations-test-secret")
    monkeypatch.delenv("NOVA_OPERATIONS_PRIVATE_S3_ENDPOINT", raising=False)


@pytest.mark.parametrize("suffix", ["BUCKET", "REGION", "ACCESS_KEY", "SECRET_KEY"])
def test_production_never_falls_back_to_shared_credentials(production, monkeypatch, suffix):
    monkeypatch.delenv(f"NOVA_OPERATIONS_PRIVATE_S3_{suffix}")
    monkeypatch.setattr(boto3, "client", lambda *a, **k: pytest.fail("No client allowed"))
    with pytest.raises(jobs.CustomerCSVBlocked, match="Private artifact storage unavailable") as exc:
        jobs._store()
    assert exc.value.code == 503


@pytest.mark.parametrize("env,value", [
    ("APP_ENV", "staging"),
    ("AMICOR_ENVIRONMENT", "prod"),
    ("NOVA_OPERATIONS_PRIVATE_S3_BUCKET", "existing-other-product-bucket"),
    ("NOVA_OPERATIONS_PRIVATE_S3_ENDPOINT", "http://storage.example.invalid"),
    ("NOVA_OPERATIONS_PRIVATE_S3_ENDPOINT", "https://@storage.example.invalid"),
    ("NOVA_OPERATIONS_PRIVATE_S3_ENDPOINT", "https://storage.example.invalid/other-path"),
])
def test_invalid_production_storage_fails_closed(production, monkeypatch, env, value):
    monkeypatch.setenv(env, value)
    monkeypatch.setattr(boto3, "client", lambda *a, **k: pytest.fail("No client allowed"))
    with pytest.raises(jobs.CustomerCSVBlocked):
        jobs._store()


def test_production_artifacts_use_only_dedicated_private_bucket(production, monkeypatch):
    payload = b"column\nsynthetic\n"
    calls = []

    class FakeS3:
        def put_object(self, **kwargs):
            calls.append(("put", kwargs))

        def get_object(self, **kwargs):
            calls.append(("get", kwargs))
            return {"Body": BytesIO(payload), "ContentType": "text/csv"}

        def delete_object(self, **kwargs):
            calls.append(("delete", kwargs))

    def client(service, **kwargs):
        assert service == "s3"
        assert kwargs["aws_access_key_id"] == "operations-test-key"
        assert kwargs["aws_secret_access_key"] == "operations-test-secret"
        assert kwargs["endpoint_url"] == "https://storage.example.invalid"
        return FakeS3()

    monkeypatch.setenv("NOVA_OPERATIONS_PRIVATE_S3_ENDPOINT", "https://storage.example.invalid/")
    monkeypatch.setattr(boto3, "client", client)
    store = jobs._store()
    assert isinstance(store, OperationsPrivateArtifactStorage)
    _, ref, count = store.store(organization_id="test-org", application_id="test-job",
                               category="nova-csv-review", filename="cleaned.csv",
                               content_type="text/csv", stream=BytesIO(payload))
    assert ref.startswith("test-org/test-job/nova-csv-review/")
    assert count == len(payload)
    assert store.retrieve(storage_ref=ref) == (payload, "text/csv")
    store.delete(storage_ref=ref)
    assert [method for method, _ in calls] == ["put", "get", "delete"]
    assert all(options["Bucket"] == "operations-private-fixture" for _, options in calls)
    assert calls[0][1]["ServerSideEncryption"] == "AES256"
    assert "ACL" not in calls[0][1]


def test_staging_preserves_existing_storage_adapter(production, monkeypatch):
    monkeypatch.setenv("APP_ENV", "staging")
    monkeypatch.setenv("AMICOR_ENVIRONMENT", "staging")
    marker = object()
    monkeypatch.setattr(jobs, "S3PrivateDocumentStorage", lambda: marker)
    assert jobs._store() is marker
