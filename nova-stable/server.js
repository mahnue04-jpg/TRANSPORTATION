/**
 * Amicor Nova Stable — SQLite + HTTP only (no WebSockets, no SSE, no Socket.IO)
 * Deploy: cd nova-stable && npm install && npm start
 */

const express = require('express');
const sqlite3 = require('sqlite3').verbose();
const bcrypt = require('bcryptjs');
const jwt = require('jsonwebtoken');
const cors = require('cors');
const path = require('path');
const fs = require('fs');
const { randomUUID } = require('crypto');

const app = express();
const PORT = process.env.PORT || 8011;
const JWT_SECRET = process.env.JWT_SECRET || 'amicor-nova-secret-2026';

app.use(cors());
app.use(express.json());
app.use(express.static(path.join(__dirname, 'public'), {
  setHeaders(res, filePath) {
    if (/\.(js|css|html)$/i.test(filePath)) {
      res.setHeader('Cache-Control', 'no-cache, no-store, must-revalidate');
    }
  },
}));

const dbPath = process.env.SQLITE_PATH || path.join(__dirname, 'amicor_nova.db');
const db = new sqlite3.Database(dbPath);

function run(sql, params = []) {
  return new Promise((resolve, reject) => {
    db.run(sql, params, function onRun(err) {
      if (err) reject(err);
      else resolve(this);
    });
  });
}

function get(sql, params = []) {
  return new Promise((resolve, reject) => {
    db.get(sql, params, (err, row) => (err ? reject(err) : resolve(row)));
  });
}

function all(sql, params = []) {
  return new Promise((resolve, reject) => {
    db.all(sql, params, (err, rows) => (err ? reject(err) : resolve(rows)));
  });
}

