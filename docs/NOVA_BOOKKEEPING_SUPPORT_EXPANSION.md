# Nova Operations Agent — Bookkeeping Support Expansion (Draft)

**Branch:** `nova/bookkeeping-support-review-workflow-20261110`  
**State:** development-only; not deployed or integrated into a customer route.

## Business objective
Win authorized direct-client work with realistic deliverables and verifiable
execution, rather than matching job listings on keywords alone.

## Implemented first work block
`app.core.nova.work_revenue.bookkeeping_workpaper.build_bookkeeping_workpaper`
accepts transaction CSV and optional bank-statement CSV with exact required
headers `date,description,amount,reference`; dates must be ISO and amounts must
be finite with at most two decimal places. Its output is an owner-reviewed draft
workpaper with source row IDs, keyword-based category suggestions, issue flags,
signed totals, and exact-reference/date/amount bank matching checks.

Security and accuracy measures: byte/row/field limits, CSV structure checks,
duplicate detection, no silent bank match on missing reference, formula escaping,
and no secrets/logged transaction data. No remote API or money movement.

### What this does NOT establish
- No verified browser upload, authenticated organization scoping, or secure
  persistence. These are required before handling customer financial records.
- No GAAP ledger, QuickBooks or bank integrations, full reconciliation, payroll,
  tax advice, tax filing, regulated accounting, or payment execution.
- No tested real-customer outcomes, CPA qualification, or permission to substitute
  the agent for a named human contractor.
- No confirmation that BELAY permits agent-led delivery or subcontracting.
- The catalog currently describes additional service families but does not
  prove their full live delivery capability.

## Next gated work blocks
1. Add authenticated, tenant-scoped job workflow and private source/artifact
   storage; duplicate-job prevention and approvals before final export.
2. Add transaction mapping review, account coding options, period close
   checklist, transparent exceptions, independent fixture and property testing.
3. Build audited integration adapters for authorized read-only source records
   and a staged end-to-end upload → workpaper → human approval → download flow.
4. Validate with an accountant/bookkeeper using synthetic cases and explicit
   customer scope, then obtain owner approval before any release.
5. Search direct-client contract scopes for transaction cleanup, invoice
   tracking, expense indexing, and reporting, but label readiness honestly.
   Do not submit applications or accept paid work absent proven capability,
   permitted AI assistance, and explicit business approval.

## Contract qualification rule
Distinguish **independent business service contracts** from positions that
require an individual qualified bookkeeper. Mandatory human qualifications
and client restrictions on AI/subcontracting are hard blockers.


## Second development block: accounts receivable
`bookkeeping_receivables.build_receivables_aging` makes an offline review-only
invoice workpaper from six exact columns:
`invoice_id,customer,invoice_date,due_date,amount,paid`.
The required `as_of` date controls current, 1–30, 31–60, 61–90 and 91+ day
aging buckets. Negative values, overpayments, invalid dates, invalid precision,
future-dated invoices and repeated invoice IDs receive rejection or review
flags as appropriate. Outstanding amounts are computed with `Decimal`.
No payment collection, outgoing communications or external ledger posting.

## Structured contract authorization / Work & Revenue interface
`bookkeeping_assignment.BookkeepingAssignment` uses exact identifiers and
an allowlisted work type, rather than a fuzzy text-match alone. Before
`prepare_assignment_draft` will run, it requires:
- organization, owner, engagement and task identifiers
- the exact work type named in the contracted work-type set
- affirmative permission to use AI assistance and handle the data
- mandatory human review
- absence of unsupported financial duties (payroll, full-cycle accounting,
  final bank reconciliation, tax or 1099 filing, money movement)

The dispatcher only returns `AWAITING_HUMAN_REVIEW` and
`delivery_allowed=False`. It is a *pure offline adapter* and neither
authenticates users nor confirms the engagement is currently active.
Those checks belong to the existing authenticated durable CSV pathway.

### Integration with draft PR #477 (not yet completed)
PR #477 already includes a separately gated owner-scoped PostgreSQL job
system and S3-compatible private artifact adapter. It has a **different base
branch** from this PR #483. Do not merge PR #483 straight into PR #477 or
assume that their database/storage paths are compatible. Integration work:
1. Rebase onto the reviewed intended shared base and resolve existing
   Work & Revenue route / schema differences explicitly.
2. Add a server-side structured allowed-work-type field tied to an actual
   active, unblocked engagement and eligible task; never trust a browser
   boolean as proof of contract permission.
3. Add a secure original-source file retention policy, object integrity
   verification, private output and status records; no sensitive CSV in logs.
4. Extend durable DB metadata to distinguish workpaper types and source
   hashes; use separate idempotency keys bound to tenant, owner, scope,
   input and contract authorization version.
5. Protect with real-session cross-tenant and negative authorization tests.
6. Verify S3 encryption/retention, interrupted uploads, database migrations,
   restart recovery, orphan cleanup, authorized download, and owner approval
   before staging acceptance. Keep feature flags default-off.

### Evidence summary
- GitHub Actions bookkeeping workflow for commit `3ffc9cce` completed
  SUCCESS, covering the earlier transaction / receivables test sets.
- The newly added structured authorization tests require their own fresh
  workflow result. Do not claim the whole PR passed based on prior commits.
- No staging configuration or real customer credentials were used.

## Practical opportunity boundaries
Appropriate trial scopes after staging security validation include supervised
expense categorization, invoice-index preparation, aging drafts and exception
reports. A named individual bookkeeper role with mandatory experience,
undisclosed AI usage, or unsupported full-cycle duties is **not** qualified
merely because the capability catalog contains a bookkeeping keyword.
