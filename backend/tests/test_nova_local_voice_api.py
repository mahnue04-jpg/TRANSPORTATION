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
    path = f"/api/nova/creative/projects/{project}/assets/{asset['id']}/file"
    first = client.get(path)
    assert first.status_code == 200 and first.headers["content-type"].startswith("audio/wav")
    assert hashlib.sha256(first.content).hexdigest() == result["sha256"]
    reopen()
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
