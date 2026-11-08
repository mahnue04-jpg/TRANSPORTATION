"""Assemble existing owner-controlled Creative Studio clips into one MP4.

No model calls, provider requests, voice synthesis, publication or charges.
Bounded first stage: 2-10 minutes, 2-16 saved H.264/AAC video assets, <=128MB final.
"""
from __future__ import annotations

import json
import math
from pathlib import Path
import subprocess


class LongFormAssemblyError(ValueError):
    pass


def _inspect(path: Path) -> dict:
    try:
        info = subprocess.run([
            "ffprobe", "-v", "error", "-protocol_whitelist", "file,pipe",
            "-enable_drefs", "0", "-use_absolute_path", "0", "-f", "mov",
            "-i", str(path), "-show_streams", "-show_format", "-of", "json",
        ], capture_output=True, check=True, timeout=25)
        data = json.loads(info.stdout)
        streams = data.get("streams") or []
        videos = [s for s in streams if s.get("codec_type") == "video"]
        audios = [s for s in streams if s.get("codec_type") == "audio"]
        seconds = float(data["format"]["duration"])
        if (len(videos) != 1 or len(audios) != 1 or
                videos[0].get("codec_name") != "h264" or audios[0].get("codec_name") != "aac" or
                not math.isfinite(seconds) or seconds <= 0):
            raise LongFormAssemblyError("All segments must be playable H.264/AAC MP4s with audio.")
        return {"duration_seconds": seconds}
    except (OSError, subprocess.SubprocessError, KeyError, TypeError, ValueError) as exc:
        raise LongFormAssemblyError("A saved segment could not be validated as H.264/AAC MP4.") from exc


def assemble_clips(paths: list[Path], target: Path, *, target_seconds: int) -> dict:
    """Re-encode mixed frame sizes and preserve sound of every supplied segment.

    The owner supplies clips already reviewed for rights, narration and captions.
    No synthetic or empty media is substituted on errors.
    """
    if not 120 <= target_seconds <= 600 or not 2 <= len(paths) <= 16:
        raise LongFormAssemblyError("Choose a 2-10 minute plan and 2-16 existing video segments.")
    paths = [Path(p).resolve(strict=True) for p in paths]
    if len(set(paths)) != len(paths):
        raise LongFormAssemblyError("Select unique segments in their intended order.")
    durations = [_inspect(path)["duration_seconds"] for path in paths]
    length = sum(durations)
    if abs(length - target_seconds) > max(5, 0.05 * target_seconds):
        raise LongFormAssemblyError(
            "The selected segments do not match the planned video length. Adjust the plan or segments."
        )
    target = Path(target).resolve()
    if target.suffix.lower() != ".mp4" or target in paths:
        raise LongFormAssemblyError("Invalid final MP4 location.")
    target.parent.mkdir(parents=True, exist_ok=True)
    cmd = ["ffmpeg", "-hide_banner", "-nostdin", "-v", "error", "-y"]
    for path in paths:
        cmd.extend(["-i", str(path)])
    filters = []
    for i in range(len(paths)):
        filters.extend([
            f"[{i}:v:0]fps=24,scale=720:1280:force_original_aspect_ratio=decrease,"
            f"pad=720:1280:(ow-iw)/2:(oh-ih)/2,setsar=1,format=yuv420p[v{i}]",
            f"[{i}:a:0]aresample=44100,aformat=sample_fmts=fltp:channel_layouts=stereo[a{i}]",
        ])
    joined = "".join(f"[v{i}][a{i}]" for i in range(len(paths)))
    cmd += [
        "-filter_complex", ";".join(filters + [joined + f"concat=n={len(paths)}:v=1:a=1[v][a]"]),
        "-map", "[v]", "-map", "[a]", "-c:v", "libx264", "-preset", "veryfast",
        "-crf", "27", "-pix_fmt", "yuv420p", "-c:a", "aac", "-b:a", "96k",
        "-movflags", "+faststart", str(target),
    ]
    try:
        result = subprocess.run(cmd, capture_output=True, check=False, timeout=900)
        if result.returncode != 0:
            raise LongFormAssemblyError("Video assembly failed. Originals are unchanged.")
        if target.stat().st_size > 128 * 1024 * 1024:
            raise LongFormAssemblyError("Final video exceeds the current secure storage limit of 128 MB.")
        measured = _inspect(target)
        if abs(measured["duration_seconds"] - target_seconds) > max(5, 0.05 * target_seconds):
            raise LongFormAssemblyError("Final MP4 duration did not match the approved plan.")
        return {"duration_seconds": measured["duration_seconds"], "segment_count": len(paths)}
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise LongFormAssemblyError("Video assembly interrupted or timed out. Originals remain saved.") from exc
    finally:
        if target.exists() and (not target.stat().st_size or target.stat().st_size > 128 * 1024 * 1024):
            target.unlink()
