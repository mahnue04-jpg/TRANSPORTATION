# AMICOR Nova Operations Agent / Work & Revenue: staging launch decision

**Status: APPROVAL REQUIRED — no deployment, no database creation, no paid
service activation.** This document concerns the existing PR #477 -> #484
release chain only, not new agent features.

## Actual verified position (November 11, 2026)

- PR #477 (durable Work & Revenue substrate) and PR #484 (bookkeeping
  integration and owner console) remain draft, with PR #484 based on
  PR #477's development branch. Do not merge directly into `main`.
- Accounting CI tests and synthetic operator workflows pass, but the
  complete workflow has NOT been deployed to Render or verified with a
  real signed-in staging browser, real PostgreSQL and real private object
  storage together.
- Render workspace inventory shows production `amicor-prod`, separate
  `amicor-casting-staging-db`, and a PR #483 preview, but no dedicated PR
  #484 accounting staging service or database was found. Neither existing
  database is authorized for this upgrade.
- The root `render.yaml` defines existing production resources and must
  remain untouched by this staging setup.

## Proposed infrastructure — NOT APPLIED

File: `render.nova-accounting-staging.proposed.yaml`.

1. Dedicated **new** `amicor-nova-accounting-staging-db` Postgres in
   Virginia (the proposal uses a potentially billable plan).
2. Dedicated **new** `amicor-nova-accounting-staging` web service with
   automatic deploys off, accounting processing flags off, paid processing
   flags off, and both staging migration approval flags off.
3. Separately procured/configured private S3-compatible bucket with
   access restrictions, default encryption, verified deletion and retention.
   **The blueprint does not create a bucket or store credentials.**
4. Separate identity and test users; independent review of the exact
   signed-consent evidence process; use synthetic data first.

**Do not sync the proposed Blueprint or incur database/storage charges
until the owner approves the specific infrastructure and pricing.**

## Ordered acceptance criteria — only after approval

1. Review proposed database and service monthly costs, secret handling
   and public exposure; record owner approval.
2. Provision *new* isolated resources and validate their exact identities.
   Verify the environment is actually staging; no customer data.
3. Run read-only preflight and confirm approved DB name, consent/index
   columns, bucket public-access block and encryption. Its output never
   grants release permission.
4. With separate schema-change approval, execute reviewed staging-only
   Alembic migration on the new staging database, not `amicor-prod`
   or casting staging.
5. With separate permission, enable staging execution flags only for
   synthetic records and an explicitly authorized test owner.
6. In a real authenticated browser: select a saved test task; upload an
   invented transaction/receivables/payables CSV; verify one durable job
   after retry and restart; review output; approve/reject; test private
   download, other-owner denial, consent revocation, stale recovery,
   deletion/orphan handling and retention behavior.
7. Preserve a screenshot/log of actual staging behavior, changes,
   issues and rollback steps. Do not infer customer readiness from
   mocked logins or a GitHub Actions green check.
8. Prepare a production release plan with reviewed SQL/data migration,
   explicit rollback/disable strategy, and owner sign-off BEFORE merge,
   deployment, feature activation or accepting real contracted finance
   data. Contract agreement must permit third-party/AI processing.

## Current single next action

**Approve or reject the proposed cost-bearing *isolated accounting
staging* resources (new PostgreSQL, separate web service, private bucket).**
This is not consent to deploy, change environment flags, migrate schema,
process customer information or merge code.

If cost is not approved, continue only with offline synthetic CI. Avoid
pretending that the live Work & Revenue upgrade has been completed.
