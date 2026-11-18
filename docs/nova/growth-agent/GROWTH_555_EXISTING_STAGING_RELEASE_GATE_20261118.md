# PR #555 — existing Growth staging release gate (2026-11-18)

**State:** READ-ONLY INVENTORY COMPLETE; **NO DEPLOYMENT OR MIGRATION APPROVED**.
This document is an operator release plan, **not** an executable Render Blueprint or authorization.
Source of truth: read-only Render workspace inspection and GitHub CI at the pinned commits below.
Never infer that a successful CI check means the new code has reached the deployed service.

## Confirmed existing target (do not create duplicates)

- Confirmed owner workspace: **Saye's workspace**, `tea-d8oe81b7uimc739gujp0`.
- Web service: `nova-growth-validation-490`, `srv-dbqv8ip5efls73dtpmo0`.
- Existing Render URL: `https://nova-growth-validation-490.onrender.com`.
- Auto-deploy: **off**. Current configured Git branch: `feature/growth-owner-website-inbox-api-20261115`.
- Current live deployment: `dep-dbt9m861egvs73fra2hg`, commit
  `0ad5c5e178f260067e2a95447a01745ed2e09a8b` (Nov 16).
- Existing build/start commands explicitly **require that older exact commit**.
  Deploying #555 without a separately reviewed change to the service branch and
  both commit guards will fail, and changing the guards alone is not sufficient.
- DB: `nova-ga-490-dispos`, `dpg-dbqv7mmtlv9c73d7tnb0-a`,
  database `nova_ga_490_dispos`; database **available** as of read-only inspection.
  The startup script validates this dedicated host and database; preserve this
  check when planning any later deployment.
- Render web service plan: `0.5c-512mb`; DB plan: `0.1c-256mb`.
  Both are not shown as free plans; exact ongoing charges were **not** retrieved.
- Current PR #555 candidate: `4350e638873176321fa039d4e228be29ef88bcd5`.
  PR #555 is open/draft and stacked on open/draft Growth MVP #490.
- CI at candidate: Growth Agent workflow run `44245199941` **three jobs
  succeeded**; backend diagnostic run `44245199913` **both jobs succeeded**.
  This proves tested source, NOT a running deployed revision.

## Critical ancestry check — STOP direct deployment

Read-only GitHub comparison on November 18:

- Deployed staging SHA: `0ad5c5e178f260067e2a95447a01745ed2e09a8b`.
- Candidate documentation head: `9f33e6e9d30ef6cdb9672ca5cb30ec28595dc59b`
  (tested app ancestor: `4350e638873176321fa039d4e228be29ef88bcd5`).
- GitHub result: **DIVERGED**, common ancestor
  `e4d0aec2e37af6b23e107c71c03eadf01d586287`.
- Candidate is **28 commits ahead** of the common ancestor; deployed staging
  has **72 additional commits** not contained in the candidate branch.
- Comparing toward staging identifies important files absent from the candidate:
  `website_inquiries.py`, `website_kv_source.py`,
  `staging_preflight.py`, `staging_start.py`, owner inbox/Workspace
  JavaScript and tests, lifespan guards, plus changes to `app/main.py`,
  `router.py`, auth tests and CI. The comparison does **not** prove that all
  these features still operate; it proves a direct candidate deploy risks loss.
- Comparing toward #555 identifies new campaign registry, preview, migration,
  synthetic reporting and tests. Neither branch is a simple successor to the
  other. **Do not deploy #555 directly or just repin the current service.**

### Required integration release branch before owner deployment approval

1. Start from the exact **currently deployed staging** SHA to preserve its
   website inbox, staging preflight/start, and operational workflow. Use an
   isolated **new Git branch only**; do not change Render.
2. Integrate the #555 feature commits with an explicit three-way review against
   the shared ancestor, paying particular attention to `router.py`,
   `tenant.py`, `test_nova_growth_agent_http.py`, and both CI workflows.
   Keep the stricter admin role gate, tenant isolation and optional review
   queue disabled by default. Do not overwrite the deployed website inbox.
3. Reconcile Alembic: inspect current deployed revision and schema in a
   disposable **restore**; compare the proposed campaign table migration.
   Never silently run an unapplied revision on the existing DB.
4. Run combined Growth, website-inbox, Workspace owner, migrations, Postgres,
   cross-page, Studio and Work & Revenue regressions on the combined branch.
   Verify public and owner routing, cancel/reschedule/dedup, synthetic only.
