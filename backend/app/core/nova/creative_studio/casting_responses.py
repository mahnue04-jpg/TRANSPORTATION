"""Explicit response projections for future authenticated casting APIs.

These functions return only approved fields; never serialize ORM objects directly.
They have no routing, database, or external integrations.
"""
from __future__ import annotations
from typing import Mapping, Any


def applicant_application_view(record: Mapping[str, Any]) -> dict[str, Any]:
    """Caller must authorize the applicant before invoking this projection."""
    fields = ("id", "campaign_id", "status", "created_at")
    return {name: record[name] for name in fields}


def organizer_application_view(record: Mapping[str, Any]) -> dict[str, Any]:
    """Caller must be a verified, same-organization casting reviewer."""
    fields = ("id", "campaign_id", "status", "created_at")
    return {name: record[name] for name in fields}


def media_status_view(record: Mapping[str, Any]) -> dict[str, Any]:
    """Never reveal private object keys or unscanned media download URLs."""
    fields = ("id", "application_id", "status", "mime_type", "byte_size")
    return {name: record[name] for name in fields}
