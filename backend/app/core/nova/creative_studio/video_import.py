"""Validate uploaded MP4 bytes locally. Never contacts a generation provider."""
from __future__ import annotations

import json
import math
from pathlib import Path
import subprocess

MAX_VIDEO_BYTES = 128 * 1024 * 1024


def validate_video(path: Path, *, max_duration_seconds: int = 120, allow_silent: bool = False) -> dict:
    # Force the MOV/MP4 demuxer and disallow external references and network input.
    common = ["-protocol_whitelist", "file,pipe", "-enable_drefs", "0",
              "-use_absolute_path", "0", "-f", "mov"]
    try:
        probe = subprocess.run(["ffprobe", "-v", "error", *common, "-i", str(path),
            "-show_streams", "-show_format", "-of", "json"],
            capture_output=True, check=True, timeout=20)
        data = json.loads(probe.stdout)
        streams = data.get("streams", [])
        videos = [s for s in streams if s.get("codec_type") == "video"]
        audios = [s for s in streams if s.get("codec_type") == "audio"]
        if len(videos) != 1 or len(audios) > 1 or (not audios and not allow_silent):
            raise ValueError("MP4 must contain one video track and one audio track.")
        video, audio = videos[0], audios[0] if audios else None
        duration = float(data["format"]["duration"])
        width, height = int(video["width"]), int(video["height"])
        if (not math.isfinite(duration) or not 0 < duration <= max_duration_seconds
                or not 128 <= width <= 4096 or not 128 <= height <= 4096
                or width * height > 8_388_608
                or video.get("codec_name") != "h264" or (audio is not None and audio.get("codec_name") != "aac")):
            raise ValueError("Choose an H.264/AAC MP4 within the configured duration and 4096 pixels per side.")
        subprocess.run(["ffmpeg", "-v", "error", "-xerror", "-err_detect", "explode",
            "-threads", "1", *common, "-i", str(path), "-map", "0:v:0", "-map", "0:a:0?" if allow_silent else "0:a:0",
            "-threads", "1", "-f", "null", "-"], capture_output=True, check=True, timeout=45 if max_duration_seconds <= 120 else 240)
    except (OSError, subprocess.SubprocessError, KeyError, TypeError, ValueError) as exc:
        raise ValueError("Choose a fully playable H.264/AAC MP4 with audio within the permitted duration.") from exc
    return {"duration_seconds": duration, "width": width, "height": height,
            "video_codec": "h264", "audio_codec": "aac" if audio else None, "decode_verified": True}
