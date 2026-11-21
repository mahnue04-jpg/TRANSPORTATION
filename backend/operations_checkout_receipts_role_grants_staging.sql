-- AMICOR Operations Starter synthetic receipt ledger: reviewed grant template.
-- NOT EXECUTED. Requires owner-approved staging-only migration and an existing
-- dedicated, non-login-by-default role provisioned by an authorized operator.
-- Never embed database passwords, connection URLs, or real customer data.
-- Run ONLY after receipt tables are created by the separately reviewed
-- operations_checkout_receipts_staging.sql migration.
-- Do not use a Render default/rotated database owner as the writer.
--
-- Target exact database: nova_operations_staging_db_541
-- Target existing restricted login role: nova_ops_receipt_writer
-- This SQL creates NO accounts, secrets, tables, or public schema permissions.
-- The operator must first create the writer role through a secure authorized
-- private connection, supply its password privately in Render, and verify
-- LOGIN, NOSUPERUSER, NOCREATEDB, NOCREATEROLE, NOREPLICATION, NOBYPASSRLS.
BEGIN;
DO $guard$
BEGIN
  IF current_database() <> 'nova_operations_staging_db_541' THEN
    RAISE EXCEPTION 'Wrong DB: staging receipt grants refused';
  END IF;
  IF NOT EXISTS (
    SELECT 1 FROM pg_catalog.pg_roles
    WHERE rolname = 'nova_ops_receipt_writer'
      AND rolcanlogin
      AND NOT rolsuper
      AND NOT rolcreatedb
      AND NOT rolcreaterole
      AND NOT rolreplication
      AND NOT rolbypassrls
  ) THEN
    RAISE EXCEPTION 'Dedicated nonprivileged receipt login role is missing or unsafe';
  END IF;
  IF to_regclass('nova_ops_checkout_sandbox.starter_test_orders') IS NULL
     OR to_regclass('nova_ops_checkout_sandbox.starter_test_receipts') IS NULL THEN
    RAISE EXCEPTION 'Required isolated receipt tables missing; stop';
  END IF;
END
$guard$;

GRANT USAGE ON SCHEMA nova_ops_checkout_sandbox TO nova_ops_receipt_writer;
GRANT SELECT, INSERT ON TABLE
  nova_ops_checkout_sandbox.starter_test_orders,
  nova_ops_checkout_sandbox.starter_test_receipts
  TO nova_ops_receipt_writer;
COMMIT;
-- Post-migration acceptance MUST separately confirm role membership,
-- effective privileges and absence of UPDATE/DELETE/TRUNCATE/REFERENCES/TRIGGER,
-- CREATE on schema, and broad inherited grants. Schema USAGE plus table
-- SELECT/INSERT is not sufficient proof of least privilege in isolation.
-- Never revoke the old database credential until ALL consumers are verified.
