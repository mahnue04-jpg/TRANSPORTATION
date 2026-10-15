"""Disposable in-memory holding area for sandbox audition bytes.

Bytes never go to public static files, never get a URL, and are not returned
to callers. A clean structural or antivirus result still stays unreleased.
"""
from __future__ import annotations

from .casting_media_scan import scan_video_bytes
from .casting_upload_rules import validate_audition_upload_metadata

_MEMORY: dict[str, bytes] = {}
_MEMORY_CAP = 8


def evaluate_mock_upload(data: bytes, declared_mime: str) -> dict:
    """Validate MIME, size, and the malware-review gate. Do not store here."""
    size = len(data) if isinstance(data, (bytes, bytearray)) else 0
    decision = validate_audition_upload_metadata(
        mime_type=declared_mime, byte_size=size, consent_confirmed=True,
    )
    if not decision.allowed:
        return _rejected(declared_mime, size, decision.reason)
    scan = scan_video_bytes(bytes(data), declared_mime)
    if not scan.clean:
        return _rejected(declared_mime, size, scan.reason)
    return {
        "scan_status": "CLEAN",
        "scan_reason": scan.reason,
        "store_bytes": True,
        "mime_type": declared_mime,
        "byte_size": size,
        "engine": scan.engine,
    }


def hold(media_id: str, data: bytes) -> None:
    """Keep bytes only in this process. Drop the oldest entries past the cap."""
    if media_id in _MEMORY:
        _MEMORY.pop(media_id, None)
    while len(_MEMORY) >= _MEMORY_CAP:
        _MEMORY.pop(next(iter(_MEMORY)))
    _MEMORY[media_id] = bytes(data)


def holds(media_id: str) -> bool:
    return media_id in _MEMORY


def wipe() -> int:
    count = len(_MEMORY)
    _MEMORY.clear()
    return count


def _rejected(mime_type: str, size: int, reason: str) -> dict:
    return {
        "scan_status": "REJECTED",
        "scan_reason": reason,
        "store_bytes": False,
        "mime_type": mime_type,
        "byte_size": size,
        "engine": "structural",
    }
