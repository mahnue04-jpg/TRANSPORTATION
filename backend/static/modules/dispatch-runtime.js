(function () {
  "use strict";

  function lifecycle() {
    return window.AmiTripLifecycle;
  }

  function emitUpdate() {
    window.dispatchEvent(new CustomEvent("ami:ops-runtime-updated"));
  }

  function requireLifecycle() {
    return lifecycle() && typeof lifecycle().getSnapshot === "function";
  }

  function assignDriver(tripId, driverId) {
    if (!requireLifecycle()) return { ok: false, error: "lifecycle_unavailable" };
    var result = lifecycle().assignDriver(tripId, driverId);
    if (result.ok) emitUpdate();
    return result;
  }

  function reassignDriver(tripId, driverId) {
    return assignDriver(tripId, driverId);
  }

  function cancelTrip(tripId) {
    if (!requireLifecycle()) return { ok: false, error: "lifecycle_unavailable" };
    var result = lifecycle().transitionTrip(tripId, "canceled", { routeStatus: "canceled" });
    if (result.ok) emitUpdate();
    return result;
  }

  function markArrived(tripId) {
    if (!requireLifecycle()) return { ok: false, error: "lifecycle_unavailable" };
    var result = lifecycle().transitionTrip(tripId, "arrived", { routeStatus: "arrived", etaMin: 0 });
    if (result.ok) emitUpdate();
    return result;
  }

  function completeRide(tripId) {
    if (!requireLifecycle()) return { ok: false, error: "lifecycle_unavailable" };
    var result = lifecycle().transitionTrip(tripId, "completed", { routeStatus: "completed", etaMin: 0 });
    if (result.ok) emitUpdate();
    return result;
  }

  function escalateTrip(tripId) {
    if (!requireLifecycle()) return { ok: false, error: "lifecycle_unavailable" };
    var result = lifecycle().transitionTrip(tripId, "delayed", { routeStatus: "escalated" });
    if (result.ok) {
      if (window.AmiOperationalEvents) {
        window.AmiOperationalEvents.emit("escalation_triggered", { tripId: tripId });
      }
      emitUpdate();
    }
    return result;
  }

  function contactRider(tripId) {
    if (window.AmiOperationalEvents) {
      window.AmiOperationalEvents.emit("contact_rider", { tripId: tripId });
    }
    emitUpdate();
    return { ok: true };
  }

  function contactDriver(tripId) {
    if (window.AmiOperationalEvents) {
      window.AmiOperationalEvents.emit("contact_driver", { tripId: tripId });
    }
    emitUpdate();
    return { ok: true };
  }

  function selectDriver(driverId) {
    if (!requireLifecycle()) return { ok: false, error: "lifecycle_unavailable" };
    lifecycle().selectDriver(driverId);
    emitUpdate();
    return { ok: true };
  }

  function snapshot() {
    if (!requireLifecycle()) {
      return {
        trips: [],
        drivers: [],
        counts: {},
        driverStatus: {},
        sla: [],
        selectedDriverId: ""
      };
    }
    return lifecycle().getSnapshot();
  }

  window.AmiDispatchRuntime = {
    snapshot: snapshot,
    assignDriver: assignDriver,
    reassignDriver: reassignDriver,
    cancelTrip: cancelTrip,
    markArrived: markArrived,
    completeRide: completeRide,
    escalateTrip: escalateTrip,
    contactRider: contactRider,
    contactDriver: contactDriver,
    selectDriver: selectDriver
  };
})();
