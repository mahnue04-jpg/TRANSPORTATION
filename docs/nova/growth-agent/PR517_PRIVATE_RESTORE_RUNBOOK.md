# Growth Agent PR #517 — private staging recovery execution gate

**Status: NOT EXECUTED.** Draft operational procedure, November 14, 2026.
This is not deployment authorization and does not prove a backup exists.

## Verified identity and access constraints
- Render workspace: Saye's workspace (`tea-d8oe81b7uimc739gujp0`).
- Staging web service: `nova-growth-validation-490` (`srv-dbqv8ip5efls73dtpmo0`), auto-deploy **off**.
- Dedicated staging PostgreSQL instance: `nova-ga-490-dispos` (`dpg-dbqv7mmtlv9c73d7tnb0-a`), database `nova_ga_490_dispos`; **do not connect to the production `amicor` DB**.
- Render metadata reports the database available. The hosted Render connector cannot establish a SQL session because **external IP allowlist is empty**. Do not relax the allowlist to make this check pass.
- Connected Render tools currently have metadata and read-only SQL but **no backup/export/restore action**. Existing database backup availability and restorable state are **not verified**.
- GitHub CI verifies a **different synthetic** pg_dump → pg_restore fixture on disposable databases; this is NOT evidence of a real staging backup.

## Preconditions (hard stop unless all satisfied)
1. Explicit owner authorization to export the identified staging data through a private internal Render connection and to restore it **only into a separately approved isolated disposable destination**. If provisioning incurs costs, stop and obtain a separate price approval.
2. Approved private execution identity with access confined to the specific staging database, not production. Never add `0.0.0.0/0` to a database allowlist or put credentials in GitHub, logs, tickets, or chat.
3. Confirm the destination is disposable and **not** production, current staging, Creative Studio, or any shared database. Record destination identity before any restore.
4. Storage location is access-controlled, encrypted, not served as a public artifact, with explicit retention and deletion policy. No raw records or credentials in the final verification report.
5. Disable any optional Growth Agent worker and retention schedule on the disposable restore environment; ensure no real outbound provider calls.

## Private execution procedure (only after approval)

Use a controlled internal session with approved tools and no public network exposure. The operator must supply the internal connection URLs through a private secret manager (not shell history or PR text). Commands below are templates; they must NOT be run with production or current staging as the restore target.

```sh
# In an approved internal execution environment only.
# SOURCE_URL: dedicated Growth staging database, READ access sufficient for pg_dump.
# RESTORE_URL: separate, EMPTY, approved disposable database.
# Both supplied securely; never echo or commit them.
umask 077
backup_dir="$(mktemp -d)"
trap 'rm -rf "$backup_dir"' EXIT
pg_dump --format=custom --no-owner --no-acl --file="$backup_dir/growth-staging.dump" "$SOURCE_URL"
test -s "$backup_dir/growth-staging.dump"
pg_restore --list "$backup_dir/growth-staging.dump" > "$backup_dir/archive-manifest.txt"
test -s "$backup_dir/archive-manifest.txt"
# STOP and confirm RESTORE_URL identity + emptiness once again.
pg_restore --exit-on-error --no-owner --no-acl --dbname="$RESTORE_URL" "$backup_dir/growth-staging.dump"
```

**The example deletes the temporary dump on process exit**; production-quality evidence preservation requires an approved encrypted backup destination and retention schedule. A successful restore should be followed by *read-only* comparisons of schema revisions, non-sensitive table counts, and a synthetic owner-scoped application smoke check on the isolated clone. Avoid posting row values. Do not run schema migrations or sample seeding on the source.

## Acceptance evidence (record without secrets or customer data)
- Source service/DB identifiers, source backup timestamp, tool versions, encrypted archive location/retention owner.
- Confirmation that the dump had no errors, manifest was readable, restore finished with no errors.
- Destination ID and evidence it was a separate disposable database.
- Schema revision comparison and per-table counts/digests for permitted data, redacted and access-controlled.
- Recovery test operator/approver and rollback procedures.
- No source modifications, no outbound deliveries, no paid activation, no production/Creative Studio touches.

## Go/no-go
**NO-GO until the above real-source restore succeeds and the exact startup candidate passes application acceptance on the isolated restored destination.** PR #517 remains draft/unmerged. The existing staging service stays pinned to the prior commit; its restart, settings change, and deployment all require a separate explicit staging-only owner approval.
