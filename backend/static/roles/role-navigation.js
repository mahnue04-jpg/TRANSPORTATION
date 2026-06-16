(function () {
  "use strict";

  window.AmiRoleNavigation = {
    admin: ["dashboard", "dispatch", "trips", "drivers", "riders", "providers", "vehicles", "billing", "analytics", "alerts", "mobile", "ai-assistant", "settings"],
    dispatcher: ["dispatch", "trips", "drivers", "riders", "alerts", "mobile", "dashboard", "analytics", "ai-assistant"],
    rider: ["riders", "mobile", "trips", "alerts", "dashboard", "ai-assistant"],
    driver: ["drivers", "mobile", "trips", "alerts", "dashboard", "ai-assistant"],
    provider: ["providers", "dispatch", "trips", "riders", "billing", "analytics", "mobile", "dashboard", "ai-assistant"],
    compliance_officer: ["dashboard", "alerts", "drivers", "riders", "providers", "trips", "analytics", "dispatch"],
    supervisor: ["dashboard", "dispatch", "trips", "alerts", "drivers", "riders", "providers", "analytics", "mobile"],
    driver_support: ["drivers", "dispatch", "trips", "riders", "alerts", "mobile", "dashboard"],
    medical_coordinator: ["riders", "trips", "providers", "mobile", "analytics", "dashboard"]
  };
})();
