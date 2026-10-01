"""Scene timeout, retry, and real encoder regressions; no paid API calls."""
from __future__ import annotations

import asyncio
import json
import importlib
import threading
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

import pytest
from fastapi import BackgroundTasks, FastAPI, HTTPException
from fastapi.testclient import TestClient

routes = importlib.import_module("app.core.nova.creative_studio.router")
from app.core.nova.creative_studio import service as services
from app.core.nova.creative_studio.providers import _resolve_creative_media_url
from app.core.nova.creative_studio.service import CreativeStudioService
from app.core.nova.creative_studio.store import CreativeStudioStore

OWNER = SimpleNamespace(user_id="owner-a", email="owner@example.invalid")


@pytest.fixture
def setup(monkeypatch):
    routes._scene_workers.clear()
    svc = CreativeStudioService(CreativeStudioStore())
    project = svc.create_project(OWNER.user_id, {"title": "Scene timeout proof", "project_type": "short_video", "platform": "Instagram"})
    svc.generate_storyboard(OWNER.user_id, project["id"])
    session = SimpleNamespace(close=lambda: None, rollback=lambda: None)
    monkeypatch.setattr(routes, "get_service", lambda db: svc)
    monkeypatch.setattr(routes, "SessionLocal", lambda: session)
    return svc, project["id"], session


def enqueue(project, session):
    tasks = BackgroundTasks()
    result = routes.generate_video(project, tasks, OWNER, session)
    return result, tasks


async def test_http_response_is_sent_before_slow_generation_finishes(setup, monkeypatch):
    svc, project, session = setup
    release = threading.Event()
    entered = threading.Event()
    response_sent = asyncio.Event()
    messages = []

    def slow_generation(owner, project_id, *, job):
        entered.set()
        assert release.wait(3), "test did not release background worker"
        svc._finish_job(job, status="GENERATED", message="Done", asset_ids=[])
        return {"provider": {"status": "GENERATED"}}

    monkeypatch.setattr(svc, "request_video_generation", slow_generation)
    app = FastAPI()
    app.include_router(routes.router)
    app.dependency_overrides[routes.require_nova_access] = lambda: None
    app.dependency_overrides[routes.get_current_user_context] = lambda: OWNER
    app.dependency_overrides[routes.get_db] = lambda: session

    async def receive():
        return {"type": "http.request", "body": b"", "more_body": False}

    async def send(message):
        messages.append(message)
        if message["type"] == "http.response.body":
            response_sent.set()

    scope = {"type": "http", "asgi": {"version": "3.0"}, "http_version": "1.1", "method": "POST", "scheme": "http", "path": f"/api/nova/creative/projects/{project}/generate/video", "raw_path": b"/", "query_string": b"", "headers": [], "client": ("127.0.0.1", 123), "server": ("test", 80)}
    task = asyncio.create_task(app(scope, receive, send))
    try:
        await asyncio.wait_for(response_sent.wait(), 1)
        assert not release.is_set()
        body = json.loads(next(m["body"] for m in messages if m["type"] == "http.response.body"))
        assert body["status"] == "PROCESSING"
        assert body["job"]["status"] == "QUEUED"
        assert await asyncio.to_thread(entered.wait, 1)
        assert not task.done()  # worker still busy, HTTP response already sent
    finally:
        release.set()
        await task
    assert svc.store.list_jobs(project, OWNER.user_id)[0].status == "GENERATED"


def test_duplicate_click_and_refresh_reattach_to_same_job(setup):
    svc, project, session = setup
    first, tasks = enqueue(project, session)
    second, duplicate_tasks = enqueue(project, session)
    assert first["job"]["id"] == second["job"]["id"]
    assert second["already_running"]
    assert len(tasks.tasks) == 1
    assert not duplicate_tasks.tasks
    assert svc.get_project(OWNER.user_id, project)["jobs"][0]["id"] == first["job"]["id"]


