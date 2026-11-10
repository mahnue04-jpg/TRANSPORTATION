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


def test_staging_download_streams_and_renames_only_verified_file(monkeypatch, tmp_path):
    payload = b"synthetic-mp4-byte-content"
    class FakeResponse(BytesIO):
        status = 200
        headers = {"Content-Length": str(len(payload)), "Content-Type": "video/mp4"}
    class FakeOpener:
        def open(self, request, timeout):
            assert request.get_header("Authorization") == "Bearer mock-owner-token"
            assert request.full_url.endswith("/projects/project/assets/asset/file")
            return FakeResponse(payload)
    monkeypatch.setattr(verifier.urllib.request, "build_opener", lambda *handlers: FakeOpener())
    # These are byte-transfer fixture bytes, not an MP4; actual probe paths
    # are independently exercised with synthetic H.264/AAC fixtures below.
    monkeypatch.setattr(verifier, "inspect_mp4", lambda path: {
        "video_codec": "h264", "audio_codec": "aac", "duration_seconds": 1.0
    })
    destination = tmp_path / "verified.mp4"
    assert verifier.download_staging_master(
        "https://studio.example.test", "project", "asset",
        digest(payload), destination, "mock-owner-token",
    ) == len(payload)
    assert destination.read_bytes() == payload
    assert not (tmp_path / "verified.mp4.partial").exists()


def test_staging_download_does_not_preserve_corrupt_partial(monkeypatch, tmp_path):
    payload = b"changed-mp4-data"
    class FakeResponse(BytesIO):
        status = 200
        headers = {"Content-Length": str(len(payload)), "Content-Type": "video/mp4"}
    class FakeOpener:
        def open(self, request, timeout):
            return FakeResponse(payload)
    monkeypatch.setattr(verifier.urllib.request, "build_opener", lambda *handlers: FakeOpener())
    destination = tmp_path / "untrusted.mp4"
    with pytest.raises(verifier.VerificationError, match="SHA-256"):
        verifier.download_staging_master(
            "https://studio.example.test", "project", "asset",
            digest(b"original-data!!"), destination, "mock-owner-token",
        )
    assert not destination.exists()
    assert not (tmp_path / "untrusted.mp4.partial").exists()


def test_staging_download_refuses_overwriting_existing_evidence(monkeypatch, tmp_path):
    destination = tmp_path / "original-evidence.mp4"
    destination.write_bytes(b"existing")
    with pytest.raises(verifier.VerificationError, match="overwrite"):
        verifier.download_staging_master(
            "https://studio.example.test", "project", "asset",
            digest(b"other"), destination, "mock-owner-token",
        )
    assert destination.read_bytes() == b"existing"


def test_staging_rejects_same_hash_non_video_before_finalizing(monkeypatch, tmp_path):
    payload = b"fake-video-with-matching-checksum"
    class FakeResponse(BytesIO):
        status = 200
        headers = {"Content-Length": str(len(payload)), "Content-Type": "video/mp4"}
    class FakeOpener:
        def open(self, request, timeout):
            return FakeResponse(payload)
    monkeypatch.setattr(verifier.urllib.request, "build_opener", lambda *handlers: FakeOpener())
    output = tmp_path / "unplayable.mp4"
    with pytest.raises(verifier.VerificationError, match="FFprobe"):
        verifier.download_staging_master(
            "https://studio.example.test", "project", "asset",
            digest(payload), output, "mock-owner-token"
        )
    assert not output.exists()
    assert not (tmp_path / "unplayable.mp4.partial").exists()


@pytest.mark.parametrize("video_codec,audio_codec", [
    ("mpeg4", "aac"), ("h264", "mp3"), ("vp9", "opus"),
])
def test_probe_rejects_wrong_codecs(monkeypatch, tmp_path, video_codec, audio_codec):
    import json
    from types import SimpleNamespace
    video = {"codec_type": "video", "codec_name": video_codec,
             "width": 1280, "height": 720}
    audio = {"codec_type": "audio", "codec_name": audio_codec}
    fake = SimpleNamespace(stdout=json.dumps({
        "format": {"duration": "650.0"}, "streams": [video, audio]
    }))
    monkeypatch.setattr(verifier.subprocess, "run", lambda *args, **kwargs: fake)
    with pytest.raises(verifier.VerificationError, match="H.264"):
        verifier.inspect_mp4(tmp_path / "dummy.mp4")


@pytest.mark.parametrize("duration", ["0", "-1", "nan", "inf", "3601"])
def test_probe_rejects_invalid_or_unbounded_duration(monkeypatch, tmp_path, duration):
    import json
    from types import SimpleNamespace
    fake = SimpleNamespace(stdout=json.dumps({
        "format": {"duration": duration},
        "streams": [
            {"codec_type": "video", "codec_name": "h264", "width": 1280, "height": 720},
            {"codec_type": "audio", "codec_name": "aac"},
        ]
    }))
    monkeypatch.setattr(verifier.subprocess, "run", lambda *args, **kwargs: fake)
    with pytest.raises(verifier.VerificationError, match="duration"):
        verifier.inspect_mp4(tmp_path / "dummy.mp4")


def test_remote_transfer_rejects_redirect_without_following_authorization(monkeypatch, tmp_path):
    from urllib.error import HTTPError
    class RedirectOpener:
        def open(self, request, timeout):
            raise verifier.VerificationError("Staging download redirected unexpectedly.")
    monkeypatch.setattr(verifier.urllib.request, "build_opener",
                        lambda *handlers: RedirectOpener())
    target = tmp_path / "no-redirect.mp4"
    with pytest.raises(verifier.VerificationError, match="redirected"):
        verifier.download_staging_master(
            "https://studio.example.test", "project", "asset",
            digest(b"fake"), target, "mock-owner-token"
        )
    assert not target.exists()


@pytest.mark.skipif(not shutil.which("ffmpeg") or not shutil.which("ffprobe"), reason="FFmpeg tools missing")
def test_full_video_and_audio_decode_on_valid_synthetic_clip(tmp_path):
    media = tmp_path / "decoded.mp4"
    subprocess.run([
        "ffmpeg", "-hide_banner", "-nostdin", "-loglevel", "error", "-y",
        "-f", "lavfi", "-i", "color=c=blue:s=160x90:r=12:d=1",
        "-f", "lavfi", "-i", "sine=frequency=440:duration=1",
        "-c:v", "libx264", "-preset", "ultrafast", "-pix_fmt", "yuv420p",
        "-c:a", "aac", "-shortest", str(media),
    ], check=True, capture_output=True, timeout=40)
    assert verifier.decode_mp4(media) is None


@pytest.mark.skipif(not shutil.which("ffmpeg") or not shutil.which("ffprobe"), reason="FFmpeg tools missing")
def test_full_decode_rejects_corrupt_pseudo_video(tmp_path):
    bad = tmp_path / "corrupt.mp4"
    bad.write_bytes(b"fake-mp4")
    with pytest.raises(verifier.VerificationError, match="decode failed"):
        verifier.decode_mp4(bad)
