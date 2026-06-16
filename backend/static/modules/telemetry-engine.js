(function () {
  "use strict";

  function snapshot() {
    if (!window.AmiTripLifecycle || typeof window.AmiTripLifecycle.getSnapshot !== "function") {
      return {
        kpis: {},
        timeline: []
      };
    }

    var snap = window.AmiTripLifecycle.getSnapshot();
    var events = window.AmiOperationalEvents && typeof window.AmiOperationalEvents.getEvents === "function"
      ? window.AmiOperationalEvents.getEvents(120)
      : [];

    var delayed = Number((snap.counts || {}).delayed || 0);
    var requested = Number((snap.counts || {}).requested || 0);
    var assigned = Number((snap.counts || {}).assigned || 0);
    var onboard = Number((snap.counts || {}).rider_onboard || 0);
    var completed = Number((snap.counts || {}).completed || 0);

    return {
      kpis: {
        activeTripQueue: requested + assigned,
        pendingAssignments: requested + Number((snap.counts || {}).scheduled || 0),
        delayedRideAlerts: delayed,
        urgentRideFlags: snap.trips.filter(function (trip) {
          return String(trip.priority || "") === "urgent" && String(trip.state || "") !== "completed";
        }).length,
        driverAvailable: Number((snap.driverStatus || {}).available || 0),
        driverBusy: Number((snap.driverStatus || {}).assigned || 0) + Number((snap.driverStatus || {}).busy || 0),
        slaBreaches: (snap.sla || []).filter(function (item) { return item.breached; }).length,
        inProgress: onboard + Number((snap.counts || {}).driver_en_route || 0) + Number((snap.counts || {}).arrived || 0),
        completed: completed
      },
      timeline: events
    };
  }

  window.AmiTelemetryEngine = {
    snapshot: snapshot
  };
})();
