"""Actual Studio routes, SQLite persistence and local worker boundary.

The worker writes a small PCM fixture; real model execution is tested separately.
Identity is substituted at the auth dependency, while project/file isolation is real.
"""
from datetime import datetime, timedelta, timezone
import hashlib
import importlib
from pathlib import Path
import wave

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.auth import UserContext, get_current_user_context
from app.core.nova.creative_studio import db_models, local_voice_provider
from app.core.nova.creative_studio.router import router
from app.core.nova.creative_studio.service import CreativeStudioService
from app.core.nova.creative_studio.store import DbCreativeStudioStore
from app.core.nova.router import require_nova_access
from app.db.session import get_db


@pytest.fixture
def studio(tmp_path, monkeypatch):
    media = tmp_path / "media"
    monkeypatch.setenv("NOVA_CREATIVE_MEDIA_DIR", str(media))
    monkeypatch.setenv("NOVA_CREATIVE_MEDIA_PUBLIC_PREFIX", "/media/nova-creative")
    monkeypatch.setenv("NOVA_CREATIVE_VOICE_PROVIDER", "nova_local")
    monkeypatch.setenv("NOVA_LOCAL_VOICE_ENABLED", "true")
    monkeypatch.setenv("NOVA_LOCAL_VOICE_MODEL_DIR", str(tmp_path / "model"))
    monkeypatch.setattr(local_voice_provider, "check", lambda _: {"ready_to_attempt_offline_inference": True})
    monkeypatch.setattr(local_voice_provider, "_free_memory_bytes", lambda: local_voice_provider.MIN_FREE_BYTES)
    calls = []
    def worker(command, env, log):
        output = Path(command[command.index("--output") + 1])
        text = Path(command[command.index("--script-file") + 1]).read_text()
        calls.append(text)
        assert text == "Business paperwork piling up? Meet AMICOR."
        assert env["HF_HUB_OFFLINE"] == env["TRANSFORMERS_OFFLINE"] == "1"
        with wave.open(str(output), "wb") as wav:
            wav.setnchannels(1); wav.setsampwidth(2); wav.setframerate(24000)
            wav.writeframes(b"\x00\x20\x00\xe0" * 2400)
        import json
        words = [{"word": word, "start": i * .02, "end": (i + 1) * .02}
                 for i, word in enumerate(text.split())]
        Path(command[command.index("--alignment-output") + 1]).write_text(json.dumps({
            "alignment_available": True, "alignment_source": "kokoro_native_token_durations",
            "duration_seconds": .2, "words": words,
            "audio_sha256": hashlib.sha256(output.read_bytes()).hexdigest(),
            "script_sha256": hashlib.sha256(text.encode()).hexdigest(),
        }))
        return 0
    monkeypatch.setattr(local_voice_provider, "_run_worker", worker)

    engine = create_engine("sqlite:///" + str(tmp_path / "studio.db"),
                           connect_args={"check_same_thread": False})
    for name in ("NovaCreativeProject", "NovaCreativeAsset", "NovaCreativeJob",
                 "NovaCreativeBrand", "NovaCreativeBrief", "NovaCreativeScene"):
        getattr(db_models, name).__table__.create(engine)
    sessions = sessionmaker(bind=engine)
    state = {"db": sessions(), "user_id": "owner-a"}
    def service():
        return CreativeStudioService(DbCreativeStudioStore(state["db"]))
    routes = importlib.import_module("app.core.nova.creative_studio.router")
    monkeypatch.setattr(routes, "get_service", lambda db=None: service())
    app = FastAPI()
    app.include_router(router)
    app.dependency_overrides[require_nova_access] = lambda: None
    app.dependency_overrides[get_db] = lambda: None
    app.dependency_overrides[get_current_user_context] = lambda: UserContext(
        user_id=state["user_id"], email=state["user_id"] + "@example.invalid",
        role="staff", organization_id="same-org",
    )
    with TestClient(app) as client:
        response = client.post("/api/nova/creative/projects", json={
            "title": "Local narration test", "project_type": "promo_video",
            "duration_target": 30, "platform": "TikTok",
        })
        assert response.status_code == 200, response.text
        project_id = response.json()["id"]
        service()._save_text_asset(
            owner_id="owner-a", project_id=project_id, kind="script",
            title="Short video full script", content="Business paperwork piling up? Meet AMICOR.",
        )
        def reopen():
            state["db"].close()
            state["db"] = sessions()
        yield client, state, project_id, media, calls, reopen, service
    state["db"].close()
    engine.dispose()


