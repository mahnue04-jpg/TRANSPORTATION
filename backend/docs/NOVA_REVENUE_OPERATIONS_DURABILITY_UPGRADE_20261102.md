# AMICOR Nova — Work & Revenue + Operations Agent durability upgrade
Date: 2026-11-02 | Status: design proposal, **not implemented** | Owner approval required for merges, deploys, external sends and paid tools.

## Why
RCAP's Nov 2 CRM assessment feedback identified missing verifiable comparable delivery experience, including bespoke CRM systems and ASP.NET/Telerik. Improve demonstrated delivery quality and reliability, not marketing claims. Do not claim new technology credentials from this plan.

## Existing foundations (verified)
- `backend/docs/NOVA_WORK_REVENUE_ENGINE.md`: tenant-scoped `/api/nova/work`, owner board, opportunities, qualification, application drafts, engagements, tasks, deliverables, reconciliation, business-fact and policy catalog. Live discovery/submission/payment/report-send flags OFF. Approval is NOT send; delivered is NOT paid.
- Draft PR #338: first-client owner board, deduplication across scheduler periods, eligibility explanations, consent-gated mock receipts. 34 local tests reported; work-revenue and qualification CI green; broader backend diagnostic has a Studio regression. Not production-ready.
- `website/nova-operations/index.html`: research/reports, spreadsheets/admin, CRM/workflow assessment, trial/demo and publicly listed $49 one-time, $99/month, $299/month starting offers. Confirm pricing against current app before quoting.
- Issue #371: integration and first-customer validation. Studio repairs stay in their own lane.

## Proposed integrated system
```
Verified lead -> qualification -> human-reviewed scope -> proposal draft
 -> owner-approved, verifiably sent proposal -> response / discovery
 -> approved engagement + acceptance checklist -> Operations Agent job
 -> reproducible output + source evidence -> QA -> owner approval
 -> customer delivery receipt -> invoice support -> independently confirmed payment
 -> customer-permitted case study
```
Every transition stores tenant, actor, timestamp, immutable event ID, source evidence, idempotency key and policy decision. Never promote inferred events to verified ones.

## Upgrade 1 — Durable Work & Revenue (P0)
1. **Persistent lead provenance**: canonical URL, observed date, eligibility quotation, budget currency, location/remote requirements, deadline and stale-source state. Never infer qualification from title alone.
2. **Event-based pipeline**: distinguish DISCOVERED, VERIFIED, QUALIFIED, DRAFTED, OWNER_APPROVED, SENT_VERIFIED, REPLIED, DISCOVERY, SCOPED, CONTRACTED, DELIVERED, INVOICED, RECEIVED_VERIFIED, LOST. Require verifiable outbound receipt for SENT_VERIFIED; do not transform MOCK_RECEIPT to sent.
3. **Idempotency**: unique tenant + opportunity source + canonical posting ID; transactional upsert; deduplicate scheduled retries, replies and application attempts. Preserve evidence on restart.
4. **Safe sending**: explicit owner consent per destination and proposal; authenticated permitted transport only; platform rules checked; dry-run default. No bypass of login/CAPTCHA or paid applications.
5. **Follow-up board**: real inbox response linking by message/thread IDs, review-before-follow-up, deadlines and pause/opt-out. No autonomous repeated cold outreach.
6. **Financial integrity**: distinct estimated, quoted, contracted, invoiced and owner-confirmed received amounts; currency/partial payments/refunds; never double count. Commission income tracked separately from services, only when payable/received evidence exists.
7. **Owner dashboard**: show stage, source, blockers, owner action, aging, next follow-up, real sends, verified replies, paid pilots and cash received. Mobile reload consistency.