async function initDb() {
  await run(`CREATE TABLE IF NOT EXISTS users (
    id TEXT PRIMARY KEY, email TEXT UNIQUE, password_hash TEXT,
    first_name TEXT, last_name TEXT, name TEXT,
    role TEXT DEFAULT 'driver', phone TEXT,
    is_active INTEGER DEFAULT 1, created_at DATETIME DEFAULT CURRENT_TIMESTAMP
  )`);

  await run(`CREATE TABLE IF NOT EXISTS patients (
    id TEXT PRIMARY KEY, first_name TEXT, last_name TEXT, phone TEXT,
    address TEXT, medical_notes TEXT, emergency_contact TEXT,
    is_active INTEGER DEFAULT 1, created_at DATETIME DEFAULT CURRENT_TIMESTAMP
  )`);

  await run(`CREATE TABLE IF NOT EXISTS drivers (
    id TEXT PRIMARY KEY, user_id TEXT, license_number TEXT,
    vehicle_id TEXT, certifications TEXT, status TEXT DEFAULT 'offline',
    lat REAL, lng REAL, earnings_today REAL DEFAULT 0, trips_today INTEGER DEFAULT 0,
    is_active INTEGER DEFAULT 1, created_at DATETIME DEFAULT CURRENT_TIMESTAMP
  )`);

  await run(`CREATE TABLE IF NOT EXISTS trips (
    id TEXT PRIMARY KEY, patient_id TEXT, driver_id TEXT,
    pickup_address TEXT, destination TEXT, dropoff TEXT,
    trip_type TEXT, priority TEXT, special_requirements TEXT,
    status TEXT DEFAULT 'pending', estimated_fare REAL, actual_fare REAL,
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP
  )`);

  await run(`CREATE TABLE IF NOT EXISTS payments (
    id TEXT PRIMARY KEY, trip_id TEXT, amount REAL,
    status TEXT DEFAULT 'pending', payment_method TEXT,
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP
  )`);

  await run(`CREATE TABLE IF NOT EXISTS activity_log (
    id TEXT PRIMARY KEY, type TEXT, description TEXT,
    user_id TEXT, trip_id TEXT, created_at DATETIME DEFAULT CURRENT_TIMESTAMP
  )`);

  const count = await get('SELECT COUNT(*) AS c FROM users');
  if (count.c > 0) return;

  const demoHash = await bcrypt.hash('Amicor123!', 10);
  const adminHash = await bcrypt.hash('admin123', 10);

  const users = [
    ['admin-001', 'admin@amicor.com', adminHash, 'System', 'Administrator', 'admin', '(555) 000-0000'],
    ['usr-dispatch', 'dispatcher@amicor.local', demoHash, 'Dispatch', 'Lead', 'dispatcher', '(555) 000-0001'],
    ['usr-driver', 'driver@amicor.local', demoHash, 'Field', 'Driver', 'driver', '(555) 000-0002'],
    ['usr-rider', 'rider@amicor.local', demoHash, 'Patient', 'Rider', 'rider', '(555) 000-0003'],
    ['usr-provider', 'provider@amicor.local', demoHash, 'Facility', 'Coordinator', 'provider', '(555) 000-0004'],
    ['drv-001', 'james.wilson@amicor.com', demoHash, 'James', 'Wilson', 'driver', '(555) 201-0001'],
    ['drv-002', 'sarah.martinez@amicor.com', demoHash, 'Sarah', 'Martinez', 'driver', '(555) 201-0002'],
    ['drv-003', 'michael.brown@amicor.com', demoHash, 'Michael', 'Brown', 'driver', '(555) 201-0003'],
  ];

  for (const [id, email, hash, first, last, role, phone] of users) {
    await run(
      `INSERT OR IGNORE INTO users (id, email, password_hash, first_name, last_name, name, role, phone)
       VALUES (?, ?, ?, ?, ?, ?, ?, ?)`,
      [id, email, hash, first, last, `${first} ${last}`, role, phone]
    );
  }

  const patients = [
    ['pat-001', 'Margaret', 'Johnson', '(555) 101-0001', '123 Oak Street', 'Wheelchair accessible'],
    ['pat-002', 'Robert', 'Chen', '(555) 101-0002', '456 Pine Avenue', 'Oxygen tank'],
    ['pat-003', 'Dorothy', 'Williams', '(555) 101-0003', '789 Elm Drive', 'Dialysis 3x/week'],
  ];
  for (const p of patients) {
    await run(
      `INSERT OR IGNORE INTO patients (id, first_name, last_name, phone, address, medical_notes) VALUES (?, ?, ?, ?, ?, ?)`,
      p
    );
  }

  const drivers = [
    ['driver-001', 'drv-001', 'DL-284756', 'AMB-001', 'CPR,First Aid', 'available', 40.7128, -74.006],
    ['driver-002', 'drv-002', 'DL-284757', 'AMB-002', 'CPR,First Aid', 'busy', 40.758, -73.9855],
    ['driver-003', 'usr-driver', 'DL-284758', 'AMB-003', 'CPR,First Aid', 'available', 40.7306, -73.9352],
  ];
  for (const d of drivers) {
    await run(
      `INSERT OR IGNORE INTO drivers (id, user_id, license_number, vehicle_id, certifications, status, lat, lng) VALUES (?, ?, ?, ?, ?, ?, ?, ?)`,
      d
    );
  }

  const trips = [
    ['TRP-2847', 'pat-001', 'driver-001', 'Sunrise Medical Center', 'Willowbrook Nursing Home', 'medical', 'standard', 'driver_en_route', 45],
    ['TRP-2848', 'pat-002', 'driver-002', 'Downtown Clinic', 'St Marys Hospital', 'medical', 'urgent', 'in_progress', 65],
    ['TRP-2849', 'pat-003', null, 'Home - 452 Oak St', 'Memorial Hospital', 'dialysis', 'standard', 'pending', 35],
    ['TRP-2850', 'pat-001', 'driver-003', 'Riverside Health', 'Rehab Center West', 'discharge', 'standard', 'assigned', 55],
    ['TRP-2851', 'pat-002', 'driver-002', 'Home - 789 Pine Ave', 'City General Hospital', 'medical', 'standard', 'completed', 40],
  ];
  for (const t of trips) {
    await run(
      `INSERT OR IGNORE INTO trips (id, patient_id, driver_id, pickup_address, destination, dropoff, trip_type, priority, status, estimated_fare)
       VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)`,
      [t[0], t[1], t[2], t[3], t[4], t[4], t[5], t[6], t[7], t[8]]
    );
  }

  await run(`INSERT OR IGNORE INTO payments (id, trip_id, amount, status, payment_method) VALUES ('pay-001', 'TRP-2851', 40.00, 'completed', 'card')`);
  await run(`INSERT OR IGNORE INTO activity_log (id, type, description, user_id, trip_id) VALUES ('act-001', 'trip', 'Demo platform initialized', 'admin-001', 'TRP-2847')`);

  console.log('SQLite seed complete.');
  console.log('Login: dispatcher@amicor.local / Amicor123!  OR  admin@amicor.com / admin123');
}

