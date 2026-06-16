(function () {
  "use strict";

  window.AmiRoleWorkspaces = {
    rider: {
      homeLinks: [
        { href: "/app/mobile", title: "Rider Mobile", description: "Primary rider experience for booking, tracking, and support.", note: "live" },
        { href: "/app/trips", title: "Trip Timeline", description: "See ride history, active trip context, and support posture.", note: "read-only" },
        { href: "/app/riders", title: "Rider Workspace", description: "Open the full customer coordination workspace.", note: "live" },
        { href: "/app/alerts", title: "Safety & Support", description: "Escalate ride concerns through supervised support flows.", note: "supervised" }
      ]
    },
    driver: {
      commandLinks: [
        { href: "/app/mobile", title: "Driver Mobile", description: "Open the mobile-first driver workspace.", note: "live" },
        { href: "/app/drivers", title: "Fleet Queue", description: "Review the live driver queue and route assignments.", note: "live" },
        { href: "/app/trips", title: "Trip Workflow", description: "Move through accept, arrive, start, and complete states.", note: "supervised" },
        { href: "/app/alerts", title: "Safety & Support", description: "Open emergency help, support, and compliance routing.", note: "supervised" }
      ]
    },
    dispatcher: {
      dispatchLinks: [
        { href: "/app/dispatch", title: "Dispatch Center", description: "Open the live trip assignment center.", note: "primary" },
        { href: "/app/trips", title: "Trip Management", description: "Open the live trip lifecycle board.", note: "live" },
        { href: "/app/drivers", title: "Driver Fleet", description: "Review drivers, assignments, and readiness.", note: "live" },
        { href: "/app/mobile", title: "Mobile Fleet View", description: "Switch to the mobile-ready operational view.", note: "responsive" }
      ]
    }
  };
})();
