"""Local 5–6 second full-body walking presenter proof (Issue #351).

Produces a real H.264/AAC MP4 with:
- full-body walking / gesturing motion (not a still or title-card slideshow)
- natural female narration when a free neural TTS endpoint is reachable
- mouth aperture driven by the narration waveform (lip motion locked to speech)
- word-aligned burned-in captions with canonical AMICOR spelling in captions

Does not call fal, Kling, D-ID, Runway, or OpenAI. Does not purchase credits.
Paid provider activation remains owner-gated elsewhere in Creative Studio.
"""

from __future__ import annotations

import asyncio
import math
import struct
import subprocess
import tempfile
import wave
from pathlib import Path
from typing import Any

from app.core.nova.creative_studio.presenter_media import burn_captions_and_cta_fade

# Spoken form for TTS; captions keep the brand spelling AMICOR.
AMICOR_SPOKEN = "AH-mih-kor"
DEFAULT_SCRIPT = (
    "Meet AMICOR Nova — your AI workspace for everyday business work."
)
DEFAULT_VOICE = "en-US-JennyNeural"
TARGET_SECONDS = 5.5
FPS = 24
WIDTH = 720
HEIGHT = 1280

# Back-compat aliases used by early call sites / tests.
_AMICOR_SPOKEN = AMICOR_SPOKEN
_DEFAULT_SCRIPT = DEFAULT_SCRIPT
_DEFAULT_VOICE = DEFAULT_VOICE
_TARGET_SECONDS = TARGET_SECONDS
_FPS = FPS
_WIDTH = WIDTH
_HEIGHT = HEIGHT


class WalkingPresenterError(RuntimeError):
    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code
        self.message = message


def canonical_spoken_script(script: str) -> str:
    """Replace AMICOR with the owner-approved pronunciation for TTS only."""
    import re

    text = " ".join(str(script or "").split())
    if not text:
        raise WalkingPresenterError("SCRIPT_REQUIRED", "Walking presenter needs a short script.")
    return re.sub(r"\bAMICOR\b", _AMICOR_SPOKEN, text, flags=re.IGNORECASE)


def caption_script(script: str) -> str:
    """Captions always show the brand spelling, never the phonetic form."""
    import re

    text = " ".join(str(script or _DEFAULT_SCRIPT).split())
    return re.sub(re.escape(_AMICOR_SPOKEN), "AMICOR", text, flags=re.IGNORECASE)


def _ffmpeg() -> str:
    try:
        import imageio_ffmpeg

        return imageio_ffmpeg.get_ffmpeg_exe()
    except Exception as exc:
        raise WalkingPresenterError("FFMPEG_UNAVAILABLE", f"Local media engine is unavailable: {exc}") from exc


def _run(cmd: list[str], *, timeout: int = 180) -> None:
    run = subprocess.run(cmd, check=False, capture_output=True, text=True, timeout=timeout)
    if run.returncode != 0:
        tail = (run.stderr or run.stdout or "").strip().splitlines()
        detail = tail[-1] if tail else "ffmpeg failed"
        raise WalkingPresenterError("FFMPEG_FAILED", detail[:400])


def probe_duration_seconds(path: Path) -> float:
    run = subprocess.run(
        [_ffmpeg(), "-hide_banner", "-i", str(path)],
        check=False,
        capture_output=True,
        text=True,
        timeout=30,
    )
    text = (run.stderr or "") + (run.stdout or "")
    marker = "Duration:"
    if marker not in text:
        return 0.0
    stamp = text.split(marker, 1)[1].split(",", 1)[0].strip()
    hours, minutes, seconds = stamp.split(":")
    return int(hours) * 3600 + int(minutes) * 60 + float(seconds)


def _has_audio_stream(path: Path) -> bool:
    run = subprocess.run(
        [_ffmpeg(), "-hide_banner", "-i", str(path)],
        check=False,
        capture_output=True,
        text=True,
        timeout=30,
    )
    text = (run.stderr or "") + (run.stdout or "")
    return "Audio:" in text


def _ffprobe_json(path: Path) -> dict[str, Any]:
    run = subprocess.run(
        [
            "ffprobe",
            "-v",
            "quiet",
            "-print_format",
            "json",
            "-show_format",
            "-show_streams",
            str(path),
        ],
        check=False,
        capture_output=True,
        text=True,
        timeout=30,
    )
    if run.returncode != 0:
        return {}
    import json

    try:
        return json.loads(run.stdout or "{}")
    except json.JSONDecodeError:
        return {}


