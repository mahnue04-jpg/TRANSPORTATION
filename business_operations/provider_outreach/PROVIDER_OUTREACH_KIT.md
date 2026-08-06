# Provider Outreach Kit

**Entity:** Amicor Health ISF LLC  
**Market:** Minnesota  
**Audience:** Healthcare and community organizations coordinating non-emergency medical transportation (NEMT)  
**Purpose:** Master overview for provider partnership outreach, discovery, intake, and onboarding

---

## What Amicor Is

Amicor Health ISF LLC is an **AI-enabled NEMT coordination and operations platform** preparing for Minnesota launch. Amicor helps healthcare and community organizations:

- Submit and manage transportation requests in one provider-ready workspace
- Coordinate available qualified drivers through operations and platform tools
- Monitor trip progress through a documented ride workflow
- Review completed trip records for operational and administrative follow-up

Amicor focuses on practical transportation operations. Outreach materials must not invent regulatory approvals, insurance guarantees, capacity guarantees, or government contract status.

---

## Public Links

| Surface | Path | Use |
|---------|------|-----|
| Provider marketing page | `/for-providers` | Partnership overview, use cases, FAQ, interest form |
| Provider workspace | `/app/providers` | Authorized staff access after workspace provisioning |

Use `{{provider_link}}` in messages. Prefer `/for-providers` for early outreach and consultation requests; use `/app/providers` when discussing workspace access for authorized partners.

---

## Target Segments

Outreach should speak to the operational reality of each setting while keeping claims consistent.

| Segment | Typical transportation needs | Outreach emphasis |
|---------|------------------------------|-------------------|
| Hospitals | Discharge, follow-up appointments, specialty visits | Timing alignment, status visibility, care-management coordination |
| Clinics | Appointment access, specialty referrals, recurring visits | Missed-appointment reduction through better logistics coordination |
| Dialysis centers | Standing/recurring pickup and return patterns | Recurring schedule coordination and exception visibility |
| Behavioral health | Therapy, medication management, program attendance | Reliable appointment access and request clarity |
| Assisted living | Medical appointments, specialty visits, recurring care | Resident support logistics and staff handoff clarity |
| Skilled nursing facilities (SNF) | Appointments, transfers that are non-emergency, follow-up care | Coordinated request workflow and trip documentation |
| Rehab | Therapy schedules, specialty appointments | Schedule-sensitive coordination and status follow-up |
| County / community organizations | Care access, social service appointment support | Community access coordination and transparent request handling |

---

## Kit Contents

| Document | File | Purpose |
|----------|------|---------|
| Partnership overview | [PROVIDER_PARTNERSHIP_OVERVIEW.md](./PROVIDER_PARTNERSHIP_OVERVIEW.md) | Value propositions suitable for external sharing |
| Discovery call script | [PROVIDER_DISCOVERY_CALL_SCRIPT.md](./PROVIDER_DISCOVERY_CALL_SCRIPT.md) | Structured discovery conversation |
| Outreach email sequence | [PROVIDER_OUTREACH_EMAIL_SEQUENCE.md](./PROVIDER_OUTREACH_EMAIL_SEQUENCE.md) | Multi-touch sequence outline |
| Follow-up emails | [PROVIDER_FOLLOW_UP_EMAILS.md](./PROVIDER_FOLLOW_UP_EMAILS.md) | Follow-up timing and sample subjects |
| Intake checklist | [PROVIDER_INTAKE_CHECKLIST.md](./PROVIDER_INTAKE_CHECKLIST.md) | Fields to capture during partnership conversations |
| Onboarding process | [PROVIDER_ONBOARDING_PROCESS.md](./PROVIDER_ONBOARDING_PROCESS.md) | Interest form → consultation → workspace → coordinated requests |
| Provider FAQ | [PROVIDER_FAQ.md](./PROVIDER_FAQ.md) | Internal FAQ aligned with public `/for-providers` content |

Email copy templates live under `email_templates/` (relative to this folder when present). Sequence outlines in this kit point there for send-ready language.

---

## Recommended Outreach Flow

1. **Identify** organization and segment (hospital, clinic, dialysis, behavioral health, AL, SNF, rehab, county/community).
2. **Personalize** first touch using `{{organization_name}}`, `{{first_name}}`, and relevant transportation use case.
3. **Point** to `/for-providers` for overview and consultation request.
4. **Discover** needs using the discovery call script; capture intake fields.
5. **Follow up** with clear next steps and optional `{{meeting_link}}`.
6. **Onboard** only after consultation alignment and authorized workspace provisioning.
7. **Coordinate** live requests through the provider workflow once access and process readiness are confirmed.

---

## Claims Guardrails

Do **not** claim any of the following unless independently documented and approved for external use:

- Medicaid enrollment or reimbursement approval
- HIPAA certification
- Guaranteed insurance coverage
- Guaranteed transportation capacity or availability
- Confirmed government contracts

Preferred framing:

- Amicor is preparing for Minnesota launch as an AI-enabled NEMT coordination/operations platform
- Partnership conversations explore fit, workflow, and coordination needs
- Capacity, coverage, and operational readiness are discussed case by case
- Privacy and data-handling practices can be reviewed during consultation; do not assert certification status

---

## Placeholders

Use these consistently across kit materials:

| Placeholder | Meaning |
|-------------|---------|
| `{{organization_name}}` | Prospect organization legal or commonly used name |
| `{{first_name}}` | Primary contact first name |
| `{{provider_link}}` | `/for-providers` or `/app/providers` as appropriate |
| `{{meeting_link}}` | Scheduling link for consultation or working session |
| `{{amicor_email}}` | Approved Amicor sender/reply address for the campaign |

Do not invent phone numbers, physical addresses, or unapproved contact details.

---

## Internal Ownership

| Role | Responsibility |
|------|----------------|
| Partnership / outreach lead | Sequencing, personalization, discovery, follow-up |
| Operations | Workflow fit, escalation design, go-live readiness |
| Compliance / legal (as needed) | Agreements, BAA discussions when applicable, claim review |

---

## Quick Start for a New Prospect

1. Open [PROVIDER_PARTNERSHIP_OVERVIEW.md](./PROVIDER_PARTNERSHIP_OVERVIEW.md) and select segment talking points.
2. Send Touch 1 from [PROVIDER_OUTREACH_EMAIL_SEQUENCE.md](./PROVIDER_OUTREACH_EMAIL_SEQUENCE.md) using templates in `email_templates/`.
3. If a call is booked, run [PROVIDER_DISCOVERY_CALL_SCRIPT.md](./PROVIDER_DISCOVERY_CALL_SCRIPT.md).
4. Complete [PROVIDER_INTAKE_CHECKLIST.md](./PROVIDER_INTAKE_CHECKLIST.md).
5. Move qualified interest into [PROVIDER_ONBOARDING_PROCESS.md](./PROVIDER_ONBOARDING_PROCESS.md).

For public-facing answers that match the website, use [PROVIDER_FAQ.md](./PROVIDER_FAQ.md).
