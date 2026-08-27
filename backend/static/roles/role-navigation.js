(function () {
  "use strict";

  window.AmiRoleNavigation = {
    admin: ["home", "dashboard", "dispatch", "trips", "drivers", "riders", "providers", "vehicles", "billing", "analytics", "alerts", "mobile", "ai-assistant", "settings"],
    dispatcher: ["home", "dispatch", "trips", "drivers", "riders", "billing", "alerts", "mobile", "dashboard", "analytics", "ai-assistant"],
    rider: ["home", "riders", "mobile", "trips", "alerts", "dashboard", "ai-assistant"],
    driver: ["home", "drivers", "mobile", "trips", "billing", "alerts", "dashboard", "ai-assistant"],
    provider: ["home", "providers", "dispatch", "trips", "riders", "billing", "analytics", "mobile", "dashboard", "ai-assistant"],
    compliance_officer: ["home", "dashboard", "alerts", "drivers", "riders", "providers", "trips", "billing", "analytics", "dispatch"],
    supervisor: ["home", "dashboard", "dispatch", "trips", "billing", "alerts", "drivers", "riders", "providers", "analytics", "mobile"],
    driver_support: ["home", "drivers", "dispatch", "trips", "riders", "billing", "alerts", "mobile", "dashboard"],
    medical_coordinator: ["home", "riders", "trips", "providers", "billing", "mobile", "analytics", "dashboard"]
  };
})();
