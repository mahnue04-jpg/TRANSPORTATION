# Security review packet: Nova RS256 issuer and Casting verifier

Status: ready for an independent reviewer. Review has not been requested from the Synapse QA track, and review has not passed. This packet does not create a production key, change production configuration, merge, or deploy.

| Item | Value |
| --- | --- |
| Issuer implementation | `cfbb54ab` on `cursor/nova-rs256-issuer-6b16` |
| This packet | this file, on that same branch, directly after `cfbb54ab` |
| Casting verifier | `0f42164a` on `cursor/casting-auditions-pilot-e1ae`, pinned in this branch at `backend/tests/support/casting_trusted_signin_0f42164a.py` |
| Proposed issuer | `https://amicor-health-isf-py.onrender.com` |
| Proposed audience | `https://amicor-health-isf-py.onrender.com` |
| Live state | Both values are refused. Synthetic tests use `https://signin.nova-staging.test` only. |

The proposed audience is the public Nova origin because current access tokens leave `JWT_AUDIENCE` empty. No second audience was invented.

## What this packet is allowed to claim

A synthetic `.test` issuer can mint an RS256 token, publish a JWKS, and the pinned Casting verifier can check the signature, issuer, audience, expiry, and `kid`. The same subject gets one local membership id. The row has no password and no email. Existing HS256 tokens still verify when the new issuer is off, in publish-only, and after rollback.

## What this packet does not claim

The owner's Nova account cannot sign into Casting. Production still signs HS256 and its `/.well-known/jwks.json` returns 404. The discovery URL on that host returns the website HTML, not an OIDC document. The preview at `0f42164a` reports trusted sign-in disabled and `production_issuer_activated` false. No reviewer has accepted this design.

## Threat model

Assets: Nova access tokens, the HMAC signing secret, a future RS256 private key, Casting membership rows, and the separation between the production database and the preview database.

Attackers considered: a caller who can hit the preview, a holder of a stolen access token, a process that is given the wrong environment variables, and a key that is retired while a verifier still remembers it.

Out of scope for these commits: production key generation, production deploy, account import, Casting reads and writes, media, email, SMS, WhatsApp, and payments.

| Threat | Current behavior |
| --- | --- |
| Use the production HMAC secret as the RS256 private key | The issuer module does not read `JWT_SECRET`, `SECRET_KEY`, or `DATABASE_URL`. Tests check that those names are absent from the module. |
| Accept a production-host issuer | The issuer refuses `onrender.com` and the proposed origin. The verifier refuses the same hosts, including when staging flags point at them. |
| Algorithm confusion | An RS256 header is verified with the RSA public key only. It is not passed to the HMAC check. An HS256 header stays on the existing HMAC path. `alg=none` fails that HMAC check. |
| Header key injection | `crit`, `jwk`, and `x5c` are rejected before the signature is trusted. |
| Unsigned claim swap | Issuer, audience, expiry, and subject are read after the signature check. |
| Small or swapped key | Install and rotation reject a key under 2048 bits and a duplicate `kid`. The JWKS contains `n` and `e` only. |
| Failed key fetch | The verifier raises. It does not fall back to a stale JWKS or to the HMAC secret. |
| Account import | Membership stores `local_id`, `issuer`, and `subject`. Email in the Nova token is not written there. |

Residual risk: there is no `jti` and no one-time-use store. A stolen bearer token works until it expires. Replay of the same subject returns the same local id, so replay does not create a second membership. The token is not sender-constrained.

## Issuer and audience

Synthetic mode requires `NOVA_RS256_ISSUER=synthetic`, one non-production environment name, an `https` origin whose host ends in `.test`, and an audience with no whitespace. The audience must not be the proposed production origin.

Any other mode, including `approved`, `production`, and `on`, stays off with reason `production_release_approval_required`. A production environment name stays off even if the issuer URL is a `.test` host. Conflicting environment names stay off.

The issuer overwrites caller-supplied `iss`, `aud`, `iat`, and `exp`. The subject must match `[A-Za-z0-9._:-]{1,200}` and must not contain `@`.

## Expiry and replay

Both sides require a whole-number `exp`. Floats and booleans are rejected. The lifetime cap is 3600 seconds. Clock skew is 60 seconds. A token is still accepted at `exp + 60` and rejected at `exp + 61`. If `iat` is present, `exp - iat` must be greater than 0 and at most 3600. If `nbf` is present, it is enforced. The issuer always sets `iat` and does not set `nbf`.

The issuer caps a longer requested lifetime at 3600 rather than emitting a token the verifier would reject. HS256 tokens are unchanged and can still carry the existing expiry value.

Replay window: the full remaining lifetime, at most 60 minutes plus 60 seconds of skew. Logout does not revoke an RS256 access token in these commits. Refresh tokens stay opaque random values and are not JWTs.

## Key rotation and cache

`kid` is the RFC 7638 thumbprint of the public JWK. New tokens use the active key. The previous key remains in the JWKS until `retire_previous_synthetic_key()`. Rotation of the same key is rejected.

The Casting `KeyRing` caches keys for 600 seconds. Inside that window, a retired `kid` can still verify. The test advances the clock to 599 seconds and still accepts the retired key, then to 600 seconds and gets reason `key`. A failed refresh does not restore an older document.

Operational rule for a later rollout: keep a previous `kid` published until access tokens that used it have expired and the 10 minute cache has lapsed. Do not retire it in the same step that stops issuing with it.

## Validation failures

Casting reasons: `malformed`, `algorithm`, `key`, `signature`, `issuer`, `audience`, `expired`, `subject`, `discovery`, `membership`.