def test_generate_readback_download_and_reopen_preserve_local_audio(studio):
    client, state, project, media, calls, reopen, service = studio
    response = client.post(f"/api/nova/creative/projects/{project}/generate/voice")
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["job"]["provider"] == "nova_local_voice"
    assert body["job"]["status"] == "GENERATED"
    asset = body["asset"]
    assert asset["content"] == "Business paperwork piling up? Meet AMICOR."
    result = asset["metadata"]["provider_result"]
    assert result["voice"] == "af_heart" and result["paid_provider_calls"] is False
    assert result["owner_review_required"] is True and result["publish_ready"] is False
    assert result["caption_alignment"] is True and result["presenter_alignment"] is False
    assert " ".join(c["text"] for c in result["caption_cues"]) == asset["content"]
    path = f"/api/nova/creative/projects/{project}/assets/{asset['id']}/file"
    first = client.get(path)
    assert first.status_code == 200 and first.headers["content-type"].startswith("audio/wav")
    assert hashlib.sha256(first.content).hexdigest() == result["sha256"]
    reopen()
    saved = next(a for a in service().store.list_assets(project, "owner-a") if a.id == asset["id"])
    assert saved.metadata["provider_result"]["caption_cues"] == result["caption_cues"]
    detail = client.get(f"/api/nova/creative/projects/{project}")
    assert detail.status_code == 200, detail.text
    saved = next(row for row in detail.json()["assets"] if row["id"] == asset["id"])
    assert saved["media_available"] is True
    assert client.get(path).content == first.content
    assert len(calls) == 1 and len(list(media.glob("*.wav"))) == 1
    # Same organization does not grant access to another owner's project/file.
    state["user_id"] = "owner-b"
    assert client.get(path).status_code == 404
    assert client.post(f"/api/nova/creative/projects/{project}/generate/voice").status_code == 404
    assert len(calls) == 1


def test_missing_authentication_cannot_generate_or_download(studio):
    client, _, project, _, calls, _, _ = studio
    del client.app.dependency_overrides[get_current_user_context]
    assert client.post(f"/api/nova/creative/projects/{project}/generate/voice").status_code == 401
    assert client.get(f"/api/nova/creative/projects/{project}/assets/missing/file").status_code == 401
    assert calls == []


@pytest.mark.parametrize("captions", [True, False])
def test_presenter_local_voice_uses_exact_script_captions_and_owner_scope(studio, monkeypatch, captions):
    client, state, project, media, calls, reopen, service = studio
    monkeypatch.setattr(CreativeStudioService, "require_budget_confirmation_for_paid",
                        lambda *_: pytest.fail("local narration must not need a paid quote"))
    payload = {"script": "Business paperwork piling up? Meet AMICOR.",
               "voice": "af_heart", "captions": captions}
    response = client.post(f"/api/nova/creative/projects/{project}/presenter/voice", json=payload)
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["provider"]["presenter_narration_ready"] is True
    assert body["provider"]["presenter_audio_version"] == 2
    assert body["provider"]["voice"] == "af_heart" and len(calls) == 1
    assert " ".join(c["text"] for c in body["provider"]["caption_cues"]) == payload["script"]
    reopen()
    saved = next(a for a in service().store.list_assets(project, "owner-a") if a.id == body["asset"]["id"])
    assert saved.metadata["provider_result"]["presenter_narration_ready"] is True
    state["user_id"] = "owner-b"
    assert client.post(f"/api/nova/creative/projects/{project}/presenter/voice", json=payload).status_code == 404
    assert len(calls) == 1


def test_presenter_local_provider_does_not_substitute_external_voice(studio):
    client, _, project, _, calls, _, _ = studio
    response = client.post(f"/api/nova/creative/projects/{project}/presenter/voice", json={
        "script": "Business paperwork piling up? Meet AMICOR.", "voice": "coral", "captions": True,
    })
    assert response.status_code == 200
    assert response.json()["provider"]["status"] == "CONFIG_REQUIRED"
    assert calls == []


def test_local_presenter_selection_survives_project_reopen(studio):
    client, _, project, _, _, reopen, service = studio
    response = client.patch(f"/api/nova/creative/projects/{project}", json={
        "voice": "af_heart", "captions": False,
    })
    assert response.status_code == 200, response.text
    reopen()
    settings = service().get_project("owner-a", project)["project"]["metadata"]["production_settings"]
    assert settings["voice"] == "af_heart" and settings["captions"] is False


