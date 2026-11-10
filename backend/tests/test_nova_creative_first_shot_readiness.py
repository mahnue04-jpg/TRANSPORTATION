"""Non-billable first-shot readiness checks for Nova Creative Studio.

These tests do not contact any generation provider and do not spend credits.
"""
from types import SimpleNamespace

from app.core.nova.creative_studio.first_shot_readiness import first_shot_readiness


def _scene(index=1, visual_prompt="Two actors work beside a canoe"):
    return SimpleNamespace(index=index, visual_prompt=visual_prompt, description="")


def _image(path, *, scene_index=1):
    return SimpleNamespace(
        id="img-1", kind="image", status="GENERATED", url=str(path),
        metadata={"scene_index": scene_index},
    )


def _run(*, scenes, assets, status="AVAILABLE", budget=True):
    return first_shot_readiness(
        scenes=scenes, assets=assets,
        provider_status=SimpleNamespace(status=status),
        budget_confirmed=budget, media_resolver=lambda url: url,
    )


def test_ready_requires_matching_available_image_and_approval(tmp_path):
    picture = tmp_path / "first-scene.png"
    picture.write_bytes(b"saved-image-fixture")
    state = _run(scenes=[_scene()], assets=[_image(picture)])
    assert state["status"] == "READY_TO_REQUEST"
    assert state["target_seconds"] == 5
    assert state["reference_image_asset_id"] == "img-1"
    assert state["blockers"] == []
    assert state["generation_submitted"] is False
    assert state["provider_charge_incurred"] is False


def test_missing_scene_and_provider_and_budget_fail_closed():
    state = _run(scenes=[], assets=[], status="DISABLED", budget=False)
    assert state["status"] == "BLOCKED"
    assert set(state["blockers"]) == {
        "STORYBOARD_REQUIRED",
        "VIDEO_PROVIDER_NOT_AVAILABLE",
        "BUDGET_CONFIRMATION_REQUIRED",
        "FIRST_SCENE_REFERENCE_IMAGE_REQUIRED",
    }


def test_missing_reference_or_wrong_scene_never_passes(tmp_path):
    image = tmp_path / "image.png"
    image.write_bytes(b"fixture")
    wrong = _run(scenes=[_scene(2)], assets=[_image(image, scene_index=1)])
    missing = _run(scenes=[_scene(1)], assets=[_image(tmp_path / "missing.png")])
    for report in (wrong, missing):
        assert "FIRST_SCENE_REFERENCE_IMAGE_REQUIRED" in report["blockers"]
        assert report["status"] == "BLOCKED"


def test_missing_prompt_blocks_generation(tmp_path):
    image = tmp_path / "image.png"
    image.write_bytes(b"fixture")
    state = _run(scenes=[_scene(visual_prompt="")], assets=[_image(image)])
    assert state["status"] == "BLOCKED"
    assert "FIRST_SCENE_PROMPT_REQUIRED" in state["blockers"]
