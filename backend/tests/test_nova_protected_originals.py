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
