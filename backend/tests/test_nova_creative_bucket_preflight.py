"""Private Studio bucket preflight cannot spend or write objects."""
from types import SimpleNamespace
import pytest

from app.core.nova.creative_studio import private_object_storage as storage


def test_bucket_preflight_checks_exact_bucket_without_mutation(monkeypatch):
    called = []
    class FakeS3:
        def head_bucket(self, *, Bucket):
            called.append(("head_bucket", Bucket))
    monkeypatch.setenv("NOVA_STUDIO_PRIVATE_OBJECT_STORAGE", "true")
    monkeypatch.setenv("NOVA_STUDIO_S3_BUCKET", "amicor-studio-staging")
    monkeypatch.setattr(storage, "_client", lambda: FakeS3())
    storage.verify_bucket_ready()
    assert called == [("head_bucket", "amicor-studio-staging")]


def test_bucket_preflight_fails_when_disabled_without_contacting_s3(monkeypatch):
    monkeypatch.setenv("NOVA_STUDIO_PRIVATE_OBJECT_STORAGE", "false")
    monkeypatch.setattr(storage, "_client", lambda: pytest.fail("No client allowed"))
    with pytest.raises(storage.PrivateStorageError, match="disabled"):
        storage.verify_bucket_ready()


def test_bucket_preflight_rejects_missing_bucket(monkeypatch):
    monkeypatch.setenv("NOVA_STUDIO_PRIVATE_OBJECT_STORAGE", "true")
    monkeypatch.delenv("NOVA_STUDIO_S3_BUCKET", raising=False)
    monkeypatch.setattr(storage, "_client", lambda: object())
    with pytest.raises(storage.PrivateStorageError, match="not configured"):
        storage.verify_bucket_ready()


def test_bucket_preflight_rejects_unavailable_bucket_without_writes(monkeypatch):
    class Unavailable:
        def head_bucket(self, *, Bucket):
            raise OSError("simulated storage outage")
    monkeypatch.setenv("NOVA_STUDIO_PRIVATE_OBJECT_STORAGE", "true")
    monkeypatch.setenv("NOVA_STUDIO_S3_BUCKET", "amicor-studio-staging")
    monkeypatch.setattr(storage, "_client", lambda: Unavailable())
    with pytest.raises(storage.PrivateStorageError, match="not reachable"):
        storage.verify_bucket_ready()
