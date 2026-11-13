"""Validate uploaded MP4 bytes locally. Never contacts a generation provider."""
from __future__ import annotations

import json
import hashlib
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
    # Decodable H.264 is not necessarily decodable by a web browser. A
    # common failure is 10-bit/4:2:2/4:4:4 H.264. Report the source properties
    # to the authenticated project owner; do not alter or delete the original.
    pixel_format = str(video.get("pix_fmt") or "").lower()
    profile = str(video.get("profile") or "")
    level = int(video.get("level") or 0)
    browser_warnings = []
    if pixel_format and pixel_format not in {"yuv420p", "yuvj420p"}:
        browser_warnings.append("Video pixel format may be unsupported by Chrome.")
    if profile.lower() in {"high 10", "high 4:2:2", "high 4:4:4 predictive"}:
        browser_warnings.append("Video H.264 profile may be unsupported by Chrome.")
    return {"duration_seconds": duration, "width": width, "height": height,
            "video_codec": "h264", "audio_codec": "aac" if audio else None, "decode_verified": True,
            "video_profile": profile, "video_pixel_format": pixel_format,
            "video_level": level, "browser_compatibility_warnings": browser_warnings}


def inspect_mp4_boxes(path: Path) -> dict:
    """Bounded read-only inspection of MP4 top-level atom boundaries.

    Only headers are read; payloads are skipped by seeking. This is structural
    evidence, not proof that the browser can decode individual frames.
    """
    total = path.stat().st_size
    position = 0
    names = []
    complete = True
    with path.open("rb") as source:
        while position < total and len(names) < 10000:
            source.seek(position)
            header = source.read(8)
            if len(header) != 8:
                complete = False
                break
            size = int.from_bytes(header[:4], "big")
            atom = header[4:8]
            if size == 1:
                extended = source.read(8)
                if len(extended) != 8:
                    complete = False
                    break
                size = int.from_bytes(extended, "big")
                minimum = 16
            elif size == 0:
                size = total - position
                minimum = 8
            else:
                minimum = 8
            if size < minimum or position + size > total:
                complete = False
                break
            if atom in {b"ftyp", b"moov", b"mdat", b"moof", b"sidx"}:
                names.append(atom.decode("ascii"))
            position += size
    if position != total:
        complete = False
    has_moov = "moov" in names
    has_mdat = "mdat" in names
    moov_first = has_moov and has_mdat and names.index("moov") < names.index("mdat")
    return {
        "mp4_structure_complete": complete,
        "mp4_has_ftyp": "ftyp" in names,
        "mp4_has_moov": has_moov,
        "mp4_has_mdat": has_mdat,
        "mp4_faststart": moov_first,
        "mp4_fragmented": "moof" in names,
    }


def inspect_existing_video(path: Path) -> dict:
    """Inspect an existing private local MP4 without modifying it or starting a render.

    The path comes from the owner-authorized Studio asset resolver. Return only
    bounded technical metadata, not paths, filenames, raw tool output or bytes.
    """
    if not path.is_file() or path.stat().st_size <= 0 or path.stat().st_size > MAX_VIDEO_BYTES:
        raise ValueError("Saved MP4 is not available within inspection limits.")
    common = ["-protocol_whitelist", "file,pipe", "-enable_drefs", "0",
              "-use_absolute_path", "0", "-f", "mov"]
    try:
        result = subprocess.run(
            ["ffprobe", "-v", "error", *common, "-i", str(path),
             "-show_streams", "-show_format", "-of", "json"],
            capture_output=True, check=True, timeout=20,
        )
        info = json.loads(result.stdout)
        streams = info.get("streams") or []
        videos = [stream for stream in streams if stream.get("codec_type") == "video"]
        audios = [stream for stream in streams if stream.get("codec_type") == "audio"]
        if len(videos) != 1 or len(audios) > 1:
            raise ValueError("Unexpected MP4 stream layout.")
        video = videos[0]
        audio = audios[0] if audios else None
        duration = float((info.get("format") or {}).get("duration") or 0)
        if not math.isfinite(duration) or not 0 < duration <= 600:
            raise ValueError("Invalid MP4 duration.")
        video_codec = str(video.get("codec_name") or "")
        audio_codec = str(audio.get("codec_name") or "") if audio else None
        profile = str(video.get("profile") or "")[:80]
        pix_fmt = str(video.get("pix_fmt") or "")[:32]
        level = int(video.get("level") or 0)
        boxes = inspect_mp4_boxes(path)
        warnings = []
        if not boxes["mp4_structure_complete"] or not boxes["mp4_has_moov"] or not boxes["mp4_has_mdat"]:
            warnings.append("MP4 container structure is incomplete or missing required atoms.")
        if not boxes["mp4_faststart"]:
            warnings.append("MP4 metadata is not before media data; streaming playback may be less reliable.")
        if video_codec != "h264":
            warnings.append("Video codec is not H.264.")
        if pix_fmt.lower() not in {"yuv420p", "yuvj420p"}:
            warnings.append("Video pixel format may not be supported by Chrome.")
        if profile.lower() in {"high 10", "high 4:2:2", "high 4:4:4 predictive"}:
            warnings.append("Video profile may not be supported by Chrome.")
        if audio_codec not in {None, "aac"}:
            warnings.append("Audio codec is not AAC.")
        # Hash the preserved local file so the browser can verify the bytes
        # received through its authenticated fetch -> Blob playback path.
        digest = hashlib.sha256()
        with path.open("rb") as source:
            for chunk in iter(lambda: source.read(1024 * 1024), b""):
                digest.update(chunk)
        return {
            "source_sha256": digest.hexdigest(),
            "video_codec": video_codec,
            "video_profile": profile,
            "video_pixel_format": pix_fmt,
            "video_level": level,
            "audio_codec": audio_codec,
            "duration_seconds": round(duration, 3),
            "size_bytes": path.stat().st_size,
            **boxes,
            "browser_compatibility_warnings": warnings,
            "read_only": True,
            "browser_playback_verified": False,
        }
    except (OSError, subprocess.SubprocessError, KeyError, TypeError, ValueError, OverflowError) as exc:
        raise ValueError("Saved MP4 cannot be safely inspected.") from exc
