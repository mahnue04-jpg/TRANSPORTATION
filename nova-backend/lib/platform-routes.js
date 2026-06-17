const notify = require('./notifications');
const dispatch = require('./dispatch');
const { syncDriverAvailability, getAvailableDrivers, driverHasActiveTrip } = require('./ops-sync');

function registerPlatformRoutes(deps) {
  const {
    app,
    pool,
    authRequired,
    requireRoles,
    audit,
    emitEvent,
    calcFare,
    updateTripStatus,
  } = deps;

  async function assignTripToDriver(tripId, driverId, userId, reason) {
    if (await driverHasActiveTrip(pool, driverId)) {
      const err = new Error('Driver already has an active trip');
      err.status = 409;
      throw err;
    }
    const result = await pool.query(
      `UPDATE trips SET driver_id = $1, status = 'assigned', accepted_at = NOW()
       WHERE id = $2 RETURNING *`,
      [driverId, tripId]
    );
    if (!result.rows[0]) return null;
    await pool.query(`UPDATE drivers SET status = 'busy' WHERE id = $1`, [driverId]);
    const trip = result.rows[0];
    await audit(userId, 'trip_assigned', 'trip', trip.id, { driver_id: driverId, reason });
    emitEvent('trip:assigned', trip);

    const patient = await pool.query(
      `SELECT p.phone, p.name FROM trips t LEFT JOIN patients p ON p.id = t.patient_id WHERE t.id = $1`,
      [tripId]
    );
    const row = patient.rows[0];
    if (row?.phone) {
      await notify.sendSms(pool, {
        to: row.phone,
        tripId,
        message: `Amicor Nova: Your driver is assigned for transport to ${trip.dropoff}. Track: ${process.env.FRONTEND_URL || 'http://localhost:8011'}/rider?trip=${tripId}`,
      });
    }
    return trip;
  }

  async function autoAssignTrip(tripId, userId) {
    const tripRes = await pool.query(`SELECT * FROM trips WHERE id = $1`, [tripId]);
    const trip = tripRes.rows[0];
    if (!trip) {
      const err = new Error('Trip not found');
      err.status = 404;
      throw err;
    }
    if (trip.driver_id) return { trip, already_assigned: true };

    const drivers = await getAvailableDrivers(pool);
    const coords = dispatch.resolvePickupCoords(trip);
    const pick = dispatch.pickNearestDriver(drivers, coords.lat, coords.lng);
    if (!pick) {
      const err = new Error('No available drivers — all drivers are on active trips');
      err.status = 409;
      throw err;
    }

    const assigned = await assignTripToDriver(tripId, pick.driver.id, userId, 'auto_dispatch');
    return {
      trip: assigned,
      dispatch: {
        driver_id: pick.driver.id,
        driver_name: pick.driver.name,
        distance_miles: pick.distance_miles,
        algorithm: 'nearest_available_v1',
      },
    };
  }

  // ── Driver mobile ───────────────────────────────────────────────────────────
  app.get('/api/driver/me', authRequired, requireRoles('driver', 'dispatcher', 'admin'), async (req, res) => {
    try {
      let result = await pool.query(
        `SELECT d.* FROM drivers d
         JOIN users u ON u.id = d.user_id
         WHERE u.id = $1 LIMIT 1`,
        [req.user.sub]
      );
      if (!result.rows[0]) {
        result = await pool.query(
          `SELECT * FROM drivers WHERE status != 'offline' ORDER BY created_at ASC LIMIT 1`
        );
      }
      if (!result.rows[0]) return res.status(404).json({ error: 'No driver profile linked' });

      const active = await pool.query(
        `SELECT t.*, p.name AS patient_name, p.phone AS patient_phone
         FROM trips t
         LEFT JOIN patients p ON p.id = t.patient_id
         WHERE t.driver_id = $1 AND t.status NOT IN ('completed','cancelled','no_show')
         ORDER BY t.created_at DESC LIMIT 1`,
        [result.rows[0].id]
      );
      res.json({ driver: result.rows[0], active_trip: active.rows[0] || null });
    } catch (err) {
      res.status(500).json({ error: err.message });
    }
  });

  app.get('/api/driver/earnings', authRequired, requireRoles('driver', 'admin'), async (req, res) => {
    try {
      const driverRes = await pool.query(
        `SELECT d.* FROM drivers d LEFT JOIN users u ON u.id = d.user_id WHERE u.id = $1 OR d.id = $2 LIMIT 1`,
        [req.user.sub, req.query.driver_id || null]
      );
      const driver = driverRes.rows[0];
      if (!driver) return res.status(404).json({ error: 'Driver not found' });

      const totals = await pool.query(
        `SELECT COUNT(*)::int AS completed_count,
                COALESCE(SUM(actual_fare), 0) AS lifetime_earnings
         FROM trips WHERE driver_id = $1 AND status = 'completed'`,
        [driver.id]
      );
      res.json({
        driver_id: driver.id,
        earnings_today: driver.earnings_today,
        trips_today: driver.trips_today,
        completed_count: totals.rows[0].completed_count,
        lifetime_earnings: totals.rows[0].lifetime_earnings,
      });
    } catch (err) {
      res.status(500).json({ error: err.message });
    }
  });

  app.post('/api/driver/gps', authRequired, requireRoles('driver'), async (req, res) => {
    try {
      const { lat, lng, trip_id, speed_kph } = req.body || {};
      const driverRes = await pool.query(
        `SELECT d.id FROM drivers d JOIN users u ON u.id = d.user_id WHERE u.id = $1`,
        [req.user.sub]
      );
      let driverId = driverRes.rows[0]?.id;
      if (!driverId) {
        const fallback = await pool.query(`SELECT id FROM drivers ORDER BY created_at ASC LIMIT 1`);
        driverId = fallback.rows[0]?.id;
      }
      if (!driverId) return res.status(404).json({ error: 'Driver profile not found' });

      await pool.query(
        `INSERT INTO driver_locations (driver_id, trip_id, lat, lng, speed_kph) VALUES ($1, $2, $3, $4, $5)`,
        [driverId, trip_id || null, lat, lng, speed_kph || null]
      );
      const updated = await pool.query(
        `UPDATE drivers SET lat = $1, lng = $2 WHERE id = $3 RETURNING *`,
        [lat, lng, driverId]
      );
      emitEvent('driver:location', { ...updated.rows[0], trip_id: trip_id || null });
      res.json(updated.rows[0]);
    } catch (err) {
      res.status(500).json({ error: err.message });
    }
  });

  // ── Rider booking ───────────────────────────────────────────────────────────
  app.post('/api/rider/book', authRequired, requireRoles('rider', 'dispatcher', 'admin'), async (req, res) => {
    try {
      const {
        name, phone, email, pickup, dropoff, type, notes, scheduled_at, auto_dispatch,
      } = req.body || {};
      if (!pickup || !dropoff) return res.status(400).json({ error: 'pickup and dropoff required' });

      let patientId = null;
      if (name) {
        const p = await pool.query(
          `INSERT INTO patients (name, phone, email, transport_type, address)
           VALUES ($1, $2, $3, $4, $5) RETURNING id`,
          [name, phone || null, email || null, type || 'medical', pickup]
        );
        patientId = p.rows[0].id;
      }

      const fare = calcFare(req.body.distance || 5, type);
      const tripRes = await pool.query(
        `INSERT INTO trips (patient_id, pickup, dropoff, type, estimated_fare, distance, status, notes, scheduled_at, pickup_lat, pickup_lng)
         VALUES ($1, $2, $3, $4, $5, $6, 'pending', $7, $8, $9, $10) RETURNING *`,
        [
          patientId,
          pickup,
          dropoff,
          type || 'medical',
          fare,
          req.body.distance || 5,
          notes || null,
          scheduled_at || null,
          req.body.pickup_lat || 40.7128,
          req.body.pickup_lng || -74.006,
        ]
      );
      const trip = tripRes.rows[0];
      emitEvent('trip:created', trip);

      let dispatchResult = null;
      if (auto_dispatch !== false) {
        try {
          dispatchResult = await autoAssignTrip(trip.id, req.user.sub);
        } catch (_) {}
      }

      if (phone) {
        await notify.sendSms(pool, {
          to: phone,
          tripId: trip.id,
          message: `Amicor Nova: Trip booked. Track your ride: ${process.env.FRONTEND_URL || 'http://localhost:8011'}/rider?trip=${trip.id}`,
        });
      }

      res.status(201).json({ trip, dispatch: dispatchResult?.dispatch || null });
    } catch (err) {
      res.status(err.status || 500).json({ error: err.message });
    }
  });

  app.get('/api/rider/track/:tripId', authRequired, async (req, res) => {
    try {
      const tripRes = await pool.query(
        `SELECT t.*, p.name AS patient_name, d.name AS driver_name, d.phone AS driver_phone,
                d.lat AS driver_lat, d.lng AS driver_lng, d.status AS driver_status
         FROM trips t
         LEFT JOIN patients p ON p.id = t.patient_id
         LEFT JOIN drivers d ON d.id = t.driver_id
         WHERE t.id = $1`,
        [req.params.tripId]
      );
      const trip = tripRes.rows[0];
      if (!trip) return res.status(404).json({ error: 'Trip not found' });

      const pings = await pool.query(
        `SELECT lat, lng, recorded_at FROM driver_locations
         WHERE trip_id = $1 OR driver_id = $2
         ORDER BY recorded_at DESC LIMIT 20`,
        [trip.id, trip.driver_id]
      );
      res.json({ trip, location_history: pings.rows });
    } catch (err) {
      res.status(500).json({ error: err.message });
    }
  });

  app.post('/api/rider/pay/:tripId', authRequired, requireRoles('rider', 'admin', 'dispatcher'), async (req, res) => {
    try {
      const tripRes = await pool.query(`SELECT * FROM trips WHERE id = $1`, [req.params.tripId]);
      const trip = tripRes.rows[0];
      if (!trip) return res.status(404).json({ error: 'Trip not found' });
      const amount = Number(trip.actual_fare) || Number(trip.estimated_fare) || 25;
      const payment = await pool.query(
        `INSERT INTO payments (stripe_payment_id, amount, status, trip_id)
         VALUES ($1, $2, 'succeeded', $3) RETURNING *`,
        [`sim_pay_${Date.now()}`, amount, trip.id]
      );
      emitEvent('payment:created', payment.rows[0]);
      res.json({ ok: true, payment: payment.rows[0] });
    } catch (err) {
      res.status(500).json({ error: err.message });
    }
  });

  // ── Provider portal ─────────────────────────────────────────────────────────
  app.get('/api/provider/dashboard', authRequired, requireRoles('provider', 'admin', 'dispatcher'), async (req, res) => {
    try {
      const facilityId = req.query.facility_id;
      const params = [];
      let where = '';
      if (facilityId) {
        where = 'WHERE t.facility_id = $1 OR p.facility_id = $1';
        params.push(facilityId);
      }
      const trips = await pool.query(
        `SELECT t.*, p.name AS patient_name FROM trips t
         LEFT JOIN patients p ON p.id = t.patient_id
         ${where}
         ORDER BY t.created_at DESC LIMIT 100`,
        params
      );
      const bulk = await pool.query(
        `SELECT * FROM bulk_schedules ${facilityId ? 'WHERE facility_id = $1' : ''} ORDER BY created_at DESC LIMIT 20`,
        facilityId ? [facilityId] : []
      );
      res.json({ trips: trips.rows, bulk_schedules: bulk.rows });
    } catch (err) {
      res.status(500).json({ error: err.message });
    }
  });

  app.post('/api/provider/bulk-schedule', authRequired, requireRoles('provider', 'admin', 'dispatcher'), async (req, res) => {
    try {
      const { facility_id, label, trips } = req.body || {};
      if (!Array.isArray(trips) || trips.length === 0) {
        return res.status(400).json({ error: 'trips array required' });
      }

      const bulk = await pool.query(
        `INSERT INTO bulk_schedules (facility_id, created_by, label, trips_json, status)
         VALUES ($1, $2, $3, $4, 'processing') RETURNING *`,
        [facility_id || null, req.user.sub, label || 'Bulk schedule', JSON.stringify(trips)]
      );

      const created = [];
      for (const item of trips) {
        if (!item.pickup || !item.dropoff) continue;
        let patientId = item.patient_id || null;
        if (!patientId && item.patient_name) {
          const p = await pool.query(
            `INSERT INTO patients (name, phone, facility_id, transport_type, address)
             VALUES ($1, $2, $3, $4, $5) RETURNING id`,
            [item.patient_name, item.phone || null, facility_id || null, item.type || 'medical', item.pickup]
          );
          patientId = p.rows[0].id;
        }
        const fare = calcFare(item.distance || 5, item.type);
        const t = await pool.query(
          `INSERT INTO trips (patient_id, facility_id, pickup, dropoff, type, estimated_fare, distance, status, scheduled_at, notes)
           VALUES ($1, $2, $3, $4, $5, $6, $7, 'pending', $8, $9) RETURNING *`,
          [
            patientId,
            facility_id || null,
            item.pickup,
            item.dropoff,
            item.type || 'medical',
            fare,
            item.distance || 5,
            item.scheduled_at || null,
            item.notes || null,
          ]
        );
        created.push(t.rows[0]);
        emitEvent('trip:created', t.rows[0]);
      }

      await pool.query(`UPDATE bulk_schedules SET status = 'completed' WHERE id = $1`, [bulk.rows[0].id]);
      await audit(req.user.sub, 'bulk_schedule_created', 'bulk_schedules', bulk.rows[0].id, { count: created.length });
      res.status(201).json({ bulk: bulk.rows[0], trips: created });
    } catch (err) {
      res.status(500).json({ error: err.message });
    }
  });

  // ── Dispatcher command center ───────────────────────────────────────────────
  app.get('/api/dispatcher/live', authRequired, requireRoles('dispatcher', 'admin', 'supervisor'), async (_req, res) => {
    try {
      await syncDriverAvailability(pool);
      const [drivers, trips, alerts] = await Promise.all([
        pool.query(`
          SELECT d.id, d.name, d.status, d.lat, d.lng, d.vehicle, d.rating, d.trips_today,
            (SELECT COUNT(*)::int FROM trips t
              WHERE t.driver_id = d.id
                AND t.status NOT IN ('completed','cancelled','no_show','pending')) AS active_trip_count
          FROM drivers d ORDER BY d.name ASC
        `),
        pool.query(
          `SELECT t.*, p.name AS patient_name, d.name AS driver_name
           FROM trips t
           LEFT JOIN patients p ON p.id = t.patient_id
           LEFT JOIN drivers d ON d.id = t.driver_id
           WHERE t.status NOT IN ('completed','cancelled','no_show')
           ORDER BY t.created_at DESC`
        ),
        pool.query(`SELECT * FROM alerts WHERE read = false ORDER BY created_at DESC LIMIT 20`),
      ]);
      res.json({
        drivers: drivers.rows,
        trips: trips.rows,
        alerts: alerts.rows,
        ts: new Date().toISOString(),
      });
    } catch (err) {
      res.status(500).json({ error: err.message });
    }
  });

  app.post('/api/dispatch/auto-assign/:tripId', authRequired, requireRoles('dispatcher', 'admin', 'supervisor'), async (req, res) => {
    try {
      const result = await autoAssignTrip(req.params.tripId, req.user.sub);
      res.json(result);
    } catch (err) {
      res.status(err.status || 500).json({ error: err.message });
    }
  });

  app.post('/api/dispatch/auto-assign-pending', authRequired, requireRoles('dispatcher', 'admin'), async (req, res) => {
    try {
      await syncDriverAvailability(pool);
      const pending = await pool.query(
        `SELECT id FROM trips WHERE status = 'pending' AND driver_id IS NULL ORDER BY created_at ASC LIMIT 50`
      );
      const results = [];
      for (const row of pending.rows) {
        try {
          results.push(await autoAssignTrip(row.id, req.user.sub));
        } catch (err) {
          results.push({ trip_id: row.id, error: err.message });
        }
      }
      await syncDriverAvailability(pool);
      res.json({ assigned: results.filter((r) => r.trip).length, results });
    } catch (err) {
      res.status(500).json({ error: err.message });
    }
  });

  // ── Invoices (SendGrid) ───────────────────────────────────────────────────
  app.post('/api/invoices/send/:tripId', authRequired, requireRoles('dispatcher', 'admin', 'compliance'), async (req, res) => {
    try {
      const { email } = req.body || {};
      const tripRes = await pool.query(
        `SELECT t.*, p.name AS patient_name, p.email AS patient_email
         FROM trips t LEFT JOIN patients p ON p.id = t.patient_id WHERE t.id = $1`,
        [req.params.tripId]
      );
      const trip = tripRes.rows[0];
      if (!trip) return res.status(404).json({ error: 'Trip not found' });

      const recipient = email || trip.patient_email || req.body.recipient;
      if (!recipient) return res.status(400).json({ error: 'Recipient email required' });

      const paymentRes = await pool.query(
        `SELECT * FROM payments WHERE trip_id = $1 ORDER BY created_at DESC LIMIT 1`,
        [trip.id]
      );
      const amount = trip.actual_fare || trip.estimated_fare || 0;
      const html = notify.buildInvoiceHtml(trip, { name: trip.patient_name, email: recipient }, paymentRes.rows[0]);
      const sent = await notify.sendEmail(pool, {
        to: recipient,
        subject: `Amicor Nova Invoice — Trip ${trip.id.slice(0, 8)}`,
        html,
        tripId: trip.id,
      });

      const invoice = await pool.query(
        `INSERT INTO invoices (trip_id, patient_id, amount, status, recipient_email, sendgrid_message_id, sent_at)
         VALUES ($1, $2, $3, 'sent', $4, $5, NOW()) RETURNING *`,
        [trip.id, trip.patient_id, amount, recipient, sent.reference]
      );

      res.json({ invoice: invoice.rows[0], delivery: sent });
    } catch (err) {
      res.status(500).json({ error: err.message });
    }
  });

  app.post('/api/notifications/sms', authRequired, requireRoles('dispatcher', 'driver', 'admin'), async (req, res) => {
    try {
      const { to, message, trip_id } = req.body || {};
      const result = await notify.sendSms(pool, { to, message, tripId: trip_id });
      res.json(result);
    } catch (err) {
      res.status(500).json({ error: err.message });
    }
  });
}

module.exports = { registerPlatformRoutes, };
