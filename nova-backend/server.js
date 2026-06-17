/**
 * Amicor Nova — Health Transportation Dispatch API
 * Express + PostgreSQL + Socket.IO on port 8011
 */

require('dotenv').config();

const http = require('http');
const path = require('path');
const express = require('express');
const cors = require('cors');
const helmet = require('helmet');
const morgan = require('morgan');
const rateLimit = require('express-rate-limit');
const bcrypt = require('bcryptjs');
const jwt = require('jsonwebtoken');
const { Pool } = require('pg');
const { Server } = require('socket.io');
const Stripe = require('stripe');
const { registerPlatformRoutes } = require('./lib/platform-routes');
const notify = require('./lib/notifications');
const { syncDriverAvailability, getOpsReadiness, driverHasActiveTrip, freeFleetCapacity } = require('./lib/ops-sync');

const PORT = Number(process.env.PORT || 8011);
const JWT_SECRET = process.env.JWT_SECRET || 'amicor-nova-secret-2026';
const DATABASE_URL = process.env.DATABASE_URL;
const STRIPE_KEY = process.env.STRIPE_SECRET_KEY || '';
const ROLES = ['supervisor', 'dispatcher', 'driver', 'compliance', 'admin', 'rider', 'provider'];

if (!DATABASE_URL) {
  console.error('DATABASE_URL is required. Copy .env.example to .env and configure PostgreSQL.');
  process.exit(1);
}

const pool = new Pool({
  connectionString: DATABASE_URL,
  max: Number(process.env.DB_POOL_SIZE || 10),
  idleTimeoutMillis: 30000,
});

const stripe = STRIPE_KEY && !STRIPE_KEY.includes('placeholder')
  ? new Stripe(STRIPE_KEY)
  : null;

const app = express();
const server = http.createServer(app);
const io = new Server(server, {
  cors: { origin: '*', methods: ['GET', 'POST', 'PUT', 'PATCH'] },
});

app.use(helmet({ contentSecurityPolicy: false }));
app.use(cors({ origin: true, credentials: true }));
app.use(morgan('dev'));
app.use(express.json({ limit: '1mb' }));
app.use(
  rateLimit({
    windowMs: 60 * 1000,
    max: Number(process.env.RATE_LIMIT || 200),
    standardHeaders: true,
    legacyHeaders: false,
  })
);

app.use(express.static(path.join(__dirname, 'public'), {
  setHeaders(res, filePath) {
    if (/\.(js|css|html)$/i.test(filePath)) {
      res.setHeader('Cache-Control', 'no-cache, no-store, must-revalidate');
    }
  },
}));

function emitEvent(event, payload) {
  io.emit(event, payload);
  // GPS ticks should not trigger full-board UI refresh storms.
  if (event !== 'driver:location') {
    io.emit('ops:update', { event, payload, ts: new Date().toISOString() });
  }
}

async function audit(userId, action, entityType, entityId, details) {
  try {
    await pool.query(
      `INSERT INTO audit_log (user_id, action, entity_type, entity_id, details)
       VALUES ($1, $2, $3, $4, $5)`,
      [userId || null, action, entityType || null, entityId || null, details || {}]
    );
  } catch (_) {}
}

function signToken(user) {
  return jwt.sign(
    { sub: user.id, email: user.email, role: user.role, name: user.name },
    JWT_SECRET,
    { expiresIn: '12h' }
  );
}

function authRequired(req, res, next) {
  const header = req.headers.authorization || '';
  const token = header.startsWith('Bearer ') ? header.slice(7) : null;
  if (!token) return res.status(401).json({ error: 'Authentication required' });
  try {
    req.user = jwt.verify(token, JWT_SECRET);
    return next();
  } catch (_) {
    return res.status(401).json({ error: 'Invalid or expired token' });
  }
}

function requireRoles(...roles) {
  return (req, res, next) => {
    if (!req.user || !roles.includes(req.user.role)) {
      return res.status(403).json({ error: 'Insufficient permissions' });
    }
    return next();
  };
}

