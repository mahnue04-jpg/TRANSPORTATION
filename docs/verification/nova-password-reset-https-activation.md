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

## Production gate
Never merge/deploy PR #458 merely because the focused tests pass.
Require review of remaining CI, verified provider/sender, isolated live send,
and explicit owner approval before production deployment.
Never send or paste the API key or reset link into a GitHub issue.
