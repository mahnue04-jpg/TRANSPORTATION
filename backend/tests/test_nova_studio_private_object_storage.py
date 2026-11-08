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


def test_remote_original_survives_service_recreation_and_cleanup(storage, tmp_path, monkeypatch):
    """Simulate a service restart over the same durable asset records and remote bucket.

    This is a unit-level persistence test, not a real staging process/disk restart.
    """
    from app.core.nova.creative_studio import video_import
    from app.core.nova.creative_studio.models import CreativeAsset
    from app.core.nova.creative_studio.service import CreativeStudioService
    from app.core.nova.creative_studio.store import CreativeStudioStore

    monkeypatch.setenv("NOVA_STUDIO_REQUIRE_DURABLE_IMPORTS", "true")
    monkeypatch.setenv("NOVA_CREATIVE_MEDIA_DIR", str(tmp_path / "ephemeral-previews"))
    monkeypatch.setenv("NOVA_CREATIVE_MEDIA_PUBLIC_PREFIX", "/media/nova-creative")
    monkeypatch.setattr(video_import, "validate_video", lambda _path: {
        "duration_seconds": 30.0, "width": 720, "height": 1280,
        "video_codec": "h264", "audio_codec": "aac", "decode_verified": True,
    })
    store = CreativeStudioStore()
    first = CreativeStudioService(store)
    project_id = first.create_project("owner", {
        "title": "Remote original retention", "project_type": "promo_video",
        "platform": "TikTok", "duration_target": 30,
    })["id"]
    original = b"fixture-bytes-only-not-playable-video"
    digest = hashlib.sha256(original).hexdigest()
    uploaded = first.import_finished_video("owner", project_id, original, content_type="video/mp4")
    asset_id = uploaded["asset"]["id"]
    ref = uploaded["asset"]["url"]
    assert ref.startswith("private-studio-s3://")
    assert objects.object_exists(ref, "owner", project_id, digest)

    # A disposable preview should be deleted, but the private original should
    # not be removed from remote storage or from the asset metadata.
    preview_root = tmp_path / "ephemeral-previews"
    preview_root.mkdir()
    preview = preview_root / "disposable-preview.mp4"
    preview.write_bytes(b"preview")
    store.save_asset(CreativeAsset(
        id="disposable-preview", project_id=project_id, owner_id="owner",
        kind="video", title="Preview", content="",
        url="/media/nova-creative/disposable-preview.mp4",
    ))
    assert first.reset_project_media("owner", project_id)["deleted_media_files"] == 1
    assert not preview.exists()
    assert objects.object_exists(ref, "owner", project_id, digest)

    # Recreate the service while retaining the same backing store to emulate
    # application-object replacement. Actual SQL/storage restart is a separate gate.
    second = CreativeStudioService(store)
    stream, mime, _filename = second.open_private_remote_asset("owner", project_id, asset_id)
    assert mime == "video/mp4"
    assert hashlib.sha256(stream.read()).hexdigest() == digest
    assert second.import_finished_video(
        "owner", project_id, original, content_type="video/mp4"
    )["reused"] is True
    assert len(storage.objects) == 1
    with pytest.raises(Exception):
        second.open_private_remote_asset("other-owner", project_id, asset_id)
    with pytest.raises(Exception):
        second.open_private_remote_asset("owner", "other-project", asset_id)


def test_private_storage_disconnection_fails_closed_and_recovers(storage, tmp_path, monkeypatch):
    """A temporary object-store configuration outage must not serve stale public media."""
    from app.core.nova.creative_studio import video_import
    from app.core.nova.creative_studio.service import CreativeStudioService, CreativeStudioError
    from app.core.nova.creative_studio.store import CreativeStudioStore

    monkeypatch.setenv("NOVA_STUDIO_REQUIRE_DURABLE_IMPORTS", "true")
    monkeypatch.setenv("NOVA_CREATIVE_MEDIA_DIR", str(tmp_path / "media"))
    monkeypatch.setattr(video_import, "validate_video", lambda _path: {
        "duration_seconds": 30.0, "width": 720, "height": 1280,
        "video_codec": "h264", "audio_codec": "aac", "decode_verified": True,
    })
    service = CreativeStudioService(CreativeStudioStore())
    project_id = service.create_project("owner", {
        "title": "Storage outage", "project_type": "promo_video",
        "platform": "TikTok", "duration_target": 30,
    })["id"]
    original = b"offline-test-fixture"
    asset = service.import_finished_video(
        "owner", project_id, original, content_type="video/mp4"
    )["asset"]
    monkeypatch.setenv("NOVA_STUDIO_PRIVATE_OBJECT_STORAGE", "false")
    with pytest.raises(CreativeStudioError) as failure:
        service.open_private_remote_asset("owner", project_id, asset["id"])
    assert failure.value.http_status == 503

    monkeypatch.setenv("NOVA_STUDIO_PRIVATE_OBJECT_STORAGE", "true")
    stream, _, _ = service.open_private_remote_asset("owner", project_id, asset["id"])
    assert stream.read() == original


def test_durable_mode_does_not_reuse_legacy_ephemeral_import(storage, tmp_path, monkeypatch):
    """Require remote persistence even when identical bytes exist on local disk."""
    from app.core.nova.creative_studio import video_import
    from app.core.nova.creative_studio.service import CreativeStudioService
    from app.core.nova.creative_studio.store import CreativeStudioStore

    monkeypatch.setenv("NOVA_CREATIVE_MEDIA_DIR", str(tmp_path / "media"))
    monkeypatch.setattr(video_import, "validate_video", lambda _path: {
        "duration_seconds": 30.0, "width": 720, "height": 1280,
        "video_codec": "h264", "audio_codec": "aac", "decode_verified": True,
    })
    service = CreativeStudioService(CreativeStudioStore())
    project_id = service.create_project("owner", {
        "title": "Legacy to durable migration", "project_type": "promo_video",
        "platform": "TikTok", "duration_target": 30,
    })["id"]
    original = b"synthetic-mp4-migration-fixture"
    monkeypatch.setenv("NOVA_STUDIO_PRIVATE_OBJECT_STORAGE", "false")
    monkeypatch.delenv("NOVA_STUDIO_REQUIRE_DURABLE_IMPORTS", raising=False)
    legacy = service.import_finished_video(
        "owner", project_id, original, content_type="video/mp4"
    )["asset"]
    assert legacy["url"].startswith("private-studio://")

    monkeypatch.setenv("NOVA_STUDIO_PRIVATE_OBJECT_STORAGE", "true")
    monkeypatch.setenv("NOVA_STUDIO_REQUIRE_DURABLE_IMPORTS", "true")
    migrated = service.import_finished_video(
        "owner", project_id, original, content_type="video/mp4"
    )
    assert migrated["reused"] is False
    assert migrated["asset"]["url"].startswith("private-studio-s3://")
    assert migrated["asset"]["id"] != legacy["id"]
    assert len(storage.objects) == 1
    stream, mime, _ = service.open_private_remote_asset(
        "owner", project_id, migrated["asset"]["id"]
    )
    assert mime == "video/mp4"
    assert stream.read() == original
    repeated = service.import_finished_video(
        "owner", project_id, original, content_type="video/mp4"
    )
    assert repeated["reused"] is True
    assert repeated["asset"]["id"] == migrated["asset"]["id"]
