"""Nova Growth Agent inbound voice (Twilio).

**Provider choice — Twilio**

Health ISF already sends operational SMS through Twilio in
``app.modules.health_isf.notifications.py`` (same company stack, shared
operational patterns). Inbound voice webhooks therefore use Twilio's
``X-Twilio-Signature`` HMAC validation rather than adding a second telephony
vendor.

``REAL_VOICE`` remains hard-coded ``False`` in ``flags.py``; only the labeled
simulator exercises these code paths without proving live phone operation.
"""

from app.core.nova.growth_agent.voice.inbound import (
    GrowthVoiceOps,
    process_inbound_event,
    receive_inbound_webhook,
    record_webhook_event,
    resolve_tenant_from_called_number,
)
from app.core.nova.growth_agent.voice.simulator import (
    craft_signed_simulator_webhook,
    run_labeled_simulator_journey,
)
from app.core.nova.growth_agent.voice.twilio_signature import (
    SIMULATOR_AUTH,
    compute_twilio_signature,
    validate_twilio_signature,
)

__all__ = [
    "GrowthVoiceOps",
    "SIMULATOR_AUTH",
    "compute_twilio_signature",
    "craft_signed_simulator_webhook",
    "process_inbound_event",
    "receive_inbound_webhook",
    "record_webhook_event",
    "resolve_tenant_from_called_number",
    "run_labeled_simulator_journey",
    "validate_twilio_signature",
]