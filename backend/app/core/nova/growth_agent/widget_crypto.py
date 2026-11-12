"""Signed widget installation tokens scoped to organization + domain."""

from __future__ import annotations

import hashlib
import hmac
import os
import time
from typing import Any
from urllib.parse import urlparse

from app.core.nova.growth_agent.errors import GrowthAgentError

_DEFAULT_TTL_SECONDS = 60 * 60 * 24 * 365  # install tokens are long-lived; rotate via dashboard


def _signing_secret() -> bytes:
    # Prefer dedicated secret; fall back to app secrets for local/test only.
    raw = (
        os.getenv("NOVA_GROWTH_AGENT_WIDGET_SECRET")
        or os.getenv("SECRET_KEY")
        or os.getenv("JWT_SECRET")
        or "growth-agent-dev-only-secret"
    )
    return str(raw).encode("utf-8")


def hash_token(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def mint_installation_token(
    *,
    organization_id: str,
    domain: str,
    installation_id: str,
    ttl_seconds: int = _DEFAULT_TTL_SECONDS,
) -> str:
    exp = int(time.time()) + int(ttl_seconds)
    payload = f"v1|{organization_id}|{domain.lower()}|{installation_id}|{exp}"
    sig = hmac.new(_signing_secret(), payload.encode("utf-8"), hashlib.sha256).hexdigest()
    return f"{payload}|{sig}"


def verify_installation_token(token: str) -> dict[str, Any]:
    parts = (token or "").split("|")
    if len(parts) != 6 or parts[0] != "v1":
        raise GrowthAgentError("INVALID_WIDGET_TOKEN", "Malformed widget token", http_status=401)
    version, org_id, domain, installation_id, exp_s, sig = parts
    payload = f"{version}|{org_id}|{domain}|{installation_id}|{exp_s}"
    expected = hmac.new(_signing_secret(), payload.encode("utf-8"), hashlib.sha256).hexdigest()
    if not hmac.compare_digest(expected, sig):
        raise GrowthAgentError("INVALID_WIDGET_TOKEN", "Invalid widget token signature", http_status=401)
    try:
        exp = int(exp_s)
    except ValueError as exc:
        raise GrowthAgentError("INVALID_WIDGET_TOKEN", "Invalid widget token expiry", http_status=401) from exc
    if exp < int(time.time()):
        raise GrowthAgentError("EXPIRED_WIDGET_TOKEN", "Widget token expired", http_status=401)
    return {
        "organization_id": org_id,
        "domain": domain,
        "installation_id": installation_id,
        "exp": exp,
    }


def normalize_origin_domain(origin: str | None, fallback_host: str | None = None) -> str:
    candidate = (origin or fallback_host or "").strip()
    if not candidate:
        return ""
    if "://" not in candidate:
        candidate = "https://" + candidate
    parsed = urlparse(candidate)
    host = (parsed.hostname or "").lower()
    return host


def domain_allowed(allowed_domain: str, request_origin: str | None) -> bool:
    allowed = (allowed_domain or "").lower().strip()
    origin_host = normalize_origin_domain(request_origin)
    if not allowed or not origin_host:
        return False
    return origin_host == allowed or origin_host.endswith("." + allowed)
