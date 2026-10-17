"""Assemble the approved 60-second full-body demo from existing media.

The public presenter file is a short silent motion clip. Coral narration and
the reviewed caption cues are separate. This joins them into one saved MP4
without calling a paid provider or replacing the source files.
"""
from __future__ import annotations

import re
import textwrap
from pathlib import Path

from app.core.nova.creative_studio.media_runtime import MIB, run_encoder, serialized_media
from app.core.nova.creative_studio.presenter_media import _time, srt_text

_CUE = re.compile(
    r"\{\s*start:\s*([0-9.]+),\s*end:\s*([0-9.]+),\s*text:\s*\"([^\"]*)\"\s*\}"
)
_DURATION = re.compile(r"Duration:\s*(\d+):(\d+):(\d+(?:\.\d+)?)")
_VIDEO_SIZE = re.compile(r",\s*(\d{2,5})x(\d{2,5})\b")


def demo_cues(js_text: str) -> list[dict]:
    cues = [
        {"start": float(start), "end": float(end), "text": text}
        for start, end, text in _CUE.findall(js_text)
    ]
    if not cues:
        raise RuntimeError("The 60-second demo caption cues are missing.")
    return cues


def webvtt_text(cues: list[dict]) -> str:
    lines = ["WEBVTT", ""]
    for cue in cues:
        lines.append(f"{_time(cue['start']).replace(',', '.')} --> {_time(cue['end']).replace(',', '.')}")
        lines.append(cue["text"])
        lines.append("")
    return "\n".join(lines)


def _probe(path: Path) -> str:
    import imageio_ffmpeg

    result = run_encoder(
        [imageio_ffmpeg.get_ffmpeg_exe(), "-hide_banner", "-i", str(path)],
        timeout=30,
        required_headroom=64 * MIB,
    )
    if "insufficient server memory headroom" in (result.stderr or ""):
        raise RuntimeError(result.stderr)
    return result.stderr or ""


def _duration_seconds(detail: str) -> float:
    match = _DURATION.search(detail)
    if not match:
        raise RuntimeError("Could not read media duration.")
    hours, minutes, seconds = match.groups()
    return int(hours) * 3600 + int(minutes) * 60 + float(seconds)


def _even(value: int) -> int:
    return max(2, value - (value % 2))


@serialized_media
def assemble_full_body_demo(
    presenter: Path,
    narration: Path,
    cues: list[dict],
    output: Path,
) -> dict:
    """Loop the full-body clip under the narration and burn the caption cues.

    The presenter frame is scaled down only. It is not cropped.
    """
    if not cues:
        raise RuntimeError("Timed full-body captions are missing.")
    if not presenter.is_file() or not narration.is_file():
        raise RuntimeError("Full-body presenter video and narration must already exist.")

    presenter_detail = _probe(presenter)
    narration_detail = _probe(narration)
    if not _VIDEO_SIZE.search(presenter_detail):
        raise RuntimeError("The presenter file has no video stream.")
    if "Audio:" not in narration_detail:
        raise RuntimeError("The narration file has no audio stream.")

    duration = _duration_seconds(narration_detail)
    if duration <= 0:
        raise RuntimeError("Narration duration is empty.")
    width, height = (int(item) for item in _VIDEO_SIZE.search(presenter_detail).groups())
    out_w = _even(min(1280, width))
    out_h = _even(round(height * (out_w / width)))
    band = 96
    total_h = out_h + band

    bounded = []
    for cue in cues:
        start = max(0.0, min(duration, float(cue["start"])))
        end = max(start + 0.05, min(duration, float(cue["end"])))
        text = str(cue.get("text") or "").strip()
        if text and start < duration:
            bounded.append({"start": start, "end": end, "text": text})
    if not bounded:
        raise RuntimeError("Timed full-body captions are missing.")

    output.parent.mkdir(parents=True, exist_ok=True)
    srt = output.with_suffix(".srt")
    vtt = output.with_suffix(".vtt")
    ass = output.with_suffix(".ass")
    srt.write_text(srt_text(bounded), encoding="utf-8")
    vtt.write_text(webvtt_text(bounded), encoding="utf-8")

    font_dir = Path(__file__).parent / "fonts"
    if not (font_dir / "DejaVuSans.ttf").is_file():
        raise RuntimeError("Bundled presenter caption font is missing.")
    lines = [
        "[Script Info]",
        f"PlayResX: {out_w}",
        f"PlayResY: {total_h}",
        "[V4+ Styles]",
        "Format: Name, Fontname, Fontsize, PrimaryColour, BackColour, Bold, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding",
        "Style: Default,DejaVu Sans,28,&H00FFFFFF,&H00000000,0,1,1,0,2,24,24,18,1",
        "[Events]",
        "Format: Layer, Start, End, Style, Text",
    ]
    for cue in bounded:
        safe = cue["text"].replace("\\", "＼").replace("{", "｛").replace("}", "｝")
        wrapped = r"\N".join(textwrap.wrap(safe, 42, break_long_words=True, break_on_hyphens=False))
        lines.append(
            f"Dialogue: 0,{_time(cue['start'], True)},{_time(cue['end'], True)},Default,{wrapped}"
        )
    ass.write_text("\n".join(lines), encoding="utf-8")

    escaped_path = str(ass).replace("\\", "\\\\").replace(":", "\\:").replace("'", "\\'")
    escaped_fonts = str(font_dir).replace("\\", "\\\\").replace(":", "\\:").replace("'", "\\'")
    import imageio_ffmpeg

    result = run_encoder(
        [
            imageio_ffmpeg.get_ffmpeg_exe(),
            "-hide_banner",
            "-y",
            "-threads",
            "1",
            "-filter_threads",
            "1",
            "-stream_loop",
            "-1",
            "-i",
            str(presenter),
            "-i",
            str(narration),
            "-t",
            f"{duration:.3f}",
            "-map",
            "0:v:0",
            "-map",
            "1:a:0",
            "-vf",
            (
                f"scale={out_w}:{out_h}:force_original_aspect_ratio=decrease,"
                f"pad={out_w}:{total_h}:(ow-iw)/2:0:color=0x07111f,"
                f"subtitles='{escaped_path}':fontsdir='{escaped_fonts}'"
            ),
            "-c:v",
            "libx264",
            "-preset",
            "ultrafast",
            "-pix_fmt",
            "yuv420p",
            "-crf",
            "28",
            "-c:a",
            "aac",
            "-b:a",
            "128k",
            "-movflags",
            "+faststart",
            str(output),
        ],
        timeout=180,
        required_headroom=192 * MIB,
    )
    ass.unlink(missing_ok=True)
    if result.returncode:
        raise RuntimeError("Full-body demo assembly failed: " + (result.stderr or "")[-600:])
    if not output.is_file():
        raise RuntimeError("Full-body demo assembly did not save the video.")
    return {
        "url": output.name,
        "srt": srt.name,
        "vtt": vtt.name,
        "duration_seconds": duration,
        "width": out_w,
        "height": total_h,
        "presenter_mode": "full_body",
        "captions_burned_in": True,
        "source_presenter": presenter.name,
        "source_narration": narration.name,
    }