## Upgrade 2 — Durable Operations Agent (P0)
1. **Scoped job contracts**: client/tenant, input type, explicit allowed actions, deliverables, acceptance criteria, due date, budget ceiling, data classification and retention policy.
2. **Persistent execution**: queued/running/needs-review/failed/cancelled/completed states; durable checkpoints, resumable jobs, lease/timeout, bounded retries and dead-letter queue; no duplicated external actions after retry.
3. **Reproducible tool execution**: versioned workflow and input fingerprint, sandboxed file transformations, deterministic validations, output checksum, logs without secrets or customer contents.
4. **Spreadsheet workflow**: type/schema inference with review, duplicates/nulls/errors report, reversible transformations, before/after row counts, downloadable .xlsx and audit manifest.
5. **Research workflow**: every material claim cites an accessible source and observation date; freshness warnings; unsupported claims flagged for human review; no invented citations.
6. **CRM workflow**: CSV import preview, field mapping, duplicate detection, consent and provenance flags, reversible export; NO live write to Salesforce/HubSpot/custom CRM until connector, permissions and rollback are independently validated.
7. **Document/customer-support workflow**: templated draft with extracted facts and uncertainty; human approval; no automatic external sending.
8. **Quality gate**: pass/fail rubric, artifact checks, privacy and source verification, reviewer signoff, client-ready export; distinguish draft vs approved vs delivered.
9. **Tenant security**: cross-tenant 404, least privilege, file-type/size controls, malware scanning plan, encrypted storage, retention/erasure audit, redacted telemetry and no secrets in logs.
10. **Cost controls**: provider registry OFF by default, preflight estimate, atomic reservation/claim, max spend, cancellation and unverified-charge state. No paid provider activation without owner approval.

## Shared contract between products (P0)
- `Opportunity` -> `ApprovedScope` -> `Engagement` -> `OperationsJob` -> `ReviewedDeliverable` -> `DeliveryEvidence` -> `RevenueEvent`.
- Shared IDs, tenant ownership, actor identity, immutable event timestamps, data classifications and evidence refs.
- Versioned schemas; additive migrations first, rollback path and no destructive migrations in first release.
- A delivered file is not a paid invoice; a signed referral agreement is not a paid commission.

## Implementation sequence (isolated PRs, no merge without approval)
A. Baseline tests and integration inventory: reproduce Work & Revenue CI and Studio regression; map existing Operations endpoints and persistence.
B. Add shared typed contracts and **offline** fixture tests only; backward compatibility.
C. Durable event ledger/idempotency for Work & Revenue, no outbound transport.
D. Durable Operations job queue and three local fixture workflows; no customer data.
E. Owner review, QA artifacts and demo dashboard; test on phone and desktop.
F. Authenticated staging integration with synthetic fixtures, rollback drill and security review.
G. Controlled opt-in real-customer pilot after owner approval and documented terms.

## Acceptance tests
- Duplicate scheduler runs and retries create one lead and one send record; 0 sends without consent/transport.
- Process restart preserves jobs, statuses, files, citations and event history.
- Failed jobs retry within limits and never silently mark complete.
- Cross-tenant reads/writes denied, unsafe URLs blocked, sensitive fields redacted.
- Spreadsheet fixture: stable input/output checksum, row counts, errors, undo artifact.
- Research fixture: no uncited substantive claims; date/source traceability.
- CRM fixture: mapping preview, duplicate report, reversible export; no external write.
- Reviewer can reject/rework; no delivery or revenue without separate evidence.
- Mobile owner board and download work after reload; no Studio regression.
- All tests in dedicated CI jobs with commit SHA, test count and reproducible artifacts.
- Zero live provider calls and zero external sends in CI.

## Customer proof and positioning
Build three synthetic, clearly labeled demos: spreadsheet cleanup, sourced research, CRM data hygiene. Then seek small paid, human-supervised assignments; obtain customer permission before publishing any case study. Do not advertise ASP.NET/Telerik implementation, guaranteed revenue, autonomous submissions or regulated services without proof.

## Gates
No merge, production deploy, paid generation, new subscription, secrets, customer data import, autonomous outreach, payment or commission recognition authorized by this document. Existing Creative Studio and Nova Intelligence feature flags remain unchanged.
