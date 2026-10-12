"""Security scan for disposable private audition videos.

Structural checks always run and are never described as antivirus. A maintained
antivirus scanner is used only when ``NOVA_CASTING_SCANNER=clamav`` and its
signature database is present and current. A missing, stale, unknown, timing-out,
or failing scanner does not mark bytes clean.

This module does not publish files, log media bytes, or create signed URLs.
"""
from __future__ import annotations

import os
import shutil
import subprocess
import tempfile
import time
from dataclasses import dataclass
from pathlib import Path

from .casting_upload_rules import ALLOWED_MIME_TYPES, MAX_VIDEO_BYTES

_EICAR = b"EICAR-STANDARD-ANTIVIRUS-TEST-FILE"
_MP4_BRANDS = frozenset({b"isom", b"iso2", b"mp41", b"mp42", b"avc1", b"M4V ", b"dash"})
_ACTIVE_MARKERS = (b"<html", b"<script", b"<!doctype html", b"javascript:")
_SIGNATURE_MAX_AGE_SECONDS = 7 * 24 * 60 * 60
_STRUCTURAL_MODES = frozenset({"", "structural", "structural-only"})


@dataclass(frozen=True)
class ScanResult:
    clean: bool
    reason: str
    engine: str


@dataclass(frozen=True)
class ScannerCapability:
    """Honest scanner posture. ``antivirus_ready`` is true only for current signatures."""

    mode: str
    antivirus_ready: bool
    reason: str
    engine: str


def _reject(reason: str, engine: str = "structural") -> ScanResult:
    return ScanResult(False, reason, engine)


def configured_scanner_mode() -> str:
    raw = str(os.getenv("NOVA_CASTING_SCANNER") or "structural").strip().lower()
    if raw in _STRUCTURAL_MODES:
        return "structural"
    if raw == "clamav":
        return "clamav"
    return "unknown"


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


class ClamAvBackend:
    """Filesystem and process adapter. Tests can replace methods without a real scanner."""

    def binary(self) -> str | None:
        found = shutil.which("clamscan")
        return found if found else None

    def signature_mtime(self) -> float | None:
        configured = str(os.getenv("NOVA_CASTING_CLAMAV_DB") or "").strip()
        directory = Path(configured) if configured else Path("/var/lib/clamav")
        try:
            root = directory.resolve()
        except OSError:
            return None
        if not root.is_dir():
            return None
        newest: float | None = None
        for pattern in ("*.cvd", "*.cld"):
            for candidate in root.glob(pattern):
                try:
                    resolved = candidate.resolve()
                    if resolved.parent != root or not resolved.is_file() or resolved.stat().st_size <= 0:
                        continue
                    modified = resolved.stat().st_mtime
                except OSError:
                    continue
                newest = modified if newest is None else max(newest, modified)
        return newest

    def signatures_ready(self, now: float | None = None) -> tuple[bool, str]:
        modified = self.signature_mtime()
        if modified is None:
            return False, "Antivirus signatures are missing."
        age = (time.time() if now is None else now) - modified
        if age < 0 or age > _SIGNATURE_MAX_AGE_SECONDS:
            return False, "Antivirus signatures are stale."
        return True, "Antivirus signatures are current."

    def scan(self, data: bytes) -> bool:
        """True only when ClamAV exits 0. Missing, timeout, and errors are False."""
        binary = self.binary()
        if not binary:
            return False
        command = [binary, "--no-summary"]
        database = str(os.getenv("NOVA_CASTING_CLAMAV_DB") or "").strip()
        if database:
            command.extend(["--database", database])
        with tempfile.TemporaryDirectory(prefix="nova-casting-scan-") as directory:
            target = Path(directory) / "audition.bin"
            target.write_bytes(data)
            command.append(str(target))
            try:
                completed = subprocess.run(
                    command,
                    capture_output=True,
                    timeout=30,
                    check=False,
                )
            except (OSError, subprocess.TimeoutExpired):
                return False
        return completed.returncode == 0


def get_scanner_backend() -> ClamAvBackend:
    return ClamAvBackend()


def scanner_capability(backend: ClamAvBackend | None = None, now: float | None = None) -> ScannerCapability:
    mode = configured_scanner_mode()
    if mode == "structural":
        return ScannerCapability(
            "structural",
            False,
            "Structural scan only. Antivirus is not ready.",
            "structural",
        )
    if mode != "clamav":
        return ScannerCapability(
            "structural",
            False,
            "Scanner configuration is not recognized.",
            "structural",
        )
    scanner = backend or get_scanner_backend()
    if scanner.binary() is None:
        return ScannerCapability("antivirus", False, "Antivirus scanner is missing.", "clamscan")
    fresh, reason = scanner.signatures_ready(now)
    if not fresh:
        return ScannerCapability("antivirus", False, reason, "clamscan")
    return ScannerCapability("antivirus", True, "Antivirus signatures are current.", "clamscan")


def scan_video_bytes(data: bytes, declared_mime: str, backend: ClamAvBackend | None = None) -> ScanResult:
    """Fail closed. A structural pass is not an antivirus result."""
    if not isinstance(data, (bytes, bytearray)) or isinstance(data, memoryview):
        return _reject("Invalid video size")
    payload = bytes(data)
    if not payload or len(payload) > MAX_VIDEO_BYTES:
        return _reject("Invalid video size")
    if declared_mime not in ALLOWED_MIME_TYPES or not _mime_matches(payload, declared_mime):
        return _reject("Unsupported video type")
    if _hostile(payload):
        return _reject("Rejected by security scan")
    mode = configured_scanner_mode()
    if mode == "structural":
        return ScanResult(True, "Structural scan accepted", "structural")
    scanner = backend or get_scanner_backend()
    capability = scanner_capability(scanner)
    if not capability.antivirus_ready:
        engine = "clamscan" if mode == "clamav" else "structural"
        return _reject("Rejected by security scan", engine)
    if scanner.scan(payload):
        return ScanResult(True, "Antivirus scan accepted", "clamscan")
    return _reject("Rejected by security scan", "clamscan")