function calcFare(distanceMiles, tripType) {
  const base = 18;
  const perMile = tripType === 'dialysis' ? 3.5 : 2.75;
  return Math.round((base + (Number(distanceMiles) || 5) * perMile) * 100) / 100;
}

// ── Health ────────────────────────────────────────────────────────────────────
app.get('/api/health', async (_req, res) => {
  try {
    await pool.query('SELECT 1');
    res.json({
      ok: true,
      service: 'amicor-nova-backend',
      port: PORT,
      database: 'connected',
      stripe: stripe ? 'enabled' : 'simulated',
      ts: new Date().toISOString(),
    });
  } catch (err) {
    res.status(503).json({ ok: false, error: err.message });
  }
});

app.get('/api/ops/readiness', async (_req, res) => {
  try {
    await syncDriverAvailability(pool);
    const readiness = await getOpsReadiness(pool);
    res.json(readiness);
  } catch (err) {
    res.status(503).json({ ok: false, error: err.message });
  }
});

app.post('/api/ops/sync-drivers', authRequired, requireRoles('dispatcher', 'admin', 'supervisor'), async (_req, res) => {
  try {
    await syncDriverAvailability(pool);
    const readiness = await getOpsReadiness(pool);
    emitEvent('ops:update', readiness);
    res.json(readiness);
  } catch (err) {
    res.status(500).json({ error: err.message });
  }
});

app.post('/api/ops/free-capacity', authRequired, requireRoles('dispatcher', 'admin', 'supervisor'), async (_req, res) => {
  try {
    const freed = await freeFleetCapacity(pool);
    const readiness = await getOpsReadiness(pool);
    emitEvent('ops:update', readiness);
    res.json({ ...readiness, ...freed });
  } catch (err) {
    res.status(500).json({ error: err.message });
  }
});

// ── Auth ──────────────────────────────────────────────────────────────────────
app.post('/api/auth/register', async (req, res) => {
  try {
    const { email, password, name, role } = req.body || {};
    if (!email || !password || !name) {
      return res.status(400).json({ error: 'email, password, and name are required' });
    }
    const normalizedRole = ROLES.includes(role) ? role : 'rider';
    const hash = await bcrypt.hash(String(password), 10);
    const result = await pool.query(
      `INSERT INTO users (email, password, name, role) VALUES ($1, $2, $3, $4)
       RETURNING id, email, name, role, created_at`,
      [String(email).toLowerCase().trim(), hash, String(name).trim(), normalizedRole]
    );
    const user = result.rows[0];
    const token = signToken(user);
    await audit(user.id, 'user_registered', 'user', user.id, { email: user.email });
    res.status(201).json({ token, user });
  } catch (err) {
    if (err.code === '23505') return res.status(409).json({ error: 'Email already registered' });
    res.status(500).json({ error: err.message });
  }
});

app.post('/api/auth/login', async (req, res) => {
  try {
    const { email, password } = req.body || {};
    if (!email || !password) {
      return res.status(400).json({ error: 'email and password are required' });
    }
    const result = await pool.query(
      `SELECT id, email, password, name, role, created_at FROM users WHERE email = $1`,
      [String(email).toLowerCase().trim()]
    );
    const user = result.rows[0];
    if (!user) return res.status(401).json({ error: 'Invalid credentials' });
    const ok = await bcrypt.compare(String(password), user.password);
    if (!ok) return res.status(401).json({ error: 'Invalid credentials' });
    delete user.password;
    const token = signToken(user);
    await audit(user.id, 'user_login', 'user', user.id, {});
    res.json({ token, user });
  } catch (err) {
    res.status(500).json({ error: err.message });
  }
});

