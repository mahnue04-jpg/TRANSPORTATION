# Growth production schema reconciliation — review-only plan

Status: **NO-GO for production DDL / deployment**. This is a concrete, additive repair plan for owner review, not a migration runner. Do not execute against AMICOR production until backed-up restore rehearsal and separately approved change window.

## Evidence (read-only Render inspection, 2026-11-23)

- Production Postgres service: `amicor-prod`, database `amicor`.
- 21 `nova_ga_%` tables exist, but `alembic_version` reports `20260918_nova_v3_live_infrastructure`.
- `nova_ga_delivery_attempts` is missing: `max_attempts`, `claimed_by`, `claimed_at`, `lease_expires_at`, `available_at`.
- `nova_ga_conversations.is_synthetic_demo` exists.
- `nova_ga_retention_schedule_runs` exists.
- `nova_ga_campaign_asset_reviews` is absent.
- The current Growth revisions block production-mode migration attempts. **Do not run `alembic upgrade heads` or `alembic stamp` on production.** Production's old Alembic pointer is not evidence that every intervening non-Growth schema migration has been completed.

## Approved architecture to develop and rehearse

1. Build a disposable PostgreSQL restore/copy, verify backup integrity and inspect full table/column/index/constraint signatures **without customer row output**.
2. Apply the *minimal missing Growth DDL* as one reviewed transaction with an explicit target database guard, advisory lock, and `lock_timeout`/`statement_timeout`. Do not touch Studio, Delivery, Work & Revenue, Health ISF, or other tables.
3. For `nova_ga_delivery_attempts` add:
   - `max_attempts INTEGER NOT NULL DEFAULT 5`
   - `claimed_by VARCHAR(80)`
   - `claimed_at TIMESTAMP WITHOUT TIME ZONE`
   - `lease_expires_at TIMESTAMP WITHOUT TIME ZONE`
   - `available_at TIMESTAMP WITHOUT TIME ZONE`
   Verify types and nullable/default behavior, not just column names; ensure existing rows retain values.
4. If campaign review functionality is in final scope, create **only** `nova_ga_campaign_asset_reviews` per `20261118_nova_ga_campaign_review.py` with full unique constraint and owner index. Avoid activating campaign review until asset permissions are separately accepted.
5. Inspect every intervening Alembic revision from production's recorded head to current `main`. Do not move the version pointer until a full schema inventory proves each revision's effects were applied or were intentionally skipped; use a reviewed, transactional revision-reconciliation procedure. Never assume 21 tables implies Alembic history is correct.
6. Validate existing Growth rows/keys, idempotent inquiry handoff, owner auth, consent, and a rollback on a **disposable restored copy**. For rollback, disable Growth flags first and revert app commit; avoid dropping tables or customer data.
7. Ensure Render production auto-deploy on `main` is intentionally controlled for release, with explicit approval and monitoring. Do not merge #586 during a schema mismatch.

## Stop conditions

- No known-good database restore or no point-in-time recovery evidence.
- A missing, changed or unexpected non-Growth table, nonconforming schema column, index, or constraint.
- Unsupported Alembic revision graph, multiple heads, a partly stamped revision, or missing historical migration source.
- Any real Cloudflare KV connection, live outbound message provider, or payment flag unexpectedly enabled.
- Cross-product regressions or readiness checks failing.

## Acceptance evidence required

- [ ] Restored-copy identity, backup timestamp, recovery proof.
- [ ] Before/after Growth schema comparison with expected columns, types, constraints, indexes.
- [ ] Alembic migration graph reconciliation reviewed separately.
- [ ] Synthetic `lead:<ISO datetime>:<uuid>` -> owner-only inquiry list -> consent check -> handoff/retry.
- [ ] No release regression in Studio/Casting, Operations, Work & Revenue and website inquiries.
- [ ] Safe rollback rehearsed and emergency Growth disable documented.
- [ ] Final owner production release authorization.

Current draft PR #586: automated tests passed at head `16999fdf86591d4d77dd35afbe7858c5cd715009`. A documentation update requires fresh CI reporting where applicable.