function authenticateToken(req, res, next) {
  const authHeader = req.headers.authorization || '';
  const token = authHeader.startsWith('Bearer ') ? authHeader.slice(7) : null;
  if (!token) return res.status(401).json({ error: 'Access token required' });
  jwt.verify(token, JWT_SECRET, (err, payload) => {
    if (err) return res.status(403).json({ error: 'Invalid token' });
    req.user = payload;
    next();
  });
}

function displayName(row) {
  if (!row) return '';
  return row.name || `${row.first_name || ''} ${row.last_name || ''}`.trim();
}

async function syncDriverAvailability() {
  await run(`
    UPDATE drivers SET status = 'available'
    WHERE status <> 'offline'
      AND id NOT IN (
        SELECT driver_id FROM trips
        WHERE driver_id IS NOT NULL
          AND status NOT IN ('completed', 'cancelled', 'no_show', 'pending')
      )
  `);
  await run(`
    UPDATE drivers SET status = 'busy'
    WHERE status <> 'offline'
      AND id IN (
        SELECT driver_id FROM trips
        WHERE driver_id IS NOT NULL
          AND status NOT IN ('completed', 'cancelled', 'no_show', 'pending')
      )
  `);
}

app.post('/api/auth/login', async (req, res) => {
  try {
    const { email, password } = req.body || {};
    const user = await get('SELECT * FROM users WHERE email = ?', [String(email || '').toLowerCase().trim()]);
    if (!user) return res.status(401).json({ error: 'Invalid credentials' });
    const valid = await bcrypt.compare(String(password || ''), user.password_hash);
    if (!valid) return res.status(401).json({ error: 'Invalid credentials' });
    const token = jwt.sign({ sub: user.id, userId: user.id, email: user.email, role: user.role }, JWT_SECRET, { expiresIn: '24h' });
    res.json({
      token,
      user: {
        id: user.id,
        email: user.email,
        name: displayName(user),
        first_name: user.first_name,
        last_name: user.last_name,
        role: user.role,
      },
    });
  } catch (err) {
    res.status(500).json({ error: err.message });
  }
});

app.post('/api/auth/register', async (req, res) => {
  try {
    const { email, password, first_name, last_name, role = 'driver' } = req.body || {};
    const id = randomUUID();
    const hash = await bcrypt.hash(String(password), 10);
    await run(
      'INSERT INTO users (id, email, password_hash, first_name, last_name, name, role) VALUES (?, ?, ?, ?, ?, ?, ?)',
      [id, email, hash, first_name, last_name, `${first_name} ${last_name}`, role]
    );
    const token = jwt.sign({ sub: id, userId: id, email, role }, JWT_SECRET, { expiresIn: '24h' });
    res.json({ token, user: { id, email, first_name, last_name, name: `${first_name} ${last_name}`, role } });
  } catch (err) {
    res.status(400).json({ error: err.message });
  }
});

app.get('/api/auth/me', authenticateToken, async (req, res) => {
  const user = await get('SELECT id, email, first_name, last_name, name, role FROM users WHERE id = ?', [req.user.sub || req.user.userId]);
  if (!user) return res.status(404).json({ error: 'User not found' });
  res.json({ ...user, name: displayName(user) });
});

app.get('/api/health', (_req, res) => {
  res.json({ ok: true, status: 'healthy', database: 'sqlite', service: 'amicor-nova-stable', port: PORT, ts: new Date().toISOString() });
});

app.get('/api/ops/readiness', async (_req, res) => {
  await syncDriverAvailability();
  const active = await get(`SELECT COUNT(*) AS c FROM trips WHERE status NOT IN ('completed','cancelled','no_show')`);
  const pending = await get(`SELECT COUNT(*) AS c FROM trips WHERE status = 'pending' AND driver_id IS NULL`);
  const drivers = await get(`SELECT COUNT(*) AS total, SUM(CASE WHEN status = 'available' THEN 1 ELSE 0 END) AS available FROM drivers`);
  res.json({
    ok: true,
    active_trips: active.c,
    pending_dispatch: pending.c,
    drivers_total: drivers.total,
    drivers_available: drivers.available || 0,
    ts: new Date().toISOString(),
  });
});

