(function () {
  "use strict";

  function lifecycle() {
    return window.AmiTripLifecycle;
  }

  function emitUpdate() {
    window.dispatchEvent(new CustomEvent("ami:ops-runtime-updated"));
  }

  function setDriverStatus(driverId, status) {
    if (!lifecycle()) return { ok: false, error: "lifecycle_unavailable" };
    var result = lifecycle().setDriverStatus(driverId, status);
    if (result.ok) emitUpdate();
    return result;
  }

  function acceptTrip(tripId) {
    if (!lifecycle()) return { ok: false, error: "lifecycle_unavailable" };
    var result = lifecycle().transitionTrip(tripId, "assigned", { routeStatus: "accepted" });
    if (result.ok) {
      if (window.AmiOperationalEvents) window.AmiOperationalEvents.emit("driver_accepted", { tripId: tripId });
      emitUpdate();
    }
    return result;
  }

  function rejectTrip(tripId) {
    if (!lifecycle()) return { ok: false, error: "lifecycle_unavailable" };
    var result = lifecycle().transitionTrip(tripId, "scheduled", { routeStatus: "rejected_requeue" });
    if (result.ok) {
      if (window.AmiOperationalEvents) window.AmiOperationalEvents.emit("driver_rejected", { tripId: tripId });
      emitUpdate();
    }
    return result;
  }

  function startNavigation(tripId) {
    if (!lifecycle()) return { ok: false, error: "lifecycle_unavailable" };
    var result = lifecycle().transitionTrip(tripId, "driver_en_route", { routeStatus: "navigation_active" });
    if (result.ok) emitUpdate();
    return result;
  }

  function markArrived(tripId) {
    if (!lifecycle()) return { ok: false, error: "lifecycle_unavailable" };
    var result = lifecycle().transitionTrip(tripId, "arrived", { routeStatus: "arrived", etaMin: 0 });
    if (result.ok) {
      if (window.AmiOperationalEvents) window.AmiOperationalEvents.emit("driver_arrived", { tripId: tripId });
      emitUpdate();
    }
    return result;
  }

  function onboardRider(tripId) {
    if (!lifecycle()) return { ok: false, error: "lifecycle_unavailable" };
    var result = lifecycle().transitionTrip(tripId, "rider_onboard", { routeStatus: "onboard" });
    if (result.ok) {
      if (window.AmiOperationalEvents) window.AmiOperationalEvents.emit("rider_onboard", { tripId: tripId });
      emitUpdate();
    }
    return result;
  }

  function completeTrip(tripId) {
    if (!lifecycle()) return { ok: false, error: "lifecycle_unavailable" };
    var result = lifecycle().transitionTrip(tripId, "completed", { routeStatus: "completed", etaMin: 0 });
    if (result.ok) {
      if (window.AmiOperationalEvents) window.AmiOperationalEvents.emit("trip_completed", { tripId: tripId });
      emitUpdate();
    }
    return result;
  }

  function delayTrip(tripId) {
    if (!lifecycle()) return { ok: false, error: "lifecycle_unavailable" };
    var result = lifecycle().transitionTrip(tripId, "delayed", { routeStatus: "delayed" });
    if (result.ok) {
      if (window.AmiOperationalEvents) window.AmiOperationalEvents.emit("delay_triggered", { tripId: tripId });
      emitUpdate();
    }
    return result;
  }

  window.AmiDriverRuntime = {
    setDriverStatus: setDriverStatus,
    acceptTrip: acceptTrip,
    rejectTrip: rejectTrip,
    startNavigation: startNavigation,
    markArrived: markArrived,
    onboardRider: onboardRider,
    completeTrip: completeTrip,
    delayTrip: delayTrip
  };
})();
