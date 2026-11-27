"""Declared-size and media-type limits. No file is opened."""
from __future__ import annotations

from app.core.nova.intelligence.messages import MEDIA_TYPE_REJECTED, SIZE_REJECTED

MAX_DECLARED_BYTES = 8 * 1024 * 1024
ALLOWED_MEDIA_TYPES = frozenset({"video/mp4"})


class QuotaError(ValueError):
    def __init__(self, detail: str) -> None:
        super().__init__(detail)
        self.detail = detail


def check_quota(media_type: object, declared_bytes: object) -> None:
    if not isinstance(media_type, str) or media_type not in ALLOWED_MEDIA_TYPES:
        raise QuotaError(MEDIA_TYPE_REJECTED)
    if isinstance(declared_bytes, bool) or not isinstance(declared_bytes, int):
        raise QuotaError(SIZE_REJECTED)
    if declared_bytes < 1 or declared_bytes > MAX_DECLARED_BYTES:
        raise QuotaError(SIZE_REJECTED)
