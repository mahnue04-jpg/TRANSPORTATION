"""Archive a downloaded Kling shot without submitting any provider request."""
from __future__ import annotations

import hashlib

from app.core.nova.creative_studio import private_object_storage as storage
from app.core.nova.creative_studio.providers import _resolve_creative_media_url
from app.core.nova.creative_studio.video_import import MAX_VIDEO_BYTES, validate_video


def archive_first_shot(owner_id: str, project_id: str, source_url: str) -> dict:
    if not storage.enabled():
        raise storage.PrivateStorageError("Private shot storage is disabled")
    # Resolve only Nova's existing local media references. Never fetch a URL
    # supplied by a client or treat a CDN link as an archived original.
    path = _resolve_creative_media_url(source_url)
    if path is None or not path.is_file() or not 0 < path.stat().st_size <= MAX_VIDEO_BYTES:
        raise ValueError("Downloaded shot is missing or exceeds the archive limit")
    measured = validate_video(path, max_duration_seconds=6, allow_silent=True)
    if measured["duration_seconds"] < 4:
        raise ValueError("Downloaded shot is shorter than the five-second request")
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for chunk in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(chunk)
    checksum = digest.hexdigest()
    url = storage.put_original_file(
        owner_id, project_id, "imported_video_" + checksum + ".mp4", path,
        checksum, max_bytes=MAX_VIDEO_BYTES,
    )
    return {"url": url, **measured, "sha256": checksum,
            "source": "kling_first_shot_archive", "owner_review_required": True,
            "publish_ready": False, "actor_movement_verified": False}
