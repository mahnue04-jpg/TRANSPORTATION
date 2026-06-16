(function () {
  "use strict";

  var notifications = {
    dispatcher: [],
    driver: [],
    rider: [],
    admin: []
  };

  function push(role, level, text) {
    if (!notifications[role]) notifications[role] = [];
    notifications[role].unshift({
      id: role + "-" + Date.now() + "-" + Math.floor(Math.random() * 100000),
      level: String(level || "low"),
      text: String(text || "notification"),
      ts: new Date().toISOString()
    });
    notifications[role] = notifications[role].slice(0, 60);
  }

  if (window.AmiOperationalEvents && typeof window.AmiOperationalEvents.onEvent === "function") {
    window.AmiOperationalEvents.onEvent(function (event) {
      var type = String((event || {}).type || "event");
      var payload = (event || {}).payload || {};
      if (type === "trip_created") {
        push("dispatcher", "medium", "New trip created: " + String(payload.tripId || "trip"));
        push("rider", "low", "Trip request submitted.");
      } else if (type === "trip_assigned") {
        push("dispatcher", "low", "Trip " + String(payload.tripId || "") + " assigned to " + String(payload.driverName || "driver"));
        push("driver", "medium", "You have a new assignment: " + String(payload.tripId || "trip"));
        push("rider", "low", "Driver assigned to your trip.");
      } else if (type === "delay_triggered") {
        push("dispatcher", "high", "Delay triggered for " + String(payload.tripId || "trip"));
        push("rider", "medium", "Your trip is delayed. Support has been alerted.");
      } else if (type === "trip_completed") {
        push("dispatcher", "low", "Trip completed: " + String(payload.tripId || "trip"));
        push("rider", "low", "Trip completed. Thank you.");
        push("driver", "low", "Trip completed successfully.");
      } else if (type === "escalation_triggered") {
        push("dispatcher", "high", "Escalation triggered for " + String(payload.tripId || "trip"));
        push("admin", "medium", "Operational escalation triggered.");
      }
      window.dispatchEvent(new CustomEvent("ami:ops-runtime-updated"));
    });
  }

  function get(role, limit) {
    var items = notifications[role] || [];
    return items.slice(0, Math.max(1, Number(limit) || 12));
  }

  window.AmiNotificationsEngine = {
    get: get,
    push: push
  };
})();
