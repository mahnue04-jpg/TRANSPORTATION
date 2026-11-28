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


def test_r2_round_trip_uses_path_signing_without_unsupported_headers(production, monkeypatch):
    from app.core.nova.work_revenue.operations_private_storage import run_synthetic_storage_probe

    body = b"AMICOR synthetic operations storage probe. No customer data.\n"
    saved = {}

    class FakeS3:
        def put_object(self, **kwargs):
            saved["put"] = kwargs
            self.key = kwargs["Key"]
            self.body = kwargs["Body"]
            self.content_type = kwargs["ContentType"]

        def get_object(self, **kwargs):
            if kwargs["Key"] != getattr(self, "key", None) or getattr(self, "gone", False):
                from botocore.exceptions import ClientError
                raise ClientError(
                    {"Error": {"Code": "NoSuchKey"}, "ResponseMetadata": {"HTTPStatusCode": 404}},
                    "GetObject",
                )
            return {"Body": BytesIO(self.body), "ContentType": self.content_type}

        def delete_object(self, **kwargs):
            assert kwargs["Key"] == self.key
            self.gone = True

    def client(service, **kwargs):
        assert service == "s3"
        assert kwargs["region_name"] == "auto"
        assert kwargs["endpoint_url"] == "https://accountid.r2.cloudflarestorage.com"
        assert kwargs["aws_secret_access_key"] == "operations-test-secret"
        config = kwargs["config"]
        assert config.signature_version == "s3v4"
        assert config.s3["addressing_style"] == "path"
        assert config.request_checksum_calculation == "when_required"
        assert config.response_checksum_validation == "when_required"
        return FakeS3()

    monkeypatch.setenv(
        "NOVA_OPERATIONS_PRIVATE_S3_ENDPOINT",
        "https://operations-private-fixture.accountid.r2.cloudflarestorage.com/operations-private-fixture/",
    )
    monkeypatch.setenv("NOVA_OPERATIONS_PRIVATE_S3_REGION", "us-east-1")
    monkeypatch.setattr(boto3, "client", client)
    report = run_synthetic_storage_probe()
    assert report["ok"] is True
    assert report["public_url"] is None
    assert "ServerSideEncryption" not in saved["put"]
    assert saved["put"]["Body"] == body
    assert saved["put"]["Bucket"] == "operations-private-fixture"
    assert "operations-test-secret" not in str(report)


def test_r2_signed_put_omits_checksum_and_sse(production, monkeypatch):
    import boto3
    from app.core.nova.work_revenue.operations_private_storage import _operations_s3_config

    seen = {}

    def capture(request, **kwargs):
        seen["url"] = request.url
        seen["checksum"] = [name for name in request.headers if "checksum" in name.lower()]
        seen["sse"] = request.headers.get("x-amz-server-side-encryption")
        seen["authorization"] = request.headers.get("Authorization") or ""

    client = boto3.client(
        "s3",
        region_name="auto",
        aws_access_key_id="operations-test-key",
        aws_secret_access_key="operations-test-secret",
        endpoint_url="https://192.0.2.1",
        config=_operations_s3_config("https://accountid.r2.cloudflarestorage.com"),
    )
    client.meta.events.register("request-created.s3", capture)
    with pytest.raises(Exception):
        client.put_object(
            Bucket="operations-private-fixture",
            Key="owner-storage-probe/synthetic/probe.txt",
            Body=b"synthetic",
            ContentType="text/plain",
        )
    assert seen["url"] == "https://192.0.2.1/operations-private-fixture/owner-storage-probe/synthetic/probe.txt"
    assert seen["checksum"] == []
    assert seen["sse"] is None
    assert seen["authorization"].startswith("AWS4-HMAC-SHA256")
    assert "operations-test-secret" not in seen["url"]
    assert "operations-test-secret" not in seen["authorization"]


def test_r2_failure_log_names_the_operation_without_secrets(production, monkeypatch, caplog):
    from botocore.exceptions import ClientError
    from app.core.nova.work_revenue.operations_private_storage import run_synthetic_storage_probe

    class RejectingS3:
        def put_object(self, **kwargs):
            raise ClientError(
                {
                    "Error": {
                        "Code": "NotImplemented",
                        "Message": "https://accountid.r2.cloudflarestorage.com operations-test-secret",
                    },
                    "ResponseMetadata": {"HTTPStatusCode": 501},
                },
                "PutObject",
            )

    monkeypatch.setenv("NOVA_OPERATIONS_PRIVATE_S3_ENDPOINT", "https://accountid.r2.cloudflarestorage.com")
    monkeypatch.setattr(boto3, "client", lambda service, **kwargs: RejectingS3())
    with caplog.at_level("WARNING"):
        with pytest.raises(ClientError):
            run_synthetic_storage_probe()
    text = caplog.text
    assert "operation=put_object" in text
    assert "error_class=ClientError" in text
    assert "error_code=NotImplemented" in text
    assert "http_status=501" in text
    assert "operations-test-secret" not in text
    assert "r2.cloudflarestorage.com" not in text


def test_staging_preserves_existing_storage_adapter(production, monkeypatch):
    monkeypatch.setenv("APP_ENV", "staging")
    monkeypatch.setenv("AMICOR_ENVIRONMENT", "staging")
    marker = object()
    monkeypatch.setattr(jobs, "S3PrivateDocumentStorage", lambda: marker)
    assert jobs._store() is marker
