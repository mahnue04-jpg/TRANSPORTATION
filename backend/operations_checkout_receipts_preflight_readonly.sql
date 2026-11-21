-- AMICOR Nova Operations $49 Starter: READ-ONLY staging preflight.
-- Review only; no database access, migration, role rotation or deployment is
-- performed by storing this file in GitHub. Execute only through an authorized
-- private Render-region connection. Do not paste passwords, URLs or outputs
-- containing secrets into tickets or chats.
--
-- This script intentionally uses SELECT against PostgreSQL catalogs only.
-- Expected target: nova_operations_staging_db_541 (staging only).
-- HALT if current_database() differs; do not execute DDL in this script.
-- BACKUP: Nov 20 export is listed in Render, restore NOT tested.
-- No live Stripe keys, production app, external allowlist changes or customer data.

-- 1. Connection identity and safety. Does not print connection URL or password.
SELECT current_database() AS connected_database,
       current_user AS connected_role,
       inet_server_port() AS server_port,
       pg_is_in_recovery() AS is_replica,
       (current_database() = 'nova_operations_staging_db_541') AS expected_staging_database;

-- 2. Existing receipt namespace and tables (absence is expected pre-migration).
SELECT n.nspname AS schema_name,
       c.relname AS object_name,
       c.relkind AS object_kind
FROM pg_catalog.pg_namespace AS n
LEFT JOIN pg_catalog.pg_class AS c
  ON c.relnamespace = n.oid
 AND c.relname IN ('starter_test_orders', 'starter_test_receipts')
WHERE n.nspname = 'nova_ops_checkout_sandbox'
ORDER BY c.relname;

-- 3. Any colliding names anywhere in the DB. Reports names only, not row data.
SELECT n.nspname AS schema_name, c.relname AS object_name, c.relkind AS object_kind
FROM pg_catalog.pg_class AS c
JOIN pg_catalog.pg_namespace AS n ON n.oid = c.relnamespace
WHERE c.relname IN ('starter_test_orders', 'starter_test_receipts')
ORDER BY n.nspname, c.relname;

-- 4. Expected structures if tables already exist; metadata only.
SELECT table_schema, table_name, column_name, data_type, is_nullable
FROM information_schema.columns
WHERE table_schema = 'nova_ops_checkout_sandbox'
  AND table_name IN ('starter_test_orders', 'starter_test_receipts')
ORDER BY table_name, ordinal_position;

-- 5. Constraints if any; inspect for unexpected legacy definitions.
SELECT n.nspname AS schema_name, c.relname AS table_name,
       k.conname AS constraint_name, k.contype AS constraint_type
FROM pg_catalog.pg_constraint AS k
JOIN pg_catalog.pg_class AS c ON c.oid = k.conrelid
JOIN pg_catalog.pg_namespace AS n ON n.oid = c.relnamespace
WHERE n.nspname = 'nova_ops_checkout_sandbox'
  AND c.relname IN ('starter_test_orders', 'starter_test_receipts')
ORDER BY c.relname, k.conname;

-- 6. Read privilege overview for CURRENT ROLE only; no table contents.
SELECT has_schema_privilege(current_user, 'public', 'CREATE') AS current_role_can_create_public,
       has_database_privilege(current_user, current_database(), 'CREATE') AS current_role_can_create_database,
       EXISTS (
         SELECT 1 FROM pg_catalog.pg_namespace
         WHERE nspname = 'nova_ops_checkout_sandbox'
       ) AS receipt_schema_exists;

-- Result interpretation:
-- * expected_staging_database must be true or STOP.
-- * Missing receipt schema/tables -> migration is still pending, NOT an error.
-- * Preexisting objects require a reviewed schema diff before DDL.
-- * This does not identify every Render web-service consumer or test restore.
-- * Do NOT delete old DB credentials based on zero active sessions.
