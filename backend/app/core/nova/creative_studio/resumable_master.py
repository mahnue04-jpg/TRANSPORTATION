"""Reusable normalized chapter segments for bounded long-form master exports.

Each normalized segment has H264 720x1280 24fps video and 44.1kHz stereo
AAC audio. The caller persists verified segments to private object storage,
and may supply a previously verified segment after an interrupted export.
No generation providers or social publishing are invoked.
"""
from __future__ import annotations

import math
from pathlib import Path
import subprocess

from app.core.nova.creative_studio.chapter_master import (
    ChapterMasterError, inspect_chapter, inspect_chapter_master,
)


def normalize_chapter(source: Path, output: Path) -> dict:
    measured = inspect_chapter(source)
    output.parent.mkdir(parents=True, exist_ok=True)
    cmd = [
        "ffmpeg", "-hide_banner", "-nostdin", "-v", "error", "-y",
        "-i", str(source), "-map", "0:v:0", "-map", "0:a:0",
        "-vf", "fps=24,scale=720:1280:force_original_aspect_ratio=decrease,"
               "pad=720:1280:(ow-iw)/2:(oh-ih)/2,setsar=1,format=yuv420p",
        "-af", "aresample=44100,aformat=sample_fmts=fltp:channel_layouts=stereo",
        "-c:v", "libx264", "-preset", "veryfast", "-crf", "29",
        "-c:a", "aac", "-b:a", "96k",
        "-pix_fmt", "yuv420p", "-movflags", "+faststart", str(output),
    ]
    try:
        result = subprocess.run(cmd, capture_output=True, timeout=1200)
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise ChapterMasterError("Chapter normalization interrupted.") from exc
    if result.returncode != 0 or not output.is_file():
        raise ChapterMasterError("Chapter normalization failed; source is unchanged.")
    if not 0 < output.stat().st_size <= 128 * 1024 * 1024:
        raise ChapterMasterError("Normalized chapter exceeds the 128 MiB limit.")
    video = inspect_chapter(output)
    if abs(video["duration_seconds"] - measured["duration_seconds"]) > 3:
        raise ChapterMasterError("Normalized chapter duration mismatch.")
    return video


def join_normalized_chapters(paths: list[Path], output: Path, *, expected_seconds: int) -> dict:
    """Stream-copy normalized segments into one MP4; avoid reencoding them."""
    if not 600 <= expected_seconds <= 3600 or not 2 <= len(paths) <= 24:
        raise ChapterMasterError("Final export supports 10–60 minutes and 2–24 segments.")
    specs = [inspect_chapter(path) for path in paths]
    if abs(sum(x["duration_seconds"] for x in specs) - expected_seconds) > max(8, expected_seconds * .02):
        raise ChapterMasterError("Completed segments do not match the planned duration.")
    # All checkpoint segments are produced by normalize_chapter using one
    # canonical encoding profile. The private source hashes are verified by the
    # caller before entering this function.
    for spec in specs:
        if spec["width"] != 720 or spec["height"] != 1280:
            raise ChapterMasterError("A checkpoint segment is not normalized.")
    output.parent.mkdir(parents=True, exist_ok=True)
    manifest = output.with_suffix(".concat.txt")
    # Paths are generated within the caller's isolated temporary directory;
    # use ffmpeg's concat demuxer with only locally generated names.
    manifest.write_text("".join(
        "file '" + str(Path(path).resolve()).replace("'", "'\\''") + "'\n"
        for path in paths
    ), encoding="utf-8")
    try:
        result = subprocess.run([
            "ffmpeg", "-hide_banner", "-nostdin", "-v", "error", "-y",
            "-f", "concat", "-safe", "0", "-i", str(manifest),
            "-map", "0:v:0", "-map", "0:a:0",
            "-c", "copy", "-movflags", "+faststart", str(output),
        ], capture_output=True, timeout=1200)
        if result.returncode != 0 or not output.is_file():
            raise ChapterMasterError("Joining saved chapter checkpoints failed.")
        if not 0 < output.stat().st_size <= 512 * 1024 * 1024:
            raise ChapterMasterError("Joined master exceeds 512 MiB.")
        measured = inspect_chapter_master(output)
        if abs(measured["duration_seconds"] - expected_seconds) > max(8, expected_seconds * .02):
            raise ChapterMasterError("Joined master duration mismatch.")
        return measured
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise ChapterMasterError("Final checkpoint join interrupted.") from exc
    finally:
        manifest.unlink(missing_ok=True)
