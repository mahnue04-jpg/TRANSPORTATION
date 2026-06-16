# LAUNCH RISK AUDIT

## Audit Lens
Independent healthcare transportation investor, pilot partner, and operations auditor review of:
- business-readiness/AMICOR_OWNER_DECISION_PACKET.md
- business-readiness/12_Pricing_Framework_Draft.md
- business-readiness/02_Independent_Contractor_Driver_Agreement.md
- business-readiness/04_Cancellation_Policy.md
- business-readiness/05_No_Show_Policy.md
- business-readiness/01_Provider_Service_Agreement_Template.md
- business-readiness/09_Pilot_Program_Proposal.md
- business-readiness/16_KPI_Tracking_Dashboard_Specification.md

This document challenges assumptions and decisions before pilot agreement signature.

## Risk Findings

### 1) Unrealistic Assumptions

Issue: Baseline KPI assumptions appear synthetic rather than verified from local corridor pilot history.
Why it is a risk: If baselines are not real, targets can be either too easy (false confidence) or impossible (rapid breach), causing partner trust erosion.
Severity: High
Recommended correction: Require 2-week pre-pilot shadow-baseline using current dispatch data or conservative proxy from local operations before contract KPI commitment.

Issue: Queue-to-assignment target of <=90 minutes may be too slow for time-sensitive dialysis operations in high-density time windows.
Why it is a risk: Facilities may view this as unacceptable for care continuity and reject pilot.
Severity: High
Recommended correction: Set corridor launch target of <=60 minutes during operating windows and <=45 minutes in peak treatment windows.

Issue: 6-week pilot duration assumes enough cycle depth for recurring care reliability proof.
Why it is a risk: Dialysis recurrence and payer/provider decision-making may require longer trend confidence than 4 active weeks.
Severity: Medium
Recommended correction: Keep 6-week initial pilot but include auto-extension clause to 10-12 weeks for KPI validation without renegotiation.

### 2) Revenue Risks

Issue: USD 68 flat one-way rate may be underpriced for outlier trip lengths and return deadhead conditions.
Why it is a risk: Margin compression can occur immediately on non-standard routes and create hidden losses.
Severity: High
Recommended correction: Add mileage/time guardrail clause (for example, trip distance cap or surcharge band beyond threshold).

Issue: Weekly minimum invoice floor is waived in first two weeks.
Why it is a risk: Earliest launch period is highest fixed-cost period; waiving floor increases probability of negative contribution.
Severity: Medium
Recommended correction: Replace full waiver with partial floor (for example 50%) and recoverable onboarding credit tied to volume achievement.

Issue: Cancellation/no-show fee economics may incentivize disputes and fee reversals.
Why it is a risk: Realized invoice values may fall below assumed billed values, weakening first-revenue timeline.
Severity: Medium
Recommended correction: Add non-discretionary evidence standard and explicit fee adjudication SLA with default acceptance rules.

### 3) Cash Flow Risks

Issue: Net 15 with 7-day dispute window may still push first cash receipt beyond week 5-6 depending partner AP cycle.
Why it is a risk: Early-stage company may face working-capital stress before meaningful collections.
Severity: High
Recommended correction: Include pilot prepayment/deposit option (for example one-week estimated volume reserve) or weekly ACH autopay requirement.

Issue: Late fee (1.5% monthly after grace) has low practical collection leverage in healthcare AP environments.
Why it is a risk: Does not materially improve payment velocity in pilot stage.
Severity: Medium
Recommended correction: Add service-continuation control clause: unresolved overdue balance can trigger controlled volume throttle after notice.

Issue: AR ownership is identified as required but not operationally locked in agreement materials.
Why it is a risk: No single accountable owner means delayed follow-up and missed first revenue milestone.
Severity: Critical
Recommended correction: Name AR owner and backup in agreement and onboarding packet with a 48-hour post-invoice follow-up cadence.

### 4) Operational Risks

Issue: Manual dispatch model with recurring dialysis peaks may not sustain reliability at upper volume (70 one-way trips/week) without staffing model proof.
Why it is a risk: SLA misses in early weeks can trigger partner confidence loss before first invoice.
Severity: High
Recommended correction: Define required dispatcher-to-active-trip ratio and staffing plan by peak hour before launch.

Issue: Provider notification SLA is set (10 minutes) but communication channel failover is undefined.
Why it is a risk: Missed notifications during outages create clinical coordination failures.
Severity: High
Recommended correction: Add mandatory failover matrix (portal, SMS, phone escalation) with acknowledgment tracking.

Issue: Exception override authority is referenced but not concretely bounded.
Why it is a risk: Inconsistent policy application leads to billing disputes and perceived unfairness.
Severity: High
Recommended correction: Define override authority tiers, required documentation, and weekly override audit.

### 5) Driver Retention Risks

