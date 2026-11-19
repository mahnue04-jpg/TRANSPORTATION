"""Read-only, fail-closed Cloudflare-shaped lead listing contract.

No Cloudflare SDK, HTTP request, credentials, database writes, or production route.
A separate approved implementation must supply a trusted source. This module
supports offline fixtures only and never equates a failed read with zero leads.
"""
from __future__ import annotations

import json
from typing import Any, Protocol

from app.core.nova.growth_agent.website_inquiry_records import normalize_inquiry_entries

MAX_PAGES = 20
MAX_KEYS = 1000
MAX_VALUE_BYTES = 16_384


class WebsiteInquirySourceError(Exception):
    """Sanitized unavailable-source error; never includes customer contents."""


class ReadOnlyKVSource(Protocol):
    def list_keys(self, *, prefix: str, cursor: str | None) -> dict[str, Any]: ...
    def get_text(self, key: str) -> str | None: ...


def read_website_inquiries(source: ReadOnlyKVSource, *, trusted_synthetic_fixture: bool = False) -> list[dict[str, Any]]:
    """Read every page before returning results; no partial lists on errors.

    Caller MUST enforce existing server-side owner/tenant authorization before
    invoking this function. This pure source contract does not supply auth.
    """
    seen_keys: set[str] = set()
    seen_cursors: set[str] = set()
    items: list[dict[str, Any]] = []
    cursor: str | None = None
    try:
        for _ in range(MAX_PAGES):
            page = source.list_keys(prefix="lead:", cursor=cursor)
            if not isinstance(page, dict) or not isinstance(page.get("keys"), list) or type(page.get("list_complete")) is not bool:
                raise WebsiteInquirySourceError("website_inquiry_source_unavailable")
            for entry in page["keys"]:
                if not isinstance(entry, dict) or not isinstance(entry.get("name"), str):
                    raise WebsiteInquirySourceError("website_inquiry_source_unavailable")
                key = entry["name"]
                if not key.startswith("lead:") or key in seen_keys:
                    continue
                seen_keys.add(key)
                if len(seen_keys) > MAX_KEYS:
                    raise WebsiteInquirySourceError("website_inquiry_source_limit")
                value = source.get_text(key)
                if not isinstance(value, str) or len(value.encode("utf-8")) > MAX_VALUE_BYTES:
                    raise WebsiteInquirySourceError("website_inquiry_source_unavailable")
                try:
                    payload = json.loads(value)
                except (ValueError, TypeError) as exc:
                    raise WebsiteInquirySourceError("website_inquiry_source_unavailable") from exc
                items.append({"key": key, "value": payload})
            if page["list_complete"] is True:
                return normalize_inquiry_entries(items, trusted_synthetic_fixture=trusted_synthetic_fixture)
            next_cursor = page.get("cursor")
            if not isinstance(next_cursor, str) or not next_cursor or next_cursor in seen_cursors:
                raise WebsiteInquirySourceError("website_inquiry_source_unavailable")
            seen_cursors.add(next_cursor)
            cursor = next_cursor
        raise WebsiteInquirySourceError("website_inquiry_source_limit")
    except WebsiteInquirySourceError:
        raise
    except Exception as exc:
        # Do not propagate network/provider exceptions, credentials or raw lead PII.
        raise WebsiteInquirySourceError("website_inquiry_source_unavailable") from exc
