"""Offline chapter-master joining for already completed owner-approved chapters.

This first stage supports 10–30 minutes, with private S3 storage required.
Never calls paid models or publishes media. Existing chapter videos are untouched.
"""
from __future__ import annotations

import json
import math
import subprocess
from pathlib import Path


class ChapterMasterError(ValueError):
    pass


def inspect_chapter(path: Path) -> dict:
    try:
        result = subprocess.run(
            ["ffprobe", "-v", "error", "-protocol_whitelist", "file,pipe",
             "-enable_drefs", "0", "-use_absolute_path", "0", "-f", "mov",
             "-i", str(path), "-show_streams", "-show_format", "-of", "json"],
            check=True, capture_output=True, timeout=40,
        )
        info = json.loads(result.stdout)
        v = [x for x in info.get("streams", []) if x.get("codec_type") == "video"]
        a = [x for x in info.get("streams", []) if x.get("codec_type") == "audio"]
        duration = float(info["format"]["duration"])
        if (len(v) != 1 or len(a) != 1 or v[0].get("codec_name") != "h264"
                or a[0].get("codec_name") != "aac"
                or not math.isfinite(duration) or not 0 < duration <= 610):
            raise ChapterMasterError("Chapter must have H.264 video, AAC audio, and a valid duration.")
        return {"duration_seconds": duration, "width": int(v[0]["width"]),
                "height": int(v[0]["height"])}
    except (OSError, subprocess.SubprocessError, KeyError, ValueError, TypeError) as exc:
        raise ChapterMasterError("A chapter is missing or cannot be validated as MP4.") from exc


def join_chapters(paths: list[Path], output: Path, *, expected_seconds: int) -> dict:
    """Concat-normalize chapter videos into a reviewed master; no source deletion."""
    if not 600 <= expected_seconds <= 1800 or not 2 <= len(paths) <= 12:
        raise ChapterMasterError("The current master export supports 10–30 minutes and 2–12 chapters.")
    sources = [Path(p).resolve(strict=True) for p in paths]
    if len(set(sources)) != len(sources):
        raise ChapterMasterError("Chapter files must be distinct.")
    specs = [inspect_chapter(p) for p in sources]
    if abs(sum(s["duration_seconds"] for s in specs) - expected_seconds) > max(8, expected_seconds * 0.02):
        raise ChapterMasterError("Chapter durations do not match the planned master duration.")
    output = Path(output).resolve()
    if output in sources or output.suffix.lower() != ".mp4":
        raise ChapterMasterError("Invalid output path.")
    output.parent.mkdir(parents=True, exist_ok=True)
    # Normalize each source, not just the container, to avoid mismatched pixel
    # formats, frame rates or audio layouts across provider and user clips.
    cmd = ["ffmpeg", "-hide_banner", "-nostdin", "-v", "error", "-y"]
    for src in sources:
        cmd.extend(["-i", str(src)])
    filters = []
    for i in range(len(sources)):
        filters += [
            f"[{i}:v:0]fps=24,scale=720:1280:force_original_aspect_ratio=decrease,"
            f"pad=720:1280:(ow-iw)/2:(oh-ih)/2,setsar=1,format=yuv420p[v{i}]",
            f"[{i}:a:0]aresample=44100,aformat=sample_fmts=fltp:channel_layouts=stereo[a{i}]",
        ]
    inputs = "".join(f"[v{i}][a{i}]" for i in range(len(sources)))
    cmd += [
        "-filter_complex", ";".join(filters + [inputs + f"concat=n={len(sources)}:v=1:a=1[v][a]"]),
        "-map", "[v]", "-map", "[a]",
        "-c:v", "libx264", "-preset", "veryfast", "-crf", "29",
        "-pix_fmt", "yuv420p", "-c:a", "aac", "-b:a", "96k",
        "-movflags", "+faststart", str(output),
    ]
    try:
        completed = subprocess.run(cmd, capture_output=True, check=False, timeout=3600)
        if completed.returncode:
            raise ChapterMasterError("Master video assembly failed; chapters were preserved.")
        if not output.is_file() or not 0 < output.stat().st_size <= 512 * 1024 * 1024:
            raise ChapterMasterError("Master is missing or exceeds 512 MiB storage limit.")
        result = inspect_chapter_master(output)
        if abs(result["duration_seconds"] - expected_seconds) > max(8, expected_seconds * 0.02):
            raise ChapterMasterError("Final master duration failed verification.")
        return result
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise ChapterMasterError("Master processing timed out or was interrupted.") from exc
    finally:
        # The caller uses an isolated temporary directory; failed partial masters
        # cannot be registered as complete.
        pass


def inspect_chapter_master(path: Path) -> dict:
    # Permit durations longer than the individual chapter bound.
    result = subprocess.run(
        ["ffprobe", "-v", "error", "-i", str(path),
         "-show_streams", "-show_format", "-of", "json"],
        capture_output=True, check=True, timeout=45,
    )
    info = json.loads(result.stdout)
    duration = float(info["format"]["duration"])
    video = [x for x in info.get("streams", []) if x.get("codec_type") == "video"]
    audio = [x for x in info.get("streams", []) if x.get("codec_type") == "audio"]
    if (len(video) != 1 or len(audio) != 1 or
        video[0].get("codec_name") != "h264" or audio[0].get("codec_name") != "aac" or
        not math.isfinite(duration) or duration <= 0):
        raise ChapterMasterError("Master output is not a valid narrated H.264/AAC MP4.")
    return {"duration_seconds": duration, "width": int(video[0]["width"]),
            "height": int(video[0]["height"]), "audio_present": True}
