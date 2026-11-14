"""Disposable, no-network coverage for the staging storage canary."""
from __future__ import annotations

import hashlib
import importlib.util
import io
from pathlib import Path

import pytest

spec = importlib.util.spec_from_file_location(
    "staging_storage_canary",
    Path(__file__).resolve().parents[1] / "scripts/verify_studio_staging_storage_canary.py",
)
canary = importlib.util.module_from_spec(spec)
spec.loader.exec_module(canary)


class MissingObject(Exception):
    def __init__(self):
        self.response = {"Error": {"Code": "NoSuchKey"},
                         "ResponseMetadata": {"HTTPStatusCode": 404}}


class FakeS3:
    def __init__(self, fail=None):
        self.objects = {}
        self.calls = []
        self.fail = fail

    def head_object(self, *, Bucket, Key):
        self.calls.append("head")
        if Key not in self.objects:
            raise MissingObject()
        body, metadata = self.objects[Key]
        return {"ContentLength": len(body), "Metadata": dict(metadata)}

    def put_object(self, *, Bucket, Key, Body, Metadata, IfNoneMatch, ContentType):
        self.calls.append("put")
        assert IfNoneMatch == "*"
        assert ContentType == "application/octet-stream"
        assert Key not in self.objects
        self.objects[Key] = (Body, dict(Metadata))
        if self.fail == "ambiguous_put":
            raise ConnectionError("response lost after write")

    def get_object(self, *, Bucket, Key):
        self.calls.append("get")
        if self.fail == "bad_read":
            return {"Body": io.BytesIO(b"tampered")}
        return {"Body": io.BytesIO(self.objects[Key][0])}

    def delete_object(self, *, Bucket, Key):
        self.calls.append("delete")
        if self.fail == "delete":
            raise ConnectionError("delete unavailable")
        self.objects.pop(Key, None)


@pytest.fixture(autouse=True)
def staging(monkeypatch):
    monkeypatch.setenv("APP_ENV", "staging")
    monkeypatch.setenv("NOVA_STUDIO_PRIVATE_OBJECT_STORAGE", "true")


def test_canary_writes_reads_hashes_and_removes_only_test_object(monkeypatch):
    client = FakeS3()
    existing = "owner/project/imported_video_original.mp4"
    client.objects[existing] = (b"original", {"sha256": "preserve"})
    result = canary.run_canary(client=client, bucket="staging-bucket",
                              random_hex=lambda count: "a" * (count * 2))
    assert result["write_verified"] is True
    assert result["full_byte_read_verified"] is True
    assert result["cleanup_verified"] is True
    assert result["real_video_verified"] is False
    assert client.objects == {existing: (b"original", {"sha256": "preserve"})}
    assert client.calls.count("put") == 1
    assert client.calls.count("get") == 1
    assert client.calls.count("delete") == 1


def test_corrupt_download_fails_and_cleans_canary():
    client = FakeS3(fail="bad_read")
    with pytest.raises(canary.CanaryBlocked, match="CANARY_BYTE_INTEGRITY_FAILED"):
        canary.run_canary(client=client, bucket="staging-bucket")
    assert client.objects == {}


def test_ambiguous_put_response_still_cleans_canary():
    client = FakeS3(fail="ambiguous_put")
    with pytest.raises(canary.CanaryBlocked, match="CANARY_STORAGE_OPERATION_FAILED"):
        canary.run_canary(client=client, bucket="staging-bucket")
    assert client.objects == {}
    assert "delete" in client.calls


def test_cleanup_failure_never_reports_success():
    client = FakeS3(fail="delete")
    with pytest.raises(canary.CanaryBlocked, match="CANARY_CLEANUP_UNVERIFIED"):
        canary.run_canary(client=client, bucket="staging-bucket")
    assert client.objects


def test_production_environment_cannot_call_storage(monkeypatch):
    monkeypatch.setenv("APP_ENV", "production")
    client = FakeS3()
    with pytest.raises(canary.CanaryBlocked, match="STAGING_ONLY"):
        canary.run_canary(client=client, bucket="staging-bucket")
    assert client.calls == []


def test_disabled_storage_cannot_write(monkeypatch):
    monkeypatch.setenv("NOVA_STUDIO_PRIVATE_OBJECT_STORAGE", "false")
    client = FakeS3()
    with pytest.raises(canary.CanaryBlocked, match="PRIVATE_STORAGE_DISABLED"):
        canary.run_canary(client=client, bucket="staging-bucket")
    assert client.calls == []


def test_default_cli_is_dry_run_and_makes_no_client(monkeypatch, capsys):
    monkeypatch.setattr(canary.storage, "_client", lambda: pytest.fail("Client forbidden"))
    assert canary.main([]) == 0
    assert '"writes": false' in capsys.readouterr().out


def test_cli_apply_requires_explicit_ack(monkeypatch, capsys):
    monkeypatch.setattr(canary.storage, "_client", lambda: pytest.fail("Client forbidden"))
    assert canary.main(["--apply"]) == 1
    assert "EXPLICIT_STAGING_TEST_ACK_REQUIRED" in capsys.readouterr().err


def test_apply_rejects_bucket_mismatch_without_network(monkeypatch, capsys):
    monkeypatch.setenv("NOVA_STUDIO_S3_BUCKET", "private-stage-one")
    monkeypatch.setattr(canary.storage, "_client", lambda: pytest.fail("No S3 call allowed"))
    assert canary.main(["--apply", "--acknowledge-staging-test-object",
                        "--expected-bucket", "private-prod-other"]) == 1
    assert "EXPECTED_STAGING_BUCKET_MISMATCH" in capsys.readouterr().err


def test_apply_requires_expected_bucket_without_network(monkeypatch, capsys):
    monkeypatch.setenv("NOVA_STUDIO_S3_BUCKET", "private-stage-one")
    monkeypatch.setattr(canary.storage, "_client", lambda: pytest.fail("No S3 call allowed"))
    assert canary.main(["--apply", "--acknowledge-staging-test-object"]) == 1
    assert "EXPECTED_STAGING_BUCKET_MISMATCH" in capsys.readouterr().err
