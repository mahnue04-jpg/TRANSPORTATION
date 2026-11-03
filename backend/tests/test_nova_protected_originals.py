"""Regression checks for protected originals in both Creative Studio stores."""
from app.core.nova.creative_studio.models import CreativeAsset
from app.core.nova.creative_studio.store import CreativeStudioStore


def asset(asset_id, *, source=None, status="GENERATED"):
    return CreativeAsset(
        id=asset_id, project_id="project", owner_id="owner", kind="video",
        title=asset_id, content="", status=status,
        metadata={"source": source} if source else {},
    )


def test_media_reset_preserves_owner_imports():
    store = CreativeStudioStore()
    for row in [
        asset("original", source="owner_video_import"),
        asset("older-import", source="owner_import"),
        asset("preview"),
    ]:
        store.save_asset(row)
    deleted = store.delete_assets_by_kinds("project", "owner", {"video"})
    assert [row.id for row in deleted] == ["preview"]
    assert {row.id for row in store.list_assets("project", "owner")} == {"original", "older-import"}


def test_preview_cleanup_preserves_imported_original():
    store = CreativeStudioStore()
    store.save_asset(asset("original", source="owner_video_import"))
    store.save_asset(asset("preview"))
    deleted = store.delete_assets_by_ids("project", "owner", {"original", "preview"})
    assert [row.id for row in deleted] == ["preview"]
    assert [row.id for row in store.list_assets("project", "owner")] == ["original"]


def test_failed_cleanup_preserves_owner_original():
    store = CreativeStudioStore()
    store.save_asset(asset("original", source="owner_video_import", status="ERROR"))
    store.save_asset(asset("failed-preview", status="ERROR"))
    assert store.delete_failed_video_assets("project", "owner") == 1
    assert [row.id for row in store.list_assets("project", "owner")] == ["original"]


def test_approved_master_protected():
    store = CreativeStudioStore()
    row = asset("approved")
    row.metadata["approved_master"] = True
    store.save_asset(row)
    assert store.delete_assets_by_kinds("project", "owner", {"video"}) == []
    assert store.get_project("project", "owner") is None
    assert len(store.list_assets("project", "owner")) == 1


def test_import_reset_preserves_original_file_and_checksum(tmp_path, monkeypatch):
    """Exercise the service cleanup and disk file, without live users or providers."""
    import hashlib
    from app.core.nova.creative_studio.service import CreativeStudioService
    from app.core.nova.creative_studio import video_import

    monkeypatch.setenv("NOVA_CREATIVE_MEDIA_DIR", str(tmp_path))
    monkeypatch.setenv("NOVA_CREATIVE_MEDIA_PUBLIC_PREFIX", "/media/nova-creative")
    monkeypatch.setattr(video_import, "validate_video", lambda path: {
        "duration_seconds": 30.0, "width": 720, "height": 1280,
        "video_codec": "h264", "audio_codec": "aac", "decode_verified": True,
    })
    store = CreativeStudioStore()
    service = CreativeStudioService(store)
    project = service.create_project("owner", {
        "title": "Protected test commercial", "project_type": "promo_video",
        "platform": "TikTok", "duration_target": 30,
    })
    project_id = project["id"]
    original = b"test-fixture-mp4-bytes-no-actual-playback"
    saved = service.import_finished_video("owner", project_id, original, content_type="video/mp4")
    saved_id = saved["asset"]["id"]
    saved_path, _, _ = service.open_asset_file("owner", project_id, saved_id)
    assert saved_path.read_bytes() == original
    assert saved["asset"]["metadata"]["sha256"] == hashlib.sha256(original).hexdigest()

    disposable = tmp_path / "disposable-preview.mp4"
    disposable.write_bytes(b"disposable")
    store.save_asset(CreativeAsset(
        id="disposable", project_id=project_id, owner_id="owner",
        kind="video", title="Preview", content="Preview",
        url="/media/nova-creative/disposable-preview.mp4",
    ))
    result = service.reset_project_media("owner", project_id)
    assert result["deleted_media_files"] == 1
    assert not disposable.exists()
    assert saved_path.is_file()
    assert saved_path.read_bytes() == original
    readback, media_type, _ = service.open_asset_file("owner", project_id, saved_id)
    assert media_type == "video/mp4"
    assert hashlib.sha256(readback.read_bytes()).hexdigest() == hashlib.sha256(original).hexdigest()
    assert len([a for a in store.list_assets(project_id, "owner") if a.id == saved_id]) == 1


def test_real_h264_aac_mp4_survives_cleanup(tmp_path, monkeypatch):
    """Decode a real local MP4 and retain exact bytes after routine reset."""
    import hashlib
    import shutil
    import subprocess

    import pytest
    from app.core.nova.creative_studio.service import CreativeStudioService

    if not shutil.which("ffmpeg") or not shutil.which("ffprobe"):
        pytest.skip("FFmpeg/ffprobe required for actual MP4 validation")

    source = tmp_path / "valid-original.mp4"
    subprocess.run([
        "ffmpeg", "-hide_banner", "-loglevel", "error", "-y",
        "-f", "lavfi", "-i", "color=c=blue:size=256x256:rate=24",
        "-f", "lavfi", "-i", "sine=frequency=440:sample_rate=44100",
        "-t", "1", "-c:v", "libx264", "-pix_fmt", "yuv420p",
        "-c:a", "aac", "-shortest", "-movflags", "+faststart",
        str(source),
    ], check=True, timeout=30)
    original = source.read_bytes()
    digest = hashlib.sha256(original).hexdigest()
    media_dir = tmp_path / "studio"
    monkeypatch.setenv("NOVA_CREATIVE_MEDIA_DIR", str(media_dir))
    monkeypatch.setenv("NOVA_CREATIVE_MEDIA_PUBLIC_PREFIX", "/media/nova-creative")
    store = CreativeStudioStore()
    service = CreativeStudioService(store)
    project_id = service.create_project("owner", {
        "title": "Real-media retention", "project_type": "promo_video",
        "platform": "TikTok", "duration_target": 30,
    })["id"]
    saved = service.import_finished_video("owner", project_id, original, content_type="video/mp4")
    asset_id = saved["asset"]["id"]
    assert saved["asset"]["metadata"]["decode_verified"] is True
    assert saved["asset"]["metadata"]["sha256"] == digest
    assert service.import_finished_video(
        "owner", project_id, original, content_type="video/mp4"
    )["reused"] is True

    preview = media_dir / "temporary-preview.mp4"
    preview.write_bytes(b"temporary-preview")
    store.save_asset(CreativeAsset(
        id="temporary-preview", project_id=project_id, owner_id="owner",
        kind="video", title="Disposable preview", content="",
        url="/media/nova-creative/temporary-preview.mp4",
    ))
    result = service.reset_project_media("owner", project_id)
    assert result["deleted_media_files"] == 1
    assert not preview.exists()
    saved_path, mime, _ = service.open_asset_file("owner", project_id, asset_id)
    assert mime == "video/mp4"
    assert hashlib.sha256(saved_path.read_bytes()).hexdigest() == digest
    with pytest.raises(Exception):
        service.open_asset_file("different-owner", project_id, asset_id)