app.get('/api/auth/me', authRequired, async (req, res) => {
  const result = await pool.query(
    `SELECT id, email, name, role, created_at FROM users WHERE id = $1`,
    [req.user.sub]
  );
  if (!result.rows[0]) return res.status(404).json({ error: 'User not found' });
  res.json(result.rows[0]);
});

// ── Trips ─────────────────────────────────────────────────────────────────────
app.get('/api/trips', authRequired, async (_req, res) => {
  try {
    const result = await pool.query(
      `SELECT t.*,
              p.name AS patient_name, p.phone AS patient_phone,
              d.name AS driver_name, d.phone AS driver_phone, d.status AS driver_status
       FROM trips t
       LEFT JOIN patients p ON p.id = t.patient_id
       LEFT JOIN drivers d ON d.id = t.driver_id
       ORDER BY t.created_at DESC
       LIMIT 500`
    );
    res.json(result.rows);
  } catch (err) {
    res.status(500).json({ error: err.message });
  }
});

app.post('/api/trips', authRequired, requireRoles('dispatcher', 'admin', 'supervisor', 'rider', 'provider'), async (req, res) => {
  try {
    const { patient_id, pickup, dropoff, type, priority, distance, notes } = req.body || {};
    if (!pickup || !dropoff) return res.status(400).json({ error: 'pickup and dropoff are required' });
    const fare = calcFare(distance, type);
    const result = await pool.query(
      `INSERT INTO trips (patient_id, pickup, dropoff, type, priority, estimated_fare, distance, status, notes)
       VALUES ($1, $2, $3, $4, $5, $6, $7, 'pending', $8)
       RETURNING *`,
      [
        patient_id || null,
        pickup,
        dropoff,
        type || 'medical',
        priority || 'standard',
        fare,
        distance || 5,
        notes || null,
      ]
    );
    const trip = result.rows[0];
    await audit(req.user.sub, 'trip_created', 'trip', trip.id, { pickup, dropoff });
    emitEvent('trip:created', trip);
    res.status(201).json(trip);
  } catch (err) {
    res.status(500).json({ error: err.message });
  }
});

app.put('/api/trips/:id/assign', authRequired, requireRoles('dispatcher', 'admin', 'supervisor'), async (req, res) => {
  try {
    const { driver_id } = req.body || {};
    if (!driver_id) return res.status(400).json({ error: 'driver_id is required' });
    if (await driverHasActiveTrip(pool, driver_id)) {
      return res.status(409).json({ error: 'Driver already has an active trip' });
    }
    const result = await pool.query(
      `UPDATE trips SET driver_id = $1, status = 'assigned', accepted_at = NOW()
       WHERE id = $2 RETURNING *`,
      [driver_id, req.params.id]
    );
    if (!result.rows[0]) return res.status(404).json({ error: 'Trip not found' });
    await pool.query(`UPDATE drivers SET status = 'busy' WHERE id = $1`, [driver_id]);
    const trip = result.rows[0];
    await audit(req.user.sub, 'trip_assigned', 'trip', trip.id, { driver_id });
    emitEvent('trip:assigned', trip);
    res.json(trip);
  } catch (err) {
    res.status(500).json({ error: err.message });
  }
});

