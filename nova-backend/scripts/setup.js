/**
 * Creates amicor_nova database (if needed), applies schema, and seeds demo accounts.
 */
require('dotenv').config({ path: require('path').join(__dirname, '..', '.env') });

const fs = require('fs');
const path = require('path');
const bcrypt = require('bcryptjs');
const { Client, Pool } = require('pg');

const DATABASE_URL = process.env.DATABASE_URL || 'postgresql://amicor:amicor_dev@localhost:5432/amicor_nova';

function parseDbUrl(url) {
  const parsed = new URL(url);
  return {
    host: parsed.hostname,
    port: Number(parsed.port || 5432),
    user: decodeURIComponent(parsed.username || 'postgres'),
    password: decodeURIComponent(parsed.password || ''),
    database: parsed.pathname.replace(/^\//, '') || 'amicor_nova',
  };
}

async function ensureDatabase() {
  const cfg = parseDbUrl(DATABASE_URL);
  const admin = new Client({
    host: cfg.host,
    port: cfg.port,
    user: cfg.user,
    password: cfg.password,
    database: 'postgres',
  });
  await admin.connect();
  const exists = await admin.query('SELECT 1 FROM pg_database WHERE datname = $1', [cfg.database]);
  if (exists.rowCount === 0) {
    await admin.query(`CREATE DATABASE "${cfg.database}"`);
    console.log(`Created database: ${cfg.database}`);
  }
  await admin.end();
}

async function applySchema(pool) {
  const sqlPath = path.join(__dirname, '..', 'database.sql');
  const sql = fs.readFileSync(sqlPath, 'utf8');
  await pool.query(sql);
  console.log('Schema applied.');
}

async function seedDemoData(pool) {
  const userCount = await pool.query('SELECT COUNT(*)::int AS c FROM users');
  if (userCount.rows[0].c > 0) {
    console.log('Seed skipped — users already exist.');
    return;
  }

  const passwordHash = await bcrypt.hash('Amicor123!', 10);
  const users = [
    ['admin@amicor.local', 'Platform Admin', 'admin'],
    ['dispatcher@amicor.local', 'Dispatch Lead', 'dispatcher'],
    ['driver@amicor.local', 'Field Driver', 'driver'],
    ['rider@amicor.local', 'Patient Rider', 'rider'],
    ['provider@amicor.local', 'Facility Coordinator', 'provider'],
  ];

  const userIds = {};
  for (const [email, name, role] of users) {
    const row = await pool.query(
      `INSERT INTO users (email, password, name, role) VALUES ($1, $2, $3, $4) RETURNING id, email`,
      [email, passwordHash, name, role]
    );
    userIds[email] = row.rows[0].id;
  }

  const facility = await pool.query(
    `INSERT INTO facilities (name, contract_value, trips_per_month, rate, address, phone, email)
     VALUES ($1, $2, $3, $4, $5, $6, $7) RETURNING id`,
    ['Lincoln Medical Center', 125000, 420, 42.5, '123 Health St, Brooklyn, NY', '718-555-0100', 'billing@lincolnmed.example']
  );
  const facilityId = facility.rows[0].id;

  const driverRows = [];
  const driverNames = [
    ['James Smith', '917-555-1001', 'sedan NYC-1001'],
    ['Maria Garcia', '917-555-1002', 'van NYC-1002'],
    ['David Chen', '917-555-1003', 'sedan NYC-1003'],
  ];
  for (const [name, phone, vehicle] of driverNames) {
    const row = await pool.query(
      `INSERT INTO drivers (name, phone, license, vehicle, status, rating, lat, lng, user_id)
       VALUES ($1, $2, $3, $4, 'available', 4.8, 40.7128, -74.0060, $5) RETURNING id`,
      [name, phone, `NY-${phone.slice(-4)}`, vehicle, name === 'James Smith' ? userIds['driver@amicor.local'] : null]
    );
    driverRows.push(row.rows[0].id);
  }

  const patientRows = [];
  const patients = [
    ['Patricia Johnson', '646-555-2001', 'dialysis'],
    ['Robert Williams', '646-555-2002', 'appointment'],
    ['Jennifer Brown', '646-555-2003', 'discharge'],
  ];
  for (const [name, phone, transportType] of patients) {
    const row = await pool.query(
      `INSERT INTO patients (name, facility_id, transport_type, phone, address, insurance)
       VALUES ($1, $2, $3, $4, $5, $6) RETURNING id`,
      [name, facilityId, transportType, phone, '100 Main St, New York, NY', 'Medicaid']
    );
    patientRows.push(row.rows[0].id);
  }

  const tripStatuses = ['pending', 'assigned', 'driver_en_route', 'completed'];
  for (let i = 0; i < 12; i += 1) {
    const status = tripStatuses[i % tripStatuses.length];
    const driverId = status === 'pending' ? null : driverRows[i % driverRows.length];
    await pool.query(
      `INSERT INTO trips (patient_id, driver_id, pickup, dropoff, type, priority, estimated_fare, distance, status, completed_at)
       VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10)`,
      [
        patientRows[i % patientRows.length],
        driverId,
        `${100 + i} Park Ave, New York, NY`,
        `${200 + i} Clinic Blvd, Brooklyn, NY`,
        'medical',
        i % 3 === 0 ? 'urgent' : 'standard',
        28 + i * 3,
        4.5 + i * 0.3,
        status,
        status === 'completed' ? new Date() : null,
      ]
    );
  }

  console.log('Demo seed complete.');
  console.log('Login: dispatcher@amicor.local / Amicor123!');
}

async function main() {
  try {
    await ensureDatabase();
  } catch (err) {
    console.warn('Could not auto-create database (connect to postgres DB manually if needed):', err.message);
  }

  const pool = new Pool({ connectionString: DATABASE_URL, max: 5 });
  try {
    await applySchema(pool);
    await seedDemoData(pool);
    console.log('Setup finished successfully.');
  } finally {
    await pool.end();
  }
}

main().catch((err) => {
  console.error('Setup failed:', err.message);
  process.exit(1);
});
