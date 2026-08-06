# Provider Outreach Email Sequence

**Amicor Health ISF LLC · Minnesota**  
**Purpose:** Multi-touch outline for provider partnership outreach  
**Send-ready copy:** Use templates in `email_templates/` (replace placeholders before send)

---

## Placeholders

| Placeholder | Replace with |
|-------------|----------------|
| `{{organization_name}}` | Prospect organization name |
| `{{first_name}}` | Contact first name |
| `{{provider_link}}` | Usually `/for-providers`; use `/app/providers` only when discussing authorized workspace access |
| `{{meeting_link}}` | Scheduling link |
| `{{amicor_email}}` | Approved Amicor reply address |

Do not invent phone numbers, postal addresses, or unapproved contact details.

---

## Sequence Overview

| Touch | Timing | Objective | Template location |
|-------|--------|-----------|-------------------|
| 1 | Day 0 | Introduce Amicor and invite consultation | `email_templates/` cold intro |
| 2 | +4–6 business days | Soft bump; add segment-relevant use case | `email_templates/` follow-up #1 |
| 3 | +5–7 business days after Touch 2 | Value reminder + clear CTA | `email_templates/` follow-up #2 |
| 4 | +7–10 business days after Touch 3 | Break-up / leave-the-door-open | `email_templates/` final touch |
| Optional | After reply or form submit | Confirm consultation and share agenda | `email_templates/` meeting confirm |
| Optional | Same day after discovery call | Recap + next steps | See [PROVIDER_FOLLOW_UP_EMAILS.md](./PROVIDER_FOLLOW_UP_EMAILS.md) |

Stop the sequence when the contact replies, books a meeting, submits the interest form, or asks not to be contacted.

---

## Touch 1 — Introduction (Day 0)

**Goal:** Establish relevance for Minnesota care transportation coordination.

**Message outline**

1. Personalized greeting to `{{first_name}}` / `{{organization_name}}`
2. One-sentence who Amicor is: AI-enabled NEMT coordination/operations platform preparing for Minnesota launch
3. One segment-relevant operational pain (appointments, dialysis recurrence, discharge timing, behavioral health access, etc.)
4. Two or three capability bullets (request coordination, status visibility, trip documentation)—no unsupported claims
5. CTA: review `{{provider_link}}` (`/for-providers`) and/or book via `{{meeting_link}}`
6. Sign-off with `{{amicor_email}}`

**Sample subject lines**

- Transportation coordination for {{organization_name}} — Minnesota provider consultation
- Helping {{organization_name}} coordinate care-related rides
- Provider partnership inquiry — Amicor Health ISF LLC

**Template:** `email_templates/` (cold intro / segment variants)

---

## Touch 2 — Follow-up (about +5 business days)

**Goal:** Stay professional and useful without pressure.

**Message outline**

1. Brief bump referencing prior note
2. One concrete use case for their segment
3. Reminder that interest form / consultation starts the conversation (not an automatic account)
4. CTA: `{{meeting_link}}` or reply to `{{amicor_email}}`
5. Link: `{{provider_link}}` → `/for-providers`

**Sample subject lines**

- Re: Transportation coordination for {{organization_name}}
- Quick follow-up for {{first_name}} — provider consultation
- Following up on care transportation coordination

**Template:** `email_templates/` (follow-up #1)

---

## Touch 3 — Value reminder (about +5–7 business days after Touch 2)

**Goal:** Restate fit around workflow outcomes, not guarantees.

**Message outline**

1. Acknowledge busy calendars
2. Restate Amicor focus: centralized requests, trip status visibility, recurring-care coordination discussions, completed-trip records
3. Invite a short discovery call using the script in [PROVIDER_DISCOVERY_CALL_SCRIPT.md](./PROVIDER_DISCOVERY_CALL_SCRIPT.md)
4. CTA: `{{meeting_link}}` or `/for-providers` interest form via `{{provider_link}}`

**Sample subject lines**

- Still useful for {{organization_name}}? Short provider consult
- Coordinating NEMT requests — open to a brief conversation?
- {{organization_name}}: one more note on transportation coordination

**Template:** `email_templates/` (follow-up #2)

---

## Touch 4 — Final / leave-open (about +7–10 business days after Touch 3)

**Goal:** Close the loop respectfully.

**Message outline**

1. Final note; no hard sell
2. Offer to reconnect when timing is better
3. Leave `/for-providers` and `{{amicor_email}}` as easy paths back
4. Optional: ask if another contact at `{{organization_name}}` owns transportation logistics

**Sample subject lines**

- Closing the loop — {{organization_name}}
- Last note from Amicor for now
- Should I check back later with {{organization_name}}?

**Template:** `email_templates/` (final touch)

---

## Segment Angles (for personalization only)

Use these as talking points inside templates—not as guarantees.

| Segment | Angle |
|---------|--------|
| Hospital | Discharge and follow-up transportation coordination with clearer status visibility |
| Clinic | Appointment access and structured request intake |
| Dialysis | Recurring pickup/return coordination discussions |
| Behavioral health | Supporting appointment attendance through dependable coordination workflows |
| Assisted living / SNF | Resident/patient appointment logistics and staff handoff clarity |
| Rehab | Schedule-sensitive therapy and specialty visit coordination |
| County / community | Community care access and transparent request handling |

---

## Compliance Notes for Every Send

- Do not claim Medicaid enrollment/reimbursement approval
- Do not claim HIPAA certification
- Do not guarantee insurance coverage
- Do not guarantee transportation capacity
- Do not claim confirmed government contracts
- State that Amicor coordinates non-emergency transportation only
- Prefer `/for-providers` in cold outreach; reserve `/app/providers` for authorized-access context

---

## Related Documents

- Master kit: [PROVIDER_OUTREACH_KIT.md](./PROVIDER_OUTREACH_KIT.md)
- Follow-up guidance: [PROVIDER_FOLLOW_UP_EMAILS.md](./PROVIDER_FOLLOW_UP_EMAILS.md)
- Partnership overview: [PROVIDER_PARTNERSHIP_OVERVIEW.md](./PROVIDER_PARTNERSHIP_OVERVIEW.md)
- Templates folder: `email_templates/`