async function updateTripStatus(tripId, status, extras, userId) {
  const allowed = [
    'pending', 'assigned', 'driver_en_route', 'arrived', 'rider_onboard',
    'in_progress', 'completed', 'cancelled', 'no_show',
  ];
  if (!allowed.includes(status)) {
    const err = new Error('Invalid status');
    err.status = 400;
    throw err;
  }

  const tripBefore = await pool.query(`SELECT * FROM trips WHERE id = $1`, [tripId]);
  if (!tripBefore.rows[0]) {
    const err = new Error('Trip not found');
    err.status = 404;
    throw err;
  }
  const existing = tripBefore.rows[0];

  let actualFare = existing.actual_fare;
  if (status === 'completed') {
    actualFare = calcFare(extras.distance || existing.distance, extras.type || existing.type);
  }

  const result = await pool.query(
    `UPDATE trips SET
       status = $1,
       accepted_at = CASE WHEN $1 = 'driver_en_route' THEN COALESCE(accepted_at, NOW()) ELSE accepted_at END,
       arrived_at = CASE WHEN $1 = 'arrived' THEN COALESCE(arrived_at, NOW()) ELSE arrived_at END,
       started_at = CASE WHEN $1 IN ('in_progress','rider_onboard') THEN COALESCE(started_at, NOW()) ELSE started_at END,
       completed_at = CASE WHEN $1 = 'completed' THEN NOW() ELSE completed_at END,
       actual_fare = CASE WHEN $1 = 'completed' THEN $2 ELSE actual_fare END
     WHERE id = $3 RETURNING *`,
    [status, actualFare, tripId]
  );
  const trip = result.rows[0];

  if (status === 'completed' && trip.driver_id) {
    await pool.query(
      `UPDATE drivers SET trips_today = trips_today + 1,
       earnings_today = earnings_today + COALESCE($1, 0),
       status = 'available'
       WHERE id = $2`,
      [trip.actual_fare, trip.driver_id]
    );
  }
  if ((status === 'no_show' || status === 'cancelled') && trip.driver_id) {
    await pool.query(`UPDATE drivers SET status = 'available' WHERE id = $1`, [trip.driver_id]);
  }

  await audit(userId, 'trip_status_updated', 'trip', trip.id, { status });
  emitEvent('trip:updated', trip);
  return trip;
}

app.put('/api/trips/:id/status', authRequired, async (req, res) => {
  try {
    const trip = await updateTripStatus(req.params.id, req.body.status, req.body || {}, req.user.sub);
    res.json(trip);
  } catch (err) {
    res.status(err.status || 500).json({ error: err.message });
  }
});

app.put('/api/trips/:id/complete', authRequired, requireRoles('driver', 'dispatcher', 'admin'), async (req, res) => {
  try {
    const trip = await updateTripStatus(req.params.id, 'completed', req.body || {}, req.user.sub);
    res.json(trip);
  } catch (err) {
    res.status(err.status || 500).json({ error: err.message });
  }
});

app.post('/api/trips/:id/accept', authRequired, requireRoles('driver', 'dispatcher'), async (req, res) => {
  try {
    const trip = await updateTripStatus(req.params.id, 'driver_en_route', {}, req.user.sub);
    res.json(trip);
  } catch (err) {
    res.status(err.status || 500).json({ error: err.message });
  }
});

app.post('/api/trips/:id/no-show', authRequired, requireRoles('driver', 'dispatcher'), async (req, res) => {
  try {
    const trip = await updateTripStatus(req.params.id, 'no_show', {}, req.user.sub);
    res.json(trip);
  } catch (err) {
    res.status(err.status || 500).json({ error: err.message });
  }
});

app.post('/api/trips/:id/contact-rider', authRequired, requireRoles('driver', 'dispatcher'), async (req, res) => {
  try {
    const result = await pool.query(
      `SELECT t.id, p.phone, p.name FROM trips t
       LEFT JOIN patients p ON p.id = t.patient_id WHERE t.id = $1`,
      [req.params.id]
    );
    const row = result.rows[0];
    if (!row) return res.status(404).json({ error: 'Trip not found' });
    await audit(req.user.sub, 'rider_contacted', 'trip', row.id, { phone: row.phone });
    if (row.phone) {
      await notify.sendSms(pool, {
        to: row.phone,
        tripId: row.id,
        message: `Amicor Nova: Your driver is en route. Need help? Reply to this message.`,
      });
    }
    res.json({ ok: true, dial_target: row.phone, message: `Contact ${row.name || 'rider'} at ${row.phone || 'N/A'}` });
  } catch (err) {
    res.status(500).json({ error: err.message });
  }
});

