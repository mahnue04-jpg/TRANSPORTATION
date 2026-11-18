# PR #556 — private Growth staging database acceptance gate

**Status: PREPARED ONLY; NOT EXECUTED. NO-GO for deployment.**

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
