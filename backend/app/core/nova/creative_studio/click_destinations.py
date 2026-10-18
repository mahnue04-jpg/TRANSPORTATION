"""First-party Nova click destinations for TikTok and Instagram.

Captions on those apps are not clickable. The profile Website field is the
click destination. This module prepares that URL and rejects platform homepages,
link-in-bio aggregators, and affiliate shorteners. It does not publish posts
and it does not invent post IDs when no connected account is available.
"""

from __future__ import annotations

import os
from typing import Any, Callable
from urllib.parse import urljoin, urlparse

CANONICAL_HOST = "getamicor.com"
NOVA_PRODUCT_PATH = "/nova-today/"
CAMPAIGN = "nova_30s_commercial"

_AGGREGATORS = {
    "linktr.ee",
    "www.linktr.ee",
    "linktree.com",
    "www.linktree.com",
    "beacons.ai",
    "www.beacons.ai",
    "stan.store",
    "www.stan.store",
    "bio.link",
    "www.bio.link",
    "lnk.bio",
    "taplink.cc",
    "www.taplink.cc",
    "campsite.bio",
    "allmylinks.com",
    "www.allmylinks.com",
    "hoo.be",
    "bit.ly",
    "tinyurl.com",
    "www.tinyurl.com",
    "amzn.to",
    "t.co",
}

_PLATFORM_HOMES = {
    "tiktok.com",
    "www.tiktok.com",
    "vm.tiktok.com",
    "instagram.com",
    "www.instagram.com",
    "l.instagram.com",
    "instagram.com",
}

_SOURCE = {
    "tiktok": "tiktok",
    "instagram": "instagram",
    "youtube shorts": "youtube",
    "youtube": "youtube",
    "facebook": "facebook",
}


def _host(url: str) -> str:
    return (urlparse(url).hostname or "").lower().rstrip(".")


def tracked_nova_url(platform: str) -> str:
    """Direct Nova product URL for a profile Website field. Not a caption link."""
    source = _SOURCE.get(str(platform or "").strip().lower(), "direct")
    return (
        f"https://{CANONICAL_HOST}{NOVA_PRODUCT_PATH}"
        f"?utm_source={source}&utm_medium=profile_website&utm_campaign={CAMPAIGN}"
    )


def classify_destination(url: str) -> str:
    """Classify a proposed click destination. Bare hosts are not website-field URLs."""
    raw = str(url or "").strip()
    if not raw:
        return "missing"
    if "://" not in raw:
        return "bare_text"
    parsed = urlparse(raw)
    if parsed.scheme not in {"http", "https"}:
        return "unsupported_scheme"
    host = _host(raw)
    if host in _PLATFORM_HOMES:
        return "platform_home"
    if host in _AGGREGATORS:
        return "aggregator"
    if host in {CANONICAL_HOST, "www." + CANONICAL_HOST}:
        path = parsed.path or "/"
        if path.rstrip("/") == NOVA_PRODUCT_PATH.rstrip("/"):
            return "first_party_nova"
        return "first_party_other"
    return "unrelated"


def _token_present(*names: str) -> bool:
    return any(bool(str(os.getenv(name) or "").strip()) for name in names)


def connected_account_audit() -> dict[str, Any]:
    """Boolean token presence only. Never invent post IDs or print secrets."""
    instagram = _token_present("INSTAGRAM_ACCESS_TOKEN", "META_ACCESS_TOKEN", "IG_ACCESS_TOKEN")
    tiktok = _token_present("TIKTOK_ACCESS_TOKEN", "TIKTOK_CLIENT_KEY")
    if instagram or tiktok:
        finding = (
            "A social token is present, but this session did not call Instagram or TikTok. "
            "Post IDs were not read and were not invented."
        )
    else:
        finding = (
            "No approved Instagram or TikTok token is configured in this session. "
            "Live post IDs and current profile links were not readable, so none were invented."
        )
    return {
        "instagram_token_present": instagram,
        "tiktok_token_present": tiktok,
        "posts_read": False,
        "post_ids": [],
        "finding": finding,
    }


def replacement_pack(platform: str) -> dict[str, Any]:
    url = tracked_nova_url(platform)
    return {
        "platform": str(platform or "TikTok"),
        "website_field_url": url,
        "classification": classify_destination(url),
        "spoken_cta": "Visit getamicor.com to explore AMICOR Nova.",
        "visible_end_card": "getamicor.com/nova-today",
        "caption_close": "Explore AMICOR Nova from the link in our profile.",
        "platform_limits": (
            "Instagram and TikTok captions and comments are not clickable links. "
            "The profile Website field is the click destination. "
            "Do not point it at tiktok.com, instagram.com, a link-in-bio page, or an affiliate shortener."
        ),
        "publish": False,
        "http_status": None,
        "verified": False,
        "connected_account_audit": connected_account_audit(),
    }


def verify_click_destination(
    url: str,
    *,
    fetch: Callable[[str], tuple[int, str | None]] | None = None,
    max_hops: int = 6,
) -> dict[str, Any]:
    """Follow redirects and accept only an HTTP 2xx that stays on the Nova product URL.

    `fetch` returns `(status, location)`. Location may be relative.
    """
    current = str(url or "").strip()
    chain: list[dict[str, Any]] = []
    opener = fetch or _urllib_fetch
    status = 0
    for _ in range(max_hops):
        try:
            status, location = opener(current)
        except Exception as exc:
            chain.append({"url": current, "status": 0, "error": type(exc).__name__})
            break
        chain.append({"url": current, "status": int(status), "location": location})
        if int(status) in {301, 302, 303, 307, 308} and location:
            current = urljoin(current, location)
            continue
        break
    final_url = str(chain[-1]["url"]) if chain else current
    classification = classify_destination(final_url)
    verified = bool(
        chain
        and 200 <= int(chain[-1].get("status") or 0) < 300
        and classification == "first_party_nova"
    )
    return {
        "website_field_url": str(url or "").strip(),
        "final_url": final_url,
        "http_status": int(chain[-1].get("status") or 0) if chain else 0,
        "chain": chain,
        "classification": classification,
        "verified": verified,
    }


def _urllib_fetch(url: str) -> tuple[int, str | None]:
    import urllib.error
    import urllib.request

    class _NoRedirect(urllib.request.HTTPRedirectHandler):
        def redirect_request(self, req, fp, code, msg, headers, newurl):  # noqa: ARG002
            return None

    opener = urllib.request.build_opener(_NoRedirect)
    request = urllib.request.Request(
        url,
        headers={"User-Agent": "AMICOR-Nova-LinkCheck/1.0"},
        method="GET",
    )
    try:
        with opener.open(request, timeout=12) as response:
            return int(response.status), response.headers.get("Location")
    except urllib.error.HTTPError as exc:
        return int(exc.code), exc.headers.get("Location")