// ── Drivers ───────────────────────────────────────────────────────────────────
app.get('/api/drivers', authRequired, async (_req, res) => {
  try {
    const result = await pool.query(`SELECT * FROM drivers ORDER BY name ASC`);
    res.json(result.rows);
  } catch (err) {
    res.status(500).json({ error: err.message });
  }
});

app.post('/api/drivers', authRequired, requireRoles('admin', 'dispatcher', 'supervisor'), async (req, res) => {
  try {
    const { name, phone, license, vehicle, insurance_expiry } = req.body || {};
    if (!name) return res.status(400).json({ error: 'name is required' });
    const result = await pool.query(
      `INSERT INTO drivers (name, phone, license, vehicle, insurance_expiry)
       VALUES ($1, $2, $3, $4, $5) RETURNING *`,
      [name, phone || null, license || null, vehicle || null, insurance_expiry || null]
    );
    emitEvent('driver:created', result.rows[0]);
    res.status(201).json(result.rows[0]);
  } catch (err) {
    res.status(500).json({ error: err.message });
  }
});

app.patch('/api/drivers/:id/location', authRequired, requireRoles('driver', 'dispatcher'), async (req, res) => {
  try {
    const { lat, lng } = req.body || {};
    const result = await pool.query(
      `UPDATE drivers SET lat = $1, lng = $2 WHERE id = $3 RETURNING *`,
      [lat, lng, req.params.id]
    );
    if (!result.rows[0]) return res.status(404).json({ error: 'Driver not found' });
    emitEvent('driver:location', result.rows[0]);
    res.json(result.rows[0]);
  } catch (err) {
    res.status(500).json({ error: err.message });
  }
});

// ── Patients ──────────────────────────────────────────────────────────────────
app.get('/api/patients', authRequired, async (_req, res) => {
  try {
    const result = await pool.query(
      `SELECT p.*, f.name AS facility_name FROM patients p
       LEFT JOIN facilities f ON f.id = p.facility_id
       ORDER BY p.name ASC`
    );
    res.json(result.rows);
  } catch (err) {
    res.status(500).json({ error: err.message });
  }
});

app.post('/api/patients', authRequired, requireRoles('dispatcher', 'admin', 'provider', 'rider'), async (req, res) => {
  try {
    const { name, facility_id, transport_type, address, insurance, phone } = req.body || {};
    if (!name) return res.status(400).json({ error: 'name is required' });
    const result = await pool.query(
      `INSERT INTO patients (name, facility_id, transport_type, address, insurance, phone)
       VALUES ($1, $2, $3, $4, $5, $6) RETURNING *`,
      [name, facility_id || null, transport_type || 'medical', address || null, insurance || null, phone || null]
    );
    res.status(201).json(result.rows[0]);
  } catch (err) {
    res.status(500).json({ error: err.message });
  }
});

// ── Facilities ────────────────────────────────────────────────────────────────
app.get('/api/facilities', authRequired, async (_req, res) => {
  try {
    const result = await pool.query(`SELECT * FROM facilities ORDER BY name ASC`);
    res.json(result.rows);
  } catch (err) {
    res.status(500).json({ error: err.message });
  }
});

// ── Revenue ───────────────────────────────────────────────────────────────────
app.get('/api/revenue', authRequired, requireRoles('admin', 'dispatcher', 'supervisor', 'compliance'), async (_req, res) => {
  try {
    const summary = await pool.query(
      `SELECT
         COUNT(*) FILTER (WHERE status = 'completed')::int AS completed_trips,
         COUNT(*) FILTER (WHERE status IN ('pending','assigned','driver_en_route','in_progress'))::int AS active_trips,
         COALESCE(SUM(actual_fare) FILTER (WHERE status = 'completed'), 0) AS revenue_total,
         COALESCE(SUM(estimated_fare) FILTER (WHERE status != 'completed'), 0) AS pipeline_value
       FROM trips`
    );
    const payments = await pool.query(
      `SELECT COALESCE(SUM(amount), 0) AS payments_total, COUNT(*)::int AS payment_count
       FROM payments WHERE status = 'succeeded'`
    );
    res.json({
      ...summary.rows[0],
      payments_total: payments.rows[0].payments_total,
      payment_count: payments.rows[0].payment_count,
      window: 'all_time',
    });
  } catch (err) {
    res.status(500).json({ error: err.message });
  }
});

