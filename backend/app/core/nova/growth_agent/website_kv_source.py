"""Default-off, read-only Cloudflare KV source for AMICOR website inquiries.

This adapter is scoped to one explicitly configured Nova organization. It
never writes KV, sends messages or imports Growth CRM contacts. Invalid or
partial Cloudflare responses fail closed without returning partial lead data.
"""
from __future__ import annotations

import json
import os
import re
from datetime import datetime, timezone
from typing import Any
from urllib.parse import quote
from urllib.request import Request, urlopen

_API = "https://api.cloudflare.com/client/v4"
_ID = re.compile(r"^[a-zA-Z0-9_-]{8,128}$")
_EMAIL = re.compile(r"^[^\s@]+@[^\s@]+\.[^\s@]+$")


def _text(raw: Any, length: int) -> str:
    return raw.strip()[:length] if isinstance(raw, str) else ""


class WebsiteKVSource:
    def __init__(self, *, tenant_id: str, account_id: str, namespace_id: str,
                 token: str, request_json=None):
        if not tenant_id or not _ID.fullmatch(account_id) or not _ID.fullmatch(namespace_id) or not token:
            raise ValueError("Invalid website KV source configuration")
        self.tenant_id = tenant_id
        self.account_id = account_id
        self.namespace_id = namespace_id
        self.token = token
        self.request_json = request_json or self._request

    def _request(self, path: str) -> dict[str, Any]:
        url = f"{_API}/accounts/{self.account_id}/storage/kv/namespaces/{self.namespace_id}/{path}"
        request = Request(url, headers={"Authorization": f"Bearer {self.token}", "Accept": "application/json"})
        with urlopen(request, timeout=8) as response:
            body = response.read(256_001)
        if len(body) > 256_000:
            raise ValueError("oversized Cloudflare response")
        return json.loads(body)

    @staticmethod
    def _normalize(key: str, value: Any) -> dict[str, Any] | None:
        if not isinstance(value, dict) or not key.startswith("lead:") or len(key) > 300:
            return None
        received = value.get("receivedAt", value.get("received_at"))
        if not isinstance(received, str):
            return None
        try:
            when = datetime.fromisoformat(received.replace("Z", "+00:00"))
            if when.tzinfo is None:
                return None
        except ValueError:
            return None
        name = _text(value.get("name"), 120)
        email = _text(value.get("email"), 254).lower()
        if not name or not _EMAIL.fullmatch(email):
            return None
        ref = key[5:] if key.startswith("lead:AMQ-") else None
        return {
            "source_system": "cloudflare_amicor_leads",
            "source_key": key,
            "reference_id": ref,
            "received_at": when.astimezone(timezone.utc).isoformat(),
            "name": name,
            "company": _text(value.get("company"), 160),
            "email": email,
            "product": _text(value.get("product"), 80),
            "message": _text(value.get("message"), 2000),
            "consent": value.get("consent") is True or value.get("consent") == "yes",
            "is_synthetic": value.get("is_synthetic") is True,
        }

    def read(self, organization_id: str) -> dict[str, Any]:
        if organization_id != self.tenant_id:
            # The binding owns one website namespace; never share it across tenants.
            raise PermissionError("Organization not authorized for website inquiries")
        rows = []
        seen = set()
        cursor = None
        seen_cursors = set()
        try:
            # 4 pages x 25 keys. If not complete, return no partial dataset.
            for _ in range(4):
                query = "keys?prefix=lead%3A&limit=25"
                if cursor:
                    query += "&cursor=" + quote(cursor, safe="")
                page = self.request_json(query)
                if not isinstance(page, dict) or page.get("success") is not True or not isinstance(page.get("result"), list):
                    raise ValueError("invalid KV listing")
                for item in page["result"]:
                    key = item.get("name") if isinstance(item, dict) else None
                    if not isinstance(key, str) or not key.startswith("lead:") or len(key) > 300:
                        continue
                    if key in seen:
                        continue
                    seen.add(key)
                    data = self.request_json("values/" + quote(key, safe=""))
                    if not isinstance(data, dict):
                        raise ValueError("invalid KV value")
                    row = self._normalize(key, data)
                    if row is not None:
                        rows.append(row)
                info = page.get("result_info")
                if not isinstance(info, dict):
                    raise ValueError("KV page status missing")
                next_cursor = info.get("cursor")
                if not next_cursor:
                    return {"state": "available", "inquiries": rows, "complete": True}
                if not isinstance(next_cursor, str) or next_cursor in seen_cursors:
                    return {"state": "stale", "inquiries": [], "complete": False}
                seen_cursors.add(next_cursor)
                cursor = next_cursor
            return {"state": "stale", "inquiries": [], "complete": False}
        except Exception:
            return {"state": "unavailable", "inquiries": [], "complete": False}


def configured_website_source() -> WebsiteKVSource | None:
    if os.getenv("NOVA_GA_WEBSITE_KV_READ_ENABLED", "").strip().lower() != "true":
        return None
    values = [
        os.getenv("NOVA_GA_WEBSITE_KV_TENANT_ID", ""),
        os.getenv("NOVA_GA_WEBSITE_CF_ACCOUNT_ID", ""),
        os.getenv("NOVA_GA_WEBSITE_CF_NAMESPACE_ID", ""),
        os.getenv("NOVA_GA_WEBSITE_CF_API_TOKEN", ""),
    ]
    if any(not value for value in values):
        return None
    try:
        return WebsiteKVSource(tenant_id=values[0], account_id=values[1],
                               namespace_id=values[2], token=values[3])
    except ValueError:
        return None
