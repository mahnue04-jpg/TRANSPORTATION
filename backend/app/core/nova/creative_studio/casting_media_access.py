"""Inactive audition media read boundary; no file retrieval or signed URLs.

All caller-supplied records must be fetched by a trusted server component.
"""
from __future__ import annotations

from .casting_access import CastingAccessDenied
from .casting_policy import CastingActor, may_view_audition_media
from .casting_responses import media_status_view
from .casting_upload_rules import ALLOWED_MIME_TYPES, MAX_VIDEO_BYTES


def read_media_metadata(*, actor: CastingActor | None, application: dict, campaign: dict, media: dict) -> dict:
    if actor is None:
        raise CastingAccessDenied("Media unavailable")
    required = ((application, ("id", "applicant_id", "campaign_id", "owner_id")),
                (campaign, ("id", "owner_id")),
                (media, ("id", "application_id", "owner_id", "status", "mime_type", "byte_size")))
    if any(not record.get(field) for record, fields in required for field in fields):
        raise CastingAccessDenied("Media unavailable")
    if (not isinstance(media["byte_size"], int) or isinstance(media["byte_size"], bool)
            or not 0 < media["byte_size"] <= MAX_VIDEO_BYTES
            or media["mime_type"] not in ALLOWED_MIME_TYPES):
        raise CastingAccessDenied("Media unavailable")
    if (application["campaign_id"] != campaign["id"]
            or application["owner_id"] != campaign["owner_id"]
            or media["owner_id"] != campaign["owner_id"]
            or media["application_id"] != application["id"]):
        raise CastingAccessDenied("Media unavailable")
    if not may_view_audition_media(
        actor, applicant_id=application["applicant_id"],
        organization_id=campaign["owner_id"], scan_status=media["status"]
    ):
        raise CastingAccessDenied("Media unavailable")
    return media_status_view(media)
