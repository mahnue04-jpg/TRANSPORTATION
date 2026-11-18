# PR #556 — private Growth staging database acceptance gate

**Status: FRESH EXPORT AVAILABLE; RESTORE NOT VERIFIED. NO-GO for deployment.**

This document separates evidence already obtained through public GitHub CI from
unverified evidence for the **existing** Render Growth staging PostgreSQL.
It is not an authorization to connect, change networking, create backups, deploy,
run migrations, or spend money.

## Verified identities and test results (November 18, 2026)

- Existing Growth staging service: `nova-growth-validation-490`
  (`srv-dbqv8ip5efls73dtpmo0`), deployed `0ad5c5e178f260067e2a95447a01745ed2e09a8b`.
- Exact draft integration head tested: `a377b026cd8c153c7ce2b57ed40c2fbfc1c164a1`
  (PR #556 based on the deployed staging source).
- GitHub Growth run **44247449211**: four jobs passed; app **139 passed**;
  disposable PostgreSQL **7 passed**; Workspace UI and synthetic demo-report
  Node checks passed.
- This PostgreSQL job rehearsed a backup/restore with **synthetic CI fixture**
  databases. It did not back up or restore Render.
- Independently run qualification regression in **44247449261** passed;
  verify separate full backend-diagnostic conclusion at release time.

## Private Render database is not remotely queryable through hosted connector

- Existing DB: `nova-ga-490-dispos`, instance
  `dpg-dbqv7mmtlv9c73d7tnb0-a`, database `nova_ga_490_dispos`.
- Read-only metadata: PostgreSQL 18, 1 GB, available, no external allowed IPs,
  plan `0.1c-256mb`. This establishes availability and isolation **only**.
- The hosted Render MCP read-only SQL query to `alembic_version` was
  **blocked** by the empty IP allowlist. Migration version, schema integrity,
  tenant counts, existing data retention and backup recovery remain unknown.
- Do not add an external IP to the allowlist or reveal database passwords.
  Prefer a read-only inspection of Render's existing Recovery page first; use a separately approved *in-environment* private diagnostic method only if needed.

## First choice: Render's existing Recovery page (no network changes)

Before proposing a new private runner or changing Render service settings,
inspect the existing database in the Render Dashboard:

1. Open **https://dashboard.render.com/d/dpg-dbqv7mmtlv9c73d7tnb0-a**
   and select **Recovery**. Confirm the correct database identity.
2. **Read only:** record whether point-in-time recovery is available and the
   displayed recovery window; record whether existing logical exports are
   listed, their completion status and timestamps. Do not reveal backup
   download URLs, credentials, or database contents.
3. Render documents built-in continuous backups/PITR for paid Postgres and
   a **Create export** action on the Recovery page for logical backups.
   Availability must be checked on THIS account, not assumed from plan alone.
   Official reference: https://render.com/docs/postgresql-backups
4. If an export is absent or stale, **do not click Create export** until the
   owner separately approves it and any costs/retention implications are
   understood. Creating an export is a write operation against Render's
   recovery service even when the database records are unchanged.
5. **Do not click Restore Database** without specific approval. Render's
   PITR creates a separate database instance that may incur additional
   charges. A logical backup export alone is not a completed restore test.
6. After read-only Recovery page inspection, decide whether a separately
   authorized Render-managed restore to an **isolated disposable database**
   is feasible within the cost limit. Never restore over the existing
   `nova_ga_490_dispos` or any production/Studio database.
7. Only if Render-managed Recovery cannot satisfy the test should we
   consider the prewritten, separately gated private schema-inventory
   utility. It has NOT been executed and would require an approved
   in-environment execution method.

No additional Render database, public connection, backup, or recovery has
been created or started by this document.

## Owner-provided Recovery page evidence (November 18, 2026)

From the existing **nova-ga-490-dispos** Render Recovery screen, the owner
observed these settings before the subsequently approved fresh export:

- **Point-in-Time Recovery:** available for timestamps within the previous
  **3 days**. Render offers a 7-day window with a Pro workspace upgrade;
  **no upgrade approved or required** for this review.
- **Logical export list:** two existing entries were visible:
  - **November 14, 2026 at 4:47 PM**, file shown as `.dir.tar.gz`.
  - **November 12, 2026 at 9:55 PM**, file shown as `.dir.tar.gz`.
- Render UI states export files are retained **at least 7 days**.
  Presence in the list does **not** prove the files were downloaded,
  integrity-verified, or successfully restored. Their age may matter for a
  rollback of **current** data.
- No new logical export or database restore was requested. No current
  recovery-point test has occurred. As of November 18, the three-day PITR
  window does **not** reach back to either November 14 or November 12,
  although these exports are listed separately.

**Updated gate:** Recovery controls observed and fresh export available; restore success still UNVERIFIED. Do not create additional exports, initiate restores, or upgrade without separate approval. Preserve existing exports.

## Fresh export available (owner-verified November 18, 2026)

Following explicit owner approval for one logical export only, the owner
confirmed the Render Recovery UI now lists a downloadable logical export
dated **November 18, 2026 at 12:42 AM**, in .dir.tar.gz format.
The November 14 and November 12 exports remain visible. Three exports
are now listed; do not store signed/tokenized download URLs.

This is **EXPORT AVAILABLE**. It is NOT evidence of archive integrity,
schema contents, an actual restore, or a validated migration head.
No Render service, database instance, restore or deployment was created.
The owner approved only the one fresh export, NOT an isolated restore,
migration, additional paid resources or a deployment. Never put backup
archives or their signed URLs into GitHub, CI, public storage or chat.

**Remaining gate:** authorize and verify a fresh export restore to a
separate, isolated destination with a known cost and cleanup plan.
Do not restore over the existing staging database.

## Read-only restoration options review — 2026-11-18 (NO ACTION PERFORMED)

The approved fresh logical export (Nov 18, 2026 12:42 AM) is now listed
with a downloadable .dir.tar.gz archive. Only its **availability** is proven.
Its signed download URL is sensitive and must not be stored in this repo.

### Option A — Render managed point-in-time recovery, preferred for fastest isolation

Render docs confirm a PITR restore creates a **new** PostgreSQL instance, not
an overwrite of the original. Current Hobby recovery window is three days.
It tests recovery from managed PITR, **not the Nov 18 logical export**.
No PITR restore is approved. If authorized in a separate step:

1. Preflight: verify existing primary is available and original ID
   `dpg-dbqv7mmtlv9c73d7tnb0-a`; preserve unchanged DNS, credentials,
   networking, and service `srv-dbqv8ip5efls73dtpmo0`.
2. Review UI's new database name (suggest a clearly distinct
   `nova-ga-restore-verification-20261118`) and precise recovery timestamp
   **within the last three days**, not less than Render's minimum time lag.
   Do **not** select production, change the existing Growth service connection,
   or click Restore until the owner approves the exact configuration.
