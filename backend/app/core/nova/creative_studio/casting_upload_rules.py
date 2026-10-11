"""Inactive admission rules for future private audition uploads.

This module performs metadata checks only. It does not accept or store media.
Server-side signature inspection, scanning, and private storage are still required.
"""
from __future__ import annotations

from dataclasses import dataclass

ALLOWED_MIME_TYPES = frozenset({"video/mp4", "video/quicktime", "video/webm"})
MAX_VIDEO_BYTES = 250 * 1024 * 1024


@dataclass(frozen=True)
class UploadDecision:
    allowed: bool
    reason: str


def validate_audition_upload_metadata(*, mime_type: str, byte_size: int, consent_confirmed: bool) -> UploadDecision:
    if not consent_confirmed:
        return UploadDecision(False, "Consent required")
    if mime_type not in ALLOWED_MIME_TYPES:
        return UploadDecision(False, "Unsupported video type")
    if not isinstance(byte_size, int) or isinstance(byte_size, bool) or not 0 < byte_size <= MAX_VIDEO_BYTES:
        return UploadDecision(False, "Invalid video size")
    return UploadDecision(True, "Metadata accepted; upload must remain private and quarantined")
