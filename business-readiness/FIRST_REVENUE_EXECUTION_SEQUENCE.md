# FIRST_REVENUE_EXECUTION_SEQUENCE

Objective: Fastest dependency-ordered path to sign the first healthcare transportation pilot.
Scope constraint: Uses only the minimum must-close blockers already identified in business-readiness/FIRST_REVENUE_BLOCKERS.md.
As-of date: 2026-05-29

## Strict Dependency-Ordered Execution Sequence

| Seq | Blocker | Exact Closure Artifact Required | Owner | Dependencies | Estimated Effort | Evidence of Completion | Next Action Executable Today |
|---|---|---|---|---|---|---|---|
| 1 | AR owner and collections workflow not operationally locked | Final AR SOP with named AR owner + backup, 48-hour follow-up cadence, escalation ladder | CFO | None | 2-4 hours | Signed AR SOP version and named owner matrix distributed | Assign named AR owner/backup and publish AR SOP v1 for sign-off today |
| 2 | Provider agreement legal identity not finalized | Executable Provider Service Agreement draft with legal entity block, registered address, signatory authority, governing law/venue completed | CEO + Compliance Officer + Legal Counsel | None | 4-8 hours | Legal-complete agreement redline accepted internally | Fill all legal entity/governing-law fields and route legal redline for same-day review |
| 3 | Insurance and certificate details unresolved in provider agreement | Insurance exhibit pack (COI schedule + policy identifiers) mapped to provider agreement exhibit | Compliance Officer | Seq 2 | 4-8 hours | Insurance exhibit attached to agreement and accepted by legal | Compile active insurance documents and map each policy field to contract exhibit today |
| 4 | Missing formal HIPAA/legal posture | Signed HIPAA/legal compliance memo covering PHI scope, incident notification, retention posture, subprocessors | Compliance Officer | None | 6-10 hours | Final signed memo added to partner diligence packet | Draft memo using existing security/privacy one-pager inputs and submit for compliance signature today |
| 5 | Data retention/deletion and vendor inventory not finalized | Approved retention schedule by data class + vendor inventory register with risk owner per vendor | Compliance Officer | Seq 4 | 6-10 hours | Versioned retention matrix and vendor register approved and linked in diligence pack | Publish retention matrix template and vendor register template; populate top-priority vendors today |
| 6 | Driver credential governance unresolved (background checks/permits) | Driver credential governance packet: mandatory checklist, approved background-check vendor, permit/renewal cadence, go-live gate | Operations Director + Compliance Officer | Seq 4 | 8-12 hours | Credential policy approved + launch cohort compliance checklist issued | Finalize credential checklist and lock approved screening vendor/renewal cadence today |
| 7 | KPI source-of-truth schema not locked | KPI Data Dictionary v1 mapping each KPI to system source fields/tables with Ops/Finance/Compliance sign-off | COO + Operations Director | None | 6-10 hours | Signed KPI dictionary v1 published in readiness package | Create KPI dictionary v1 sheet and complete field-level mapping for all contract KPIs today |
| 8 | Manual dispatch staffing proof not defined for upper-volume scenario | Dispatch staffing plan with dispatcher-to-active-trip ratio and pilot peak shift roster | Operations Director | Seq 6, Seq 7 | 4-8 hours | Staffing model and week-1 peak roster signed off | Build pilot peak-hour roster and document dispatcher coverage ratio today |
| 9 | Communication failover matrix undefined | Communication failover SOP (portal/SMS/phone escalation) + drill log template and completed drill record | Operations Director | Seq 8 | 4-8 hours | Approved failover SOP and completed drill record attached | Draft failover matrix and schedule same-day tabletop drill with acknowledgment logging |
| 10 | Pilot proposal missing partner-specific site names and kickoff date | Partner-specific pilot SOW/addendum with named sites, kickoff date, weekly slot plan, and aligned KPI references | CEO + COO | Seq 2, Seq 3, Seq 4, Seq 5, Seq 6, Seq 7, Seq 8, Seq 9 | 6-12 hours (internal prep) + external turnaround | Countersigned SOW/addendum (or written partner approval pending signature) | Populate SOW template with named site placeholders, kickoff options, and weekly slot plan; issue to partner today |

## PHASE 1: Items That Can Be Completed In 24 Hours

These are fully internal closure items that can be completed without partner approval if owners execute immediately.

1. AR owner and collections workflow not operationally locked (Seq 1)
2. Provider agreement legal identity not finalized (Seq 2)
3. Insurance and certificate details unresolved in provider agreement (Seq 3)
4. Missing formal HIPAA/legal posture (Seq 4)
5. Data retention/deletion and vendor inventory not finalized (Seq 5)
6. Driver credential governance unresolved (Seq 6)
7. KPI source-of-truth schema not locked (Seq 7)
8. Manual dispatch staffing proof not defined for upper-volume scenario (Seq 8)
9. Communication failover matrix undefined (Seq 9)

## PHASE 2: Items That Can Be Completed This Week

This is the internal hardening window to finalize and package all signature prerequisites into one executable signature pack.

1. Reconfirm all Seq 1-9 artifacts are signed/versioned and cross-linked in one diligence package.
2. Complete final legal/compliance quality check of agreement + exhibits + compliance packet.
3. Freeze pilot signature pack version for partner execution.

Primary blockers finalized in this phase:
- Seq 1 through Seq 9 (if not closed in first 24 hours)

## PHASE 3: Items Requiring External Partner Approval

These require partner-side action and are the final gate to signature.

1. Pilot proposal missing partner-specific site names and kickoff date (Seq 10)
- External output required: countersigned SOW/addendum with named sites and kickoff date.

## Fastest Path To Signature (Dependency Gate View)

Gate A (internal legal/compliance foundation): Seq 2, Seq 3, Seq 4, Seq 5
Gate B (operational readiness foundation): Seq 1, Seq 6, Seq 7, Seq 8, Seq 9
Gate C (external signature gate): Seq 10

Strict order to execute:
1) Close Gate A and Gate B in parallel by dependency order above.
2) Submit Gate C signature pack immediately after Gate A/B completion.
3) Signature achieved when Seq 10 evidence is complete.
