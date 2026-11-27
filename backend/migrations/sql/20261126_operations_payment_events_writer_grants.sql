-- Least-privilege writer for Operations payment event intake.
-- Apply only after 20261126_operations_payment_events.sql on database `amicor`.
-- Does not enable customer sales or grant DELETE.

DO $$
BEGIN
  IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'nova_ops_event_writer') THEN
    CREATE ROLE nova_ops_event_writer NOINHERIT;
  END IF;
END
$$;

REVOKE ALL ON TABLE public.nova_operations_payment_events FROM PUBLIC;
REVOKE ALL ON TABLE public.nova_operations_payment_events FROM nova_ops_event_writer;
GRANT SELECT (event_id, event_type, object_id, received_at, processed_at)
  ON public.nova_operations_payment_events TO nova_ops_event_writer;
GRANT INSERT (event_id, event_type, object_id)
  ON public.nova_operations_payment_events TO nova_ops_event_writer;
