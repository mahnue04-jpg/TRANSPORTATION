"""Snap limits, link safety, and media checks. No network calls."""
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


def ice_config() -> dict:
    """Free STUN can be configured. TURN stays off unless an operator sets it.

    This does not buy a relay and does not promise call quality.
    """
    stun_raw = os.getenv("SNAP_STUN_URLS", "stun:stun.l.google.com:19302").strip()
    turn_raw = os.getenv("SNAP_TURN_URLS", "").strip()
    turn_user = os.getenv("SNAP_TURN_USERNAME", "").strip()
    turn_secret = os.getenv("SNAP_TURN_CREDENTIAL", "").strip()
    stun_urls = [] if stun_raw.lower() in {"", "off", "none"} else [u.strip() for u in stun_raw.split(",") if u.strip()]
    turn_urls = [u.strip() for u in turn_raw.split(",") if u.strip()] if turn_raw else []
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
    }


def public_status() -> dict:
    ice = ice_config()
    blocker = None
    if not ice["turn_configured"]:
        blocker = (
            "No TURN relay is configured. Snap calls use a direct browser path and optional STUN "
            "address discovery only. Strict NATs, some mobile carriers, and many international paths "
            "will fail. A relay would be a separate infrastructure cost and is not purchased."
        )
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
