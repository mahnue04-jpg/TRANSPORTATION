# AMICOR Growth: additive production worker-schema patch

**Review-only artifact. Do not execute against the live database under PR #586.**
The production DB was inspected using read-only metadata, and five columns on `public.nova_ga_delivery_attempts` are missing. The Growth runtime must remain disabled until the migration graph and schema drift are fully reconciled.

## Required preconditions for a separate approval

1. Take and independently verify a point-in-time recoverable backup of the production `amicor` database. Restore it to an isolated copy and prove row totals/constraints before and after the exercise without exporting customer data.
2. Inventory the **entire** Alembic graph from production's `20260918_nova_v3_live_infrastructure` to the target version and validate every intermediate schema effect. The 21 existing `nova_ga_%` tables are not proof that the revision pointer is correct. **Do not stamp or upgrade production Alembic blindly.**
3. Confirm exclusive release coordination, expected production database identity, connection role, lock/statement timeout, change window, approved rollback path, and that Growth live flags remain OFF.
4. Rehearse the *exact* patch on a restored copy, verify existing rows, and run cross-product regression checks. Only then may the owner approve the production SQL.

## Proposed transaction (illustrative; not an authorized production run)

```sql
BEGIN;
SET LOCAL lock_timeout = '3s';
SET LOCAL statement_timeout = '30s';

DO $growth_precheck$
BEGIN
  IF current_database() <> 'amicor' THEN
    RAISE EXCEPTION 'Unexpected target database';
  END IF;
  IF to_regclass('public.nova_ga_delivery_attempts') IS NULL THEN
    RAISE EXCEPTION 'Growth delivery attempts table missing';
  END IF;
END;
$growth_precheck$;

ALTER TABLE public.nova_ga_delivery_attempts
  ADD COLUMN IF NOT EXISTS max_attempts integer NOT NULL DEFAULT 5,
  ADD COLUMN IF NOT EXISTS claimed_by varchar(80),
  ADD COLUMN IF NOT EXISTS claimed_at timestamp without time zone,
  ADD COLUMN IF NOT EXISTS lease_expires_at timestamp without time zone,
  ADD COLUMN IF NOT EXISTS available_at timestamp without time zone;

DO $growth_verify$
DECLARE
  mismatches integer;
BEGIN
  SELECT count(*) INTO mismatches
  FROM (VALUES
    ('max_attempts','integer','NO'),
    ('claimed_by','character varying','YES'),
    ('claimed_at','timestamp without time zone','YES'),
    ('lease_expires_at','timestamp without time zone','YES'),
    ('available_at','timestamp without time zone','YES')
  ) AS expected(column_name,data_type,is_nullable)
  LEFT JOIN information_schema.columns c
    ON c.table_schema = 'public'
   AND c.table_name = 'nova_ga_delivery_attempts'
   AND c.column_name = expected.column_name
  WHERE c.column_name IS NULL
     OR c.data_type <> expected.data_type
     OR c.is_nullable <> expected.is_nullable;
  IF mismatches <> 0 THEN
    RAISE EXCEPTION 'Unexpected Growth worker column schema';
  END IF;
END;
$growth_verify$;
-- An explicit review of existing rows and constraints, in the same transaction,
-- must precede COMMIT in the approved release runbook.
ROLLBACK; -- REVIEW DEFAULT: leaves DB unchanged.
```

**Important:** This patch is not a complete Growth production release. The missing `nova_ga_campaign_asset_reviews` table, migration version reconciliation, customer inquiry authorization, and staged rollout still require independent acceptance. Do not remove the default `ROLLBACK` as an informal shortcut. The final approved runbook must be separately generated and reviewed, with the approved commit/backup IDs and a signed go/no-go decision. No existing tables should be dropped as part of a rollback.
