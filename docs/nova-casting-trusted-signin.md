# Casting trusted Nova sign-in

Status: staging verifier implemented. Main Nova is not activated. Draft pull request #339.

The owner approved the consumer side of the design. This branch verifies RS256 tokens for a synthetic staging issuer and can create a local membership for a verified subject in tests. It does not change production signing, import accounts, or turn on Casting workflows.

## Deployment identity

Main Nova's public origin is `https://amicor-health-isf-py.onrender.com`. Signup and password reset use that URL, and the production health check is served there. The service name in this repo is `amicor-health-isf-py`.

Current access tokens are HS256. The payload is `sub` (the platform user id), `email`, `role`, `organization_id`, `auth_version`, and `exp`. `JWT_ISSUER` and `JWT_AUDIENCE` default to empty, so live tokens do not carry an issuer or audience.

Proposed values, not activated:

| Claim | Proposed value | Why |
| --- | --- | --- |
| Issuer | `https://amicor-health-isf-py.onrender.com` | The live public origin. |
| Audience | `https://amicor-health-isf-py.onrender.com` | No audience is configured. The same origin is the only stable identifier. |

No other issuer or audience was invented for production. The preview host is not an issuer.

## What is implemented

`backend/app/core/casting_trusted_signin.py` verifies a token only when all of these hold:

- `NOVA_CASTING_TRUSTED_SIGNIN` is exactly `staging`.
- The process environment names agree on one non-production allowlisted value.
- The issuer is an `https` host ending in `.test`. Production hosts and any `onrender.com` host are refused.
- The audience matches the configured audience exactly. A list is rejected.
- The signature is RS256 with a JWKS key of at least 2048 bits. `none`, HS256, and a `jwk` or `x5c` inside the token header are rejected before a fetch.
- `exp` is present, not expired (60 second skew), and the token lifetime is at most 60 minutes.
- `sub` is a stable id, not an email address. Claims are read only after the signature matches.
- OIDC discovery is used when a JWKS URL is not set. The discovery `issuer` must match, and `jwks_uri` must be `https` on that same host. Redirects are not followed.
- An unknown `kid` refreshes the JWKS once. A failed fetch does not fall back to a stale key or to the local HMAC secret.

`GET /api/nova/casting/trusted-signin` reports this status and does not fetch a key. `POST /api/nova/casting/trusted-signin/session` returns 403 while the staging configuration is absent. On the preview that is the expected state.

## Staging membership

A verified subject can get one local row in a disposable sqlite table used by tests: `local_id`, `issuer`, `subject`, `created_at`. The same subject returns the same local id. A different subject gets a different id. The table has no password and does not store email. It is not `platform_users`. The deployed preview does not open this table; the default store is unconfigured, so a session cannot be saved on the preview until a later approval attaches the staging database.

## Still required before a real Nova sign-in

Main Nova still signs with HS256 and does not publish `/.well-known/openid-configuration` or a JWKS. This branch does not change that.

Owner decision: approve a separate change on main Nova to publish an RS256 key and a JWKS at `https://amicor-health-isf-py.onrender.com`, with issuer and audience both set to that origin. Confirm those two values before activation. Until that approval, the preview cannot accept a main Nova token, and the owner does not need to retry a password.

Casting reads, writes, media, email, SMS, WhatsApp, and payments stay off. Production services and the preview database stay unchanged.