@pytest.mark.parametrize("mode", ["head", "half_body", "full_body", "cloud"])
@pytest.mark.parametrize("captions", [True, False])
def test_local_presenter_requires_prepared_audio_before_any_video_work(studio, monkeypatch, mode, captions):
    client, _, project, _, calls, _, service = studio
    monkeypatch.setattr(CreativeStudioService, "require_budget_confirmation_for_paid", lambda *_: None)
    routes = importlib.import_module("app.core.nova.creative_studio.router")
    def no_provider():
        pytest.fail("Missing prepared Nova Voice narration must stop before any video provider")
    monkeypatch.setattr(routes, "talking_presenter_provider", no_provider)
    monkeypatch.setattr(routes, "video_provider", no_provider)
    # General narration has native cues but has not passed presenter preparation.
    client.post(f"/api/nova/creative/projects/{project}/generate/voice").raise_for_status()
    payload = {"script": "Business paperwork piling up? Meet AMICOR.",
               "voice": "af_heart", "captions": captions}
    endpoint = "cloud-finalize" if mode == "cloud" else "preview"
    if mode != "cloud":
        payload["presenter_mode"] = mode
    response = client.post(f"/api/nova/creative/projects/{project}/presenter/{endpoint}", json=payload)
    assert response.status_code == 422, response.text
    assert "Generate Presenter Voice first" in response.text
    assert len(calls) == 1


@pytest.mark.parametrize("mode", ["head", "full_body", "cloud"])
@pytest.mark.parametrize("captions", [True, False])
def test_local_presenter_passes_exact_prepared_audio_to_video_adapter(studio, monkeypatch, mode, captions):
    from types import SimpleNamespace
    from app.core.nova.creative_studio import fal_cloud, kling, presenter_media, providers
    client, _, project, _, calls, reopen, service = studio
    script = "Business paperwork piling up? Meet AMICOR."
    payload = {"script": script, "voice": "af_heart", "captions": captions}
    audio_response = client.post(f"/api/nova/creative/projects/{project}/presenter/voice", json=payload)
    assert audio_response.status_code == 200, audio_response.text
    audio = audio_response.json()["asset"]
    reopen()
    # A newer different voice must not replace the selected local narration.
    service()._save_text_asset(owner_id="owner-a", project_id=project, kind="audio",
        title="Other voice", content=script, status="GENERATED", url="/media/other.mp3",
        metadata={"provider_result": {"voice": "coral"}})
    service()._save_text_asset(owner_id="owner-a", project_id=project, kind="image",
        title="Presenter", content="Genova presenter v2", status="GENERATED",
        url="/media/presenter.png", metadata={})
    service()._save_text_asset(owner_id="owner-a", project_id=project, kind="presenter_video",
        title="Reviewed motion", content="Existing motion", status="GENERATED", url="/media/motion.mp4",
        metadata={"presenter_mode": "full_body", "motion_style": "friendly_explainer",
                  "output_preset": "16:9", "provider_result": {"provider": "fal_kling_video"}})
    monkeypatch.setattr(CreativeStudioService, "require_budget_confirmation_for_paid", lambda *_: None)
    monkeypatch.setattr(CreativeStudioService, "request_voice_generation",
                        lambda *_a, **_k: pytest.fail("Prepared narration must not regenerate"))
    monkeypatch.setattr(CreativeStudioService, "request_image_generation",
                        lambda *_a, **_k: pytest.fail("Reviewed motion must not generate new artwork"))
    routes = importlib.import_module("app.core.nova.creative_studio.router")
    monkeypatch.setenv("NOVA_TALKING_PRESENTER_PROVIDER", "d-id")
    used = []
    def generated(**kwargs):
        used.append(kwargs)
        assert kwargs["audio_url"] == audio["url"]
        return {"status": "GENERATED", "asset_generated": True, "url": "/media/lipsynced.mp4",
                "provider": "test_adapter", "watermark_free": False}
    monkeypatch.setattr(routes, "talking_presenter_provider", lambda: SimpleNamespace(generate=generated))
    monkeypatch.setattr(routes, "video_provider", lambda: SimpleNamespace(
        provider_id="fal_kling_video", status=lambda: SimpleNamespace(status="AVAILABLE"),
        generate=lambda **_k: pytest.fail("Reviewed motion must not regenerate")))
    monkeypatch.setattr(kling.FalKlingLipSyncProvider, "generate_lipsync", lambda _self, **kw: generated(**kw))
    monkeypatch.setattr(fal_cloud.FalCloudProcessor, "lip_sync", lambda _self, **kw: generated(**kw))
    monkeypatch.setattr(fal_cloud.FalCloudProcessor, "auto_subtitle", lambda _self, **_kw: {
        "status": "GENERATED", "asset_generated": True, "url": "/media/cloud-captioned.mp4"})
    monkeypatch.setattr(providers, "_resolve_creative_media_url", lambda _url: Path("/tmp/lipsynced.mp4"))
    caption_calls = []
    def captioned(_path, cues, **kwargs):
        caption_calls.append(kwargs)
        assert cues == audio["metadata"]["provider_result"]["caption_cues"]
        return Path("/tmp/lipsynced-captioned.mp4"), Path("/tmp/lipsynced.srt")
    monkeypatch.setattr(presenter_media, "caption_presenter", captioned)
    endpoint = "cloud-finalize" if mode == "cloud" else "preview"
    if mode != "cloud":
        payload.update(presenter_mode=mode, output_preset="16:9", motion_style="friendly_explainer")
    response = client.post(f"/api/nova/creative/projects/{project}/presenter/{endpoint}", json=payload)
    assert response.status_code == 200, response.text
    assert response.json()["status"] == "GENERATED"
    assert response.json()["asset"]["metadata"]["source_audio_asset_id"] == audio["id"]
    assert len(used) == len(calls) == 1
    if mode != "cloud":
        assert len(caption_calls) == int(captions)
        if captions:
            assert response.json()["asset"]["metadata"]["captions_burned_in"] is True
            assert response.json()["url"].endswith("lipsynced-captioned.mp4")
            assert caption_calls[0] == ({"output_preset": "16:9"} if mode == "full_body" else {})


