# Marketing Lead Email — Environment Variables

Internal notifications for website lead forms use **environment variables only**.  
Do not hard-code SMTP credentials, API keys, or recipient addresses in source code.

## Required for email delivery

| Variable | Purpose |
|----------|---------|
| `MARKETING_SMTP_HOST` | SMTP hostname |
| `MARKETING_SMTP_PORT` | SMTP port (default `587` if unset in runtime code fallback) |
| `MARKETING_SMTP_FROM` | From address for internal notifications |
| `MARKETING_LEAD_NOTIFY_TO` | Internal inbox that receives new-lead alerts |

## Optional

| Variable | Purpose |
|----------|---------|
| `MARKETING_SMTP_USER` | SMTP username (if auth required) |
| `MARKETING_SMTP_PASSWORD` | SMTP password / app password |
| `MARKETING_SMTP_USE_TLS` | `1`/`true` to use STARTTLS (default on) |

## Behavior

- If email variables are **not** configured, form submissions still **save to the database** and return a successful confirmation to the user.
- Delivery failures are logged with safe metadata only (lead id, exception type). Credentials and message secrets are not logged.
- Configure these in the Render service environment before expecting live notifications.

## Related API

`POST /api/marketing/leads`
