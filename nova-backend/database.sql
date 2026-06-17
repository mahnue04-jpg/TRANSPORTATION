-- Amicor Nova PostgreSQL schema
-- Health transportation dispatch platform

CREATE EXTENSION IF NOT EXISTS "pgcrypto";

CREATE TABLE IF NOT EXISTS users (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  email VARCHAR(255) NOT NULL UNIQUE,
  password VARCHAR(255) NOT NULL,
  name VARCHAR(255) NOT NULL,
  role VARCHAR(50) NOT NULL CHECK (
    role IN ('supervisor', 'dispatcher', 'driver', 'compliance', 'admin', 'rider', 'provider')
  ),
  created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS facilities (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  name VARCHAR(255) NOT NULL,
  contract_value NUMERIC(12, 2) DEFAULT 0,
  trips_per_month INTEGER DEFAULT 0,
  rate NUMERIC(8, 2) DEFAULT 0,
  status VARCHAR(32) NOT NULL DEFAULT 'active',
  address TEXT,
  phone VARCHAR(32),
  email VARCHAR(256),
  created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS drivers (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  user_id UUID REFERENCES users(id) ON DELETE SET NULL,
  name VARCHAR(255) NOT NULL,
  phone VARCHAR(32),
  license VARCHAR(64),
  vehicle VARCHAR(128),
  status VARCHAR(32) NOT NULL DEFAULT 'available',
  rating NUMERIC(3, 2) DEFAULT 5.0,
  trips_today INTEGER DEFAULT 0,
  earnings_today NUMERIC(10, 2) DEFAULT 0,
  insurance_expiry DATE,
  lat NUMERIC(10, 6),
  lng NUMERIC(10, 6),
  created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS patients (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  name VARCHAR(255) NOT NULL,
  facility_id UUID REFERENCES facilities(id) ON DELETE SET NULL,
  transport_type VARCHAR(64) DEFAULT 'medical',
  address TEXT,
  insurance VARCHAR(128),
  phone VARCHAR(32),
  email VARCHAR(256),
  status VARCHAR(32) NOT NULL DEFAULT 'active',
  created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS trips (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  patient_id UUID REFERENCES patients(id) ON DELETE SET NULL,
  driver_id UUID REFERENCES drivers(id) ON DELETE SET NULL,
  pickup TEXT NOT NULL,
  dropoff TEXT NOT NULL,
  type VARCHAR(64) DEFAULT 'medical',
  priority VARCHAR(32) DEFAULT 'standard',
  estimated_fare NUMERIC(10, 2) DEFAULT 0,
  actual_fare NUMERIC(10, 2),
  distance NUMERIC(8, 2) DEFAULT 0,
  pickup_lat NUMERIC(10, 6),
  pickup_lng NUMERIC(10, 6),
  dropoff_lat NUMERIC(10, 6),
  dropoff_lng NUMERIC(10, 6),
  facility_id UUID REFERENCES facilities(id) ON DELETE SET NULL,
  scheduled_at TIMESTAMPTZ,
  status VARCHAR(32) NOT NULL DEFAULT 'pending',
  notes TEXT,
  created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  accepted_at TIMESTAMPTZ,
  arrived_at TIMESTAMPTZ,
  started_at TIMESTAMPTZ,
  completed_at TIMESTAMPTZ
);

CREATE TABLE IF NOT EXISTS payments (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  stripe_payment_id VARCHAR(128),
  amount NUMERIC(10, 2) NOT NULL,
  status VARCHAR(32) NOT NULL DEFAULT 'pending',
  facility_id UUID REFERENCES facilities(id) ON DELETE SET NULL,
  trip_id UUID REFERENCES trips(id) ON DELETE SET NULL,
  created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS alerts (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  type VARCHAR(64) NOT NULL,
  message TEXT NOT NULL,
  priority VARCHAR(16) NOT NULL DEFAULT 'medium',
  read BOOLEAN NOT NULL DEFAULT FALSE,
  trip_id UUID REFERENCES trips(id) ON DELETE SET NULL,
  created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS audit_log (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  user_id UUID REFERENCES users(id) ON DELETE SET NULL,
  action VARCHAR(128) NOT NULL,
  entity_type VARCHAR(64),
  entity_id UUID,
  details JSONB,
  created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_trips_status ON trips(status);
CREATE INDEX IF NOT EXISTS idx_trips_driver ON trips(driver_id);
CREATE INDEX IF NOT EXISTS idx_drivers_status ON drivers(status);
CREATE INDEX IF NOT EXISTS idx_alerts_read ON alerts(read);

CREATE TABLE IF NOT EXISTS driver_locations (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  driver_id UUID NOT NULL REFERENCES drivers(id) ON DELETE CASCADE,
  trip_id UUID REFERENCES trips(id) ON DELETE SET NULL,
  lat NUMERIC(10, 6) NOT NULL,
  lng NUMERIC(10, 6) NOT NULL,
  speed_kph NUMERIC(6, 2),
  recorded_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS invoices (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  trip_id UUID REFERENCES trips(id) ON DELETE CASCADE,
  patient_id UUID REFERENCES patients(id) ON DELETE SET NULL,
  facility_id UUID REFERENCES facilities(id) ON DELETE SET NULL,
  amount NUMERIC(10, 2) NOT NULL,
  status VARCHAR(32) NOT NULL DEFAULT 'draft',
  recipient_email VARCHAR(256),
  sendgrid_message_id VARCHAR(128),
  sent_at TIMESTAMPTZ,
  created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS bulk_schedules (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  facility_id UUID REFERENCES facilities(id) ON DELETE SET NULL,
  created_by UUID REFERENCES users(id) ON DELETE SET NULL,
  label VARCHAR(255) NOT NULL,
  trips_json JSONB NOT NULL,
  status VARCHAR(32) NOT NULL DEFAULT 'pending',
  created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS notification_log (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  channel VARCHAR(16) NOT NULL,
  recipient VARCHAR(256) NOT NULL,
  message TEXT,
  provider_ref VARCHAR(128),
  trip_id UUID,
  status VARCHAR(32) NOT NULL DEFAULT 'sent',
  created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_driver_locations_driver ON driver_locations(driver_id, recorded_at DESC);
CREATE INDEX IF NOT EXISTS idx_trips_facility ON trips(facility_id);