def test_interrupted_job_can_be_retried(setup):
    svc, project, session = setup
    first, _ = enqueue(project, session)
    routes._scene_workers.clear()  # a restarted process loses worker ownership
    job = svc.store.jobs[first["job"]["id"]]
    job.updated_at = (datetime.now(timezone.utc) - timedelta(minutes=21)).isoformat()
    second, tasks = enqueue(project, session)
    assert second["job"]["id"] != first["job"]["id"]
    assert job.status == "ERROR"
    assert len(tasks.tasks) == 1


def test_restart_reconnects_same_saved_task_once_without_new_artwork(setup, monkeypatch):
    svc, project, session = setup
    first, _ = enqueue(project, session)
    job = svc.store.jobs[first["job"]["id"]]
    asset = svc._save_text_asset(owner_id=OWNER.user_id, project_id=project, kind="video", title="Pending", content="", status="PROCESSING", metadata={"provider_result": {"status": "PROCESSING", "task_id": "saved-task", "brief": {"scene_index": 1}}})
    svc._finish_job(job, status="RUNNING", message="Pending", asset_ids=[asset.id])
    routes._scene_workers.clear()
    tasks = BackgroundTasks()
    detail = routes.get_project(project, tasks, OWNER, session)
    assert detail["jobs"][0]["id"] == job.id
    assert detail["jobs"][0]["status"] == "QUEUED"
    duplicate = BackgroundTasks()
    routes.get_project(project, duplicate, OWNER, session)
    assert len(tasks.tasks) == 1 and not duplicate.tasks
    monkeypatch.setattr(svc, "request_image_generation", lambda *a, **kw: pytest.fail("recovery recreated artwork"))
    calls = []
    def resume(*, brief):
        calls.append(brief)
        assert brief["resume_task_id"] == "saved-task"
        return {"status": "GENERATED", "asset_generated": True, "url": "https://example.invalid/recovered.mp4", "brief": brief}
    monkeypatch.setattr(services, "video_provider", lambda: SimpleNamespace(provider_id="mock", status=lambda: SimpleNamespace(status="AVAILABLE"), generate=resume))
    routes._run_scene_background(OWNER.user_id, project, job.id)
    assert len(calls) == 1 and job.status == "GENERATED"
    assert job.id not in routes._scene_workers


def test_restart_unknown_submission_is_reported_without_automatic_retry(setup):
    svc, project, session = setup
    first, _ = enqueue(project, session)
    routes._scene_workers.clear()
    tasks = BackgroundTasks()
    detail = routes.get_project(project, tasks, OWNER, session)
    job = next(row for row in detail["jobs"] if row["id"] == first["job"]["id"])
    assert job["status"] == "ERROR" and "check provider history" in job["message"]
    assert not tasks.tasks


def test_restart_after_asset_commit_finishes_job_without_next_scene(setup):
    svc, project, session = setup
    first, _ = enqueue(project, session)
    job = svc.store.jobs[first["job"]["id"]]
    asset = svc._save_text_asset(owner_id=OWNER.user_id, project_id=project, kind="video", title="Done", content="", status="GENERATED", url="https://example.invalid/done.mp4")
    job.result_asset_ids = [asset.id]
    routes._scene_workers.clear()
    tasks = BackgroundTasks()
    routes.get_project(project, tasks, OWNER, session)
    assert job.status == "GENERATED" and not tasks.tasks


def test_runway_returns_task_id_before_polling(monkeypatch):
    from app.core.nova.creative_studio import providers
    provider = providers.RunwayVideoProvider()
    monkeypatch.setattr(provider, "status", lambda: SimpleNamespace(status="AVAILABLE"))
    monkeypatch.setattr(provider, "_prompt_image_value", lambda value: "data:image/png;base64,AA==")
    monkeypatch.setattr(provider, "_request_json", lambda *a: pytest.fail("task was polled before ID could be saved"))
    created = []
    def create(**kwargs):
        created.append(kwargs)
        return SimpleNamespace(id="new-task")
    monkeypatch.setattr(providers, "RunwayML", lambda **kw: SimpleNamespace(image_to_video=SimpleNamespace(create=create)))
    result = provider.generate(brief={"prompt_text": "Scene", "persist_task_before_poll": True})
    assert result["task_id"] == "new-task" and result["status"] == "PROCESSING"
    assert len(created) == 1


