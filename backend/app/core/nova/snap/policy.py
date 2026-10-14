"""Snap limits, link safety, and media checks. No network calls."""
import json
import os
import re

MAX_MESSAGE_CHARS = 2000
MAX_GROUP_MEMBERS = 8
MAX_PHOTO_BYTES = 2_000_000
MAX_CLIP_BYTES = 8_000_000
MAX_CLIP_MS = 15_000
MIN_CLIP_MS = 1
MESSAGE_RETENTION_DAYS = 30
CAPTURE_RETENTION_HOURS = 72
MESSAGE_RATE = (30, 60)
CONTACT_RATE = (10, 3600)
CALL_RATE = (8, 3600)
CAPTURE_RATE = (12, 3600)
SIGNAL_RATE = (120, 60)
RING_TIMEOUT_S = 120
RECONNECT_AFTER_S = 20
FAIL_AFTER_S = 90
# A peer who has accepted but has not sent a description yet is still in the
# browser permission prompt. Do not treat that silence as a dropped call.
PERMISSION_GRACE_S = 180

_UNSAFE_LINK = re.compile(r"(?i)\b(?:javascript|data|vbscript|file|blob)\s*:")
_URL = re.compile(r"(?i)\bhttps?://[^\s<>]+")
_SCRIPT = re.compile(r"(?i)<\s*/?\s*script")
_CLIENT_ID = re.compile(r"^[A-Za-z0-9_\-]{8,80}$")


def client_id(value: str) -> str:
    text = (value or "").strip()
    if not _CLIENT_ID.fullmatch(text):
        raise ValueError("client_id")
    return text


def message_text(body: str) -> dict:
    text = (body or "").replace("\r\n", "\n").replace("\r", "\n")
    if not text.strip():
        raise ValueError("empty")
    if len(text) > MAX_MESSAGE_CHARS:
        raise ValueError("long")
    if any(ord(ch) < 32 and ch not in "\n\t" for ch in text):
        raise ValueError("control")
    if _UNSAFE_LINK.search(text) or _SCRIPT.search(text):
        raise ValueError("unsafe")
    return {"body": text, "untrusted_links": bool(_URL.search(text))}


def reason_text(body: str) -> str:
    text = (body or "").replace("\r\n", "\n").replace("\r", "\n").strip()
    if len(text) < 3 or len(text) > 500:
        raise ValueError("reason")
    if any(ord(ch) < 32 and ch not in "\n\t" for ch in text):
        raise ValueError("control")
    if _UNSAFE_LINK.search(text) or _SCRIPT.search(text):
        raise ValueError("unsafe")
    return text


def title_text(body: str) -> str:
    text = " ".join((body or "").split())
    if not text or len(text) > 80:
        raise ValueError("title")
    if any(ord(ch) < 32 for ch in text):
        raise ValueError("control")
    return text


def sniff_media(data: bytes, declared: str) -> str | None:
    kind = (declared or "").split(";", 1)[0].strip().lower()
    if data.startswith(b"\xff\xd8\xff") and kind in {"image/jpeg", "image/jpg"}:
        return "image/jpeg"
    if data.startswith(b"\x89PNG\r\n\x1a\n") and kind == "image/png":
        return "image/png"
    if len(data) > 12 and data[:4] == b"RIFF" and data[8:12] == b"WEBP" and kind == "image/webp":
        return "image/webp"
    if data.startswith(b"\x1a\x45\xdf\xa3") and kind == "video/webm":
        return "video/webm"
    if len(data) > 12 and data[4:8] == b"ftyp" and kind == "video/mp4":
        return "video/mp4"
    return None


def media_limit(content_type: str) -> int:
    if content_type.startswith("video/"):
        return MAX_CLIP_BYTES
    return MAX_PHOTO_BYTES


_ICE_URL = re.compile(r"^(?:stun|stuns|turn|turns):[^\s@]+$", re.IGNORECASE)
_CANDIDATE = re.compile(r"^candidate:\S+ \d+ \S+ \d+ \S+ \d+ typ (host|srflx|prflx|relay)\b")
_TARGET = re.compile(r"^[A-Za-z0-9_\-]{1,36}$")


def _ice_urls(raw: str) -> list[str]:
    urls = []
    for part in (raw or "").split(","):
        url = part.strip()
        if _ICE_URL.fullmatch(url):
            urls.append(url)
    return urls


def ice_config() -> dict:
    """Free STUN can be configured. TURN stays off unless an operator sets it.

    This module never buys a relay and never promises call quality.
    URLs with embedded userinfo are dropped so secrets are not copied into the page.
    """
    stun_raw = os.getenv("SNAP_STUN_URLS", "stun:stun.l.google.com:19302").strip()
    turn_raw = os.getenv("SNAP_TURN_URLS", "").strip()
    turn_user = os.getenv("SNAP_TURN_USERNAME", "").strip()
    turn_secret = os.getenv("SNAP_TURN_CREDENTIAL", "").strip()
    stun_urls = [] if stun_raw.lower() in {"", "off", "none"} else _ice_urls(stun_raw)
    turn_urls = _ice_urls(turn_raw)
    turn_ready = bool(turn_urls and turn_user and turn_secret)
    servers = []
    if stun_urls:
        servers.append({"urls": stun_urls})
    if turn_ready:
        servers.append({"urls": turn_urls, "username": turn_user, "credential": turn_secret})
    return {
        "stun_configured": bool(stun_urls),
        "turn_configured": turn_ready,
        "ice_servers": servers,
        "quality_guarantee": False,
        "calling_mode": "browser-webrtc-direct",
        "turn_purchased": False,
    }


