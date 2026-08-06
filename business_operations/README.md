# Amicor Business Operations — Phase 3

Operational kits for Minnesota launch outreach. These documents support recruitment and provider partnership work outside the ride-engine codebase.

## Folders

| Folder | Purpose |
|--------|---------|
| `driver_recruitment/` | Driver recruitment kit, checklists, FAQs, social posts |
| `provider_outreach/` | Provider partnership outreach kit and scripts |
| `email_templates/` | Ready-to-use acknowledgment and follow-up email drafts |

## Website routes

| Audience | Public page | Application / workspace |
|----------|-------------|-------------------------|
| Drivers | `/for-drivers` | `/platform-ops/driver-apply`, `/app/mobile` |
| Providers | `/for-providers` | `/app/providers` |
| General | `/contact` | — |

## Lead capture

Website forms post to `POST /api/marketing/leads`.  
See `MARKETING_LEAD_EMAIL_ENV.md` for optional SMTP notification configuration.
