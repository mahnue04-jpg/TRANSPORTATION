# Nova Creative Studio staging cutover runbook (PR #482)

**Scope:** Staging only. No production switch, paid-provider activation, or customer contract acceptance is authorized by this runbook.

## Confirmed inventory (2026-11-10)

- Render Studio validation service: `nova-studio-validation-350` (`srv-db9da4ijnfac73bs0isg`), deployed from `feature/studio-landscape-film-assembly-20261110`; Docker service with persistent `/data` disk; automatic deployment disabled.
- Neon project: `amicor-nova-creative-pr454-staging` (`shy-poetry-63686456`), PostgreSQL 17.
- Neon `staging` branch: `br-plain-sea-bb75boy7`.
- Neon `studio-validation-pr478-20261110` branch: `br-mute-haze-bbxomd0l`, created **from parent data**. Its `creative_staging` database is NOT automatically a fresh empty transfer target. Verify counts, not just the presence of the branch.
- PR #482 SHA `1b891ab8954ae9b02870a7fd6fd9797db89513a5`: SQLite-to-PostgreSQL transfer and backend diagnostic workflows passed.
- **No staging transfer or production change has been performed.**

## Latest confirmed staging source and read-only preflight (2026-11-10)

- Live GET `/api/health/detail` reports `db.backend=sqlite`, `db.ok=true`, and `db.db_path=/data/chat.db`. Its startup environment validator reports no missing required settings.
- The separate legacy `app.core.runtime_config` validator requires `DATABASE_URL` and logged critical warnings despite the healthy active SQLite service. **Do not switch database endpoints just to quiet that warning.**
- Render service `nova-studio-validation-350` reports a 10 GB mounted `/data` disk. Its currently live deployed commit is `ba7c5482a945255c46cb5195433a4d9047a46af0`, not this PR branch.
- A standalone inventory/backup utility is provided at `backend/scripts/studio_staging_backup_preflight.py`. It runs in a trusted shell with access to the actual mounted disk; the Render management connector does not grant shell or file access.

### Operator procedure from authorized staging shell

Review and run against the actual staging service, **not** a disposable CI checkout or a production instance:

```sh
APP_ENV=staging python backend/scripts/studio_staging_backup_preflight.py \
  --source /data/chat.db
```

The default mode is read-only, returns Studio/account table counts, active job count, and counts of local-present, local-missing, empty, and remote asset references. It does **not** print owner IDs, account content, file paths, or credentials.

After confirming `active_jobs=0`, selecting an owner-only private backup directory outside public/static content, and obtaining approval for the staging backup:

```sh
APP_ENV=staging python backend/scripts/studio_staging_backup_preflight.py \
  --source /data/chat.db \
  --backup-directory /data/private-studio-backups \
  --backup
```

This creates an integrity-checked SQLite snapshot with owner-only file permissions and reports its SHA-256 and byte size; it does **not** export or preserve media bytes. Check free disk headroom before backup (the utility fails closed if space is insufficient). Once the backup is exported to secure off-disk storage, compare its SHA-256 and byte count against the original report and independently test an isolated restore. An on-disk backup on the same Render disk is **not sufficient disaster recovery**: separately copy the verified database snapshot and private media to authorized external storage, confirm byte/hash integrity and test restoration in isolation. A restart or disk loss must not destroy the only backup. Never log or upload personal customer records to CI.

Do not confuse database asset references with physically retrievable MP4 files. For remote references, confirm authorized access to the bucket and persisted bytes in a separate owner-scoped procedure. For local file references, enumerate and copy the real referenced bytes through a trusted service shell; the inventory output intentionally contains counts only. Keep provider billing off.

## Access and change gate

1. Identify the existing SQLite database file on the actual Render staging `/data` disk using an authenticated administration channel. The Render management connector can inspect service metadata, but does **not** provide disk-level file access. Do not infer the file path.
2. Confirm staging maintenance window, current signed-in owner, and that all render jobs are inactive. Keep all paid provider switches disabled.
3. Obtain explicit approval for a staging transfer and preserve a recovery path to the exact source revision. Avoid accidentally deploying the different PR branch just to gain migration access.
4. Choose an **isolated destination** with an application-prepared schema. Do not reuse an inherited Neon branch or any database with existing rows. Never use the Render production database.
5. Use a secure interactive environment to supply connection credentials. Never commit them, paste them into a PR comment, or print them in CI.

