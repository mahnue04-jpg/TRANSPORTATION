"""The saved Studio demo must stay an honest fail until a real talking presenter exists."""
from __future__ import annotations

import json
import subprocess
from pathlib import Path

import imageio_ffmpeg

ROOT = Path(__file__).resolve().parents[1]
DEMO = ROOT / "static" / "nova-one-minute-demo"
VIDEO = DEMO / "amicor-nova-60-second-full-body.mp4"


def _ffmpeg() -> str:
    return imageio_ffmpeg.get_ffmpeg_exe()


def _probe() -> str:
    result = subprocess.run(
        [_ffmpeg(), "-hide_banner", "-i", str(VIDEO)],
        capture_output=True,
        text=True,
        check=False,
    )
    return result.stderr


def _gray_frame(at: float) -> bytes:
    result = subprocess.run(
        [
            _ffmpeg(),
            "-hide_banner",
            "-loglevel",
            "error",
            "-ss",
            f"{at:.3f}",
            "-i",
            str(VIDEO),
            "-frames:v",
            "1",
            "-vf",
            "crop=1280:852:0:0,scale=80:53,format=gray",
            "-f",
            "rawvideo",
            "-",
        ],
        capture_output=True,
        check=False,
    )
    assert result.returncode == 0 and result.stdout, result.stderr
    return result.stdout


def _mean_abs(left: bytes, right: bytes) -> float:
    assert len(left) == len(right) and left
    return sum(abs(a - b) for a, b in zip(left, right)) / len(left)


def test_saved_demo_stays_an_explicit_acceptance_fail() -> None:
    manifest = json.loads((DEMO / "acceptance.json").read_text(encoding="utf-8"))
    html = (DEMO / "index.html").read_text(encoding="utf-8")
    detail = _probe()

    assert manifest["assessment_ready"] is False
    assert manifest["paid_provider_called_this_pass"] is False
    assert manifest["originals_replaced"] is False
    assert manifest["licensing"]["commercial_use_cleared"] is False
    assert manifest["measured"]["vertical_9_16"] is False
    assert manifest["measured"]["width"] == 1280
    assert manifest["measured"]["height"] == 948
    assert "not_lip_synced" in manifest["blocking_gaps"]
    assert "not_sitting" in manifest["blocking_gaps"]
    assert "not_vertical_9_16" in manifest["blocking_gaps"]

    assert "Duration: 00:00:59.88" in detail
    assert "1280x948" in detail
    assert "Video: h264" in detail
    assert "Audio: aac" in detail
    assert "24000 Hz, mono" in detail
    assert "does not claim lip-sync" in html
    assert 'id="release-acceptance"' in html
    assert "not assessment-ready" in html
    assert "/media/nova-creative/nova-da25e10f80924d6ca99e62a04c9eb346.mp4" in html
    assert "/media/nova-creative/nova-bb9d59169aef4733ba8c07d1b0d418f6.mp3" in html
    assert (DEMO / "amicor-nova-60-second-full-body.vtt").is_file()
    assert (DEMO / "amicor-nova-60-second-full-body.srt").is_file()

    looped = _mean_abs(_gray_frame(1.2), _gray_frame(1.2 + 5.04))
    unrelated = _mean_abs(_gray_frame(1.2), _gray_frame(3.4))
    assert looped < 1.5
    assert unrelated > looped * 3