app.post('/api/ops/free-capacity', authenticateToken, async (_req, res) => {
  const result = await run(
    `UPDATE trips SET status = 'completed', actual_fare = COALESCE(actual_fare, estimated_fare)
     WHERE status NOT IN ('completed', 'cancelled', 'no_show', 'pending')`
  );
  await syncDriverAvailability();
  const available = await get(`SELECT COUNT(*) AS c FROM drivers WHERE status = 'available'`);
  res.json({ completed_trips: result.changes, drivers_available: available.c, ok: true });
});

app.get('/api/dashboard/stats', authenticateToken, async (_req, res) => {
  const total = await get('SELECT COUNT(*) AS total_trips FROM trips');
  const active = await get(`SELECT COUNT(*) AS active_trips FROM trips WHERE status NOT IN ('completed','cancelled','no_show')`);
  const revenue = await get(`SELECT COALESCE(SUM(amount), 0) AS revenue FROM payments WHERE status = 'completed'`);
  const drivers = await get('SELECT COUNT(*) AS total_drivers FROM drivers WHERE is_active = 1');
  const online = await get(`SELECT COUNT(*) AS online_drivers FROM drivers WHERE status IN ('available','online','busy') AND is_active = 1`);
  res.json({
    total_trips: total.total_trips,
    active_trips: active.active_trips,
    completed_trips: (total.total_trips || 0) - (active.active_trips || 0),
    revenue_total: revenue.revenue,
    monthly_revenue: revenue.revenue,
    total_drivers: drivers.total_drivers,
    online_drivers: online.online_drivers,
  });
});

app.get('/api/revenue', authenticateToken, async (_req, res) => {
  const completed = await get(`SELECT COUNT(*) AS c, COALESCE(SUM(COALESCE(actual_fare, estimated_fare)),0) AS rev FROM trips WHERE status = 'completed'`);
  const active = await get(`SELECT COUNT(*) AS c FROM trips WHERE status NOT IN ('completed','cancelled','no_show')`);
  res.json({ completed_trips: completed.c, active_trips: active.c, revenue_total: completed.rev, pipeline_value: 0 });
});

app.get('/api/trips', authenticateToken, async (_req, res) => {
  const rows = await all(
    `SELECT t.*,
      p.first_name || ' ' || p.last_name AS patient_name,
      d_u.first_name || ' ' || d_u.last_name AS driver_name,
      t.pickup_address AS pickup,
      COALESCE(t.dropoff, t.destination) AS dropoff
     FROM trips t
     LEFT JOIN patients p ON t.patient_id = p.id
     LEFT JOIN drivers d ON t.driver_id = d.id
     LEFT JOIN users d_u ON d.user_id = d_u.id
     ORDER BY t.created_at DESC LIMIT 100`
  );
  res.json(rows);
});

app.post('/api/trips', authenticateToken, async (req, res) => {
  const { patient_id, pickup, dropoff, pickup_address, destination, trip_type, priority, special_requirements, distance } = req.body || {};
  const pickupText = pickup || pickup_address;
  const dropText = dropoff || destination;
  if (!pickupText || !dropText) return res.status(400).json({ error: 'pickup and dropoff required' });
  const id = 'TRP-' + Math.floor(1000 + Math.random() * 9000);
  const fare = 18 + (Number(distance) || 5) * 2.75;
  await run(
    `INSERT INTO trips (id, patient_id, pickup_address, destination, dropoff, trip_type, priority, special_requirements, status, estimated_fare)
     VALUES (?, ?, ?, ?, ?, ?, ?, ?, 'pending', ?)`,
    [id, patient_id || null, pickupText, dropText, dropText, trip_type || 'medical', priority || 'standard', special_requirements || null, fare]
  );
  const trip = await get('SELECT * FROM trips WHERE id = ?', [id]);
  res.status(201).json({ ...trip, pickup: trip.pickup_address, dropoff: trip.dropoff || trip.destination });
});

