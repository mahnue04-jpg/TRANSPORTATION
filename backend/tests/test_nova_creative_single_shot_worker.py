"""Worker-side fail-closed checks for one authorized five-second actor render.

All tests are offline; a fake provider throws if a billable generation is called.
"""
from types import SimpleNamespace

import pytest

from app.core.nova.creative_studio import service as studio_service


class RecordingStore:
    def __init__(self, image):
        self.image = image
        self.deleted = False

    def list_scenes(self, project_id, owner_id):
        return [SimpleNamespace(index=1, visual_prompt="Two boys repairing a canoe", description="", duration_seconds=5)]

    def list_assets(self, project_id, owner_id):
        return [self.image]

    def delete_failed_video_assets(self, project_id, owner_id):
        self.deleted = True
        raise AssertionError("Controlled shot must not delete existing assets")


class ProviderSpy:
    provider_id = "fal_kling_video"

    def __init__(self, state):
        self.state = state
        self.calls = 0

    def status(self):
        return SimpleNamespace(status=self.state)

    def generate(self, *, brief):
        self.calls += 1
        raise AssertionError("Unapproved provider generation")


@pytest.mark.parametrize(
    ("state", "budget", "reference", "expected"),
    [
        ("DISABLED", True, "image-1", "FIRST_SHOT_REVALIDATION_FAILED"),
        ("AVAILABLE", False, "image-1", "FIRST_SHOT_REVALIDATION_FAILED"),
        ("AVAILABLE", True, "wrong-image", "FIRST_SHOT_REVALIDATION_FAILED"),
    ],
)
def test_controlled_worker_revalidates_before_paid_provider_or_asset_mutation(
    tmp_path, monkeypatch, state, budget, reference, expected,
):
    picture = tmp_path / "reference.jpg"
    picture.write_bytes(b"fixture")
    asset = SimpleNamespace(
        id="image-1", kind="image", status="GENERATED",
        url=str(picture), metadata={"scene_index": 1},
    )
    store = RecordingStore(asset)
    provider = ProviderSpy(state)
    monkeypatch.setattr(studio_service, "video_provider", lambda: provider)
    monkeypatch.setattr(studio_service, "_resolve_creative_media_url", lambda url: picture)
    fake = SimpleNamespace(
        store=store,
        _project_or_404=lambda owner_id, project_id: SimpleNamespace(id=project_id),
        preflight_quote=lambda owner_id, project_id: {"owner_budget_confirmed": budget},
    )
    with pytest.raises(studio_service.CreativeStudioError) as error:
        studio_service.CreativeStudioService.request_video_generation(
            fake, "owner", "project", job=SimpleNamespace(id="job"),
            single_shot_reference_id=reference,
        )
    assert error.value.code == expected
    assert provider.calls == 0
    assert store.deleted is False


def test_controlled_worker_fails_closed_if_provider_switched(tmp_path, monkeypatch):
    provider = ProviderSpy("AVAILABLE")
    provider.provider_id = "runway"
    monkeypatch.setattr(studio_service, "video_provider", lambda: provider)
    fake = SimpleNamespace(
        store=RecordingStore(None),
        _project_or_404=lambda owner_id, project_id: SimpleNamespace(id=project_id),
    )
    with pytest.raises(studio_service.CreativeStudioError) as error:
        studio_service.CreativeStudioService.request_video_generation(
            fake, "owner", "project", job=SimpleNamespace(id="job"),
            single_shot_reference_id="image-1",
        )
    assert error.value.code == "FIRST_SHOT_PROVIDER_CHANGED"
    assert provider.calls == 0
