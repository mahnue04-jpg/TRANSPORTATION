"""No-provider regression checks for explicit film and original social formats.

These are control-plane checks for FFmpeg command construction and fail-closed
validation, NOT proof of working provider generation, movie rendering or live UI.
"""
from pathlib import Path
from types import SimpleNamespace

import pytest

from app.core.nova.creative_studio import long_form_assembly as assembly


def test_invalid_aspect_fails_before_inspecting_sources(tmp_path):
    with pytest.raises(assembly.LongFormAssemblyError, match="portrait or 16:9"):
        assembly.assemble_clips(
            [tmp_path / "missing1.mp4", tmp_path / "missing2.mp4"],
            tmp_path / "master.mp4", target_seconds=120, aspect_ratio="21:9",
        )


@pytest.mark.parametrize(
    ("aspect_ratio", "expected_scale", "expected_pad", "expected_size"),
    [
        ("9:16", "scale=720:1280:", "pad=720:1280:", (720, 1280)),
        ("16:9", "scale=1280:720:", "pad=1280:720:", (1280, 720)),
    ],
)
def test_assembly_chooses_explicit_canvas_and_keeps_audio(
    tmp_path, monkeypatch, aspect_ratio, expected_scale, expected_pad, expected_size,
):
    inputs = [tmp_path / "first.mp4", tmp_path / "second.mp4"]
    for path in inputs:
        path.write_bytes(b"test-fixture-not-real-video")
    output = tmp_path / "master.mp4"
    monkeypatch.setattr(assembly, "_inspect", lambda path: {"duration_seconds": 60.0})
    calls = []

    def fake_ffmpeg(command, **kwargs):
        calls.append(command)
        output.write_bytes(b"test-fixture-output")
        return SimpleNamespace(returncode=0)

    monkeypatch.setattr(assembly.subprocess, "run", fake_ffmpeg)
    result = assembly.assemble_clips(
        inputs, output, target_seconds=120, aspect_ratio=aspect_ratio,
    )
    assert len(calls) == 1
    command = calls[0]
    filt = command[command.index("-filter_complex") + 1]
    assert filt.count(expected_scale) == 2
    assert filt.count(expected_pad) == 2
    assert "concat=n=2:v=1:a=1" in filt
    assert command[command.index("-map") + 1] == "[v]"
    assert command[command.index("-map", command.index("-map") + 1) + 1] == "[a]"
    assert command[-2:] == ["-movflags", "+faststart", str(output)][-2:] or command[-1] == str(output)
    assert (result["width"], result["height"]) == expected_size
    assert result["aspect_ratio"] == aspect_ratio
    assert result["segment_count"] == 2


def test_default_format_remains_portrait(tmp_path, monkeypatch):
    one, two = tmp_path / "one.mp4", tmp_path / "two.mp4"
    one.write_bytes(b"one")
    two.write_bytes(b"two")
    result = {}
    monkeypatch.setattr(assembly, "_inspect", lambda path: {"duration_seconds": 60.0})

    def fake_ffmpeg(command, **kwargs):
        result["command"] = command
        (tmp_path / "out.mp4").write_bytes(b"mock")
        return SimpleNamespace(returncode=0)

    monkeypatch.setattr(assembly.subprocess, "run", fake_ffmpeg)
    assembly.assemble_clips([one, two], tmp_path / "out.mp4", target_seconds=120)
    filters = result["command"][result["command"].index("-filter_complex") + 1]
    assert "scale=720:1280:" in filters
