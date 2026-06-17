/**
 * Dispatch intelligence — nearest available driver selection.
 */

function toRad(value) {
  return (Number(value) * Math.PI) / 180;
}

function haversineMiles(lat1, lng1, lat2, lng2) {
  const R = 3958.8;
  const dLat = toRad(lat2 - lat1);
  const dLng = toRad(lng2 - lng1);
  const a =
    Math.sin(dLat / 2) ** 2 +
    Math.cos(toRad(lat1)) * Math.cos(toRad(lat2)) * Math.sin(dLng / 2) ** 2;
  return R * 2 * Math.atan2(Math.sqrt(a), Math.sqrt(1 - a));
}

function scoreDriver(driver, pickupLat, pickupLng) {
  const lat = Number(driver.lat);
  const lng = Number(driver.lng);
  if (!Number.isFinite(lat) || !Number.isFinite(lng)) {
    return { driver, score: 9999, distance_miles: null };
  }
  const distance = haversineMiles(lat, lng, pickupLat, pickupLng);
  const ratingBoost = (5 - Number(driver.rating || 4.5)) * 0.5;
  const tripsPenalty = Number(driver.trips_today || 0) * 0.1;
  return {
    driver,
    score: distance + ratingBoost + tripsPenalty,
    distance_miles: Math.round(distance * 100) / 100,
  };
}

function pickNearestDriver(drivers, pickupLat, pickupLng) {
  const available = drivers.filter((d) => d.status === 'available');
  if (available.length === 0) return null;

  const ranked = available
    .map((d) => scoreDriver(d, pickupLat, pickupLng))
    .sort((a, b) => a.score - b.score);

  return ranked[0] || null;
}

/** Default NYC metro coordinates when geocoding unavailable */
const DEFAULT_PICKUP = { lat: 40.7128, lng: -74.006 };

function resolvePickupCoords(trip) {
  const lat = Number(trip.pickup_lat);
  const lng = Number(trip.pickup_lng);
  if (Number.isFinite(lat) && Number.isFinite(lng)) return { lat, lng };
  return DEFAULT_PICKUP;
}

module.exports = {
  haversineMiles,
  pickNearestDriver,
  resolvePickupCoords,
};
