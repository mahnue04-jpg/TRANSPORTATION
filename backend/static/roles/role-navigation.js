(function () {
  "use strict";

  window.AmiRoleNavigation = {
    admin: ["dashboard", "dispatch", "trips", "drivers", "riders", "providers", "vehicles", "billing", "analytics", "alerts", "mobile", "ai-assistant", "settings"],
    dispatcher: ["dispatch", "trips", "drivers", "riders", "billing", "alerts", "mobile", "dashboard", "analytics", "ai-assistant"],
    rider: ["riders", "mobile", "trips", "alerts", "dashboard", "ai-assistant"],
    driver: ["drivers", "mobile", "trips", "billing", "alerts", "dashboard", "ai-assistant"],
    provider: ["providers", "dispatch", "trips", "riders", "billing", "analytics", "mobile", "dashboard", "ai-assistant"],
    compliance_officer: ["dashboard", "alerts", "drivers", "riders", "providers", "trips", "billing", "analytics", "dispatch"],
    supervisor: ["dashboard", "dispatch", "trips", "billing", "alerts", "drivers", "riders", "providers", "analytics", "mobile"],
    driver_support: ["drivers", "dispatch", "trips", "riders", "billing", "alerts", "mobile", "dashboard"],
    medical_coordinator: ["riders", "trips", "providers", "billing", "mobile", "analytics", "dashboard"]
  };
})();
