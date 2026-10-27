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
