"""Offline tests for the staging master verifier; no network or paid media."""
from io import BytesIO
import hashlib
import importlib.util
from pathlib import Path
import subprocess
import shutil

import pytest

SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "verify_studio_master_download.py"
spec = importlib.util.spec_from_file_location("studio_staging_verifier", SCRIPT)
verifier = importlib.util.module_from_spec(spec)
spec.loader.exec_module(verifier)


def digest(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def test_real_bytes_pass_exact_length_and_sha():
    data = b"real-stream-bytes" * 256
    sink = BytesIO()
    count = verifier.digest_reader(BytesIO(data), sink, len(data), digest(data))
    assert count == len(data)
    assert sink.getvalue() == data


@pytest.mark.parametrize("expected_length", [1, 3, 99999, 0, -1, 2 * 1024 * 1024 * 1024 + 1])
def test_truncated_or_oversized_transfer_fails(expected_length):
    data = b"hello"
    with pytest.raises(verifier.VerificationError):
        verifier.digest_reader(BytesIO(data), BytesIO(), expected_length, digest(data))


def test_corrupted_same_length_transfer_fails():
    with pytest.raises(verifier.VerificationError, match="SHA-256"):
        verifier.digest_reader(BytesIO(b"wrong"), BytesIO(), 5, digest(b"right"))


def test_invalid_sha_rejected_before_transfer():
    with pytest.raises(verifier.VerificationError, match="SHA-256"):
        verifier.digest_reader(BytesIO(b"abc"), BytesIO(), 3, "unsafe")


def test_staging_url_requires_https_and_no_secrets():
    good = verifier._download_url("https://studio.example.test", "project_1", "asset-2")
    assert good.endswith("/projects/project_1/assets/asset-2/file")
    for base in (
        "http://studio.example.test", "https://user:pw@studio.example.test",
        "https://studio.example.test?token=secret", "https://studio.example.test/#fragment",
    ):
        with pytest.raises(verifier.VerificationError):
            verifier._download_url(base, "project", "asset")
    with pytest.raises(verifier.VerificationError):
        verifier._download_url("https://studio.example.test", "../other", "asset")


def test_remote_download_rejects_no_bearer_before_network(tmp_path):
    with pytest.raises(verifier.VerificationError, match="bearer"):
        verifier.download_staging_master(
            "https://studio.example.test", "project", "asset",
            digest(b"file"), tmp_path / "master.mp4", "",
        )


@pytest.mark.skipif(not shutil.which("ffmpeg") or not shutil.which("ffprobe"), reason="FFmpeg tools missing")
def test_mp4_probe_checks_real_audio_and_video(tmp_path):
    target = tmp_path / "sample.mp4"
    subprocess.run([
        "ffmpeg", "-hide_banner", "-nostdin", "-loglevel", "error", "-y",
        "-f", "lavfi", "-i", "color=c=blue:s=160x90:r=12:d=2",
        "-f", "lavfi", "-i", "sine=frequency=440:duration=2",
        "-c:v", "libx264", "-preset", "ultrafast", "-pix_fmt", "yuv420p",
        "-c:a", "aac", "-shortest", str(target)
    ], capture_output=True, check=True, timeout=40)
    probe = verifier.inspect_mp4(target)
    assert probe["width"] == 160 and probe["height"] == 90
    assert probe["audio_codec"] == "aac"
    assert probe["video_codec"] == "h264"
    assert 1.5 <= probe["duration_seconds"] <= 2.5


@pytest.mark.skipif(not shutil.which("ffmpeg") or not shutil.which("ffprobe"), reason="FFmpeg tools missing")
def test_video_only_file_fails_audio_requirement(tmp_path):
    target = tmp_path / "silent.mp4"
    subprocess.run([
        "ffmpeg", "-hide_banner", "-nostdin", "-loglevel", "error", "-y",
        "-f", "lavfi", "-i", "color=c=red:s=160x90:r=12:d=1",
        "-an", "-c:v", "libx264", "-preset", "ultrafast",
        "-pix_fmt", "yuv420p", str(target)
    ], capture_output=True, check=True, timeout=40)
    with pytest.raises(verifier.VerificationError, match="video and audio"):
        verifier.inspect_mp4(target)