## Back up first

- Preserve an independent, private copy of SQLite source and any associated write-ahead log, or obtain a consistent SQLite backup while preventing concurrent writers. The transfer utility makes its own integrity-checked backup during `--apply`; retain a separately verified recovery copy before any service switch.
- Inventory protected media files and storage references separately; the PostgreSQL transfer copies **database references**, not video bytes.
- Confirm private backup permissions, disk capacity, SQLite `PRAGMA integrity_check`, source table row counts, and a restore procedure. Do not delete or overwrite the source.
- Document backup retention and access without storing private locations, tokens, or account details in public logs.

## Transfer acceptance

1. Prepare the reviewed target schema from the exact application revision intended to run after cutover.
2. Verify every selected destination table is empty. The transfer includes `platform_users` and all `nova_creative_*` tables; excludes refresh-token tables and non-Studio modules.
3. Set `APP_ENV=staging` and supply the direct encrypted Neon URL only through `NOVA_STAGING_TARGET_DATABASE_URL` in the secure execution environment. The target hostname and database must match separate reviewed values. Pooled URLs are rejected.
4. Dry-run (prints only table counts):
   ```sh
   python backend/scripts/migrate_studio_staging.py \
     --source /ACTUAL/STAGING/PATH/studio.sqlite \
     --expected-target-host ACTUAL-DIRECT-HOST.neon.tech \
     --expected-target-database ACTUAL_EMPTY_DATABASE
   ```
5. Compare source/target schema, primary keys, table counts, owner associations, and job states. Verify there are no blocking migrations or unexpected nonempty target tables.
6. Apply only after explicit staging authorization:
   ```sh
   python backend/scripts/migrate_studio_staging.py \
     --source /ACTUAL/STAGING/PATH/studio.sqlite \
     --expected-target-host ACTUAL-DIRECT-HOST.neon.tech \
     --expected-target-database ACTUAL_EMPTY_DATABASE \
     --backup-directory /PRIVATE/STAGING/BACKUPS \
     --apply
   ```
7. Require `verified: true`, equal per-table row counts and matching transfer checksums. Verify database-generated identifiers/sequences (if present) are safe for **subsequent** inserts before opening the service for writes.
8. If any step fails, leave the running service on its unchanged source, retain backups, and investigate. Do not switch application database settings.

## Protected storage and sign-in validation

- Confirm private storage credentials, tenant/owner isolation and persisted original video objects independently. SQL asset records are **not** proof that MP4 bytes exist.
- Only after successful transfer, bind the staging application to the reviewed pooled DB endpoint plus private storage configuration. Review the exact deployed commit and deploy intentionally; automatic deployment is off for the validation service.
- Sign in as an existing test owner (refresh tokens are intentionally excluded, so a new sign-in is expected). Confirm old project and imported asset metadata are present.
- Verify **Play saved five-second shot** and **Download** with authenticated access to a real MP4, including playable audio/video and correct MIME/status.
- Confirm another owner cannot retrieve the first owner's files, and signed-out requests are rejected.
- Create a new disposable project and a new saved asset to confirm that inserts still work after migrating pre-existing identifiers. Exercise replay/restart recovery and duplicate-job protection as applicable.
- Keep paid providers disabled; confirm no unwanted provider billing or generation is triggered.

## Rollback / stop conditions

Stop on backup integrity failure, missing SQLite/media files, nonempty or inconsistent target, active render jobs, transfer error, authentication errors, unplayable media, cross-owner access, or paid-provider activation.

If a staging switch fails, restore the prior service settings and reviewed application revision, preserve both data copies, and validate owner sign-in and playback on the original source. Do not run a reverse migration without a separate tested plan.

## Evidence required before broader rollout

Record only non-sensitive: staging revision and deploy ID, source/target table counts, backup integrity outcome, transfer report, signed-in Play/Download and owner-isolation test results, media persistence confirmation, and rollback drill outcome. Production release remains a **separate owner approval**.
