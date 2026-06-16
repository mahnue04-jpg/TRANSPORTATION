(function () {
  "use strict";

  var STORAGE_KEY = "amicor_ops_runtime_v1";
  var STATES = [
    "requested",
    "scheduled",
    "assigned",
    "driver_en_route",
    "arrived",
    "rider_onboard",
    "completed",
    "canceled",
    "delayed",
    "no_show"
  ];

  var TRANSITIONS = {
    requested: ["scheduled", "assigned", "canceled", "delayed", "no_show"],
    scheduled: ["assigned", "canceled", "delayed", "no_show"],
    assigned: ["driver_en_route", "canceled", "delayed", "no_show"],
    driver_en_route: ["arrived", "canceled", "delayed", "no_show"],
    arrived: ["rider_onboard", "canceled", "no_show"],
    rider_onboard: ["completed", "delayed", "canceled"],
    delayed: ["driver_en_route", "arrived", "rider_onboard", "completed", "canceled", "no_show"],
    completed: [],
    canceled: [],
    no_show: []
  };

  function nowIso() {
    return new Date().toISOString();
  }

  function minutesSince(isoTs) {
    var ts = Date.parse(String(isoTs || ""));
    if (!Number.isFinite(ts)) return 0;
    return Math.max(0, Math.floor((Date.now() - ts) / 60000));
  }

  function safeState(value, fallback) {
    var state = String(value || "");
    return STATES.indexOf(state) >= 0 ? state : fallback;
  }

  function emit(type, payload) {
    if (window.AmiOperationalEvents && typeof window.AmiOperationalEvents.emit === "function") {
      window.AmiOperationalEvents.emit(type, payload);
    }
  }

  function initialData() {
    var drivers = [
      { id: "DRV-A22", name: "Marcus R.", status: "available", etaMin: 3, vehicle: "Medical Van" },
      { id: "DRV-B11", name: "Elena V.", status: "available", etaMin: 5, vehicle: "Wheelchair Van" },
      { id: "DRV-C44", name: "James T.", status: "busy", etaMin: 8, vehicle: "Sedan" },
      { id: "DRV-D19", name: "Sarah M.", status: "on_break", etaMin: 0, vehicle: "SUV" }
    ];

    var trips = [
      { id: "TRIP-4421", riderId: "RID-101", riderName: "J. Adams", pickup: "12th & Vine", dropoff: "General Hospital", state: "requested", priority: "urgent", requestedAt: nowIso(), assignedDriverId: "", assignedDriverName: "", etaMin: 12, slaTargetMin: 15, routeStatus: "pending" },
      { id: "TRIP-4420", riderId: "RID-102", riderName: "M. Torres", pickup: "Oak Park", dropoff: "Dialysis Clinic", state: "scheduled", priority: "urgent", requestedAt: nowIso(), assignedDriverId: "", assignedDriverName: "", etaMin: 18, slaTargetMin: 20, routeStatus: "scheduled" },
      { id: "TRIP-4419", riderId: "RID-103", riderName: "P. Singh", pickup: "Downtown Hub", dropoff: "Airport T2", state: "assigned", priority: "standard", requestedAt: nowIso(), assignedDriverId: "DRV-A22", assignedDriverName: "Marcus R.", etaMin: 11, slaTargetMin: 20, routeStatus: "assigned" },
      { id: "TRIP-4415", riderId: "RID-108", riderName: "R. Brown", pickup: "West Side", dropoff: "Cancer Center", state: "driver_en_route", priority: "standard", requestedAt: nowIso(), assignedDriverId: "DRV-C44", assignedDriverName: "James T.", etaMin: 8, slaTargetMin: 20, routeStatus: "en_route" },
      { id: "TRIP-4414", riderId: "RID-110", riderName: "T. White", pickup: "North Station", dropoff: "Rehab Center", state: "rider_onboard", priority: "standard", requestedAt: nowIso(), assignedDriverId: "DRV-B11", assignedDriverName: "Elena V.", etaMin: 20, slaTargetMin: 25, routeStatus: "in_progress" }
    ];

    return {
      trips: trips,
      drivers: drivers,
      selectedDriverId: "",
      lastUpdatedAt: nowIso()
    };
  }

  var store = initialData();

  function persist() {
    try {
      localStorage.setItem(STORAGE_KEY, JSON.stringify(store));
    } catch (_) {}
  }

  function hydrate() {
    try {
      var raw = localStorage.getItem(STORAGE_KEY);
      if (!raw) return;
      var parsed = JSON.parse(raw);
      if (!parsed || typeof parsed !== "object") return;
      if (Array.isArray(parsed.trips) && Array.isArray(parsed.drivers)) {
        store = parsed;
      }
    } catch (_) {}
  }

  function touch() {
    store.lastUpdatedAt = nowIso();
    persist();
  }

  function clone(value) {
    return JSON.parse(JSON.stringify(value));
  }

  function getTrips() {
    return clone(store.trips);
  }

  function getTripById(tripId) {
    var id = String(tripId || "");
    for (var i = 0; i < store.trips.length; i += 1) {
      if (String(store.trips[i].id) === id) return store.trips[i];
    }
    return null;
  }

  function getDrivers() {
    return clone(store.drivers);
  }

  function getDriverById(driverId) {
    var id = String(driverId || "");
    for (var i = 0; i < store.drivers.length; i += 1) {
      if (String(store.drivers[i].id) === id) return store.drivers[i];
    }
    return null;
  }

  function transitionTrip(tripId, nextState, meta) {
    var trip = getTripById(tripId);
    var target = safeState(nextState, "requested");
    if (!trip) return { ok: false, error: "trip_not_found" };
    var allowed = TRANSITIONS[safeState(trip.state, "requested")] || [];
    if (allowed.indexOf(target) < 0 && safeState(trip.state, "") !== target) {
      return { ok: false, error: "transition_not_allowed" };
    }

    trip.state = target;
    if (meta && typeof meta === "object") {
      if (meta.routeStatus) trip.routeStatus = String(meta.routeStatus);
      if (meta.etaMin !== undefined) trip.etaMin = Number(meta.etaMin) || trip.etaMin;
      if (meta.assignedDriverId !== undefined) trip.assignedDriverId = String(meta.assignedDriverId || "");
      if (meta.assignedDriverName !== undefined) trip.assignedDriverName = String(meta.assignedDriverName || "");
      if (meta.priority) trip.priority = String(meta.priority);
    }

    touch();
    emit("trip_state_changed", { tripId: trip.id, state: target, meta: meta || {} });
    return { ok: true, trip: clone(trip) };
  }

  function createTrip(input) {
    var data = input || {};
    var tripId = "TRIP-" + String(Date.now()).slice(-5);
    var trip = {
      id: tripId,
      riderId: String(data.riderId || ("RID-" + String(Date.now()).slice(-4))),
      riderName: String(data.riderName || "Rider"),
      pickup: String(data.pickup || "Pickup"),
      dropoff: String(data.dropoff || "Dropoff"),
      state: "requested",
      priority: String(data.priority || "standard"),
      requestedAt: nowIso(),
      assignedDriverId: "",
      assignedDriverName: "",
      etaMin: Number(data.etaMin) || 14,
      slaTargetMin: Number(data.slaTargetMin) || 20,
      routeStatus: "pending"
    };
    store.trips.unshift(trip);
    touch();
    emit("trip_created", { tripId: trip.id, riderName: trip.riderName });
    return clone(trip);
  }

  function assignDriver(tripId, driverId) {
    var trip = getTripById(tripId);
    var driver = getDriverById(driverId);
    if (!trip || !driver) return { ok: false, error: "trip_or_driver_not_found" };
    if (safeState(trip.state, "requested") === "completed" || safeState(trip.state, "requested") === "canceled") {
      return { ok: false, error: "trip_closed" };
    }

    trip.assignedDriverId = driver.id;
    trip.assignedDriverName = driver.name;
    trip.state = safeState(trip.state, "requested") === "requested" ? "assigned" : safeState(trip.state, "requested");
    trip.routeStatus = "assigned";
    driver.status = "assigned";
    touch();
    emit("trip_assigned", { tripId: trip.id, driverId: driver.id, driverName: driver.name });
    return { ok: true, trip: clone(trip), driver: clone(driver) };
  }

  function selectDriver(driverId) {
    store.selectedDriverId = String(driverId || "");
    touch();
    return store.selectedDriverId;
  }

  function getSelectedDriverId() {
    return String(store.selectedDriverId || "");
  }

  function setDriverStatus(driverId, status) {
    var driver = getDriverById(driverId);
    if (!driver) return { ok: false, error: "driver_not_found" };
    driver.status = String(status || "available");
    touch();
    emit("driver_status_changed", { driverId: driver.id, status: driver.status });
    return { ok: true, driver: clone(driver) };
  }

  function getSlaClock(trip) {
    var elapsed = minutesSince(trip.requestedAt);
    var target = Number(trip.slaTargetMin) || 20;
    return {
      elapsedMin: elapsed,
      targetMin: target,
      breached: elapsed > target
    };
  }

  function getSnapshot() {
    var trips = getTrips();
    var drivers = getDrivers();
    return {
      trips: trips,
      drivers: drivers,
      selectedDriverId: getSelectedDriverId(),
      updatedAt: store.lastUpdatedAt,
      counts: {
        requested: trips.filter(function (t) { return t.state === "requested"; }).length,
        scheduled: trips.filter(function (t) { return t.state === "scheduled"; }).length,
        assigned: trips.filter(function (t) { return t.state === "assigned"; }).length,
        driver_en_route: trips.filter(function (t) { return t.state === "driver_en_route"; }).length,
        arrived: trips.filter(function (t) { return t.state === "arrived"; }).length,
        rider_onboard: trips.filter(function (t) { return t.state === "rider_onboard"; }).length,
        completed: trips.filter(function (t) { return t.state === "completed"; }).length,
        canceled: trips.filter(function (t) { return t.state === "canceled"; }).length,
        delayed: trips.filter(function (t) { return t.state === "delayed"; }).length,
        no_show: trips.filter(function (t) { return t.state === "no_show"; }).length
      },
      driverStatus: {
        available: drivers.filter(function (d) { return d.status === "available"; }).length,
        assigned: drivers.filter(function (d) { return d.status === "assigned"; }).length,
        busy: drivers.filter(function (d) { return d.status === "busy"; }).length,
        on_break: drivers.filter(function (d) { return d.status === "on_break"; }).length,
        offline: drivers.filter(function (d) { return d.status === "offline"; }).length
      },
      sla: trips.map(function (trip) {
        var clock = getSlaClock(trip);
        return {
          tripId: trip.id,
          elapsedMin: clock.elapsedMin,
          targetMin: clock.targetMin,
          breached: clock.breached
        };
      })
    };
  }

  hydrate();

  window.AmiTripLifecycle = {
    STATES: STATES,
    getSnapshot: getSnapshot,
    getTrips: getTrips,
    getDrivers: getDrivers,
    getTripById: function (tripId) { return clone(getTripById(tripId)); },
    createTrip: createTrip,
    transitionTrip: transitionTrip,
    assignDriver: assignDriver,
    setDriverStatus: setDriverStatus,
    selectDriver: selectDriver,
    getSelectedDriverId: getSelectedDriverId
  };
})();
