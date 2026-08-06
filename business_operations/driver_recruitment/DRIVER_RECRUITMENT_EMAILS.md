# Driver Recruitment Emails — Internal Guidance

**Company:** AMICOR HEALTH ISF LLC  
**Audience:** Recruitment and onboarding team members sending driver communications  
**Application link placeholder:** `{{application_link}}` → `/platform-ops/driver-apply`  
**Name placeholder:** `{{first_name}}`

---

## Purpose

This page is short internal guidance for using Amicor’s driver email templates. Full message bodies live in the `email_templates` folder. Do not rewrite public promises into email copy.

---

## Rules for every driver email

1. Use `{{first_name}}` for personalization.
2. Use `{{application_link}}` for the application URL (`/platform-ops/driver-apply`). For full URLs in send tools, prepend the approved Amicor site origin to that path.
3. Do **not** invent phone numbers, email addresses, or mailing addresses. If a template includes `{{amicor_email}}` or `{{amicor_phone}}`, fill those only from approved Amicor contact sources—or omit contact lines until confirmed.
4. Do **not** promise guaranteed income, pay rates, trip minimums, or employment benefits.
5. Distinguish **conditional approval** from **activation**.
6. Keep tone professional, welcoming, and community-focused.
7. Prefer directing early interest to `/for-drivers` for overview and `/platform-ops/driver-apply` to apply.

---

## Template index (driver)

| Order | Template file | When to use |
|------:|---------------|-------------|
| 1 | [`../email_templates/01_driver_inquiry_acknowledgment.md`](../email_templates/01_driver_inquiry_acknowledgment.md) | First response after a driver inquiry |
| 2 | [`../email_templates/02_driver_application_follow_up.md`](../email_templates/02_driver_application_follow_up.md) | Application started or stalled; encourage completion |
| 3 | [`../email_templates/03_driver_document_reminder.md`](../email_templates/03_driver_document_reminder.md) | Missing or incomplete uploads |
| 4 | [`../email_templates/04_driver_interview_invitation.md`](../email_templates/04_driver_interview_invitation.md) | Invite candidate to interview / readiness conversation |
| 5 | [`../email_templates/05_driver_conditional_approval.md`](../email_templates/05_driver_conditional_approval.md) | Candidate may proceed to onboarding pending remaining items |

Open the linked file for the approved body text before sending.

---

## Sample subject lines

Use these (or the subject lines already set in each template). Keep subjects short and accurate.

### From existing templates

| Template | Sample subject |
|----------|----------------|
| Inquiry acknowledgment | Thank you for your interest in driving with AMICOR |
| Application follow-up | Following up on your AMICOR driver application |
| Document reminder | Reminder: Documents needed to continue your AMICOR application |
| Interview invitation | Invitation to meet with the AMICOR driver team |
| Conditional approval | Next steps for your AMICOR driver application |

### Optional alternate subjects (same intent)

| Intent | Alternate subject |
|--------|-------------------|
| Inquiry acknowledgment | {{first_name}}, thanks for reaching out to AMICOR |
| Application follow-up | {{first_name}}, ready to finish your AMICOR application? |
| Document reminder | Action needed: documents for your AMICOR driver application |
| Interview invitation | {{first_name}}, let’s talk about driving with AMICOR |
| Conditional approval | {{first_name}}, your AMICOR application — next onboarding steps |
| Activation readiness (if separately emailed later) | Your AMICOR driver readiness next steps |
| General redirect to apply | Start your AMICOR driver application |

---

## Placeholder cheat sheet

| Placeholder | Meaning | Notes |
|-------------|---------|-------|
| `{{first_name}}` | Candidate first name | Required for personalization |
| `{{application_link}}` | Driver application path | Use `/platform-ops/driver-apply` |
| `{{amicor_email}}` | Approved Amicor contact email | Do not invent |
| `{{amicor_phone}}` | Approved Amicor contact phone | Do not invent |
| `{{organization_name}}` | Provider org name (provider templates) | Not used for standard driver recruitment |

---

## Suggested send sequence

1. **Inquiry** → `01_driver_inquiry_acknowledgment.md`  
   Include `{{application_link}}`. Optionally mention learning more at `/for-drivers`.
2. **No application yet / incomplete** → `02_driver_application_follow_up.md`
3. **Missing docs** → `03_driver_document_reminder.md`
4. **Interview needed** → `04_driver_interview_invitation.md`
5. **May continue** → `05_driver_conditional_approval.md`  
   Emphasize pending requirements; do not imply immediate trip eligibility.

After conditional approval, continue with onboarding checklist and orientation. Only describe activation when readiness is confirmed.

---

## Quick copy blocks (internal only)

### Pointing to the marketing page

> You can learn more about driving with AMICOR on our driver page: `/for-drivers`

### Pointing to the application

> To begin or continue your application, visit: {{application_link}}

### Softening expectations

> Final eligibility depends on review, screening, and completion of required documentation. Trip opportunities, when available, depend on approval, readiness, and platform coordination—and are not a guarantee of income or trip volume.

---

## Related kit documents

- [DRIVER_RECRUITMENT_KIT.md](./DRIVER_RECRUITMENT_KIT.md)
- [DRIVER_APPLICATION_PROCESS.md](./DRIVER_APPLICATION_PROCESS.md)
- [DRIVER_FAQ.md](./DRIVER_FAQ.md)

---

*AMICOR HEALTH ISF LLC — Use approved templates in `business_operations/email_templates/` as the source of truth for full email bodies.*
