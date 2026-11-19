"""Fail-closed, read-only Cloudflare KV transport for owner-reviewed website inquiries.

No write/delete operations. Requires explicit staging activation, a verified
one-tenant namespace mapping, and an environment-injected restricted token.
Never supply token, namespace, or account from untrusted HTTP request inputs.
"""
from __future__ import annotations

import json
import os
import re
from urllib.parse import quote, urlencode
from urllib.request import Request, urlopen

from app.core.nova.growth_agent.website_inquiry_readonly import WebsiteInquirySourceError
from app.core.nova.growth_agent.website_inquiry_source_binding import (
    WebsiteInquiryBindingDenied, select_inquiry_source_binding,
)

_HEX = re.compile(r"^[0-9a-f]{32}$")
_KEY = re.compile(r"^lead:[^\x00-\x1f]{1,240}$")


class CloudflareReadonlyKV:
    def __init__(self, *, account_id: str, namespace_id: str, token: str):
        if not _HEX.fullmatch(account_id) or not _HEX.fullmatch(namespace_id) or not token or len(token) > 2048:
            raise WebsiteInquirySourceError("website_inquiry_source_unavailable")
        self._base = (
            "https://api.cloudflare.com/client/v4/accounts/"
            + account_id + "/storage/kv/namespaces/" + namespace_id
        )
        self._token = token

    def _request(self, path: str, *, json_response: bool):
        req = Request(self._base + path, headers={
            "Authorization": "Bearer " + self._token,
            "Accept": "application/json" if json_response else "text/plain",
        }, method="GET")
        try:
            with urlopen(req, timeout=8) as response:
                # Limit provider payloads to prevent an unexpectedly large response.
                data = response.read(262145)
                if len(data) > 262144:
                    raise WebsiteInquirySourceError("website_inquiry_source_unavailable")
                if not json_response:
                    return data.decode("utf-8")
                body = json.loads(data)
                if not isinstance(body, dict) or body.get("success") is not True:
                    raise WebsiteInquirySourceError("website_inquiry_source_unavailable")
                return body
        except WebsiteInquirySourceError:
            raise
        except Exception as exc:
            # Never include URL, headers, body, or provider errors in logs/replies.
            raise WebsiteInquirySourceError("website_inquiry_source_unavailable") from None

    def list_keys(self, *, prefix: str, cursor: str | None):
        if prefix != "lead:" or (cursor is not None and (not cursor or len(cursor) > 2048)):
            raise WebsiteInquirySourceError("website_inquiry_source_unavailable")
        params = {"prefix": "lead:", "limit": "100"}
        if cursor is not None:
            params["cursor"] = cursor
        body = self._request("/keys?" + urlencode(params), json_response=True)
        keys = body.get("result")
        info = body.get("result_info")
        if not isinstance(keys, list) or not isinstance(info, dict):
            raise WebsiteInquirySourceError("website_inquiry_source_unavailable")
        next_cursor = info.get("cursor")
        if next_cursor is not None and not isinstance(next_cursor, str):
            raise WebsiteInquirySourceError("website_inquiry_source_unavailable")
        return {"keys": keys, "list_complete": not bool(next_cursor), "cursor": next_cursor}

    def get_text(self, key: str):
        if not isinstance(key, str) or not _KEY.fullmatch(key):
            raise WebsiteInquirySourceError("website_inquiry_source_unavailable")
        return self._request("/values/" + quote(key, safe=""), json_response=False)


def staging_cloudflare_source_for_org(organization_id: str):
    """Return None unless *all* trusted staging settings are explicitly present.

    This function must run only after active owner/JWT and exact-tenant guards.
    Never turn this on in production; keep the staged source read-only.
    """
    if (
        os.getenv("AMICOR_ENVIRONMENT") != "staging"
        or os.getenv("NOVA_WEBSITE_INQUIRY_KV_READ_ENABLED") != "true"
    ):
        return None
    org = os.getenv("NOVA_WEBSITE_INQUIRY_ORG_ID", "")
    binding_name = "AMICOR_LEADS"
    try:
        binding = select_inquiry_source_binding(
            organization_id, {org: binding_name},
        )
        if binding.namespace_binding != binding_name:
            return None
        return CloudflareReadonlyKV(
            account_id=os.getenv("NOVA_WEBSITE_INQUIRY_CF_ACCOUNT_ID", ""),
            namespace_id=os.getenv("NOVA_WEBSITE_INQUIRY_CF_NAMESPACE_ID", ""),
            token=os.getenv("NOVA_WEBSITE_INQUIRY_CF_READ_TOKEN", ""),
        )
    except (WebsiteInquiryBindingDenied, WebsiteInquirySourceError):
        return None
