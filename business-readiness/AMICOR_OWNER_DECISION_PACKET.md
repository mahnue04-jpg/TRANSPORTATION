# AMICOR OWNER DECISION PACKET

## Context
Decision mode assumptions applied as fixed:
- Customer Type: Healthcare Facility Contracts (B2B)
- Launch Focus: Recurring Ambulatory Medical Transportation
- Initial Target Segment: Dialysis Centers
- Initial Service Area: Small City / Suburban Healthcare Corridor
- Pricing Model: Flat-Rate Pricing
- Business Goal: First Pilot Partner, First Recurring Rider, First Invoice, First Revenue

---

## SECTION 1: Recommended Final Business Decisions

### 1) Pricing Framework
Document: business-readiness/12_Pricing_Framework_Draft.md

Recommended exact operational values:
- Flat rate per completed one-way trip: USD 68
- Pilot setup fee: USD 0
- Late cancellation fee (>2h and <=24h): USD 24
- Same-day cancellation fee (<=2h): USD 34
- Rider no-show fee: USD 41
- Payment terms: Net 15
- Dispute window: 7 business days
- Late payment charge: 1.5% per month after 10-day grace period
- Margin threshold: >=25% for two-week rolling period
- Max discount: 10% for max 8 weeks

Reasoning:
- Flat-rate pricing fits recurring dialysis scheduling and simplifies partner procurement decisions.
- Net 15 improves early-stage cash conversion.
- Fee structure protects schedule integrity and driver commitment.

Estimated operational impact:
- Faster contracting and invoicing due to simple rate card.
- Improved schedule adherence from cancellation/no-show deterrence.
- Better early cash discipline from short payment terms.

Risks:
- Flat-rate may underperform on unusually long routes.
- Price sensitivity risk if local alternatives are subsidized.

Status: APPROVED

### 2) Driver Compensation Framework
Documents: business-readiness/02_Independent_Contractor_Driver_Agreement.md and business-readiness/12_Pricing_Framework_Draft.md

Recommended exact operational values:
- Base payout per completed one-way trip: USD 38
- Peak payout windows (5:00-7:00 AM, 4:00-7:00 PM): USD 42
- Rider no-show payout: USD 13 with validated evidence
- Same-day cancellation payout after acceptance: USD 10
- Active-trip cancellation payout after en_route_pickup: USD 24
- Dispatch response SLA: 5 minutes

Reasoning:
- Payout structure supports reliability in dialysis-heavy windows.
- Peak differential improves driver acceptance when demand is time-concentrated.
- Partial payouts reduce driver churn during unavoidable disruption.

Estimated operational impact:
- Better acceptance rates during first-month launch windows.
- Reduced assignment failures in recurring morning treatment blocks.

Risks:
- Peak differential may increase labor cost if peak volume is underestimated.
- Insufficient payout competitiveness in tight local driver markets.

Status: APPROVED

### 3) Cancellation Policy
Document: business-readiness/04_Cancellation_Policy.md

Recommended exact operational values:
- Standard cancellation (>24h): no charge, no payout
- Late cancellation (>2h and <=24h): charge USD 24; accepted assignment payout USD 8
- Same-day cancellation (<=2h): charge USD 34; accepted assignment payout USD 10
- Active-trip cancellation (after en_route_pickup): charge full USD 68; payout USD 24
- Provider notification SLA: within 10 minutes of status change

Reasoning:
- Aligns partner accountability with operational costs.
- Balances fairness for facilities while protecting route reliability.

Estimated operational impact:
- Lower late cancellation behavior over first 4 weeks.
- Better predictability for dispatch and driver utilization.

Risks:
- Partner pushback on cancellation penalties at pilot start.
- Potential waiver pressure for high-acuity circumstances.

Status: APPROVED

### 4) No-Show Policy
Document: business-readiness/05_No_Show_Policy.md

Recommended exact operational values:
- Wait window: 15 minutes with required contact attempts
- Rider no-show fee: USD 41
- Rider no-show payout: USD 13 with evidence
- Dispute submission window: 7 business days
- Driver reliability thresholds:
  - 2 no-shows in 30 days: suspension review
  - 3 no-shows in 30 days: termination review

Reasoning:
- Protects schedule continuity for recurring medical riders.
- Creates clear evidence and accountability framework.

Estimated operational impact:
- Reduced ambiguity in billing and payout decisions.
- Faster dispute resolution due to fixed evidence and timelines.

Risks:
- Administrative burden for evidence validation in high-volume weeks.
- Relationship friction if no-show attribution is contested.

Status: APPROVED

### 5) Provider Service Agreement Business Terms
Document: business-readiness/01_Provider_Service_Agreement_Template.md

Recommended exact operational values:
- Initial term: 6-month pilot-to-recurring term
- Renewal: automatic month-to-month
- Termination for cause: 15-day cure
- Termination for convenience: 30-day notice
- Service window: Mon-Sat, 5:00 AM-7:00 PM
- Breach notification window: 48 hours
- Payment terms: Net 15
- Liability cap: prior 3 months fees (excluding fraud/willful misconduct)

Reasoning:
- 6-month window gives enough signal for recurring economics.
- Net 15 and monthly rollover supports early-stage revenue reliability.

Estimated operational impact:
- Accelerated contracting with clear commercial terms.
- Better launch governance and predictable operating coverage.

Risks:
- Legal negotiation cycle may delay signature if entity-state terms are unresolved.
- Insurance thresholds may need adjustment by partner procurement teams.

