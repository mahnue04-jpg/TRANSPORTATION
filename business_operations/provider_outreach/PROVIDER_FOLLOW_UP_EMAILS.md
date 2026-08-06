# Provider Follow-Up Emails

**Amicor Health ISF LLC · Minnesota**  
**Purpose:** Guidance for post-outreach and post-conversation follow-ups, with sample subjects and placeholders

---

## Principles

- Follow up promptly, briefly, and with a clear next step
- Personalize with `{{organization_name}}` and `{{first_name}}`
- Point early-stage contacts to `/for-providers` via `{{provider_link}}`
- Mention `/app/providers` only when discussing authorized workspace access
- Include `{{meeting_link}}` when asking to schedule
- Reply from / include `{{amicor_email}}`
- Do not invent phone numbers or physical addresses
- Avoid unsupported claims (Medicaid enrollment, HIPAA certification, guaranteed insurance, guaranteed capacity, government contracts)

For sequence timing, see [PROVIDER_OUTREACH_EMAIL_SEQUENCE.md](./PROVIDER_OUTREACH_EMAIL_SEQUENCE.md).  
For full body copy, use `email_templates/` when available.

---

## When to Follow Up

| Trigger | Timing | Goal |
|---------|--------|------|
| No reply to cold outreach | Per sequence (Touches 2–4) | Re-engage politely |
| Interest form submitted | Same business day acknowledgment; consultation outreach within 1–2 business days | Confirm receipt and book consult |
| Meeting booked | 24 hours before (optional reminder) | Reduce no-shows |
| Discovery call completed | Same day | Recap + next steps |
| Stakeholder intro requested | Within 1 business day | Equip champion with overview |
| Materials requested | Within 1 business day | Send overview links only; no invented claims |
| Quiet after promising conversation | +5 business days | Soft re-open |

---

## Sample Subject Lines

### After no reply

- Re: Transportation coordination for {{organization_name}}
- Quick follow-up for {{first_name}}
- Following up — Amicor provider consultation
- Still open to a short conversation, {{first_name}}?

### After interest form

- Received — {{organization_name}} provider consultation request
- Next step for {{organization_name}}: schedule your Amicor consult
- Thanks, {{first_name}} — confirming your Amicor inquiry

### After discovery call

- Thank you, {{first_name}} — next steps for {{organization_name}}
- Amicor follow-up from today’s conversation
- {{organization_name}} transportation coordination — proposed next step

### Meeting logistics

- Reminder: Amicor consultation with {{organization_name}}
- Proposed times for {{organization_name}} provider discussion
- Book here: Amicor consultation for {{organization_name}}

### Leave-open / pause

- Closing the loop for now — {{organization_name}}
- Happy to reconnect when timing is better
- Should I check back next quarter with {{organization_name}}?

---

## Follow-Up Skeleton (Post-Discovery)

Use this structure; pull wording from `email_templates/` if a matching template exists.

1. **Thank** `{{first_name}}` for the conversation about `{{organization_name}}`
2. **Restate** 2–3 needs they shared (volume, trip types, workflow owners, geography)
3. **Propose** one next step (working session, stakeholder intro, or consultation continuation)
4. **Link** overview: `{{provider_link}}` → `/for-providers`
5. **Offer** scheduling: `{{meeting_link}}`
6. **Invite** questions at `{{amicor_email}}`
7. **Do not** promise capacity, payer approval, certification, or contract status

---

## Example Body Outline — Same-Day Thank You

> Hi {{first_name}},  
>  
> Thank you for speaking with Amicor Health ISF LLC about transportation coordination at {{organization_name}}.  
>  
> As discussed, you are exploring [trip types / workflow challenges summarized from the call]. Amicor is an AI-enabled NEMT coordination and operations platform preparing for Minnesota launch, and our next step is [consultation / workflow working session / stakeholder intro].  
>  
> Overview: {{provider_link}}  
> Schedule: {{meeting_link}}  
> Questions: {{amicor_email}}  
>  
> Looking forward to the next conversation.

---

## Example Body Outline — Soft Re-Open

> Hi {{first_name}},  
>  
> Checking back in case timing is better for {{organization_name}}. If care-related transportation coordination is still a priority, I’m glad to schedule a short consultation.  
>  
> You can review Amicor at {{provider_link}} or book time here: {{meeting_link}}.  
>  
> Best regards,  
> {{amicor_email}}

---

## What Not to Write in Follow-Ups

- “We are Medicaid enrolled / approved for reimbursement”
- “We are HIPAA certified”
- “We guarantee insurance coverage”
- “We guarantee we can cover all of your rides / capacity”
- “We have confirmed government contracts”
- Specific phone/address details that have not been approved for use

If a prospect asks about any of the above, answer carefully (see [PROVIDER_DISCOVERY_CALL_SCRIPT.md](./PROVIDER_DISCOVERY_CALL_SCRIPT.md) and [PROVIDER_FAQ.md](./PROVIDER_FAQ.md)) and escalate for documented review before putting absolute statements in writing.

---

## Checklist Before Sending

- [ ] Placeholders replaced
- [ ] Segment language fits `{{organization_name}}`
- [ ] Correct `{{provider_link}}` path for the stage of conversation
- [ ] Clear single CTA
- [ ] Claims reviewed against guardrails
- [ ] Logged in outreach tracker / CRM equivalent