Local RS256 details, mapped to HTTP 401: `Invalid token format`, `Token signature invalid`, `Token payload invalid`, `Token expired`, `Token issuer invalid`, `Token audience invalid`.

An unknown `kid`, a bad signature, an embedded `jwk`, a wrong audience, an email-shaped subject, and an HS256 token presented to the Casting verifier are rejected. The HS256 rejection reason is `algorithm`.

## HS256 compatibility

When `NOVA_RS256_ISSUER` is unset, `create_access_token` does not call the RS256 issuer. The test freezes time and checks the token bytes against the existing HS256 signer. The header algorithm remains `HS256`.

An HS256 token created before the synthetic issue phase still verifies during publish-only, during issue, and after rollback. An RS256 token is rejected once the phase is `off`, because the RSA key is ignored while the gate is closed. The HMAC secret is not used to check that RS256 token.

Customer sign-in on production does not load this branch. Production deploy is still `3ad96ec6` on `main`.

## Rollback

1. `NOVA_RS256_PHASE=publish-only`. New access tokens are HS256. Already issued RS256 tokens still verify while the JWKS is published.
2. After those access tokens expire, set the phase to `off`. The JWKS returns 404.
3. Unset `NOVA_RS256_ISSUER` to leave the historical HS256 function as the only path.

HS256 sessions do not depend on the JWKS. An opaque refresh token can mint a new HS256 access token after rollback. Rollback to `off` rejects outstanding RS256 access tokens immediately.

## Test evidence

Command, run from `backend` on this commit:

`python3 -m pytest tests/test_nova_rs256_issuer.py tests/test_nova_rs256_casting_verifier.py -q`

Result: 9 passed. The ninth test is `test_disposable_membership_survives_reopen_without_a_password`.

Covered behavior:

- Default gate off, and HS256 token bytes unchanged.
- `approved`, production environment, the production origin, and conflicting environment names cannot arm the issuer.
- A missing key or a 1024-bit key does not switch sign-in off HS256.
- Publish-only, issue, rollback, rotation, and retirement.
- Expiry at the 60 second skew boundary, a tampered signature, and an embedded `jwk`.
- The pinned verifier still refuses the production origin.
- Discovery, JWKS, one membership per subject, HS256 rejected, wrong audience rejected.
- A retired key survives inside the 10 minute cache and fails after it.
- A disposable sqlite membership returns the same local id after the connection is reopened, and the table has no password or email column.

These tests do not call production, do not read a password, and do not import account rows.

## Staged synthetic proof plan

This plan stays inside development and testing. It is not an owner login test.

Done locally in this branch:

1. Arm only `https://signin.nova-staging.test`.
2. Install a 2048-bit key in memory.
3. Issue an RS256 token for subject `11111111-1111-4111-8111-111111111111`.
4. Fetch `/.well-known/openid-configuration`, then the JWKS on that same host.
5. The pinned verifier returns that subject. A second call returns the same local id.
6. Rotate, keep the old token inside the cache window, then reject it after 600 seconds.
7. Reopen the sqlite file and read the same local id back.
8. Turn the phase off and confirm the JWKS is 404 and the earlier HS256 token still verifies.

Not done, and not available on the current preview:

- The preview route's membership store is unconfigured. A staged session there would fail closed even if the synthetic flags were set.
- The verifier accepts only a `.test` host. The preview's `onrender.com` host cannot be the issuer.
- No preview environment change and no preview deploy is part of this packet.

The next executable staging step, after a reviewer accepts this packet and the owner asks for it, is a disposable store on the preview only, aimed at a `.test` issuer, followed by the eight checks above and a process restart. That run still uses a synthetic subject. It does not submit the owner's Nova session.

## Production key options

No key was generated or stored for this packet. These are options for a later approval.

Recommended shape:

- Generate the RSA key outside the repository, on a machine or dashboard action that does not print the private key into Slack, Git, or logs.
- Store the private key in a file outside the repo, mode `0600`, owned by the service account. Render's secret-file mount is the closest fit. Do not reuse `JWT_SECRET` or `SECRET_KEY`. Do not put the PEM in the database.
- Publish only the public JWK. Keep the previous private key until issued tokens and the 10 minute verifier cache have expired, then delete it.
- Startup behavior to implement later, not in this commit: if the phase is `issue` or `publish-only` and the key file is missing, unreadable, under 2048 bits, or not RSA, readiness fails and no RS256 token is issued. HS256 verification of tokens already issued stays available so existing sessions are not destroyed. A flag other than an explicit future approval value continues to leave RS256 off.
- The stricter alternative, exiting the process when the key is bad, would take customer login down with it. This packet does not recommend that.

A plain environment variable is the weaker storage option. It is easier to copy into a log or a screenshot. Use it only if a secret file is unavailable, and still never print the value. This commit does not add either loader.

## Decisions that still require a separate owner approval

1. Create the production RS256 key.
2. Enable production RS256 issuance.
3. Allow the Casting verifier to trust `https://amicor-health-isf-py.onrender.com`.
4. Merge to `main` or deploy production.

Development and testing of the synthetic path does not include those four actions.

## Reviewer access

Independent review was not requested, and it has not passed.

The repository collaborator list contains `mahnue04-jpg` only. There is no `CODEOWNERS` file. This session cannot open a pull request for `cursor/nova-rs256-issuer-6b16` because GitHub requires a collaborator. Issue #312 is the independent QA track for Synapse #311, and its body limits that work to Synapse mobile, desktop, and 15-language acceptance. No QA agent is assigned there. This packet was not sent to that issue, so that lane was not interrupted.

A second reviewer needs collaborator access, or the owner reviews this file directly. Until one of those happens, this document is a request for review, not a passed review.