Status: REVISE
(Reason: legal entity name, state/venue specifics, and insurance policy numbers still require final legal completion.)

### 6) Pilot Program Proposal
Document: business-readiness/09_Pilot_Program_Proposal.md

Recommended exact operational values:
- Pilot duration: 6 weeks
- Sites: up to 2 dialysis sites
- Weekly volume target: 40-70 one-way trips
- Service hours: Mon-Sat, 5:00 AM-7:00 PM
- KPI targets:
  - Completion >=95%
  - Cancellation <=8%
  - Exception resolution <=20 min
  - On-time pickup >=92%
- Commercial terms:
  - USD 68 per completed one-way trip
  - Weekly minimum invoice floor USD 2,000 (waived first 2 weeks)
  - Net 15

Reasoning:
- 6-week window is long enough for recurring pattern validation.
- Volume and KPI targets are practical for dialysis recurrence.

Estimated operational impact:
- Faster move from discovery to signed pilot due to clear numbers.
- Easier conversion to recurring service with threshold-based expansion trigger.

Risks:
- KPI baselines may vary by partner geography and shift schedule.
- Weekly minimum may be challenged during initial adoption.

Status: REVISE
(Reason: partner-specific naming, actual kickoff date, and exact site list are still required per deal.)

### 7) KPI Dictionary
Document: business-readiness/16_KPI_Tracking_Dashboard_Specification.md

Recommended exact operational values:
- Request-to-queue <=15 minutes
- Queue-to-assignment <=90 minutes
- On-time pickup >=92%
- Completion >=95%
- Cancellation <=8%
- Exception rate <=6%
- Exception resolution <=20 minutes
- Invoice realization >=98%
- Collection cycle <=21 days
- Gross margin >=25%
- Escalation thresholds defined for underperformance in rolling 7-day windows

Reasoning:
- Mixes service quality, financial quality, and grant evidence readiness.
- Dialysis recurring operations require strict pickup and exception controls.

Estimated operational impact:
- Stronger operating discipline and partner confidence.
- Faster grant evidence production with stable monthly KPI outputs.

Risks:
- Data-source inconsistencies can undermine KPI trust if not standardized.
- Alert fatigue risk if thresholds are too sensitive in week 1-2.

Status: APPROVED

---

## SECTION 2: Revenue Impact Analysis

### Unit Economics (Launch Model)
- Average billed rate per completed one-way trip: USD 68
- Average driver payout per trip (blended base/peak assumption): ~USD 40
- Gross margin per completed trip before overhead: ~USD 28
- Gross margin percent before overhead: ~41%

### Weekly Revenue Range (Pilot)
- At 40 completed trips/week: USD 2,720 billed
- At 70 completed trips/week: USD 4,760 billed
- Weekly floor protection: USD 2,000 (first 2 weeks waived)

### 6-Week Pilot Revenue Range
- Gross billed revenue estimate: USD 16,320 to USD 28,560
- Additional fee revenue from cancellation/no-show depends on operational behavior and should remain secondary to completion revenue.

### Cash Conversion Impact
- Net 15 terms + weekly invoices accelerate first-cash timing versus Net 30.
- AR escalation plus 7-day dispute window reduces open-receivable drag.

---

## SECTION 3: Pilot Readiness Analysis

Readiness position after decision replacement:
- Commercial readiness: materially improved (rates, terms, fee logic now fixed)
- Operational readiness: improved (dispatch response, no-show timing, escalation KPIs fixed)
- Partner proposal readiness: improved but partner-specific values still required
- Legal readiness: partial (entity/state/insurance final legal fields still open)

Go-live blockers remaining:
1. Final legal entity and governing-law completion in agreement package
2. Named pilot partner site list and kickoff dates in proposal
3. AR ownership and collections contacts finalized
4. Data source-of-truth mapping for KPI reporting outputs

Overall pilot launch status: READY WITH CONTROLLED REVISIONS

---

## SECTION 4: First Revenue Path

1. Execute provider agreement with finalized business terms and legal completion fields.
2. Confirm pilot site roster and recurring dialysis schedule by coordinator.
3. Activate driver cohort for morning/afternoon recurring windows.
4. Start rides and enforce cancellation/no-show policy with evidence logging.
5. Close first weekly billing cycle and issue first invoice (Net 15).
6. Run AR follow-up within 48 hours of invoice issue confirmation.
7. Resolve disputes within 7 business days under fixed policy.
8. Record first payment as first revenue milestone.

Expected sequence timeline:
- Week 1: signature and onboarding
- Week 2: recurring rides active
- Week 3: first invoice issued
- Week 4-5: first payment collected

---

## SECTION 5: Top 5 Decisions That Must Be Approved Before Launch

1. Legal completion package
- Confirm legal entity details, governing law/venue, liability language, insurance policy numbers.

2. Final partner-specific pilot scope
- Approve exact dialysis sites, launch date, and weekly trip commitment.

3. Collections and AR ownership
- Approve single-threaded owner, escalation ladder, and customer communication sequence.

4. KPI source-of-truth lock
- Approve final KPI data dictionary to prevent reporting disputes with partner and funders.

5. Exception waiver authority
- Approve who can waive cancellation/no-show fees and under what criteria.

---

## Owner Decision Summary
- Pricing Framework: APPROVED
- Driver Compensation Framework: APPROVED
- Cancellation Policy: APPROVED
- No-Show Policy: APPROVED
- Provider Service Agreement Business Terms: REVISE
- Pilot Program Proposal: REVISE
- KPI Dictionary: APPROVED
