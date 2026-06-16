# LAUNCH_BLOCKER_CLOSURE_PLAN

## SECTION 1: Launch Blockers

The blockers below are sourced from NO-GO conditions and all Critical/High risks in:
- business-readiness/LAUNCH_RISK_AUDIT.md
- business-readiness/AMICOR_OWNER_DECISION_PACKET.md

### Blocker Register
| Blocker | Why It Blocks Launch | Exact Action Required | Owner | Evidence Required to Close | Completion Window |
|---|---|---|---|---|---|
| Provider agreement legal identity not finalized | Partner procurement cannot execute contract | Complete legal entity name, registered address, signatory authority, governing law, venue | CEO + Compliance Officer + Legal Counsel | Executable provider agreement PDF with all legal fields complete and signed redline approval | This Week |
| Insurance and certificate details unresolved in provider agreement | Partner legal/compliance review fails | Attach insurance schedule, certificate workflow, and policy identifiers | Compliance Officer | Insurance certificate pack + contract exhibit reference | This Week |
| Missing formal HIPAA/legal posture | Healthcare facilities may halt onboarding and legal review | Issue signed compliance memo covering PHI handling, legal posture, incident reporting, retention, subprocessors | Compliance Officer | Signed compliance memo + partner diligence response pack | Before First Pilot |
| Driver credential governance unresolved (background checks/permits) | Regulatory and safety exposure prevents responsible launch | Publish mandatory driver credential checklist, approved background-check vendor, permit requirements, renewal cadence | Operations Director + Compliance Officer | Driver go-live checklist, vendor contract, 100% launch-cohort compliance report | Before First Pilot |
| AR owner and collections workflow not operationally locked | First invoice may not convert to cash | Assign AR owner + backup, define 48-hour invoice follow-up cadence, define escalation ladder | CFO | AR SOP with named owners, first-invoice follow-up checklist, escalation matrix | Today |
| Pilot proposal missing partner-specific site names and kickoff date | Proposal remains non-binding, delays signature | Convert proposal to partner-specific SOW with facility names, launch date, weekly slots | CEO + COO | Signed partner-specific SOW or countersigned proposal addendum | Before First Pilot |
| KPI source-of-truth schema not locked | KPI disputes can invalidate SLA and grant reporting | Map each KPI formula to system fields/tables and freeze metric governance version | COO + Operations Director | KPI data dictionary v1 signed by Ops + Finance + Compliance | This Week |
| Queue-to-assignment target misaligned for dialysis urgency | Partner may reject SLA terms and launch confidence | Revise dialysis peak target to <=45 min peak and <=60 min standard windows | COO + Operations Director | SLA addendum with updated targets approved by partner | Before First Pilot |
| Manual dispatch staffing proof not defined for upper-volume scenario | SLA miss risk at 40-70 trips/week | Define dispatcher-to-active-trip ratio and peak-hour staffing schedule | Operations Director | Staffing model sheet + pilot shift roster + coverage sign-off | This Week |
| Communication failover matrix undefined | Clinical coordination failure risk during outages | Define portal/SMS/phone failover with acknowledgment and escalation rules | Operations Director | Communication failover SOP + test log from simulation drill | Before First Pilot |
| Exception waiver authority not bounded | Inconsistent fee enforcement and disputes | Define waiver tiers, approvers, documentation requirements, weekly audit | COO + CFO | Waiver authority matrix + first weekly waiver audit template | This Week |
| Flat-rate model lacks outlier route protection | Margin collapse risk on long-route/idle scenarios | Add route guardrail clause (distance/time threshold surcharge or exclusion band) | CFO + COO | Pricing addendum signed and reflected in provider agreement | Before First Pilot |
| Cash conversion risk with Net 15 only | Early-stage working-capital stress | Add pilot payment control: one-week deposit or ACH autopay in contract | CFO + CEO | Contract clause + partner confirmation of payment control method | Before First Pilot |
| Data retention/deletion and vendor inventory not finalized | Compliance and grant diligence weakness | Finalize retention matrix and vendor register with owners | Compliance Officer | Data retention policy + third-party vendor inventory with risk owner fields | Before First Pilot |
| Driver payout competitiveness risk in corridor | Retention and reliability degradation after early weeks | Implement temporary recurring-block acceptance incentive or minimum shift guarantee for launch cohort | COO + CFO + Operations Director | Driver incentive memo + acceptance-rate weekly dashboard | Before First Pilot |

