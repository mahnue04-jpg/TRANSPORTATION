# First customer prep (website only)

This is an internal operating plan for **AMICOR HEALTH ISF LLC**. It is not a public offer, not a signed contract, and not attorney-approved. Pilot prices below are **preliminary / subject to change / subject to owner approval**. There is no checkout on https://getamicor.com.

Do not implement billing from this document.

## Launch-readiness snapshot

| Area | Status | What is ready now | What is not ready |
|---|---|---|---|
| A. Public website | Ready for outreach | Live HTTPS site at https://getamicor.com; truthful product-status labels | Legal pages are drafts |
| B. Lead capture | Ready for inquiries | Early Access / Request Demo form → `POST /api/leads` → AMICOR KV store | Optional webhook not set; no CRM |
| C. Legal | Blocker for paid work | Draft Privacy, Terms, Software Terms, Accessibility | Attorney review required before accepting payment |
| D. Business email | Active and verified | `info@getamicor.com` and `sales@getamicor.com` forward to the owner inbox; public site uses info@ | Optional aliases (support / partners / privacy) not created; send-as not configured |
| E. Customer demo | Ready as a conversation | Request Demo query, product page, supervised-agent story | No scheduled demo product, no shared calendar |
| F. Payment / revenue | Not ready | Public site says Contact AMICOR / preliminary prices | No Stripe checkout, no invoice product, no paid-pilot agreement |
| G. Outreach | Ready with limits | Public URL, form, status matrix | Do not claim licensed rides, live delivery, medical use, or autonomous production execution |

## What can be done immediately (no payment)

1. Send the official URL: https://getamicor.com
2. Point prospects to **Request Demo** or **Request Early Access**
3. Qualify the lead from the KV store (see questions below)
4. Hold a supervised product conversation / screen-share
5. Collect written interest only — not a sale

## Request Demo flow

1. Prospect clicks Request Demo on the Autonomous Operations Agent page (`?product=Autonomous%20Operations%20Agent&intent=demo`).
2. Form pre-fills product and a demo message.
3. After consent and validation, `POST /api/leads` stores the inquiry if accepted.
4. Success copy appears only after storage succeeds.
5. Owner reviews the KV lead and replies from an AMICOR channel. Use info@getamicor.com as the public face. Do not publish the private destination inbox.

## Early Access lead flow

1. Prospect opens `/early-access/` and selects a product (Agent, Health, Deliver, Lifesaver, Home Hub, Partnership, or Other).
2. Same validation, honeypot, consent, and KV storage as Request Demo.
3. Treat Health / Deliver / Lifesaver / Home Hub leads as **interest**, not as bookings, orders, or hardware sales.

## Lead qualification questions

Ask these after the form arrives. Do not collect medical records, diagnoses, or other sensitive health information.

- What operation do you run today (transportation, NEMT, courier, fleet, field service, other)?
- How many vehicles, jobs, or concurrent assignments in a typical day?
- Who approves dispatch or work assignment today?
- What system would the agent observe (existing dispatch, spreadsheet, other)?
- Are you asking for a demo, a supervised pilot, or general information?
- Timeline: looking now, later this quarter, or later?
- Any requirement we cannot meet yet (unattended execution, licensed public rides, live delivery, clinical use)? If yes, decline politely.

## Pilot customer intake

For a prospect that passes qualification:

1. Confirm they understand the agent is **Early Access / In Development** and stops for human approval.
2. Confirm they will not use it for unattended production execution.
3. Record company, contact, use case, and desired start window.
4. Do **not** take payment until the payment blockers below are cleared.
5. If they only want a demo, keep it unpaid.

## Proposed controlled paid-pilot structure (preliminary)

These figures are planning numbers only. They are **not an offer to sell**.

| Track | Preliminary idea | Notes |
|---|---|---|
| Supervised demo | No charge | Screen-share / conversation only |
| Early Access evaluation | Contact AMICOR | Time-boxed, human approval required |
| Starter pilot | planned $29/month | Same public planning price; owner must approve before quoting |
| Growth pilot | planned $99/month | Same public planning price; owner must approve before quoting |
| Business / Enterprise | Contact Sales | Scoped after a conversation |

Pilot rules if later approved:

- Written scope: observe / recommend / human approval / verify / audit only
- No autonomous production execution
- No consumer ride booking and no public delivery orders
- AMICOR may stop the pilot if safety or status labels are ignored

## What must be complete before accepting payment

- Attorney-reviewed customer terms (or a signed pilot agreement)
- A way to invoice or collect payment that is not the public website checkout (none exists today)
- A named AMICOR reply mailbox or documented owner follow-up process (`info@getamicor.com` now receives mail; send-as is still optional)
- Written confirmation that the pilot is supervised software, not a licensed transportation or medical service
- Owner approval of any price actually quoted

Until those exist, take **interest and demos only**.
