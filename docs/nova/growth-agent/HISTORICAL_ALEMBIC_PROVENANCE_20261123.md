# Provenance of production Alembic V3 revision — 2026-11-23

**Finding: historical revision ID verified in GitHub; production rollout remains blocked.**

Production's read-only `alembic_version` is `20260918_nova_v3_live_infrastructure`. The current `main` revision ID is `20260918_nova_v3_live_infra`.

The historical branch `feature/nova-v3-canonical-integration` contains `backend/migrations/versions/20260918_nova_v3_live_infrastructure.py` with:
- `revision = "20260918_nova_v3_live_infrastructure"`
- `down_revision = "20260918_nova_work_revenue_v2_owner_scheduler"`
- Blob SHA `54bc88b4dcbd2b08b5290da766c4d6c3fd7d994d`.

The current `main` file at the same path has:
- `revision = "20260918_nova_v3_live_infra"`
- `down_revision = "20260918_work_rev_owner_sched"`
- Blob SHA `5adc66cd7fa2a95b14595bc03b48a1358f8df822`.

Line-by-line inspection found **exactly four differences across 365 lines** (two docstring revision references and two assigned Alembic identifiers). All executable upgrade/downgrade logic appears text-identical. This is a **provenance mapping**, not permission to `alembic stamp` or evidence of production schema completeness.

The historical parent file `20260918_nova_work_revenue_v2_owner_scheduler.py` exists on that historical branch and declares parent `20260918_nova_work_revenue_v2_hardening`.

## Required before reconciliation

1. Audit the entire original-to-current revision chain (including the historical parent aliases), not just this V3 node. Resolve any missing or renamed parent and test a one-off version normalization on an **isolated restored copy**, not production.
2. Verify the restored copy has the expected V3 tables, indexes, unique constraints, and data preservation.
3. Check the 21 Growth tables and five missing worker columns, missing campaign review table, and any other non-Growth migrations independently.
4. Validate backup/restore, error handling, owner-only inquiry handoff, and rollback.
5. Obtain a separate production go/no-go and schedule coordinated deployment. No PR merge or live KV access until then.

## Release decision

**NO-GO.** Historical identity established; schema/migration-history reconciliation not completed. No live migrations or data access authorized by this document.
