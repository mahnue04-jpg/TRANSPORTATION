"""Structural scan and private file placement. No public URL is created."""
import importlib.util
import os
import stat
import subprocess
import sys
import time
import types
from pathlib import Path

FOLDER = Path(__file__).resolve().parents[1] / "app/core/nova/creative_studio"
BACKEND = Path(__file__).resolve().parents[1]
MP4 = b"\x00\x00\x00\x18ftypisom\x00\x00\x00\x00isomavc1"
WEBM = b"\x1a\x45\xdf\xa3" + b"\x00" * 8
QUICKTIME = b"\x00\x00\x00\x10ftypqt  \x00\x00\x00\x00"


def load_scan():
    prefix = "_casting_media_scan_test"
    package = types.ModuleType(prefix)
    package.__path__ = [str(FOLDER)]
    sys.modules[prefix] = package
    for name in ("casting_upload_rules", "casting_media_scan"):
        spec = importlib.util.spec_from_file_location(f"{prefix}.{name}", FOLDER / f"{name}.py")
        module = importlib.util.module_from_spec(spec)
        sys.modules[spec.name] = module
        spec.loader.exec_module(module)
    return sys.modules[f"{prefix}.casting_media_scan"]


def load_store():
    spec = importlib.util.spec_from_file_location(
        "casting_media_store_test_module", FOLDER / "casting_media_store.py"
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_structural_scan_accepts_allowed_video_and_rejects_hostile_bytes(monkeypatch):
    scan = load_scan()
    monkeypatch.setattr(scan.shutil, "which", lambda *_args, **_kwargs: None)
    assert scan.scan_video_bytes(MP4, "video/mp4").engine == "structural"
    assert scan.scan_video_bytes(WEBM, "video/webm").clean
    assert scan.scan_video_bytes(QUICKTIME, "video/quicktime").clean
    assert scan.scan_video_bytes(b"\xff\xd8\xff\x00", "video/mp4").reason == "Unsupported video type"
    assert scan.scan_video_bytes(b"", "video/mp4").reason == "Invalid video size"
    assert scan.scan_video_bytes(None, "video/mp4").reason == "Invalid video size"
    hostile = scan.scan_video_bytes(MP4 + b"EICAR-STANDARD-ANTIVIRUS-TEST-FILE", "video/mp4")
    assert hostile.clean is False
    assert hostile.reason == "Rejected by security scan"
    assert scan.scan_video_bytes(MP4 + b"<script>alert(1)</script>", "video/mp4").clean is False
    assert scan.scan_video_bytes(b"MZ" + b"\x00" * 16, "video/mp4").clean is False
    assert scan.scan_video_bytes(b"\x7fELF" + b"\x00" * 8, "video/webm").clean is False
    scan.MAX_VIDEO_BYTES = 8
    assert scan.scan_video_bytes(MP4, "video/mp4").reason == "Invalid video size"


def _fresh_signatures(tmp_path, monkeypatch, age_seconds=0):
    database = tmp_path / "clamav"
    database.mkdir(exist_ok=True)
    signature = database / "main.cvd"
    signature.write_bytes(b"synthetic-signature")
    stamp = time.time() - age_seconds
    os.utime(signature, (stamp, stamp))
    monkeypatch.setenv("NOVA_CASTING_CLAMAV_DB", str(database))
    monkeypatch.setenv("NOVA_CASTING_SCANNER", "clamav")
    return signature


def test_structural_mode_is_not_labeled_antivirus(monkeypatch):
    scan = load_scan()
    monkeypatch.delenv("NOVA_CASTING_SCANNER", raising=False)
    monkeypatch.setattr(scan.shutil, "which", lambda *_args, **_kwargs: "/usr/bin/clamscan")
    called = {"count": 0}

    def explode(*_args, **_kwargs):
        called["count"] += 1
        raise AssertionError("structural mode must not run clamscan")

    monkeypatch.setattr(scan.subprocess, "run", explode)
    result = scan.scan_video_bytes(MP4, "video/mp4")
    capability = scan.scanner_capability()
    assert result.clean is True
    assert result.engine == "structural"
    assert result.reason == "Structural scan accepted"
    assert "antivirus" not in result.reason.lower()
    assert capability.mode == "structural"
    assert capability.antivirus_ready is False
    assert capability.reason == "Structural scan only. Antivirus is not ready."
    assert called["count"] == 0


def test_clamscan_failure_is_not_treated_as_clean(monkeypatch, tmp_path):
    scan = load_scan()
    _fresh_signatures(tmp_path, monkeypatch)
    monkeypatch.setattr(scan.shutil, "which", lambda *_args, **_kwargs: "/usr/bin/clamscan")

    def reject(*_args, **_kwargs):
        return subprocess.CompletedProcess(args=["clamscan"], returncode=1)

    monkeypatch.setattr(scan.subprocess, "run", reject)
    blocked = scan.scan_video_bytes(MP4, "video/mp4")
    assert blocked.clean is False
    assert blocked.engine == "clamscan"
    assert scan.scanner_capability().antivirus_ready is True

    def explode(*_args, **_kwargs):
        raise subprocess.TimeoutExpired(cmd="clamscan", timeout=30)

    monkeypatch.setattr(scan.subprocess, "run", explode)
    assert scan.scan_video_bytes(MP4, "video/mp4").clean is False

    def accept(*_args, **_kwargs):
        return subprocess.CompletedProcess(args=["clamscan"], returncode=0)

    monkeypatch.setattr(scan.subprocess, "run", accept)
    accepted = scan.scan_video_bytes(MP4, "video/mp4")
    assert accepted.clean is True
    assert accepted.engine == "clamscan"
    assert accepted.reason == "Antivirus scan accepted"


def test_missing_or_stale_antivirus_fails_closed(monkeypatch, tmp_path):
    scan = load_scan()
    _fresh_signatures(tmp_path, monkeypatch)
    monkeypatch.setattr(scan.shutil, "which", lambda *_args, **_kwargs: None)
    missing = scan.scan_video_bytes(MP4, "video/mp4")
    assert missing.clean is False
    assert missing.engine == "clamscan"
    assert scan.scanner_capability().reason == "Antivirus scanner is missing."

    monkeypatch.setattr(scan.shutil, "which", lambda *_args, **_kwargs: "/usr/bin/clamscan")
    _fresh_signatures(tmp_path, monkeypatch, age_seconds=8 * 24 * 60 * 60)
    called = {"count": 0}

    def accept(*_args, **_kwargs):
        called["count"] += 1
        return subprocess.CompletedProcess(args=["clamscan"], returncode=0)

    monkeypatch.setattr(scan.subprocess, "run", accept)
    stale = scan.scan_video_bytes(MP4, "video/mp4")
    assert stale.clean is False
    assert stale.reason == "Rejected by security scan"
    assert scan.scanner_capability().antivirus_ready is False
    assert scan.scanner_capability().reason == "Antivirus signatures are stale."
    assert called["count"] == 0

    monkeypatch.setenv("NOVA_CASTING_SCANNER", "paid-vendor")
    unknown = scan.scan_video_bytes(MP4, "video/mp4")
    assert unknown.clean is False
    assert scan.scanner_capability().antivirus_ready is False
    assert scan.scanner_capability().reason == "Scanner configuration is not recognized."


def test_private_files_stay_outside_public_hosting(tmp_path, monkeypatch):
    store = load_store()
    private = tmp_path / "private"
    monkeypatch.setenv("NOVA_CASTING_PRIVATE_MEDIA_DIR", str(private))
    monkeypatch.delenv("NOVA_CREATIVE_MEDIA_DIR", raising=False)
    media_id = "a" * 32
    assert store.write_private_file(media_id, MP4) == media_id
    path = private / media_id
    assert path.read_bytes() == MP4
    assert stat.S_IMODE(path.stat().st_mode) == 0o600
    assert stat.S_IMODE(private.stat().st_mode) == 0o700
    assert store.read_private_file(media_id) == MP4
    assert store.read_private_file(f"private-quarantine/{media_id}") is None
    assert store.read_private_file("../" + media_id) is None
    assert store.private_file_exists("rejected") is False
    try:
        store.write_private_file("../secret", MP4)
    except ValueError:
        pass
    else:
        raise AssertionError("traversal key was accepted")
    public = BACKEND / "static" / "generated" / "casting-must-not-land"
    monkeypatch.setenv("NOVA_CASTING_PRIVATE_MEDIA_DIR", str(public))
    try:
        store.private_media_root()
    except RuntimeError as exc:
        assert "private" in str(exc)
    else:
        raise AssertionError("public directory was accepted")
    assert not public.exists()
    monkeypatch.setenv("NOVA_CASTING_PRIVATE_MEDIA_DIR", str(private))
    store.delete_private_file(media_id)
    assert not path.exists()
