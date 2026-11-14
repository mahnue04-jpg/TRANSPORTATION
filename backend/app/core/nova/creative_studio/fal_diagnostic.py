"""Non-billable owner diagnostic for the fixed fal Kling first-shot endpoint.

Never calls the generation queue, returns secrets, toggles provider flags, or
infers account funding from dashboard screenshots. The pricing GET confirms
only access to that pricing API, NOT model submission permission.
"""
from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation
import json
import os
import urllib.error
import urllib.parse
import urllib.request

from app.core.nova.creative_studio.kling import MODEL, _NoRedirect


def fal_first_shot_diagnostic() -> dict:
    result = {
        "checked_at": datetime.now(timezone.utc).isoformat(),
        "endpoint_id": MODEL,
        "key_present": False,
        "key_authenticated": "UNVERIFIED",
        "model_authorized": "UNVERIFIED",
        "account_balance": "UNVERIFIED",
        "price_status": "UNVERIFIED",
        "price_usd_five_seconds": None,
        "generation_enabled_by_this_check": False,
        "provider_request_submitted": False,
        "blockers": [],
    }
    key = (os.environ.get("FAL_KEY") or "").strip()
    if not key:
        result["blockers"].append("FAL_KEY_MISSING")
        return result
    result["key_present"] = True
    url = "https://api.fal.ai/v1/models/pricing?" + urllib.parse.urlencode({"endpoint_id": MODEL})
    req = urllib.request.Request(url, method="GET", headers={
        "Authorization": "Key " + key, "Accept": "application/json",
    })
    try:
        with urllib.request.build_opener(_NoRedirect()).open(req, timeout=12) as response:
            raw = response.read(65537)
        if len(raw) > 65536:
            result["blockers"].append("PRICING_RESPONSE_TOO_LARGE")
            return result
        data = json.loads(raw.decode("utf-8"))
    except urllib.error.HTTPError as exc:
        # Never incorporate provider response bodies or exception strings.
        result["blockers"].append({
            401: "FAL_AUTH_REJECTED",
            402: "FAL_ACCOUNT_PAYMENT_REQUIRED",
            403: "FAL_ACCESS_DENIED",
        }.get(exc.code, "FAL_PRICING_HTTP_ERROR"))
        return result
    except (ValueError, UnicodeError, OSError, TimeoutError):
        result["blockers"].append("FAL_PRICING_UNAVAILABLE")
        return result
    # A successful authenticated request verifies access to pricing only.
    result["key_authenticated"] = "PRICING_API_ACCEPTED"
    try:
        prices = data["prices"]
        if not isinstance(prices, list) or len(prices) != 1 or data.get("has_more") is True:
            raise ValueError
        row = prices[0]
        if not isinstance(row, dict) or row["endpoint_id"] != MODEL or row["currency"] != "USD":
            raise ValueError
        qty = {"second": 5, "seconds": 5, "video": 1, "videos": 1}.get(row["unit"])
        if qty is None or isinstance(row["unit_price"], bool):
            raise ValueError
        value = Decimal(str(row["unit_price"]))
        if not value.is_finite() or value <= 0:
            raise ValueError
        total = value * qty
        if not total.is_finite():
            raise ValueError
    except (ValueError, KeyError, TypeError, InvalidOperation, AttributeError):
        result["blockers"].append("FAL_PRICING_AMBIGUOUS")
        return result
    result["price_status"] = "VERIFIED_FOR_PRICING_API"
    result["price_usd_five_seconds"] = str(total)
    result["blockers"].extend(["MODEL_SUBMISSION_PERMISSION_UNVERIFIED", "ACCOUNT_BALANCE_UNVERIFIED"])
    return result
