# AMICOR Nova password recovery: HTTPS mail activation checklist

Status: draft implementation in PR #458. This file is guidance, not evidence of a successful live send.

## Why this is required
The production password-reset request logged `password_reset_email_skipped reason=not_configured`.
The API intentionally returns the same generic response whether an account is present or not.
Never interpret HTTP 200 from `/api/auth/forgot-password` as proof that email was delivered.

## Prerequisites (owner-controlled)
1. Create or identify an authorized SendGrid account; review provider terms, costs, and sender-verification requirements.
2. Verify an email sender identity/domain that the organization controls.
3. Create a SendGrid API key with only the Mail Send permission; do not put it in GitHub, screenshots, chat, or logs.
4. Add these secrets/settings in the appropriate **isolated staging** Render service:
   - `SENDGRID_API_KEY`: private provider API key.
   - `SENDGRID_FROM_EMAIL`: verified sender address.
   - `AMICOR_PUBLIC_BASE_URL`: staging public HTTPS origin matching the environment.
   - `APP_ENV`: staging/test value, as appropriate for the deployment.
5. Do not enable `AMICOR_PASSWORD_RESET_TEST_CAPTURE` in production.

The code uses SendGrid's HTTPS `POST https://api.sendgrid.com/v3/mail/send`
when both SendGrid variables are configured. Without them, existing SMTP settings
may be used. SMTP connectivity can be restricted by the hosting plan.

## Verification gates
- Focused automated tests pass, including generic responses, expired tokens,
  single-use consumption, old-session revocation, and preserved role/organization.
- Authorized staging test account requests a reset; logs show only an acceptance
  or sanitized failure event, never an email address, API key, or reset token.
- Confirm the provider actually accepts the request (HTTP 202), and separately
  confirm inbox receipt: provider acceptance is not guaranteed delivery.
- Reset link points to staging, uses HTTPS, and expires in one hour.
- Password changes successfully; reuse of link fails; prior login sessions are revoked.
- Do not test with a production administrator account until staging passes.
- Verify account access and projects after owner-approved production release.


## Verified draft state and remaining release gates (November 2026)
- **PR status:** #458 remains open, draft, and unmerged. The Render preview is **suspended**; production was not deployed.
- **Latest verified password-reset CI:** Commit `7af0cf323c15f2977cdcd5abda703afb246f70e1` passed both password-reset jobs (offline and disposable PostgreSQL). The suite covers URL safety, explicit staging public URL, delayed-email credential-version changes, pending token activation, and test-only plaintext capture disabled in staging. Jekyll passed; the broader Render diagnostic and Work & Revenue checks had not finished at the last verified check.
- **Token activation fixed in draft:** New reset tokens are created with already-expired `expires_at` until the provider accepts sending. The accepted-email finalizer locks the account, activates the token, and retires active competing tokens. Delayed-send, interrupted-send, and overlapping pending-token scenarios have passed offline/disposable PostgreSQL tests. This is *code/CI evidence only*, not live delivery evidence.
- **SMTP log redaction fixed in draft:** Errors log a sanitized warning rather than full exception contents. The corresponding offline regression passed.
- **Isolation blocker:** Preview `DATABASE_URL` was copied from another environment and has not been verified as isolated. **Never resume preview or trigger live reset requests against it** until its database target is verified. Do not repurpose `amicor-prod` or `amicor-casting-staging-db`. Render already rejected a second free database; obtain explicit owner consent before creating anything paid.
- **Sender verification blocker:** The SendGrid domain/sender and an API key were prepared, but the API key's Mail Send-only scope and preview environment settings have not been independently confirmed. Never expose keys or reset URLs in issues, chats, screenshots, or logs.
- **Live verification blocker:** No successful SendGrid HTTP 202 response from an isolated staging service, actual inbox receipt, staging-link HTTPS/expiry, or end-to-end staging reset has been established.
- **Coverage limitation:** Automated tests do not prove behavior for all overlapping HTTP requests, provider timing, infrastructure failures, or delivery-order reversals. Maintain owner-controlled release gating.



## Safe staging isolation verification (no live traffic)
1. Keep PR #458 suspended while checking settings. Inspect the **preview service** in the Render dashboard, not its parent production service.
2. In its Environment settings, inspect only the `DATABASE_URL` destination (hostname/database identity) **privately**. Do not share or log connection credentials, the full URL, or any SendGrid secret.
3. Confirm the destination is a dedicated disposable staging database, clearly different from both `amicor-prod` and `amicor-casting-staging-db`. A database name alone is not sufficient proof if the hostname or instance still points to production.
4. If the destination cannot be conclusively identified, **stop**. Never run migrations, startup table creation, password-reset HTTP requests, or a live SendGrid attempt against that preview.
5. Privately confirm `AMICOR_PUBLIC_BASE_URL` is the preview HTTPS origin and the SendGrid API key has only Mail Send permission. Confirm the test-token capture flag is off outside isolated tests.
6. Only after an isolated database, staging URL, and secret scope have been verified should a separately owner-approved staging resume and one disposable account/inbox delivery test be considered.
7. Capture evidence as non-sensitive status values only: isolated database confirmed (yes/no), provider accepted (yes/no), inbox delivered (yes/no), link expiry and one-time behavior passed (yes/no). Never record keys, email addresses, full database URLs, or token-bearing links.

**Current connector limitation:** The available Render service detail shows suspension and service metadata, but cannot independently reveal or verify the preview's effective `DATABASE_URL`. This gate remains **blocked**, not passed.

## Production gate
Never merge/deploy PR #458 merely because the focused tests pass.
Require review of remaining CI, verified provider/sender, isolated live send,
and explicit owner approval before production deployment.
Never send or paste the API key or reset link into a GitHub issue.
