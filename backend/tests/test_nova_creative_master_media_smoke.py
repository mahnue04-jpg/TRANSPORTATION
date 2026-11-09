"""FFmpeg-backed, no-provider integration checks for normalized chapter master media.

Synthetic test patterns only. These tests do not use customer media, paid AI,
private network storage, publishing, or a real Studio project.
"""
import shutil
import subprocess
from pathlib import Path

import pytest

from app.core.nova.creative_studio.chapter_master import ChapterMasterError, inspect_chapter_master
from app.core.nova.creative_studio.resumable_master import normalize_chapter, join_normalized_chapters


pytestmark = pytest.mark.skipif(
    not shutil.which("ffmpeg") or not shutil.which("ffprobe"),
    reason="FFmpeg and FFprobe are required for the no-provider media smoke",
)


def _sample(path: Path, duration: int, color: str) -> Path:
    subprocess.run([
        "ffmpeg", "-hide_banner", "-nostdin", "-loglevel", "error", "-y",
        "-f", "lavfi", "-i", f"color=c={color}:s=160x90:r=12:d={duration}",
        "-f", "lavfi", "-i", f"sine=frequency=440:sample_rate=44100:duration={duration}",
        "-c:v", "libx264", "-preset", "ultrafast", "-pix_fmt", "yuv420p",
        "-c:a", "aac", "-b:a", "48k", "-shortest", str(path),
    ], check=True, capture_output=True, timeout=60)
    assert path.stat().st_size > 0
    return path


def test_normalize_preserves_source_and_rejects_same_output(tmp_path):
    original = _sample(tmp_path / "clip-original.mp4", 3, "red")
    before = original.read_bytes()
    with pytest.raises(ChapterMasterError, match="separate MP4"):
        normalize_chapter(original, original)
    assert original.read_bytes() == before

    normalized = tmp_path / "clip-normalized.mp4"
    info = normalize_chapter(original, normalized)
    assert normalized.exists()
    assert info["width"] == 720
    assert info["height"] == 1280
    assert original.read_bytes() == before


def test_join_rejects_duplicate_sources_and_in_place_output(tmp_path):
    first = _sample(tmp_path / "clip-1.mp4", 2, "blue")
    second = _sample(tmp_path / "clip-2.mp4", 2, "green")
    with pytest.raises(ChapterMasterError, match="distinct"):
        join_normalized_chapters([first, first], tmp_path / "master.mp4",
                                 expected_seconds=600)
    with pytest.raises(ChapterMasterError, match="distinct"):
        join_normalized_chapters([first, second], first,
                                 expected_seconds=600)


def _repeat_normalized_clip(source: Path, output: Path, count: int = 100) -> Path:
    """Use lossless stream copying to create real 5-minute chapter fixtures."""
    manifest = output.with_suffix(".concat.txt")
    # Paths are inside pytest's isolated scratch directory.
    manifest.write_text("".join(
        f"file '{source.resolve()}'\\n" for _ in range(count)
    ), encoding="utf-8")
    try:
        subprocess.run([
            "ffmpeg", "-hide_banner", "-nostdin", "-loglevel", "error", "-y",
            "-f", "concat", "-safe", "0", "-i", str(manifest),
            "-map", "0:v:0", "-map", "0:a:0",
            "-c", "copy", "-movflags", "+faststart", str(output),
        ], check=True, capture_output=True, timeout=120)
    finally:
        manifest.unlink(missing_ok=True)
    assert output.stat().st_size > 0
    return output


def test_join_two_real_five_minute_chapters_into_ten_minute_master(tmp_path):
    """Actual 10m H.264/AAC MP4, without provider billing or customer media."""
    source_a = _sample(tmp_path / "source-a.mp4", 3, "blue")
    source_b = _sample(tmp_path / "source-b.mp4", 3, "yellow")
    normalized_a = tmp_path / "normalized-a.mp4"
    normalized_b = tmp_path / "normalized-b.mp4"
    normalize_chapter(source_a, normalized_a)
    normalize_chapter(source_b, normalized_b)
    chapter_a = _repeat_normalized_clip(normalized_a, tmp_path / "chapter-a.mp4")
    chapter_b = _repeat_normalized_clip(normalized_b, tmp_path / "chapter-b.mp4")
    before_a = chapter_a.stat().st_size
    before_b = chapter_b.stat().st_size
    output = tmp_path / "assembled-master.mp4"
    result = join_normalized_chapters([chapter_a, chapter_b], output,
                                      expected_seconds=600)
    assert result["width"] == 720
    assert result["height"] == 1280
    assert result["audio_present"] is True
    assert output.stat().st_size > 0
    measured = inspect_chapter_master(output)
    assert abs(measured["duration_seconds"] - 600) <= 12
    assert measured["audio_present"] is True
    assert chapter_a.stat().st_size == before_a
    assert chapter_b.stat().st_size == before_b
    assert source_a.exists() and source_b.exists()
    assert not output.with_suffix(".concat.txt").exists()
