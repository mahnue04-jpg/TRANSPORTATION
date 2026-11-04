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


## Current release blockers (reviewed November 2026)
- PR #458 Render preview is **suspended**. Its `DATABASE_URL` was copied from another environment; its isolation is unverified. Do not resume or run real password-reset requests there.
- Render rejected creation of a second free PostgreSQL instance because the workspace already has its one active free instance. Do not modify `amicor-prod`, borrow `amicor-casting-staging-db`, or provision a paid database without owner approval.
- SendGrid verified sender and an API key were prepared by the owner. Permission scope (Mail Send only) and saved preview configuration must still be independently verified before use.
- **Verified automated milestone:** Commit `16c611ec78e7963af88a6eb178eddb007c11c48c` passed all four GitHub workflows, including both password-reset CI jobs. The disposable PostgreSQL 18 job covered accepted-email finalizations with 2, 3, and 5 simultaneous contenders, plus concurrent attempts to consume the same token. The offline job covered the password-reset lifecycle and mocked email outcomes. No Render production or Casting database was used.
- **Newly identified release blocker — token activation timing:** `request_password_reset` currently commits a reset token with `used_at=NULL` and a future expiration **before** SendGrid accepts the message. During a slow or interrupted send, that token is temporarily eligible for password reset. A failed send later deletes it, but process crashes or race conditions can strand an unsent token. Before release, implement an explicit pending-versus-active state or equivalent transactional activation so a reset token cannot be consumed until provider acceptance. Verify failed, delayed, interrupted, and simultaneous deliveries in isolated tests. Do not infer that passing existing concurrency tests resolves this risk.
- **Verified mixed-outcome milestone:** Commit `25c775555974b8f0fabf72a9d36a428b0c2d30cb` passed both password-reset jobs, including PostgreSQL tests for one accepted/one failed and both failed attempts. The broader CI checks were still pending at that check.
- **Remaining concurrency coverage limitation:** These tests do **not** run the complete overlapping HTTP requests with real email-provider responses, delivery-order reversals, process crashes, or real inbox delivery. Account and token lifecycle correctness must be reviewed before release; passing these bounded tests is not a blanket security guarantee.
- Do not merge, deploy, resume staging, send a real password-reset email, or change any real administrator password until these blockers are resolved.

## Production gate
Never merge/deploy PR #458 merely because the focused tests pass.
Require review of remaining CI, verified provider/sender, isolated live send,
and explicit owner approval before production deployment.
Never send or paste the API key or reset link into a GitHub issue.
