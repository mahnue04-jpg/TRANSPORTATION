"""Non-billable 30s provider path. No fal posts and no local montage."""

import json
import wave
from pathlib import Path

import pytest

from app.core.nova.creative_studio.kling import FalKlingLipSyncProvider, FalKlingVideoProvider
from app.core.nova.creative_studio.models import CreativeScene, new_id
from app.core.nova.creative_studio.service import CreativeStudioError, CreativeStudioService
from app.core.nova.creative_studio.store import CreativeStudioStore

LINES = [
    "Meet AMICOR Nova, your AI operations workspace.",
    "Busywork piles up and steals focus from real work.",
    "AMICOR helps with research, follow-ups, workflows, and data cleanup.",
    "AMICOR prepares drafts, then you review before anything moves.",
    "Keep ownership and make room for real business progress.",
    "Visit getamicor.com to explore AMICOR Nova.",
]
SCRIPT = " ".join(LINES)


def _wav(path: Path, frames: int = 8000) -> None:
    with wave.open(str(path), "wb") as audio:
        audio.setnchannels(1)
        audio.setsampwidth(2)
        audio.setframerate(8000)
        audio.writeframes(b"\0\0" * frames)


def _card(**overrides):
    card = {
        "source": "owner_verified_provider_price",
        "currency": "USD",
        "motion_usd_per_5s_shot": 0.40,
        "lipsync_usd_per_clip": 0.20,
        "shot_count": 6,
        "balance_usd": 8.00,
        "balance_status": "owner_reported",
    }
    card.update(overrides)
    return card


def _forbid_posts(monkeypatch):
    def fail(*_args, **_kwargs):
        raise AssertionError("provider post attempted")

    monkeypatch.setattr(FalKlingVideoProvider, "generate", fail)
    monkeypatch.setattr(FalKlingLipSyncProvider, "generate_lipsync", fail)
    monkeypatch.setattr(FalKlingVideoProvider, "_request_json", fail)
    monkeypatch.setattr(FalKlingLipSyncProvider, "_request_json", fail)


@pytest.fixture
def ready(tmp_path, monkeypatch):
    monkeypatch.setenv("NOVA_CREATIVE_MEDIA_DIR", str(tmp_path))
    monkeypatch.setenv("NOVA_CREATIVE_MEDIA_PUBLIC_PREFIX", "/media/nova-creative")
    monkeypatch.delenv("FAL_KEY", raising=False)
    monkeypatch.setenv("NOVA_CREATIVE_VIDEO_LIVE_ENABLED", "false")
    monkeypatch.setenv("NOVA_CREATIVE_KLING_LIVE_ENABLED", "false")
    _forbid_posts(monkeypatch)
    svc = CreativeStudioService(CreativeStudioStore())
    owner = "provider-30s-owner"
    project = svc.create_project(
        owner,
        {"title": "Guarded 30s", "project_type": "short_video", "platform": "TikTok", "duration_target": 30},
    )
    image = tmp_path / "genova.png"
    image.write_bytes(b"\x89PNG\r\n")
    image_asset = svc._save_text_asset(
        owner_id=owner,
        project_id=project["id"],
        kind="image",
        title="Approved Genova",
        content="owner approved presenter",
        status="GENERATED",
        url="/media/nova-creative/genova.png",
    )
    svc.set_genova_presenter_approval(owner, project["id"], image_asset.id)
    shot_ids = []
    for index, _line in enumerate(LINES, start=1):
        name = f"shot-{index}.wav"
        _wav(tmp_path / name)
        asset = svc._save_text_asset(
            owner_id=owner,
            project_id=project["id"],
            kind="audio",
            title=f"Shot {index} narration",
            content=LINES[index - 1],
            status="GENERATED",
            url=f"/media/nova-creative/{name}",
        )
        shot_ids.append(asset.id)
    _wav(tmp_path / "narration.wav")
    narration = svc._save_text_asset(
        owner_id=owner,
        project_id=project["id"],
        kind="audio",
        title="Approved narration",
        content=SCRIPT,
        status="GENERATED",
        url="/media/nova-creative/narration.wav",
        metadata={
            "pronunciation_contract": "AM ih core",
            "shot_audio_asset_ids": shot_ids,
        },
    )
    svc._save_text_asset(
        owner_id=owner,
        project_id=project["id"],
        kind="presenter_script",
        title="Exact script",
        content=SCRIPT,
        status="GENERATED",
    )
    for index, line in enumerate(LINES, start=1):
        svc.store.save_scene(
            CreativeScene(
                id=new_id("cscene"),
                project_id=project["id"],
                owner_id=owner,
                index=index,
                heading=f"Beat {index}",
                description="Approved Genova presenter motion",
                visual_prompt="Natural walk, no text",
                voiceover_text=line,
                subtitle_text=line,
                duration_seconds=5,
            )
        )
    svc.set_genova_narration_approval(owner, project["id"], narration.id)
    return svc, owner, project["id"]


