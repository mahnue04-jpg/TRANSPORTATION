"""SIMULATED inbound voice helpers — never proof of live telephony.

All payloads include ``meta.simulated=true`` and ``simulated=true`` at the
top level where applicable. These utilities craft signed webhook bodies for
tests and local demos only; they do not place or receive real phone calls.
"""

from __future__ import annotations

from typing import Any

from sqlalchemy.orm import Session

from app.core.nova.growth_agent.flags import REAL_VOICE, voice_simulator_enabled
from app.core.nova.growth_agent.voice.inbound import GrowthVoiceOps, receive_inbound_webhook
from app.core.nova.growth_agent.voice.twilio_signature import SIMULATOR_AUTH, compute_twilio_signature

SIMULATOR_LABEL = "SIMULATED_VOICE_WEBHOOK"


def _require_simulator() -> None:
    if REAL_VOICE:
        raise RuntimeError("REAL_VOICE is hard-off; simulator cannot run in live voice mode")
    if not voice_simulator_enabled():
        raise RuntimeError("NOVA_GROWTH_AGENT_VOICE_SIMULATOR must be enabled for simulator helpers")


def craft_signed_simulator_webhook(
    *,
    url: str,
    to_number: str,
    from_number: str = "+15555550100",
    event_type: str = "faq_answer",
    extra: dict[str, Any] | None = None,
    auth_token: str = SIMULATOR_AUTH,
) -> dict[str, Any]:
    """Build a Twilio-shaped POST body and matching ``X-Twilio-Signature``."""
    _require_simulator()
    params: dict[str, Any] = {
        "To": to_number,
        "From": from_number,
        "CallSid": f"SIM{event_type[:8]}-{to_number[-4:]}",
        "CallStatus": "in-progress",
        "event_type": event_type,
        "event_id": None,
        "simulated": True,
        "meta": {"simulated": True, "label": SIMULATOR_LABEL},
    }
    if extra:
        params.update(extra)
    if not params.get("event_id"):
        params["event_id"] = f"sim:{params['CallSid']}:{event_type}:{params.get('SequenceNumber', '0')}"
    signature = compute_twilio_signature(url=url, params=params, auth_token=auth_token)
    return {
        "params": params,
        "signature": signature,
        "auth_token": auth_token,
        "meta": {"simulated": True, "label": SIMULATOR_LABEL},
    }


def run_labeled_simulator_journey(
    db: Session,
    *,
    url: str,
    to_number: str,
    growth_ops: GrowthVoiceOps,
    steps: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """Drive a scripted multi-step SIMULATED call flow (no live phone)."""
    _require_simulator()
    outcomes: list[dict[str, Any]] = []
    for step in steps:
        event_type = str(step.get("event_type") or "faq_answer")
        crafted = craft_signed_simulator_webhook(
            url=url,
            to_number=to_number,
            from_number=str(step.get("from_number") or "+15555550100"),
            event_type=event_type,
            extra={**step, "meta": {"simulated": True, "label": SIMULATOR_LABEL}},
        )
        params = crafted["params"]
        for key, val in step.items():
            if key not in {"event_type", "from_number"}:
                params[key] = val
        params["meta"] = {"simulated": True, "label": SIMULATOR_LABEL}
        params["simulated"] = True

        result = receive_inbound_webhook(
            db,
            url=url,
            params=params,
            signature_header=crafted["signature"],
            auth_token=crafted["auth_token"],
            growth_ops=growth_ops,
            simulator_mode=True,
        )
        result["meta"] = {"simulated": True, "label": SIMULATOR_LABEL}
        outcomes.append(result)
    return outcomes