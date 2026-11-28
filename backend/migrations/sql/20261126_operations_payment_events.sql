CREATE TABLE IF NOT EXISTS nova_operations_payment_events (
    event_id text PRIMARY KEY,
    event_type text NOT NULL,
    object_id text NOT NULL,
    received_at timestamptz NOT NULL DEFAULT now(),
    processed_at timestamptz
);