def test_no_provider_post_without_approval(tmp_path, monkeypatch):
    monkeypatch.setenv("NOVA_CREATIVE_MEDIA_DIR", str(tmp_path))
    monkeypatch.setenv("NOVA_CREATIVE_MEDIA_PUBLIC_PREFIX", "/media/nova-creative")
    monkeypatch.delenv("FAL_KEY", raising=False)
    monkeypatch.setenv("NOVA_CREATIVE_VIDEO_LIVE_ENABLED", "false")
    monkeypatch.setenv("NOVA_CREATIVE_KLING_LIVE_ENABLED", "false")
    _forbid_posts(monkeypatch)
    svc = CreativeStudioService(CreativeStudioStore())
    project = svc.create_project(
        "unapproved-owner",
        {"title": "No approval", "project_type": "short_video", "platform": "TikTok", "duration_target": 30},
    )
    result = svc.reserve_provider_commercial_30s("unapproved-owner", project["id"], _card())
    assert result["reserved"] is False
    assert result["paid_provider_charges"] is False
    assert result["provider_posts"] == 0
    assert "missing_presenter_image" in result["blockers"]
    assert result["credentials"]["fal_key_present"] is False
    assert result["activation"]["video_live_enabled"] is False
    assert result["activation"]["kling_live_enabled"] is False
    stored = svc._project_or_404("unapproved-owner", project["id"])
    assert "provider_commercial_30s_reservation" not in (stored.metadata or {})


def test_exact_script_pronunciation_and_idempotent_reservation(ready):
    svc, owner, project_id = ready
    first = svc.reserve_provider_commercial_30s(owner, project_id, _card())
    assert first["reserved"] is True
    assert first["pronunciation_confirmed"] is True
    assert first["pronunciation"] == "AM ih core"
    assert first["exact_script"] == SCRIPT
    assert first["price"]["verified"] is True
    assert first["price"]["per_shot_motion_usd"] == "0.40"
    assert first["price"]["per_shot_lipsync_usd"] == "0.20"
    assert first["price"]["total_usd"] == "3.60"
    assert first["price"]["within_ceiling"] is True
    assert first["paid_provider_charges"] is False
    assert first["provider_posts"] == 0
    assert first["submission_authorized"] is False
    assert first["uses_local_montage"] is False
    second = svc.reserve_provider_commercial_30s(owner, project_id, _card())
    assert second["idempotent_replay"] is True
    assert second["reservation"]["reservation_id"] == first["reservation"]["reservation_id"]
    assert second["provider_posts"] == 0
    assets = [asset for asset in svc.store.list_assets(project_id, owner) if asset.kind == "cost_reservation"]
    assert len(assets) == 1


def test_price_ambiguity_ceiling_and_balance_fail_closed(ready):
    svc, owner, project_id = ready
    ambiguous = svc.reserve_provider_commercial_30s(owner, project_id, dict(_card(), note="maybe"))
    assert ambiguous["reserved"] is False
    assert "ambiguous_price" in ambiguous["blockers"]
    planning = svc.reserve_provider_commercial_30s(owner, project_id, _card(source="planning_estimate"))
    assert "unverified_per_shot_price" in planning["blockers"]
    ceiling = svc.reserve_provider_commercial_30s(
        owner, project_id, _card(motion_usd_per_5s_shot=1.00, lipsync_usd_per_clip=0.50)
    )
    assert "above_internal_ceiling" in ceiling["blockers"]
    balance = svc.reserve_provider_commercial_30s(owner, project_id, _card(balance_status="cannot_verify", balance_usd=8))
    assert "balance_unverified" in balance["blockers"]
    short = svc.reserve_provider_commercial_30s(owner, project_id, _card(balance_usd=1))
    assert "insufficient_reported_balance" in short["blockers"]
    stored = svc._project_or_404(owner, project_id)
    assert stored.metadata.get("provider_commercial_30s_reservation") is None


def test_open_reservation_conflict_does_not_replace_or_post(ready):
    svc, owner, project_id = ready
    first = svc.reserve_provider_commercial_30s(owner, project_id, _card())
    second = svc.reserve_provider_commercial_30s(owner, project_id, _card(motion_usd_per_5s_shot=0.45))
    assert second["reserved"] is False
    assert "ambiguous_open_reservation" in second["blockers"]
    assert second["provider_posts"] == 0
    stored = svc._project_or_404(owner, project_id)
    assert stored.metadata["provider_commercial_30s_reservation"]["reservation_id"] == first["reservation"]["reservation_id"]
    assert stored.metadata["provider_commercial_30s_reservation"]["amount_usd"] == "3.60"