def test_external_presenter_voice_retains_paid_budget_guard(studio, monkeypatch):
    client, _, project, _, calls, _, _ = studio
    monkeypatch.setenv("NOVA_CREATIVE_VOICE_PROVIDER", "openai")
    monkeypatch.setenv("NOVA_CREATIVE_VOICE_LIVE_ENABLED", "true")
    from app.core.nova.creative_studio import providers
    monkeypatch.setattr(providers, "get_client", lambda: pytest.fail("paid provider must not run"))
    response = client.post(f"/api/nova/creative/projects/{project}/presenter/voice", json={
        "script": "Business paperwork piling up? Meet AMICOR.", "voice": "coral", "captions": True,
    })
    assert response.status_code == 422
    assert calls == []


def test_real_signed_tokens_enforce_owner_identity_and_session_revocation(studio):
    client, state, project, _, calls, _, _ = studio
    from app.auth import create_access_token
    from app.db.models import User
    User.__table__.create(state["db"].get_bind(), checkfirst=True)
    for user_id in ("owner-a", "owner-b"):
        state["db"].add(User(
            id=user_id, email=user_id + "@example.invalid", hashed_password="unused-test-hash",
            role="staff", session_role="staff", organization_id="same-org",
            is_active=True, auth_version=0,
        ))
    state["db"].commit()
    del client.app.dependency_overrides[get_current_user_context]
    client.app.dependency_overrides[get_db] = lambda: state["db"]
    def headers(user_id):
        return {"Authorization": "Bearer " + create_access_token({
            "sub": user_id, "role": "staff", "auth_version": 0,
        })}
    owner_headers = headers("owner-a")
    response = client.post(f"/api/nova/creative/projects/{project}/generate/voice", headers=owner_headers)
    assert response.status_code == 200, response.text
    asset_id = response.json()["asset"]["id"]
    path = f"/api/nova/creative/projects/{project}/assets/{asset_id}/file"
    assert client.get(path, headers=owner_headers).status_code == 200
    assert client.get(path, headers=headers("owner-b")).status_code == 404
    token = owner_headers["Authorization"].split()[1]
    parts = token.split(".")
    parts[2] = ("A" if parts[2][0] != "A" else "B") + parts[2][1:]
    assert client.get(path, headers={"Authorization": "Bearer " + ".".join(parts)}).status_code == 401
    user = state["db"].get(User, "owner-a")
    user.auth_version = 1
    state["db"].commit()
    assert client.get(path, headers=owner_headers).status_code == 401
    assert len(calls) == 1


