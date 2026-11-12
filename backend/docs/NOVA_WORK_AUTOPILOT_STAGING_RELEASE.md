# AMICOR Nova Work & Revenue — Scheduled discovery staging release gate

**Status: CODE IN DRAFT; NO SCHEDULER DEPLOYED.**

This is for PR #338 on top of existing Work & Revenue discovery and
qualification logic. Its purpose is to make finding legitimate paid work a
bounded, auditable owner-review routine. It does not submit applications,
promise client revenues, contact prospects, execute finance, or auto-accept
contracts.

## Implemented in this draft

- Pure preflight `autopilot_staging_guard.inspect_configuration`: must be
  in an explicitly marked staging environment, staging flag must be true,
  named PostgreSQL database must be separately approved, and exact owner/org
  identifiers must be provided.
- Runnable `backend/scripts/nova_work_autopilot_staging.py`. In its
  **default disabled state**, it reports BLOCKED before importing the DB
  engine or contacting opportunity providers.
- At **5 AM America/Chicago only**, a connected staging run verifies the
  actual PostgreSQL `current_database()` and checks that the saved owner
  account is active/verified and belongs to the configured organization.
- Acquires a PostgreSQL advisory lock for the owner/day and commits a durable
  owner-scoped `AUTO_DISCOVERY` period record BEFORE source queries.
  The existing unique database index prevents repeat runs after restart.
  A crash may leave RUNNING; human review is then required before retry.
- Reuses bounded existing `run_autopilot_cycle`:
  max 3 search families, 5 per query, 8 saved, 3 prepared application
  workspaces, relevance threshold 85/100. Source capability, eligibility and
  no-fee rules in the existing qualification pipeline still apply.
- Never sends an application, sends outreach, accepts work or performs
  payments. Provider unavailability reports SOURCE_UNAVAILABLE, not a
  fabricated successful search.
- Disposable PostgreSQL CI verifies owner scope, uniqueness, simulated
  provider failure, source outage, prohibited external action and the
  time/environment gate.

## Critical limitations

- **A code path is not a deployed cron worker.** There is NO configured
  recurring Render cron job or actual live production background scheduler
  in this PR. Scheduling needs separately approved staging infrastructure,
  prices, secret handling and monitoring.
- Only safe, approved public-source discovery may be used. External
  source API access and actual first-client quality have NOT been verified
  by fake provider CI.
- This run is daily in one approved local time window. There is no automatic
  retry of a failed or interrupted cycle. The owner must inspect the saved
  FAILED/RUNNING/SKIPPED state first.
- Work & Revenue PR #338 is draft; Operations PR #477 and accounting PR #484
  are also draft, with PR #484 based on #477. These are separate branches
  with an unresolved integration and staging deployment sequence.
- Client contracts, accounting data, live permissions, actual cloud
  authentication, private file storage and restart recovery are not validated
  merely by this scheduler's CI.

## Shortest controlled release sequence

1. Review PR #338's discovery scheduler and PR #477/#484 release order.
2. Obtain explicit owner approval and costs for a separate isolated
   staging database/runner and private storage (if accounting stage included).
3. Run the safe disabled CLI and read-only exact-identity preflight.
4. Apply reviewed staging-only schema revisions after separate approval;
   test a real authenticated owner and scheduled discovery against approved
   live sources using *only public job postings*.
5. Verify saved opportunities, duplicate suppression, accurate source URL,
   country/contractor eligibility, no-fee filtering and one clear owner action.
6. Verify Operations Agent job intake, output review, owner-only file
   download, restart/failure behavior and no external delivery.
7. Only then propose separate production merge/deploy/activation approval.
   Preserve the ability to disable scheduling and accounting processing.

**Single next release gate:** owner-approved, cost-reviewed isolated staging
infrastructure. There is no authorization to create Render services or to
activate production in this commit.


## Missed-run and recovery evidence — November 12, 2026