def test_resume_save_and_download_without_provider_contact(ready):
    svc, owner, project_id = ready
    reserved = svc.reserve_provider_commercial_30s(owner, project_id, _card())
    token = FalKlingVideoProvider()._encode_task(
        {
            "request_id": "shot-1",
            "status_url": "https://queue.fal.run/fal-ai/kling-video/requests/shot-1/status",
            "response_url": "https://queue.fal.run/fal-ai/kling-video/requests/shot-1",
        }
    )
    project = svc._project_or_404(owner, project_id)
    reservation = dict(project.metadata["provider_commercial_30s_reservation"])
    reservation["shots"][0]["motion_task_id"] = token
    project.metadata = {**project.metadata, "provider_commercial_30s_reservation": reservation}
    svc.store.save_project(project)
    restored = CreativeStudioService(svc.store)
    checked = restored.validate_provider_commercial_30s_resume(owner, project_id)
    assert checked["resume_valid"] is True
    assert checked["download_ready"] is True
    assert checked["provider_posts"] == 0
    assert checked["paid_provider_charges"] is False
    path, _media, _name = restored.open_asset_file(owner, project_id, reservation["download_asset_id"])
    body = path.read_text(encoding="utf-8")
    assert json.loads(body)["reservation_id"] == reserved["reservation"]["reservation_id"]
    assert "test-only" not in body
    reservation["shots"][0]["motion_task_id"] = "fal-kling25:not-a-task"
    project = svc._project_or_404(owner, project_id)
    project.metadata = {**project.metadata, "provider_commercial_30s_reservation": reservation}
    svc.store.save_project(project)
    invalid = svc.validate_provider_commercial_30s_resume(owner, project_id)
    assert invalid["resume_valid"] is False
    assert any(item.startswith("invalid_motion_task_") for item in invalid["problems"])
    assert invalid["provider_posts"] == 0


def test_pronunciation_mismatch_fails_closed(ready):
    svc, owner, project_id = ready
    narration = next(asset for asset in svc.store.list_assets(project_id, owner) if asset.url and asset.url.endswith("narration.wav"))
    narration.metadata = {**narration.metadata, "pronunciation_contract": "AH-mih-kor"}
    svc.store.save_asset(narration)
    result = svc.reserve_provider_commercial_30s(owner, project_id, _card())
    assert result["reserved"] is False
    assert "pronunciation_unconfirmed" in result["blockers"]
    assert result["provider_posts"] == 0


def test_submit_does_not_post_without_authorization_or_flags(ready, monkeypatch):
    svc, owner, project_id = ready
    svc.reserve_provider_commercial_30s(owner, project_id, _card())
    refused = svc.submit_provider_commercial_30s(owner, project_id, authorize_provider_submit=False)
    assert refused["submission_authorized"] is False
    assert "authorization_required" in refused["blockers"]
    assert refused["provider_posts"] == 0
    monkeypatch.setenv("FAL_KEY", "test-only")
    monkeypatch.setenv("NOVA_CREATIVE_VIDEO_PROVIDER", "kling")
    monkeypatch.setenv("NOVA_CREATIVE_VIDEO_LIVE_ENABLED", "false")
    monkeypatch.setenv("NOVA_CREATIVE_KLING_LIVE_ENABLED", "false")
    gated = svc.render_walking_commercial_30s(owner, project_id, authorize_provider_submit=True)
    assert gated["submission_authorized"] is False
    assert "live_flag_off" in gated["blockers"]
    assert gated["provider_posts"] == 0
    assert gated["uses_local_montage"] is False
    assert gated["offline_demo_fallback"] is False


def test_in_memory_paid_submit_fails_closed_without_atomic_store(ready, monkeypatch):
    """Test stores cannot silently bypass the database's atomic claim gate."""
    svc, owner, project_id = ready
    svc.reserve_provider_commercial_30s(owner, project_id, _card())
    monkeypatch.setenv("FAL_KEY", "test-only")
    monkeypatch.setenv("NOVA_CREATIVE_VIDEO_PROVIDER", "kling")
    monkeypatch.setenv("NOVA_CREATIVE_VIDEO_LIVE_ENABLED", "true")
    monkeypatch.setenv("NOVA_CREATIVE_KLING_LIVE_ENABLED", "true")
    def forbidden(*args, **kwargs):
        raise AssertionError("Paid provider POST attempted without durable atomic claim")
    monkeypatch.setattr(FalKlingVideoProvider, "generate", forbidden)
    monkeypatch.setattr(FalKlingLipSyncProvider, "generate_lipsync", forbidden)
    first = svc.submit_provider_commercial_30s(owner, project_id, authorize_provider_submit=True)
    second = svc.submit_provider_commercial_30s(owner, project_id, authorize_provider_submit=True)
    assert first["submission_authorized"] is False
    assert second["submission_authorized"] is False
    assert "submission_claim_unavailable" in first["blockers"]
    assert first["provider_posts"] == second["provider_posts"] == 0


