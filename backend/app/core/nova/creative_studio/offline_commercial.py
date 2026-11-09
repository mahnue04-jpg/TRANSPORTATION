"""Offline 30-second promotional montage. No paid provider calls.

This is a locally drawn title-card montage with local narration and burned
captions. It is not a lip-synced presenter and it is not a publish approval.
"""

from __future__ import annotations

import shutil
import subprocess
import tempfile
from pathlib import Path
from typing import Any

from app.core.nova.creative_studio.presenter_media import burn_captions_and_cta_fade, even_spaced_cues

_FONT = Path(__file__).parent / "fonts" / "DejaVuSans.ttf"
_COLORS = {
    "Hook": (11, 42, 74),
    "Problem": (74, 32, 24),
    "Capabilities": (18, 58, 52),
    "Process": (28, 36, 72),
    "Progress": (22, 58, 36),
    "CTA": (8, 24, 48),
}


class OfflineCommercialError(RuntimeError):
    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code
        self.message = message


def _ffmpeg() -> str:
    try:
        import imageio_ffmpeg

        return imageio_ffmpeg.get_ffmpeg_exe()
    except Exception as exc:
        raise OfflineCommercialError("FFMPEG_UNAVAILABLE", f"Local media engine is unavailable: {exc}") from exc


def _run(cmd: list[str], *, timeout: int = 180) -> None:
    run = subprocess.run(cmd, check=False, capture_output=True, text=True, timeout=timeout)
    if run.returncode != 0:
        tail = (run.stderr or run.stdout or "").strip().splitlines()
        detail = tail[-1] if tail else "ffmpeg failed"
        raise OfflineCommercialError("FFMPEG_FAILED", detail[:400])