3. Exact billing preflight: source instance tier `0.1c-256mb` is listed
   publicly at **$6/month** plus included 1 GB storage; new restore instance
   likely bills separately while it exists. This is only a planning benchmark,
   NOT a verified checkout price or permission to incur a charge. If the
   UI demands a higher tier, additional storage, a Pro upgrade, or cost beyond
   the separately approved cap, stop with NO CHANGE.
4. Upon separately authorized restore, use read-only private diagnostics
   against the **new instance only**: database identity/version, Alembic
   version, tables and aggregate counts, synthetic-only acceptance. Do not
   print or export customer rows, passwords, or signed URLs.
5. Compare row/table counts and migrations with an authorized read-only
   original baseline; document mismatch explicitly. Success requires a
   usable restored instance plus comparable data, not merely "Available".
6. Deletion of the **named disposable restored instance** is a separate
   destructive operation requiring authorization and confirmation of its
   exact ID. Never delete the original or a production instance. Billing can
   continue until cleanup.

Official docs:
- https://render.com/docs/postgresql-backups
- https://render.com/articles/how-to-backup-and-restore-postgresql-databases
- https://render.com/pricing

### Option B — Validate the exact Nov 18 Render logical export

The downloaded `.dir.tar.gz` file contains sensitive database contents.
An exact-export recovery rehearsal would require a separately authorized
secure, isolated PostgreSQL 18 target and private archive transfer; avoid
public repositories, support tickets, CI artifacts, third-party file shares,
chat attachments and log output. Render exports use directory-format
`pg_restore` after extraction. Restore only to a newly empty disposable
target; options like `--clean` can delete existing data. Verify internal
archive structure and hash **without printing records**, restore into the
isolated target, inspect database structure/counts with read-only queries,
and preserve original staging connectivity. No actual archive download,
hashing or restore is authorized or yet performed.

### Decision boundary and safeguards

- **Existing approvals:** one fresh logical export only, already visible.
- **Not approved:** another export, download to another service, PITR or
  logical restore, new database, paid instance, migration, public networking,
  changing pinned Render service commit, customer processing or deletion.
- **Code checks:** PR #556 additive candidate passed prior CI and diagnostic,
  but passing source tests does not demonstrate real staging DB recovery.
- **Recommendation:** prefer a separately scoped, minimum-tier PITR rehearsal
  if the goal is proving Render recovery, or an exact logical export restore
  if the goal is proving the actual downloaded archive. Neither was attempted.
  Any approval must specify which proof is needed, cost cap, target and cleanup.
- **STOP** on wrong service/DB identity, new costs outside the cap, unknown
  ownership, missing recovery timestamp, backup format mismatch, schema
  divergence, external-network exposure, or any request to alter primary.

