"""No-cost validation tests for the isolated six-scene final assembly module."""
from pathlib import Path
import pytest
from app.core.nova.creative_studio import provider_commercial_assembly as assembly


def test_requires_six_distinct_local_scene_files(tmp_path):
    with pytest.raises(assembly.CommercialAssemblyError, match="six_scenes_required"):
        assembly.assemble_saved_scenes([], tmp_path / "commercial.mp4")


def test_rejects_duplicate_scene_without_ffmpeg(tmp_path, monkeypatch):
    clip = tmp_path / "clip.mp4"
    clip.write_bytes(b"fake data; validation should reject duplicate paths first")
    monkeypatch.setattr(assembly, "probe_mp4", lambda _: {"duration_seconds": 5, "has_video": True, "has_audio": True})
    with pytest.raises(assembly.CommercialAssemblyError, match="duplicate_scene"):
        assembly.assemble_saved_scenes([clip] * 6, tmp_path / "commercial.mp4")


def test_rejects_out_of_range_source_duration_without_spending(tmp_path, monkeypatch):
    files = []
    for i in range(6):
        p = tmp_path / f"clip-{i}.mp4"
        p.write_bytes(b"test")
        files.append(p)
    monkeypatch.setattr(assembly, "probe_mp4", lambda _: {"duration_seconds": 2.0, "has_video": True, "has_audio": True})
    with pytest.raises(assembly.CommercialAssemblyError, match="scene_duration_out_of_range"):
        assembly.assemble_saved_scenes(files, tmp_path / "commercial.mp4")


def test_six_scenes_assemble_to_validated_mp4_without_provider_calls(tmp_path, monkeypatch):
    """Offline assembly contract: input order, stream mapping, output validation.

    A fake encoder avoids billing and expensive video processing. A separate
    real-FFmpeg integration test is still needed for playback acceptance.
    """
    import subprocess
    from app.core.nova.creative_studio import walking_presenter

    files = []
    for i in range(6):
        path = tmp_path / f"scene-{i}.mp4"
        path.write_bytes(b"synthetic-local-input")
        files.append(path)
    final = tmp_path / "genova-30s.mp4"
    recorded = {}

    def probe(path):
        if path.name.endswith(".assembling.mp4"):
            return {"duration_seconds": 30.0, "has_video": True, "has_audio": True}
        return {"duration_seconds": 5.0, "has_video": True, "has_audio": True}

    def fake_encoder(cmd, **kwargs):
        recorded["cmd"] = cmd
        for path in files:
            assert cmd.count(str(path)) == 1
        assert "concat=n=6:v=1:a=1[v][a]" in cmd
        Path(cmd[-1]).write_bytes(b"synthetic-final-output")
        return subprocess.CompletedProcess(cmd, 0, "", "")

    monkeypatch.setattr(assembly, "probe_mp4", probe)
    monkeypatch.setattr(walking_presenter, "_ffmpeg", lambda: "ffmpeg")
    monkeypatch.setattr(assembly.subprocess, "run", fake_encoder)
    outcome = assembly.assemble_saved_scenes(files, final)
    assert final.read_bytes() == b"synthetic-final-output"
    assert outcome["scene_count"] == 6
    assert outcome["status"] == "ASSEMBLED_UNCAPTIONED"
    assert outcome["captions_verified"] is False
    assert outcome["owner_scoped_asset_saved"] is False
    assert outcome["duration_seconds"] == 30.0


def test_final_duration_check_rejects_incorrect_render(tmp_path, monkeypatch):
    import subprocess
    from app.core.nova.creative_studio import walking_presenter

    files = []
    for i in range(6):
        p = tmp_path / f"scene-{i}.mp4"
        p.write_bytes(b"synthetic-input")
        files.append(p)

    def fake_probe(path):
        return {"duration_seconds": 7.0 if path.name.endswith(".assembling.mp4") else 5.0,
                "has_video": True, "has_audio": True}

    def fake_encoder(cmd, **kwargs):
        Path(cmd[-1]).write_bytes(b"bad-final-output")
        return subprocess.CompletedProcess(cmd, 0, "", "")

    monkeypatch.setattr(assembly, "probe_mp4", fake_probe)
    monkeypatch.setattr(walking_presenter, "_ffmpeg", lambda: "ffmpeg")
    monkeypatch.setattr(assembly.subprocess, "run", fake_encoder)
    output = tmp_path / "invalid.mp4"
    with pytest.raises(assembly.CommercialAssemblyError, match="final_duration_out_of_range"):
        assembly.assemble_saved_scenes(files, output)
    assert not output.exists()
    assert not (tmp_path / "invalid.assembling.mp4").exists()


@pytest.mark.slow
def test_real_ffmpeg_six_scenes_have_audio_and_playable_duration(tmp_path):
    """Use only locally synthesized colors and sine tones, no provider or network."""
    import shutil
    import subprocess
    from app.core.nova.creative_studio.walking_presenter import _ffmpeg

    try:
        ffmpeg = _ffmpeg()
    except Exception:
        pytest.skip("FFmpeg binary is not available")
    if not shutil.which("ffprobe"):
        pytest.skip("ffprobe is not available")
    clips = []
    for i in range(6):
        clip = tmp_path / f"synthetic-{i}.mp4"
        cmd = [
            ffmpeg, "-hide_banner", "-nostdin", "-loglevel", "error", "-y",
            "-f", "lavfi", "-i", f"color=c=blue:s=160x90:r=12:d=5",
            "-f", "lavfi", "-i", f"sine=frequency={400 + 40 * i}:sample_rate=48000:duration=5",
            "-shortest", "-c:v", "libx264", "-threads", "1", "-pix_fmt", "yuv420p",
            "-c:a", "aac", str(clip),
        ]
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=60, check=False)
        if result.returncode != 0:
            pytest.skip("Local FFmpeg cannot encode the synthetic fixtures")
        clips.append(clip)

    output = tmp_path / "finished-30s.mp4"
    result = assembly.assemble_saved_scenes(clips, output)
    measured = assembly.probe_mp4(output)
    assert result["status"] == "ASSEMBLED_UNCAPTIONED"
    assert output.stat().st_size > 1000
    assert 29.0 <= measured["duration_seconds"] <= 31.0
    assert measured["has_audio"] and measured["has_video"]
    assert result["captions_verified"] is False


def test_draft_srt_has_six_five_second_cues(tmp_path):
    lines = [f"Genova scene {i}" for i in range(1, 7)]
    path = assembly.write_six_scene_caption_draft(lines, tmp_path / "draft.srt")
    body = path.read_text(encoding="utf-8")
    assert body.count(" --> ") == 6
    assert "00:00:00,000 --> 00:00:05,000" in body
    assert "00:00:25,000 --> 00:00:30,000" in body
    assert "Genova scene 6" in body


def test_srt_refuses_missing_scene_text(tmp_path):
    with pytest.raises(assembly.CommercialAssemblyError, match="six_caption_lines_required"):
        assembly.write_six_scene_caption_draft(["One"] * 5 + [""], tmp_path / "bad.srt")