def draw_title_card(scene: dict[str, Any], dest: Path, *, width: int = 540, height: int = 960) -> None:
    """No-cost illustrated scene card. Narration belongs in audio/captions, not a wall of text."""
    from PIL import Image, ImageDraw, ImageFont
    heading = str(scene.get("heading") or "Hook").strip()
    color = _COLORS.get(heading, (11, 42, 74))
    selected_image = scene.get("visual_image_path")
    if selected_image:
        from PIL import ImageOps, UnidentifiedImageError
        try:
            with Image.open(selected_image) as source:
                source.verify()
            with Image.open(selected_image) as source:
                if source.width < 256 or source.height < 256 or source.width * source.height > 20_000_000:
                    raise ValueError("Scene visual dimensions are unsupported")
                image = ImageOps.fit(source.convert("RGB"), (width, height), method=Image.Resampling.LANCZOS)
        except (OSError, ValueError, UnidentifiedImageError, Image.DecompressionBombError) as exc:
            raise OfflineCommercialError("SCENE_VISUAL_INVALID", "The selected scene image cannot be decoded.") from exc
        # Simple original-image preview, with restrained branding overlay.
        from PIL import ImageDraw, ImageFont
        draw = ImageDraw.Draw(image)
        overlay_height = max(96, int(height * 0.13))
        draw.rectangle((0, 0, width, overlay_height), fill=(12, 30, 54))
        label = "Scene preview - owner-provided image"
        font_path = str(_FONT) if _FONT.is_file() else None
        font = ImageFont.truetype(font_path, max(16, width // 22)) if font_path else ImageFont.load_default()
        draw.text((max(12, width // 25), max(12, height // 40)), label, fill=(255, 255, 255), font=font)
        image.save(dest, format="PNG")
        return
    image = Image.new("RGB", (width, height), color)
    draw = ImageDraw.Draw(image)
    font_path = str(_FONT) if _FONT.is_file() else None
    def font(n):
        return ImageFont.truetype(font_path, n) if font_path else ImageFont.load_default()
    scale = min(width / 540, height / 960)
    def rect(box, fill, outline=None, radius=0, stroke=2):
        coords = tuple(round(v * scale) for v in box)
        if radius:
            draw.rounded_rectangle(coords, radius=round(radius * scale), fill=fill, outline=outline, width=max(1, round(stroke * scale)))
        else:
            draw.rectangle(coords, fill=fill, outline=outline, width=max(1, round(stroke * scale)))
    def line(points, color, thickness=5):
        draw.line([(round(x*scale), round(y*scale)) for x,y in points], fill=color, width=max(1,round(thickness*scale)), joint="curve")
    def circle(box, fill):
        draw.ellipse(tuple(round(v*scale) for v in box), fill=fill)
    def text(x,y,value,size=24,fill=(255,255,255)):
        draw.text((round(x*scale),round(y*scale)),value,font=font(max(10,round(size*scale))),fill=fill)

    # Visual system: a phone dashboard, human silhouettes, and task/workflow
    # illustrations. Original local vector artwork; never labeled AI footage.
    rect((0,0,540,960),(12,30,54))
    circle((325,90,650,415),(23,61,94))
    circle((-140,610,205,940),(23,58,79))
    text(35,48,"AMICOR Nova",39)
    text(36,111,heading.upper(),29,(255,210,128))
    rect((30,210,510,735),(235,241,247),radius=30)
    rect((53,236,487,293),(24,56,91),radius=14)
    text(76,249,"Nova  •  Business workspace",18)
    if heading == "Problem":
        for y,label in [(327,"Too many follow-ups"),(410,"Scattered paperwork"),(493,"Missing deadlines")]:
            rect((62,y,477,y+65),(255,234,227),radius=12)
            circle((79,y+19,110,y+50),(194,77,64))
            text(125,y+19,label,20,(71,48,47))
        text(88,620,"Busywork adds up",28,(45,62,82))
    elif heading == "Capabilities":
        for x,y,label in [(66,326,"Research"),(277,326,"Admin"),(66,477,"Follow-ups"),(277,477,"Workflows")]:
            rect((x,y,x+188,y+128),(224,240,238),radius=15)
            circle((x+18,y+16,x+62,y+60),(28,132,119))
            text(x+18,y+78,label,20,(21,70,75))
        text(75,645,"One place to organize",22,(43,62,82))
    elif heading == "Process":
        for y,num,label in [(335,"1","Create a task"),(445,"2","Nova drafts"),(555,"3","You review")]:
            rect((69,y,465,y+85),(222,234,248),radius=15)
            circle((87,y+19,137,y+69),(36,100,163))
            text(103,y+25,num,21)
            text(155,y+25,label,22,(29,62,93))
        text(88,673,"You stay in control",22,(43,62,82))
    elif heading == "Progress":
        for y,label in [(332,"Tasks organized"),(432,"Updates prepared"),(532,"Time to focus")]:
            rect((65,y,474,y+76),(223,243,229),radius=15)
            circle((88,y+22,122,y+56),(37,137,83))
            line([(96,y+38),(104,y+46),(117,y+30)],(255,255,255),3)
            text(141,y+23,label,20,(28,77,56))
    elif heading == "CTA":
        rect((69,334,470,600),(217,240,252),radius=20)
        circle((203,362,336,495),(37,120,165))
        text(160,522,"Explore Nova",30,(22,70,103))
        text(63,655,"getamicor.com",28,(32,66,93))
    else:  # Hook: human entrepreneur next to Nova's task board
        circle((107,332,217,442),(185,115,83))
        rect((91,434,233,613),(45,115,149),radius=42)
        rect((262,348,445,612),(218,238,249),radius=13)
        for y in (381,452,523):
            circle((282,y,308,y+26),(36,145,105))
            rect((318,y+4,427,y+17),(90,134,163),radius=5)
        text(84,650,"Meet your AI workspace",22,(38,66,91))
    text(45,787,"Research  •  Organize  •  Follow up",19)
    text(43,846,"getamicor.com/nova-today",19,(255,211,131))
    image.save(dest, format="PNG")

def _wrap(text: str, width: int) -> list[str]:
    words = text.split()
    lines: list[str] = []
    current: list[str] = []
    for word in words:
        trial = " ".join([*current, word])
        if len(trial) > width and current:
            lines.append(" ".join(current))
            current = [word]
        else:
            current.append(word)
    if current:
        lines.append(" ".join(current))
    return lines or [""]


def synthesize_narration(script: str, dest: Path, *, voice: str = "en-us", speed: int = 148) -> dict[str, Any]:
    """Speak the reviewed script with a local engine. No network and no provider charge."""
    binary = shutil.which("espeak-ng") or shutil.which("espeak")
    if not binary:
        raise OfflineCommercialError(
            "LOCAL_NARRATION_UNAVAILABLE",
            "Offline narration needs espeak-ng on the server. No paid voice provider was called, and silence was not labeled as narration.",
        )
    text = " ".join(str(script or "").split())
    if not text:
        raise OfflineCommercialError("SCRIPT_REQUIRED", "Offline narration needs the storyboard script.")
    if voice not in {"en-us", "en-gb"} or not 110 <= speed <= 185:
        raise OfflineCommercialError("VOICE_SETTINGS_INVALID", "Choose an approved English voice and speaking speed.")
    probe = subprocess.run([binary, "--voices"], check=False, capture_output=True, text=True, timeout=20)
    if probe.returncode != 0 or voice not in (probe.stdout or "").lower():
        raise OfflineCommercialError("VOICE_UNAVAILABLE", "Selected local English voice is not installed; choose another voice.")
    dest.parent.mkdir(parents=True, exist_ok=True)
    run = subprocess.run(
        [binary, "-w", str(dest), "-s", str(speed), "-v", voice, text[:1800]],
        check=False,
        capture_output=True,
        text=True,
        timeout=60,
    )
    if run.returncode != 0 or not dest.is_file() or dest.stat().st_size < 44:
        detail = (run.stderr or run.stdout or "espeak failed").strip()
        raise OfflineCommercialError("LOCAL_NARRATION_FAILED", detail[:400])
    engine = Path(binary).name
    return {
        "engine": engine,
        "voice": voice,
        "speed_wpm": speed,
        "license": "GPL-3.0-or-later",
        "license_status": "AMBER",
        "commercial_use": (
            f"{engine} is GPL-3.0-or-later. This spoken file is for owner review. "
            "Commercial-use clearance stays AMBER until the owner accepts that license for a public ad."
        ),
        "paid_provider_charges": False,
        "lip_sync": False,
    }


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


def _build_scene_narration(
    scenes: list[dict[str, Any]], dest: Path, scratch: Path,
    *, voice: str, speed: int, ffmpeg: str,
) -> tuple[dict[str, Any], list[float]]:
    """Synthesize and pad scene-local narration; never cut off spoken text.

    Each scene audio is measured first. If it cannot fit its approved time,
    rendering stops with an actionable error instead of truncating speech.
    Caption cues can then use the measured speaking window of each scene.
    """
    audio_paths: list[Path] = []
    spoken_seconds: list[float] = []
    narration_info: dict[str, Any] = {}
    for index, scene in enumerate(scenes):
        approved = float(scene["duration_seconds"])
        content = str(scene.get("voiceover_text") or scene.get("subtitle_text") or "").strip()
        if not content:
            raise OfflineCommercialError(
                "SCENE_NARRATION_REQUIRED",
                f"Scene {index + 1} needs narration for scene-aligned audio.",
            )
        audio_path = scratch / f"scene-audio-{index:02d}.wav"
        narration_info = synthesize_narration(
            content, audio_path, voice=voice, speed=speed
        )
        actual = probe_duration_seconds(audio_path)
        if actual <= 0:
            raise OfflineCommercialError(
                "SCENE_AUDIO_INVALID", f"Scene {index + 1} narration could not be measured."
            )
        if actual > approved + 0.05:
            raise OfflineCommercialError(
                "SCENE_NARRATION_TOO_LONG",
                f"Scene {index + 1} narration is {actual:.1f} seconds, "
                f"but its allocated duration is {approved:.1f} seconds. "
                "Shorten dialogue, select a faster voice, or increase the scene duration.",
            )
        audio_paths.append(audio_path)
        spoken_seconds.append(actual)
    if not audio_paths:
        raise OfflineCommercialError("SCRIPT_REQUIRED", "Storyboard narration is empty.")
    cmd = [ffmpeg, "-y", "-hide_banner", "-loglevel", "error"]
    for source in audio_paths:
        cmd.extend(["-i", str(source)])
    filters = []
    for index, scene in enumerate(scenes):
        approved = float(scene["duration_seconds"])
        filters.append(
            f"[{index}:a:0]aresample=44100,"
            f"aformat=sample_fmts=s16:channel_layouts=mono,"
            f"apad,atrim=0:{approved:.3f},asetpts=PTS-STARTPTS[a{index}]"
        )
    joined = "".join(f"[a{i}]" for i in range(len(audio_paths)))
    filters.append(f"{joined}concat=n={len(audio_paths)}:v=0:a=1[out]")
    cmd.extend([
        "-filter_complex", ";".join(filters),
        "-map", "[out]", "-c:a", "pcm_s16le", str(dest),
    ])
    _run(cmd, timeout=180)
    if not dest.is_file() or not dest.stat().st_size:
        raise OfflineCommercialError("SCENE_AUDIO_INVALID", "Combined narration was not saved.")
    return narration_info, spoken_seconds


def render_offline_montage(
    scenes: list[dict[str, Any]],
    *,
    output_mp4: Path,
    audio_wav: Path,
    vertical: bool = True,
    voice: str = "en-us",
    speed: int = 148,
) -> dict[str, Any]:
    """Build one MP4 from storyboard beats. Duration follows the storyboard, not a 5s loop."""
    if not scenes:
        raise OfflineCommercialError("STORYBOARD_REQUIRED", "Generate the storyboard before the offline montage.")
    width, height = (540, 960) if vertical else (960, 540)
    ffmpeg = _ffmpeg()
    script = " ".join(
        str(scene.get("voiceover_text") or scene.get("subtitle_text") or "").strip()
        for scene in scenes
        if str(scene.get("voiceover_text") or scene.get("subtitle_text") or "").strip()
    )
    scene_audio_mode = bool(all(scene.get("caption_by_scene") for scene in scenes))
    planned = 0.0
    with tempfile.TemporaryDirectory(prefix="nova-offline-") as temp_name:
        temp = Path(temp_name)
        if scene_audio_mode:
            narration, spoken_windows = _build_scene_narration(
                scenes, audio_wav, temp, voice=voice, speed=speed, ffmpeg=ffmpeg
            )
        else:
            narration = synthesize_narration(script, audio_wav, voice=voice, speed=speed)
            spoken_windows = []
        clips: list[Path] = []
        for index, scene in enumerate(scenes, start=1):
            seconds = float(scene.get("duration_seconds") or 5)
            seconds = max(2.0, min(seconds, 12.0))
            planned += seconds
            card = temp / f"card-{index}.png"
            clip = temp / f"clip-{index}.mp4"
            draw_title_card(scene, card, width=width, height=height)
            frames = max(int(seconds * 12), 2)
            # Slow horizontal pan. Motion, not a still slideshow.
            pan = (
                f"scale={width + 80}:{height}:force_original_aspect_ratio=increase,"
                f"crop={width}:{height}:x='(in_w-out_w)*t/{seconds:.3f}':y='(in_h-out_h)/2',"
                f"fps=12,format=yuv420p"
            )
            # A fade is a short fade-in from black, NOT an overlapping
            # cross-dissolve. The original sequence and runtime are preserved.
            transition = str(scene.get("transition") or "cut")
            if transition not in {"cut", "fade"}:
                raise OfflineCommercialError("INVALID_TRANSITION", "Only cut and fade-in transitions are supported.")
            if index > 1 and transition == "fade":
                pan += f",fade=t=in:st=0:d={min(0.5, seconds / 4):.3f}"
            _run(
                [
                    ffmpeg, "-y", "-threads", "1", "-loop", "1", "-i", str(card),
                    "-vf", pan, "-frames:v", str(frames), "-an",
                    "-c:v", "libx264", "-preset", "ultrafast", "-pix_fmt", "yuv420p",
                    str(clip),
                ]
            )
            clips.append(clip)
        concat = temp / "clips.txt"
        concat.write_text(
            "\n".join("file '" + str(path).replace("'", "'\\''") + "'" for path in clips) + "\n",
            encoding="utf-8",
        )
        joined = temp / "joined.mp4"
        _run([ffmpeg, "-y", "-f", "concat", "-safe", "0", "-i", str(concat), "-c", "copy", str(joined)])
        muxed = temp / "muxed.mp4"
        _run(
            [
                ffmpeg, "-y", "-i", str(joined), "-i", str(audio_wav),
                "-filter_complex", f"[1:a]apad,atrim=0:{planned:.3f}[a]",
                "-map", "0:v:0", "-map", "[a]",
                "-c:v", "copy", "-c:a", "aac", "-b:a", "96k",
                "-t", f"{planned:.3f}", "-movflags", "+faststart", str(muxed),
            ]
        )
        if all(scene.get("caption_by_scene") for scene in scenes):
            # Approximate, scene-bounded caption timing. This is not
            # word-aligned transcription or verified speech synchronization.
            cues = []
            offset = 0.0
            for index, scene in enumerate(scenes):
                seconds = max(2.0, min(float(scene.get("duration_seconds") or 5), 12.0))
                speech_window = min(seconds, spoken_windows[index]) if scene_audio_mode else seconds
                text = str(scene.get("subtitle_text") or scene.get("voiceover_text") or "").strip()
                manual = scene.get("caption_cues") or []
                if manual:
                    prev_end = 0.0
                    for cue in manual:
                        start = float(cue["start_seconds"])
                        end = float(cue["end_seconds"])
                        caption_text = str(cue["text"]).strip()
                        if (not caption_text or start < prev_end or end <= start
                                or end > speech_window + 0.01):
                            raise OfflineCommercialError(
                                "CAPTION_TIMING_INVALID",
                                "Manual captions must fit inside measured scene speech; review their timing."
                            )
                        cues.append({
                            "start": round(offset + start, 3),
                            "end": round(offset + end, 3),
                            "text": caption_text,
                        })
                        prev_end = end
                elif text:
                    for cue in even_spaced_cues(text, speech_window):
                        cues.append({
                            "start": round(offset + cue["start"], 3),
                            "end": round(offset + cue["end"], 3),
                            "text": cue["text"],
                        })
                offset += seconds
            if not cues:
                raise OfflineCommercialError("SCRIPT_REQUIRED", "Storyboard narration is required for captions.")
        else:
            cues = even_spaced_cues(script or "Visit getamicor.com", planned)
        polished, srt = burn_captions_and_cta_fade(
            muxed,
            cues,
            width=width,
            height=height,
            cta_text="getamicor.com/nova-today",
            fade_seconds=min(2.5, max(1.0, planned / 8)),
        )
        output_mp4.parent.mkdir(parents=True, exist_ok=True)
        output_mp4.write_bytes(polished.read_bytes())
        srt_dest = output_mp4.with_suffix(".srt")
        srt_dest.write_text(srt.read_text(encoding="utf-8"), encoding="utf-8")
    duration = probe_duration_seconds(output_mp4)
    has_audio = _has_audio_stream(output_mp4)
    return {
        "render_mode": "offline_montage_not_lipsync",
        "quality_state": "PREVIEW_ONLY",
        "presenter_used": False,
        "pipeline": "offline_title_card_fallback",
        "commercial_complete": False,
        "duration_seconds": round(duration, 3),
        "planned_seconds": round(planned, 3),
        "width": width,
        "height": height,
        "captions_burned_in": True,
        "captions_scene_bounded": bool(all(scene.get("caption_by_scene") for scene in scenes)),
        "captions_speech_aligned": False,
        "manual_caption_cues_used": any(bool(scene.get("caption_cues")) for scene in scenes),
        "narration_scene_audio_aligned": scene_audio_mode,
        "caption_alignment_mode": "scene_speech_window_estimate" if scene_audio_mode else "global_even_spacing",
        "subtitle_path": str(output_mp4.with_suffix(".srt")),
        "audio_present": has_audio,
        "lip_sync": False,
        "presenter": False,
        "paid_provider_charges": False,
        "commercial_slideshow": False,
        "publish_ready": False,
        "owner_review_required": True,
        "license_status": narration["license_status"],
        "narration": narration,
        "visible_end_card": "getamicor.com/nova-today",
    }


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
