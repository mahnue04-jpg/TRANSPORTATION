# Threat model — Nova Growth Agent MVP

## Assets

- Tenant business profiles, FAQs, conversation transcripts
- Contact identities (email/phone) after consent
- Consent records and audit history
- Widget installation signing secret
- Appointment calendar integrity

## Trust boundaries

| Boundary | Control |
|----------|---------|
| Browser → owner API | JWT + org scope deny-by-default |
| Browser → widget API | HMAC install token + domain allowlist + rate limit |
| Worker/provider | Mock only; live flags hard-off |
| Cross-tenant DB | Every query filters `organization_id` |
| Logs/observability | PII/secret redaction helpers |

## Abuses considered

1. **Forged widget token** — HMAC verification + token hash match + install active check  
2. **Cross-origin embed** — Origin/Referer domain allowlist  
3. **XSS via chat** — HTML stripped/escaped before persistence  
4. **Prompt injection** — FAQ grounding only; injection patterns blocked; no refunds/contracts tools  
5. **Spam** — per-installation rate limit  
6. **Consent bypass** — marketing requires opt-in; STOP suppresses; chat ≠ marketing permission  
7. **Double booking** — unique slot constraint + in-process lock + overlap checks  
8. **Secret leakage** — no plaintext secrets in `integration_connections`; redacted audits  
9. **CSRF on owner APIs** — Bearer token required (cookie-only not sufficient for these routes)  
10. **Feature enablement via headers** — `HEADER_CAN_ENABLE_LIVE=False`

## Residual risks / blocked until owner+legal

- Live SMS/email/voice providers and TCPA/CAN-SPAM counsel review  
- External Google/Microsoft OAuth calendar writes  
- Production DDL apply (migration currently stamp-only in prod)  
- Commercial Stripe subscriptions (unlaunched plans only)