def test_video_download_uses_bounded_reads_and_removes_partial_file(monkeypatch, tmp_path):
    from app.core.nova.creative_studio import providers
    monkeypatch.setenv("NOVA_CREATIVE_VIDEO_ASSET_DIR", str(tmp_path))
    class Response:
        calls = 0
        def __enter__(self): return self
        def __exit__(self, *args): pass
        def read(self, size):
            assert size == 1024 * 1024
            self.calls += 1
            if self.calls == 1: return b"video-data"
            raise OSError("connection interrupted")
    monkeypatch.setattr(providers.urllib.request, "urlopen", lambda *a, **kw: Response())
    with pytest.raises(RuntimeError, match="could not save"):
        providers.RunwayVideoProvider()._save_remote_video("https://example.invalid/video")
    assert not list(tmp_path.iterdir())


def test_worker_error_is_visible_in_project_and_retryable(setup, monkeypatch):
    svc, project, session = setup
    queued, _ = enqueue(project, session)
    def fail(*args, **kwargs):
        raise RuntimeError("encoder unavailable")
    monkeypatch.setattr(svc, "request_video_generation", fail)
    routes._run_scene_background(OWNER.user_id, project, queued["job"]["id"])
    job = svc.get_project(OWNER.user_id, project)["jobs"][0]
    assert job["status"] == "ERROR"
    assert "encoder unavailable" in job["message"]
    retry, _ = enqueue(project, session)
    assert retry["job"]["id"] != queued["job"]["id"]


def test_project_ownership_and_storyboard_are_checked_before_queue(setup):
    svc, project, session = setup
    with pytest.raises(HTTPException) as exc:
        routes.generate_video(project, BackgroundTasks(), SimpleNamespace(user_id="other", email="other@example.invalid"), session)
    assert exc.value.status_code == 404
    svc.store.delete_scenes(project, OWNER.user_id)
    with pytest.raises(HTTPException) as exc:
        enqueue(project, session)
    assert exc.value.status_code == 422
    assert not [job for job in svc.store.jobs.values() if job.kind == "video"]


def test_pending_task_completes_then_next_scene_advances_without_duplicate_images(setup, monkeypatch, tmp_path):
    svc, project, session = setup
    monkeypatch.setenv("NOVA_CREATIVE_MEDIA_DIR", str(tmp_path))
    source = tmp_path / "source.ppm"
    source.write_bytes(b"P6\n2 2\n255\n" + b"\x00\x60\xff" * 4)
    url = "/media/nova-creative/source.ppm"
    image_calls = []
    video_calls = []
    def image_generate(owner, project_id, *, aspect_ratio, prompt):
        image_calls.append(prompt)
        svc._save_text_asset(owner_id=owner, project_id=project_id, kind="image", title="Source", content=prompt, url=url)
        return {"url": url}
    def video_generate(*, brief):
        video_calls.append(brief.copy())
        if len(video_calls) == 1:
            return {"status": "PROCESSING", "task_id": "task-1", "brief": brief, "asset_generated": False}
        return {"status": "GENERATED", "task_id": "task-1" if brief["scene_index"] == 1 else "task-2", "brief": brief, "asset_generated": True, "url": "https://example.invalid/scene.mp4"}
    monkeypatch.setattr(svc, "request_image_generation", image_generate)
    monkeypatch.setattr(services, "video_provider", lambda: SimpleNamespace(provider_id="mock", status=lambda: SimpleNamespace(status="AVAILABLE"), generate=video_generate))
    queued, _ = enqueue(project, session)
    routes._run_scene_background(OWNER.user_id, project, queued["job"]["id"])
    assert [call["resume_task_id"] for call in video_calls] == [None, "task-1"]
    assert len(image_calls) == 1
    videos = [a for a in svc.store.list_assets(project, OWNER.user_id) if a.kind == "video"]
    assert len(videos) == 1 and videos[0].status == "GENERATED"
    next_result = svc.request_video_generation(OWNER.user_id, project)
    assert next_result["scene_index"] == 2
    assert video_calls[-1]["resume_task_id"] is None