// ── Stripe ────────────────────────────────────────────────────────────────────
app.post('/api/create-payment-intent', authRequired, async (req, res) => {
  try {
    const { trip_id, amount } = req.body || {};
    if (!trip_id) return res.status(400).json({ error: 'trip_id is required' });

    const tripResult = await pool.query(`SELECT * FROM trips WHERE id = $1`, [trip_id]);
    const trip = tripResult.rows[0];
    if (!trip) return res.status(404).json({ error: 'Trip not found' });

    const chargeAmount = Number(amount) || Number(trip.actual_fare) || Number(trip.estimated_fare) || 25;
    const amountCents = Math.round(chargeAmount * 100);

    let stripePaymentId = `sim_${Date.now()}`;
    let status = 'requires_capture';

    if (stripe) {
      const intent = await stripe.paymentIntents.create({
        amount: amountCents,
        currency: 'usd',
        metadata: { trip_id },
        capture_method: 'manual',
      });
      stripePaymentId = intent.id;
      status = intent.status;
    }

    const payment = await pool.query(
      `INSERT INTO payments (stripe_payment_id, amount, status, trip_id)
       VALUES ($1, $2, $3, $4) RETURNING *`,
      [stripePaymentId, chargeAmount, status, trip_id]
    );

    await audit(req.user.sub, 'payment_intent_created', 'payment', payment.rows[0].id, { trip_id });
    emitEvent('payment:created', payment.rows[0]);
    res.json({
      payment: payment.rows[0],
      client_secret: stripe ? undefined : 'simulated',
      stripe_enabled: Boolean(stripe),
    });
  } catch (err) {
    res.status(500).json({ error: err.message });
  }
});

// ── Alerts ────────────────────────────────────────────────────────────────────
app.get('/api/alerts', authRequired, async (_req, res) => {
  const result = await pool.query(
    `SELECT * FROM alerts ORDER BY created_at DESC LIMIT 100`
  );
  res.json(result.rows);
});

registerPlatformRoutes({
  app,
  pool,
  authRequired,
  requireRoles,
  audit,
  emitEvent,
  calcFare,
  updateTripStatus,
});

// ── Portal pages ──────────────────────────────────────────────────────────────
const pages = ['driver', 'rider', 'provider', 'dispatcher'];
pages.forEach((page) => {
  app.get(`/${page}`, (_req, res) => {
    res.sendFile(path.join(__dirname, 'public', `${page}.html`));
  });
});

// ── SPA fallback ──────────────────────────────────────────────────────────────
app.get('*', (req, res, next) => {
  if (req.path.startsWith('/api/') || req.path.startsWith('/socket.io')) return next();
  if (/\.(js|css|map|png|jpg|jpeg|gif|svg|ico|json|woff2?|webmanifest)$/i.test(req.path)) return next();
  res.sendFile(path.join(__dirname, 'public', 'index.html'));
});

io.on('connection', (socket) => {
  socket.emit('connected', { ok: true, ts: new Date().toISOString() });
});

server.listen(PORT, async () => {
  console.log(`Amicor Nova API running on http://localhost:${PORT}`);
  console.log(`Health: http://localhost:${PORT}/api/health`);
  console.log(`Ops readiness: http://localhost:${PORT}/api/ops/readiness`);
  try {
    await syncDriverAvailability(pool);
    console.log('Driver availability synced for live operations.');
  } catch (err) {
    console.warn('Driver sync skipped:', err.message);
  }
});

process.on('SIGINT', async () => {
  await pool.end();
  process.exit(0);
});
