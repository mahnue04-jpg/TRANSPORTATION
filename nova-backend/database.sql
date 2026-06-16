-- Amicor Nova — PostgreSQL schema for health transportation dispatch
-- Run via: npm run setup

-- Enable UUID generation
CREATE EXTENSION IF NOT EXISTS "pgcrypto";

-- ── Users (authentication & role-based access) ─────────────────────────────
CREATE TABLE IF NOT EXISTS users (
  id          UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  email       VARCHAR(255) NOT NULL UNIQUE,
  password    VARCHAR(255) NOT NULL,
  name        VARCHAR(255) NOT NULL,
  role        VARCHAR(50)  NOT NULL CHECK (role IN (
                'supervisor', 'dispatcher', 'driver', 'compliance', 'admin'
              )),
  created_at  TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_users_email ON users (email);
CREATE INDEX IF NOT EXISTS idx_users_role  ON users (role);

-- ── Facilities (healthcare partners / contract sites) ──────────────────────
CREATE TABLE IF NOT EXISTS facilities (
  id               UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  name             VARCHAR(255) NOT NULL,
  contract_value   NUMERIC(12, 2) NOT NULL DEFAULT 0,
  trips_per_month  INTEGER NOT NULL DEFAULT 0,
  rate             NUMERIC(10, 2) NOT NULL DEFAULT 0,
  status           VARCHAR(50) NOT NULL DEFAULT 'active' CHECK (status IN (
                     'active', 'inactive', 'pending', 'suspended'
                   ))
);

CREATE INDEX IF NOT EXISTS idx_facilities_status ON facilities (status);

-- ── Drivers ────────────────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS drivers (
  id                UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  name              VARCHAR(255) NOT NULL,
  phone             VARCHAR(50),
  license           VARCHAR(100),
  vehicle           VARCHAR(255),
  status            VARCHAR(50) NOT NULL DEFAULT 'offline' CHECK (status IN (
                      'available', 'busy', 'offline', 'on_break'
                    )),
  rating            NUMERIC(3, 2) NOT NULL DEFAULT 5.00,
  trips_today       INTEGER NOT NULL DEFAULT 0,
  earnings_today    NUMERIC(10, 2) NOT NULL DEFAULT 0,
  insurance_expiry  DATE
);

CREATE INDEX IF NOT EXISTS idx_drivers_status ON drivers (status);

-- ── Patients ───────────────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS patients (
  id             UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  name           VARCHAR(255) NOT NULL,
  facility       VARCHAR(255),
  transport_type VARCHAR(100),
  address        TEXT,
  insurance      VARCHAR(255),
  phone          VARCHAR(50),
  status         VARCHAR(50) NOT NULL DEFAULT 'active' CHECK (status IN (
                   'active', 'inactive', 'pending'
                 ))
);

CREATE INDEX IF NOT EXISTS idx_patients_status ON patients (status);

-- ── Trips ──────────────────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS trips (
  id             UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  patient_id     UUID REFERENCES patients (id) ON DELETE SET NULL,
  driver_id      UUID REFERENCES drivers (id) ON DELETE SET NULL,
  pickup         TEXT NOT NULL,
  dropoff        TEXT NOT NULL,
  type           VARCHAR(100),
  priority       VARCHAR(50) NOT NULL DEFAULT 'normal' CHECK (priority IN (
                   'low', 'normal', 'high', 'urgent'
                 )),
  estimated_fare NUMERIC(10, 2),
  actual_fare    NUMERIC(10, 2),
  distance       NUMERIC(10, 2),
  status         VARCHAR(50) NOT NULL DEFAULT 'pending' CHECK (status IN (
                   'pending', 'assigned', 'in_progress', 'completed', 'cancelled'
                 )),
  created_at     TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  completed_at   TIMESTAMPTZ
);

CREATE INDEX IF NOT EXISTS idx_trips_status     ON trips (status);
CREATE INDEX IF NOT EXISTS idx_trips_patient_id ON trips (patient_id);
CREATE INDEX IF NOT EXISTS idx_trips_driver_id  ON trips (driver_id);
CREATE INDEX IF NOT EXISTS idx_trips_created_at ON trips (created_at DESC);

-- ── Payments (Stripe integration) ──────────────────────────────────────────
CREATE TABLE IF NOT EXISTS payments (
  id                UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  stripe_payment_id VARCHAR(255) UNIQUE,
  amount            NUMERIC(10, 2) NOT NULL,
  status            VARCHAR(50) NOT NULL DEFAULT 'pending' CHECK (status IN (
                      'pending', 'succeeded', 'failed', 'refunded'
                    )),
  facility_id       UUID REFERENCES facilities (id) ON DELETE SET NULL,
  trip_id           UUID REFERENCES trips (id) ON DELETE SET NULL,
  created_at        TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_payments_status      ON payments (status);
CREATE INDEX IF NOT EXISTS idx_payments_facility_id ON payments (facility_id);
CREATE INDEX IF NOT EXISTS idx_payments_trip_id     ON payments (trip_id);

-- ── Alerts (operational notifications) ─────────────────────────────────────
CREATE TABLE IF NOT EXISTS alerts (
  id         UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  type       VARCHAR(100) NOT NULL,
  message    TEXT NOT NULL,
  priority   VARCHAR(50) NOT NULL DEFAULT 'normal' CHECK (priority IN (
               'low', 'normal', 'high', 'critical'
             )),
  read       BOOLEAN NOT NULL DEFAULT FALSE,
  created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_alerts_read        ON alerts (read);
CREATE INDEX IF NOT EXISTS idx_alerts_created_at  ON alerts (created_at DESC);

-- ── Audit log (compliance & traceability) ──────────────────────────────────
CREATE TABLE IF NOT EXISTS audit_log (
  id          UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  user_id     UUID REFERENCES users (id) ON DELETE SET NULL,
  action      VARCHAR(100) NOT NULL,
  entity_type VARCHAR(100),
  entity_id   UUID,
  details     JSONB,
  created_at  TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_audit_log_user_id     ON audit_log (user_id);
CREATE INDEX IF NOT EXISTS idx_audit_log_entity       ON audit_log (entity_type, entity_id);
CREATE INDEX IF NOT EXISTS idx_audit_log_created_at   ON audit_log (created_at DESC);
