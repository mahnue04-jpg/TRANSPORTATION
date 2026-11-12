"""Keep the offline 30s montage row and look for its file on the persistent disk.

These tests do not render a montage, delete a live file, or change an owner.
"""

from __future__ import annotations

from pathlib import Path

from app.core.nova.creative_studio.models import CreativeAsset, CreativeProject
from app.core.nova.creative_studio.providers import (
    _resolve_creative_media_url,
    choose_creative_media_root,
)
from app.core.nova.creative_studio.service import CreativeStudioService
from app.core.nova.creative_studio.store import CreativeStudioStore


def test_media_root_prefers_explicit_dir_then_onboarding_disk_then_data_root(tmp_path: Path) -> None:
    ephemeral = tmp_path / "ephemeral"
    configured = choose_creative_media_root(
        configured=str(tmp_path / "configured"),
        onboarding_docs_exists=True,
        data_dir_exists=True,
        ephemeral=ephemeral,
        public_prefix="/media/custom",
    )
    assert configured == (tmp_path / "configured", "/media/custom")

    production = choose_creative_media_root(
        configured="",
        onboarding_docs_exists=True,
        data_dir_exists=True,
        ephemeral=ephemeral,
        public_prefix="/media/nova-creative",
    )
    assert production == (Path("/data/onboarding_docs/nova_creative_media"), "/media/nova-creative")

    staging = choose_creative_media_root(
        configured="",
        onboarding_docs_exists=False,
        data_dir_exists=True,
        ephemeral=ephemeral,
        public_prefix="/media/nova-creative",
    )
    assert staging == (Path("/data/nova_creative_media"), "/media/nova-creative")

    local = choose_creative_media_root(
        configured="",
        onboarding_docs_exists=False,
        data_dir_exists=False,
        ephemeral=ephemeral,
        public_prefix="/media/nova-creative",
    )
    assert local == (ephemeral, "/static/generated/nova-creative")


def test_resolve_finds_saved_montage_on_another_persistent_root(tmp_path, monkeypatch) -> None:
    primary = tmp_path / "primary"
    surviving = tmp_path / "data-nova"
    primary.mkdir()
    surviving.mkdir()
    filename = "nova-offline-abc123.mp4"
    (surviving / filename).write_bytes(b"ftyp-preserved")
    monkeypatch.setattr(
        "app.core.nova.creative_studio.providers._creative_media_root_and_prefix",
        lambda: (primary, "/media/nova-creative"),
    )
    monkeypatch.setattr(
        "app.core.nova.creative_studio.providers.creative_media_search_roots",
        lambda: [primary, surviving],
    )

    found = _resolve_creative_media_url("/media/nova-creative/" + filename)
    assert found == surviving / filename
    assert found.is_file()

    missing = _resolve_creative_media_url("/media/nova-creative/nova-offline-missing.mp4")
    assert missing == primary / "nova-offline-missing.mp4"
    assert missing.is_file() is False


def test_preview_cleanup_keeps_offline_montage_and_its_file(tmp_path: Path) -> None:
    store = CreativeStudioStore()
    service = CreativeStudioService(store)
    project = CreativeProject(
        id="cproj_testmontage",
        owner_id="owner-a",
        title="Nova",
        project_type="short_video",
        platform="TikTok",
    )
    store.save_project(project)
    media = tmp_path / "nova-offline-keep.mp4"
    media.write_bytes(b"preserved-montage")
    montage = CreativeAsset(
        id="asset_montage",
        project_id=project.id,
        owner_id="owner-a",
        kind="video",
        title="Offline 30s AMICOR Nova montage",
        content="Local title-card montage.",
        status="GENERATED",
        url=str(media),
        metadata={
            "quality_state": "PREVIEW_ONLY",
            "render_mode": "offline_montage_not_lipsync",
            "pipeline": "offline_title_card_fallback",
            "duration_seconds": 30.0,
            "provider_result": {"duration_seconds": 30.0},
        },
    )
    headshot = CreativeAsset(
        id="asset_headshot",
        project_id=project.id,
        owner_id="owner-a",
        kind="presenter_video",
        title="Old headshot",
        content="preview",
        status="GENERATED",
        url=None,
        metadata={"presenter_mode": "head", "quality_state": "PREVIEW_ONLY"},
    )
    script = CreativeAsset(
        id="asset_script",
        project_id=project.id,
        owner_id="owner-a",
        kind="script",
        title="Short script",
        content="script",
        status="GENERATED",
    )
    store.save_asset(montage)
    store.save_asset(headshot)
    store.save_asset(script)

    # The saved URL is a local test path, not a public media URL, so cleanup
    # must not treat it as a file to unlink via the public resolver.
    result = service.clear_legacy_preview_videos("owner-a", project.id)

    remaining = {row.id for row in store.list_assets(project.id, "owner-a")}
    assert "asset_montage" in remaining
    assert "asset_script" in remaining
    assert "asset_headshot" not in remaining
    assert result["deleted_asset_records"] == 1
    assert media.is_file()
    assert media.read_bytes() == b"preserved-montage"
