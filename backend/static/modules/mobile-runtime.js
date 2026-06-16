(function () {
  "use strict";

  function lifecycle() {
    return window.AmiTripLifecycle;
  }

  function driverWorkspace(driverId) {
    var snap = lifecycle() ? lifecycle().getSnapshot() : { trips: [], drivers: [] };
    var id = String(driverId || "DRV-A22");
    var driver = (snap.drivers || []).find(function (item) { return String(item.id) === id; }) || (snap.drivers || [])[0] || null;
    var queue = (snap.trips || []).filter(function (trip) {
      return !trip.assignedDriverId || String(trip.assignedDriverId) === String((driver || {}).id || "");
    }).filter(function (trip) {
      return ["requested", "scheduled", "assigned", "driver_en_route", "arrived", "rider_onboard", "delayed"].indexOf(String(trip.state)) >= 0;
    });
    return {
      driver: driver,
      queue: queue
    };
  }

  function riderWorkspace(riderId) {
    var snap = lifecycle() ? lifecycle().getSnapshot() : { trips: [] };
    var id = String(riderId || "");
    var trips = (snap.trips || []).filter(function (trip) {
      return !id || String(trip.riderId) === id;
    });
    return {
      active: trips.find(function (trip) {
        return ["requested", "scheduled", "assigned", "driver_en_route", "arrived", "rider_onboard", "delayed"].indexOf(String(trip.state)) >= 0;
      }) || null,
      history: trips.filter(function (trip) {
        return ["completed", "canceled", "no_show"].indexOf(String(trip.state)) >= 0;
      })
    };
  }

  window.AmiMobileRuntime = {
    driverWorkspace: driverWorkspace,
    riderWorkspace: riderWorkspace
  };
})();
