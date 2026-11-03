"""Read-only classification of Creative Studio originals requiring private-media migration.

This module never opens, moves, hashes, or deletes a media file.
"""
from __future__ import annotations

import re
from typing import Iterable, Any


PROTECTED_SOURCES = frozenset({"owner_import", "owner_video_import"})
PRIVATE_SCHEME = "private-media://"
_VALID_PRIVATE_REFERENCE = re.compile(r"private-media://imported_video_[a-f0-9]{12}\.mp4\Z")


def audit_protected_media(assets: Iterable[Any]) -> dict[str, int]:
    """Summarize exposure risk without returning filenames, paths, or identifiers.

    A protected original with a public URL needs migration even if a filename
    prefix is currently blocked: aliases and historical names are uncertain.
    Assets without a URL must be investigated, not counted as privately stored.
    """
    counts = {
        "protected_total": 0,
        "private_reference": 0,
        "public_reference_requires_migration": 0,
        "missing_reference_requires_review": 0,
    }
    for asset in assets:
        metadata = getattr(asset, "metadata", None) or {}
        if metadata.get("source") not in PROTECTED_SOURCES and not metadata.get("approved_master"):
            continue
        counts["protected_total"] += 1
        url = str(getattr(asset, "url", "") or "").strip()
        if _VALID_PRIVATE_REFERENCE.fullmatch(url):
            counts["private_reference"] += 1
        elif url.startswith(("/media/", "/static/", "/assets/")):
            counts["public_reference_requires_migration"] += 1
        else:
            counts["missing_reference_requires_review"] += 1
    return counts
