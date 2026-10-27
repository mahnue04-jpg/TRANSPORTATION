"""Offline final MP4 assembly for already-saved provider scenes.

No provider requests, payment, external downloads, or automatic publishing.
Call only after owner-scoped scene files have been resolved and verified by
the Creative Studio service. This module deliberately accepts local Paths only.
"""
from __future__ import annotations

import json
import math
import subprocess
from pathlib import Path


class CommercialAssemblyError(ValueError):
    pass


def probe_mp4(path: Path) -> dict:
    if not path.is_file() or path.stat().st_size == 0:
        raise CommercialAssemblyError("missing_video")
    try:
        from app.core.nova.creative_studio.walking_presenter import _ffprobe_json
        info = _ffprobe_json(path)
    except Exception as exc:
        raise CommercialAssemblyError("probe_failed") from exc
    streams = info.get("streams") or []
    if not any(x.get("codec_type") == "video" for x in streams):
        raise CommercialAssemblyError("video_stream_missing")
    if not any(x.get("codec_type") == "audio" for x in streams):
        raise CommercialAssemblyError("audio_stream_missing")
    try:
        duration = float((info.get("format") or {}).get("duration"))
    except (TypeError, ValueError):
        raise CommercialAssemblyError("duration_unavailable") from None
    if not math.isfinite(duration) or duration <= 0:
        raise CommercialAssemblyError("duration_invalid")
    return {"duration_seconds": duration, "has_video": True, "has_audio": True}


def assemble_saved_scenes(scene_paths: list[Path], output: Path) -> dict:
    """Offline composition of six *already saved* 5s audio+video files.

    Re-encode to common H264/AAC profiles for mixed provider clips. Reject
    missing, silent or wrong-duration scenes. Caller must authorize output
    location and publish only after independent owner-scoped asset creation.
    """
    if len(scene_paths) != 6:
        raise CommercialAssemblyError("six_scenes_required")
    inputs = [Path(p).resolve(strict=True) for p in scene_paths]
    if len(set(inputs)) != 6:
        raise CommercialAssemblyError("duplicate_scene")
    checks = [probe_mp4(p) for p in inputs]
    if any(not 4.5 <= c["duration_seconds"] <= 5.5 for c in checks):
        raise CommercialAssemblyError("scene_duration_out_of_range")
    output = Path(output).resolve()
    if output in inputs or output.suffix.lower() != ".mp4":
        raise CommercialAssemblyError("invalid_output_path")
    output.parent.mkdir(parents=True, exist_ok=True)
    staged = output.with_name(output.stem + ".assembling.mp4")
    from app.core.nova.creative_studio.walking_presenter import _ffmpeg
    cmd = [_ffmpeg(), "-hide_banner", "-nostdin", "-y"]
    for path in inputs:
        cmd.extend(["-i", str(path)])
    streams = "".join(
        f"[{i}:v:0]fps=24,scale=1280:720:force_original_aspect_ratio=decrease,"
        f"pad=1280:720:(ow-iw)/2:(oh-ih)/2,setsar=1,format=yuv420p[v{i}];"
        f"[{i}:a:0]aresample=48000,aformat=sample_fmts=fltp:channel_layouts=stereo[a{i}];"
        for i in range(6)
    )
    joined = "".join(f"[v{i}][a{i}]" for i in range(6))
    cmd.extend([
        "-filter_complex", streams + joined + "concat=n=6:v=1:a=1[v][a]",
        "-map", "[v]", "-map", "[a]", "-c:v", "libx264", "-preset", "veryfast",
        "-crf", "23", "-c:a", "aac", "-b:a", "128k", "-movflags", "+faststart",
        str(staged),
    ])
    try:
        run = subprocess.run(cmd, capture_output=True, text=True, timeout=240, check=False)
        if run.returncode != 0:
            raise CommercialAssemblyError("assembly_failed")
        checked = probe_mp4(staged)
        if not 29 <= checked["duration_seconds"] <= 31:
            raise CommercialAssemblyError("final_duration_out_of_range")
        staged.replace(output)
        return {"status": "ASSEMBLED_UNCAPTIONED", "path": str(output),
                "duration_seconds": checked["duration_seconds"],
                "scene_count": 6, "captions_verified": False,
                "owner_scoped_asset_saved": False}
    finally:
        if staged.exists():
            staged.unlink()
