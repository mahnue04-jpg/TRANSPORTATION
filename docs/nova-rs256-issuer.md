# Nova RS256 issuer

Status: development and testing only. This branch is not merged and not deployed. Live token issuance stays off. Production configuration, signing secrets, account rows, and the database are unchanged.

Casting draft PR #339 is a separate branch. This change does not edit it. The synthetic test imports that branch's verifier at commit `0f42164a`.

The review packet is `docs/nova-rs256-security-review.md`. Independent review has not been requested from the Synapse QA track and has not passed.

## Proposed identity

Current Nova access tokens are HS256. `JWT_ISSUER` and `JWT_AUDIENCE` default to empty, so live tokens do not carry an issuer or audience. Signup, password reset, and the production health check use `https://amicor-health-isf-py.onrender.com`.

| Claim | Proposed value | Why |
| --- | --- | --- |
| Issuer | `https://amicor-health-isf-py.onrender.com` | The live public Nova origin. |
| Audience | `https://amicor-health-isf-py.onrender.com` | No audience is configured. That origin is the stable identifier. |

This build refuses both values. A `.test` host is the only issuer a synthetic test can arm. `NOVA_RS256_ISSUER=approved`, `production`, or `on` stays off with reason `production_release_approval_required`. A production environment name stays off as well.

## Phases

`NOVA_RS256_ISSUER` defaults to off. Customer login keeps the existing HS256 function, including the same header and the same expiry number.

| Phase | New access tokens | JWKS | Existing HS256 sessions |
| --- | --- | --- | --- |
| off | HS256 | 404 | Still valid |
| publish-only | HS256 | Public RS256 keys | Still valid |
| issue | RS256, at most 60 minutes | Public RS256 keys | Still valid |

Keys exist only in process memory after a test calls the synthetic installer. There is no loader for `JWT_SECRET`, `SECRET_KEY`, a PEM environment variable, or a database. A flag without an installed 2048-bit key does not publish a JWKS and does not stop HS256 sign-in.

The active key signs new RS256 tokens. The previous key stays in the JWKS until `retire_previous_synthetic_key()`. `kid` is the RFC 7638 thumbprint. Rotation rejects a duplicate kid. Local verification and the Casting verifier both require RS256, the configured issuer, the configured audience, a whole-number expiry, and a subject that is not an email address. `none`, HS256 presented as RS256, and a `jwk` or `x5c` header fail closed. An RS256 header is never checked with the HMAC secret.

Refresh tokens stay opaque random values.

## Rollback

1. Set `NOVA_RS256_PHASE=publish-only`. New sessions are HS256 again. Tokens already signed with RS256 still verify until they expire.
2. After those access tokens are gone, set the phase to `off`. The JWKS returns 404.
3. Leave `NOVA_RS256_ISSUER` unset to return to today's code path.

HS256 sessions do not depend on the JWKS. An opaque refresh token can mint a new HS256 access token after rollback.

## Casting verifier

The pinned verifier accepts a synthetic `.test` issuer only. It still refuses `amicor-health-isf-py.onrender.com` and every `onrender.com` host. A verified subject can be recorded by that verifier's in-memory membership helper as `local_id`, `issuer`, and `subject`. The row has no password and no email. This branch does not write `platform_users` and does not import accounts.

The verifier may cache a JWKS key for 10 minutes. Keep a previous `kid` published until access tokens that used it have expired and that cache window has passed.

## Still required before a production release

This is a request for a later review, not approval to enable the issuer.

- Approve this design and the synthetic evidence.
- Approve a production key store outside the repository and a rotation ceremony. This branch has neither.
- Approve activating the proposed issuer and audience on main Nova.
- Approve a separate Casting change that can trust that issuer. The current verifier will keep refusing it.
- Publish the JWKS before issuing RS256 tokens.
- Keep Casting reads, writes, media, email, SMS, WhatsApp, and payments off until their own approval.

No production merge, deploy, secret rotation, account migration, or fee is part of this change.