Issue: Base payout may be uncompetitive in some suburban corridors when wait/idle time is high.
Why it is a risk: Driver acceptance and retention could deteriorate after week 2, damaging recurring rider reliability.
Severity: High
Recommended correction: Introduce minimum guaranteed hourly floor for assigned duty windows or acceptance bonus for recurring blocks.

Issue: Strict no-show disciplinary thresholds without explicit remediation/training step.
Why it is a risk: Rapid suspension/termination in thin driver markets can reduce network coverage.
Severity: Medium
Recommended correction: Add structured remediation stage before suspension for first threshold event unless safety critical.

Issue: Cancellation compensation to drivers may not fully offset repositioning cost.
Why it is a risk: Drivers may avoid high-risk schedules with frequent changes.
Severity: Medium
Recommended correction: Add graduated cancellation payout when driver has already traveled >X minutes or distance.

### 6) Partner Adoption Risks

Issue: Provider agreement still contains unresolved legal identity and insurance artifacts.
Why it is a risk: Procurement/legal cannot execute; pilot signature delayed.
Severity: Critical
Recommended correction: Complete legal entity block, insurance certificates, and governing-law finalization before outreach close.

Issue: Pilot proposal lacks named sites and exact kickoff date.
Why it is a risk: Partner views proposal as non-binding and non-operational.
Severity: Critical
Recommended correction: Convert proposal into partner-specific statement of work with facility names, launch date, and agreed weekly slots.

Issue: Fee policy complexity may be perceived as punitive for care settings.
Why it is a risk: Adoption friction from care coordinators and administrators.
Severity: Medium
Recommended correction: Add initial 14-day policy grace period with transparent education and warning-mode for first infractions.

### 7) Compliance Risks

Issue: HIPAA/legal posture is still listed as missing in security one-pager dependencies.
Why it is a risk: Healthcare facility partner legal review can halt pilot.
Severity: Critical
Recommended correction: Issue signed legal compliance memo covering PHI handling scope, BA/contract posture, retention, incident notification, and subprocessors.

Issue: Background check process/vendor and permit requirements remain unresolved in driver framework.
Why it is a risk: Exposure to regulatory and safety non-compliance.
Severity: Critical
Recommended correction: Publish mandatory credential checklist, approved vendor, renewal cadence, and go-live gate enforcement.

Issue: Data retention/deletion schedule and vendor inventory not finalized.
Why it is a risk: Security due diligence failure and grant compliance weakness.
Severity: High
Recommended correction: Finalize retention policy by data class and third-party register with risk owner per vendor.

### 8) Scalability Risks

Issue: Flat-rate single-class pricing has no corridor or complexity segmentation.
Why it is a risk: As route variance grows, margins become unpredictable and scale becomes loss-making.
Severity: High
Recommended correction: Add phase-2 pricing bands by zone/time and route complexity after first 30 days of data.

Issue: KPI system lacks finalized source-of-truth schema references.
Why it is a risk: Scaling partner portfolio without data governance creates reporting disputes and weak renewal outcomes.
Severity: High
Recommended correction: Lock KPI data dictionary to explicit source tables/fields and publish version-controlled metric governance log.

Issue: Manual operations dependency not linked to scale trigger thresholds.
Why it is a risk: Growth can outpace control capacity and degrade service.
Severity: Medium
Recommended correction: Define explicit scale trigger points (for example active rides per dispatcher) and pre-approved staffing/automation steps.

## GO / NO-GO Recommendation
Recommendation: NO-GO (conditional)

Rationale:
- Commercial framework is substantially improved, but signature-critical legal/compliance and pilot-specific execution artifacts remain unresolved.
- Highest launch blockers are in legal completion, compliance certainties, AR ownership, and partner-specific SOW precision.

Go conditions to clear NO-GO:
1. Complete provider agreement legal identity, insurance, governing-law fields.
2. Finalize HIPAA/compliance position and driver credential governance.
3. Name AR owner and enforce payment-control mechanics.
4. Issue partner-specific pilot SOW with named sites and kickoff date.
5. Lock KPI source-of-truth and dispute-proof reporting logic.

## Top 10 Issues That Would Prevent Successful Launch
1. Unfinalized legal entity/insurance/governing-law details in provider agreement.
2. Missing formal HIPAA/legal compliance posture for partner diligence.
3. Missing AR single-threaded ownership and payment escalation execution.
4. Partner proposal not finalized with named sites and definitive kickoff.
5. KPI data source-of-truth not fully locked for contractual reporting.
6. Driver credentialing process/vendor/permit requirements unresolved.
7. Flat-rate model lacks outlier route protection bands.
8. Dispatch staffing model not proven for peak recurring dialysis loads.
9. Exception override governance insufficiently constrained/audited.
10. Early cash conversion risk due to AP timing and limited payment controls.