5. Produce one full-length candidate SHA and a reviewed exact diff against the
   deployed staging SHA; separately verify backups, recovery procedure, costs,
   service branch/pin changes and required feature flags.
6. Only then request new explicit approval for **one** isolated staging update.
   This document grants no such approval.

## Explicit blockers before any in-place release

1. **Version gap**: inspect the exact diff and ancestry between the deployed
   `0ad5c5e` and the proposed candidate. Reconcile the staging branch, PR
   #490 dependency, and PR #555 before editing Render settings; avoid dropping
   earlier website-to-owner-inbox behavior.
2. **Snapshot/restore proof**: verify a recoverable database backup **and an
   actual disposable restore rehearsal**. Existing database availability
   does not prove backup, recovery point or restore ability. Capture row counts,
   schema and migration head BEFORE any change, without exposing PII.
3. **Migration approval**: existing startup advances Alembic only through
   `20261112_nova_ga_retention`. PR #555 adds
   `20261118_nova_ga_campaign_review` which creates
   `nova_ga_campaign_asset_reviews` when applied; the revision is additive
   but `downgrade()` intentionally does NOT remove it. Never silently run
   `alembic upgrade heads` on this existing database. Specify and separately
   approve the exact migration target and expected DDL, test against restored
   disposable data, and provide a manual rollback protocol.
4. **No implicit rollout**: do not apply the old
   `render.nova-growth-staging.yaml` blueprint—it describes a *different*
   proposed service/database and could create duplicates. Prepare a proposed
   in-place plan only after exact current service settings and rollback are
   captured; require a clean diff.
5. **Configuration freeze**: keep auto-deploy off, one instance and existing
   PostgreSQL destination. Preserve current secret values without reading,
   logging or exporting them. Explicitly require all live SMS/email/calls,
   paid AI, Stripe, prospect outreach and retention deletion OFF; mock worker
   and retention schedule settings must remain unchanged unless individually
   approved. Treat any unverified flag as **unknown**, not as OFF.
6. **Studio bridge**: PR #555's campaign IDs are **unverified opaque references**.
   No asset may be called approved or published without server-verified Studio
   ownership and grant records, independent of a caller-supplied ID.
7. **Cost / blast radius**: retrieve exact cost impact before approval; no new
   instances, DBs, providers, or billing actions.

## One controlled acceptance sequence, once separately authorized

- Record baseline live commit, readiness HTTP response, auth role, table/schema
  checks, configured branch/commit guard, service and DB state, and snapshot ID.
- Deploy **once** with exact approved full SHA and pinned branch after a clean
  plan review. Avoid duplicate deploys or CI-triggered auto-deploy.
- Prove port 10000 or `$PORT` readiness and inspect startup logs; stop on
  guard mismatch, Alembic error, DB host mismatch or unexpected spend.
- Use **synthetic users/contacts only**: owner login; widget FAQ/AI disclosure;
  deduplication; consent and opt-out; CRM qualification; slot availability;
  booking, cancellation and reschedule; mock reminder; worker lease/restart
  recovery; audit/analytics; tenant-crossing and dispatcher-role denials.
- Verify review-queue feature is default OFF, or if separately approved to
  enable, that the table exists, records remain `verification_pending`, and
  no asset ingestion, publishing, paid charge or outbound contact occurs.
- Confirm the **previous committed data** is intact before and after; retain
  the original deploy and backup until acceptance is signed off.
- Report per-step PASS/FAIL, actual commit and deployed URL, DB preservation,
  logs/redacted evidence, rollback status, and explicit GO/NO-GO.

## Rollback and stop rules

If startup, auth, migration, tenant isolation, data preservation, or spending
constraints fail, **stop**; no retries that could duplicate work. If the schema
was changed, reverting the web commit does not undo DDL; execute only the
separately approved recovery method. Never delete or replace the Growth staging
DB, Creative Studio SQLite/projects/media, or any production resource.

## Scope of authorization

Owner confirmation of the Render **workspace** authorized read-only inventory
only. No authorization has been granted for merge, branch/pin editing,
Blueprint apply, deployment, database migration, secrets update, live provider,
customer communication or spend. Require a new explicit decision referencing
the exact service `srv-dbqv8ip5efls73dtpmo0`, candidate SHA, migration scope
and accepted rollback before any change.