def test_ambiguous_post_does_not_submit_again(ready, monkeypatch):
    svc, owner, project_id = ready
    svc.reserve_provider_commercial_30s(owner, project_id, _card())
    project = svc._project_or_404(owner, project_id)
    reservation = dict(project.metadata["provider_commercial_30s_reservation"])
    reservation["shots"][0]["post_attempted"] = True
    reservation["shots"][0]["motion_task_id"] = None
    project.metadata = {**project.metadata, "provider_commercial_30s_reservation": reservation}
    svc.store.save_project(project)
    monkeypatch.setenv("FAL_KEY", "test-only")
    monkeypatch.setenv("NOVA_CREATIVE_VIDEO_PROVIDER", "kling")
    monkeypatch.setenv("NOVA_CREATIVE_VIDEO_LIVE_ENABLED", "true")
    monkeypatch.setenv("NOVA_CREATIVE_KLING_LIVE_ENABLED", "true")
    result = svc.submit_provider_commercial_30s(owner, project_id, authorize_provider_submit=True)
    assert result["submission_authorized"] is False
    assert "ambiguous_provider_post" in result["blockers"]
    assert result["provider_posts"] == 0


def test_default_30s_route_stays_offline_even_when_reserved(ready, monkeypatch):
    from app.core.nova.creative_studio import walking_presenter as media

    svc, owner, project_id = ready
    svc.reserve_provider_commercial_30s(owner, project_id, _card())
    monkeypatch.setenv("FAL_KEY", "test-only")
    monkeypatch.setenv("NOVA_CREATIVE_VIDEO_PROVIDER", "kling")
    monkeypatch.setenv("NOVA_CREATIVE_VIDEO_LIVE_ENABLED", "true")
    monkeypatch.setenv("NOVA_CREATIVE_KLING_LIVE_ENABLED", "true")

    def stop(**_kwargs):
        raise media.WalkingPresenterError("TEST_STOP", "offline demo")

    monkeypatch.setattr(media, "render_walking_commercial_30s", stop)
    with pytest.raises(CreativeStudioError) as exc:
        svc.render_walking_commercial_30s(owner, project_id)
    assert exc.value.code == "TEST_STOP"


def test_atomic_claim_only_one_winner_for_simultaneous_requests(ready, monkeypatch):
    """No real provider calls: two contenders can claim the same held job only once.

    Uses a locked fake compare-and-swap to check the orchestration contract.
    A separate SQLite/Postgres integration test is still required before paid use.
    """
    import copy
    import threading
    from concurrent.futures import ThreadPoolExecutor

    from app.core.nova.creative_studio.provider_commercial_30s import _atomic_claim_reservation

    svc, owner, project_id = ready
    svc.reserve_provider_commercial_30s(owner, project_id, _card())
    original = copy.deepcopy(svc._project_or_404(owner, project_id).metadata)
    state = {"metadata": original, "successful_claims": 0}
    lock = threading.Lock()

    def snapshot(_owner, _project):
        assert (_owner, _project) == (owner, project_id)
        project = copy.copy(svc._project_or_404(owner, project_id))
        with lock:
            project.metadata = copy.deepcopy(state["metadata"])
        return project

    def compare_and_swap(_project, _owner, expected, replacement):
        assert (_owner, _project) == (owner, project_id)
        with lock:
            if state["metadata"] != expected:
                return False
            state["metadata"] = copy.deepcopy(replacement)
            state["successful_claims"] += 1
            return True

    monkeypatch.setattr(svc, "_project_or_404", snapshot)
    monkeypatch.setattr(svc.store, "compare_and_swap_project_metadata", compare_and_swap, raising=False)
    with ThreadPoolExecutor(max_workers=2) as pool:
        outcomes = list(pool.map(
            lambda _: _atomic_claim_reservation(svc, owner, project_id, expected_status="reserved"),
            range(2),
        ))
    assert sorted(outcomes) == [False, True]
    assert state["successful_claims"] == 1
    assert state["metadata"]["provider_commercial_30s_reservation"]["submission_claimed"] is True