## SECTION 2: Closure Actions

### Today
1. Name AR owner and backup; publish invoice follow-up workflow and escalation path.
2. Launch legal completion sprint owner list with due times for entity fields and governing law/venue.
3. Freeze blocker tracker with owner, due date, evidence link, and status.

### This Week
1. Finalize provider agreement legal identity + insurance artifacts.
2. Finalize KPI source-of-truth dictionary and approval signatures.
3. Finalize dispatcher staffing ratio and publish pilot-week shift roster.
4. Finalize exception waiver authority matrix.
5. Build partner-specific draft SOW (site names + kickoff date) ready for signature.

### Before First Pilot
1. Issue signed HIPAA/legal posture memo and compliance diligence package.
2. Complete driver credential governance package and verify launch cohort compliance.
3. Execute partner-specific SOW and payment-control clause (deposit or ACH autopay).
4. Implement communication failover SOP and complete drill evidence.
5. Add outlier route guardrail clause to pricing and agreement.
6. Finalize retention/deletion schedule and vendor inventory.

### Before Scaling
1. Implement pricing segmentation bands by route complexity and time.
2. Define scale triggers for staffing and operational control expansion.
3. Introduce periodic driver compensation competitiveness review by corridor.

## SECTION 3: Required Documents

Required documents to close blockers (no new strategy; closure artifacts only):
1. Executable Provider Service Agreement (final legal fields completed)
2. Insurance certificate exhibit and coverage schedule
3. Partner-specific pilot SOW with named sites and kickoff date
4. KPI Data Dictionary v1 (source tables/fields/formulas locked)
5. AR Standard Operating Procedure with named owner and escalation ladder
6. HIPAA/legal compliance memo for partner diligence
7. Driver credential checklist + vendor/process standard
8. Communication failover SOP + drill record
9. Pricing addendum for outlier route guardrails
10. Data retention and deletion schedule + vendor inventory register
11. Exception waiver authority matrix
12. Dispatch staffing plan for pilot peak windows

## SECTION 4: Required Partner Decisions

Partner decisions required to clear launch blockers:
1. Confirm named dialysis sites in scope (up to 2 for pilot).
2. Confirm kickoff date and first recurring slot schedule.
3. Approve payment control model (deposit or ACH autopay).
4. Approve SLA assignment-time targets and escalation windows.
5. Confirm designated billing contacts and dispute contact.
6. Approve communication failover channels and acknowledgment expectations.

## SECTION 5: Required Compliance Decisions

Compliance decisions required to clear launch blockers:
1. Approve and sign legal/HIPAA posture memo.
2. Approve incident notification timing commitment and legal language.
3. Approve driver background-check vendor and standards.
4. Approve permit/licensing requirements by launch corridor.
5. Approve data retention/deletion schedule by data type.
6. Approve third-party vendor inventory and risk ownership.
7. Approve insurance minimums and certificate verification process.

## SECTION 6: First Revenue Readiness

First revenue readiness requires all items below complete:
1. Partner-specific pilot SOW signed.
2. Executable provider agreement complete and signed.
3. AR owner and backup operating with 48-hour follow-up cadence.
4. Payment control method confirmed (deposit or ACH autopay).
5. KPI dictionary locked for dispute-proof invoicing and SLA evidence.
6. Cancellation/no-show evidence rules operational and auditable.
7. Weekly invoice issue checklist and dispute handling SLA active.
8. Dispatch staffing and communication failover readiness validated.

First revenue can be declared ready when:
- First invoice is issued with complete audit trail,
- Payment-control terms are active,
- AR follow-up evidence exists within 48 hours,
- No unresolved Critical compliance blocker remains.

---

## CURRENT STATUS

RED = Cannot launch
- Legal identity/insurance completion not fully evidenced
- HIPAA/legal posture not formally issued
- Driver credential governance unresolved
- Partner-specific SOW not finalized with named sites and kickoff date
- KPI source-of-truth not formally locked

YELLOW = Can launch pilot after blocker closure
- Commercial terms and core operating policies are materially defined
- Requires closure evidence for all RED items before first live pilot

GREEN = Ready for pilot outreach
- Outreach can proceed in parallel while RED blockers are closed
- No first-live pilot start until RED transitions to YELLOW/closed