def _sdp_lines(text: str) -> list[str]:
    if not isinstance(text, str) or "\x00" in text or len(text) > 20000:
        raise ValueError("sdp")
    normalized = text.replace("\r\n", "\n").replace("\r", "\n").strip()
    lines = normalized.split("\n")
    if not lines or lines[0] != "v=0":
        raise ValueError("sdp")
    if not any(line.startswith("m=audio ") for line in lines):
        raise ValueError("sdp")
    return lines


def _reject_relay(lines: list[str]) -> None:
    if ice_config()["turn_configured"]:
        return
    for line in lines:
        if "typ relay" in line.lower():
            raise ValueError("relay")


def _check_sdp(text: str, media: str) -> str:
    lines = _sdp_lines(text)
    if media == "video" and not any(line.startswith("m=video ") for line in lines):
        raise ValueError("sdp")
    _reject_relay(lines)
    return text.strip()


def normalize_description(payload: str, media: str) -> str:
    """Accept raw SDP or a {target, sdp} wrapper. Reject relay lines when TURN is off."""
    text = (payload or "").strip()
    if text.startswith("{"):
        try:
            body = json.loads(text)
        except json.JSONDecodeError as exc:
            raise ValueError("sdp") from exc
        if not isinstance(body, dict):
            raise ValueError("sdp")
        target = body.get("target")
        sdp = body.get("sdp")
        if not isinstance(target, str) or not _TARGET.fullmatch(target) or not isinstance(sdp, str):
            raise ValueError("sdp")
        return json.dumps({"target": target, "sdp": _check_sdp(sdp, media)}, separators=(",", ":"))
    return _check_sdp(text, media)


def _clean_candidate(candidate: dict) -> dict:
    line = candidate.get("candidate")
    if not isinstance(line, str):
        raise ValueError("ice")
    line = line.strip()
    if not line or len(line) > 500 or "\n" in line or "\r" in line or not _CANDIDATE.match(line):
        raise ValueError("ice")
    if "typ relay" in line.lower() and not ice_config()["turn_configured"]:
        raise ValueError("relay")
    clean = {"candidate": line}
    mid = candidate.get("sdpMid")
    index = candidate.get("sdpMLineIndex")
    if isinstance(mid, str) and 0 < len(mid) <= 8:
        clean["sdpMid"] = mid
    if isinstance(index, int) and not isinstance(index, bool) and 0 <= index <= 8:
        clean["sdpMLineIndex"] = index
    return clean


def normalize_ice(payload: str) -> str:
    """Store a host, srflx, prflx, or configured-relay candidate. Drop other JSON fields."""
    text = (payload or "").strip()
    if not text.startswith("{") or len(text) > 4000:
        raise ValueError("ice")
    try:
        body = json.loads(text)
    except json.JSONDecodeError as exc:
        raise ValueError("ice") from exc
    if not isinstance(body, dict):
        raise ValueError("ice")
    target = None
    candidate = body
    nested = body.get("candidate")
    if isinstance(nested, dict):
        target = body.get("target")
        candidate = nested
    clean = _clean_candidate(candidate)
    if target is not None:
        if not isinstance(target, str) or not _TARGET.fullmatch(target):
            raise ValueError("ice")
        return json.dumps({"target": target, "candidate": clean}, separators=(",", ":"))
    return json.dumps(clean, separators=(",", ":"))


def public_status() -> dict:
    ice = ice_config()
    blocker = None
    if not ice["turn_configured"]:
        blocker = (
            "No TURN relay is configured. Snap calls use a direct browser path and optional STUN "
            "address discovery only. Strict NATs, some mobile carriers, and many international paths "
            "will fail. A relay would be a separate infrastructure cost and is not purchased."
        )
    if ice["turn_configured"]:
        transport = "operator-turn"
    elif ice["stun_configured"]:
        transport = "stun-only"
    else:
        transport = "no-ice-servers"
    return {
        "product": "Nova Snap",
        "release": "preview",
        "production_ready": False,
        "production_release": False,
        "distinct_from": [
            "AMICOR Synapse meetings",
            "Nova Casting auditions",
            "Nova Communications inbox",
            "Work and Revenue",
        ],
        "stun_configured": ice["stun_configured"],
        "turn_configured": ice["turn_configured"],
        "turn_purchased": False,
        "two_device_verified": False,
        "human_two_device_test_required": True,
        "preview_transport": transport,
        "quality_guarantee": False,
        "calling_mode": ice["calling_mode"],
        "calling_blocker": blocker,
        "capture": {
            "opt_in": True,
            "max_clip_ms": MAX_CLIP_MS,
            "max_clip_bytes": MAX_CLIP_BYTES,
            "max_photo_bytes": MAX_PHOTO_BYTES,
            "public_upload": False,
            "retention_hours": CAPTURE_RETENTION_HOURS,
        },
        "messaging": {"retention_days": MESSAGE_RETENTION_DAYS, "max_group_members": MAX_GROUP_MEMBERS},
        "tiers": {
            "preview": "Included with this build. No new purchase. Organization contacts, STUN-only calls, 15-second private captures.",
            "relay_option": "Not enabled. A future team option could add TURN. There is no checkout and no new paid account in this change.",
        },
    }