def test_external_voice_still_requires_paid_budget_confirmation(studio, monkeypatch):
    client, _, project, _, calls, _, _ = studio
    from app.core.nova.creative_studio import providers
    monkeypatch.setenv("NOVA_CREATIVE_VOICE_PROVIDER", "openai")
    monkeypatch.setenv("NOVA_CREATIVE_VOICE_LIVE_ENABLED", "true")
    monkeypatch.setattr(providers, "get_client", lambda: pytest.fail("paid provider must not run"))
    response = client.post(f"/api/nova/creative/projects/{project}/generate/voice")
    assert response.status_code == 422
    assert response.json()["detail"]["code"] == "BUDGET_CONFIRMATION_REQUIRED"
    assert calls == []


def test_short_drama_budget_guard_remains_even_with_local_voice_selected(studio):
    client, _, project, _, calls, _, service = studio
    service().update_project("owner-a", project, {"project_type": "short_drama"})
    response = client.post(f"/api/nova/creative/projects/{project}/generate/voice")
    assert response.status_code == 422
    assert response.json()["detail"]["code"] == "BUDGET_CONFIRMATION_REQUIRED"
    assert calls == []


def test_failed_local_generation_is_terminal_without_audio_and_does_not_retry(studio, monkeypatch):
    client, _, project, media, _, reopen, _ = studio
    calls = []
    def failed(*args): calls.append(1); return 1
    monkeypatch.setattr(local_voice_provider, "_run_worker", failed)
    response = client.post(f"/api/nova/creative/projects/{project}/generate/voice")
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["job"]["status"] == "ERROR" and body["asset"]["url"] is None
    reopen()
    polled = client.get(f"/api/nova/creative/projects/{project}/jobs/{body['job']['id']}")
    assert polled.status_code == 200 and polled.json()["ready"] is True
    assert len(calls) == 1 and not list(media.glob("*.wav"))


@pytest.mark.parametrize("condition,expected", [("disabled", "DISABLED"), ("missing_model", "CONFIG_REQUIRED")])
def test_unready_local_job_is_terminal_without_polling_forever(studio, monkeypatch, condition, expected):
    client, _, project, media, calls, _, _ = studio
    if condition == "disabled": monkeypatch.setenv("NOVA_LOCAL_VOICE_ENABLED", "false")
    else: monkeypatch.setattr(local_voice_provider, "check", lambda _: {"ready_to_attempt_offline_inference": False})
    response = client.post(f"/api/nova/creative/projects/{project}/generate/voice")
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["job"]["status"] == expected
    polled = client.get(f"/api/nova/creative/projects/{project}/jobs/{body['job']['id']}").json()
    assert polled["ready"] is True and polled["paid_provider_charges"] is False
    assert calls == [] and not list(media.glob("*.wav"))


def test_expired_local_job_recovers_after_restart_without_new_generation(studio):
    client, state, project, _, calls, reopen, service = studio
    job = service()._start_job("owner-a", project, "voice")
    job.provider = "nova_local_voice"
    job.created_at = (datetime.now(timezone.utc) - timedelta(minutes=4)).isoformat()
    service().store.save_job(job)
    reopen()
    path = f"/api/nova/creative/projects/{project}/jobs/{job.id}"
    state["user_id"] = "owner-b"
    assert client.get(path).status_code == 404
    state["user_id"] = "owner-a"
    response = client.get(path)
    assert response.status_code == 200, response.text
    assert response.json()["job"]["status"] == "ERROR" and response.json()["ready"] is True
    assert "interrupted" in response.json()["job"]["message"]
    reopen()
    assert client.get(path).json()["job"]["status"] == "ERROR"
    assert calls == []


@pytest.mark.parametrize("provider,age_minutes", [("nova_local_voice", 0), ("openai_voice", 4)])
def test_active_local_and_other_provider_jobs_are_not_reclassified(studio, provider, age_minutes):
    client, _, project, _, calls, _, service = studio
    job = service()._start_job("owner-a", project, "voice")
    job.provider = provider
    job.created_at = (datetime.now(timezone.utc) - timedelta(minutes=age_minutes)).isoformat()
    service().store.save_job(job)
    response = client.get(f"/api/nova/creative/projects/{project}/jobs/{job.id}")
    assert response.status_code == 200, response.text
    assert response.json()["job"]["status"] == "RUNNING"
    assert response.json()["ready"] is False and calls == []
