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
  Use a separately approved *in-environment* private diagnostic/backup method.

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
