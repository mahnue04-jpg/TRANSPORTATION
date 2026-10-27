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
