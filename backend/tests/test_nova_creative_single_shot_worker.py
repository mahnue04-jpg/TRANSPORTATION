"""Worker-side fail-closed checks for one authorized five-second actor render.

All tests are offline; a fake provider throws if a billable generation is called.
"""
from types import SimpleNamespace
from datetime import datetime, timedelta, timezone

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


def test_restart_does_not_resubmit_paid_first_shot(monkeypatch):
    import importlib
    from fastapi import BackgroundTasks

    routes = importlib.import_module("app.core.nova.creative_studio.router")
    routes._scene_workers.clear()
    job = SimpleNamespace(
        id="single-job", kind="first_shot_video", status="RUNNING",
        updated_at=(datetime.now(timezone.utc) - timedelta(minutes=22)).isoformat(),
        result_asset_ids=[],
    )
    updates = []

    class FakeService:
        store = SimpleNamespace(
            list_jobs=lambda project, owner: [job],
            list_assets=lambda project, owner: [],
        )

        def _finish_job(self, row, *, status, message, asset_ids):
            updates.append((status, message))
            row.status = status

    tasks = BackgroundTasks()
    routes._recover_scene_jobs(FakeService(), "owner", "project", tasks)
    assert job.status == "ERROR"
    assert "no automatic retry" in updates[0][1]
    assert tasks.tasks == []


def test_restart_can_recognize_saved_paid_video_without_resubmission():
    import importlib
    from fastapi import BackgroundTasks

    routes = importlib.import_module("app.core.nova.creative_studio.router")
    routes._scene_workers.clear()
    result = SimpleNamespace(id="clip-1", kind="video", status="GENERATED", url="/saved/clip.mp4")
    job = SimpleNamespace(
        id="single-job", kind="first_shot_video", status="RUNNING",
        updated_at=(datetime.now(timezone.utc) - timedelta(minutes=22)).isoformat(),
        result_asset_ids=[result.id],
    )

    class FakeService:
        store = SimpleNamespace(
            list_jobs=lambda project, owner: [job],
            list_assets=lambda project, owner: [result],
        )

        def _finish_job(self, row, *, status, message, asset_ids):
            row.status = status

    tasks = BackgroundTasks()
    routes._recover_scene_jobs(FakeService(), "owner", "project", tasks)
    assert job.status == "GENERATED"
    assert tasks.tasks == []


def test_fresh_job_on_other_process_is_not_marked_failed():
    import importlib
    from fastapi import BackgroundTasks

    routes = importlib.import_module("app.core.nova.creative_studio.router")
    routes._scene_workers.clear()
    job = SimpleNamespace(
        id="single-job", kind="first_shot_video", status="QUEUED",
        updated_at=datetime.now(timezone.utc).isoformat(),
        result_asset_ids=[],
    )
    updated = []
    class FakeService:
        store = SimpleNamespace(
            list_jobs=lambda project, owner: [job],
            list_assets=lambda project, owner: [],
        )
        def _finish_job(self, row, *, status, message, asset_ids):
            updated.append(status)
            row.status = status

    tasks = BackgroundTasks()
    routes._recover_scene_jobs(FakeService(), "owner", "project", tasks)
    assert job.status == "QUEUED"
    assert updated == []
    assert tasks.tasks == []