app.patch('/api/trips/:id/status', authenticateToken, async (req, res) => {
  const { status, driver_id } = req.body || {};
  await run('UPDATE trips SET status = ?, driver_id = COALESCE(?, driver_id) WHERE id = ?', [status, driver_id || null, req.params.id]);
  if (status === 'completed') {
    await run('UPDATE trips SET actual_fare = COALESCE(actual_fare, estimated_fare) WHERE id = ?', [req.params.id]);
  }
  const trip = await get('SELECT * FROM trips WHERE id = ?', [req.params.id]);
  if (['completed', 'cancelled', 'no_show'].includes(status) && trip.driver_id) {
    await run(`UPDATE drivers SET status = 'available', trips_today = trips_today + 1 WHERE id = ?`, [trip.driver_id]);
  }
  await syncDriverAvailability();
  res.json(trip);
});

app.put('/api/trips/:id/status', authenticateToken, async (req, res) => {
  req.body = req.body || {};
  const status = req.body.status;
  await run('UPDATE trips SET status = ? WHERE id = ?', [status, req.params.id]);
  const trip = await get('SELECT * FROM trips WHERE id = ?', [req.params.id]);
  if (['completed', 'cancelled', 'no_show'].includes(status) && trip.driver_id) {
    await run(`UPDATE drivers SET status = 'available' WHERE id = ?`, [trip.driver_id]);
  }
  await syncDriverAvailability();
  res.json(trip);
});

app.post('/api/trips/:id/accept', authenticateToken, async (req, res) => {
  await run(`UPDATE trips SET status = 'driver_en_route' WHERE id = ?`, [req.params.id]);
  res.json(await get('SELECT * FROM trips WHERE id = ?', [req.params.id]));
});

app.put('/api/trips/:id/assign', authenticateToken, async (req, res) => {
  const { driver_id } = req.body || {};
  await run(`UPDATE trips SET driver_id = ?, status = 'assigned' WHERE id = ?`, [driver_id, req.params.id]);
  await run(`UPDATE drivers SET status = 'busy' WHERE id = ?`, [driver_id]);
  res.json(await get('SELECT * FROM trips WHERE id = ?', [req.params.id]));
});

app.post('/api/dispatch/auto-assign/:tripId', authenticateToken, async (req, res) => {
  const trip = await get('SELECT * FROM trips WHERE id = ?', [req.params.tripId]);
  if (!trip) return res.status(404).json({ error: 'Trip not found' });
  const driver = await get(
    `SELECT d.* FROM drivers d
     WHERE d.is_active = 1 AND d.status <> 'offline'
       AND NOT EXISTS (
         SELECT 1 FROM trips t
         WHERE t.driver_id = d.id
           AND t.status NOT IN ('completed','cancelled','no_show','pending')
       )
     ORDER BY d.trips_today ASC LIMIT 1`
  );
  if (!driver) return res.status(409).json({ error: 'No available drivers — all drivers are on active trips' });
  await run(`UPDATE trips SET driver_id = ?, status = 'assigned' WHERE id = ?`, [driver.id, trip.id]);
  await run(`UPDATE drivers SET status = 'busy' WHERE id = ?`, [driver.id]);
  const driverName = await get(
    `SELECT COALESCE(u.first_name || ' ' || u.last_name, u.email, d.id) AS name
     FROM drivers d LEFT JOIN users u ON d.user_id = u.id WHERE d.id = ?`,
    [driver.id]
  );
  res.json({
    trip: await get('SELECT * FROM trips WHERE id = ?', [trip.id]),
    dispatch: { driver_id: driver.id, driver_name: driverName && driverName.name, distance_miles: null },
  });
});

app.get('/api/drivers', authenticateToken, async (_req, res) => {
  const rows = await all(
    `SELECT d.*, u.first_name, u.last_name, u.email,
      (SELECT COUNT(*) FROM trips WHERE driver_id = d.id AND status = 'completed') AS total_trips
     FROM drivers d JOIN users u ON d.user_id = u.id WHERE d.is_active = 1`
  );
  res.json(rows);
});

