# Growth Agent staging: backup restore rehearsal and cutover runbook
Prepared 2026-11-13. **Preparation only — no deployment or restoration performed.**

## Verified starting state
- Candidate PR #507 HEAD `cbc371c0ed03cd42a86e28fd6988351280fc3910` (as checked); exact-head GitHub CI run `43463606721` success (qualification and backend diagnostic) and Casting run `43463606735` success. Candidate SHA changes if further edits are made; re-verify.
- Existing Render service `nova-growth-validation-490`, ID `srv-dbqv8ip5efls73dtpmo0`, auto-deploy disabled, old branch `review/growth-agent-staging-corrections-20261112`, old pin `1395f7e47f0f2e4a94473621374f9219e180ac6b`. Existing startup **still** runs tests against persistent staging Postgres. Do not click Deploy Latest.
- Dedicated staging DB ID `dpg-dbqv7mmtlv9c73d7tnb0-a`, expected database `nova_ga_490_dispos`. Remote read-only query tool is blocked by the database's empty external IP allowlist. **Do not widen IP allowlist, paste credentials into chat, or treat the failed tool query as a database outage.**
- Owner previously downloaded backup export 2026-11-13 03:55 UTC; archive readability checked (159,692 bytes). Full PostgreSQL restore **not verified**.

## Restore rehearsal: required operator steps (no existing staging data touched)
1. On a trusted machine with the backup, record archive name, size, checksum (e.g. PowerShell `Get-FileHash -Algorithm SHA256 <archive-file>`) and backup timestamp. Store checksum/evidence privately; do not commit archive or secrets.
2. Inspect archive with `tar -tf <archive-file>`. Identify whether it is a PostgreSQL custom-format dump, tar dump, or directory-format dump compressed as tar.gz. **Inspect files inside first; do not assume `pg_restore` can restore an outer .tar.gz directly.**
3. Use an **already available truly disposable** PostgreSQL target with separate credentials; only create a new Render database if owner explicitly approves any price impact. Target must not be `nova_ga_490_dispos` and never a production DB. Verify `SELECT current_database();` before restoring.
4. Restore with the command appropriate to archive format, e.g. `pg_restore --no-owner --no-acl --exit-on-error --dbname=<DISPOSABLE_RESTORE_DB_URL> <valid-pg-dump-path>`, or `pg_restore --format=directory ... <extracted-directory>` for a directory archive. Use OS secrets/environment, not an inline password in visible commands/logs. Do not use `--clean` / `--create` against staging or production.
5. Verify restoration **on disposable target only**: `SELECT version_num FROM alembic_version;`, count `nova_ga_*` tables, selected schema definitions/indices, and non-sensitive row counts by table. Compare to backup manifest/source inventory where available. Check application-level read-only retrieval on isolated restored DB with mock integrations and network transports off.
6. Save verification evidence (archive checksum, dump format, restore exit code, schema revision, counts, isolated target identity, date). Destroy/disconnect disposable target in accordance with owner-approved cost and retention policy. Never publish customer records or passwords.
7. If full restore cannot be proven, mark **NO-GO** for deployment; keep existing service and database unchanged.

## Candidate Render config (manual, coordinated, owner-approved change only)
First merge/rebase reviewed PR #507 into a chosen staging-only branch without touching main/production, run exact-head CI, and record the **final** candidate SHA. That final SHA (not necessarily the initial `cbc371...`) is the only one eligible for approval.

Proposed new Render build command:
```sh
test "$RENDER_GIT_COMMIT" = "<FINAL_APPROVED_CANDIDATE_SHA>" && pip install -r backend/requirements.txt
```
Proposed new Render start command:
```sh
cd backend && python scripts/verify_growth_staging_start.py
```
Proposed environment key (value is an approved 40-character hex SHA, not a secret):
```text
NOVA_GA_APPROVED_STAGING_SHA=<FINAL_APPROVED_CANDIDATE_SHA>
```
Source branch: the reconciled staging-only branch pinned to this final SHA, **auto-deploy OFF**. Existing DB secrets, database binding, URLs, and provider disable flags must be preserved. The script refuses mismatch/unsafe settings and checks the expected database revision read-only; **no migration or pytest at startup**.

Make coordinated source-branch/build/start/environment updates only after owner explicitly approves the exact final SHA and rollback. The connected Render interface does not expose an atomic change of branch, build and start, so do not try to achieve the release with `trigger_deploy` or partial env-variable edits.

## Staging rollback criteria
If authorization preflight fails, health checks fail, new Workspace fails in authenticated browser, or any mock-only invariant changes: stop deployment/traffic, preserve incident logs and existing database, revert **application branch/config** to the known-good pin `1395f7e47f0f2e4a94473621374f9219e180ac6b` only if schema compatibility is independently verified. Do not downgrade the persistent staging database or run destructive schema tests. Retain backup until a clean review.

## Acceptance after approved staging deployment
Run synthetic chat -> CRM contact -> appointment -> workflow preview -> owner Approve (record only), Reject, Hold -> audit retrieval after restart -> mock worker due-time/consent; desktop/mobile sign-out/tenant-switch/duplicate; confirm **zero real sends, charges, or production changes**. Production website activation requires a completely separate owner approval.

**NO-GO today:** restore rehearsal not proven, no coordinated Render configuration authorization, no deployed authenticated browser acceptance.