A read-only `inspect_staging_schedule_health` function checks the last
expected 5 a.m. Central run against the durable owner/day marker on an
explicitly approved staging PostgreSQL database. It distinguishes:
`MISSING_EXPECTED_RUN`, `RECORDED_FOR_OWNER_REVIEW`,
`SOURCE_UNAVAILABLE`, and `NEEDS_OPERATOR_REVIEW`. It defaults to
`BLOCKED` if the staging environment, feature flag, approved owner, or
exact database identity cannot be established.

A saved successful work-preparation record is **not evidence that a
Render scheduler exists, is continuously running, or is ready for real
customer data**. The health response explicitly reports
`deployed_scheduler_verified=false` and
`production_autopilot_enabled=false`. Failed or interrupted runs require
manual owner review; no automatic rerun, submission, payment or contact
occurs. Regression tests use disposable PostgreSQL only.

Before declaring the live autopilot operational, externally verify the
actual job trigger, execution timestamps, source availability, saved
legitimate opportunities, alerting on missed runs and safe shutdown.


## Render cron deployment proposal — November 12, 2026

Added `render.nova-work-autopilot-cron.proposed.yaml`, which is NOT part of
the existing root production `render.yaml` and has not been synchronized
to Render. It specifies a proposed paid `0.5c-512mb` cron service on
the Work & Revenue draft branch, with automatic deployment OFF and the
staging execution flag FALSE. No owner account, provider key, or financial
credentials are committed. It points at the separately proposed isolated
accounting PostgreSQL resource from PR #484; that database is not deployed.

Render cron schedules are evaluated in UTC. The proposed `0 10,11 * * *`
invokes at both possible UTC hours corresponding to 5 a.m. US Central
across daylight saving changes, while the application guard allows the
5 a.m. local execution only. The extra blocked invocation can still add
billable running time; it is not a cost-free scheduler. Render documents
a minimum $1/month per cron service in addition to usage-based charges.
Actual costs and any database/storage costs must be approved before
provisioning.

Four new CI checks validate that this proposal is separate from production,
has no embedded credentials, has all execution/paid flags OFF, and handles
summer/winter UTC-to-Central conversion. A successful cron Blueprint test
does not verify the actual scheduled trigger, provider access, job postings,
or owner review. Real Render resources were not created.

**Verified acceptance run 43237941256: 23 tests passed** against synthetic
providers and disposable PostgreSQL (including cron-proposal checks). The
default-disabled CLI refused to open live connections as expected.

The next work that changes deployment state requires the owner's separate
specific approval: create a dedicated billable isolated database, web
staging and cron service, provision secure private storage, apply reviewed
staging migrations, establish test users and real permission records.
Only then should an actual deployed run and missed-run alarm be accepted.


## Draft PR integration reconciliation (2026-11-12)

Added read-only GitHub Actions `Nova Release Cross-PR Integration Preview`.
It checks PR #477 (durable Operations processing), PR #484 (accounting
integration), then PR #338 (Work & Revenue) in a temporary CI checkout.
Nothing is pushed, merged into GitHub, or deployed to Render.

The first run found one genuine shared dashboard conflict:
`backend/static/nova-work/index.html`. PR #477 + #484 merged without a
textual conflict; PR #338 also inserts the first-client board in the same
area as Operations/Accounting panels.

An intentionally strict CI-only reconciler now preserves all three panels,
the first-client stylesheet and the four feature scripts, without
modifying any draft PR head. It refuses unknown conflicts and checks for
missing/duplicate DOM controls. A separate combined synthetic regression
step exercises work discovery, CSV job processing, accounting HTTP review and
the staging preflight together.

**Verified prior ephemeral CI run 43278967342:** dashboard reconciliation
succeeded, all static UI checks passed, and **31 combined synthetic
functional tests passed**. A later CI revision additionally records explicit
test-success evidence in the downloadable integration report; its separate
verification must complete before release credit is given.

A conflict-free temporary tree is NOT a reviewed integrated release branch.
Human review is required for the shared HTML resolution, dependency/route
ordering, full PostgreSQL/private S3 behavior, authenticated Render staging,
consent controls, missed-run alerting and rollback. Keep all production and
paid-processing flags disabled. Do not merge/deploy automatically.