app.get('/api/dispatcher/live', authenticateToken, async (_req, res) => {
  await syncDriverAvailability();
  const drivers = await all(
    `SELECT d.id, d.status, d.lat, d.lng, d.vehicle_id AS vehicle,
      COALESCE(u.first_name || ' ' || u.last_name, u.email, d.id) AS name,
      (SELECT COUNT(*) FROM trips t
        WHERE t.driver_id = d.id
          AND t.status NOT IN ('completed','cancelled','no_show','pending')) AS active_trip_count
     FROM drivers d
     LEFT JOIN users u ON d.user_id = u.id
     WHERE d.is_active = 1`
  );
  const trips = await all(
    `SELECT t.*,
      p.first_name || ' ' || p.last_name AS patient_name,
      d_u.first_name || ' ' || d_u.last_name AS driver_name,
      t.pickup_address AS pickup,
      COALESCE(t.dropoff, t.destination) AS dropoff
     FROM trips t
     LEFT JOIN patients p ON t.patient_id = p.id
     LEFT JOIN drivers d ON t.driver_id = d.id
     LEFT JOIN users d_u ON d.user_id = d_u.id
     WHERE t.status NOT IN ('completed','cancelled','no_show')
     ORDER BY t.created_at DESC`
  );
  res.json({ drivers, trips, alerts: [], ts: new Date().toISOString() });
});

app.post('/api/dispatch/auto-assign-pending', authenticateToken, async (_req, res) => {
  await syncDriverAvailability();
  const pending = await all(`SELECT id FROM trips WHERE status = 'pending' AND driver_id IS NULL ORDER BY created_at ASC LIMIT 50`);
  let assigned = 0;
  for (const row of pending) {
    const trip = await get('SELECT * FROM trips WHERE id = ?', [row.id]);
    const driver = await get(
      `SELECT d.* FROM drivers d
       WHERE d.is_active = 1 AND d.status <> 'offline'
         AND NOT EXISTS (
           SELECT 1 FROM trips t
           WHERE t.driver_id = d.id
             AND t.status NOT IN ('completed','cancelled','no_show','pending')
         )
       ORDER BY d.trips_today ASC LIMIT 1`
    );
    if (!driver) break;
    await run(`UPDATE trips SET driver_id = ?, status = 'assigned' WHERE id = ?`, [driver.id, trip.id]);
    await run(`UPDATE drivers SET status = 'busy' WHERE id = ?`, [driver.id]);
    assigned += 1;
  }
  await syncDriverAvailability();
  res.json({ assigned, results: [] });
});

app.get('/api/patients', authenticateToken, async (_req, res) => {
  res.json(await all('SELECT * FROM patients WHERE is_active = 1 ORDER BY created_at DESC'));
});

app.get('/api/payments', authenticateToken, async (_req, res) => {
  res.json(await all('SELECT * FROM payments ORDER BY created_at DESC LIMIT 100'));
});

app.get('/api/activity', authenticateToken, async (_req, res) => {
  res.json(await all('SELECT * FROM activity_log ORDER BY created_at DESC LIMIT 50'));
});

app.get('/api/driver/me', authenticateToken, async (req, res) => {
  const driver = await get(
    `SELECT d.* FROM drivers d JOIN users u ON d.user_id = u.id WHERE u.id = ?`,
    [req.user.sub || req.user.userId]
  ) || await get('SELECT * FROM drivers LIMIT 1');
  const activeTrip = driver
    ? await get(`SELECT t.*, p.first_name || ' ' || p.last_name AS patient_name, p.phone AS patient_phone,
        t.pickup_address AS pickup, COALESCE(t.dropoff,t.destination) AS dropoff
        FROM trips t LEFT JOIN patients p ON t.patient_id = p.id
        WHERE t.driver_id = ? AND t.status NOT IN ('completed','cancelled','no_show') ORDER BY t.created_at DESC LIMIT 1`, [driver.id])
    : null;
  res.json({ driver, active_trip: activeTrip });
});

app.get('/api/driver/earnings', authenticateToken, async (req, res) => {
  const driver = await get(`SELECT d.* FROM drivers d JOIN users u ON d.user_id = u.id WHERE u.id = ?`, [req.user.sub || req.user.userId]);
  if (!driver) return res.status(404).json({ error: 'Driver not found' });
  const totals = await get(`SELECT COUNT(*) AS completed_count, COALESCE(SUM(COALESCE(actual_fare,estimated_fare)),0) AS lifetime FROM trips WHERE driver_id = ? AND status = 'completed'`, [driver.id]);
  res.json({ earnings_today: driver.earnings_today || 0, trips_today: driver.trips_today || 0, completed_count: totals.completed_count, lifetime_earnings: totals.lifetime });
});

