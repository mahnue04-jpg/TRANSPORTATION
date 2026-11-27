"""Commercial wording/timing regressions; no network or paid generation."""
from pathlib import Path
import wave

import pytest

from app.core.nova.creative_studio import walking_presenter as media
from app.core.nova.creative_studio.service import CreativeStudioError, CreativeStudioService
from app.core.nova.creative_studio.store import CreativeStudioStore


@pytest.mark.parametrize("script", ["A short reviewed line.", " ".join(["reviewed"] * 120)])
def test_commercial_never_adds_or_removes_reviewed_words(tmp_path, monkeypatch, script):
    captured = {}
    monkeypatch.setattr(media, "_memory_profile", lambda **kw: (180, 320, 12))
    monkeypatch.setattr(media, "_render_walking_core", lambda **kw: captured.update(kw) or {})
    media.render_walking_commercial_30s(output_mp4=tmp_path / "test.mp4", script=script)
    assert captured["script"] == script


@pytest.mark.parametrize("duration,code", [(36.48, "NARRATION_TOO_LONG"), (0, "INVALID_NARRATION"), (float("nan"), "INVALID_NARRATION")])
def test_overlong_or_invalid_narration_stops_before_video_encoding(tmp_path, monkeypatch, duration, code):
    monkeypatch.setattr(media, "_ffmpeg", lambda: "unused-encoder")
    monkeypatch.setattr(media, "_prepare_presenter_plate", lambda *a, **kw: (None, 0.5))
    monkeypatch.setattr(media, "synthesize_female_narration", lambda *a, **kw: {
        "wav_path": str(tmp_path / "test.wav"), "duration_seconds": duration, "license_status": "AMBER"})
    monkeypatch.setattr(media, "_rms_envelope", lambda *a, **kw: pytest.fail("Video preparation started"))
    monkeypatch.setattr(media, "_run", lambda *a, **kw: pytest.fail("Encoder started"))
    output = tmp_path / "test.mp4"
    with pytest.raises(media.WalkingPresenterError) as exc:
        media._render_walking_core(output_mp4=output, script="All reviewed words.", voice="test",
            min_seconds=28, max_seconds=32, target_seconds=30, fps=12, width=180, height=320,
            milestone="30s_walking_commercial", render_mode="test")
    assert exc.value.code == code
    assert not output.exists()


def test_approved_audio_is_measured_without_generating_a_replacement(tmp_path, monkeypatch):
    monkeypatch.setattr(media, "_ffmpeg", lambda: "unused-encoder")
    monkeypatch.setattr(media, "_prepare_presenter_plate", lambda *a, **kw: (None, 0.5))
    monkeypatch.setattr(media, "probe_duration_seconds", lambda p: 36.48)
    monkeypatch.setattr(media, "synthesize_female_narration", lambda *a, **kw: pytest.fail("Approved voice was regenerated"))
    monkeypatch.setattr(media, "_run", lambda *a, **kw: pytest.fail("Encoder started"))
    with pytest.raises(media.WalkingPresenterError) as exc:
        media._render_walking_core(output_mp4=tmp_path / "test.mp4", script="Reviewed words.", voice="test",
            min_seconds=28, max_seconds=32, target_seconds=30, fps=12, width=180, height=320,
            milestone="30s_walking_commercial", render_mode="test", approved_narration_path=tmp_path / "approved.wav")
    assert exc.value.code == "NARRATION_TOO_LONG"


@pytest.mark.parametrize("approved_audio", [False, True])
def test_service_prefers_saved_script_and_reuses_approved_audio(tmp_path, monkeypatch, approved_audio):
    monkeypatch.setenv("NOVA_CREATIVE_MEDIA_DIR", str(tmp_path))
    monkeypatch.setenv("NOVA_CREATIVE_MEDIA_PUBLIC_PREFIX", "/media/nova-creative")
    svc = CreativeStudioService(CreativeStudioStore())
    p = svc.create_project("timing-owner", {"title": "TEST timing", "project_type": "short_video", "duration_target": 30})
    svc.generate_storyboard("timing-owner", p["id"])
    script = "The latest reviewed presenter script."
    svc._save_text_asset(owner_id="timing-owner", project_id=p["id"], kind="presenter_script", title="Saved script", content=script)
    path = tmp_path / "test-approved.wav"
    if approved_audio:
        with wave.open(str(path), "wb") as audio:
            audio.setnchannels(1); audio.setsampwidth(2); audio.setframerate(8000)
            audio.writeframes(b"\0\0" * 8000)
        asset = svc._save_text_asset(owner_id="timing-owner", project_id=p["id"], kind="audio", title="TEST audio", content=script,
            url="/media/nova-creative/test-approved.wav", status="GENERATED")
        svc.set_genova_narration_approval("timing-owner", p["id"], asset.id)
    captured = {}
    def stop_before_render(**kwargs):
        captured.update(kwargs)
        raise media.WalkingPresenterError("TEST_STOP", "Stopped before encoding")
    monkeypatch.setattr(media, "render_walking_commercial_30s", stop_before_render)
    with pytest.raises(CreativeStudioError) as exc:
        svc.render_walking_commercial_30s("timing-owner", p["id"])
    assert exc.value.code == "TEST_STOP"
    assert captured["script"] == script
    assert captured["approved_narration_path"] == (path if approved_audio else None)


def test_thirty_second_approval_rejects_a_thirty_one_second_recording(tmp_path, monkeypatch):
    monkeypatch.setenv("NOVA_CREATIVE_MEDIA_DIR", str(tmp_path))
    monkeypatch.setenv("NOVA_CREATIVE_MEDIA_PUBLIC_PREFIX", "/media/nova-creative")
    svc = CreativeStudioService(CreativeStudioStore())
    p = svc.create_project("timing-owner", {"title": "TEST limit", "project_type": "short_video", "duration_target": 30})
    path = tmp_path / "too-long.wav"
    with wave.open(str(path), "wb") as audio:
        audio.setnchannels(1); audio.setsampwidth(2); audio.setframerate(8000)
        audio.writeframes(b"\0\0" * 8000 * 31)
    asset = svc._save_text_asset(owner_id="timing-owner", project_id=p["id"], kind="audio", title="TEST overrun", content="Test only.",
        url="/media/nova-creative/too-long.wav", status="GENERATED")
    with pytest.raises(CreativeStudioError) as exc:
        svc.set_genova_narration_approval("timing-owner", p["id"], asset.id)
    assert exc.value.code == "INVALID_NARRATION"
