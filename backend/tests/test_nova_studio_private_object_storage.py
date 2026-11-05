"""Staging private originals: no public URLs, owner scopes, no paid providers."""
import hashlib
from io import BytesIO

import pytest

from app.core.nova.creative_studio import private_object_storage as objects


class InMemoryBucket:
    def __init__(self):
        self.objects = {}

    def put_object(self, *, Bucket, Key, Body, ContentType, Metadata):
        assert Bucket == "creative-originals-staging"
        assert ContentType == "video/mp4"
        self.objects[Key] = (Body, Metadata)

    def head_object(self, *, Bucket, Key):
        data, metadata = self.objects[Key]
        return {"ContentLength": len(data), "Metadata": metadata}

    def get_object(self, *, Bucket, Key):
        return {"Body": BytesIO(self.objects[Key][0])}

    def delete_object(self, *, Bucket, Key):
        self.objects.pop(Key, None)


@pytest.fixture
def storage(monkeypatch):
    client = InMemoryBucket()
    monkeypatch.setenv("NOVA_STUDIO_PRIVATE_OBJECT_STORAGE", "true")
    monkeypatch.setenv("NOVA_STUDIO_S3_BUCKET", "creative-originals-staging")
    monkeypatch.setattr(objects, "_client", lambda: client)
    return client


def test_remote_ref_is_private_and_owner_scoped(storage):
    raw = b"synthetic staging mp4 payload"
    checksum = hashlib.sha256(raw).hexdigest()
    ref = objects.put_original("test_owner", "test_project", "imported_video_abc.mp4", raw, checksum)
    assert ref == "private-studio-s3://test_owner/test_project/imported_video_abc.mp4"
    assert objects.object_exists(ref, "test_owner", "test_project", checksum)
    assert objects.open_original(ref, "test_owner", "test_project").read() == raw
    with pytest.raises(objects.PrivateStorageError):
        objects.open_original(ref, "other_owner", "test_project")
    with pytest.raises(objects.PrivateStorageError):
        objects.open_original(ref, "test_owner", "other_project")


def test_remote_import_rejects_wrong_checksum_and_unsafe_names(storage):
    with pytest.raises(objects.PrivateStorageError):
        objects.put_original("owner", "project", "imported_video_test.mp4", b"data", "0" * 64)
    assert storage.objects == {}
    for name in ["../imported_video_a.mp4", "imported_video_a.srt", "file.mp4"]:
        with pytest.raises(objects.PrivateStorageError):
            objects.make_key("owner", "project", name)
    with pytest.raises(objects.PrivateStorageError):
        objects.make_key("../owner", "project", "imported_video_abc.mp4")


def test_private_remote_import_requires_explicit_feature_toggle(storage, monkeypatch):
    monkeypatch.delenv("NOVA_STUDIO_PRIVATE_OBJECT_STORAGE")
    with pytest.raises(objects.PrivateStorageError):
        objects.put_original("owner", "project", "imported_video_a.mp4", b"a", hashlib.sha256(b"a").hexdigest())
    assert storage.objects == {}


def test_remote_original_deduped_without_provider_charge(storage, tmp_path, monkeypatch):
    from app.core.nova.creative_studio import video_import
    from app.core.nova.creative_studio.models import CreativeProject
    from app.core.nova.creative_studio.service import CreativeStudioService
    from app.core.nova.creative_studio.store import CreativeStudioStore

    monkeypatch.setenv("NOVA_CREATIVE_MEDIA_DIR", str(tmp_path / "staging-media"))
    monkeypatch.setattr(video_import, "validate_video", lambda _path: {
        "duration_seconds": 30.0, "width": 720, "height": 1280,
        "video_codec": "h264", "audio_codec": "aac", "decode_verified": True,
    })
    service = CreativeStudioService(CreativeStudioStore())
    project = service.create_project("owner", {
        "title": "Disposable staging video", "project_type": "promo_video",
        "platform": "TikTok", "duration_target": 30,
    })
    raw = b"synthetic staging fixture, not a valid commercial"
    result = service.import_finished_video("owner", project["id"], raw, content_type="video/mp4")
    assert result["asset"]["url"].startswith("private-studio-s3://")
    assert result["paid_request_submitted"] is False
    repeated = service.import_finished_video("owner", project["id"], raw, content_type="video/mp4")
    assert repeated["reused"] is True
    assert repeated["asset"]["id"] == result["asset"]["id"]
    stream, media_type, filename = service.open_private_remote_asset(
        "owner", project["id"], result["asset"]["id"]
    )
    assert stream.read() == raw
    assert media_type == "video/mp4"
    with pytest.raises(Exception):
        service.open_private_remote_asset("wrong-owner", project["id"], result["asset"]["id"])


def test_required_durable_imports_reject_ephemeral_fallback(monkeypatch, tmp_path):
    from app.core.nova.creative_studio.service import CreativeStudioService, CreativeStudioError
    from app.core.nova.creative_studio.store import CreativeStudioStore

    monkeypatch.setenv("NOVA_STUDIO_REQUIRE_DURABLE_IMPORTS", "true")
    monkeypatch.delenv("NOVA_STUDIO_PRIVATE_OBJECT_STORAGE", raising=False)
    monkeypatch.setenv("NOVA_CREATIVE_MEDIA_DIR", str(tmp_path / "temporary"))
    service = CreativeStudioService(CreativeStudioStore())
    project = service.create_project("owner", {
        "title": "Safe staging imports", "project_type": "promo_video",
        "platform": "TikTok", "duration_target": 30,
    })
    with pytest.raises(CreativeStudioError) as error:
        service.import_finished_video("owner", project["id"], b"unverified fake mp4", content_type="video/mp4")
    assert error.value.code == "PRIVATE_STORAGE_UNAVAILABLE"
    assert error.value.http_status == 503
    assert not list(tmp_path.rglob("*.mp4"))
