"""Typed draft checks for a future audition intake. Nothing is stored or uploaded.

Callers pass a plain mapping. Extra fields are rejected, including protected-trait
scores and storage locators. Minors are ineligible; there is no guardian bypass.
"""
from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass

from .casting_upload_rules import ALLOWED_MIME_TYPES, MAX_VIDEO_BYTES

MINIMUM_CASTING_AGE = 18
CAMPAIGN_CATEGORIES = frozenset({"reality", "beauty", "film"})
CAMPAIGN_STATUSES = frozenset({"DRAFT", "CLOSED"})
_APPLICATION_FIELDS = frozenset({"consent_accepted", "consent_version", "age_years", "mime_type", "byte_size"})
_CAMPAIGN_FIELDS = frozenset({"title", "category", "minimum_age", "status"})


@dataclass(frozen=True)
class IntakeDecision:
    accepted: bool
    reason: str


def _reject(reason: str) -> IntakeDecision:
    return IntakeDecision(False, reason)


def validate_draft_application_intake(payload: Mapping[str, object]) -> IntakeDecision:
    """Validate consent, age, MIME, and size. Does not accept file bytes."""
    if not isinstance(payload, Mapping):
        return _reject("Invalid intake")
    unknown = set(payload) - _APPLICATION_FIELDS
    if unknown:
        return _reject("Unsupported field")
    if payload.get("consent_accepted") is not True:
        return _reject("Consent required")
    version = payload.get("consent_version")
    if not isinstance(version, str) or not version.strip() or len(version) > 32:
        return _reject("Consent version required")
    age = payload.get("age_years")
    if isinstance(age, bool) or not isinstance(age, int) or age < MINIMUM_CASTING_AGE:
        return _reject("Applicant does not meet the minimum age")
    mime_type = payload.get("mime_type")
    if mime_type not in ALLOWED_MIME_TYPES:
        return _reject("Unsupported video type")
    byte_size = payload.get("byte_size")
    if isinstance(byte_size, bool) or not isinstance(byte_size, int) or not 0 < byte_size <= MAX_VIDEO_BYTES:
        return _reject("Invalid video size")
    return IntakeDecision(True, "Draft metadata accepted; no upload was stored")


def validate_draft_campaign(payload: Mapping[str, object]) -> IntakeDecision:
    """Validate an unpublished campaign spec. Publishing is not represented."""
    if not isinstance(payload, Mapping):
        return _reject("Invalid campaign")
    if set(payload) - _CAMPAIGN_FIELDS:
        return _reject("Unsupported field")
    title = payload.get("title")
    if not isinstance(title, str) or not title.strip() or len(title) > 200:
        return _reject("Invalid title")
    if payload.get("category") not in CAMPAIGN_CATEGORIES:
        return _reject("Unsupported category")
    minimum_age = payload.get("minimum_age", MINIMUM_CASTING_AGE)
    if isinstance(minimum_age, bool) or not isinstance(minimum_age, int) or minimum_age < MINIMUM_CASTING_AGE:
        return _reject("Minimum age must be at least 18")
    status = payload.get("status", "DRAFT")
    if status not in CAMPAIGN_STATUSES:
        return _reject("Campaign cannot be published")
    return IntakeDecision(True, "Draft campaign spec accepted; nothing was published")
