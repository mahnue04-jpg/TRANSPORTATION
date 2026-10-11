"""Security scan for disposable private audition videos.

Structural checks always run. ClamAV is used when ``clamscan`` is installed.
A failed or unavailable external scanner does not mark malware as clean.
This module does not publish files or create signed URLs.
"""
from __future__ import annotations

import shutil
import subprocess
import tempfile
from dataclasses import dataclass
from pathlib import Path

from .casting_upload_rules import ALLOWED_MIME_TYPES, MAX_VIDEO_BYTES

_EICAR = b"EICAR-STANDARD-ANTIVIRUS-TEST-FILE"
_MP4_BRANDS = frozenset({b"isom", b"iso2", b"mp41", b"mp42", b"avc1", b"M4V ", b"dash"})
_ACTIVE_MARKERS = (b"<html", b"<script", b"<!doctype html", b"javascript:")


@dataclass(frozen=True)
class ScanResult:
    clean: bool
    reason: str
    engine: str


def _reject(reason: str, engine: str = "structural") -> ScanResult:
    return ScanResult(False, reason, engine)


def _mime_matches(data: bytes, mime_type: str) -> bool:
    if mime_type == "video/webm":
        return data.startswith(b"\x1a\x45\xdf\xa3")
    if mime_type not in {"video/mp4", "video/quicktime"} or len(data) < 12 or data[4:8] != b"ftyp":
        return False
    brand = data[8:12]
    if mime_type == "video/quicktime":
        return brand == b"qt  "
    return brand in _MP4_BRANDS


def _hostile(data: bytes) -> bool:
    if _EICAR in data or data.startswith(b"MZ") or data.startswith(b"\x7fELF"):
        return True
    prefix = data[:512].lower()
    return any(marker in prefix for marker in _ACTIVE_MARKERS)


def _clamscan(data: bytes) -> bool | None:
    """True when ClamAV accepts the bytes, False on a hit or scanner failure, None when absent."""
    binary = shutil.which("clamscan")
    if not binary:
        return None
    with tempfile.TemporaryDirectory(prefix="nova-casting-scan-") as directory:
        target = Path(directory) / "audition.bin"
        target.write_bytes(data)
        try:
            completed = subprocess.run(
                [binary, "--no-summary", str(target)],
                capture_output=True,
                timeout=30,
                check=False,
            )
        except (OSError, subprocess.TimeoutExpired):
            return False
    if completed.returncode == 0:
        return True
    return False


def scan_video_bytes(data: bytes, declared_mime: str) -> ScanResult:
    """Fail closed. Clean means the bytes passed structural checks and ClamAV when present."""
    if not isinstance(data, (bytes, bytearray)) or isinstance(data, memoryview):
        return _reject("Invalid video size")
    payload = bytes(data)
    if not payload or len(payload) > MAX_VIDEO_BYTES:
        return _reject("Invalid video size")
    if declared_mime not in ALLOWED_MIME_TYPES or not _mime_matches(payload, declared_mime):
        return _reject("Unsupported video type")
    if _hostile(payload):
        return _reject("Rejected by security scan")
    clam = _clamscan(payload)
    if clam is False:
        return _reject("Rejected by security scan", "clamscan")
    if clam is True:
        return ScanResult(True, "Scan accepted", "clamscan")
    return ScanResult(True, "Structural scan accepted", "structural")
