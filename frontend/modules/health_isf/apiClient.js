export async function fetchHealthDashboard() {
  const response = await fetch("/api/health-isf/dashboard");
  if (!response.ok) throw new Error("Failed to load dashboard");
  return response.json();
}

export async function fetchHealthRides() {
  const response = await fetch("/api/health-isf/rides");
  if (!response.ok) throw new Error("Failed to load rides");
  return response.json();
}

export async function fetchHealthDrivers() {
  const response = await fetch("/api/health-isf/drivers");
  if (!response.ok) throw new Error("Failed to load drivers");
  return response.json();
}

export async function fetchHealthProviders() {
  const response = await fetch("/api/health-isf/providers");
  if (!response.ok) throw new Error("Failed to load providers");
  return response.json();
}

export async function createHealthRide(payload) {
  const response = await fetch("/api/health-isf/rides", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload),
  });
  if (!response.ok) throw new Error("Failed to create ride");
  return response.json();
}

export async function updateHealthRideStatus(rideId, status) {
  const response = await fetch(`/api/health-isf/rides/${encodeURIComponent(rideId)}/status`, {
    method: "PATCH",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ status }),
  });
  if (!response.ok) throw new Error("Failed to update ride status");
  return response.json();
}

export async function assignHealthRideDriver(rideId, driverId) {
  const response = await fetch(`/api/health-isf/rides/${encodeURIComponent(rideId)}/assign-driver`, {
    method: "PATCH",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ driver_id: driverId }),
  });
  if (!response.ok) throw new Error("Failed to assign driver");
  return response.json();
}
