# STABILIZATION WEEK - PRIORITY A.3

## Migration Graph Repair Investigation

Date: 2026-05-31
Result: PASS

## 1) Complete Alembic Dependency Graph

Base chain:
- 0001 -> 0002 -> 051233e3a434 -> 2a7c8b9d5f12 -> b9f4c2d1a901

Branches from b9f4c2d1a901:
- b9f4c2d1a901 -> d5c4e8a1c901 -> e2f1b7c4a991 -> c3f7a91d2b44 (head)
- b9f4c2d1a901 -> c7e4f1a2d8b3 (head)

## 2) Required Graph Facts

- Heads:
  - c3f7a91d2b44
  - c7e4f1a2d8b3
- Branch points:
  - b9f4c2d1a901
- Merge revisions:
  - none
- First revision creating health_isf_rides:
  - 051233e3a434 ([backend/migrations/versions/20260517_051233e3a434_health_isf_relational_persistence.py](backend/migrations/versions/20260517_051233e3a434_health_isf_relational_persistence.py))
- Target revision:
  - 2a7c8b9d5f12 ([backend/migrations/versions/20260517_2a7c8b9d5f12_health_isf_realtime_operations.py](backend/migrations/versions/20260517_2a7c8b9d5f12_health_isf_realtime_operations.py#L19))
- Dependency path between first rides-create and 2a7c8b9d5f12:
  - 051233e3a434 -> 2a7c8b9d5f12

## 3) Root Cause (for original failure)

Primary root cause:
- Migration generated against pre-existing DB/runtime-created tables and not fully self-contained for clean DB bootstrap.

Exact issue:
- Revision 2a7c8b9d5f12 alters health_isf_rides directly.
- Its parent 051233e3a434 previously did not explicitly create health_isf_rides from zero (it only altered it conditionally if already present).
- On clean migration runs, this allowed 2a7c8b9d5f12 to execute before health_isf_rides existed.

Classification:
- migration generated against existing DB state: YES
- incorrect down_revision: NO
- missing dependency edge: NO (2a depends on 051 correctly)
- bad branch ordering: NO (graph ordering is valid)
- deleted migration: NO evidence
- merge conflict revision: NO merge revisions present

## 4) Exact Migration Files Involved

Primary graph/bootstrap repair:
- [backend/migrations/versions/20260517_051233e3a434_health_isf_relational_persistence.py](backend/migrations/versions/20260517_051233e3a434_health_isf_relational_persistence.py#L87)
- [backend/migrations/versions/20260517_2a7c8b9d5f12_health_isf_realtime_operations.py](backend/migrations/versions/20260517_2a7c8b9d5f12_health_isf_realtime_operations.py#L20)

Additional migration-only portability fixes required to satisfy clean sqlite upgrade validation:
- [backend/migrations/versions/20260518_e2f1b7c4a991_health_isf_ride_intake_enterprise.py](backend/migrations/versions/20260518_e2f1b7c4a991_health_isf_ride_intake_enterprise.py#L38)
- [backend/migrations/versions/20260529_c3f7a91d2b44_health_isf_ride_vehicle_assignment.py](backend/migrations/versions/20260529_c3f7a91d2b44_health_isf_ride_vehicle_assignment.py#L25)

## 5) Minimal Migration-Only Fix Applied

1. In 051233e3a434, added explicit table bootstrap for missing legacy bases on clean DB:
- health_isf_providers
- health_isf_drivers
- health_isf_rides

2. In e2f1b7c4a991, guarded sqlite-incompatible ALTER COLUMN DROP DEFAULT.

3. In c3f7a91d2b44, switched sqlite FK add/drop to batch mode.

No runtime files changed.
No dispatch/onboarding/scheduling/workflow-runtime code changed.

## 6) Final Validation Evidence

Command (fresh DB):
- DATABASE_URL=sqlite:///./pilot_a3_clean.db
- alembic upgrade heads

Observed result:
- Upgrade progressed through all revisions and completed both heads:
  - c3f7a91d2b44
  - c7e4f1a2d8b3

Current DB revisions after run (alembic current):
- c7e4f1a2d8b3 (head)
- c3f7a91d2b44 (head)

Conclusion:
- Migration graph/bootstrap repaired for clean-database migration validation.
- Final status: PASS.