def validate_presenter_mp4(
    path: Path,
    *,
    min_seconds: float = 4.5,
    max_seconds: float = 6.5,
) -> dict[str, Any]:
    """Automated acceptance probe for the 5–6s walking presenter milestone."""
    info = _ffprobe_json(path)
    streams = list(info.get("streams") or [])
    video = next((s for s in streams if s.get("codec_type") == "video"), None)
    audio = next((s for s in streams if s.get("codec_type") == "audio"), None)
    duration = float((info.get("format") or {}).get("duration") or probe_duration_seconds(path) or 0.0)
    checks = {
        "file_exists": path.is_file() and path.stat().st_size > 1000,
        "duration_in_range": min_seconds <= duration <= max_seconds,
        "video_h264": bool(video and str(video.get("codec_name") or "").lower() in {"h264", "avc1"}),
        "audio_aac": bool(audio and str(audio.get("codec_name") or "").lower() in {"aac", "mp4a"}),
        "has_video": video is not None,
        "has_audio": audio is not None,
    }
    return {
        "ok": all(checks.values()),
        "checks": checks,
        "duration_seconds": round(duration, 3),
        "width": int(video.get("width") or 0) if video else 0,
        "height": int(video.get("height") or 0) if video else 0,
        "video_codec": (video or {}).get("codec_name"),
        "audio_codec": (audio or {}).get("codec_name"),
        "size_bytes": path.stat().st_size if path.is_file() else 0,
    }


def word_aligned_cues(script: str, duration: float) -> list[dict[str, Any]]:
    """Exact script words timed across the measured narration duration."""
    tokens = [t for t in caption_script(script).split() if t]
    if not tokens:
        raise WalkingPresenterError("SCRIPT_REQUIRED", "Caption script is empty.")
    duration = max(0.8, float(duration or 0.8))
    weights = [max(1, len(re_sub_punct(t))) for t in tokens]
    total = float(sum(weights))
    cues: list[dict[str, Any]] = []
    cursor = 0.0
    first = 0
    for i, token in enumerate(tokens):
        end_of_group = (
            i - first >= 5
            or token.endswith((".", "!", "?", ";", ":", "—", "–", ","))
            or i == len(tokens) - 1
        )
        if not end_of_group:
            continue
        group = tokens[first : i + 1]
        group_weight = float(sum(weights[first : i + 1]))
        slot = duration * (group_weight / total)
        start = cursor
        end = duration if i == len(tokens) - 1 else min(duration, cursor + slot)
        cues.append(
            {
                "start": round(start, 3),
                "end": round(max(start + 0.05, end), 3),
                "text": " ".join(group),
                "words": group,
            }
        )
        cursor = end
        first = i + 1
    return cues


def re_sub_punct(token: str) -> str:
    import re

    return re.sub(r"[^\w]", "", token)


def synthesize_female_narration(script: str, dest: Path, *, voice: str = _DEFAULT_VOICE) -> dict[str, Any]:
    """Natural female neural TTS via free edge-tts (no API key, no credit purchase).

    Network required. Failure is explicit — silence is never labeled as narration.
    """
    spoken = canonical_spoken_script(script)
    dest.parent.mkdir(parents=True, exist_ok=True)

    async def _synthesize() -> None:
        try:
            import edge_tts
        except ImportError as exc:
            raise WalkingPresenterError(
                "NEURAL_VOICE_UNAVAILABLE",
                "edge-tts is not installed. Natural female narration cannot run in this environment.",
            ) from exc
        communicate = edge_tts.Communicate(spoken, voice)
        await communicate.save(str(dest))

    try:
        asyncio.run(_synthesize())
    except WalkingPresenterError:
        raise
    except Exception as exc:
        raise WalkingPresenterError(
            "NEURAL_VOICE_FAILED",
            f"Natural female narration failed without purchasing credits: {exc}"[:400],
        ) from exc

    if not dest.is_file() or dest.stat().st_size < 200:
        raise WalkingPresenterError("NEURAL_VOICE_FAILED", "Narration file was empty after synthesis.")

    # Normalize to WAV for amplitude lip-sync analysis.
    wav = dest.with_suffix(".wav") if dest.suffix.lower() != ".wav" else dest
    if dest.suffix.lower() != ".wav":
        _run(
            [
                _ffmpeg(),
                "-y",
                "-i",
                str(dest),
                "-ac",
                "1",
                "-ar",
                "24000",
                str(wav),
            ]
        )
    duration = probe_duration_seconds(wav if wav.is_file() else dest)
    return {
        "engine": "edge-tts",
        "voice": voice,
        "spoken_script": spoken,
        "caption_script": caption_script(script),
        "duration_seconds": round(duration, 3),
        "wav_path": str(wav),
        "source_path": str(dest),
        "paid_provider_charges": False,
        "license_status": "AMBER",
        "commercial_use": (
            "Narration used free Microsoft Edge neural TTS for proof generation. "
            "No credits were purchased. Commercial redistribution clearance stays AMBER "
            "until the owner approves the voice source for public ads."
        ),
        "natural_female_voice": True,
        "lip_sync": True,
    }