## Owner-delegated recovery follow-up — verified status, execution limitations

At the owner's request to finish the recovery inspection and arrange cleanup,
a **read-only Render audit** confirmed:

- **ORIGINAL / PROTECT**: `nova-ga-490-dispos`,
  instance `dpg-dbqv7mmtlv9c73d7tnb0-a`, **available**.
- **TEMPORARY PITR COPY ONLY**: `nova-ga-490-dispos-copy`,
  instance `dpg-dbuku8dckfvc73ch22e0-a`, internal DB
  `nova_ga_490_dispos_nu6s`, PostgreSQL 18, 1 GB,
  tier `0.1c-256mb`, **available**, created
  `2026-11-18T07:09:21.352984Z`, external IP allowlist empty.
- Render metrics show post-provisioning memory measurements for the
  temporary instance and normal connections on the original; **metrics do
  not prove restored data integrity**.
- A read-only SQL probe to the temporary database could **not connect**
  through the hosted Render tool because its IP allowlist is empty.
  That is a security safeguard; **DO NOT weaken it**.
- The connected Render API has **no private SQL execution, PITR/schema
  inspection, or PostgreSQL deletion action**. No alternate signed-in
  Render browser profile was available. No unapproved service or database
  was created to work around this.
- Consequently no verified migration head, restored row-count comparison,
  retention of customer records, or restored export integrity was obtained.
  The PITR instance being "available" is **not full restore acceptance**.
- Keep the Nov 18 logical export and existing source intact. The PITR
  rehearsal does NOT verify the exact Nov 18 export archive.

### Private validation and cost-stop handoff

1. Use an **already authorized** private-network console/runner to read
   only the temporary copy: confirm `current_database()` equals
   `nova_ga_490_dispos_nu6s`, PostgreSQL version, Alembic revision,
   table presence, and aggregate counts without exposing rows/secrets.
   A private diagnostic cannot reuse a hardcoded **original DB** identity
   guard unchanged; change/test the scope for the disposable copy without
   altering the original service or its security checks.
2. If no safe private inspection path is available, report **PITR created,
   data verification unproven**; do not claim PASS.
3. Stop temporary charges once the owner has preserved the necessary
   evidence. Deletion must target **ONLY**
   `dpg-dbuku8dckfvc73ch22e0-a` after independently re-checking both
   instance names and IDs. Never delete `dpg-dbqv7mmtlv9c73d7tnb0-a`.
   Render deletion permanently removes the copy; the connected tools
   cannot perform this action. Confirm the owner explicitly authorized
   the destructive cleanup and its exact target before the final Delete.
4. Record the deletion outcome or continued billing accurately. Until then,
   the temporary restore is **available and potentially still accruing
   prorated charges** (owner-confirmed checkout displayed $6.30/month).
   No automatic cleanup is configured.
5. Keep PR #556 draft and Render web deployment pinned until a separate
   migration/deploy acceptance. Do not merge or enable outbound providers.

## Required safe evidence before an exact-version staging update

1. Owner authorizes **read-only private diagnosis** of this named staging DB,
   from a preexisting private service or approved private runner, without
   production credentials or public network exposure.
2. Capture no PII and no secrets: PostgreSQL server version, current migration
   head(s), presence/absence of `nova_ga_campaign_asset_reviews`, number of
   existing Growth tables, table row counts only (aggregated), tenant-scope
   integrity checks, and any existing backup metadata. Do not copy records.
3. Independently prove recoverability of the **actual staging DB** to a separate,
   disposable private target under a separately approved backup/export procedure.
   Document retained recovery point, restore time, checksums/row-count validation
   and secure destruction of the *disposable* restore only. CI fixture success
   is not a substitute.
4. Review planned DDL in `20261118_nova_ga_campaign_review.py`. It creates
   `nova_ga_campaign_asset_reviews` and owner index, with a unique
   organization/campaign constraint. `downgrade()` does not delete it, so
   rolling back code does not roll back this schema.
5. Any later deploy requires a **separate explicit owner approval** of
   full commit SHA, exact service ID, no duplicate deployments, schema target,
   preserved app secrets/flags, baseline backup, allowed cost and rollback.
   Keep live SMS/email/calls, paid AI, Stripe payments, prospecting and
   retention deletion OFF. Missing or unknown flags are **not verified OFF**.
6. Run one synthetic browser/API journey after that separately approved
   staging change. Require owner authentication, website inquiry/inbox,
   consent, CRM, appointments, mock reminders, audit, cross-tenant denial,
   dispatcher denial, and campaign review staying unverified/unpublished.

## Current go/no-go

- **GO** for source review and disposable CI testing.
- **NO-GO** for live staging DB schema changes, changes to Render config,
  replacing the deployed commit, customer traffic, paid services or production.

Existing staging/Studio data and resources must remain unchanged until the
owner separately approves a precise implementation and recovery plan.
