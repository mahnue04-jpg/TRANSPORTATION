# Growth-only shared backend: controlled release gate (2026-11-23)

**Decision: NO-GO for production.** This document is an integration review artifact, not authorization to merge, deploy, run migrations, read customer KV data, or send customer messages.

## Verified baseline
- Render service: `amicor health isf` (`srv-d8of2kmrnols73d06h50`) tracks `main` with auto-deploy enabled.
- Latest Render live deploy on inspection: `f0ec2d767e207f99816756f9e1119979eec29f4d`; GitHub main at PR creation: `61f6444d725d6c96fd10d046ad5f360536ad06ef`.
- Main is 14 commits ahead of deployed SHA; GitHub comparison shows 46 changed paths, all under `website/` or `.github/workflows/amicor-website-lead-regression.yml`. Exact backend `app/main.py`, `migrations/env.py`, and `requirements.txt` blob SHAs match between deployed SHA and `main`.
- PR #586 changes 71 files, 62 additive lines in `backend/app/main.py`, 15 additive lines in shared Workspace index, no Studio or Operations file modifications. Its GitHub Actions matrix completed 12/12 jobs successfully (Growth, disposable Postgres, workspace UI, Casting, Work & Revenue, backend diagnostics, site CI).

## Pre-release blockers
1. **Production Growth schema:** `20261112_nova_growth_agent` explicitly returns without creating tables when environment is production. A normal Alembic upgrade can therefore *stamp* the revision while skipping Growth DDL. This is NOT safe for enabling real Growth conversations; design a separately owner-reviewed migration with real DDL, schema version verification, backup, restore, and rollback on a disposable copy first.
2. **Ingestion must remain isolated:** The actual site handler saves `lead:${receivedAt}:${uuid}` keys in `AMICOR_LEADS`; the Growth reader handles the `lead:` namespace and projects consent. Test that exact record format with synthetic values. Do not connect production Cloudflare credentials until separate approval.
3. **Cross-product release safety:** `main` is Render auto-deployed. No merges or release toggles until a controlled deploy method, working rollback target, outage monitoring, and explicit owner go/no-go are confirmed. Production website files differ from the deployed Render commit but the backend file hashes above are identical; evaluate the automatic Render redeploy nonetheless.
4. **Privacy/security:** Verify organization binding, owner authentication, audit trail, consent evidence, retention, no customer data in logs, and unapproved outbound channels remain disabled.
5. **Operational acceptance:** On isolated private staging, test website `202` save -> owner inbox -> consented approval -> same conversation on retry; deny signed-out/nonowners; fail closed on missing consent, bad source, and cross-tenant reads; verify other products routes still function.

## Explicit rollback design (not executed)
- Before any release, record production commit/backup identifiers and check a restore of **disposable** database data.
- On a failed deployment, turn Growth master and customer-handoff flags OFF; roll Render back to the last verified backend SHA using an approved release procedure. Do not automatically downgrade or drop Growth tables.
- Keep public site's free inquiry form available independently of Growth readiness; never claim automatic CRM delivery until independently accepted.

## Review-only signoff
- [x] Confirm backend target branch and deployed SHA
- [x] Review GitHub diff scope (no Studio/Operations files changed)
- [x] Execute GitHub Actions regression jobs (12/12 green)
- [x] Verify backend code from deployed SHA and current main matches in key files
- [ ] Approve safe production migration path (current revision is stamp-only under production flags)
- [ ] Complete private restored-DB rehearsal and rollback verification
- [ ] Complete isolated synthetic end-to-end test against actual website key shape
- [ ] Verify customer source, consent, owner access, privacy/retention and monitoring
- [ ] Obtain explicit owner authorization for production deploy and live source connection
