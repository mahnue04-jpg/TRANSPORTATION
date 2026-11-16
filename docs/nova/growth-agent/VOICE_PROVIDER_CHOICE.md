# Voice provider choice — Twilio

## Decision

**Twilio** is the inbound voice webhook provider for Nova Growth Agent
receptionist pilot.

## Rationale

1. **Same stack as Health ISF SMS** — `backend/app/modules/health_isf/notifications.py`
   already sends operational SMS via Twilio when `TWILIO_*` environment variables
   are set. Operations and security teams already know Twilio credentials,
   signature validation, and audit patterns.
2. **No second telephony vendor** — Avoids parallel billing, webhook validators,
   and on-call runbooks for another provider during the pilot.
3. **Signature parity** — Twilio's `X-Twilio-Signature` HMAC-SHA1 scheme is
   implemented in `voice/twilio_signature.py` without requiring the Twilio SDK.

## Non-goals (pilot constraints)

| Flag | Value | Meaning |
|------|-------|---------|
| `REAL_VOICE` | always `False` | No live PSTN in this repo revision |
| `voice_simulator_enabled()` | env-gated | Labeled simulator only (`NOVA_GROWTH_AGENT_VOICE_SIMULATOR`) |

## Replay protection

1. **Primary** — `GaVoiceWebhookEvent` unique `(provider, event_id)` dedupe;
   duplicates return `status: duplicate` without reprocessing.
2. **Secondary** — When Twilio sends timestamp-like fields, reject skew > 5 minutes
   (`twilio_signature.check_timestamp_replay_skew`).

## Tenant resolution

Never trust webhook-supplied `organization_id`. Resolve tenant only via
`GaVoiceAgentMapping` on the called number (`voice/inbound.resolve_tenant_from_called_number`).