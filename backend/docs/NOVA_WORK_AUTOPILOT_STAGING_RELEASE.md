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
