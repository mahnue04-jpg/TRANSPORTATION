"""Private Creative Studio playback/download guard: owner and object metadata checks."""
from types import SimpleNamespace

import pytest

from app.core.nova.creative_studio import private_object_storage as storage
from app.core.nova.creative_studio.service import CreativeStudioError, CreativeStudioService


def _studio(asset, owner="owner"):
    class FakeStore:
        def get_project(self, project_id, owner_id):
            return SimpleNamespace(id=project_id) if owner_id == owner else None

        def list_assets(self, project_id, owner_id):
            return [asset] if owner_id == owner else []

    return CreativeStudioService(store=FakeStore())


def _asset(digest="a" * 64):
    return SimpleNamespace(
        id="master-1", title="Private master", kind="video",
        url="private-studio-s3://owner/project/imported_video_test.mp4",
        metadata={"sha256": digest},
    )


def test_private_download_requires_head_validation_before_open(monkeypatch):
    asset = _asset()
    studio = _studio(asset)
    monkeypatch.setattr(storage, "enabled", lambda: True)
    seen = []
    stream = object()

    def check(ref, owner, project, digest):
        seen.append(("head", owner, project, digest))
        return 512

    def open_file(ref, owner, project):
        seen.append(("open", owner, project))
        return stream

    monkeypatch.setattr(storage, "owned_object_size", check)
    monkeypatch.setattr(storage, "open_original", open_file)
    result = studio.open_private_remote_asset("owner", "project", "master-1")
    assert result[0] is stream
    assert result[1] == "video/mp4"
    assert result[3] == 512
    assert [event[0] for event in seen] == ["head", "open"]


@pytest.mark.parametrize("digest,exists", [
    ("", True), ("too-short", True), ("a" * 64, False),
])
def test_unverified_private_download_never_opens_remote_stream(
    monkeypatch, digest, exists,
):
    studio = _studio(_asset(digest))
    monkeypatch.setattr(storage, "enabled", lambda: True)
    monkeypatch.setattr(storage, "owned_object_size", lambda *args: 512 if exists and len(digest) == 64 else None)
    monkeypatch.setattr(
        storage, "open_original",
        lambda *args: pytest.fail("Unverified object must not be streamed"),
    )
    with pytest.raises(CreativeStudioError) as err:
        studio.open_private_remote_asset("owner", "project", "master-1")
    assert err.value.http_status == 503


def test_cross_owner_download_is_denied_before_remote_access(monkeypatch):
    studio = _studio(_asset())
    monkeypatch.setattr(storage, "enabled", lambda: True)
    monkeypatch.setattr(
        storage, "owned_object_size",
        lambda *args: pytest.fail("Cross-owner request must not reach bucket"),
    )
    with pytest.raises(CreativeStudioError) as err:
        studio.open_private_remote_asset("other-owner", "project", "master-1")
    assert err.value.http_status == 404