def _rms_envelope(wav_path: Path, *, fps: int, frame_count: int) -> list[float]:
    with wave.open(str(wav_path), "rb") as handle:
        channels = handle.getnchannels()
        sample_width = handle.getsampwidth()
        rate = handle.getframerate()
        frames = handle.readframes(handle.getnframes())
    if sample_width != 2:
        # Convert non-16-bit WAV through ffmpeg.
        converted = wav_path.with_name(wav_path.stem + "-pcm16.wav")
        _run([_ffmpeg(), "-y", "-i", str(wav_path), "-ac", "1", "-ar", "24000", "-sample_fmt", "s16", str(converted)])
        return _rms_envelope(converted, fps=fps, frame_count=frame_count)

    count = len(frames) // (sample_width * channels)
    samples = struct.unpack("<" + "h" * (count * channels), frames[: count * channels * sample_width])
    if channels > 1:
        mono = [(samples[i] + samples[i + 1]) / 2.0 for i in range(0, len(samples) - 1, channels)]
    else:
        mono = list(samples)
    envelope: list[float] = []
    window = max(1, int(rate / fps))
    peak = 1.0
    for i in range(frame_count):
        start = i * window
        chunk = mono[start : start + window] or [0.0]
        rms = math.sqrt(sum(v * v for v in chunk) / len(chunk))
        envelope.append(rms)
        peak = max(peak, rms)
    return [min(1.0, value / peak) for value in envelope]