app.post('/api/driver/gps', authenticateToken, async (req, res) => {
  const { lat, lng } = req.body || {};
  const driver = await get(`SELECT d.id FROM drivers d JOIN users u ON d.user_id = u.id WHERE u.id = ?`, [req.user.sub || req.user.userId]);
  if (!driver) return res.status(404).json({ error: 'Driver not found' });
  await run('UPDATE drivers SET lat = ?, lng = ? WHERE id = ?', [lat, lng, driver.id]);
  res.json(await get('SELECT * FROM drivers WHERE id = ?', [driver.id]));
});

async function tripRow(id) {
  return get(
    `SELECT t.*, p.first_name || ' ' || p.last_name AS patient_name, p.phone AS patient_phone,
      d_u.first_name || ' ' || d_u.last_name AS driver_name,
      t.pickup_address AS pickup, COALESCE(t.dropoff, t.destination) AS dropoff
     FROM trips t LEFT JOIN patients p ON t.patient_id = p.id
     LEFT JOIN drivers d ON t.driver_id = d.id LEFT JOIN users d_u ON d.user_id = d_u.id
     WHERE t.id = ?`,
    [id]
  );
}

app.put('/api/trips/:id/complete', authenticateToken, async (req, res) => {
  await run(`UPDATE trips SET status = 'completed', actual_fare = COALESCE(actual_fare, estimated_fare) WHERE id = ?`, [req.params.id]);
  const trip = await get('SELECT * FROM trips WHERE id = ?', [req.params.id]);
  if (trip && trip.driver_id) {
    await run(`UPDATE drivers SET status = 'available', trips_today = trips_today + 1 WHERE id = ?`, [trip.driver_id]);
  }
  await syncDriverAvailability();
  res.json(await tripRow(req.params.id));
});

app.post('/api/trips/:id/no-show', authenticateToken, async (req, res) => {
  await run(`UPDATE trips SET status = 'no_show' WHERE id = ?`, [req.params.id]);
  const trip = await get('SELECT * FROM trips WHERE id = ?', [req.params.id]);
  if (trip && trip.driver_id) await run(`UPDATE drivers SET status = 'available' WHERE id = ?`, [trip.driver_id]);
  await syncDriverAvailability();
  res.json(await tripRow(req.params.id));
});

app.post('/api/trips/:id/contact-rider', authenticateToken, async (req, res) => {
  const trip = await tripRow(req.params.id);
  if (!trip) return res.status(404).json({ error: 'Trip not found' });
  res.json({ dial_target: trip.patient_phone || null });
});

app.get('/api/facilities', authenticateToken, async (_req, res) => {
  res.json([
    { id: 'fac-001', name: 'Sunrise Medical Center' },
    { id: 'fac-002', name: 'Memorial Hospital' },
  ]);
});

app.get('/api/provider/dashboard', authenticateToken, async (_req, res) => {
  const trips = await all(
    `SELECT t.*, p.first_name || ' ' || p.last_name AS patient_name,
      t.pickup_address AS pickup, COALESCE(t.dropoff, t.destination) AS dropoff
     FROM trips t LEFT JOIN patients p ON t.patient_id = p.id
     ORDER BY t.created_at DESC LIMIT 50`
  );
  res.json({ trips });
});

app.post('/api/provider/bulk-schedule', authenticateToken, async (req, res) => {
  const { trips = [] } = req.body || {};
  const created = [];
  for (const row of trips) {
    if (!row.pickup || !row.dropoff) continue;
    const id = 'TRP-' + Math.floor(1000 + Math.random() * 9000);
    const fare = 18 + 5 * 2.75;
    let patientId = null;
    if (row.patient_name) {
      patientId = 'pat-' + randomUUID().slice(0, 8);
      await run(`INSERT INTO patients (id, first_name, last_name, phone) VALUES (?, ?, '', ?)`, [patientId, row.patient_name, row.phone || null]);
    }
    await run(
      `INSERT INTO trips (id, patient_id, pickup_address, destination, dropoff, trip_type, status, estimated_fare)
       VALUES (?, ?, ?, ?, ?, ?, 'pending', ?)`,
      [id, patientId, row.pickup, row.dropoff, row.dropoff, row.type || 'medical', fare]
    );
    created.push(await tripRow(id));
  }
  res.json({ trips: created });
});