def test_failed_provider_retry_reuses_source_artwork(setup, monkeypatch, tmp_path):
    svc, project, session = setup
    monkeypatch.setenv("NOVA_CREATIVE_MEDIA_DIR", str(tmp_path))
    (tmp_path / "source.ppm").write_bytes(b"P6\n2 2\n255\n" + b"\x00\x60\xff" * 4)
    scene = svc.store.list_scenes(project, OWNER.user_id)[0]
    svc._save_text_asset(owner_id=OWNER.user_id, project_id=project, kind="image", title="Existing source", content=scene.visual_prompt, url="/media/nova-creative/source.ppm")
    monkeypatch.setattr(svc, "request_image_generation", lambda *a, **kw: pytest.fail("retry regenerated source artwork"))
    monkeypatch.setattr(services, "video_provider", lambda: SimpleNamespace(provider_id="mock", status=lambda: SimpleNamespace(status="AVAILABLE"), generate=lambda **kw: {"status": "ERROR", "message": "provider unavailable", "asset_generated": False}))
    for _ in range(2):
        assert svc.request_video_generation(OWNER.user_id, project)["job"]["status"] == "ERROR"
    assert len([a for a in svc.store.list_assets(project, OWNER.user_id) if a.kind == "image"]) == 1


def test_real_ffmpeg_scene_encodes_valid_vertical_mp4(setup, monkeypatch, tmp_path):
    import imageio_ffmpeg
    svc, _, _ = setup
    monkeypatch.setenv("NOVA_CREATIVE_MEDIA_DIR", str(tmp_path))
    (tmp_path / "source.ppm").write_bytes(b"P6\n2 2\n255\n" + b"\x00\x60\xff" * 4)
    result = svc._build_local_scene_motion(source_image_url="/media/nova-creative/source.ppm", platform="Instagram", duration_seconds=2)
    assert result["status"] == "GENERATED", result
    path = _resolve_creative_media_url(result["url"])
    reader = imageio_ffmpeg.read_frames(str(path))
    try:
        metadata = next(reader)
        assert metadata["size"] == (720, 1280)
        assert metadata["duration"] == pytest.approx(2, abs=0.1)
        assert len(next(reader)) == 720 * 1280 * 3
    finally:
        reader.close()


def test_queue_and_completion_persist_across_database_sessions(monkeypatch):
    from app.db.session import SessionLocal, engine
    from app.core.nova.creative_studio.schema_ensure import ensure_nova_creative_schema
    ensure_nova_creative_schema(engine)
    with SessionLocal() as db:
        svc = services.get_service(db)
        project = svc.create_project(OWNER.user_id, {"title": "Persistent job proof", "project_type": "short_video"})
        svc.generate_storyboard(OWNER.user_id, project["id"])
        queued, _ = enqueue(project["id"], db)
    with SessionLocal() as db:
        jobs = services.get_service(db).get_project(OWNER.user_id, project["id"])["jobs"]
        assert next(j for j in jobs if j["id"] == queued["job"]["id"])["status"] == "QUEUED"
    def finish(self, owner, project_id, *, job):
        self._finish_job(job, status="GENERATED", message="Persisted", asset_ids=[])
        return {"provider": {"status": "GENERATED"}}
    monkeypatch.setattr(CreativeStudioService, "request_video_generation", finish)
    routes._run_scene_background(OWNER.user_id, project["id"], queued["job"]["id"])
    with SessionLocal() as db:
        jobs = services.get_service(db).get_project(OWNER.user_id, project["id"])["jobs"]
        job = next(j for j in jobs if j["id"] == queued["job"]["id"])
        assert job["status"] == "GENERATED" and job["message"] == "Persisted"
