# STABILIZATION WEEK - PRIORITY A.2 Pilot Readiness Report

Date: 2026-05-31
Scope: Clean-environment pilot readiness validation
Verdict: **FAIL**

## Execution Summary

1. Created brand-new empty database file: `backend/pilot_a2_clean.db`.
2. Attempted migrations from zero:
   - `alembic upgrade head` failed because repository has multiple heads.
   - `alembic upgrade heads` then failed during migration execution.
3. Validation halted at migration stage because step 2 is a hard prerequisite for the rest of clean-environment pilot validation.

## Blocking Issue (Exact)

- Blocking issue: Fresh-database migration chain is not self-sufficient from zero and fails before reaching heads.
- Error: `sqlite3.OperationalError: no such table: health_isf_rides`
- Failing SQL: `ALTER TABLE health_isf_rides ADD COLUMN version INTEGER DEFAULT '0' NOT NULL`

### Location

- File: `backend/migrations/versions/20260517_2a7c8b9d5f12_health_isf_realtime_operations.py`
- Function: `upgrade()`
- Failing operation: `op.add_column("health_isf_rides", ...)`
- Route: `N/A` (migration-time failure, before API runtime)

### Dependency Gap Location

- File: `backend/migrations/versions/20260517_051233e3a434_health_isf_relational_persistence.py`
- Function: `upgrade()`
- Observation: this migration conditionally alters `health_isf_rides` only if it already exists, and does not create `health_isf_rides` from zero.

## Reproduction Steps

1. Open terminal in `backend/`.
2. Set clean DB URL:
   - PowerShell: `$env:DATABASE_URL = "sqlite:///./pilot_a2_clean.db"`
3. Ensure DB file is absent:
   - `Remove-Item .\pilot_a2_clean.db -Force` (if present)
4. Run migration chain:
   - `python -m alembic upgrade heads`
5. Observe failure at revision `2a7c8b9d5f12` with missing `health_isf_rides`.

## Evidence Export

### Migration Evidence

- New DB target: `backend/pilot_a2_clean.db`
- Migration heads detected:
  - `c7e4f1a2d8b3`
  - `c3f7a91d2b44`
- Failure revision: `2a7c8b9d5f12`

### Required Pilot Evidence (Unavailable Due Blocker)

Because migration-from-zero failed, the following pilot-runtime evidence could not be produced under the required clean-environment constraints:

- created entity IDs: N/A
- workflow IDs: N/A
- audit counts: N/A
- operational event counts: N/A
- distributed sync sequence numbers: N/A

## Readiness Decision

**FAIL** — Current system is not pilot-ready for clean-environment deployment because step 2 (apply all migrations from zero) fails deterministically before runtime validation can begin.
