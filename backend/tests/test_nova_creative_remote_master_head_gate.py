"""Private remote master object HEAD gate, no external network or provider use."""
import pytest

from app.core.nova.creative_studio import private_object_storage as storage


REF = "private-studio-s3://owner/project/imported_video_test.mp4"
SHA = "a" * 64


def test_head_gate_needs_positive_object_length_and_matching_digest(monkeypatch):
    monkeypatch.setattr(storage, "_bucket", lambda: "test-bucket")
    recorded = []

    class FakeClient:
        def __init__(self, response):
            self.response = response

        def head_object(self, **kwargs):
            recorded.append(kwargs)
            return self.response

    def verify(response, digest=SHA):
        monkeypatch.setattr(storage, "_client", lambda: FakeClient(response))
        return storage.object_exists(REF, "owner", "project", digest)

    assert verify({"ContentLength": 200, "Metadata": {"sha256": SHA}})
    assert recorded[-1]["Key"] == "owner/project/imported_video_test.mp4"
    assert not verify({"ContentLength": 0, "Metadata": {"sha256": SHA}})
    assert not verify({"ContentLength": -1, "Metadata": {"sha256": SHA}})
    assert not verify({"Metadata": {"sha256": SHA}})
    assert not verify({"ContentLength": 200, "Metadata": {"sha256": "b" * 64}})
    assert not verify({"ContentLength": 200, "Metadata": {}}, SHA)
    assert not verify({"ContentLength": "corrupt", "Metadata": {"sha256": SHA}})
    assert not verify({"ContentLength": None, "Metadata": {"sha256": SHA}})
    assert not verify({"ContentLength": 200, "Metadata": {"sha256": "too-short"}},
                      "too-short")


def test_head_gate_enforces_owner_and_project_scope(monkeypatch):
    monkeypatch.setattr(storage, "_bucket", lambda: "test-bucket")

    class FakeClient:
        def head_object(self, **kwargs):
            return {"ContentLength": 1, "Metadata": {"sha256": SHA}}

    monkeypatch.setattr(storage, "_client", lambda: FakeClient())
    assert storage.object_exists(REF, "owner", "project", SHA) is True
    with pytest.raises(storage.PrivateStorageError, match="access denied"):
        storage.object_exists(REF, "other", "project", SHA)
    with pytest.raises(storage.PrivateStorageError, match="access denied"):
        storage.object_exists(REF, "owner", "different", SHA)
    assert storage.object_exists("not-a-private-url", "owner", "project", SHA) is False


def test_owned_object_size_returns_exact_length_and_rejects_large_remote_files(monkeypatch):
    monkeypatch.setattr(storage, "_bucket", lambda: "test-bucket")

    class FakeClient:
        def __init__(self, length):
            self.length = length

        def head_object(self, **kwargs):
            return {"ContentLength": self.length, "Metadata": {"sha256": SHA}}

    monkeypatch.setattr(storage, "_client", lambda: FakeClient(4096))
    assert storage.owned_object_size(REF, "owner", "project", SHA) == 4096
    monkeypatch.setattr(storage, "_client", lambda: FakeClient(2 * 1024 * 1024 * 1024 + 1))
    assert storage.owned_object_size(REF, "owner", "project", SHA) is None
    assert storage.object_exists(REF, "owner", "project", SHA) is False
    assert storage.owned_object_size(REF, "owner", "project", "bad") is None
