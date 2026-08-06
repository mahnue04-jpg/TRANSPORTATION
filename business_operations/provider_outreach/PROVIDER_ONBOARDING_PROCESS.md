# Provider Onboarding Process

**Amicor Health ISF LLC · Minnesota**  
**Purpose:** Define the path from provider interest to coordinated transportation requests

---

## Process Summary

```text
Interest form / outreach reply
        ↓
Consultation
        ↓
Partnership alignment & intake completion
        ↓
Authorized workspace access (/app/providers)
        ↓
Training / workflow readiness
        ↓
Coordinated transportation requests
```

Public entry point: `/for-providers`  
Authorized workspace: `/app/providers`

---

## Stage 1 — Interest Capture

### Sources

- Provider interest form on `/for-providers`
- Reply to outreach sequence
- Referral or direct email to `{{amicor_email}}`

### What this stage means

The interest form creates a **partnership inquiry**. It does **not** automatically create a provider account or workspace access.

### Amicor actions

1. Acknowledge receipt (same business day when possible)
2. Confirm organization name, contact, and preferred method
3. Offer consultation scheduling via `{{meeting_link}}`
4. Share overview link: `{{provider_link}}` → `/for-providers`
5. Log lead and assign outreach/partnership owner

### Exit criteria

- [ ] Valid contact and organization identified
- [ ] Consultation invited or scheduled

---

## Stage 2 — Consultation

### Goals

- Understand transportation coordination needs at `{{organization_name}}`
- Explain Amicor’s NEMT coordination/operations model carefully
- Determine whether to proceed toward partnership and workspace access

### Recommended agenda (25–30 minutes)

1. Introductions and Minnesota market context (launch preparation)
2. Discovery questions ([PROVIDER_DISCOVERY_CALL_SCRIPT.md](./PROVIDER_DISCOVERY_CALL_SCRIPT.md))
3. High-level workflow: request → coordination → status → completed trip records
4. Roles: authorized requestors, Amicor operations, drivers
5. Next-step options

### Capture

Complete [PROVIDER_INTAKE_CHECKLIST.md](./PROVIDER_INTAKE_CHECKLIST.md).

### Exit criteria

- [ ] Needs and geography understood at a working level
- [ ] Mutual interest confirmed or polite close documented
- [ ] Sensitive claim questions flagged if raised

---

## Stage 3 — Partnership Alignment

### Goals

- Confirm scope (sites, trip types, hours, contacts)
- Identify authorized users
- Align on documentation/reporting expectations for operational use
- Determine whether agreements or additional review are required before go-live

### Typical outputs

- Completed intake checklist
- Named operational contact(s)
- Draft authorized requestor list
- Proposed readiness window (not a capacity guarantee)
- Internal decision: proceed / pause / not a fit

### Guardrails during alignment

Do not represent:

- Medicaid enrollment or reimbursement approval
- HIPAA certification
- Guaranteed insurance coverage
- Guaranteed transportation capacity
- Confirmed government contracts

If a Business Associate Agreement or similar document is requested, route through approved legal/compliance process. Discuss data-handling expectations without asserting certification status.

### Exit criteria

- [ ] Scope documented
- [ ] Decision-makers identified
- [ ] Green light to provision access (or documented pause)

---

## Stage 4 — Workspace Access

### Goals

Provision authorized access to the provider workspace at `/app/providers`.

### Amicor actions

1. Create/configure partner record per internal operations process
2. Provision accounts only for approved authorized users
3. Confirm login path: `/app/providers`
4. Share how to submit or schedule transportation requests
5. Confirm escalation contacts for operational issues

### Provider actions

1. Designate authorized staff
2. Complete any required access verification steps
3. Confirm service locations and request standards
4. Attend brief workflow orientation

### Exit criteria

- [ ] At least one authorized user can access `/app/providers`
- [ ] Request standards understood
- [ ] Escalation contacts exchanged

---

## Stage 5 — Workflow Readiness

### Goals

Ensure the partner can submit clear requests and monitor status before relying on the workflow for routine coordination.

### Readiness checklist

- [ ] Trip detail expectations confirmed (pickup window, addresses, rider needs, appointment time)
- [ ] Recurring patterns discussed if applicable (e.g., dialysis)
- [ ] Status monitoring path reviewed for authorized staff
- [ ] Completed-trip documentation review explained
- [ ] Non-emergency scope restated (911 for emergencies)
- [ ] Test or controlled first request planned when operationally appropriate

Availability and matching depend on operational readiness, geography, timing, and driver availability. Do not promise that every request will be filled.

### Exit criteria

- [ ] Partner and Amicor agree readiness is sufficient for coordinated requests

---

## Stage 6 — Coordinated Requests (Live Use)

### Steady-state flow

1. Authorized staff submit or schedule a transportation request through Amicor’s provider coordination workflow
2. Amicor operations and platform tools help coordinate an available qualified driver when matching is possible
3. Staff monitor pickup and trip status in the provider/operations workspace
4. Completed trip records support operational follow-up and internal review

### Ongoing partnership hygiene

- Keep authorized user list current
- Review recurring schedules periodically
- Escalate workflow issues promptly
- Revisit scope if volume, geography, or trip mix changes materially

---

## Communication Templates by Stage

| Stage | Suggested CTA |
|-------|----------------|
| Interest | Review `{{provider_link}}` (`/for-providers`); book `{{meeting_link}}` |
| Post-consult | Recap + next meeting; reply `{{amicor_email}}` |
| Access ready | Use `/app/providers` for authorized workspace |
| Live use | Follow internal escalation path; keep non-emergency scope clear |

See also [PROVIDER_FOLLOW_UP_EMAILS.md](./PROVIDER_FOLLOW_UP_EMAILS.md) and `email_templates/`.

---

## Stage Ownership

| Stage | Primary owner | Supporting |
|-------|---------------|------------|
| Interest capture | Partnership / outreach | Operations (visibility) |
| Consultation | Partnership / outreach | Operations as needed |
| Alignment | Partnership + operations | Legal/compliance if required |
| Workspace access | Operations | Partnership |
| Readiness | Operations | Partnership |
| Coordinated requests | Operations + partner staff | Partnership (relationship health) |

---

## Related Documents

- [PROVIDER_OUTREACH_KIT.md](./PROVIDER_OUTREACH_KIT.md)
- [PROVIDER_PARTNERSHIP_OVERVIEW.md](./PROVIDER_PARTNERSHIP_OVERVIEW.md)
- [PROVIDER_INTAKE_CHECKLIST.md](./PROVIDER_INTAKE_CHECKLIST.md)
- [PROVIDER_FAQ.md](./PROVIDER_FAQ.md)
