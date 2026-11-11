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