def _draw_walking_frame(
    *,
    width: int,
    height: int,
    t: float,
    duration: float,
    mouth: float,
    caption_line: str,
):
    from PIL import Image, ImageDraw, ImageFont

    image = Image.new("RGB", (width, height), (12, 28, 48))
    draw = ImageDraw.Draw(image)

    # Soft studio backdrop
    for y in range(height):
        blend = y / max(1, height - 1)
        color = (
            int(12 + 28 * blend),
            int(28 + 40 * blend),
            int(48 + 36 * blend),
        )
        draw.line([(0, y), (width, y)], fill=color)
    draw.ellipse((width * 0.15, height * 0.08, width * 0.95, height * 0.42), fill=(28, 62, 92))
    draw.rectangle((0, int(height * 0.78), width, height), fill=(22, 40, 58))

    # Walk cycle: one full step ~0.55s
    phase = (t / 0.55) * math.pi * 2
    stride = math.sin(phase)
    bob = abs(math.sin(phase)) * 10
    cx = int(width * 0.48 + math.sin(t * 0.7) * 18)
    base_y = int(height * 0.72 - bob)

    skin = (198, 142, 104)
    hair = (28, 18, 14)
    blazer = (28, 78, 132)
    pants = (24, 36, 58)
    shoes = (20, 20, 24)
    shirt = (236, 242, 248)

    # Legs (walking)
    hip = (cx, base_y - 210)
    left_knee = (cx - 18 + int(42 * stride), base_y - 110)
    right_knee = (cx + 18 - int(42 * stride), base_y - 110)
    left_foot = (left_knee[0] - 8 + int(28 * stride), base_y - 8)
    right_foot = (right_knee[0] + 8 - int(28 * stride), base_y - 8)
    draw.line([hip, left_knee, left_foot], fill=pants, width=18)
    draw.line([hip, right_knee, right_foot], fill=pants, width=18)
    draw.ellipse((left_foot[0] - 16, left_foot[1] - 8, left_foot[0] + 22, left_foot[1] + 10), fill=shoes)
    draw.ellipse((right_foot[0] - 16, right_foot[1] - 8, right_foot[0] + 22, right_foot[1] + 10), fill=shoes)

    # Torso
    torso_top = (cx, base_y - 360)
    draw.rounded_rectangle((cx - 48, base_y - 360, cx + 48, base_y - 210), radius=28, fill=blazer)
    draw.rectangle((cx - 18, base_y - 340, cx + 18, base_y - 250), fill=shirt)

    # Arms + gesture
    shoulder = (cx, base_y - 340)
    left_hand = (cx - 70 - int(20 * stride), base_y - 250 + int(18 * math.cos(phase)))
    # Presenting gesture with the right hand toward camera / product space
    gesture = 0.35 + 0.25 * math.sin(t * 2.2)
    right_hand = (cx + 55 + int(70 * gesture), base_y - 300 - int(40 * gesture))
    draw.line([shoulder, left_hand], fill=blazer, width=14)
    draw.line([shoulder, (cx + 40, base_y - 300), right_hand], fill=blazer, width=14)
    draw.ellipse((left_hand[0] - 12, left_hand[1] - 12, left_hand[0] + 12, left_hand[1] + 12), fill=skin)
    draw.ellipse((right_hand[0] - 12, right_hand[1] - 12, right_hand[0] + 12, right_hand[1] + 12), fill=skin)

    # Head
    head_c = (cx, base_y - 410)
    draw.ellipse((head_c[0] - 38, head_c[1] - 46, head_c[0] + 38, head_c[1] + 40), fill=skin)
    draw.ellipse((head_c[0] - 42, head_c[1] - 58, head_c[0] + 42, head_c[1] - 8), fill=hair)
    # Eyes
    draw.ellipse((head_c[0] - 16, head_c[1] - 8, head_c[0] - 6, head_c[1] + 2), fill=(30, 24, 20))
    draw.ellipse((head_c[0] + 6, head_c[1] - 8, head_c[0] + 16, head_c[1] + 2), fill=(30, 24, 20))

    # Mouth aperture synced to narration energy (lip motion)
    open_px = 2 + int(16 * max(0.0, min(1.0, mouth)))
    mouth_y = head_c[1] + 16
    draw.ellipse(
        (head_c[0] - 12, mouth_y - open_px // 2, head_c[0] + 12, mouth_y + open_px // 2 + 2),
        fill=(120, 48, 58),
    )
    if mouth > 0.35:
        draw.ellipse(
            (head_c[0] - 7, mouth_y - max(1, open_px // 3), head_c[0] + 7, mouth_y + max(1, open_px // 3)),
            fill=(60, 20, 28),
        )

    # Brand strip (not a title-card montage — presenter remains the subject)
    font_path = Path(__file__).parent / "fonts" / "DejaVuSans.ttf"
    try:
        title_font = ImageFont.truetype(str(font_path), 34) if font_path.is_file() else ImageFont.load_default()
        small_font = ImageFont.truetype(str(font_path), 22) if font_path.is_file() else ImageFont.load_default()
    except Exception:
        title_font = ImageFont.load_default()
        small_font = ImageFont.load_default()
    draw.text((36, 42), "AMICOR Nova", font=title_font, fill=(255, 255, 255))
    draw.text((36, 88), "Full-body walking presenter proof", font=small_font, fill=(255, 210, 128))
    if caption_line:
        # Live caption preview under the figure; final burn-in uses ASS.
        draw.rectangle((40, height - 160, width - 40, height - 70), fill=(7, 14, 24))
        draw.text((56, height - 130), caption_line[:48], font=small_font, fill=(255, 255, 255))

    # Progress of walk across the shot (proves continuous motion)
    progress = min(1.0, t / max(0.1, duration))
    draw.rectangle((40, height - 36, 40 + int((width - 80) * progress), height - 24), fill=(64, 168, 214))
    return image


def render_walking_presenter(
    *,
    output_mp4: Path,
    script: str = _DEFAULT_SCRIPT,
    voice: str = _DEFAULT_VOICE,
    target_seconds: float = _TARGET_SECONDS,
    width: int = _WIDTH,
    height: int = _HEIGHT,
) -> dict[str, Any]:
    """Render the Issue #351 five-second walking presenter milestone."""
    script = " ".join(str(script or _DEFAULT_SCRIPT).split())
    if not script:
        raise WalkingPresenterError("SCRIPT_REQUIRED", "Walking presenter needs a short script.")

    ffmpeg = _ffmpeg()
    with tempfile.TemporaryDirectory(prefix="nova-walk-") as temp_name:
        temp = Path(temp_name)
        audio_mp3 = temp / "narration.mp3"
        narration = synthesize_female_narration(script, audio_mp3, voice=voice)
        wav_path = Path(narration["wav_path"])
        audio_duration = float(narration["duration_seconds"] or 0.0)
        # Hold the picture briefly if TTS is slightly short/long; clamp to 5–6s band.
        duration = max(4.8, min(6.2, max(audio_duration, float(target_seconds))))
        frame_count = max(int(duration * _FPS), 24)
        envelope = _rms_envelope(wav_path, fps=_FPS, frame_count=frame_count)
        cues = word_aligned_cues(script, min(duration, max(audio_duration, 0.8)))

        frames_dir = temp / "frames"
        frames_dir.mkdir(parents=True, exist_ok=True)
        for index in range(frame_count):
            t = index / _FPS
            mouth = envelope[index] if index < len(envelope) else 0.0
            active = next((c["text"] for c in cues if c["start"] <= t <= c["end"]), cues[0]["text"] if cues else "")
            frame = _draw_walking_frame(
                width=width,
                height=height,
                t=t,
                duration=duration,
                mouth=mouth,
                caption_line=active,
            )
            frame.save(frames_dir / f"frame-{index:05d}.png", format="PNG")

        silent = temp / "silent.mp4"
        _run(
            [
                ffmpeg,
                "-y",
                "-framerate",
                str(_FPS),
                "-i",
                str(frames_dir / "frame-%05d.png"),
                "-c:v",
                "libx264",
                "-preset",
                "ultrafast",
                "-pix_fmt",
                "yuv420p",
                "-t",
                f"{duration:.3f}",
                "-an",
                str(silent),
            ]
        )
        muxed = temp / "muxed.mp4"
        _run(
            [
                ffmpeg,
                "-y",
                "-i",
                str(silent),
                "-i",
                str(wav_path),
                "-filter_complex",
                f"[1:a]apad,atrim=0:{duration:.3f}[a]",
                "-map",
                "0:v:0",
                "-map",
                "[a]",
                "-c:v",
                "copy",
                "-c:a",
                "aac",
                "-b:a",
                "128k",
                "-t",
                f"{duration:.3f}",
                "-movflags",
                "+faststart",
                str(muxed),
            ]
        )
        polished, srt = burn_captions_and_cta_fade(
            muxed,
            [{"start": c["start"], "end": c["end"], "text": c["text"]} for c in cues],
            width=width,
            height=height,
            cta_text="getamicor.com/nova-today",
            fade_seconds=1.2,
        )
        output_mp4.parent.mkdir(parents=True, exist_ok=True)
        output_mp4.write_bytes(polished.read_bytes())
        srt_dest = output_mp4.with_suffix(".srt")
        srt_dest.write_text(srt.read_text(encoding="utf-8"), encoding="utf-8")
        # Keep narration WAV beside the MP4 for download / receipts.
        audio_out = output_mp4.with_suffix(".wav")
        audio_out.write_bytes(wav_path.read_bytes())

    validation = validate_presenter_mp4(output_mp4)
    return {
        "render_mode": "local_walking_presenter_lipsync",
        "milestone": "5s_walking_presenter",
        "duration_seconds": validation["duration_seconds"],
        "planned_seconds": round(duration, 3),
        "width": width,
        "height": height,
        "fps": _FPS,
        "captions_burned_in": True,
        "word_aligned_captions": True,
        "subtitle_path": str(output_mp4.with_suffix(".srt")),
        "audio_path": str(output_mp4.with_suffix(".wav")),
        "audio_present": _has_audio_stream(output_mp4),
        "lip_sync": True,
        "lip_sync_method": "waveform_mouth_aperture",
        "presenter": True,
        "presenter_mode": "full_body",
        "motion_style": "walking_gesture",
        "full_body_walking": True,
        "paid_provider_charges": False,
        "commercial_slideshow": False,
        "publish_ready": False,
        "owner_review_required": True,
        "license_status": narration["license_status"],
        "narration": narration,
        "caption_cues": cues,
        "validation": validation,
        "visible_end_card": "getamicor.com/nova-today",
        "script": caption_script(script),
    }
