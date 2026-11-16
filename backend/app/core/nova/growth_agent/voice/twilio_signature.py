"""Twilio webhook signature validation (RequestValidator-compatible, no SDK)."""

from __future__ import annotations

import base64
import hmac
import hashlib
import time
from datetime import datetime, timezone
from typing import Any, Mapping

from app.core.nova.growth_agent.errors import GrowthAgentError

# Explicit token label for simulator-only runs when TWILIO_AUTH_TOKEN is unset.
SIMULATOR_AUTH = "nova-ga-voice-simulator-auth"

SIGNATURE_SKEW_SECONDS = 300
_TIMESTAMP_KEYS = ("Timestamp", "MessageDate", "DateCreated", "date_created", "timestamp")


class TwilioSignatureError(GrowthAgentError):
    def __init__(self, code: str, message: str, *, http_status: int = 403) -> None:
        super().__init__(code, message, http_status=http_status)


def compute_twilio_signature(*, url: str, params: Mapping[str, Any], auth_token: str) -> str:
    """HMAC-SHA1 over sorted POST fields — matches Twilio RequestValidator."""
    pieces = [str(url)]
    for key in sorted(params.keys()):
        pieces.append(str(key))
        val = params[key]
        if val is None:
            pieces.append("")
        elif isinstance(val, (list, tuple)):
            pieces.append("".join(str(v) for v in val))
        else:
            pieces.append(str(val))
    payload = "".join(pieces).encode("utf-8")
    digest = hmac.new(auth_token.encode("utf-8"), payload, hashlib.sha1).digest()
    return base64.b64encode(digest).decode("ascii")


def _parse_twilio_timestamp(value: Any) -> float | None:
    if value is None or value == "":
        return None
    if isinstance(value, (int, float)):
        ts = float(value)
        if ts > 1e12:
            ts /= 1000.0
        return ts
    text = str(value).strip()
    if text.isdigit():
        ts = float(text)
        if ts > 1e12:
            ts /= 1000.0
        return ts
    try:
        if text.endswith("Z"):
            text = text[:-1] + "+00:00"
        dt = datetime.fromisoformat(text)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt.timestamp()
    except ValueError:
        return None


def check_timestamp_replay_skew(params: Mapping[str, Any]) -> None:
    """Secondary replay guard when Twilio supplies a timestamp-like field.

    Primary replay protection is ``(provider, event_id)`` uniqueness on
    ``GaVoiceWebhookEvent`` (see ``inbound.record_webhook_event``).
    """
    for key in _TIMESTAMP_KEYS:
        if key not in params:
            continue
        parsed = _parse_twilio_timestamp(params[key])
        if parsed is None:
            continue
        skew = abs(time.time() - parsed)
        if skew > SIGNATURE_SKEW_SECONDS:
            raise TwilioSignatureError(
                "VOICE_TIMESTAMP_SKEW",
                "Webhook timestamp outside acceptable window",
                http_status=403,
            )
        return


def validate_twilio_signature(
    *,
    url: str,
    params: dict[str, Any],
    signature_header: str | None,
    auth_token: str | None,
    simulator_mode: bool = False,
) -> None:
    """Validate ``X-Twilio-Signature``. Reject missing auth token unless simulator."""
    token = (auth_token or "").strip()
    if not token:
        if simulator_mode:
            token = SIMULATOR_AUTH
        else:
            raise TwilioSignatureError(
                "VOICE_AUTH_TOKEN_MISSING",
                "Twilio auth token is required for signature validation",
                http_status=503,
            )

    if not signature_header:
        raise TwilioSignatureError(
            "VOICE_SIGNATURE_MISSING",
            "Missing X-Twilio-Signature header",
            http_status=401,
        )

    check_timestamp_replay_skew(params)

    expected = compute_twilio_signature(url=url, params=params, auth_token=token)
    provided = str(signature_header).strip()
    if not hmac.compare_digest(expected, provided):
        raise TwilioSignatureError(
            "VOICE_SIGNATURE_INVALID",
            "Twilio signature validation failed",
            http_status=403,
        )