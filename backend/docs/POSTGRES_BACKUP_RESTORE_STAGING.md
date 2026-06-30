# PostgreSQL Backup & Restore — Staging Verification

Verify backup and restore on **staging** before production go-live.  
Replace placeholders with your actual staging database name and host.

## Prerequisites

- PostgreSQL 14+ staging instance
- `pg_dump` / `psql` / `pg_restore` client tools installed
- Network access from operator workstation or CI runner to staging DB

## 1. Create a logical backup

```bash
# Full custom-format backup (recommended)
pg_dump "$DATABASE_URL" \
  --format=custom \
  --no-owner \
  --file="amicor_staging_$(date -u +%Y%m%dT%H%M%SZ).dump"

# Verify backup file is non-empty
ls -lh amicor_staging_*.dump
```

## 2. Record baseline counts (before restore test)

```sql
SELECT 'health_isf_rides' AS table_name, COUNT(*) FROM health_isf_rides
UNION ALL SELECT 'health_isf_trips', COUNT(*) FROM health_isf_trips
UNION ALL SELECT 'health_isf_payouts', COUNT(*) FROM health_isf_payouts
UNION ALL SELECT 'health_isf_dispatch_logs', COUNT(*) FROM health_isf_dispatch_logs;
```

Save the output with the backup filename.

## 3. Restore to an isolated test database

```bash
# Create empty restore target (on same or separate staging cluster)
createdb amicor_restore_test

# Restore — does not overwrite production when target is separate
pg_restore \
  --dbname=postgresql://USER:PASS@HOST:5432/amicor_restore_test \
  --no-owner \
  --clean \
  --if-exists \
  amicor_staging_YYYYMMDDTHHMMSSZ.dump
```

## 4. Validate restore integrity

```sql
\c amicor_restore_test

-- Row counts should match baseline from step 2
SELECT 'health_isf_rides' AS table_name, COUNT(*) FROM health_isf_rides;

-- Spot-check a completed ride has trip + payout linkage
SELECT r.id, r.status, t.id AS trip_id, p.id AS payout_id
FROM health_isf_rides r
LEFT JOIN health_isf_trips t ON t.ride_id = r.id
LEFT JOIN health_isf_payouts p ON p.trip_id = t.id
WHERE r.status = 'completed'
LIMIT 5;
```

## 5. Application smoke on restore target (optional)

Point a **disposable** app instance at `amicor_restore_test`:

```powershell
$env:DATABASE_URL = "postgresql://USER:PASS@HOST:5432/amicor_restore_test"
cd backend
$env:PYTHONPATH = "."
python -m uvicorn app.main:app --port 8020
```

- [ ] `GET /api/health/readiness` → database connected
- [ ] `GET /api/health-isf/dashboard` (authenticated) returns metrics
- [ ] Dispatcher can list rides

## 6. Document results

Record in your change ticket:

| Field | Value |
|-------|-------|
| Backup file | `amicor_staging_*.dump` |
| Backup size | |
| Restore target | `amicor_restore_test` |
| Row count match | Yes / No |
| App smoke on restore | Pass / Fail |
| Verified by | |
| Date (UTC) | |

## 7. Cleanup

```bash
dropdb amicor_restore_test
```

## Managed provider notes

- **Render PostgreSQL:** use dashboard backup snapshots + download for off-site copy
- **Azure Database for PostgreSQL:** configure geo-redundant backup retention; test point-in-time restore to a new server

## Recovery time objective (guidance)

| Tier | Target |
|------|--------|
| Staging drill | Complete restore + smoke within 60 minutes |
| Production | Define RTO/RPO with ops team before go-live |

This document satisfies the staging backup/recovery verification step in the production certification audit.
