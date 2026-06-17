/**
 * Keep driver availability aligned with active trip assignments.
 */

const ACTIVE_TRIP_FILTER = `t.status NOT IN ('completed', 'cancelled', 'no_show', 'pending')`;

const AVAILABLE_DRIVER_WHERE = `
  d.status <> 'offline'
  AND NOT EXISTS (
    SELECT 1 FROM trips t
    WHERE t.driver_id = d.id
      AND ${ACTIVE_TRIP_FILTER}
  )
`;

async function syncDriverAvailability(pool) {
  await pool.query(`
    UPDATE drivers d SET status = 'available'
    WHERE ${AVAILABLE_DRIVER_WHERE}
  `);
  await pool.query(`
    UPDATE drivers d SET status = 'busy'
    WHERE d.status <> 'offline'
      AND EXISTS (
        SELECT 1 FROM trips t
        WHERE t.driver_id = d.id
          AND ${ACTIVE_TRIP_FILTER}
      )
  `);
}

async function getAvailableDrivers(pool) {
  const result = await pool.query(`
    SELECT d.*,
      (SELECT COUNT(*)::int FROM trips t
        WHERE t.driver_id = d.id AND ${ACTIVE_TRIP_FILTER}) AS active_trip_count
    FROM drivers d
    WHERE ${AVAILABLE_DRIVER_WHERE}
    ORDER BY d.trips_today ASC, d.name ASC
  `);
  return result.rows;
}

async function driverHasActiveTrip(pool, driverId) {
  const result = await pool.query(
    `SELECT id FROM trips
     WHERE driver_id = $1 AND ${ACTIVE_TRIP_FILTER}
     LIMIT 1`,
    [driverId]
  );
  return Boolean(result.rows[0]);
}

async function freeFleetCapacity(pool) {
  const result = await pool.query(`
    UPDATE trips SET
      status = 'completed',
      completed_at = COALESCE(completed_at, NOW()),
      actual_fare = COALESCE(actual_fare, estimated_fare)
    WHERE status NOT IN ('completed', 'cancelled', 'no_show', 'pending')
    RETURNING id
  `);
  await syncDriverAvailability(pool);
  return { completed_trips: result.rowCount, ts: new Date().toISOString() };
}

async function getOpsReadiness(pool) {
  const [trips, drivers, revenue] = await Promise.all([
    pool.query(`
      SELECT
        COUNT(*) FILTER (WHERE status NOT IN ('completed','cancelled','no_show'))::int AS active_trips,
        COUNT(*) FILTER (WHERE status = 'pending' AND driver_id IS NULL)::int AS pending_dispatch
      FROM trips
    `),
    pool.query(`
      SELECT
        COUNT(*)::int AS total,
        COUNT(*) FILTER (WHERE ${AVAILABLE_DRIVER_WHERE})::int AS available
      FROM drivers d
    `),
    pool.query(`
      SELECT COALESCE(SUM(actual_fare) FILTER (WHERE status = 'completed'), 0) AS revenue_total
      FROM trips
    `),
  ]);

  return {
    ok: true,
    active_trips: trips.rows[0].active_trips,
    pending_dispatch: trips.rows[0].pending_dispatch,
    drivers_total: drivers.rows[0].total,
    drivers_available: drivers.rows[0].available,
    revenue_total: Number(revenue.rows[0].revenue_total || 0),
    ts: new Date().toISOString(),
  };
}

module.exports = {
  syncDriverAvailability,
  getOpsReadiness,
  getAvailableDrivers,
  driverHasActiveTrip,
  freeFleetCapacity,
  ACTIVE_TRIP_FILTER,
};
