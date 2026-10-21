# Casting trusted Nova sign-in

Status: design only. Shared sign-in is off. This document does not enable it, import accounts, or change production.

Draft pull request #339. Preview only: `amicor-health-isf-pr-339` and `amicor-casting-staging-db`. Casting reads, writes, media, email, SMS, and WhatsApp stay disabled.

## What the preview 401 is

`POST /api/auth/login` on the preview checks `platform_users` in the database that preview process is using. A missing account and a password mismatch return the same HTTP 401, `Invalid email or password`. The casting sandbox posts that form to the preview's `/api/auth/login`.

The sandbox says: "This preview keeps its own accounts. A main Nova sign-in is not in this database." That sentence matches the code. A 401 from that form is the local check. It is not a diagnosis that the owner password is wrong, and it is not a request to retry.

Access tokens are HS256. `_jwt_verify` in `backend/app/auth.py` checks the HMAC with this process's `JWT_SECRET`, or `SECRET_KEY` when `JWT_SECRET` is empty. It then checks `exp` and, only if set, local `JWT_ISSUER` and `JWT_AUDIENCE` equality. It does not fetch a key, call another host, or accept a token signed with a different secret.

## Supported path

No supported shared-auth path exists.

Searched this repository for a JWKS URL, OIDC discovery (`.well-known/openid-configuration`), an OAuth authorize endpoint, and a token-introspection endpoint used for Nova user login. None exist. `JWT_ISSUER` and `JWT_AUDIENCE` are optional string checks after the local HMAC. They do not identify main Nova as a trusted issuer. Ops "federation" routes coordinate regions. They are not sign-in. Mailbox code reuses an Outlook refresh token and does not add a Nova identity provider. Upwork OAuth is a separate work-revenue note.

The exact blocker: a main Nova access token can be checked on this preview only by sharing the HMAC signing secret, and a main Nova password can succeed only if that account row is in this database. Both are out of bounds. There is no public key or introspection endpoint to trust instead.

`backend/app/core/casting_trusted_signin.py` records that decision. `trusted_signin_decision()` returns `supported: false` and `enabled: false`. Setting `NOVA_CASTING_TRUSTED_SIGNIN`, an issuer, an audience, or a JWKS URL does not change that. The function does not read `DATABASE_URL`, `JWT_SECRET`, or `SECRET_KEY`.

## Safe design, after a separate approval

Do not implement this until the owner decisions below are answered. The preview database, signing secret, and password hashes stay independent of production.

1. Main Nova publishes a public verification method. Preferred: sign access tokens with an asymmetric algorithm and publish a JWKS at an HTTPS URL on the production host. Alternative: an introspection endpoint that returns only subject, expiry, issuer, and audience. The preview never receives the private key, `JWT_SECRET`, or `SECRET_KEY`.
2. The preview trusts one named issuer and one audience. It checks signature, expiry, issuer, and audience. A failed check stays a 401 and does not fall back to the production database.
3. A verified token does not copy a production user row and does not copy a password hash. If a later approval allows a local membership, that row is created on the preview with a new id and no imported secret. Until that approval, verification alone does not open Casting.
4. Casting workflow flags stay off. Trusted sign-in does not set `NOVA_CASTING_STAGING_READS` or enable applications, media, email, SMS, or WhatsApp.
5. The browser keeps one sign-in control. A 401 clears `amicor_nova_creative_token` and the refresh value and shows Sign in. The page does not invent "Nova rejected these sign-in credentials" or "Request error".

## Owner decisions required

- Approve a public verification method on main Nova that does not copy `JWT_SECRET`, `SECRET_KEY`, `DATABASE_URL`, passwords, or account rows.
- Name the issuer URL and audience the preview may accept.
- Choose whether a verified subject may create a new local preview membership with no imported password, or must stay request-only.
- Keep casting reads, writes, media, email, SMS, and WhatsApp disabled until a separate approval.
- Leave the preview on `amicor-casting-staging-db` and leave production services unchanged.

No owner login retry is required for this design.
