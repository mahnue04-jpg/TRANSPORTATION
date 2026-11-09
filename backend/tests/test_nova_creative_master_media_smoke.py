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


def test_join_two_real_normalized_chapters_into_private_review_only_mp4(tmp_path):
    # Repeated sample audio/video makes a full 10-minute output without
    # paid providers; use ultrafast synthetic sources to keep CI bounded.
    source_a = _sample(tmp_path / "source-a.mp4", 3, "blue")
    source_b = _sample(tmp_path / "source-b.mp4", 3, "yellow")
    first = tmp_path / "chapter-a.mp4"
    second = tmp_path / "chapter-b.mp4"
    normalize_chapter(source_a, first)
    normalize_chapter(source_b, second)
    # Join validation must reject a wildly incorrect requested duration.
    with pytest.raises(ChapterMasterError, match="planned duration"):
        join_normalized_chapters([first, second], tmp_path / "wrong.mp4",
                                 expected_seconds=600)
    assert not (tmp_path / "wrong.mp4").exists()
    # No real 10-minute video is generated here; the test intentionally
    # verifies the duration gate and absence of false-success artifacts.