app.post('/api/rider/book', authenticateToken, async (req, res) => {
  const { name, phone, pickup, dropoff, notes, auto_dispatch } = req.body || {};
  if (!pickup || !dropoff) return res.status(400).json({ error: 'pickup and dropoff required' });
  const id = 'TRP-' + Math.floor(1000 + Math.random() * 9000);
  const fare = 18 + 5 * 2.75;
  const patientId = 'pat-' + randomUUID().slice(0, 8);
  await run(`INSERT INTO patients (id, first_name, last_name, phone) VALUES (?, ?, '', ?)`, [patientId, name || 'Rider', phone || null]);
  await run(
    `INSERT INTO trips (id, patient_id, pickup_address, destination, dropoff, trip_type, special_requirements, status, estimated_fare)
     VALUES (?, ?, ?, ?, ?, 'medical', ?, 'pending', ?)`,
    [id, patientId, pickup, dropoff, dropoff, notes || null, fare]
  );
  let dispatch = null;
  if (auto_dispatch) {
    const driver = await get(
      `SELECT d.* FROM drivers d
       WHERE d.is_active = 1 AND d.status <> 'offline'
         AND NOT EXISTS (
           SELECT 1 FROM trips t
           WHERE t.driver_id = d.id
             AND t.status NOT IN ('completed','cancelled','no_show','pending')
         )
       ORDER BY d.trips_today ASC LIMIT 1`
    );
    if (driver) {
      await run(`UPDATE trips SET driver_id = ?, status = 'assigned' WHERE id = ?`, [driver.id, id]);
      await run(`UPDATE drivers SET status = 'busy' WHERE id = ?`, [driver.id]);
      const driverName = await get(
        `SELECT COALESCE(u.first_name || ' ' || u.last_name, u.email) AS name
         FROM drivers d LEFT JOIN users u ON d.user_id = u.id WHERE d.id = ?`,
        [driver.id]
      );
      dispatch = { driver_id: driver.id, driver_name: driverName && driverName.name };
    }
    await syncDriverAvailability();
  }
  res.json({ trip: await tripRow(id), dispatch });
});

app.get('/api/rider/track/:id', authenticateToken, async (req, res) => {
  const trip = await tripRow(req.params.id);
  if (!trip) return res.status(404).json({ error: 'Trip not found' });
  let driver_lat = null;
  let driver_lng = null;
  if (trip.driver_id) {
    const d = await get('SELECT lat, lng FROM drivers WHERE id = ?', [trip.driver_id]);
    if (d) {
      driver_lat = d.lat;
      driver_lng = d.lng;
    }
  }
  res.json({ trip: { ...trip, driver_lat, driver_lng } });
});

app.post('/api/rider/pay/:id', authenticateToken, async (req, res) => {
  const trip = await get('SELECT * FROM trips WHERE id = ?', [req.params.id]);
  if (!trip) return res.status(404).json({ error: 'Trip not found' });
  const amount = trip.actual_fare || trip.estimated_fare || 0;
  const payId = 'pay-' + randomUUID().slice(0, 8);
  await run(
    `INSERT INTO payments (id, trip_id, amount, status, payment_method) VALUES (?, ?, ?, 'completed', 'card')`,
    [payId, trip.id, amount]
  );
  res.json({ ok: true, payment_id: payId });
});

app.get('*', (req, res, next) => {
  if (req.path.startsWith('/api/')) return next();
  if (/\.(js|css|map|png|jpg|jpeg|gif|svg|ico|json|woff2?|webmanifest)$/i.test(req.path)) return next();
  const file = path.join(__dirname, 'public', req.path === '/' ? 'index.html' : req.path);
  if (fs.existsSync(file) && fs.statSync(file).isFile()) return res.sendFile(file);
  return res.sendFile(path.join(__dirname, 'public', 'index.html'));
});

initDb()
  .then(async () => {
    await syncDriverAvailability();
    app.listen(PORT, () => {
      console.log(`Amicor Nova STABLE running on http://localhost:${PORT}`);
      console.log(`Health: http://localhost:${PORT}/api/health`);
      console.log(`Database: SQLite at ${dbPath}`);
    });
  })
  .catch((err) => {
    console.error('Failed to initialize SQLite:', err);
    process.exit(1);
  });
