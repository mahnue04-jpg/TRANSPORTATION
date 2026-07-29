(function () {
  "use strict";

  var APP_BASE_PATH = "/app";

  var ROUTES = {
    "dashboard": { path: APP_BASE_PATH + "/dashboard", title: "Dashboard", subtitle: "Healthcare transportation command center with live operational intelligence." },
    "dispatch": { path: APP_BASE_PATH + "/dispatch", title: "Dispatch Board", subtitle: "Live fleet dispatch, assignment coordination, and escalation control." },
    "trips": { path: APP_BASE_PATH + "/trips", title: "Trips", subtitle: "Trip lifecycle monitoring across rider, driver, and provider flows." },
    "drivers": { path: APP_BASE_PATH + "/drivers", title: "Drivers", subtitle: "Driver operations, compliance state, and shift performance." },
    "riders": { path: APP_BASE_PATH + "/riders", title: "Rider App", subtitle: "Request rides, track active trips, and contact support." },
    "providers": { path: APP_BASE_PATH + "/providers", title: "Providers", subtitle: "Facility and provider transport operations portal." },
    "vehicles": { path: APP_BASE_PATH + "/vehicles", title: "Vehicles", subtitle: "Fleet inventory, availability, and maintenance readiness." },
    "billing": { path: APP_BASE_PATH + "/billing", title: "Billing", subtitle: "Revenue tracking, claims reimbursement, and financial controls." },
    "analytics": { path: APP_BASE_PATH + "/analytics", title: "Reports & Analytics", subtitle: "Operational and financial analytics across dispatch and care delivery." },
    "alerts": { path: APP_BASE_PATH + "/alerts", title: "Alerts", subtitle: "Operational alerts, escalations, and supervision-critical notices." },
    "mobile": { path: APP_BASE_PATH + "/mobile", title: "Driver Mobile", subtitle: "Field driver sign-in, trip workflow, and assignment sync." },
    "ai-assistant": { path: APP_BASE_PATH + "/ai-assistant", title: "AI Assistant", subtitle: "Side operational assistant for guidance, summaries, and supervised recommendations." },
    "settings": { path: APP_BASE_PATH + "/settings", title: "Settings", subtitle: "Organization, permissions, and platform configuration controls." },
    "system-health": { path: APP_BASE_PATH + "/system-health", title: "Operations Status", subtitle: "Operational readiness and live monitoring posture." }
  };

  var LEGACY_ROUTE_ALIASES = {
            detail: "Compare available drivers against active provider demand and confirm readiness gaps using read-only operations visibility.",
    "/dispatch": APP_BASE_PATH + "/dispatch",
    "/trips": APP_BASE_PATH + "/trips",
    "/riders": APP_BASE_PATH + "/riders",
    "/patients": APP_BASE_PATH + "/riders",
    "/vehicles": APP_BASE_PATH + "/vehicles",
    "/billing": APP_BASE_PATH + "/billing",
    "/analytics": APP_BASE_PATH + "/analytics",
    "/alerts": APP_BASE_PATH + "/alerts",
    "/mobile": APP_BASE_PATH + "/mobile",
    "/settings": APP_BASE_PATH + "/settings",
    "/providers": APP_BASE_PATH + "/providers",
    "/drivers": APP_BASE_PATH + "/drivers",
    [APP_BASE_PATH + "/patients"]: APP_BASE_PATH + "/riders",
    "/rides": APP_BASE_PATH + "/trips",
    "/operations": APP_BASE_PATH + "/dispatch",
    "/operations/live": APP_BASE_PATH + "/dispatch",
    "/operations/federation": APP_BASE_PATH + "/analytics",
    "/operations/replay": APP_BASE_PATH + "/analytics",
    "/operations/predictive": APP_BASE_PATH + "/analytics",
    "/operations/governance": APP_BASE_PATH + "/analytics",
    "/operations/command-center": APP_BASE_PATH + "/dispatch",
    "/operations/timeline": APP_BASE_PATH + "/trips",
    "/operations/map-preview": APP_BASE_PATH + "/mobile",
    "/operations/alerts": APP_BASE_PATH + "/alerts",
    "/system-health": APP_BASE_PATH + "/system-health",
    "/ai-assistant": APP_BASE_PATH + "/ai-assistant"
  };

  var ROLE_ACCESS = {
    admin: ["dashboard", "dispatch", "trips", "drivers", "riders", "providers", "vehicles", "billing", "analytics", "alerts", "mobile", "ai-assistant", "settings", "system-health"],
    dispatcher: ["dashboard", "dispatch", "trips", "drivers", "riders", "vehicles", "billing", "alerts", "mobile", "ai-assistant", "system-health"],
    rider: ["dashboard", "trips", "riders", "mobile", "ai-assistant", "system-health"],
    provider: ["dashboard", "dispatch", "trips", "riders", "providers", "billing", "analytics", "mobile", "ai-assistant", "system-health"],
    driver: ["dashboard", "trips", "drivers", "billing", "mobile", "ai-assistant", "system-health"],
    compliance_officer: ["dashboard", "dispatch", "trips", "drivers", "riders", "providers", "vehicles", "billing", "analytics", "alerts", "system-health"],
    supervisor: ["dashboard", "dispatch", "trips", "drivers", "riders", "providers", "vehicles", "billing", "alerts", "analytics", "system-health", "ai-assistant"],
    driver_support: ["dashboard", "dispatch", "trips", "drivers", "riders", "billing", "alerts", "mobile", "ai-assistant", "system-health"],
    medical_coordinator: ["dashboard", "trips", "riders", "providers", "billing", "analytics", "mobile", "system-health", "ai-assistant"]
  };

  var ROLE_DEFAULT_ROUTE = {
    admin: "dashboard",
    dispatcher: "dispatch",
    rider: "riders",
    provider: "providers",
    driver: "mobile",
    compliance_officer: "dashboard",
    supervisor: "dashboard",
    driver_support: "dashboard",
    medical_coordinator: "dashboard"
  };

  var SEED_DRIVER_PHONE_BY_EMAIL = {
    "driver@amicor.local": "917-555-1001",
    "maria.garcia@amicor.local": "917-555-1002",
    "dispatcher@amicor.local": "917-555-1000"
  };
  var DRIVER_PROOF_MARKERS = [
    "driver ai proof",
    "production proof",
    "proof driver",
    "live dispatch driver",
    "hydration proof",
    "proof rider",
    "malik_final_proof",
    "prod_sync_",
    "bill_sync_",
    "render_ready_",
    "ops_clean_",
    "e2e sync",
    "financial rider",
    "lifecycle test",
    "platform stability",
    "proof rider"
  ];
  var DRIVER_SCRIPT_MARKERS = [
    "live pickup",
    "live dropoff",
    "rider browser pickup",
    "rider browser dropoff",
    "rider app verify",
    "ops verify",
    "flow pickup",
    "flow dropoff",
    "browser pickup",
    "browser dropoff",
    "proof pickup",
    "proof dropoff",
    "final local production readiness",
    "billing module sync",
    "production sync consecutive"
  ];
  var TERMINAL_RIDE_STATUSES = [
    "completed",
    "cancelled",
    "failed",
    "dropoff_complete",
    "closed",
    "resolved",
    "declined",
    "no_show"
  ];

  var ROLE_OPERATIONAL_PATHS = {
    medical_coordinator: APP_BASE_PATH + "/operations/medical-coordinator",
    driver_support: APP_BASE_PATH + "/operations/driver-support",
    supervisor: APP_BASE_PATH + "/operations/supervisor",
    compliance_officer: APP_BASE_PATH + "/operations/compliance",
    provider: APP_BASE_PATH + "/operations/provider",
    driver: APP_BASE_PATH + "/operations/driver"
  };

  var OPERATIONAL_PATH_TO_ROLE = {
    "medical-coordinator": "medical_coordinator",
    "driver-support": "driver_support",
    "supervisor": "supervisor",
    "compliance": "compliance_officer",
    "provider": "provider",
    "driver": "driver"
  };

  var ROLE_PROFILE = {
    admin: {
      context: "Owner command center with cross-surface visibility and supervision-first controls.",
      emphasis: "dispatch",
      notices: ["Admin scope includes all surfaces.", "Automated field actions and dispatch remain disabled.", "All recommendations remain advisory-only."]
    },
    dispatcher: {
      context: "Dispatcher command center for queue management, assignment coordination, and escalation supervision.",
      emphasis: "dispatch",
      notices: ["Assignments require supervised confirmation.", "Priority routing remains policy-constrained.", "All action requests pass governance review before release."]
    },
    rider: {
      context: "Rider/customer experience with ride progress visibility and support guidance.",
      emphasis: "riders",
      notices: ["Ride status is updated from protected operational feeds.", "ETA and assignment indicators are advisory snapshots for coordination.", "Assistant guidance is informational only."]
    },
    provider: {
      context: "Provider/partner operations visibility for coverage, compliance, and capacity.",
      emphasis: "providers",
      notices: ["Provider recommendations are advisory only.", "No provider workflow changes are permitted in this phase.", "Compliance state remains view-only and audit-safe."]
    },
    driver: {
      context: "Driver workspace for supervised opportunities, route summaries, and safety posture.",
      emphasis: "drivers",
      notices: ["Dispatch continuity remains supervisor-controlled.", "Trip workflow controls are supervised and continuity-safe.", "Route and earnings values remain informational for protected operations."]
    },
    compliance_officer: {
      context: "Compliance operations workspace for document review, expiration tracking, and supervised onboarding governance.",
      emphasis: "alerts",
      notices: ["Document verification is operator-supervised.", "No automatic approvals or suspensions are enabled.", "All compliance actions are continuity protected in audit history."]
    },
    supervisor: {
      context: "Supervisor workspace for manual approval and rejection decisions with full audit attribution.",
      emphasis: "alerts",
      notices: ["Supervisor approval is mandatory for activation outcomes.", "Approval/rejection reasons are required upstream.", "Automated field actions remain disabled."]
    },
    driver_support: {
      context: "Driver support workspace for onboarding assistance without approval authority.",
      emphasis: "drivers",
      notices: ["Driver support can assist onboarding only.", "Approval controls remain restricted to supervisors.", "All updates are advisory and audit-tracked."]
    },
    medical_coordinator: {
      context: "Medical coordinator workspace with view-only medical transport certification visibility.",
      emphasis: "trips",
      notices: ["Medical view is role-scoped and view-only.", "No approval or direct change controls are available.", "Audit timeline remains continuity protected."]
    }
  };

  var state = {
    role: "admin",
    route: "dashboard",
    roleRoutes: {
      admin: "dashboard",
      dispatcher: "dispatch",
      rider: "riders",
      provider: "providers",
      driver: "mobile",
      compliance_officer: "dashboard",
      supervisor: "dashboard",
      driver_support: "dashboard",
      medical_coordinator: "dashboard"
    },
    health: null,
    supervision: null,
    ops: {
      dashboardSummary: null,
      liveStatus: null,
      alerts: null,
      recommendations: null,
      timeline: [],
      timelineCursor: 0,
      stream: {
        connected: false,
        mode: "polling_fallback",
        fallbackPollingActive: true,
        lastEventReceived: null,
        eventCount: 0,
        timelineSyncStatus: "idle",
        supervisionSafe: true,
        replaySafe: true
      },
      correlation: {
        totalGroups: 0,
        groups: []
      },
      compliance: {
        compliance_overview: null,
        expiration_queue: null,
        approval_queue: null,
        compliance_timeline: [],
        phase25: {
          evidence_chain_viewer: [],
          document_lineage_viewer: [],
          supervisor_review_queue: [],
          regulatory_export_builder: [],
          signed_access_monitor: [],
          retention_status_dashboard: []
        },
        profiles: [],
        documents: []
      },
      orchestration: {
        queue_snapshot: {
          tasks: [],
          queue_health: {}
        },
        live_stream: {
          events: [],
          next_cursor: 0,
          checkpoint: null,
          stream_cursor: null
        },
        timeline_projection: {
          events: [],
          next_cursor: 0
        },
        notifications: {
          notifications: []
        },
        sla: {
          alerts: [],
          metrics: {}
        },
        queue_health: {
          queue_pressure_dashboard: {}
        },
        export_bundle: {
          bundle_id: null,
          bundle_checksum: null,
          replay_reconstruction: {}
        }
      },
      federation: {
        regions: { regions: [] },
        queues: { regions: [] },
        capacity: { forecasts: [] },
        continuity: { continuity_projection: [] },
        health: { regions: [] },
        export_bundle: { bundle_id: null, bundle_checksum: null, payload: {} }
      },
      predictive: {
        governance: null,
        constraints: null,
        capacity: null,
        risk: null,
        anomaly: null,
        drift: { drift_events: [] },
        recommendations: { recommendations: [] },
        trends: { trends: [] },
        evidence: { payload: {} },
        export_bundle: { bundle_id: null, bundle_checksum: null, payload: {} }
      },
      governance: {
        provenance: null,
        explanations: null,
        reasoning: null,
        memory: null,
        ancestry: { ancestry_trace: [] },
        lineage: null,
        history: null,
        trends: null,
        policyMatrix: { policy_matrix: [], constraint_versions: [] },
        policyFrameworkMap: { frameworks: [], framework_rule_mappings: [] },
        policyEvaluations: { constraint_evaluations: [], constraint_violations: [], regulatory_evidence_refs: [] },
        policyScore: null,
        rationaleChain: { rationale_chain: [], decision_trace: [] },
        policyLineage: { policy_lineage: [] },
        policyHistory: { constraint_history: [], score_history: [] },
        policyViolations: { violations: [] },
        policyConstraints: { constraints: [] },
        policyFrameworks: { frameworks: [] },
        risk: { recommendations: [] },
        export_bundle: { bundle_id: null, bundle_checksum: null, payload: {} }
      },
      workspaceActivation: {
        role_view: "admin",
        role_scope: "admin",
        summary: null,
        compliance: null,
        orchestration: null,
        workspace_modules: {},
        allowed_actions: [],
        governance: {
          advisory_only: true,
          supervision_required: true,
          execution_disabled: true,
          append_only: true,
          replay_safe: true
        }
      },
      replay: {
        session: { frames: [] },
        scenario: null,
        branch: null,
        timeline: { events: [] },
        projection: { events: [] },
        comparison: { comparisons: [] },
        continuity: null,
        evidence: { payload: {} },
        export_bundle: { bundle_id: null, bundle_checksum: null, payload: {} }
      },
      visibility: {}
    },
    loading: false,
    error: null,
    fetchWarnings: [],
    hydration: {
      authTokenPresent: false,
      opsHydrated: false,
      roleSlice: "admin",
      lastUpdatedAt: "",
      warningCount: 0,
      integrityState: "replay_safe"
    },
    liveWorkflow: {
      dispatchQueue: [],
      activeAssignments: [],
      drivers: [],
      activityFeed: [],
      rides: [],
      providers: [],
      customerRequests: [],
      vehicles: []
    },
    revenueWorkflow: null,
    dispatcherWorkspace: {
      messages: [],
      proof: {
        last_action: "none",
        api_status: "idle",
        db_record_id: "n/a",
        ui_updated: "no"
      },
      patientDraft: {
        name: "",
        phone: "",
        pickup: "",
        dropoff: ""
      }
    },
    driverWorkflow: {
      driverId: "",
      workspace: null,
      activeOffer: null
    },
    healthIsfAiSnapshot: null,
    assistant: {
      runtimeState: "monitoring",
      isResponding: false,
      draft: "",
      pendingPrompt: "",
      messages: [],
      toolEvents: [],
      previewCards: [],
      pendingIntent: null,
      auditEvents: [],
      executionHistory: [],
      memoryEntries: [],
      sessionNonce: "",
      securityState: {
        verifiedPreview: false,
        signedConfirmation: false,
        tokenExpiresInSeconds: 0,
        dryRunOnly: true,
        executionDisabled: true,
        supervisionEnforced: true,
        durableVerifiedPreview: false,
        auditChainActive: false,
        distributedReplayProtection: false,
        policyVersion: "unknown",
        correlationId: ""
      },
      collapsible: {
        memory: false,
        tools: false,
        audit: false,
        preview: false,
        session: false,
        history: false,
        execution: false,
        persistent: false
      }
    },
    driverApp: null,
    riderApp: null,
    runtime: {
      operatorMode: true,
      reconnectCount: 0,
      lastReconnectReason: "none",
      lastNavigationSource: "init",
      lastRenderTimestamp: "",
      backendHealth: "unknown",
      lastUserActivityAt: 0,
      lastRefreshTriggerAt: 0,
      lastRefreshTriggerSource: "",
      refreshPausedUntilMs: 0,
      backendDownConsecutive: 0,
      silentRetryCount: 0,
      suppressSyntheticClicks: 0,
      hydrationLoadGen: 0,
      lastPageDataSignature: ""
    }
  };

  var refreshHandle = null;
  var driverUiRenderTimer = null;
  var driverHydrateLockUntil = 0;
  var driverWorkflowRefreshSeq = 0;
  var driverBoundDriverId = "";
  var driverLastAppliedRefreshSeq = 0;
  var driverPollAbortController = null;
  var driverWorkflowRefreshPromise = null;
  var driverLastConfirmedWorkflow = null;
  var driverLastAppliedObservedAt = 0;
  var driverActionInFlight = false;
  var driverMobileLoginInFlight = false;
  var DRIVER_SESSION_STORAGE_KEY = "amicor_driver_session";
  var MOBILE_SURFACE_STORAGE_KEY = "amicor_last_mobile_surface";
  var driverMobileAuthCache = null;

  function getMobileSessionDriverId() {
    if (!isDriverMobileAppRoute()) return "";
    var persisted = readPersistedDriverSession();
    return persisted && persisted.driver_id ? safeText(persisted.driver_id, "") : "";
  }

  function getCanonicalMobileDriverContext() {
    if (!isDriverMobileSessionRoute()) {
      return {
        driverId: "",
        sessionToken: "",
        driverName: "",
        organizationId: "",
        authenticated: false,
        uiState: "not_mobile"
      };
    }
    var persisted = readPersistedDriverSession();
    if (!persisted || !persisted.driver_id || !persisted.session_token) {
      return {
        driverId: "",
        sessionToken: "",
        driverName: "",
        organizationId: "",
        authenticated: false,
        uiState: "login_required"
      };
    }
    return {
      driverId: safeText(persisted.driver_id, ""),
      sessionToken: safeText(persisted.session_token, ""),
      sessionId: safeText(persisted.session_id, ""),
      driverName: safeText(persisted.driver_name, ""),
      organizationId: safeText(persisted.organization_id, ""),
      authenticated: true,
      uiState: "session_ready"
    };
  }

  function resolveCanonicalMobileDriverId() {
    var ctx = getCanonicalMobileDriverContext();
    if (ctx.authenticated && ctx.driverId) {
      driverBoundDriverId = ctx.driverId;
      return ctx.driverId;
    }
    return "";
  }

  function isMobileDriverApiUrl(url) {
    return safeText(url, "").indexOf("/api/health-isf/drivers/") >= 0;
  }

  function isDriverMobileRideApiUrl(url) {
    return isDriverMobileAppRoute() && safeText(url, "").indexOf("/api/health-isf/rides/") >= 0;
  }

  function resolveDriverMobileFetchTimeoutMs(scopedUrl, explicitTimeoutMs) {
    if (explicitTimeoutMs) {
      return explicitTimeoutMs;
    }
    if (isMobileDriverApiUrl(scopedUrl) && isDriverMobileAppRoute()) {
      return DRIVER_MOBILE_FETCH_TIMEOUT_MS;
    }
    return null;
  }

  function shouldUseDriverSessionFirstFetch(scopedUrl) {
    if (!isDriverMobileSessionRoute()) {
      return false;
    }
    var driverSessionToken = getDriverSessionToken();
    if (!driverSessionToken) {
      return false;
    }
    return isMobileDriverApiUrl(scopedUrl) || isDriverMobileRideApiUrl(scopedUrl);
  }

  function persistMobileSurfacePreference(surface) {
    var normalized = safeText(surface, "").toLowerCase();
    if (normalized !== "driver" && normalized !== "rider") {
      return;
    }
    try {
      localStorage.setItem(MOBILE_SURFACE_STORAGE_KEY, normalized);
    } catch (_) {}
  }

  function readMobileSurfacePreference() {
    try {
      var value = safeText(localStorage.getItem(MOBILE_SURFACE_STORAGE_KEY), "").toLowerCase();
      return value === "driver" || value === "rider" ? value : "";
    } catch (_) {
      return "";
    }
  }

  function shouldRestoreDedicatedMobileRoute(pathRoute) {
    if (pathRoute === "mobile" || pathRoute === "riders") {
      return false;
    }
    if (pathRoute !== "dashboard") {
      return false;
    }
    var surface = readMobileSurfacePreference();
    if (surface === "driver") {
      var driverSession = readPersistedDriverSession();
      return !!(driverSession && (driverSession.session_token || driverSession.driver_id));
    }
    if (surface === "rider") {
      return getPlatformRole() === "rider" && !!getAccessToken();
    }
    return false;
  }

  function resolveInitialAppRoute(pathRoute, rememberedRoute) {
    if (pathRoute === "mobile") {
      return "mobile";
    }
    if (pathRoute === "riders") {
      return "riders";
    }
    if (pathRoute !== "dashboard") {
      return pathRoute;
    }
    if (shouldRestoreDedicatedMobileRoute(pathRoute)) {
      return readMobileSurfacePreference() === "rider" ? "riders" : "mobile";
    }
    if (rememberedRoute && routeAllowed(getPlatformRole(), rememberedRoute)) {
      return rememberedRoute;
    }
    return pathRoute;
  }

  function alignPlatformRoleWithDedicatedPath(pathRoute) {
    if (pathRoute === "riders") {
      persistMobileSurfacePreference("rider");
      var jwtRole = getJwtSessionRole();
      if (jwtRole === "rider" || state.role === "rider") {
        state.role = "rider";
        savePlatformRole("rider");
      }
      return;
    }
    if (pathRoute === "mobile") {
      persistMobileSurfacePreference("driver");
    }
  }

  function readPersistedDriverSession() {
    try {
      var raw = localStorage.getItem(DRIVER_SESSION_STORAGE_KEY);
      if (!raw) return null;
      var parsed = JSON.parse(raw);
      if (!parsed || typeof parsed !== "object") return null;
      var driverId = safeText(parsed.driver_id || parsed.driverId, "");
      if (!driverId) return null;
      return {
        driver_id: driverId,
        driver_name: safeText(parsed.driver_name || parsed.driverName, ""),
        role: safeText(parsed.role, "driver").toLowerCase() || "driver",
        session_token: safeText(parsed.session_token || parsed.sessionToken, ""),
        session_id: safeText(parsed.session_id || parsed.sessionId, ""),
        organization_id: safeText(parsed.organization_id || parsed.organizationId, ""),
        updated_at: safeText(parsed.updated_at, "")
      };
    } catch (_) {
      return null;
    }
  }

  function persistDriverSession(payload) {
    var driverId = safeText(payload && (payload.driver_id || payload.driverId), "");
    if (!driverId) return null;
    var session = {
      driver_id: driverId,
      driver_name: safeText(payload && (payload.driver_name || payload.driverName), ""),
      role: "driver",
      session_token: safeText(payload && (payload.session_token || payload.sessionToken), ""),
      session_id: safeText(payload && (payload.session_id || payload.sessionId), ""),
      organization_id: safeText(payload && (payload.organization_id || payload.organizationId), ""),
      updated_at: new Date().toISOString()
    };
    try {
      localStorage.setItem(DRIVER_SESSION_STORAGE_KEY, JSON.stringify(session));
      if (!isDriverMobileAppRoute()) {
        localStorage.setItem("amicor_driver_workflow_id", driverId);
      }
    } catch (_) {}
    bindDriverIdentity(driverId, { forceRebind: true });
    driverMobileAuthCache = null;
    persistMobileSurfacePreference("driver");
    try {
      window.dispatchEvent(new CustomEvent("ami:driver-session-updated", { detail: session }));
    } catch (_) {}
    return session;
  }

  function getDriverSessionToken() {
    var persisted = readPersistedDriverSession();
    return persisted && persisted.session_token ? persisted.session_token : "";
  }

  function applyDriverSessionHeaders(headers, platformToken, requestUrl) {
    var next = Object.assign({}, headers || {});
    if (!isMobileDriverApiUrl(requestUrl) && !isDriverMobileRideApiUrl(requestUrl)) {
      return next;
    }
    var mobileCtx = getCanonicalMobileDriverContext();
    var driverSessionToken = mobileCtx.sessionToken || getDriverSessionToken();
    if (driverSessionToken) {
      next["X-Driver-Session-Token"] = driverSessionToken;
    }
    return next;
  }

  window._amiPersistDriverSession = persistDriverSession;

  function clearPersistedDriverSession() {
    try {
      localStorage.removeItem(DRIVER_SESSION_STORAGE_KEY);
      localStorage.removeItem("amicor_driver_workflow_id");
    } catch (_) {}
    driverMobileAuthCache = null;
    resetDriverBoundIdentity();
    try {
      window.dispatchEvent(new CustomEvent("ami:driver-session-updated", { detail: null }));
    } catch (_) {}
  }

  window._amiClearDriverSession = clearPersistedDriverSession;

  async function resolveDriverMobileAuth(token) {
    var persisted = readPersistedDriverSession();
    if (isDriverMobileAppRoute()) {
      if (
        driverMobileAuthCache
        && persisted
        && safeText(driverMobileAuthCache.driver_id, "") !== safeText(persisted.driver_id, "")
      ) {
        driverMobileAuthCache = null;
      }
      if (driverMobileAuthCache && safeText(driverMobileAuthCache.driver_id, "")) {
        return driverMobileAuthCache;
      }
      if (persisted && persisted.driver_id && persisted.session_token) {
        driverMobileAuthCache = {
          valid: true,
          requires_login: false,
          driver_id: persisted.driver_id,
          driver_name: persisted.driver_name || "",
          session_role: "driver",
          auth_role: "driver",
          organization_id: persisted.organization_id || "",
          session_token: persisted.session_token || "",
          source: "persisted_driver_session"
        };
        bindDriverIdentity(persisted.driver_id);
        return driverMobileAuthCache;
      }
      driverMobileAuthCache = {
        valid: false,
        requires_login: true,
        driver_id: "",
        driver_name: "",
        session_role: "driver",
        auth_role: "driver",
        organization_id: "",
        session_token: "",
        source: "driver_mobile_login_required"
      };
      return driverMobileAuthCache;
    }
    var authRole = "";
    var authEmail = "";
    var authName = "";
    var organizationId = "";
    if (token) {
      try {
        var me = await fetchJson("/api/auth/me", {}, token);
        authRole = safeText(me.role || me.session_role, "").toLowerCase();
        authEmail = safeText(me.email, "").toLowerCase();
        authName = safeText(me.display_name, "");
        organizationId = safeText(me.organization_id, "");
      } catch (_) {}
    }
    if (persisted && persisted.driver_id) {
      driverMobileAuthCache = {
        valid: true,
        requires_login: false,
        driver_id: persisted.driver_id,
        driver_name: persisted.driver_name || "",
        session_role: "driver",
        auth_role: authRole || persisted.role || "driver",
        organization_id: persisted.organization_id || organizationId,
        session_token: persisted.session_token || "",
        source: "persisted_driver_session"
      };
      bindDriverIdentity(persisted.driver_id);
      return driverMobileAuthCache;
    }
    var supervisedRoles = ["dispatcher", "admin", "supervisor", "driver_support"];
    var candidateDriverId = "";
    try {
      var query = new URLSearchParams(String(window.location.search || ""));
      candidateDriverId = safeText(query.get("driver_id") || query.get("driverId") || "", "");
    } catch (_) {}
    if (!candidateDriverId) {
      candidateDriverId = safeText(localStorage.getItem("amicor_driver_workflow_id") || "", "");
    }
    if (token && candidateDriverId && supervisedRoles.indexOf(authRole) >= 0) {
      var supervisedName = "";
      try {
        var supervisedDrivers = await fetchJson("/api/health-isf/drivers?limit=200", {}, token);
        var supervisedRows = Array.isArray(supervisedDrivers) ? supervisedDrivers : [];
        var supervisedMatch = supervisedRows.find(function (row) {
          return safeText(row.id, "") === candidateDriverId;
        });
        supervisedName = safeText(supervisedMatch && (supervisedMatch.name || supervisedMatch.driver_name), "");
      } catch (_) {}
      driverMobileAuthCache = {
        valid: true,
        requires_login: false,
        driver_id: candidateDriverId,
        driver_name: supervisedName,
        session_role: authRole,
        auth_role: authRole,
        organization_id: organizationId,
        session_token: "",
        source: "supervised_driver_view"
      };
      bindDriverIdentity(candidateDriverId);
      return driverMobileAuthCache;
    }
    if (authRole === "driver") {
      var resolvedId = await resolveSessionDriverId(token);
      if (resolvedId) {
        var driverName = "";
        try {
          var drivers = await fetchJson("/api/health-isf/drivers?limit=200", {}, token);
          var rows = Array.isArray(drivers) ? drivers : [];
          var match = rows.find(function (row) {
            return safeText(row.id, "") === resolvedId;
          });
          driverName = safeText(match && (match.name || match.driver_name), "");
        } catch (_) {}
        driverMobileAuthCache = {
          valid: true,
          requires_login: false,
          driver_id: resolvedId,
          driver_name: driverName,
          session_role: "driver",
          auth_role: authRole,
          organization_id: organizationId,
          session_token: "",
          source: "auth_driver_role"
        };
        bindDriverIdentity(resolvedId);
        return driverMobileAuthCache;
      }
    }
    driverMobileAuthCache = {
      valid: false,
      requires_login: true,
      driver_id: "",
      driver_name: "",
      session_role: authRole || safeText(state.role, ""),
      auth_role: authRole || safeText(state.role, ""),
      organization_id: organizationId,
      session_token: "",
      source: "missing_driver_session",
      auth_email: authEmail,
      auth_name: authName
    };
    return driverMobileAuthCache;
  }

  function clearDriverMobileWorkflowState(options) {
    var opts = options || {};
    var nextDriverId = safeText(opts.driverId, "");
    driverLastConfirmedWorkflow = null;
    driverHydrateLockUntil = 0;
    driverLastAppliedRefreshSeq = 0;
    driverLastAppliedObservedAt = 0;
    state.driverWorkflow = {
      driverId: nextDriverId,
      workspace: null,
      activeRide: { has_active_ride: false, ride: null },
      activeOffer: null,
      assignedRides: [],
      upcomingSchedule: [],
      scheduledOffers: [],
      earnings: safeObject((safeObject(state.driverWorkflow)).earnings),
      completedRides: Array.isArray((safeObject(state.driverWorkflow)).completedRides)
        ? state.driverWorkflow.completedRides
        : [],
      billingHandoffs: Array.isArray((safeObject(state.driverWorkflow)).billingHandoffs)
        ? state.driverWorkflow.billingHandoffs
        : [],
      documents: []
    };
    state.driverApp = safeObject(state.driverApp);
    state.driverApp.currentDriverId = nextDriverId;
    state.driverApp.activeTripId = "";
    state.driverApp.activeStage = "queued";
    state.driverApp.tripQueue = [];
    try {
      sessionStorage.removeItem("ops_driver_trip_cache_v1");
    } catch (_) {}
  }

  function resetDriverMobileAfterCompletion() {
    var mobileCtx = getCanonicalMobileDriverContext();
    clearDriverMobileWorkflowState({ driverId: mobileCtx.driverId || driverBoundDriverId || "" });
    state.driverApp.shiftOnline = true;
    state.driverApp.mobileUiState = mobileCtx.authenticated ? "awaiting_assignment" : "login_required";
    state.driverApp.lastStatusUpdate = mobileCtx.authenticated ? "Awaiting Assignment" : "Driver login required";
    syncDriverEarningsSummaryToApp(
      state.driverApp,
      safeObject((safeObject(state.driverWorkflow)).earnings),
      Array.isArray((safeObject(state.driverWorkflow)).completedRides) ? state.driverWorkflow.completedRides : [],
      Array.isArray((safeObject(state.driverWorkflow)).billingHandoffs) ? state.driverWorkflow.billingHandoffs : []
    );
    if (state.driverApp.lastActionResult) {
      state.driverApp.lastActionResult.current_ride_status = "completed";
    }
    persistMobileSurfacePreference("driver");
  }

  function resetDriverBoundIdentity() {
    driverBoundDriverId = "";
    driverLastConfirmedWorkflow = null;
    driverLastAppliedRefreshSeq = 0;
    try {
      localStorage.removeItem("amicor_driver_workflow_id");
    } catch (_) {}
  }

  function bindDriverIdentity(driverId, options) {
    var opts = options || {};
    if (isDriverMobileAppRoute()) {
      var sessionId = resolveCanonicalMobileDriverId();
      if (sessionId && opts.forceRebind !== true) {
        return sessionId;
      }
      if (opts.forceRebind === true) {
        var normalizedForce = safeText(driverId, "");
        if (normalizedForce) {
          driverBoundDriverId = normalizedForce;
          return normalizedForce;
        }
      }
      return sessionId || driverBoundDriverId || "";
    }
    var normalized = safeText(driverId, "");
    if (!normalized) return driverBoundDriverId || "";
    if (driverBoundDriverId && driverBoundDriverId !== normalized && opts.forceRebind !== true) {
      console.warn("[DriverPoll] driver_id rebind blocked", {
        bound: driverBoundDriverId,
        attempted: normalized
      });
      return driverBoundDriverId;
    }
    driverBoundDriverId = normalized;
    if (!isDriverMobileAppRoute()) {
      try {
        localStorage.setItem("amicor_driver_workflow_id", normalized);
      } catch (_) {}
    }
    return normalized;
  }

  async function resolveBoundDriverId(token, options) {
    var opts = options || {};
    if (isDriverMobileAppRoute()) {
      return resolveCanonicalMobileDriverId();
    }
    if (driverBoundDriverId && opts.forceRebind !== true) {
      return driverBoundDriverId;
    }
    try {
      var stored = safeText(localStorage.getItem("amicor_driver_workflow_id"), "");
      if (stored && opts.forceRebind !== true) {
        return bindDriverIdentity(stored);
      }
    } catch (_) {}
    var priorWorkflow = safeObject(state.driverWorkflow);
    var priorId = safeText(priorWorkflow.driverId, "");
    if (priorId && opts.forceRebind !== true) {
      return bindDriverIdentity(priorId);
    }
    var priorAppId = safeText((safeObject(state.driverApp)).currentDriverId, "");
    if (priorAppId && opts.forceRebind !== true) {
      return bindDriverIdentity(priorAppId);
    }
    var resolved = await resolveSessionDriverId(token);
    if (resolved) {
      return bindDriverIdentity(resolved);
    }
    return driverBoundDriverId || "";
  }

  function logDriverPoll(entry) {
    var payload = safeObject(entry);
    try {
      console.info("[DriverPoll]", payload);
      if (!Array.isArray(window.__amiDriverPollLog)) {
        window.__amiDriverPollLog = [];
      }
      window.__amiDriverPollLog.push(Object.assign({ ts: new Date().toISOString() }, payload));
      if (window.__amiDriverPollLog.length > 200) {
        window.__amiDriverPollLog = window.__amiDriverPollLog.slice(-200);
      }
    } catch (_) {}
  }

  function logDriverMobileAssignmentSync(entry) {
    if (!isDriverMobileSessionRoute()) return;
    var ctx = getCanonicalMobileDriverContext();
    var opts = safeObject(entry);
    var driverId = safeText(opts.authenticated_driver_id, ctx.driverId);
    if (!driverId) return;
    var priorUi = safeText((safeObject(state.driverApp)).mobileUiState, "");
    var nextUi = safeText(opts.next_ui_state, priorUi);
    var transition = safeText(opts.frontend_state_transition, "");
    if (!transition && nextUi && nextUi !== priorUi) {
      transition = priorUi ? (priorUi + "->" + nextUi) : nextUi;
    }
    var payload = {
      authenticated_driver_id: driverId,
      assignment_driver_id: safeText(opts.assignment_driver_id, "") || null,
      driver_session_id: safeText(opts.driver_session_id, ctx.sessionId),
      requested_ride_id: safeText(opts.requested_ride_id, "") || null,
      assignment_state: safeText(opts.assignment_state, "") || null,
      api_response: opts.api_response || null,
      frontend_state_transition: transition || null,
      http_status: opts.http_status == null ? null : opts.http_status,
      route: safeText(opts.route, "") || null,
      event: safeText(opts.event, "assignment_sync"),
      extra: opts.extra || null
    };
    try {
      console.info("[DriverMobileSync]", payload);
      if (!Array.isArray(window.__amiDriverMobileSyncLog)) {
        window.__amiDriverMobileSyncLog = [];
      }
      window.__amiDriverMobileSyncLog.push(Object.assign({ ts: new Date().toISOString() }, payload));
      if (window.__amiDriverMobileSyncLog.length > 300) {
        window.__amiDriverMobileSyncLog = window.__amiDriverMobileSyncLog.slice(-300);
      }
    } catch (_) {}
    var ingestUrl = "/api/health-isf/drivers/mobile-assignment-sync-log";
    try {
      fetch(ingestUrl, {
        method: "POST",
        headers: applyDriverSessionHeaders({
          Accept: "application/json",
          "Content-Type": "application/json"
        }, getAccessToken(), ingestUrl),
        credentials: "same-origin",
        body: JSON.stringify(payload),
        keepalive: true
      }).catch(function () {});
    } catch (_) {}
  }

  function logDriverMobileRefreshSync(options) {
    logDriverMobileAssignmentSync(safeObject(options));
  }

  function driverRefreshCollectTripIds(activeRidePayload, assignedRideRows, offerEnvelope) {
    var ids = [];
    function push(id) {
      var normalized = safeText(id, "");
      if (normalized && ids.indexOf(normalized) < 0) ids.push(normalized);
    }
    var activeRide = safeObject(activeRidePayload);
    if (activeRide.has_active_ride === true) {
      push(safeText((safeObject(activeRide.ride)).id, ""));
    }
    push(safeText((safeObject(offerEnvelope && offerEnvelope.offer)).ride_id, ""));
    (Array.isArray(assignedRideRows) ? assignedRideRows : []).forEach(function (row) {
      push(safeText(row.id || row.ride_id, ""));
    });
    return ids;
  }

  function driverRefreshWouldClearActiveTrip(priorTripId, activeRidePayload, assignedRideRows, offerEnvelope, completionSnapshot) {
    if (!priorTripId) return false;
    if (priorTripCompletedInSnapshot(priorTripId, completionSnapshot)) return false;
    var incomingIds = driverRefreshCollectTripIds(activeRidePayload, assignedRideRows || [], offerEnvelope);
    return incomingIds.indexOf(priorTripId) < 0;
  }

  function isOperationalExcludedRideMeta(name, pickup, dropoff, notes) {
    return isProofOrDemoTripMeta(name, pickup, dropoff, notes);
  }

  function filterOperationalRidesForHydration(rides) {
    return (Array.isArray(rides) ? rides : []).filter(function (ride) {
      return !isOperationalExcludedRideMeta(
        ride.passenger_name || ride.rider_name,
        ride.pickup_address || ride.pickup,
        ride.dropoff_address || ride.dropoff,
        ride.notes
      );
    });
  }

  function driverRefreshHasOpenAssignment(activeRidePayload, assignedRideRows, offerEnvelope) {
    var activeRide = safeObject(activeRidePayload);
    if (activeRide.has_active_ride === true && safeText((safeObject(activeRide.ride)).id, "")) {
      return true;
    }
    var offer = safeObject(offerEnvelope && offerEnvelope.offer);
    if (safeText(offer.ride_id, "")) {
      return true;
    }
    return Array.isArray(assignedRideRows) && assignedRideRows.some(function (row) {
      var status = normalizeRideStatusToken(row.lifecycle_state || row.status);
      return !isTerminalRideStatus(status);
    });
  }

  function priorDriverTripIdFromState() {
    var app = safeObject(state.driverApp);
    var wf = safeObject(state.driverWorkflow);
    var fromApp = safeText(app.activeTripId, "");
    if (fromApp) return fromApp;
    var activeRide = safeObject(wf.activeRide);
    return safeText((safeObject(activeRide.ride)).id, "");
  }

  function priorTripCompletedInSnapshot(priorTripId, completionSnapshot) {
    if (!priorTripId || !completionSnapshot) return false;
    var rows = Array.isArray(completionSnapshot.completed_rides) ? completionSnapshot.completed_rides : [];
    return rows.some(function (row) {
      return safeText(row.id || row.ride_id, "") === priorTripId;
    });
  }

  function markDriverSyncWarning(message) {
    state.fetchWarnings = dedupeWarnings((state.fetchWarnings || []).concat(["driver_sync_degraded"]));
    state.driverApp = safeObject(state.driverApp);
    state.driverApp.syncWarning = safeText(message, "Driver workspace synchronization delayed. Showing last confirmed trip.");
  }

  function clearDriverSyncWarning() {
    state.driverApp = safeObject(state.driverApp);
    state.driverApp.syncWarning = "";
  }

  function clearDriverMobileSyncError() {
    state.driverApp = safeObject(state.driverApp);
    state.driverApp.syncWarning = "";
    state.driverApp.mobileBootstrapError = "";
  }

  function recoverDriverMobileSyncUiState() {
    if (!isDriverMobileAppRoute() || !hasValidDriverMobileSession()) {
      return;
    }
    var appState = safeObject(state.driverApp);
    if (safeText(appState.mobileUiState, "") !== "api_error") {
      return;
    }
    var workflow = safeObject(state.driverWorkflow);
    var hasOpenAssignment = driverRefreshHasOpenAssignment(
      workflow.activeRide,
      Array.isArray(workflow.assignedRides) ? workflow.assignedRides : [],
      workflow.activeOffer
    );
    if (hasOpenAssignment) {
      clearDriverMobileSyncError();
      state.driverApp.mobileUiState = "active_ride";
      scheduleRenderPage({ immediate: true });
      return;
    }
    resetDriverMobileAfterCompletion();
    clearDriverMobileSyncError();
  }

  async function retryDriverMobileAssignmentSync() {
    clearDriverMobileSyncError();
    state.driverApp = safeObject(state.driverApp);
    state.driverApp.mobileUiState = "loading_assignment";
    scheduleRenderPage({ immediate: true });
    try {
      await refreshDriverWorkflowData({ forceReset: true });
    } catch (err) {
      state.driverApp = safeObject(state.driverApp);
      state.driverApp.mobileUiState = "api_error";
      state.driverApp.mobileBootstrapError = safeText(err && err.message, "driver_assignment_sync_failed");
      markDriverSyncWarning(state.driverApp.mobileBootstrapError);
    }
    recoverDriverMobileSyncUiState();
    scheduleRenderPage({ immediate: true });
  }

  var DRIVER_UI_RENDER_MS = 300;
  var DRIVER_MOBILE_LOGIN_TIMEOUT_MS = 45000;
  var DRIVER_MOBILE_BOOTSTRAP_TIMEOUT_MS = 90000;
  var DRIVER_MOBILE_FETCH_TIMEOUT_MS = 60000;
  var DRIVER_WORKSPACE_ROLES = ["driver", "admin", "dispatcher", "supervisor"];

  function hasValidDriverMobileSession() {
    var cached = driverMobileAuthCache;
    if (cached && cached.valid === true && safeText(cached.driver_id, "")) {
      if (isDriverMobileAppRoute()) {
        return !!safeText(cached.session_token, "");
      }
      return true;
    }
    var persisted = readPersistedDriverSession();
    if (!persisted || !persisted.driver_id) {
      return false;
    }
    if (isDriverMobileAppRoute()) {
      return !!safeText(persisted.session_token, "");
    }
    return true;
  }

  function isDriverWorkspaceRoute() {
    return state.route === "dashboard" || state.route === "mobile" || state.route === "drivers";
  }

  function canUseDriverWorkspaceActions() {
    if (!isDriverWorkspaceRoute()) return false;
    if (isDriverMobileSurface()) {
      return hasValidDriverMobileSession();
    }
    return DRIVER_WORKSPACE_ROLES.indexOf(state.role) >= 0;
  }

  function isDriverMobileSessionRoute() {
    return state.route === "mobile" || state.route === "drivers";
  }

  function isDriverMobileAppRoute() {
    return state.route === "mobile";
  }

  function isDriverMobileSurface() {
    return isDriverMobileAppRoute();
  }

  function isRiderDedicatedSurface() {
    return state.route === "riders";
  }

  function isRiderJwtRole(jwtRole) {
    var role = safeText(jwtRole, "").toLowerCase();
    return role === "rider" || role === "staff";
  }

  function isRiderSurfaceAuthenticated() {
    if (!getAccessToken()) {
      return false;
    }
    if (isRiderDedicatedSurface()) {
      return true;
    }
    return isRiderJwtRole(getJwtSessionRole());
  }

  function getRiderSurfaceIdentityName() {
    try {
      if (window.AmiCorSession && typeof window.AmiCorSession.getSessionProfile === "function") {
        var sessionProfile = window.AmiCorSession.getSessionProfile() || {};
        var profileName = safeText(sessionProfile.displayName, "");
        if (profileName) {
          return profileName;
        }
      }
      if (window.AmiCorSession && typeof window.AmiCorSession.getCurrent === "function") {
        var current = window.AmiCorSession.getCurrent() || {};
        var identity = safeObject(current.identity);
        var identityName = safeText(identity.name || identity.display_name, "");
        if (identityName) {
          return identityName;
        }
      }
    } catch (_) {}
    return "";
  }

  function getRiderSurfacePresentation() {
    var jwtRole = getJwtSessionRole();
    var riderProfile = ROLE_PROFILE.rider;
    if (!isRiderSurfaceAuthenticated()) {
      return {
        displayName: "Signed Out",
        displaySubrole: "Rider",
        badgeRole: "rider",
        profile: riderProfile
      };
    }
    if (jwtRole === "staff") {
      return {
        displayName: getRiderSurfaceIdentityName() || "Rider Staff",
        displaySubrole: "Rider Staff",
        badgeRole: "rider",
        profile: riderProfile
      };
    }
    return {
      displayName: getRiderSurfaceIdentityName() || "Rider",
      displaySubrole: "Rider",
      badgeRole: "rider",
      profile: riderProfile
    };
  }

  function wrapDriverMobilePage(bodyHtml) {
    return '<div class="driver-mobile-page">' + String(bodyHtml || "") + '</div>';
  }

  function applyDriverMobileShellLayout(enabled) {
    document.body.classList.toggle("driver-mobile-app", !!enabled);
  }

  function applyDedicatedSurfaceLayout() {
    applyDriverMobileShellLayout(isDriverMobileAppRoute());
    document.body.classList.toggle("rider-app-surface", state.route === "riders");
  }

  function getPlatformRole() {
    return ROLE_ACCESS[state.role] ? state.role : "admin";
  }

  function initializePlatformRole(pathRoute) {
    var platformRole = "";
    try {
      platformRole = safeText(localStorage.getItem(PLATFORM_ROLE_KEY), "");
    } catch (_) {}
    if (platformRole && ROLE_ACCESS[platformRole]) {
      return platformRole;
    }
    var legacyRole = "admin";
    try {
      var raw = localStorage.getItem("amicor_shell_role") || "admin";
      legacyRole = ROLE_ACCESS[raw] ? raw : "admin";
    } catch (_) {}
    if (legacyRole === "driver" && pathRoute !== "mobile" && pathRoute !== "drivers") {
      legacyRole = "admin";
    }
    savePlatformRole(legacyRole);
    return legacyRole;
  }

  function normalizeDriverLoginPhone(raw) {
    var digits = safeText(raw, "").replace(/[^\d+]/g, "");
    if (!digits) return "";
    if (digits.charAt(0) !== "+") {
      digits = digits.replace(/^\+/, "");
    }
    if (digits.length === 10) {
      return digits.slice(0, 3) + "-" + digits.slice(3, 6) + "-" + digits.slice(6);
    }
    if (digits.length === 11 && digits.charAt(0) === "1") {
      return digits.slice(1, 4) + "-" + digits.slice(4, 7) + "-" + digits.slice(7);
    }
    return safeText(raw, "").trim();
  }

  function syncDriverMobilePhoneState(rawPhone) {
    state.driverApp = safeObject(state.driverApp);
    state.driverApp.mobileLogin = safeObject(state.driverApp.mobileLogin);
    state.driverApp.mobileLogin.phone = normalizeDriverLoginPhone(rawPhone);
    return state.driverApp.mobileLogin.phone;
  }

  function readDriverMobilePhoneInput() {
    var phoneInput = document.getElementById("driver-mobile-phone");
    var fromDom = safeText(phoneInput && phoneInput.value, "").trim();
    if (fromDom) {
      return syncDriverMobilePhoneState(fromDom);
    }
    var fromState = safeText((safeObject(state.driverApp)).mobileLogin && state.driverApp.mobileLogin.phone, "").trim();
    return normalizeDriverLoginPhone(fromState);
  }

  function scheduleRenderPage(options) {
    var opts = options || {};
    if (opts.immediate) {
      if (driverUiRenderTimer) {
        clearTimeout(driverUiRenderTimer);
        driverUiRenderTimer = null;
      }
      renderPage();
      return;
    }
    if (driverUiRenderTimer) {
      clearTimeout(driverUiRenderTimer);
    }
    var delay = isDriverMobileSurface() ? DRIVER_UI_RENDER_MS : 60;
    driverUiRenderTimer = setTimeout(function () {
      driverUiRenderTimer = null;
      renderPage();
    }, delay);
  }

  function lockDriverHydration(ms) {
    driverHydrateLockUntil = Date.now() + Math.max(500, Number(ms) || 2500);
  }

  function isDriverHydrationLocked() {
    return Date.now() < driverHydrateLockUntil;
  }
  var refreshInFlight = false;
  var eventsBound = false;
  var windowEventBindings = [];
  var documentEventBindings = [];
  var navEventBindings = [];
  var roleSelectChangeHandler = null;
  var runtimeUpdateHandler = null;
  window.__amiDispatcherDraftRenderDeferred = false;

  var SESSION_STATE_KEY = "amicor_shell_session_v1";
  var PLATFORM_ROLE_KEY = "amicor_platform_role";
  var PLATFORM_RESET_EPOCH_KEY = "amicor_platform_reset_epoch_v1";
  var USER_ACTIVITY_COOLDOWN_MS = 5000;
  var REFRESH_TRIGGER_COOLDOWN_MS = 2500;
  var STABLE_POLL_INTERVAL_MS = 30000;
  var DRIVER_AWAITING_POLL_INTERVAL_MS = 5000;
  var BACKEND_DOWN_PAUSE_MS = 60000;
  var MAX_BACKEND_DOWN_RETRY_BEFORE_PAUSE = 2;
  var ENTERPRISE_HYDRATION_TIMEOUT_MS = 45000;
  var SESSION_READY_TIMEOUT_MS = 8000;
  var AI_SNAPSHOT_TIMEOUT_MS = 8000;
  var RIDER_SUBMIT_TIMEOUT_MS = 60000;
  var RIDER_RECOVERY_MAX_ATTEMPTS = 30;
  var RIDER_RECOVERY_POLL_MS = 2000;

  var els = {
    pageTitle: document.getElementById("page-title"),
    pageSubtitle: document.getElementById("page-subtitle"),
    pageContent: document.getElementById("page-content"),
    roleSelect: document.getElementById("role-select"),
    roleBadge: document.getElementById("role-badge"),
    roleContext: document.getElementById("role-context"),
    connectionBadge: document.getElementById("connection-badge"),
    workspacePill: document.getElementById("workspace-pill"),
    notificationPill: document.getElementById("notification-pill"),
    navLinks: Array.prototype.slice.call(document.querySelectorAll(".ops-nav a[data-route]"))
  };

  function escapeHtml(value) {
    return String(value == null ? "" : value)
      .replace(/&/g, "&amp;")
      .replace(/</g, "&lt;")
      .replace(/>/g, "&gt;")
      .replace(/\"/g, "&quot;")
      .replace(/'/g, "&#39;");
  }

  function setHtmlIfChanged(el, html) {
    if (!el) return false;
    if (el.__stableHtml === html) return false;
    el.__stableHtml = html;
    el.innerHTML = html;
    return true;
  }

  function syncPageContentHtml(el, html) {
    if (!el) return;
    el.__stableHtml = html;
    el.innerHTML = html;
  }

  function formatIsoShort(ts) {
    if (!ts) return "";
    try {
      var d = new Date(ts);
      if (isNaN(d.getTime())) return String(ts);
      return d.toLocaleTimeString([], { hour: "2-digit", minute: "2-digit", second: "2-digit" });
    } catch (_) {
      return String(ts);
    }
  }

  function computePageDataSignature() {
    var lw = state.liveWorkflow || {};
    var ops = state.ops || {};
    var liveEvents = ops.orchestration && ops.orchestration.live_stream && Array.isArray(ops.orchestration.live_stream.events)
      ? ops.orchestration.live_stream.events
      : [];
    var rideSig = (lw.rides || []).slice(0, 25).map(function (row) {
      return safeText(row.id, "") + ":" + safeText(row.status, "");
    }).join("|");
    return [
      safeText(state.route, "dashboard"),
      safeText(state.role, "admin"),
      state.loading ? "1" : "0",
      safeText(state.error, ""),
      String((state.fetchWarnings || []).length),
      String((lw.dispatchQueue || []).length),
      String((lw.activeAssignments || []).length),
      String((lw.drivers || []).length),
      String((lw.rides || []).length),
      String((Array.isArray(lw.billingHandoffs) ? lw.billingHandoffs : []).length),
      String((state.adminRevenue && state.adminRevenue.completed_trip_count) || 0),
      safeText((safeObject(state.driverApp)).secondaryTab, "earnings"),
      safeText((safeObject(state.driverApp)).mobileUiState, ""),
      hasValidDriverMobileSession() ? "session" : "anon",
      rideSig,
      safeText((state.supervision || {}).supervision_status, ""),
      safeText((state.health || {}).status, ""),
      String(liveEvents.length),
    ].join("§");
  }

  function updateLastUpdatedLabel() {
    var lu = safeText((state.hydration || {}).lastUpdatedAt, "");
    var routeMeta = ROUTES[state.route] || ROUTES.dashboard;
    var subtitle = routeMeta.subtitle;
    if (lu) {
      subtitle += " · Last sync " + formatIsoShort(lu);
    }
    if (els.pageSubtitle) {
      if (els.pageSubtitle.__stableText !== subtitle) {
        els.pageSubtitle.__stableText = subtitle;
        els.pageSubtitle.textContent = subtitle;
      }
    }
    var lastUpdatedPill = document.getElementById("last-updated-pill");
    if (lastUpdatedPill) {
      var pillText = lu ? "updated " + formatIsoShort(lu) : "updated —";
      if (lastUpdatedPill.__stableText !== pillText) {
        lastUpdatedPill.__stableText = pillText;
        lastUpdatedPill.textContent = pillText;
      }
    }
  }

  function safeNumber(value, fallback) {
    var numeric = Number(value);
    if (Number.isFinite(numeric)) {
      return numeric;
    }
    return fallback;
  }

  function safeText(value, fallback) {
    if (value == null) {
      return fallback;
    }
    var text = String(value).trim();
    return text ? text : fallback;
  }

  function shortOperationalId(value, fallback) {
    var text = safeText(value, fallback || "n/a");
    if (/^[0-9a-f]{8}-[0-9a-f]{4}-[1-5][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/i.test(text)) {
      return text.slice(0, 8).toUpperCase();
    }
    return text;
  }

  function formatOperationalTime(value) {
    var raw = safeText(value, "");
    if (!raw) {
      return "Awaiting update";
    }
    var parsed = Date.parse(raw);
    if (!Number.isFinite(parsed)) {
      return raw;
    }
    try {
      return new Date(parsed).toLocaleString([], {
        month: "short",
        day: "2-digit",
        hour: "2-digit",
        minute: "2-digit"
      });
    } catch (_err) {
      return raw;
    }
  }

  function operationalTimeValue(value) {
    var raw = safeText(value, "");
    if (!raw) {
      return 0;
    }
    var parsed = Date.parse(raw);
    return Number.isFinite(parsed) ? parsed : 0;
  }

  function safeObject(value) {
    return value && typeof value === "object" ? value : {};
  }

  function isOperatorModeEnabled() {
    try {
      var query = new URLSearchParams(String(window.location.search || ""));
      var queryOverride = String(query.get("operator_mode") || "").toLowerCase();
      var storageOverride = String(localStorage.getItem("amicor_operator_mode") || "").toLowerCase();
      if (queryOverride === "false" || queryOverride === "0" || queryOverride === "off") return false;
      if (storageOverride === "false" || storageOverride === "0" || storageOverride === "off") return false;
      return true;
    } catch (_) {
      return true;
    }
  }

  function markUserActivity(source) {
    state.runtime.lastUserActivityAt = Date.now();
    state.runtime.lastNavigationSource = safeText(source, state.runtime.lastNavigationSource || "activity");
  }

  function shouldThrottleRefreshTrigger(source) {
    var now = Date.now();
    var triggerSource = safeText(source, "unknown");
    if (state.runtime.refreshPausedUntilMs > now) {
      state.fetchWarnings = dedupeWarnings((state.fetchWarnings || []).concat(["backend_refresh_paused"]));
      return true;
    }
    if (triggerSource === "interval" && (now - safeNumber(state.runtime.lastRefreshTriggerAt, 0)) < STABLE_POLL_INTERVAL_MS - 500) {
      return true;
    }
    if (triggerSource !== "interval" && state.runtime.lastRefreshTriggerSource === triggerSource
      && (now - safeNumber(state.runtime.lastRefreshTriggerAt, 0)) < REFRESH_TRIGGER_COOLDOWN_MS) {
      return true;
    }
    state.runtime.lastRefreshTriggerAt = now;
    state.runtime.lastRefreshTriggerSource = triggerSource;
    return false;
  }

  function normalizeAuditRecord(input) {
    var item = safeObject(input);
    var detail = safeText(item.detail, safeText(item.message, "No detail provided."));
    var timestamp = safeText(item.timestamp, safeText(item.created_at, ""));
    var signature = safeText(item.signature, safeText(item.event_id, safeText(timestamp, "sig-missing")));
    var payload = safeObject(item.payload);
    var eventType = safeText(item.type, "event");
    return {
      id: safeText(item.id, safeText(item.event_id, "")),
      event_id: safeText(item.event_id, ""),
      type: eventType,
      event_type: safeText(item.event_type, eventType),
      event_name: safeText(item.event_name, "event"),
      status: safeText(item.status, "info"),
      detail: detail,
      timestamp: timestamp,
      signature: signature,
      session_id: safeText(item.session_id, ""),
      route: safeText(item.route, ""),
      correlation_id: safeText(item.correlation_id, ""),
      payload: payload,
      memory_type: safeText(item.memory_type, "memory"),
      updated_at: safeText(item.updated_at, ""),
      error_message: safeText(item.error_message, "")
    };
  }

  function normalizeExecutionRecord(input) {
    var item = safeObject(input);
    var status = safeText(item.status, safeText(item.state, "pending"));
    return {
      execution_id: safeText(item.execution_id, safeText(item.id, "")),
      intent_id: safeText(item.intent_id, safeText(item.request_id, "")),
      action_type: safeText(item.action_type, safeText(item.intent, "preview")),
      status: status,
      correlation_id: safeText(item.correlation_id, ""),
      queued_at: safeText(item.queued_at, safeText(item.created_at, "")),
      started_at: safeText(item.started_at, ""),
      completed_at: safeText(item.completed_at, safeText(item.updated_at, "")),
      failed_at: safeText(item.failed_at, ""),
      error_message: safeText(item.error_message, safeText(item.error, ""))
    };
  }

  function normalizeMemoryRecord(input) {
    var item = safeObject(input);
    return {
      id: safeText(item.id, safeText(item.memory_id, "")),
      title: safeText(item.title, safeText(item.name, "memory")),
      memory_type: safeText(item.memory_type, safeText(item.type, "memory")),
      role: safeText(item.role, safeText(item.actor_role, "unknown")),
      session_id: safeText(item.session_id, ""),
      created_at: safeText(item.created_at, safeText(item.timestamp, "")),
      updated_at: safeText(item.updated_at, ""),
      content: safeObject(item.content)
    };
  }

  function normalizePreviewPayload(payload) {
    var item = safeObject(payload);
    item.preview_card = safeObject(item.preview_card);
    item.confirmation_verification = safeObject(item.confirmation_verification);
    item.security_state = safeObject(item.security_state);
    item.governance = safeObject(item.governance);
    item.workflow_execution = safeObject(item.workflow_execution);
    item.integrity = safeObject(item.integrity);
    return item;
  }

  function roleFromStorage() {
    try {
      var platformRaw = localStorage.getItem(PLATFORM_ROLE_KEY);
      if (platformRaw && ROLE_ACCESS[platformRaw]) {
        return platformRaw;
      }
      var raw = localStorage.getItem("amicor_shell_role") || "admin";
      return ROLE_ACCESS[raw] ? raw : "admin";
    } catch (_) {
      return "admin";
    }
  }

  function roleFromOperationalPath(pathname) {
    var normalizedPath = safeText(pathname, "");
    if (normalizedPath.length > 1 && normalizedPath.charAt(normalizedPath.length - 1) === "/") {
      normalizedPath = normalizedPath.slice(0, -1);
    }
    var prefix = APP_BASE_PATH + "/operations/";
    if (normalizedPath.indexOf(prefix) !== 0) {
      return "";
    }
    var slug = normalizedPath.slice(prefix.length).toLowerCase();
    return OPERATIONAL_PATH_TO_ROLE[slug] || "";
  }

  function routePathForRole(route, role) {
    if (route === "dashboard" && ROLE_OPERATIONAL_PATHS[role]) {
      return ROLE_OPERATIONAL_PATHS[role];
    }
    return safeText((ROUTES[route] || {}).path, ROUTES.dashboard.path);
  }

  function defaultRouteForRole(role) {
    return ROLE_DEFAULT_ROUTE[role] || "dashboard";
  }

  function savePlatformRole(role) {
    var nextRole = ROLE_ACCESS[role] ? role : "admin";
    try {
      localStorage.setItem(PLATFORM_ROLE_KEY, nextRole);
      localStorage.setItem("amicor_shell_role", nextRole);
    } catch (_) {}
    return nextRole;
  }

  var AUTH_SYNC_PLATFORM_ROLES = {
    admin: "admin",
    dispatcher: "dispatcher",
    supervisor: "supervisor",
    staff: "staff",
    rider: "rider",
    provider: "provider",
    driver: "driver",
    compliance_officer: "compliance_officer",
    driver_support: "driver_support",
    medical_coordinator: "medical_coordinator"
  };

  function getJwtSessionRole() {
    try {
      if (window.AmiCorSession && typeof window.AmiCorSession.getRole === "function") {
        return safeText(window.AmiCorSession.getRole(), "").toLowerCase();
      }
    } catch (_) {}
    return "";
  }

  function resolveAuthRoleForPlatformRole(platformRole) {
    var key = safeText(platformRole, "").toLowerCase();
    return AUTH_SYNC_PLATFORM_ROLES[key] || key;
  }

  function syncPlatformRoleAuth(platformRole) {
    if (isRiderDedicatedSurface() || dedicatedRouteFromPath(window.location.pathname) === "riders") {
      return Promise.resolve(false);
    }
    var authRole = resolveAuthRoleForPlatformRole(platformRole);
    if (!authRole || !getAccessToken()) {
      return Promise.resolve(false);
    }
    if (getJwtSessionRole() === authRole) {
      return Promise.resolve(true);
    }
    if (!(window.AmiCorSession && typeof window.AmiCorSession.switchWorkspaceRole === "function")) {
      return Promise.resolve(false);
    }
    return window.AmiCorSession.switchWorkspaceRole(authRole).then(function () {
      return true;
    }).catch(function (error) {
      console.warn("[ops-shell] workspace role sync failed", error);
      return false;
    });
  }

  function saveRole(role) {
    savePlatformRole(role);
  }

  function getRoleWorkspaceConfig(role) {
    var modules = window.AmiRoleWorkspaces;
    if (!modules || typeof modules !== "object") {
      return {};
    }
    var roleConfig = modules[role];
    if (!roleConfig || typeof roleConfig !== "object") {
      return {};
    }
    return roleConfig;
  }

  function roleWorkspaceLinks(role, key, fallbackLinks) {
    var roleConfig = getRoleWorkspaceConfig(role);
    var configured = roleConfig[key];
    if (Array.isArray(configured) && configured.length > 0) {
      return configured;
    }
    return fallbackLinks;
  }

  function roleNavigationOrder(role) {
    var navConfig = window.AmiRoleNavigation;
    if (!navConfig || typeof navConfig !== "object") {
      return [];
    }
    var order = navConfig[role];
    return Array.isArray(order) ? order : [];
  }

  function lifecycleSnapshot() {
    if (window.AmiTripLifecycle && typeof window.AmiTripLifecycle.getSnapshot === "function") {
      return window.AmiTripLifecycle.getSnapshot();
    }
    return null;
  }

  function dispatchSnapshot() {
    if (window.AmiDispatchRuntime && typeof window.AmiDispatchRuntime.snapshot === "function") {
      return window.AmiDispatchRuntime.snapshot();
    }
    return lifecycleSnapshot();
  }

  function notificationsForRole(role, limit) {
    if (window.AmiNotificationsEngine && typeof window.AmiNotificationsEngine.get === "function") {
      return window.AmiNotificationsEngine.get(role, limit || 12);
    }
    return [];
  }

  function minutesAgoIso(minutes) {
    return new Date(Date.now() - (safeNumber(minutes, 0) * 60000)).toISOString();
  }

  function minutesAheadIso(minutes) {
    return new Date(Date.now() + (safeNumber(minutes, 0) * 60000)).toISOString();
  }

  function buildDemoTransportRecords() {
    return [
      {
        trip_id: "TRIP-6201",
        patient_name: "Helen Morris",
        pickup: "Riverbend Dialysis Center",
        dropoff: "Oakridge Senior Living",
        priority: "high",
        trip_state: "requested",
        route_status: "intake_review",
        requested_at: minutesAgoIso(18),
        sla_target_minutes: 30,
        eta_minutes: 20,
        transport_type: "dialysis_recurring",
        appointment_window: "08:30 - 09:00",
        coordination_note: "Recurring dialysis return-home transport."
      },
      {
        trip_id: "TRIP-6202",
        patient_name: "Daniel Ortega",
        pickup: "St. Anne Hospital Discharge Bay",
        dropoff: "Pinecrest Rehabilitation",
        priority: "urgent",
        trip_state: "assigned",
        route_status: "driver_assignment_confirmed",
        requested_at: minutesAgoIso(24),
        sla_target_minutes: 25,
        assigned_driver_name: "D. Patel",
        eta_minutes: 14,
        transport_type: "hospital_discharge",
        appointment_window: "09:15 - 09:45",
        coordination_note: "Wheelchair discharge with nurse handoff notes attached."
      },
      {
        trip_id: "TRIP-6203",
        patient_name: "Iris Bennett",
        pickup: "Cedar Grove Rural Clinic",
        dropoff: "Summit Imaging Center",
        priority: "high",
        trip_state: "driver_en_route",
        route_status: "rural_pickup_en_route",
        requested_at: minutesAgoIso(32),
        sla_target_minutes: 40,
        assigned_driver_name: "L. Johnson",
        eta_minutes: 11,
        transport_type: "rural_pickup",
        appointment_window: "10:00 - 10:30",
        coordination_note: "Rural pickup route requires bridge traffic bypass."
      },
      {
        trip_id: "TRIP-6204",
        patient_name: "Noah Williams",
        pickup: "Valley Orthopedics",
        dropoff: "Meadowview Assisted Home",
        priority: "medium",
        trip_state: "patient_onboard",
        route_status: "onboard_confirmed",
        requested_at: minutesAgoIso(39),
        sla_target_minutes: 35,
        assigned_driver_name: "T. Nguyen",
        eta_minutes: 17,
        transport_type: "wheelchair_transport",
        appointment_window: "11:00 - 11:30",
        coordination_note: "Wheelchair securement verified at pickup."
      },
      {
        trip_id: "TRIP-6205",
        patient_name: "Leah Carter",
        pickup: "Mercy Cardiology",
        dropoff: "Willow Creek Residence",
        priority: "medium",
        trip_state: "in_transit",
        route_status: "facility_route_active",
        requested_at: minutesAgoIso(46),
        sla_target_minutes: 45,
        assigned_driver_name: "M. Shah",
        eta_minutes: 9,
        transport_type: "return_home",
        appointment_window: "11:30 - 12:00",
        coordination_note: "Return-home ride with pharmacy stop removed per provider request."
      },
      {
        trip_id: "TRIP-6206",
        patient_name: "Peter Reeves",
        pickup: "North County Dialysis",
        dropoff: "Elm Street Home Care",
        priority: "low",
        trip_state: "arrived_at_facility",
        route_status: "facility_arrival_confirmed",
        requested_at: minutesAgoIso(58),
        sla_target_minutes: 50,
        assigned_driver_name: "K. Brooks",
        eta_minutes: 0,
        transport_type: "dialysis_return_home",
        appointment_window: "07:45 - 08:15",
        coordination_note: "Facility arrival pending handoff signature upload."
      },
      {
        trip_id: "TRIP-6207",
        patient_name: "Mina Lopez",
        pickup: "Regional Oncology Center",
        dropoff: "Harborview Apartments",
        priority: "low",
        trip_state: "completed",
        route_status: "transport_completed",
        requested_at: minutesAgoIso(75),
        completed_at: minutesAgoIso(22),
        sla_target_minutes: 55,
        assigned_driver_name: "A. Walker",
        eta_minutes: 0,
        transport_type: "recurring_patient_ride",
        appointment_window: "08:00 - 08:30",
        coordination_note: "Completed with home-entry assistance documented."
      },
      {
        trip_id: "TRIP-6208",
        patient_name: "Ruth Simmons",
        pickup: "Pioneer Rural Health Outpost",
        dropoff: "County General Hospital",
        priority: "urgent",
        trip_state: "escalated",
        route_status: "driver_shortage_escalated",
        requested_at: minutesAgoIso(52),
        sla_target_minutes: 30,
        eta_minutes: 0,
        transport_type: "rural_emergency_transfer",
        appointment_window: "Immediate",
        coordination_note: "No local driver available; supervisor escalation initiated."
      }
    ];
  }

  function buildDemoDriverAvailability() {
    return [
      { driver_id: "DRV-101", driver_name: "D. Patel", vehicle: "Wheelchair Van 12", status: "assigned", next_eta_minutes: 14 },
      { driver_id: "DRV-087", driver_name: "L. Johnson", vehicle: "Rural Unit 04", status: "busy", next_eta_minutes: 11 },
      { driver_id: "DRV-054", driver_name: "M. Shah", vehicle: "Sedan Med 07", status: "assigned", next_eta_minutes: 9 },
      { driver_id: "DRV-031", driver_name: "K. Brooks", vehicle: "Lift Van 03", status: "available", next_eta_minutes: 6 }
    ];
  }

  function buildDemoEscalationSignals() {
    return [
      { trip_id: "TRIP-6208", indicator: "Rural pickup risk", priority: "high", state: "active" },
      { trip_id: "TRIP-6202", indicator: "Discharge handoff delay", priority: "medium", state: "watch" }
    ];
  }

  function buildDemoReassignmentQueue() {
    return [
      { trip_id: "TRIP-6210", rider_name: "Aaron Mills", assignment_status: "driver_declined", assigned_driver_name: "unassigned" },
      { trip_id: "TRIP-6211", rider_name: "Nina Patel", assignment_status: "timeout_reassignment", assigned_driver_name: "unassigned" }
    ];
  }

  function buildDemoNoDriverRecovery() {
    return [
      { trip_id: "TRIP-6208", rider_name: "Ruth Simmons", trip_state: "escalated", transport_risk_indicators: ["rural_coverage_gap", "critical_window"] }
    ];
  }

  function buildDemoSupervisorApprovals() {
    return [
      { id: "APV-903", action_type: "escalation_override", actor_role: "dispatcher", priority: "high", created_at: minutesAgoIso(19) },
      { id: "APV-904", action_type: "manual_assignment_approval", actor_role: "driver_support", priority: "medium", created_at: minutesAgoIso(25) },
      { id: "APV-905", action_type: "rural_route_exception", actor_role: "operations", priority: "high", created_at: minutesAgoIso(33) }
    ];
  }

  function buildDemoSupervisorRecoveryQueue() {
    return [
      { trip_id: "TRIP-6208", rider_name: "Ruth Simmons", trip_state: "escalated", transport_risk_indicators: ["driver_unavailable", "rural_transfer"] },
      { trip_id: "TRIP-6212", rider_name: "Gavin Cole", trip_state: "pending_supervisor_review", transport_risk_indicators: ["facility_delay"] }
    ];
  }

  function buildDemoSupervisorResolutionTimeline() {
    return [
      { trip_id: "TRIP-6208", action: "Escalated", trip_state: "escalated", authority_source: "dispatcher", timestamp: minutesAgoIso(28) },
      { trip_id: "TRIP-6208", action: "Supervisor Reviewed", trip_state: "supervisor_reviewed", authority_source: "supervisor", timestamp: minutesAgoIso(21) },
      { trip_id: "TRIP-6208", action: "Manual Reassignment", trip_state: "assigned", authority_source: "supervisor", timestamp: minutesAgoIso(17) },
      { trip_id: "TRIP-6208", action: "Resolution Confirmed", trip_state: "resolved", authority_source: "operations", timestamp: minutesAgoIso(11) }
    ];
  }

  function buildDefaultAssistantMessages() {
    return [
      {
        id: "msg-system-1",
        type: "system",
        title: "Assistant workspace ready",
        text: "Monitoring-first interaction is enabled. Responses stay in the current operational session and remain view-only.",
        timestamp: new Date().toISOString()
      }
    ];
  }

  function buildDefaultAssistantState() {
    var nonce = "sess-" + Date.now() + "-" + Math.floor(Math.random() * 1000000);
    return {
      runtimeState: "monitoring",
      isResponding: false,
      draft: "",
      pendingPrompt: "",
      messages: buildDefaultAssistantMessages(),
      toolEvents: [
        {
          id: "tool-info-1",
          status: "informational",
          label: "Workspace initialized",
          detail: "Local review mode active. No direct action requests are sent.",
          timestamp: new Date().toISOString()
        }
      ],
      previewCards: [],
      pendingIntent: null,
      auditEvents: [],
      executionHistory: [],
      memoryEntries: [],
      sessionNonce: nonce,
      securityState: {
        verifiedPreview: false,
        signedConfirmation: false,
        tokenExpiresInSeconds: 0,
        dryRunOnly: true,
        executionDisabled: true,
        supervisionEnforced: true,
        durableVerifiedPreview: false,
        auditChainActive: false,
        distributedReplayProtection: false,
        policyVersion: "unknown",
        correlationId: ""
      },
      collapsible: {
        memory: false,
        tools: false,
        audit: false,
        preview: false,
        session: false,
        history: false,
        execution: false,
        persistent: false
      }
    };
  }

  function parseSessionState() {
    try {
      var raw = sessionStorage.getItem(SESSION_STATE_KEY);
      if (!raw) return null;
      var parsed = JSON.parse(raw);
      if (!parsed || typeof parsed !== "object") {
        return null;
      }
      return parsed;
    } catch (_) {
      return null;
    }
  }

  function hydrateSessionState() {
    var parsed = parseSessionState();
    if (!parsed) return;

    if (parsed.platformRole && ROLE_ACCESS[parsed.platformRole]) {
      state.role = parsed.platformRole;
      savePlatformRole(parsed.platformRole);
    }

    if (parsed.roleRoutes && typeof parsed.roleRoutes === "object") {
      Object.keys(state.roleRoutes).forEach(function (roleKey) {
        var candidate = safeText(parsed.roleRoutes[roleKey], "");
        if (candidate && routeAllowed(roleKey, candidate)) {
          state.roleRoutes[roleKey] = candidate;
        }
      });
    }

    var parsedRoute = safeText(parsed.route, "");
    var pathLockedRoute = dedicatedRouteFromPath(window.location.pathname);
    if (pathLockedRoute) {
      state.route = pathLockedRoute;
      state.roleRoutes[state.role] = pathLockedRoute;
    } else if (parsedRoute && routeAllowed(state.role, parsedRoute)) {
      state.route = parsedRoute;
      state.roleRoutes[state.role] = parsedRoute;
    }

    if (parsed.runtime && typeof parsed.runtime === "object") {
      state.runtime.operatorMode = parsed.runtime.operatorMode !== false;
      state.runtime.reconnectCount = safeNumber(parsed.runtime.reconnectCount, 0);
      state.runtime.lastReconnectReason = safeText(parsed.runtime.lastReconnectReason, "none");
      state.runtime.lastNavigationSource = safeText(parsed.runtime.lastNavigationSource, "init");
      state.runtime.lastRenderTimestamp = safeText(parsed.runtime.lastRenderTimestamp, "");
      state.runtime.backendHealth = safeText(parsed.runtime.backendHealth, "unknown");
    }

    var assistantState = parsed.assistant || {};
    if (assistantState && typeof assistantState === "object") {
      state.assistant.runtimeState = safeText(assistantState.runtimeState, "monitoring");
      state.assistant.draft = safeText(assistantState.draft, "");
      state.assistant.pendingPrompt = safeText(assistantState.pendingPrompt, "");
      state.assistant.isResponding = false;
      if (Array.isArray(assistantState.messages) && assistantState.messages.length > 0) {
        state.assistant.messages = assistantState.messages.slice(-24);
      }
      if (Array.isArray(assistantState.toolEvents)) {
        state.assistant.toolEvents = assistantState.toolEvents.slice(-24);
      }
      if (Array.isArray(assistantState.previewCards)) {
        state.assistant.previewCards = assistantState.previewCards.slice(-12);
      }
      if (Array.isArray(assistantState.auditEvents)) {
        state.assistant.auditEvents = assistantState.auditEvents.slice(-48).map(normalizeAuditRecord);
      }
      if (Array.isArray(assistantState.executionHistory)) {
        state.assistant.executionHistory = assistantState.executionHistory.slice(-16).map(normalizeExecutionRecord);
      }
      if (Array.isArray(assistantState.memoryEntries)) {
        state.assistant.memoryEntries = assistantState.memoryEntries.slice(-20).map(normalizeMemoryRecord);
      }
      if (assistantState.securityState && typeof assistantState.securityState === "object") {
        state.assistant.securityState = {
          verifiedPreview: Boolean(assistantState.securityState.verifiedPreview),
          signedConfirmation: Boolean(assistantState.securityState.signedConfirmation),
          tokenExpiresInSeconds: safeNumber(assistantState.securityState.tokenExpiresInSeconds, 0),
          dryRunOnly: assistantState.securityState.dryRunOnly !== false,
          executionDisabled: assistantState.securityState.executionDisabled !== false,
          supervisionEnforced: assistantState.securityState.supervisionEnforced !== false,
          durableVerifiedPreview: Boolean(assistantState.securityState.durableVerifiedPreview),
          auditChainActive: Boolean(assistantState.securityState.auditChainActive),
          distributedReplayProtection: Boolean(assistantState.securityState.distributedReplayProtection),
          policyVersion: safeText(assistantState.securityState.policyVersion, "unknown"),
          correlationId: safeText(assistantState.securityState.correlationId, "")
        };
      }
      if (assistantState.pendingIntent && typeof assistantState.pendingIntent === "object") {
        state.assistant.pendingIntent = {
          intent: safeText(assistantState.pendingIntent.intent, "preview"),
          status: safeText(assistantState.pendingIntent.status, "awaiting_confirmation"),
          prompt: safeText(assistantState.pendingIntent.prompt, ""),
          policy: assistantState.pendingIntent.policy || null,
          createdAt: safeText(assistantState.pendingIntent.createdAt, new Date().toISOString())
        };
      } else {
        state.assistant.pendingIntent = null;
      }
      state.assistant.sessionNonce = safeText(assistantState.sessionNonce, state.assistant.sessionNonce || ("sess-" + Date.now()));
      var collapsible = assistantState.collapsible || {};
      state.assistant.collapsible = {
        memory: Boolean(collapsible.memory),
        tools: Boolean(collapsible.tools),
        audit: Boolean(collapsible.audit),
        preview: Boolean(collapsible.preview),
        session: Boolean(collapsible.session),
        history: Boolean(collapsible.history),
        execution: Boolean(collapsible.execution),
        persistent: Boolean(collapsible.persistent)
      };
    }

    var riderAppState = parsed.riderApp || {};
    if (riderAppState && typeof riderAppState === "object") {
      state.riderApp = safeObject(state.riderApp);
      state.riderApp.profile = safeObject(riderAppState.profile);
      state.riderApp.activeRequestId = safeText(riderAppState.activeRequestId, "");
      state.riderApp.lastSubmit = safeObject(riderAppState.lastSubmit);
    }
  }

  function persistSessionState() {
    try {
      var payload = {
        role: getPlatformRole(),
        platformRole: getPlatformRole(),
        route: state.route,
        roleRoutes: state.roleRoutes,
        runtime: {
          operatorMode: state.runtime.operatorMode,
          reconnectCount: state.runtime.reconnectCount,
          lastReconnectReason: state.runtime.lastReconnectReason,
          lastNavigationSource: state.runtime.lastNavigationSource,
          lastRenderTimestamp: state.runtime.lastRenderTimestamp,
          backendHealth: state.runtime.backendHealth
        },
        assistant: {
          runtimeState: state.assistant.runtimeState,
          draft: state.assistant.draft,
          pendingPrompt: state.assistant.pendingPrompt,
          pendingIntent: state.assistant.pendingIntent,
          previewCards: state.assistant.previewCards.slice(-12),
          auditEvents: state.assistant.auditEvents.slice(-48),
          executionHistory: state.assistant.executionHistory.slice(-16),
          memoryEntries: state.assistant.memoryEntries.slice(-20),
          sessionNonce: state.assistant.sessionNonce,
          securityState: state.assistant.securityState,
          collapsible: state.assistant.collapsible,
          messages: state.assistant.messages.slice(-24),
          toolEvents: state.assistant.toolEvents.slice(-24)
        },
        riderApp: {
          profile: safeObject((state.riderApp || {}).profile),
          activeRequestId: safeText((state.riderApp || {}).activeRequestId, ""),
          lastSubmit: safeObject((state.riderApp || {}).lastSubmit)
        }
      };
      sessionStorage.setItem(SESSION_STATE_KEY, JSON.stringify(payload));
    } catch (_) {}
  }

  function routeFromPath(pathname) {
    var normalizedPath = safeText(pathname, APP_BASE_PATH + "/dashboard");
    if (normalizedPath.length > 1 && normalizedPath.charAt(normalizedPath.length - 1) === "/") {
      normalizedPath = normalizedPath.slice(0, -1);
    }
    if (LEGACY_ROUTE_ALIASES[normalizedPath]) {
      normalizedPath = LEGACY_ROUTE_ALIASES[normalizedPath];
    }

    for (var key in ROUTES) {
      if (Object.prototype.hasOwnProperty.call(ROUTES, key) && ROUTES[key].path === normalizedPath) {
        return key;
      }
    }
    return "dashboard";
  }

  function dedicatedRouteFromPath(pathname) {
    var pathRoute = routeFromPath(pathname);
    return pathRoute === "mobile" || pathRoute === "riders" ? pathRoute : "";
  }

  function routeAllowed(role, route) {
    var allowed = ROLE_ACCESS[role] || ROLE_ACCESS.admin;
    return allowed.indexOf(route) >= 0;
  }

  function switchRoleView(role, pushHistory) {
    var nextRole = ROLE_ACCESS[role] ? role : "admin";
    var previousRole = state.role;
    state.role = nextRole;
    saveRole(nextRole);
    if (nextRole === "driver") {
      clearDriverLiveTripState({ resetBoundIdentity: false });
    } else if (previousRole === "driver") {
      resetDriverBoundIdentity();
    }
    var rememberedRoute = safeText(state.roleRoutes[nextRole], "");
    var targetRoute = routeAllowed(nextRole, rememberedRoute) ? rememberedRoute : defaultRouteForRole(nextRole);
    setRoute(targetRoute, pushHistory !== false, "role-switch");
    syncPlatformRoleAuth(nextRole).finally(function () {
      loadBackendData({ silent: true, forceDriverReset: nextRole === "driver" });
      void safeLogAssistantEvent("workflow", "role_switch", "success", {
        from_role: safeText(previousRole, "unknown"),
        to_role: safeText(state.role, "unknown"),
        jwt_role: getJwtSessionRole()
      }, "");
      renderPage();
      persistSessionState();
      updateTopBadges();
    });
  }

  function asBoolean(value, fallback) {
    if (value === null || value === undefined) {
      return fallback === true;
    }
    if (typeof value === "boolean") {
      return value;
    }
    var normalized = String(value).toLowerCase();
    return normalized === "true" || normalized === "1" || normalized === "yes";
  }

  function titleizeWords(value) {
    return String(value || "")
      .split(/[^a-zA-Z0-9]+/)
      .filter(Boolean)
      .map(function (part) {
        return part.charAt(0).toUpperCase() + part.slice(1).toLowerCase();
      })
      .join(" ");
  }

  var WARNING_DISPLAY_MAP = {
    ops_auth_required: {
      default: "Secure sign-in is required to view live operations."
    },
    hydration_partial: {
      default: "Some live operations data is temporarily delayed."
    },
    ops_hydration_partial: {
      default: "Some live operations data is temporarily delayed."
    },
    timeline_integrity_warning: {
      default: "Event timeline verification is still in progress."
    },
    provider_slice_missing: {
      default: "Provider intelligence is partially loaded.",
      provider: "Provider intelligence is partially loaded for your operational view."
    },
    health_snapshot_unavailable: {
      default: "Operations status updates are temporarily delayed. Monitoring remains active."
    },
    backend_down_8011: {
      default: "Backend API is unreachable. Auto-refresh is paused briefly to prevent loop churn."
    },
    backend_refresh_paused: {
      default: "Auto-refresh is paused briefly after a connectivity check. Data may be stale until the next refresh."
    },
    backend_unreachable: {
      default: "Backend API did not respond. Check that the server on this page origin is running, then hard-refresh."
    },
    supervision_snapshot_unavailable: {
      default: "Supervisor updates are temporarily delayed. Monitoring remains active."
    },
    streaming_unavailable: {
      default: "Live dispatch updates are temporarily delayed. Monitoring updates remain active."
    },
    stream_polling_fallback: {
      default: "Live updates are running in monitoring mode."
    },
    compliance_unavailable: {
      default: "Compliance updates are temporarily delayed. Existing operations data remains view-only."
    },
    orchestration_unavailable: {
      default: "Dispatch coordination updates are temporarily delayed. Task boards remain view-only."
    },
    hydration_timeout: {
      default: "Live data refresh timed out. Previously loaded records are kept until retry succeeds."
    },
    partial_operations_data: {
      default: "Some live feeds are delayed. Existing records remain visible; tap Retry to refresh."
    },
    dispatch_queue_unavailable: {
      default: "Dispatch queue refresh failed. Showing the last loaded queue snapshot."
    },
    live_workflow_feed_unavailable: {
      default: "Live workflow refresh failed. Showing the last loaded operational snapshot."
    },
    billing_rides_unavailable: {
      default: "Billing ride list refresh failed. Existing billing records remain visible."
    },
    billing_handoffs_unavailable: {
      default: "Billing handoff refresh failed. Existing handoff records remain visible."
    },
    admin_revenue_unavailable: {
      default: "Revenue totals refresh failed. Last known totals remain visible."
    }
  };

  function warningDisplayText(code, role) {
    var normalized = safeText(code, "unknown_warning");
    var entry = WARNING_DISPLAY_MAP[normalized] || {};
    if (entry[role]) {
      return entry[role];
    }
    if (entry.default) {
      return entry.default;
    }
    return titleizeWords(normalized.replace(/_/g, " ")) + ".";
  }

  function dedupeWarnings(warnings) {
    var seen = {};
    return (Array.isArray(warnings) ? warnings : []).filter(function (item) {
      var key = safeText(item, "");
      if (!key || seen[key]) {
        return false;
      }
      seen[key] = true;
      return true;
    });
  }

  function isNonEmptyArray(value) {
    return Array.isArray(value) && value.length > 0;
  }

  function preserveWorkflowField(incoming, previous, key) {
    if (incoming === null || incoming === undefined) {
      var prev = previous && previous[key];
      return Array.isArray(prev) ? prev.slice() : [];
    }
    return Array.isArray(incoming) ? incoming : [];
  }

  function mergeLiveWorkflowSnapshot(previous, incoming) {
    var prev = safeObject(previous);
    var next = safeObject(incoming);
    return {
      dispatchQueue: preserveWorkflowField(next.dispatchQueue, prev, "dispatchQueue"),
      activeAssignments: preserveWorkflowField(next.activeAssignments, prev, "activeAssignments"),
      activityFeed: preserveWorkflowField(next.activityFeed, prev, "activityFeed"),
      drivers: preserveWorkflowField(next.drivers, prev, "drivers"),
      rides: preserveWorkflowField(next.rides, prev, "rides"),
      providers: preserveWorkflowField(next.providers, prev, "providers"),
      customerRequests: preserveWorkflowField(next.customerRequests, prev, "customerRequests"),
      vehicles: preserveWorkflowField(next.vehicles, prev, "vehicles"),
      billingHandoffs: preserveWorkflowField(next.billingHandoffs, prev, "billingHandoffs"),
      tripDocuments: preserveWorkflowField(next.tripDocuments, prev, "tripDocuments")
    };
  }

  function recordLastGoodLiveWorkflow() {
    var wf = safeObject(state.liveWorkflow);
    var hasData = isNonEmptyArray(wf.drivers)
      || isNonEmptyArray(wf.rides)
      || isNonEmptyArray(wf.dispatchQueue)
      || isNonEmptyArray(wf.billingHandoffs)
      || isNonEmptyArray(wf.providers);
    if (!hasData) {
      return;
    }
    state.runtime = safeObject(state.runtime);
    try {
      state.runtime.lastGoodLiveWorkflow = JSON.parse(JSON.stringify(wf));
    } catch (_) {
      state.runtime.lastGoodLiveWorkflow = wf;
    }
    if (state.adminRevenue) {
      state.runtime.lastGoodAdminRevenue = state.adminRevenue;
    }
  }

  function restoreLastGoodLiveWorkflowIfNeeded() {
    var lastGood = safeObject(state.runtime && state.runtime.lastGoodLiveWorkflow);
    if (!Object.keys(lastGood).length) {
      return false;
    }
    state.liveWorkflow = mergeLiveWorkflowSnapshot(lastGood, safeObject(state.liveWorkflow));
    if (!state.adminRevenue && state.runtime.lastGoodAdminRevenue) {
      state.adminRevenue = state.runtime.lastGoodAdminRevenue;
    }
    return true;
  }

  async function sleepMs(ms) {
    return new Promise(function (resolve) {
      setTimeout(resolve, ms);
    });
  }

  function warningDisplayEntries() {
    return dedupeWarnings(state.fetchWarnings).map(function (code) {
      return {
        code: code,
        message: warningDisplayText(code, state.role)
      };
    });
  }

  function computeHydrationIntegrity(hasToken, opsFailures, warnings, healthReady, supervisionReady) {
    var warningList = dedupeWarnings(warnings);
    if (!hasToken) {
      return "AUTH_REQUIRED";
    }
    if (!healthReady || !supervisionReady) {
      return "DEGRADED";
    }
    if (opsFailures >= 3) {
      return "DEGRADED";
    }
    if (warningList.indexOf("timeline_integrity_warning") >= 0) {
      return "DEGRADED";
    }
    if (warningList.length > 0 || opsFailures > 0) {
      return "PARTIAL";
    }
    return "HEALTHY";
  }

  function hydrationIntegrityMeta(integrityState) {
    var stateKey = String(integrityState || "PARTIAL").toUpperCase();
    if (stateKey === "HEALTHY") {
      return {
        label: "Live",
        badgeClass: "badge-good",
        tone: "good",
        summary: "All required role-based live data feeds are available."
      };
    }
    if (stateKey === "AUTH_REQUIRED") {
      return {
        label: "Sign-In Required",
        badgeClass: "badge-bad",
        tone: "bad",
        summary: "Sign in to load live operations data for this role."
      };
    }
    if (stateKey === "DEGRADED") {
      return {
        label: "Operational Continuity",
        badgeClass: "badge-bad",
        tone: "bad",
        summary: "Live data quality is reduced. Monitoring safeguards remain active."
      };
    }
    return {
      label: "Limited Live Visibility",
      badgeClass: "badge-warn",
      tone: "warn",
      summary: "Some live updates are delayed while monitoring safeguards remain active."
    };
  }

  function renderHydrationIntegrityBadge(integrityState) {
    var meta = hydrationIntegrityMeta(integrityState);
    return '<span class="badge ' + meta.badgeClass + ' integrity-badge">' + escapeHtml(meta.label) + '</span>';
  }

  function timelineSeverityLabel(item) {
    var level = String(item.level || item.severity || "info").toLowerCase();
    if (level === "error" || level === "critical") return "HIGH";
    if (level === "warning" || level === "warn") return "MEDIUM";
    return "LOW";
  }

  function timelineHumanTitle(item) {
    var raw = String(item.event || item.event_type || item.status || "event").toLowerCase();
    var combined = [raw, safeText(item.subsystem, ""), safeText(item.source, ""), safeText(item.message, "")].join(" ").toLowerCase();

    if (combined.indexOf("driver") >= 0 && (combined.indexOf("availability") >= 0 || combined.indexOf("available") >= 0)) {
      return "Driver availability updated";
    }
    if (combined.indexOf("provider") >= 0 && (combined.indexOf("partial") >= 0 || combined.indexOf("unavailable") >= 0 || combined.indexOf("missing") >= 0)) {
      return "Provider coverage partially unavailable";
    }
    if (combined.indexOf("supervision") >= 0 && (combined.indexOf("connected") >= 0 || combined.indexOf("healthy") >= 0)) {
      return "System supervision feed connected";
    }
    if (combined.indexOf("auth") >= 0 || combined.indexOf("ops_auth_required") >= 0) {
      return "Operational authentication required";
    }
    return titleizeWords(raw.replace(/_/g, " "));
  }

  function timelineRoleAssociation(item) {
    var role = safeText(item.role || item.actor || item.slice_role || "system", "system").toLowerCase();
    if (ROLE_ACCESS[role]) {
      return role;
    }
    return "system";
  }

  function timelineTimestampGroup(timestamp) {
    var raw = safeText(timestamp, "");
    if (!raw) {
      return "Unknown";
    }
    var date = new Date(raw);
    if (Number.isNaN(date.getTime())) {
      return "Unknown";
    }
    var now = new Date();
    var sameUtcDay = now.getUTCFullYear() === date.getUTCFullYear() && now.getUTCMonth() === date.getUTCMonth() && now.getUTCDate() === date.getUTCDate();
    return sameUtcDay ? "Today" : "Earlier";
  }

  function unifiedTimelineItems(phase17) {
    var workflowRows = (phase17?.workflowTimeline ?? []).map(function (row) {
      return {
        sequence_number: row.sequence_number,
        event: safeText(row.status || row.event_type, "workflow_update"),
        level: safeText(row.level, "info"),
        subsystem: "workflow",
        source: safeText(row.workflow_name, "workflow"),
        actor: safeText(row.actor || row.role, "system"),
        timestamp: safeText(row.updated_at || row.timestamp, "")
      };
    });
    var eventRows = (phase17.eventPreview || []).map(function (row) {
      return {
        sequence_number: row.sequence || row.sequence_number,
        event: safeText(row.event_type || row.status, "event"),
        level: safeText(row.level, "info"),
        subsystem: "event_stream",
        source: safeText(row.source || row.subsystem, "event_stream"),
        actor: safeText(row.actor || row.role, "system"),
        timestamp: safeText(row.emitted_at || row.timestamp || row.updated_at, "")
      };
    });
    return mergeTimeline(workflowRows, eventRows);
  }

  function contractEventToTimelineItem(item) {
    var contract = item || {};
    return {
      event_id: safeText(contract.event_id, ""),
      sequence_number: safeNumber(contract.sequence, 0),
      event_type: safeText(contract.event_type, "workflow_transition"),
      event: safeText(contract.event_type, "workflow_transition"),
      level: safeText(contract.severity, "info").toLowerCase() === "high" ? "error" : (safeText(contract.severity, "info").toLowerCase() === "medium" ? "warning" : "info"),
      role: Array.isArray(contract.role_scope) && contract.role_scope.length > 0 ? safeText(contract.role_scope[0], "system") : "system",
      source: safeText(contract.source, "stream_adapter"),
      timestamp: safeText(contract.timestamp, ""),
      correlation_id: safeText(contract.correlation_id, ""),
      metadata: {
        advisory_only: safeText(contract.advisory_only, true),
        replay_safe: safeText(contract.replay_safe, true),
        append_only: safeText(contract.append_only, true),
        supervision_required: safeText(contract.supervision_required, true),
        role_scope: Array.isArray(contract.role_scope) ? contract.role_scope : []
      }
    };
  }

  function parseJwtPayload(token) {
    try {
      var parts = String(token || "").split(".");
      if (parts.length < 2) {
        return null;
      }
      var base64 = parts[1].replace(/-/g, "+").replace(/_/g, "/");
      var normalized = base64 + "===".slice((base64.length + 3) % 4);
      var decoded = atob(normalized);
      return JSON.parse(decoded);
    } catch (_) {
      return null;
    }
  }

  function tokenAgeBucket() {
    var token = getAccessToken();
    if (!token) {
      return "no_session";
    }
    var payload = parseJwtPayload(token);
    if (!payload || !payload.exp) {
      return "aging";
    }
    var nowSeconds = Math.floor(Date.now() / 1000);
    var remaining = safeNumber(payload.exp, nowSeconds) - nowSeconds;
    if (remaining <= 600) {
      return "near expiration";
    }
    if (remaining <= 1800) {
      return "aging";
    }
    return "fresh";
  }

  function operationalFeedCount() {
    var total = 0;
    if (state.health) total += 1;
    if (state.supervision) total += 1;
    if (state.ops.dashboardSummary) total += 1;
    if (state.ops.liveStatus) total += 1;
    if (Array.isArray(state.ops.alerts) && state.ops.alerts.length >= 0) total += 1;
    if (Array.isArray(state.ops.recommendations) && state.ops.recommendations.length >= 0) total += 1;
    if (Array.isArray(state.ops.timeline) && state.ops.timeline.length > 0) total += 1;
    return total;
  }

  function supervisorModeEnabled() {
    if (state.role === "admin") {
      return true;
    }
    try {
      var query = new URLSearchParams(window.location.search || "");
      if (query.get("support") === "1" || query.get("supervisor") === "1") {
        return true;
      }
    } catch (_) {}
    try {
      var supportMode = localStorage.getItem("amicor_support_mode");
      return supportMode === "1" || supportMode === "true";
    } catch (_) {
      return false;
    }
  }

  function badgeClassByStatus(status) {
    var normalized = String(status || "unknown").toLowerCase();
    if (normalized === "healthy" || normalized === "green" || normalized === "alive" || normalized === "ok" || normalized === "available") {
      return "badge-good";
    }
    if (normalized === "degraded" || normalized === "warning" || normalized === "warn") {
      return "badge-warn";
    }
    if (normalized === "critical" || normalized === "error" || normalized === "unavailable" || normalized === "failed") {
      return "badge-bad";
    }
    return "badge-neutral";
  }

  function throughputLabel(activeRequestCount, eventCount) {
    var active = safeNumber(activeRequestCount, 0);
    var recent = safeNumber(eventCount, 0);
    if (active >= 25 || recent >= 30) return "high";
    if (active >= 10 || recent >= 12) return "moderate";
    return "light";
  }

  function uptimeProgressPercent(uptimeSeconds) {
    var uptime = safeNumber(uptimeSeconds, 0);
    var dayCycle = 86400;
    var cyclePct = ((uptime % dayCycle) / dayCycle) * 100;
    return Math.max(4, Math.min(100, Math.round(cyclePct)));
  }

  function countEventsByKeyword(events, keyword) {
    if (!Array.isArray(events)) return 0;
    var key = String(keyword || "").toLowerCase();
    return events.filter(function (event) {
      var joined = [event.subsystem, event.event, event.level].join(" ").toLowerCase();
      return joined.indexOf(key) >= 0;
    }).length;
  }

  function buildSystemNotices() {
    var notices = [];
    var supervision = state.supervision || {};
    var profile = ROLE_PROFILE[state.role] || ROLE_PROFILE.admin;

    warningDisplayEntries().forEach(function (entry) {
      notices.push(entry.message + " (" + entry.code + ")");
    });

    if (state.error) {
      notices.push("Some operational data is delayed. Protected continuity monitoring remains active.");
    }

    if (safeText(supervision.supervision_status, "unknown") !== "healthy") {
      notices.push("Supervision reports a protected degraded subsystem state. Core continuity safeguards remain active.");
    }

    profile.notices.forEach(function (notice) {
      notices.push(notice);
    });

    if (notices.length === 0) {
      notices.push("No active operational notices.");
    }
    return notices;
  }

  function updateTopBadges() {
    var platformRole = getPlatformRole();
    var profile = ROLE_PROFILE[platformRole] || ROLE_PROFILE.admin;
    var displayRole = platformRole;
    var displayName = "";
    var displaySubrole = titleizeWords(displayRole);
    var badgeRole = platformRole;
    var badgeProfile = profile;
    var workspaceProfile = profile;
    var roleSelectValue = platformRole;
    var preferJwtRoleLabel = true;

    if (isRiderDedicatedSurface()) {
      var riderPresentation = getRiderSurfacePresentation();
      displayName = riderPresentation.displayName;
      displaySubrole = riderPresentation.displaySubrole;
      badgeRole = riderPresentation.badgeRole;
      badgeProfile = riderPresentation.profile;
      workspaceProfile = riderPresentation.profile;
      roleSelectValue = "rider";
      preferJwtRoleLabel = false;
    } else if (isDriverMobileAppRoute()) {
      var mobileAuth = driverMobileAuthCache || null;
      if (!mobileAuth || !mobileAuth.valid) {
        var persistedBadge = readPersistedDriverSession();
        if (persistedBadge && persistedBadge.driver_id && persistedBadge.session_token) {
          mobileAuth = {
            valid: true,
            driver_name: persistedBadge.driver_name,
            driver_id: persistedBadge.driver_id
          };
        }
      }
      displayRole = "driver";
      profile = ROLE_PROFILE.driver;
      if (mobileAuth && mobileAuth.valid) {
        displayName = safeText(mobileAuth.driver_name, "") || "Driver";
        displaySubrole = "driver";
      } else {
        displayName = "Driver Mobile";
        displaySubrole = "sign in required";
      }
      badgeRole = displayRole;
      badgeProfile = ROLE_PROFILE[displayRole] || profile;
      preferJwtRoleLabel = false;
    } else if (state.route === "drivers" && platformRole === "driver") {
      var driverBadgeAuth = driverMobileAuthCache || null;
      if ((!driverBadgeAuth || !driverBadgeAuth.valid) && hasValidDriverMobileSession()) {
        var persistedDriverBadge = readPersistedDriverSession();
        if (persistedDriverBadge && persistedDriverBadge.driver_id) {
          driverBadgeAuth = {
            valid: true,
            driver_name: persistedDriverBadge.driver_name,
            driver_id: persistedDriverBadge.driver_id
          };
        }
      }
      if (driverBadgeAuth && driverBadgeAuth.valid) {
        displayRole = "driver";
        displayName = safeText(driverBadgeAuth.driver_name, "") || "Driver";
        displaySubrole = "driver";
        profile = ROLE_PROFILE.driver;
      }
    }
    try {
      if (!displayName && !isDriverMobileAppRoute() && !isRiderDedicatedSurface() && window.AmiCorSession && typeof window.AmiCorSession.getIdentity === "function") {
        var identity = window.AmiCorSession.getIdentity() || {};
        displayName = safeText(identity.name || identity.display_name, "");
      }
    } catch (_) {}
    if (!displayName && !isRiderDedicatedSurface()) {
      displayName = displayRole === "dispatcher" ? "Dispatcher" : titleizeWords(displayRole);
    }
    var jwtRole = getJwtSessionRole();
    document.body.setAttribute("data-role", badgeRole);
    els.roleBadge.textContent = "role: " + badgeRole;
    els.roleContext.textContent = badgeProfile.context;
    if (els.roleSelect && !isDriverMobileAppRoute()) {
      els.roleSelect.value = roleSelectValue;
    }
    try {
      var userNameEl = document.getElementById("ops-user-name");
      var userRoleEl = document.getElementById("ops-user-role");
      if (userNameEl) userNameEl.textContent = displayName;
      if (userRoleEl) {
        userRoleEl.textContent = preferJwtRoleLabel && jwtRole ? titleizeWords(jwtRole) : displaySubrole;
      }
      var logoutBtn = document.getElementById("btn-logout");
      if (logoutBtn && isRiderDedicatedSurface()) {
        logoutBtn.hidden = !isRiderSurfaceAuthenticated();
      }
    } catch (_) {}

    var supervision = state.supervision;
    if (supervision && supervision.supervision_status) {
      els.connectionBadge.className = "badge " + badgeClassByStatus(supervision.supervision_status);
      els.connectionBadge.textContent = "operations: " + supervision.supervision_status;
    } else if (state.loading) {
      els.connectionBadge.className = "badge badge-neutral";
      els.connectionBadge.textContent = "checking operations";
    } else if (state.error) {
      els.connectionBadge.className = "badge badge-bad";
      els.connectionBadge.textContent = "operations notice";
    } else {
      els.connectionBadge.className = "badge badge-neutral";
      els.connectionBadge.textContent = "operations status pending";
    }

    if (els.workspacePill) {
      els.workspacePill.className = "badge badge-soft";
      els.workspacePill.textContent = "workspace: " + workspaceProfile.emphasis;
    }

    if (els.notificationPill) {
      var events = Array.isArray((state.supervision || {}).recent_events) ? state.supervision.recent_events : [];
      var warningCount = countEventsByLevel(events, "warning") + countEventsByLevel(events, "error");
      var runtimeTone = state.runtime.backendHealth === "down" ? "badge-bad" : (warningCount > 0 ? "badge-warn" : "badge-good");
      els.notificationPill.className = "badge " + runtimeTone;
      els.notificationPill.textContent = "route:" + state.route + " op:" + String(state.runtime.operatorMode) + " rc:" + String(safeNumber(state.runtime.reconnectCount, 0)) + " backend:" + state.runtime.backendHealth;
    }

    if (els.connectionBadge) {
      els.connectionBadge.title = [
        "lastReconnectReason=" + safeText(state.runtime.lastReconnectReason, "none"),
        "lastNavigationSource=" + safeText(state.runtime.lastNavigationSource, "init"),
        "lastRenderTimestamp=" + safeText(state.runtime.lastRenderTimestamp, ""),
        "backendHealth=" + safeText(state.runtime.backendHealth, "unknown")
      ].join(" | ");
    }
  }

  function renderNav() {
    var profile = ROLE_PROFILE[state.role] || ROLE_PROFILE.admin;
    var order = roleNavigationOrder(state.role);
    els.navLinks.forEach(function (link) {
      var route = String(link.getAttribute("data-route") || "dashboard");
      var meta = ROUTES[route] || {};
      var visible = routeAllowed(state.role, route);
      var orderIndex = order.indexOf(route);
      link.style.display = visible ? "block" : "none";
      link.style.order = orderIndex >= 0 ? String(orderIndex) : "999";
      link.classList.toggle("active", route === state.route);
      link.classList.toggle("role-emphasis", route === profile.emphasis && visible);
      if (meta.title) {
        link.textContent = meta.title;
      }
    });
  }

  function renderRecentEvents(events, limit) {
    if (!Array.isArray(events) || events.length === 0) {
      return '<p class="muted">No new supervision events in the current monitoring window.</p>';
    }
    var items = events.slice(0, limit || 8).map(function (event) {
      var level = String(event.level || "info").toLowerCase();
      var when = escapeHtml(formatOperationalTime(event.timestamp));
      var name = escapeHtml(event.event || "event");
      var subsystem = escapeHtml(event.subsystem || "runtime");
      return '<li><span class="event-pill">' + subsystem + '</span> ' + name + ' <span class="muted">(' + level + ', ' + when + ')</span></li>';
    }).join("");
    return '<ul class="list">' + items + '</ul>';
  }

  function renderNoticeList(notices) {
    var items = notices.map(function (notice) {
      return '<li>' + escapeHtml(notice) + '</li>';
    }).join("");
    return '<ul class="list">' + items + '</ul>';
  }

  function renderMetric(label, value, tone) {
    var toneClass = tone ? (" metric-" + tone) : "";
    return '<div class="metric' + toneClass + '"><label>' + escapeHtml(label) + '</label><strong>' + escapeHtml(value) + '</strong></div>';
  }

  function renderPanelBlock(title, subtitle, body, eyebrow, extraClass) {
    var classes = "panel" + (extraClass ? " " + extraClass : "");
    var head = '<div class="section-head">';
    if (eyebrow) {
      head += '<span class="section-eyebrow">' + escapeHtml(eyebrow) + '</span>';
    }
    head += '<div class="section-copy"><h3>' + escapeHtml(title) + '</h3>';
    if (subtitle) {
      head += '<p class="section-subtitle">' + escapeHtml(subtitle) + '</p>';
    }
    head += '</div></div>';
    return '<section class="' + classes + '">' + head + body + '</section>';
  }

  function renderQuickLinks(items) {
    var cards = items.map(function (item) {
      return '<a class="link-card" href="' + escapeHtml(item.href) + '">' +
        '<strong>' + escapeHtml(item.title) + '</strong>' +
        '<span>' + escapeHtml(item.description) + '</span>' +
        (item.note ? '<small>' + escapeHtml(item.note) + '</small>' : '') +
        '</a>';
    }).join("");
    return '<div class="link-grid">' + cards + '</div>';
  }

  function renderSimpleBars(items) {
    var maxValue = 1;
    items.forEach(function (item) {
      var value = safeNumber(item.value, 0);
      if (value > maxValue) {
        maxValue = value;
      }
    });

    return '<div class="visual-grid">' + items.map(function (item) {
      var value = safeNumber(item.value, 0);
      var width = Math.max(8, Math.round((value / maxValue) * 100));
      return '<div class="visual-card">' +
        '<div class="visual-card-head"><strong>' + escapeHtml(item.label) + '</strong><span>' + escapeHtml(String(value)) + '</span></div>' +
        '<div class="visual-track"><div class="visual-fill" style="width:' + width + '%"></div></div>' +
        '<p>' + escapeHtml(item.note || "read-only preview") + '</p>' +
        '</div>';
    }).join("") + '</div>';
  }

  function renderPayloadViewer(title, payload, subtitle) {
    var payloadText = JSON.stringify(payload || {}, null, 2)
      .replace(/runtime/gi, "operations")
      .replace(/orchestration/gi, "coordination")
      .replace(/autonomous/gi, "supervisor_controlled")
      .replace(/runtime_governor/gi, "supervisor_control")
      .replace(/websocket/gi, "live_updates")
      .replace(/telemetry/gi, "operations_visibility")
      .replace(/backend/gi, "operations")
      .replace(/diagnostics?/gi, "coordination")
      .replace(/infrastructure/gi, "operations_foundation")
      .replace(/synchronization/gi, "alignment")
      .replace(/severity/gi, "priority")
      .replace(/federation/gi, "regional_coordination")
      .replace(/distributed/gi, "multi_region")
      .replace(/event bus/gi, "event_flow")
      .replace(/observability/gi, "operations_visibility")
      .replace(/immutable/gi, "verified")
      .replace(/deterministic/gi, "consistent");
    return '<div class="payload-view">' +
      '<div class="payload-head"><strong>' + escapeHtml(title) + '</strong>' + (subtitle ? '<span>' + escapeHtml(subtitle) + '</span>' : '') + '</div>' +
      '<pre class="payload-json">' + escapeHtml(payloadText) + '</pre>' +
      '</div>';
  }

  function normalizePresentationText(text) {
    return safeText(text, "")
      .replace(/system health/gi, "operations status")
      .replace(/backend/gi, "operations")
      .replace(/diagnostics?/gi, "coordination")
      .replace(/runtime/gi, "operations")
      .replace(/orchestration/gi, "coordination")
      .replace(/telemetry/gi, "operations visibility")
      .replace(/severity/gi, "priority")
      .replace(/federation/gi, "regional coordination")
      .replace(/observability/gi, "operations visibility");
  }

  function renderFeedSummary(events, keyword) {
    var filtered = filterEventsByKeyword(events, keyword);
    if (filtered.length === 0) {
      return '<p class="muted">No matching events available for this surface.</p>';
    }
    return renderRecentEvents(filtered, 8);
  }

  function filterEventsByKeyword(events, keyword) {
    if (!Array.isArray(events) || events.length === 0) return [];
    var key = String(keyword || "").toLowerCase();
    return events.filter(function (event) {
      var joined = [event.subsystem, event.event, event.level, event.message].join(" ").toLowerCase();
      return joined.indexOf(key) >= 0;
    });
  }

  function countEventsByLevel(events, level) {
    if (!Array.isArray(events) || events.length === 0) return 0;
    var key = String(level || "").toLowerCase();
    return events.filter(function (event) {
      return String(event.level || "info").toLowerCase() === key;
    }).length;
  }

  function healthToneFromStatus(status) {
    var normalized = String(status || "unknown").toLowerCase();
    if (normalized === "healthy" || normalized === "alive" || normalized === "ok" || normalized === "available") {
      return "good";
    }
    if (normalized === "degraded" || normalized === "warning" || normalized === "warn" || normalized === "partial") {
      return "warn";
    }
    if (normalized === "critical" || normalized === "unavailable" || normalized === "failed" || normalized === "error") {
      return "bad";
    }
    return "neutral";
  }

  function buildHealthScore(health, supervision) {
    var score = 100;
    var statusValues = [
      safeText((health || {}).backend_status, "unknown"),
      safeText((supervision || {}).supervision_status, "unknown"),
      safeText((supervision || {}).health_classification, "unknown"),
      safeText(((supervision || {}).runtime_governor || {}).status, "unknown"),
      safeText(((supervision || {}).websocket_status || {}).status, "unknown"),
      safeText(((supervision || {}).memory_persistence || {}).status, "unknown")
    ];

    statusValues.forEach(function (value) {
      var tone = healthToneFromStatus(value);
      if (tone === "warn") score -= 10;
      if (tone === "bad") score -= 20;
    });

    if (state.fetchWarnings.length > 0) {
      score -= state.fetchWarnings.length * 6;
    }
    if (state.error) {
      score -= 8;
    }
    score -= Math.min(15, safeNumber((supervision || {}).active_request_count, 0));
    return Math.max(0, Math.min(100, score));
  }

  function renderHealthBanner(health, supervision) {
    var score = buildHealthScore(health, supervision);
    var tone = score >= 85 ? "good" : score >= 65 ? "warn" : "bad";
    return [
      '<section class="panel status-banner status-banner-' + tone + '">',
      '<div class="status-banner-copy">',
      '<span class="section-eyebrow">Operational intelligence</span>',
      '<h3>Health score ' + score + '/100</h3>',
      '<p>View-only readout combining service health, supervision status, memory context, and live visibility quality signals.</p>',
      '</div>',
      '<div class="status-banner-score">',
      '<strong>' + score + '</strong>',
      '<span>' + (tone === "good" ? "stable" : tone === "warn" ? "watch" : "critical") + '</span>',
      '</div>',
      '</section>'
    ].join("");
  }

  function renderUptimeBlock(uptimeText, uptimeSeconds) {
    var pct = uptimeProgressPercent(uptimeSeconds);
    return [
      '<section class="panel">',
      '<h3>Service Uptime</h3>',
      '<p class="muted">Current continuous service duration.</p>',
      '<div class="uptime-value">' + escapeHtml(uptimeText) + '</div>',
      '<div class="uptime-track" role="progressbar" aria-valuemin="0" aria-valuemax="100" aria-valuenow="' + pct + '">',
      '<div class="uptime-fill" style="width:' + pct + '%"></div>',
      '</div>',
      '</section>'
    ].join("");
  }

  function renderHydrationStatusPanel(roleLabel, slice) {
    var hydration = state.hydration || {};
    var alerts = Array.isArray(slice.alerts) ? slice.alerts.length : 0;
    var timelineCount = Array.isArray(slice.timeline) ? slice.timeline.length : 0;
    var integrity = hydrationIntegrityMeta(hydration.integrityState);
    return renderPanelBlock(
      roleLabel + " Data Feed Status",
      "Secure operational feed status, continuity markers, and role-bound visibility.",
      '<div class="integrity-strip">' +
        '<span class="muted">Access Status</span>' + renderHydrationIntegrityBadge(hydration.integrityState) +
      '</div>' +
      '<div class="grid-4">' +
        renderMetric("Access Status", hydration.authTokenPresent ? "Connected" : "Sign-In Required", hydration.authTokenPresent ? "status" : "bad") +
        renderMetric("Live Visibility", (hydration.opsHydrated || hydration.authTokenPresent || safeText((state.supervision || {}).supervision_status, "") === "healthy") ? "Live" : "Limited Live Visibility", (hydration.opsHydrated || hydration.authTokenPresent || safeText((state.supervision || {}).supervision_status, "") === "healthy") ? "status" : "warn") +
        renderMetric("Access Verification", integrity.label, integrity.tone) +
        renderMetric("Role Slice", safeText(slice.sliceRole, roleLabel.toLowerCase())) +
        renderMetric("Continuity Protected", safeText(slice.replaySafe, true) ? "yes" : "watch") +
        renderMetric("Audit Trail", safeText(slice.appendOnly, true) ? "preserved" : "watch") +
        renderMetric("Advisory Only", safeText(slice.advisoryOnly, true) ? "true" : "watch") +
        renderMetric("Alerts", String(alerts)) +
        renderMetric("Timeline Events", String(timelineCount)) +
      '</div>' +
      '<p class="muted">' + escapeHtml(integrity.summary) + '</p>' +
      '<p class="muted">Last update time: ' + escapeHtml(safeText(hydration.lastUpdatedAt, "unknown")) + '</p>',
      'live data status'
    );
  }

  function renderRoleIdentityPanel(roleKey, slice, supervisionStatus) {
    var profile = ROLE_PROFILE[roleKey] || ROLE_PROFILE.admin;
    var identityMap = {
      admin: {
        heading: "Administrative Command Center",
        scope: "Cross-role command visibility with supervision-first oversight."
      },
      dispatcher: {
        heading: "Dispatcher Operations Workspace",
        scope: "Live assignment control, queue supervision, and dispatch coordination."
      },
      rider: {
        heading: "Rider Operations View",
        scope: "Rider-facing trip progress, support context, and advisory guidance."
      },
      driver: {
        heading: "Driver Operations Console",
        scope: "Driver readiness, assignment awareness, and supervised route context."
      },
      provider: {
        heading: "Provider Intelligence Surface",
        scope: "Provider coverage, readiness posture, and partner-focused intelligence."
      },
      compliance_officer: {
        heading: "Compliance Dashboard",
        scope: "Credential review, document lineage, and regulatory posture."
      },
      supervisor: {
        heading: "Supervision Center",
        scope: "Approval queue oversight, escalation handling, and team performance."
      },
      driver_support: {
        heading: "Driver Support Workspace",
        scope: "Onboarding assistance, ticket response, and certification tracking."
      },
      medical_coordinator: {
        heading: "Medical Coordination Portal",
        scope: "Patient transport planning, clinical liaison, and appointment coordination."
      }
    };
    var identity = identityMap[roleKey] || identityMap.admin;
    return renderPanelBlock(
      identity.heading,
      "Role identity, operational scope, and supervision posture for live transport operations.",
      '<div class="grid-4">' +
        renderMetric("Role Identity", titleizeWords(roleKey), "status") +
        renderMetric("Operational Scope", identity.scope) +
        renderMetric("Advisory-Only Status", asBoolean(slice.advisoryOnly, true) ? "active" : "watch", asBoolean(slice.advisoryOnly, true) ? "good" : "warn") +
        renderMetric("Supervision Mode", titleizeWords(safeText(supervisionStatus, "unknown")), healthToneFromStatus(supervisionStatus)) +
      '</div>' +
      '<p class="muted">' + escapeHtml(profile.context) + '</p>',
      'role identity'
    );
  }

  function renderOperationalHeartbeatPanel(slice) {
    var hydrationActive = asBoolean((state.hydration || {}).authTokenPresent, false) && asBoolean((state.hydration || {}).opsHydrated, false);
    var timelineActive = Array.isArray((slice || {}).timeline) && (slice.timeline.length > 0 || safeNumber((state.ops || {}).timelineCursor, 0) > 0);
    var advisoryOnly = asBoolean((slice || {}).advisoryOnly, true);
    var replaySafe = asBoolean((slice || {}).replaySafe, true);
    var feedCount = operationalFeedCount();
    return renderPanelBlock(
      "Operational Heartbeat",
      "Supervision-first heartbeat indicators for live transport operations.",
      '<div class="grid-4">' +
        renderMetric("Route Monitoring", hydrationActive ? "active" : "limited visibility", hydrationActive ? "good" : "warn") +
        renderMetric("Trip Sequence", timelineActive ? "in progress" : "pending updates", timelineActive ? "good" : "warn") +
        renderMetric("Operational Sources", String(feedCount)) +
        renderMetric("Operational Guidance", advisoryOnly ? "enabled" : "watch", advisoryOnly ? "good" : "warn") +
        renderMetric("Continuity Protection", replaySafe ? "active" : "watch", replaySafe ? "good" : "warn") +
      '</div>' +
      '<p class="muted">Monitoring remains supervisor-controlled with no automatic field actions.</p>',
      'heartbeat'
    );
  }

  function renderAuthDiagnosticsCard(slice) {
    if (!supervisorModeEnabled()) {
      return "";
    }
    var hydration = state.hydration || {};
    var integrity = hydrationIntegrityMeta(hydration.integrityState);
    var roleSlice = safeText((slice || {}).sliceRole, safeText(hydration.roleSlice, state.role));
    var warningCount = dedupeWarnings(state.fetchWarnings).length;
    return renderPanelBlock(
      "Access Status",
      "View-only access and live transport status for supervision-aware operations.",
      '<div class="grid-4">' +
        renderMetric("Secure Session", hydration.authTokenPresent ? "yes" : "no", hydration.authTokenPresent ? "good" : "warn") +
        renderMetric("Session Age", tokenAgeBucket(), tokenAgeBucket() === "near expiration" ? "warn" : "status") +
        renderMetric("Transport Visibility", integrity.label, integrity.tone) +
        renderMetric("Role View Loaded", safeText(roleSlice, state.role)) +
        renderMetric("Connected Sources", String(operationalFeedCount())) +
        renderMetric("Active Notices", String(warningCount), warningCount > 0 ? "warn" : "good") +
        renderMetric("Last Sync Time", safeText(hydration.lastUpdatedAt, "unknown")) +
        renderMetric("Continuity Protection", asBoolean((slice || {}).replaySafe, true) ? "active" : "watch") +
        renderMetric("Advisory-Only Mode Active", asBoolean((slice || {}).advisoryOnly, true) ? "yes" : "watch") +
      '</div>' +
      '<p class="muted">Sensitive values and credentials are never exposed in this supervision view.</p>',
      'access status'
    );
  }

  function renderStreamStatusPanel(phase17) {
    var stream = (phase17 || {}).stream || {};
    var streamConnected = asBoolean(stream.connected, false);
    var streamMode = safeText(stream.mode, "polling_fallback");
    var streamModeMap = {
      polling_fallback: "Live Monitoring",
      secure_monitoring: "Live Monitoring",
      websocket: "Live Route Updates"
    };
    var streamModeDisplay = safeText(streamModeMap[streamMode], titleizeWords(streamMode));
    var timelineSyncState = safeText(stream.timelineSyncStatus, "idle");
    var timelineSyncMap = {
      idle: "Monitoring Ready",
      active: "Route Monitoring Active"
    };
    var timelineSyncDisplay = safeText(timelineSyncMap[timelineSyncState], titleizeWords(timelineSyncState));
    var lastDispatchDisplay = safeText(stream.lastEventReceived, null) || (
      (asBoolean((state.hydration || {}).authTokenPresent, false) || safeText((state.supervision || {}).supervision_status, "") === "healthy")
        ? "Connected · awaiting next event"
        : "Awaiting Dispatch Update"
    );
    return renderPanelBlock(
      "Live Update Status",
      "Live operational update channel status with safe monitoring fallback.",
      '<div class="grid-4">' +
        renderMetric("Update Channel", streamConnected ? "connected" : "standby", streamConnected ? "good" : "warn") +
        renderMetric("Update Mode", streamModeDisplay) +
        renderMetric("Last Dispatch Update", lastDispatchDisplay) +
        renderMetric("Update Count", String(safeNumber(stream.eventCount, 0))) +
        renderMetric("Timeline Sync", timelineSyncDisplay, timelineSyncState === "active" ? "good" : "warn") +
        renderMetric("Supervisor-Safe", asBoolean(stream.supervisionSafe, true) ? "yes" : "watch") +
        renderMetric("Continuity Protected", asBoolean(stream.replaySafe, true) ? "yes" : "watch") +
      '</div>' +
      '<p class="muted">Live updates are view-only. No dispatch actions or automatic field changes are available.</p>',
      'stream status'
    );
  }

  function renderCorrelationPanel(phase17) {
    var correlation = (phase17 || {}).correlation || {};
    var groups = Array.isArray(correlation.groups) ? correlation.groups : [];
    var body = '<div class="grid-3">' +
      renderMetric("Correlation Groups", String(safeNumber(correlation.totalGroups, groups.length))) +
      renderMetric("Top Group Size", String(groups.length > 0 ? safeNumber(groups[0].event_count, 0) : 0)) +
      renderMetric("Read-Only Correlation", "enabled") +
    '</div>';

    if (groups.length === 0) {
      body += '<p class="muted">No correlated event groups are currently available.</p>';
    } else {
      body += '<div class="table-wrap"><table class="ops-table"><thead><tr><th>Correlation ID</th><th>Events</th><th>Roles</th><th>Last Timestamp</th></tr></thead><tbody>' + groups.slice(0, 8).map(function (group) {
        var roleText = Array.isArray(group.role_scope) ? group.role_scope.join(",") : "none";
        return '<tr>' +
          '<td>' + escapeHtml(safeText(group.correlation_id, "unknown")) + '</td>' +
          '<td>' + escapeHtml(String(safeNumber(group.event_count, 0))) + '</td>' +
          '<td>' + escapeHtml(roleText) + '</td>' +
          '<td>' + escapeHtml(safeText(group.last_timestamp, "unknown")) + '</td>' +
        '</tr>';
      }).join("") + '</tbody></table></div>';
    }

    return renderPanelBlock(
      "Event Correlation Context",
      "Correlation groups across role-safe transport activity streams. View-only context only.",
      body,
      'correlation'
    );
  }

  function renderComplianceOverviewPanel(phase17) {
    var compliance = (phase17 || {}).compliance || {};
    var overview = compliance.compliance_overview || {};
    return renderPanelBlock(
      "Compliance Overview",
      "Read-only compliance counters for supervised operator decisions.",
      '<div class="grid-4">' +
        renderMetric("Total Compliant", String(safeNumber(overview.total_compliant, 0))) +
        renderMetric("Expiring Soon", String(safeNumber(overview.expiring_soon, 0)), safeNumber(overview.expiring_soon, 0) > 0 ? "warn" : "good") +
        renderMetric("Expired", String(safeNumber(overview.expired, 0)), safeNumber(overview.expired, 0) > 0 ? "bad" : "good") +
        renderMetric("Under Review", String(safeNumber(overview.under_review, 0))) +
      '</div>' +
      '<p class="muted">Compliance status is advisory-only. No automatic activation, suspension, or dispatch action is executed.</p>',
      "compliance-overview"
    );
  }

  function renderExpirationQueuePanel(phase17) {
    var compliance = (phase17 || {}).compliance || {};
    var queue = compliance.expiration_queue || {};
    var licenses = Array.isArray(queue.licenses_expiring) ? queue.licenses_expiring : [];
    var insurance = Array.isArray(queue.insurance_expiring) ? queue.insurance_expiring : [];
    var inspection = Array.isArray(queue.inspection_expiring) ? queue.inspection_expiring : [];
    var severity = queue.severity_distribution || {};

    return renderPanelBlock(
      "Credential Expiration Queue",
      "Expiring and expired transport credentials with supervisor-priority labels.",
      '<div class="grid-4">' +
        renderMetric("Licenses Expiring", String(licenses.length), licenses.length > 0 ? "warn" : "good") +
        renderMetric("Insurance Expiring", String(insurance.length), insurance.length > 0 ? "warn" : "good") +
        renderMetric("Inspection Expiring", String(inspection.length), inspection.length > 0 ? "warn" : "good") +
        renderMetric("Critical Alerts", String(safeNumber(severity.CRITICAL, 0)), safeNumber(severity.CRITICAL, 0) > 0 ? "bad" : "good") +
      '</div>' +
      '<div class="grid-4">' +
        renderMetric("Routine Review", String(safeNumber(severity.LOW, 0))) +
        renderMetric("Time-Sensitive", String(safeNumber(severity.MEDIUM, 0)), safeNumber(severity.MEDIUM, 0) > 0 ? "warn" : "neutral") +
        renderMetric("Continuity-Sensitive", String(safeNumber(severity.HIGH, 0)), safeNumber(severity.HIGH, 0) > 0 ? "warn" : "neutral") +
        renderMetric("Transport-Critical", String(safeNumber(severity.CRITICAL, 0)), safeNumber(severity.CRITICAL, 0) > 0 ? "bad" : "neutral") +
      '</div>',
      "expiration-queue"
    );
  }

  function renderApprovalQueuePanel(phase17) {
    var compliance = (phase17 || {}).compliance || {};
    var queue = compliance.approval_queue || {};
    return renderPanelBlock(
      "Supervisor Approval Queue",
      "Supervisor-reviewed approval backlog requiring oversight team confirmation.",
      '<div class="grid-3">' +
        renderMetric("Pending Approvals", String(safeNumber(queue.pending_approvals, 0)), safeNumber(queue.pending_approvals, 0) > 0 ? "warn" : "good") +
        renderMetric("Pending Reviews", String(safeNumber(queue.pending_reviews, 0)), safeNumber(queue.pending_reviews, 0) > 0 ? "warn" : "good") +
        renderMetric("Rejected Items", String(safeNumber(queue.rejected_items, 0)), safeNumber(queue.rejected_items, 0) > 0 ? "warn" : "neutral") +
      '</div>' +
      '<p class="muted">Supervisor approval is mandatory. Automatic approvals and unsupervised assignment handling are disabled.</p>',
      "approval-queue"
    );
  }

  function renderComplianceTimelinePanel(phase17) {
    var compliance = (phase17 || {}).compliance || {};
    var timeline = Array.isArray(compliance.compliance_timeline) ? compliance.compliance_timeline : [];
    if (timeline.length === 0) {
      return renderPanelBlock(
        "Compliance Timeline",
        "Audit-tracked compliance activity grouped by supervisor priority and role.",
        '<p class="muted">No compliance audit events are currently available for this role scope.</p>',
        "compliance-timeline"
      );
    }

    var severityCounts = { LOW: 0, MEDIUM: 0, HIGH: 0, CRITICAL: 0 };
    timeline.forEach(function (row) {
      var sev = String(row.severity || "LOW").toUpperCase();
      if (severityCounts[sev] === undefined) sev = "LOW";
      severityCounts[sev] += 1;
    });

    var table = timeline.slice(0, 12).map(function (row) {
      return '<tr>' +
        '<td>' + escapeHtml(String(row.sequence || "")) + '</td>' +
        '<td>' + escapeHtml(String(row.action_type || "unknown")) + '</td>' +
        '<td>' + escapeHtml(String(row.actor_role || "unknown")) + '</td>' +
        '<td>' + escapeHtml(String(row.target_driver_id || "unknown")) + '</td>' +
        '<td>' + escapeHtml(String(row.severity || "LOW").toUpperCase()) + '</td>' +
        '<td>' + escapeHtml(String(row.timestamp || "unknown")) + '</td>' +
      '</tr>';
    }).join("");

    return renderPanelBlock(
      "Compliance Timeline",
      "Audit-tracked compliance activity grouped by supervisor priority and role.",
      '<div class="grid-4">' +
        renderMetric("Routine Review", String(severityCounts.LOW)) +
        renderMetric("Time-Sensitive", String(severityCounts.MEDIUM), severityCounts.MEDIUM > 0 ? "warn" : "neutral") +
        renderMetric("Continuity-Sensitive", String(severityCounts.HIGH), severityCounts.HIGH > 0 ? "warn" : "neutral") +
        renderMetric("Transport-Critical", String(severityCounts.CRITICAL), severityCounts.CRITICAL > 0 ? "bad" : "neutral") +
      '</div>' +
      '<div class="table-wrap"><table class="ops-table"><thead><tr><th>Sequence</th><th>Action</th><th>Role</th><th>Driver</th><th>Priority</th><th>Timestamp</th></tr></thead><tbody>' + table + '</tbody></table></div>',
      "compliance-timeline"
    );
  }

  function renderEvidenceChainViewerPanel(phase17) {
    var compliance = (phase17 || {}).compliance || {};
    var phase25 = compliance.phase25 || {};
    var rows = Array.isArray(phase25.evidence_chain_viewer) ? phase25.evidence_chain_viewer : [];
    var encryptedCount = rows.filter(function (row) { return safeText(row.encryption_status, "").indexOf("encrypted") === 0; }).length;
    var regulatoryCount = rows.filter(function (row) { return safeText(row.retention_class, "") === "regulatory"; }).length;
    var table = rows.slice(0, 10).map(function (row) {
      return '<tr>' +
        '<td>' + escapeHtml(safeText(row.document_id, "unknown")) + '</td>' +
        '<td>' + escapeHtml(safeText(row.driver_id, "unknown")) + '</td>' +
        '<td>' + escapeHtml(safeText(row.retention_class, "unknown")) + '</td>' +
        '<td>' + escapeHtml(safeText(row.immutable_reference_id, "unknown")) + '</td>' +
      '</tr>';
    }).join("");

    return renderPanelBlock(
      "Evidence Chain Viewer",
      "Verified document evidence links with storage and retention posture.",
      '<div class="grid-4">' +
        renderMetric("Evidence Links", String(rows.length)) +
        renderMetric("Encrypted", String(encryptedCount), encryptedCount === rows.length && rows.length > 0 ? "good" : "warn") +
        renderMetric("Regulatory Class", String(regulatoryCount), regulatoryCount > 0 ? "good" : "neutral") +
        renderMetric("Update Control", "manual review only") +
      '</div>' +
      (rows.length > 0
        ? '<div class="table-wrap"><table class="ops-table"><thead><tr><th>Document</th><th>Driver</th><th>Retention</th><th>Verification Ref</th></tr></thead><tbody>' + table + '</tbody></table></div>'
        : '<p class="muted">No evidence links are available for the current role scope.</p>'),
      "evidence-chain"
    );
  }

  function renderDocumentLineageViewerPanel(phase17) {
    var compliance = (phase17 || {}).compliance || {};
    var phase25 = compliance.phase25 || {};
    var rows = Array.isArray(phase25.document_lineage_viewer) ? phase25.document_lineage_viewer : [];
    var table = rows.slice(0, 12).map(function (row) {
      return '<tr>' +
        '<td>' + escapeHtml(String(row.sequence || "")) + '</td>' +
        '<td>' + escapeHtml(safeText(row.document_id, "unknown")) + '</td>' +
        '<td>' + escapeHtml(safeText(row.replaces_document_id, "-")) + '</td>' +
        '<td>' + escapeHtml(safeText(row.lineage_root_id, "unknown")) + '</td>' +
      '</tr>';
    }).join("");
    return renderPanelBlock(
      "Document Update Timeline",
      "Chronological document replacement history for supervisor review.",
      rows.length > 0
        ? '<div class="table-wrap"><table class="ops-table"><thead><tr><th>Sequence</th><th>Document</th><th>Replaces</th><th>Lineage Root</th></tr></thead><tbody>' + table + '</tbody></table></div>'
        : '<p class="muted">No document update events captured yet.</p>',
      "document-lineage"
    );
  }

  function renderSupervisorReviewQueuePanel(phase17) {
    var compliance = (phase17 || {}).compliance || {};
    var phase25 = compliance.phase25 || {};
    var rows = Array.isArray(phase25.supervisor_review_queue) ? phase25.supervisor_review_queue : [];
    var waiting = rows.filter(function (row) { return safeText(row.stage, "") !== "approved"; }).length;
    return renderPanelBlock(
      "Supervisor Review Queue",
      "Dual-control handoff stages for supervisor-reviewed compliance decisions.",
      '<div class="grid-3">' +
        renderMetric("Queue Depth", String(rows.length), rows.length > 0 ? "warn" : "good") +
        renderMetric("Awaiting Review", String(waiting), waiting > 0 ? "warn" : "good") +
        renderMetric("Countersigned", String(rows.filter(function (row) { return !!row.countersign_supervisor_id; }).length)) +
      '</div>' +
      '<p class="muted">Approval remains operator-supervised. Unsupervised review progression is disabled.</p>',
      "supervisor-review"
    );
  }

  function renderRegulatoryExportBuilderPanel(phase17) {
    var compliance = (phase17 || {}).compliance || {};
    var phase25 = compliance.phase25 || {};
    var rows = Array.isArray(phase25.regulatory_export_builder) ? phase25.regulatory_export_builder : [];
    var checksumReady = rows.filter(function (row) { return !!safeText(row.checksum, ""); }).length;
    return renderPanelBlock(
      "Regulatory Export Builder",
      "Regulator-ready export bundles with supervisor-verified checksum snapshots.",
      '<div class="grid-3">' +
        renderMetric("Generated Bundles", String(rows.length)) +
        renderMetric("Checksummed", String(checksumReady), checksumReady === rows.length && rows.length > 0 ? "good" : "neutral") +
        renderMetric("Retention Scope", "regulatory") +
      '</div>' +
      '<p class="muted">Export generation is audit-tracked and supervisor-controlled. No silent record changes are allowed.</p>',
      "export-builder"
    );
  }

  function renderSignedAccessMonitorPanel(phase17) {
    var compliance = (phase17 || {}).compliance || {};
    var phase25 = compliance.phase25 || {};
    var rows = Array.isArray(phase25.signed_access_monitor) ? phase25.signed_access_monitor : [];
    var revoked = rows.filter(function (row) { return !!row.revoked; }).length;
    var active = rows.length - revoked;
    return renderPanelBlock(
      "Signed Access Monitor",
      "Time-bound signed retrieval access with reason and role-scoped audit trace.",
      '<div class="grid-4">' +
        renderMetric("Active Grants", String(active), active > 0 ? "warn" : "good") +
        renderMetric("Revoked Grants", String(revoked)) +
        renderMetric("Total Grants", String(rows.length)) +
        renderMetric("Reason Required", "enforced") +
      '</div>',
      "signed-access"
    );
  }

  function renderRetentionStatusDashboardPanel(phase17) {
    var compliance = (phase17 || {}).compliance || {};
    var phase25 = compliance.phase25 || {};
    var rows = Array.isArray(phase25.retention_status_dashboard) ? phase25.retention_status_dashboard : [];
    var legalHoldCount = rows.filter(function (row) { return !!row.legal_hold; }).length;
    var releaseRequired = rows.filter(function (row) { return !!row.release_workflow_required; }).length;
    return renderPanelBlock(
      "Retention Status Dashboard",
      "Retention class timeline with legal hold and release workflow governance.",
      '<div class="grid-4">' +
        renderMetric("Retention Events", String(rows.length)) +
        renderMetric("Legal Holds", String(legalHoldCount), legalHoldCount > 0 ? "warn" : "good") +
        renderMetric("Release Required", String(releaseRequired), releaseRequired > 0 ? "warn" : "neutral") +
        renderMetric("Operator Release", "supervisor_only") +
      '</div>',
      "retention-status"
    );
  }

  function renderSupervisorTaskInboxPanel(phase17) {
    var orchestration = (phase17 || {}).orchestration || {};
    var snapshot = orchestration.queue_snapshot || {};
    var tasks = Array.isArray(snapshot.tasks) ? snapshot.tasks : [];
    var table = tasks.slice(0, 10).map(function (row) {
      return '<tr>' +
        '<td>' + escapeHtml(safeText(row.task_id, "unknown")) + '</td>' +
        '<td>' + escapeHtml(safeText(row.title, "untitled")) + '</td>' +
        '<td>' + escapeHtml(safeText(row.priority, "normal")) + '</td>' +
        '<td>' + escapeHtml(safeText(row.assigned_to_role, "unassigned")) + '</td>' +
      '</tr>';
    }).join("");
    return renderPanelBlock(
      "Supervisor Task Inbox",
      "View-only supervised task inbox with audit references.",
      '<div class="grid-3">' +
        renderMetric("Visible Tasks", String(tasks.length)) +
        renderMetric("Masked View", snapshot.masked ? "yes" : "no") +
        renderMetric("Change Authority", "disabled") +
      '</div>' +
      (tasks.length > 0
        ? '<div class="table-wrap"><table class="ops-table"><thead><tr><th>Task</th><th>Title</th><th>Priority</th><th>Assigned Role</th></tr></thead><tbody>' + table + '</tbody></table></div>'
        : '<p class="muted">No tasks are visible for the current role scope.</p>'),
      "orchestration-inbox"
    );
  }

  function renderEscalationQueuePanel(phase17) {
    var orchestration = (phase17 || {}).orchestration || {};
    var snapshot = orchestration.queue_snapshot || {};
    var health = snapshot.queue_health || {};
    return renderPanelBlock(
      "Escalation Queue",
      "Escalation routing metrics with chronological supervised-only progression.",
      '<div class="grid-4">' +
        renderMetric("Escalated", String(safeNumber(health.escalated, 0)), safeNumber(health.escalated, 0) > 0 ? "warn" : "good") +
        renderMetric("Pending", String(safeNumber(health.pending, 0))) +
        renderMetric("Handoff Pending", String(safeNumber(health.handoff_pending, 0)), safeNumber(health.handoff_pending, 0) > 0 ? "warn" : "neutral") +
        renderMetric("Continuity Protection Active", "true") +
      '</div>',
      "orchestration-escalation"
    );
  }

  function renderAssignmentTimelinePanel(phase17) {
    var orchestration = (phase17 || {}).orchestration || {};
    var timeline = orchestration.timeline_projection || {};
    var events = Array.isArray(timeline.events) ? timeline.events : [];
    var table = events.slice(0, 12).map(function (row) {
      return '<tr>' +
        '<td>' + escapeHtml(String(row.sequence || "")) + '</td>' +
        '<td>' + escapeHtml(safeText(row.event_type, "event")) + '</td>' +
        '<td>' + escapeHtml(safeText(row.task_id, "unknown")) + '</td>' +
        '<td>' + escapeHtml(safeText(row.timestamp, "unknown")) + '</td>' +
      '</tr>';
    }).join("");
    return renderPanelBlock(
      "Assignment Timeline",
      "Chronological coordination timeline for supervisor review.",
      (events.length > 0
        ? '<div class="table-wrap"><table class="ops-table"><thead><tr><th>Seq</th><th>Type</th><th>Task</th><th>Timestamp</th></tr></thead><tbody>' + table + '</tbody></table></div>'
        : '<p class="muted">No coordination timeline events are currently available.</p>') +
      '<p class="muted">This timeline is view-only and cannot trigger field actions.</p>',
      "orchestration-timeline"
    );
  }

  function renderOperationalNotificationsPanel(phase17) {
    var orchestration = (phase17 || {}).orchestration || {};
    var feed = orchestration.notifications || {};
    var notifications = Array.isArray(feed.notifications) ? feed.notifications : [];
    return renderPanelBlock(
      "Operational Notifications",
      "Role-scoped operational notifications with audit references.",
      '<div class="grid-3">' +
        renderMetric("Notifications", String(notifications.length)) +
        renderMetric("Read Only", "true") +
        renderMetric("Advisory Scope", "human_supervised") +
      '</div>' +
      '<ul class="list">' + notifications.slice(0, 8).map(function (row) {
        return '<li><strong>' + escapeHtml(safeText(row.notification_type, "notice")) + '</strong> ' +
          escapeHtml(safeText(row.message, "")) +
          ' <span class="muted">(' + escapeHtml(safeText(row.timestamp, "unknown")) + ')</span></li>';
      }).join("") + '</ul>',
      "orchestration-notifications"
    );
  }

  function renderHandoffTrackerPanel(phase17) {
    var orchestration = (phase17 || {}).orchestration || {};
    var timeline = orchestration.timeline_projection || {};
    var events = Array.isArray(timeline.events) ? timeline.events : [];
    var handoffCount = events.filter(function (row) { return safeText(row.event_type, "") === "handoff"; }).length;
    return renderPanelBlock(
      "Handoff Tracker",
      "Transport handoff pending and supervisor-cleared progression tracking.",
      '<div class="grid-3">' +
        renderMetric("Transport Handoff Pending", String(handoffCount), handoffCount > 0 ? "warn" : "good") +
        renderMetric("Recovery Sequence", String(safeNumber(timeline.next_cursor, 0))) +
        renderMetric("Supervisor Clearance", "required") +
      '</div>',
      "orchestration-handoff"
    );
  }

  function renderQueueHealthDashboardPanel(phase17) {
    var orchestration = (phase17 || {}).orchestration || {};
    var snapshot = orchestration.queue_snapshot || {};
    var health = snapshot.queue_health || {};
    return renderPanelBlock(
      "Queue Stability Dashboard",
      "Backlog review, escalation accumulation, and supervisor-cleared queue posture.",
      '<div class="grid-4">' +
        renderMetric("Backlog Review", String(safeNumber(health.pending, 0))) +
        renderMetric("Supervisor-Cleared", String(safeNumber(health.acknowledged, 0))) +
        renderMetric("Escalation Accumulation", String(safeNumber(health.escalated, 0)), safeNumber(health.escalated, 0) > 0 ? "warn" : "good") +
        renderMetric("Continuity Oversight", "active") +
      '</div>' +
      '<p class="muted">Queue monitoring remains supervisor-governed. No unsupervised queue changes are enabled.</p>',
      "orchestration-health"
    );
  }

  function renderResolutionApprovalQueuePanel(phase17) {
    var orchestration = (phase17 || {}).orchestration || {};
    var live = orchestration.live_stream || {};
    var events = Array.isArray(live.events) ? live.events : [];
    var approvalRows = events.filter(function (row) {
      return safeText(row.event_type, "") === "closure_approval" || safeText(row.event_type, "") === "resolution";
    });
    var approvalsRequired = approvalRows.filter(function (row) {
      var metadata = row.metadata || {};
      return metadata.requires_dual_approval === true;
    }).length;
    return renderPanelBlock(
      "Supervisor Clearance Queue",
      "Continuity escalations and late-stage dispatch adjustments awaiting supervisor clearance.",
      '<div class="grid-4">' +
        renderMetric("Operational Review Queue", String(approvalRows.length)) +
        renderMetric("Override Confirmations", String(approvalsRequired), approvalsRequired > 0 ? "warn" : "neutral") +
        renderMetric("Supervisor Review Active", "yes") +
        renderMetric("Assignment Override", "pending confirmation") +
      '</div>' +
      '<p class="muted">Escalations remain queued until supervisor clearance is completed. No unsupervised task completion is available.</p>',
      "resolution-approval-queue"
    );
  }

  function renderLiveOperationalStreamPanel(phase17) {
    var orchestration = (phase17 || {}).orchestration || {};
    var live = orchestration.live_stream || {};
    var events = Array.isArray(live.events) ? live.events : [];
    var rows = events.slice(0, 14).map(function (row) {
      return '<tr>' +
        '<td>' + escapeHtml(String(row.projection_sequence || "")) + '</td>' +
        '<td>' + escapeHtml(safeText(row.event_type, "event")) + '</td>' +
        '<td>' + escapeHtml(safeText(row.task_id, "unknown")) + '</td>' +
        '<td>' + escapeHtml(safeText(row.timestamp, "unknown")) + '</td>' +
      '</tr>';
    }).join("");
    return renderPanelBlock(
      "Live Dispatch Recovery Stream",
      "Chronological dispatch recovery, provider coordination, and route interruption updates.",
      '<div class="grid-4">' +
        renderMetric("Active Delay Reviews", String(events.length)) +
        renderMetric("Queue Sequence", String(safeNumber(live.next_cursor, 0))) +
        renderMetric("Dispatch Flow Stability", "managed") +
        renderMetric("Service Interruption Prevention", "active") +
      '</div>' +
      (events.length > 0
        ? '<div class="table-wrap"><table class="ops-table"><thead><tr><th>Projection Seq</th><th>Type</th><th>Task</th><th>Timestamp</th></tr></thead><tbody>' + rows + '</tbody></table></div>'
        : '<p class="muted">No live recovery entries are currently posted. Limited coordination visibility remains in effect.</p>'),
      "live-operational-stream"
    );
  }

  function renderSlaAdvisoryMonitorPanel(phase17) {
    var orchestration = (phase17 || {}).orchestration || {};
    var sla = orchestration.sla || {};
    var alerts = Array.isArray(sla.alerts) ? sla.alerts : [];
    return renderPanelBlock(
      "Continuity Threshold Monitor",
      "Queue and escalation threshold visibility for supervisor-led intervention windows.",
      '<div class="grid-4">' +
        renderMetric("Continuity Alerts", String(alerts.length), alerts.length > 0 ? "warn" : "good") +
        renderMetric("Pending Continuity Review", String(safeNumber((sla.metrics || {}).unacknowledged_tasks, 0))) +
        renderMetric("Transport Handoff Pending", String(safeNumber((sla.metrics || {}).unresolved_handoffs, 0))) +
        renderMetric("Escalation Handling", "supervisor-cleared") +
      '</div>' +
      '<p class="muted">Escalation visibility supports supervisor intervention. Automatic escalation decisions remain disabled.</p>',
      "sla-advisory-monitor"
    );
  }

  function renderQueuePressureDashboardPanel(phase17) {
    var orchestration = (phase17 || {}).orchestration || {};
    var queueHealth = orchestration.queue_health || {};
    var pressure = queueHealth.queue_pressure_dashboard || {};
    return renderPanelBlock(
      "Queue Pressure Dashboard",
      "Live queue pressure posture for supervision with audit-safe visibility.",
      '<div class="grid-4">' +
        renderMetric("Pending", String(safeNumber(pressure.pending, 0))) +
        renderMetric("Escalated", String(safeNumber(pressure.escalated, 0)), safeNumber(pressure.escalated, 0) > 0 ? "warn" : "good") +
        renderMetric("Pressure Index", String(safeNumber(pressure.pressure_index, 0)), safeNumber(pressure.pressure_index, 0) >= 15 ? "warn" : "good") +
        renderMetric("Pressure Level", safeText(pressure.pressure_level, "normal")) +
      '</div>' +
      '<p class="muted">Queue pressure metrics are advisory-only and cannot trigger automatic dispatch or queue reprioritization.</p>',
      "queue-pressure-dashboard"
    );
  }

  function renderResolutionAuditTimelinePanel(phase17) {
    var orchestration = (phase17 || {}).orchestration || {};
    var live = orchestration.live_stream || {};
    var events = Array.isArray(live.events) ? live.events : [];
    var auditRows = events.filter(function (row) {
      return safeText(row.event_type, "") === "resolution" || safeText(row.event_type, "") === "closure_approval";
    });
    return renderPanelBlock(
      "Resolution Audit Timeline",
      "Continuity-protected resolution history from verified events and supervisor checkpoints.",
      '<div class="grid-3">' +
        renderMetric("Resolution Events", String(auditRows.length)) +
        renderMetric("Checkpoint", safeText(((live.checkpoint || {}).checkpoint_id), "none")) +
        renderMetric("Continuity Review", "active") +
      '</div>' +
      '<ul class="list">' + auditRows.slice(0, 8).map(function (row) {
        return '<li><strong>' + escapeHtml(safeText(row.event_type, "event")) + '</strong> ' +
          escapeHtml(safeText(row.task_id, "unknown")) +
          ' <span class="muted">(' + escapeHtml(safeText(row.timestamp, "unknown")) + ')</span></li>';
      }).join("") + '</ul>',
      "resolution-audit-timeline"
    );
  }

  function renderExportBundleConsolePanel(phase17) {
    var orchestration = (phase17 || {}).orchestration || {};
    var bundle = orchestration.export_bundle || {};
    return renderPanelBlock(
      "Export Bundle Console",
      "Coordination evidence export with checksum verification.",
      '<div class="grid-4">' +
        renderMetric("Bundle ID", safeText(bundle.bundle_id, "pending")) +
        renderMetric("Bundle Checksum", safeText(bundle.bundle_checksum, "pending")) +
        renderMetric("Chain Tail Hash", safeText(bundle.chain_tail_hash, "pending")) +
        renderMetric("Export Authority", "read_only") +
      '</div>' +
      '<p class="muted">Exports include continuity checkpoints and verified chain records. No destructive export action is possible.</p>',
      "export-bundle-console"
    );
  }

  function renderRegionalOperationsMapPanel() {
    var federation = ((state.ops || {}).federation || {});
    var regions = (((federation.regions || {}).regions) || []);
    return renderPanelBlock(
      "Regional Operations Map",
      "Role-scoped regional topology with isolated governance zones and read-only visibility.",
      '<div class="grid-4">' +
        renderMetric("Regions Visible", String(regions.length)) +
        renderMetric("Isolation Mode", "enabled") +
        renderMetric("Execution", "disabled") +
        renderMetric("Advisory", "true") +
      '</div>' +
      '<ul class="list">' + regions.slice(0, 8).map(function (row) {
        return '<li><strong>' + escapeHtml(safeText(row.region_code, "region")) + '</strong> ' +
          escapeHtml(safeText(row.region_name, "unknown")) +
          ' <span class="muted">(' + escapeHtml(safeText(row.region_id, "unknown")) + ')</span></li>';
      }).join("") + '</ul>',
      "regional-operations-map"
    );
  }

  function renderFederatedQueueMonitorPanel() {
    var federation = ((state.ops || {}).federation || {});
    var queues = (((federation.queues || {}).regions) || []);
    var pendingTotal = queues.reduce(function (sum, row) { return sum + safeNumber(row.pending, 0); }, 0);
    var escalatedTotal = queues.reduce(function (sum, row) { return sum + safeNumber(row.escalated, 0); }, 0);
    return renderPanelBlock(
      "Federated Queue Monitor",
      "Cross-region queue posture with chronological snapshots and continuity records.",
      '<div class="grid-4">' +
        renderMetric("Region Snapshots", String(queues.length)) +
        renderMetric("Pending Total", String(pendingTotal)) +
        renderMetric("Escalated Total", String(escalatedTotal), escalatedTotal > 0 ? "warn" : "good") +
        renderMetric("Continuity Protection Active", "true") +
      '</div>',
      "federated-queue-monitor"
    );
  }

  function renderCapacityForecastConsolePanel() {
    var federation = ((state.ops || {}).federation || {});
    var forecasts = (((federation.capacity || {}).forecasts) || []);
    var highRisk = forecasts.filter(function (row) { return safeText(row.saturation_risk, "") === "high"; }).length;
    return renderPanelBlock(
      "Capacity Forecast Console",
      "Forecasted regional pressure and supervision bottlenecks with advisory-only guidance.",
      '<div class="grid-4">' +
        renderMetric("Forecast Regions", String(forecasts.length)) +
        renderMetric("High Risk", String(highRisk), highRisk > 0 ? "warn" : "good") +
        renderMetric("Window", "next_30m") +
        renderMetric("Automation", "off") +
      '</div>',
      "capacity-forecast-console"
    );
  }

  function renderContinuityProjectionTimelinePanel() {
    var federation = ((state.ops || {}).federation || {});
    var checkpoints = (((federation.continuity || {}).continuity_projection) || []);
    return renderPanelBlock(
      "Continuity Projection Timeline",
      "Regional continuity checkpoints for supervised resilience monitoring and recovery review.",
      '<div class="grid-4">' +
        renderMetric("Checkpoints", String(checkpoints.length)) +
        renderMetric("Degraded", String(checkpoints.filter(function (row) { return safeText(row.continuity_state, "") === "degraded"; }).length), checkpoints.some(function (row) { return safeText(row.continuity_state, "") === "degraded"; }) ? "warn" : "good") +
        renderMetric("Audit-Tracked", "yes") +
        renderMetric("Continuity Review", "active") +
      '</div>',
      "continuity-projection-timeline"
    );
  }

  function renderCrossRegionHandoffViewerPanel() {
    var federation = ((state.ops || {}).federation || {});
    var exportPayload = ((federation.export_bundle || {}).payload || {});
    var regionalEvents = Array.isArray(exportPayload.regional_events) ? exportPayload.regional_events : [];
    var handoffs = regionalEvents.filter(function (row) {
      return safeText(row.event_type, "") === "cross_region_handoff";
    });
    return renderPanelBlock(
      "Cross-Region Handoff Viewer",
      "Handoff lineage surface with no client-side state change authority.",
      '<div class="grid-3">' +
        renderMetric("Handoff Events", String(handoffs.length)) +
        renderMetric("State Changes", "disabled") +
        renderMetric("Manual Approval", "required") +
      '</div>',
      "cross-region-handoff-viewer"
    );
  }

  function renderRegionalGovernanceLedgerPanel() {
    var federation = ((state.ops || {}).federation || {});
    var bundle = federation.export_bundle || {};
    var payload = bundle.payload || {};
    return renderPanelBlock(
      "Regional Governance Ledger",
      "Verified chain checks for federated governance evidence and continuity integrity.",
      '<div class="grid-4">' +
        renderMetric("Bundle ID", safeText(bundle.bundle_id, "pending")) +
        renderMetric("Checksum", safeText(bundle.bundle_checksum, "pending")) +
        renderMetric("Chain Tail", safeText(bundle.chain_tail_hash, "pending")) +
        renderMetric("Event Count", String(safeNumber((payload.replay_reconstruction || {}).event_count, 0))) +
      '</div>',
      "regional-governance-ledger"
    );
  }

  function renderOperationalHealthGridPanel() {
    var federation = ((state.ops || {}).federation || {});
    var rows = (((federation.health || {}).regions) || []);
    return renderPanelBlock(
      "Operational Health Grid",
      "Role-scoped regional health posture combining capacity and continuity indicators.",
      '<div class="grid-4">' +
        renderMetric("Regions", String(rows.length)) +
        renderMetric("Capacity High", String(rows.filter(function (row) { return safeText(row.capacity_risk, "") === "high"; }).length), rows.some(function (row) { return safeText(row.capacity_risk, "") === "high"; }) ? "warn" : "good") +
        renderMetric("Continuity Degraded", String(rows.filter(function (row) { return safeText(row.continuity_state, "") === "degraded"; }).length), rows.some(function (row) { return safeText(row.continuity_state, "") === "degraded"; }) ? "warn" : "good") +
        renderMetric("Regional Isolation", "true") +
      '</div>',
      "operational-health-grid"
    );
  }

  function renderFederatedEvidenceExplorerPanel() {
    var federation = ((state.ops || {}).federation || {});
    var bundle = federation.export_bundle || {};
    var payload = bundle.payload || {};
    var rows = Array.isArray(payload.regional_events) ? payload.regional_events : [];
    return renderPanelBlock(
      "Federated Evidence Explorer",
      "Continuity-protected federated evidence events for audit and supervisory review.",
      '<div class="grid-3">' +
        renderMetric("Evidence Events", String(rows.length)) +
        renderMetric("Ordering", safeText((payload.replay_reconstruction || {}).ordering, "chronological")) +
        renderMetric("Export Authority", "read_only") +
      '</div>' +
      '<ul class="list">' + rows.slice(0, 8).map(function (row) {
        return '<li><strong>' + escapeHtml(safeText(row.event_type, "event")) + '</strong> ' +
          escapeHtml(safeText(row.region_id, "unknown")) +
          ' <span class="muted">(' + escapeHtml(safeText(row.timestamp, "unknown")) + ')</span></li>';
      }).join("") + '</ul>',
      "federated-evidence-explorer"
    );
  }

  function renderOperationsFederation() {
    return [
      renderPanelBlock(
        "Operations Federation",
        "Federated operational intelligence fabric with strict supervisory governance and continuity protection.",
        '<div class="grid-4">' +
          renderMetric("Advisory Only", "true") +
          renderMetric("Execution Disabled", "true") +
          renderMetric("Unsupervised Actions", "disabled") +
          renderMetric("Audit-Tracked", "yes") +
        '</div>' +
        '<p class="muted">All projections and forecasts are guidance-only. No unsupervised dispatch, escalation, or completion is permitted.</p>',
        "operations-federation"
      ),
      renderRegionalOperationsMapPanel(),
      renderFederatedQueueMonitorPanel(),
      renderCapacityForecastConsolePanel(),
      renderContinuityProjectionTimelinePanel(),
      renderCrossRegionHandoffViewerPanel(),
      renderRegionalGovernanceLedgerPanel(),
      renderOperationalHealthGridPanel(),
      renderFederatedEvidenceExplorerPanel()
    ].join("");
  }

  function renderReplayTimelineExplorerPanel() {
    var replay = ((state.ops || {}).replay || {});
    var timeline = replay.timeline || {};
    var events = Array.isArray(timeline.events) ? timeline.events : [];
    return renderPanelBlock(
      "Replay Timeline Explorer",
      "Historical reconstruction with consistent ordering and advisory-only masking.",
      '<div class="grid-4">' +
        renderMetric("Timeline Events", String(events.length)) +
        renderMetric("Ordering", safeText(timeline.ordering, "chronological")) +
        renderMetric("Continuity Protection Active", "true") +
        renderMetric("Audit-Tracked", "yes") +
      '</div>' +
      '<ul class="list">' + events.slice(0, 8).map(function (row) {
        return '<li><strong>' + escapeHtml(safeText(row.event_type, "event")) + '</strong> ' +
          escapeHtml(safeText(row.event_id, "unknown")) +
          ' <span class="muted">(' + escapeHtml(safeText(row.timestamp, "unknown")) + ')</span></li>';
      }).join("") + '</ul>',
      "replay-timeline-explorer"
    );
  }

  function renderOperationalSimulationConsolePanel() {
    var replay = ((state.ops || {}).replay || {});
    var session = replay.session || {};
    var projection = replay.projection || {};
    return renderPanelBlock(
      "Operational Simulation Console",
      "Advisory-only scenario outputs derived from verified continuity history.",
      '<div class="grid-4">' +
        renderMetric("Session ID", safeText(session.replay_session_id, "pending")) +
        renderMetric("Frames", String((Array.isArray(session.frames) ? session.frames : []).length)) +
        renderMetric("Projection Events", String((Array.isArray(projection.events) ? projection.events : []).length)) +
        renderMetric("Execution", "disabled") +
      '</div>',
      "operational-simulation-console"
    );
  }

  function renderTimelineBranchViewerPanel() {
    var branch = (((state.ops || {}).replay || {}).branch || {});
    return renderPanelBlock(
      "Timeline Branch Viewer",
      "Branch lineage and checksum verification for replay experimentation.",
      '<div class="grid-4">' +
        renderMetric("Branch ID", safeText(branch.branch_id, "pending")) +
        renderMetric("Branch Type", safeText(branch.branch_type, "deterministic_replay")) +
        renderMetric("Base Checksum", safeText(branch.base_checksum, "pending")) +
        renderMetric("Branch Checksum", safeText(branch.branch_checksum, "pending")) +
      '</div>',
      "timeline-branch-viewer"
    );
  }

  function renderForecastComparisonGridPanel() {
    var comparison = (((state.ops || {}).replay || {}).comparison || {});
    var rows = Array.isArray(comparison.comparisons) ? comparison.comparisons : [];
    return renderPanelBlock(
      "Forecast Comparison Grid",
      "Baseline versus simulated outcome comparison with advisory-only deltas.",
      '<div class="grid-4">' +
        renderMetric("Comparison Rows", String(rows.length)) +
        renderMetric("Advisory Only", "true") +
        renderMetric("Replay Safe", "true") +
        renderMetric("Audit-Tracked", "yes") +
      '</div>' +
      '<ul class="list">' + rows.map(function (row) {
        return '<li><strong>' + escapeHtml(safeText(row.comparison_metric, "metric")) + '</strong> ' +
          escapeHtml(String(safeNumber(row.delta_value, 0))) + '</li>';
      }).join("") + '</ul>',
      "forecast-comparison-grid"
    );
  }

  function renderContinuityReplayDashboardPanel() {
    var continuity = (((state.ops || {}).replay || {}).continuity || {});
    return renderPanelBlock(
      "Continuity Replay Dashboard",
      "Continuity validation with verified history and supervisor scoring.",
      '<div class="grid-4">' +
        renderMetric("State", safeText(continuity.continuity_state, "pending")) +
        renderMetric("Score", String(safeNumber(continuity.continuity_score, 0))) +
        renderMetric("Validation", safeText(continuity.validation_checksum, "pending")) +
        renderMetric("Execution", "disabled") +
      '</div>',
      "continuity-replay-dashboard"
    );
  }

  function renderReplayEvidenceLedgerPanel() {
    var replay = ((state.ops || {}).replay || {});
    var bundle = replay.evidence || {};
    var payload = bundle.payload || {};
    var rows = Array.isArray(payload.replay_events) ? payload.replay_events : [];
    return renderPanelBlock(
      "Replay Evidence Ledger",
      "Continuity evidence chain with checksum and history visibility.",
      '<div class="grid-4">' +
        renderMetric("Evidence Events", String(rows.length)) +
        renderMetric("Bundle Checksum", safeText(bundle.bundle_checksum, "pending")) +
        renderMetric("Chain Tail", safeText(bundle.chain_tail_hash, "pending")) +
        renderMetric("Export Authority", "read_only") +
      '</div>',
      "replay-evidence-ledger"
    );
  }

  function renderSimulationGovernanceInspectorPanel() {
    var replay = ((state.ops || {}).replay || {});
    var session = replay.session || {};
    var scenario = replay.scenario || {};
    return renderPanelBlock(
      "Simulation Governance Inspector",
      "Governance envelope showing advisory-only continuity review and scenario controls.",
      '<div class="grid-4">' +
        renderMetric("Session", safeText(session.replay_session_id, "pending")) +
        renderMetric("Scenario", safeText(scenario.scenario_id, "pending")) +
        renderMetric("Advisory", "true") +
        renderMetric("State Changes", "disabled") +
      '</div>',
      "simulation-governance-inspector"
    );
  }

  function renderHistoricalReconstructionViewerPanel() {
    var replay = ((state.ops || {}).replay || {});
    var timeline = replay.timeline || {};
    var events = Array.isArray(timeline.events) ? timeline.events : [];
    return renderPanelBlock(
      "Historical Reconstruction Viewer",
      "Source history, continuity ordering, and reconstruction visibility for verified records.",
      '<div class="grid-3">' +
        renderMetric("Reconstructed Events", String(events.length)) +
        renderMetric("Ordering", safeText(timeline.ordering, "deterministic")) +
        renderMetric("Continuity Protection Active", "true") +
      '</div>',
      "historical-reconstruction-viewer"
    );
  }

  function renderGovernancePredictionCenterPanel() {
    var predictive = ((state.ops || {}).predictive || {});
    var governance = predictive.governance || {};
    return renderPanelBlock(
      "Governance Prediction Center",
      "Advisory scorecards for governance pressure, verified history, and continuity-protected projections.",
      '<div class="grid-4">' +
        renderMetric("Score", safeText(governance.governance_score, "n/a")) +
        renderMetric("Label", safeText(governance.prediction_label, "n/a")) +
        renderMetric("Scope", safeText(governance.prediction_scope, "n/a")) +
        renderMetric("Advisory", "true") +
      '</div>' +
      '<p class="muted">Predictions remain advisory-only and do not alter operational state.</p>',
      "governance-prediction-center"
    );
  }

  function renderConstraintIntelligenceGridPanel() {
    var predictive = ((state.ops || {}).predictive || {});
    var constraints = predictive.constraints || {};
    var violations = Array.isArray(constraints.constraint_violation_projections) ? constraints.constraint_violation_projections : [];
    var violationHtml = violations.length > 0 ? '<ul class="list">' + violations.map(function (item) { return '<li><strong>' + escapeHtml(safeText(item.constraint_name, "constraint")) + '</strong><span class="muted"> probability ' + escapeHtml(safeText(item.violation_probability, "0")) + '</span></li>'; }).join("") + '</ul>' : '<p class="muted">No constraint projections are hydrated yet.</p>';
    return renderPanelBlock(
      "Constraint Intelligence Grid",
      "Constraint-aware pressure analysis, violation projection ranking, and advisory continuity records.",
      '<div class="grid-4">' +
        renderMetric("Status", safeText(constraints.constraint_status, "n/a")) +
        renderMetric("Pressure", safeText(constraints.pressure_score, "n/a")) +
        renderMetric("Domain", safeText(constraints.constraint_domain, "n/a")) +
        renderMetric("Advisory", "true") +
      '</div>' + violationHtml,
      "constraint-intelligence-grid"
    );
  }

  function renderCapacityForecastMatrixPanel() {
    var predictive = ((state.ops || {}).predictive || {});
    var capacity = predictive.capacity || {};
    return renderPanelBlock(
      "Capacity Forecast Matrix",
      "Capacity pressure projection with advisory headroom estimates and continuity tracking.",
      '<div class="grid-4">' +
        renderMetric("Projected Capacity", safeText(capacity.projected_capacity, "n/a")) +
        renderMetric("Pressure", safeText(capacity.pressure_score, "n/a")) +
        renderMetric("Scope", safeText(capacity.capacity_scope, "n/a")) +
        renderMetric("Advisory", "true") +
      '</div>',
      "capacity-forecast-matrix"
    );
  }

  function renderRiskProjectionExplorerPanel() {
    var predictive = ((state.ops || {}).predictive || {});
    var risk = predictive.risk || {};
    return renderPanelBlock(
      "Risk Projection Explorer",
      "Risk surface ranking with advisory forecasts and continuity-protected ordering.",
      '<div class="grid-4">' +
        renderMetric("Risk Level", safeText(risk.risk_level, "n/a")) +
        renderMetric("Risk Score", safeText(risk.risk_score, "n/a")) +
        renderMetric("Domain", safeText(risk.risk_domain, "n/a")) +
        renderMetric("Advisory", "true") +
      '</div>',
      "risk-projection-explorer"
    );
  }

  function renderGovernanceDriftMonitorPanel() {
    var predictive = ((state.ops || {}).predictive || {});
    var drift = predictive.drift || {};
    var rows = Array.isArray(drift.drift_events) ? drift.drift_events : [];
    var rowHtml = rows.length > 0 ? '<ul class="list">' + rows.map(function (item) { return '<li><strong>' + escapeHtml(safeText(item.drift_dimension, "drift")) + '</strong><span class="muted"> score ' + escapeHtml(safeText(item.drift_score, "0")) + '</span></li>'; }).join("") + '</ul>' : '<p class="muted">No drift events are hydrated yet.</p>';
    return renderPanelBlock(
      "Governance Drift Monitor",
      "Governance drift scoring for advisory supervision and verified evidence history.",
      '<div class="grid-4">' +
        renderMetric("Drift Events", String(rows.length)) +
        renderMetric("Advisory", "true") +
        renderMetric("Execution", "disabled") +
        renderMetric("Continuity Protection Active", "true") +
      '</div>' + rowHtml,
      "governance-drift-monitor"
    );
  }

  function renderOptimizationRecommendationLedgerPanel() {
    var predictive = ((state.ops || {}).predictive || {});
    var recommendations = predictive.recommendations || {};
    var rows = Array.isArray(recommendations.recommendations) ? recommendations.recommendations : [];
    var rowHtml = rows.length > 0 ? '<ol class="list">' + rows.map(function (item) { return '<li><strong>' + escapeHtml(safeText(item.recommendation_title, "recommendation")) + '</strong><span class="muted"> rank ' + escapeHtml(safeText(item.recommendation_rank, "0")) + '</span></li>'; }).join("") + '</ol>' : '<p class="muted">No recommendations are hydrated yet.</p>';
    return renderPanelBlock(
      "Optimization Recommendation Ledger",
      "Constraint-safe recommendation ranking that remains advisory-only and audit-tracked.",
      '<div class="grid-4">' +
        renderMetric("Recommendations", String(rows.length)) +
        renderMetric("Advisory", "true") +
        renderMetric("Execution", "disabled") +
        renderMetric("Audit-Tracked", "yes") +
      '</div>' + rowHtml,
      "optimization-recommendation-ledger"
    );
  }

  function renderOperationalAnomalyForecastViewerPanel() {
    var predictive = ((state.ops || {}).predictive || {});
    var anomaly = predictive.anomaly || {};
    var rows = Array.isArray(anomaly.anomalies) ? anomaly.anomalies : [];
    var rowHtml = rows.length > 0 ? '<ul class="list">' + rows.map(function (item) { return '<li><strong>' + escapeHtml(safeText(item.anomaly_type, "anomaly")) + '</strong><span class="muted"> score ' + escapeHtml(safeText(item.anomaly_score, "0")) + '</span></li>'; }).join("") + '</ul>' : '<p class="muted">No anomaly forecasts are hydrated yet.</p>';
    return renderPanelBlock(
      "Operational Anomaly Forecast Viewer",
      "Advisory anomaly projections with continuity records and continuity-protected ordering.",
      '<div class="grid-4">' +
        renderMetric("Advisory", "true") +
        renderMetric("Anomalies", String(rows.length)) +
        renderMetric("Execution", "disabled") +
        renderMetric("Continuity Protection Active", "true") +
      '</div>' + rowHtml,
      "operational-anomaly-forecast-viewer"
    );
  }

  function renderGovernanceTrendAnalysisBoardPanel() {
    var predictive = ((state.ops || {}).predictive || {});
    var trends = predictive.trends || {};
    var rows = Array.isArray(trends.trends) ? trends.trends : [];
    var rowHtml = rows.length > 0 ? '<ul class="list">' + rows.map(function (item) { return '<li><strong>' + escapeHtml(safeText(item.trend_metric, "trend")) + '</strong><span class="muted"> slope ' + escapeHtml(safeText(item.trend_slope, "0")) + '</span></li>'; }).join("") + '</ul>' : '<p class="muted">No trend analysis is hydrated yet.</p>';
    return renderPanelBlock(
      "Governance Trend Analysis Board",
      "Historical governance trend aggregation with consistent advisory ordering.",
      '<div class="grid-4">' +
        renderMetric("Trend Rows", String(rows.length)) +
        renderMetric("Advisory", "true") +
        renderMetric("Execution", "disabled") +
        renderMetric("Continuity Protection Active", "true") +
      '</div>' + rowHtml,
      "governance-trend-analysis-board"
    );
  }

  function renderOperationsPredictive() {
    return [
      renderPanelBlock(
        "Operations Predictive",
        "Predictive governance intelligence and constraint-aware advisory projections over verified historical records.",
        '<div class="grid-4">' +
          renderMetric("Advisory Only", "true") +
          renderMetric("Execution Disabled", "true") +
          renderMetric("Unsupervised Actions", "disabled") +
          renderMetric("Audit-Tracked", "yes") +
        '</div>' +
        '<p class="muted">Predictive intelligence remains read-only and never mutates operational state.</p>',
        "operations-predictive"
      ),
      renderGovernancePredictionCenterPanel(),
      renderConstraintIntelligenceGridPanel(),
      renderCapacityForecastMatrixPanel(),
      renderRiskProjectionExplorerPanel(),
      renderGovernanceDriftMonitorPanel(),
      renderOptimizationRecommendationLedgerPanel(),
      renderOperationalAnomalyForecastViewerPanel(),
      renderGovernanceTrendAnalysisBoardPanel()
    ].join("");
  }

  function renderGovernanceProvenanceExplorerPanel() {
    var governance = ((state.ops || {}).governance || {});
    var provenance = governance.provenance || {};
    return renderPanelBlock(
      "Governance Provenance Explorer",
      "Deterministic decision provenance scoring with immutable ancestry and advisory-only constraints.",
      '<div class="grid-4">' +
        renderMetric("Scope", safeText(provenance.decision_scope, "n/a")) +
        renderMetric("Provenance Score", safeText(provenance.provenance_score, "n/a")) +
        renderMetric("Status", safeText(provenance.provenance_status, "traceable")) +
        renderMetric("Advisory", "true") +
      '</div>',
      "governance-provenance-explorer"
    );
  }

  function renderAdvisoryReasoningTimelinePanel() {
    var governance = ((state.ops || {}).governance || {});
    var reasoning = governance.reasoning || {};
    var steps = Array.isArray(reasoning.rationale_steps) ? reasoning.rationale_steps : [];
    var rowHtml = steps.length > 0 ? '<ol class="list">' + steps.map(function (item) {
      var payload = item.rationale_json || {};
      return '<li><strong>' + escapeHtml(safeText(payload.event_type, "reasoning")) + '</strong><span class="muted"> depth ' + escapeHtml(safeText(payload.depth, "0")) + '</span></li>';
    }).join("") + '</ol>' : '<p class="muted">No advisory reasoning steps are hydrated yet.</p>';
    return renderPanelBlock(
      "Advisory Reasoning Timeline",
      "Explainable reasoning reconstruction with deterministic step ordering and immutable lineage.",
      '<div class="grid-4">' +
        renderMetric("Chain Depth", safeText(reasoning.chain_depth, "0")) +
        renderMetric("Steps", String(steps.length)) +
        renderMetric("Execution", "disabled") +
        renderMetric("Replay Safe", "true") +
      '</div>' + rowHtml,
      "advisory-reasoning-timeline"
    );
  }

  function renderOperationalMemoryLedgerPanel() {
    var governance = ((state.ops || {}).governance || {});
    var memoryContainer = governance.memory || {};
    var memory = memoryContainer.memory || {};
    return renderPanelBlock(
      "Operational Memory Ledger",
      "Long-horizon governance memory snapshots preserved as append-only advisory evidence.",
      '<div class="grid-4">' +
        renderMetric("Memory Window", safeText(memory.memory_window, "n/a")) +
        renderMetric("Memory Density", safeText(memory.memory_density, "n/a")) +
        renderMetric("Audit-Tracked", "yes") +
        renderMetric("Replay Safe", "true") +
      '</div>',
      "operational-memory-ledger"
    );
  }

  function renderGovernanceExplanationViewerPanel() {
    var governance = ((state.ops || {}).governance || {});
    var explanations = governance.explanations || {};
    var explanation = explanations.explanation || {};
    return renderPanelBlock(
      "Governance Explanation Viewer",
      "Explainable advisory rationale with immutable reconstruction metadata.",
      '<div class="grid-4">' +
        renderMetric("Scope", safeText(explanations.explanation_scope, "n/a")) +
        renderMetric("Confidence", safeText(explanations.explanation_confidence, "n/a")) +
        renderMetric("Summary", safeText(explanation.summary, "advisory explanation")) +
        renderMetric("Explainable", "true") +
      '</div>',
      "governance-explanation-viewer"
    );
  }

  function renderRecommendationLineageMatrixPanel() {
    var governance = ((state.ops || {}).governance || {});
    var lineage = governance.lineage || {};
    var steps = Array.isArray(((lineage.lineage || {}).lineage_steps)) ? (lineage.lineage || {}).lineage_steps : [];
    var rowHtml = steps.length > 0 ? '<ul class="list">' + steps.map(function (item) {
      return '<li><strong>' + escapeHtml(safeText(item.event_type, "event")) + '</strong><span class="muted"> depth ' + escapeHtml(safeText(item.depth, "0")) + ' weight ' + escapeHtml(safeText(item.weight, "0")) + '</span></li>';
    }).join("") + '</ul>' : '<p class="muted">No recommendation lineage steps are hydrated yet.</p>';
    return renderPanelBlock(
      "Recommendation Lineage Matrix",
      "Recommendation ancestry tracing with deterministic lineage traversal and immutable audit refs.",
      '<div class="grid-4">' +
        renderMetric("Lineage Depth", safeText(lineage.lineage_depth, "0")) +
        renderMetric("Steps", String(steps.length)) +
        renderMetric("Advisory", "true") +
        renderMetric("Execution", "disabled") +
      '</div>' + rowHtml,
      "recommendation-lineage-matrix"
    );
  }

  function renderHistoricalGovernanceReconstructionPanel() {
    var governance = ((state.ops || {}).governance || {});
    var history = governance.history || {};
    var historical = history.historical_state || {};
    return renderPanelBlock(
      "Historical Governance Reconstruction",
      "Deterministic historical governance state reconstruction from immutable ancestry.",
      '<div class="grid-4">' +
        renderMetric("Window", safeText(history.memory_window, "n/a")) +
        renderMetric("State Score", safeText(historical.state_score, "n/a")) +
        renderMetric("Hydration Safe", "true") +
        renderMetric("Replay Safe", "true") +
      '</div>',
      "historical-governance-reconstruction"
    );
  }

  function renderLongHorizonTrendExplorerPanel() {
    var governance = ((state.ops || {}).governance || {});
    var trends = governance.trends || {};
    return renderPanelBlock(
      "Long-Horizon Trend Explorer",
      "Long-horizon trend memory stitching over cross-phase governance history.",
      '<div class="grid-4">' +
        renderMetric("Trend Window", safeText(trends.trend_window, "n/a")) +
        renderMetric("Trend Strength", safeText(trends.trend_strength, "n/a")) +
        renderMetric("Advisory", "true") +
        renderMetric("Audit-Tracked", "yes") +
      '</div>',
      "long-horizon-trend-explorer"
    );
  }

  function renderDecisionContextViewerPanel() {
    var governance = ((state.ops || {}).governance || {});
    var memoryContainer = governance.memory || {};
    var context = memoryContainer.decision_context || {};
    return renderPanelBlock(
      "Decision Context Viewer",
      "Explainable decision context reconstruction with immutable audit ancestry.",
      '<div class="grid-4">' +
        renderMetric("Scope", safeText(context.decision_scope, "n/a")) +
        renderMetric("Context Reconstructed", safeText((((context.decision_context || {}).context_reconstructed) ? "true" : "false"), "false")) +
        renderMetric("Explainable", "true") +
        renderMetric("Execution", "disabled") +
      '</div>',
      "decision-context-viewer"
    );
  }

  function renderGovernancePolicyMatrixPanel() {
    var governance = ((state.ops || {}).governance || {});
    var matrix = governance.policyMatrix || {};
    var rows = Array.isArray(matrix.policy_matrix) ? matrix.policy_matrix : [];
    var rowHtml = rows.length ? '<ul class="list">' + rows.slice(0, 8).map(function (item) {
      return '<li><strong>' + escapeHtml(safeText(item.framework_name, 'framework')) + '</strong><span class="muted"> ' + escapeHtml(safeText(item.rule_code, 'rule')) + ' / ' + escapeHtml(safeText(item.policy_category, 'policy')) + '</span></li>';
    }).join('') + '</ul>' : '<p class="muted">No policy matrix rows are hydrated yet.</p>';
    return renderPanelBlock(
      "Governance Policy Matrix",
      "Deterministic policy rows with immutable lineage references and explainable weighting metadata.",
      '<div class="grid-4">' +
        renderMetric("Policies", String(rows.length)) +
        renderMetric("Versions", String((Array.isArray(matrix.constraint_versions) ? matrix.constraint_versions.length : 0))) +
        renderMetric("Advisory", "true") +
        renderMetric("Replay Safe", "true") +
      '</div>' + rowHtml,
      "governance-policy-matrix"
    );
  }

  function renderRegulatoryFrameworkExplorerPanel() {
    var governance = ((state.ops || {}).governance || {});
    var frameworks = governance.policyFrameworks || {};
    var rows = Array.isArray(frameworks.frameworks) ? frameworks.frameworks : [];
    var rowHtml = rows.length ? '<ul class="list">' + rows.slice(0, 8).map(function (item) {
      return '<li><strong>' + escapeHtml(safeText(item.framework_name, 'framework')) + '</strong><span class="muted"> family ' + escapeHtml(safeText(item.regulation_family, 'family')) + '</span></li>';
    }).join('') + '</ul>' : '<p class="muted">No framework mappings are hydrated yet.</p>';
    return renderPanelBlock(
      "Regulatory Framework Explorer",
      "Cross-framework mapping view for SOC2, ISO27001, HIPAA, NIST, GDPR, PCI-DSS, and internal governance policy alignment.",
      '<div class="grid-4">' +
        renderMetric("Frameworks", String(rows.length)) +
        renderMetric("Mapped Families", String(rows.length)) +
        renderMetric("Deterministic", "true") +
        renderMetric("Advisory", "true") +
      '</div>' + rowHtml,
      "regulatory-framework-explorer"
    );
  }

  function renderConstraintEvaluationTimelinePanel() {
    var governance = ((state.ops || {}).governance || {});
    var evaluations = governance.policyEvaluations || {};
    var rows = Array.isArray(evaluations.constraint_evaluations) ? evaluations.constraint_evaluations : [];
    var rowHtml = rows.length ? '<ol class="list">' + rows.slice(0, 8).map(function (item) {
      return '<li><strong>' + escapeHtml(safeText(item.policy_id, 'policy')) + '</strong><span class="muted"> ' + escapeHtml(safeText(item.evaluation_status, 'status')) + ' / score ' + escapeHtml(safeText(item.evaluation_score, '0')) + '</span></li>';
    }).join('') + '</ol>' : '<p class="muted">No constraint evaluations are hydrated yet.</p>';
    return renderPanelBlock(
      "Constraint Evaluation Timeline",
      "Constraint evaluation ordering over immutable evidence refs and explainable policy scoring inputs.",
      '<div class="grid-4">' +
        renderMetric("Evaluations", String(rows.length)) +
        renderMetric("Violations", String((Array.isArray(evaluations.constraint_violations) ? evaluations.constraint_violations.length : 0))) +
        renderMetric("Execution", "disabled") +
        renderMetric("Audit-Tracked", "yes") +
      '</div>' + rowHtml,
      "constraint-evaluation-timeline"
    );
  }

  function renderGovernanceScoreViewerPanel() {
    var governance = ((state.ops || {}).governance || {});
    var score = governance.policyScore || {};
    var snapshot = score.score_snapshot || {};
    return renderPanelBlock(
      "Governance Score Viewer",
      "Explainable weighted governance score with deterministic contributing weights and replay lineage references.",
      '<div class="grid-4">' +
        renderMetric("Weighted Score", safeText(score.weighted_score, 'n/a')) +
        renderMetric("Status", safeText(score.score_status, 'n/a')) +
        renderMetric("Scope", safeText(score.policy_scope, 'n/a')) +
        renderMetric("Evidence Refs", String((Array.isArray(snapshot.evidence_lineage_refs) ? snapshot.evidence_lineage_refs.length : 0))) +
      '</div>',
      "governance-score-viewer"
    );
  }

  function renderPolicyRationaleChainViewerPanel() {
    var governance = ((state.ops || {}).governance || {});
    var rationale = governance.rationaleChain || {};
    var rows = Array.isArray(rationale.rationale_chain) ? rationale.rationale_chain : [];
    var rowHtml = rows.length ? '<ol class="list">' + rows.map(function (item) {
      var payload = item.chain_payload || {};
      var constraint = payload.constraint || {};
      return '<li><strong>' + escapeHtml(safeText(constraint.policy_id, 'policy')) + '</strong><span class="muted"> ' + escapeHtml(safeText(constraint.framework_name, 'framework')) + '</span></li>';
    }).join('') + '</ol>' : '<p class="muted">No policy rationale chain is hydrated yet.</p>';
    return renderPanelBlock(
      "Policy Rationale Chain Viewer",
      "Immutable rationale segments showing how governance policy logic remained explainable under replay.",
      '<div class="grid-4">' +
        renderMetric("Decision Id", safeText(rationale.decision_id, 'n/a')) +
        renderMetric("Chain Rows", String(rows.length)) +
        renderMetric("Explainable", "true") +
        renderMetric("Replay Safe", "true") +
      '</div>' + rowHtml,
      "policy-rationale-chain-viewer"
    );
  }

  function renderConstraintViolationLedgerPanel() {
    var governance = ((state.ops || {}).governance || {});
    var violations = governance.policyViolations || {};
    var rows = Array.isArray(violations.violations) ? violations.violations : [];
    var rowHtml = rows.length ? '<ul class="list">' + rows.map(function (item) {
      return '<li><strong>' + escapeHtml(safeText(item.policy_id, 'policy')) + '</strong><span class="muted"> ' + escapeHtml(safeText(item.violation_level, 'level')) + ' / ' + escapeHtml(safeText(item.rule_code, 'rule')) + '</span></li>';
    }).join('') + '</ul>' : '<p class="muted">No policy violations are currently hydrated.</p>';
    return renderPanelBlock(
      "Constraint Violation Ledger",
      "Append-only violation ledger with immutable rule ancestry and advisory-only remediation posture.",
      '<div class="grid-4">' +
        renderMetric("Violations", String(rows.length)) +
        renderMetric("Execution", "disabled") +
        renderMetric("Unsupervised Actions", "disabled") +
        renderMetric("Advisory", "true") +
      '</div>' + rowHtml,
      "constraint-violation-ledger"
    );
  }

  function renderGovernanceRiskHeatmapPanel() {
    var governance = ((state.ops || {}).governance || {});
    var risk = governance.risk || {};
    return renderPanelBlock(
      "Governance Risk Heatmap",
      "Operational risk summary driven by deterministic policy scoring, evidence density, and immutable lineage stability.",
      '<div class="grid-4">' +
        renderMetric("Risk Score", safeText(risk.risk_score, 'n/a')) +
        renderMetric("Risk Level", safeText(risk.risk_level, 'n/a')) +
        renderMetric("Recommendations", String((Array.isArray(risk.recommendations) ? risk.recommendations.length : 0))) +
        renderMetric("Replay Safe", "true") +
      '</div>',
      "governance-risk-heatmap"
    );
  }

  function renderExplainableRecommendationViewerPanel() {
    var governance = ((state.ops || {}).governance || {});
    var risk = governance.risk || {};
    var rows = Array.isArray(risk.recommendations) ? risk.recommendations : [];
    var rowHtml = rows.length ? '<ol class="list">' + rows.map(function (item) {
      return '<li><strong>' + escapeHtml(safeText(item.framework_name, 'framework')) + '</strong><span class="muted"> ' + escapeHtml(safeText(item.summary, 'recommendation')) + '</span></li>';
    }).join('') + '</ol>' : '<p class="muted">No explainable recommendations are hydrated yet.</p>';
    return renderPanelBlock(
      "Explainable Recommendation Viewer",
      "Advisory-only recommendations derived from deterministic violations and policy score provenance.",
      '<div class="grid-4">' +
        renderMetric("Recommendations", String(rows.length)) +
        renderMetric("Advisory", "true") +
        renderMetric("Execution", "disabled") +
        renderMetric("Audit-Tracked", "yes") +
      '</div>' + rowHtml,
      "explainable-recommendation-viewer"
    );
  }

  function renderOperationsGovernance() {
    return [
      renderPanelBlock(
        "Operations Governance",
        "Multi-layer governance memory and decision provenance fabric with immutable advisory lineage.",
        '<div class="grid-4">' +
          renderMetric("Advisory Only", "true") +
          renderMetric("Execution Disabled", "true") +
          renderMetric("Unsupervised Actions", "disabled") +
          renderMetric("Audit-Tracked", "yes") +
        '</div>' +
        '<p class="muted">Governance memory and provenance surfaces remain explainable, deterministic, and read-only.</p>',
        "operations-governance"
      ),
      renderGovernanceProvenanceExplorerPanel(),
      renderAdvisoryReasoningTimelinePanel(),
      renderOperationalMemoryLedgerPanel(),
      renderGovernanceExplanationViewerPanel(),
      renderRecommendationLineageMatrixPanel(),
      renderHistoricalGovernanceReconstructionPanel(),
      renderLongHorizonTrendExplorerPanel(),
      renderDecisionContextViewerPanel(),
      renderGovernancePolicyMatrixPanel(),
      renderRegulatoryFrameworkExplorerPanel(),
      renderConstraintEvaluationTimelinePanel(),
      renderGovernanceScoreViewerPanel(),
      renderPolicyRationaleChainViewerPanel(),
      renderConstraintViolationLedgerPanel(),
      renderGovernanceRiskHeatmapPanel(),
      renderExplainableRecommendationViewerPanel()
    ].join("");
  }

  function renderOperationsReplay() {
    return [
      renderPanelBlock(
        "Operations Replay",
        "Operational continuity review and advisory simulation over verified historical records.",
        '<div class="grid-4">' +
          renderMetric("Advisory Only", "true") +
          renderMetric("Execution Disabled", "true") +
          renderMetric("Unsupervised Actions", "disabled") +
          renderMetric("Continuity Protection", "active") +
        '</div>' +
        '<p class="muted">Continuity review reads verified history only. No live state changes or destructive history rewrite is possible.</p>',
        "operations-replay"
      ),
      renderReplayTimelineExplorerPanel(),
      renderOperationalSimulationConsolePanel(),
      renderTimelineBranchViewerPanel(),
      renderForecastComparisonGridPanel(),
      renderContinuityReplayDashboardPanel(),
      renderReplayEvidenceLedgerPanel(),
      renderSimulationGovernanceInspectorPanel(),
      renderHistoricalReconstructionViewerPanel()
    ].join("");
  }

  function buildRoleHydrationSlice(role, phase17) {
    var source = phase17 || {};
    var workflowTimeline = source?.workflowTimeline ?? [];
    var eventPreview = source?.eventPreview ?? [];
    var events = source?.events ?? [];
    var lifecycle = source?.lifecycle ?? {};
    var driverStates = source?.driverStates ?? {};
    var providerStates = source?.providerStates ?? {};
    var supervision = source?.supervision ?? {};
    var workspaceActivation = state.ops.workspaceActivation || {};
    var workspaceModules = safeObject(workspaceActivation.workspace_modules);
    var workspaceTimeline = Array.isArray(workspaceModules.escalation_audit_timeline) ? workspaceModules.escalation_audit_timeline : [];
    var dashboardSummary = state.ops.dashboardSummary || {};
    var sharedTimeline = workflowTimeline.concat(eventPreview).concat(events).concat(workspaceTimeline);
    var hasOperationalData = Boolean(
      Array.isArray(phase17?.workflowTimeline) ||
      Array.isArray(phase17?.eventPreview) ||
      Array.isArray(phase17?.events) ||
      (phase17 && typeof phase17 === "object" && Object.keys(phase17).length > 0)
    );
    var shared = {
      sliceRole: role,
      advisoryOnly: safeText((dashboardSummary.governance || {}).advisory_only, true),
      executionDisabled: safeText((dashboardSummary.governance || {}).execution_disabled, true),
      replaySafe: safeText((dashboardSummary.audit_metadata || {}).replay_safe, true),
      appendOnly: true,
      alerts: Array.isArray(state.ops.alerts) ? state.ops.alerts : [],
      workflowTimeline: workflowTimeline,
      timeline: sharedTimeline,
      metrics: {},
      routes: [],
      queue: [],
      recommendations: Array.isArray(state.ops.recommendations) ? state.ops.recommendations : [],
      workspaceModules: workspaceModules,
      allowedActions: Array.isArray(workspaceActivation.allowed_actions) ? workspaceActivation.allowed_actions : [],
      hasOperationalData: hasOperationalData
    };

    if (role === "dispatcher") {
      return {
        sliceRole: "dispatcher",
        advisoryOnly: shared.advisoryOnly,
        executionDisabled: shared.executionDisabled,
        replaySafe: shared.replaySafe,
        appendOnly: shared.appendOnly,
        alerts: shared.alerts,
        workflowTimeline: shared.workflowTimeline,
        timeline: shared.timeline,
        metrics: shared.metrics,
        routes: shared.routes,
        queue: shared.queue,
        recommendations: shared.recommendations,
        hasOperationalData: shared.hasOperationalData,
        activeTrips: safeNumber((lifecycle || {}).IN_PROGRESS, 0),
        pendingQueue: safeNumber((lifecycle || {}).REQUESTED, 0),
        availableDrivers: safeNumber((driverStates || {}).available, 0),
        escalationDepth: Array.isArray((((state.ops.orchestration || {}).sla || {}).alerts)) ? (((state.ops.orchestration || {}).sla || {}).alerts.length) : 0
      };
    }

    if (role === "rider") {
      return {
        sliceRole: "rider",
        advisoryOnly: shared.advisoryOnly,
        executionDisabled: shared.executionDisabled,
        replaySafe: shared.replaySafe,
        appendOnly: shared.appendOnly,
        alerts: shared.alerts,
        workflowTimeline: shared.workflowTimeline,
        timeline: shared.timeline,
        metrics: shared.metrics,
        routes: shared.routes,
        queue: shared.queue,
        recommendations: shared.recommendations,
        hasOperationalData: shared.hasOperationalData,
        rideStatus: safeText((lifecycle || {}).IN_PROGRESS, "0") !== "0" ? "in_progress" : "requested",
        pickup: "Facility pickup pending confirmation",
        dropoff: "Care destination pending confirmation",
        eta: safeText(((state.ops.liveStatus || {}).dispatch_posture || {}).estimated_pickup_eta, "ETA pending dispatch confirmation"),
        assignedDriver: safeText(((state.ops.liveStatus || {}).driver_snapshot || {}).driver_id, "driver assignment pending"),
        assignedProvider: safeText(((state.ops.liveStatus || {}).provider_snapshot || {}).provider_id, "provider match pending")
      };
    }

    if (role === "driver") {
      return {
        sliceRole: "driver",
        advisoryOnly: shared.advisoryOnly,
        executionDisabled: shared.executionDisabled,
        replaySafe: shared.replaySafe,
        appendOnly: shared.appendOnly,
        alerts: shared.alerts,
        workflowTimeline: shared.workflowTimeline,
        timeline: shared.timeline,
        metrics: shared.metrics,
        routes: shared.routes,
        queue: shared.queue,
        recommendations: shared.recommendations,
        hasOperationalData: shared.hasOperationalData,
        opportunities: safeNumber((lifecycle || {}).REQUESTED, 0),
        assignedRide: safeNumber((lifecycle || {}).IN_PROGRESS, 0) > 0 ? "assignment_hydration_ready" : "awaiting_assignment",
        pickupQueue: safeNumber((lifecycle || {}).ASSIGNED, 0),
        shiftStatus: safeText((supervision || {}).supervision_status, "unknown")
      };
    }

    if (role === "provider") {
      return {
        sliceRole: "provider",
        advisoryOnly: shared.advisoryOnly,
        executionDisabled: shared.executionDisabled,
        replaySafe: shared.replaySafe,
        appendOnly: shared.appendOnly,
        alerts: shared.alerts,
        workflowTimeline: shared.workflowTimeline,
        timeline: shared.timeline,
        metrics: shared.metrics,
        routes: shared.routes,
        queue: shared.queue,
        recommendations: shared.recommendations,
        hasOperationalData: shared.hasOperationalData,
        activeRides: safeNumber((lifecycle || {}).IN_PROGRESS, 0),
        activeDrivers: safeNumber((driverStates || {}).available, 0),
        activeProviders: safeNumber((providerStates || {}).active, 0),
        utilization: safeNumber((lifecycle || {}).IN_PROGRESS, 0) + safeNumber((lifecycle || {}).EN_ROUTE, 0)
      };
    }

    if (role === "compliance_officer") {
      return {
        sliceRole: "compliance_officer",
        advisoryOnly: shared.advisoryOnly,
        executionDisabled: shared.executionDisabled,
        replaySafe: shared.replaySafe,
        appendOnly: shared.appendOnly,
        alerts: shared.alerts,
        workflowTimeline: shared.workflowTimeline,
        timeline: shared.timeline,
        metrics: shared.metrics,
        routes: shared.routes,
        queue: shared.queue,
        recommendations: shared.recommendations,
        hasOperationalData: shared.hasOperationalData,
        reviewQueue: Array.isArray((state.ops.compliance || {}).approval_queue) ? state.ops.compliance.approval_queue : [],
        documentCount: Array.isArray((state.ops.compliance || {}).documents) ? state.ops.compliance.documents.length : 0,
        profileCount: Array.isArray((state.ops.compliance || {}).profiles) ? state.ops.compliance.profiles.length : 0
      };
    }

    if (role === "supervisor") {
      return {
        sliceRole: "supervisor",
        advisoryOnly: shared.advisoryOnly,
        executionDisabled: shared.executionDisabled,
        replaySafe: shared.replaySafe,
        appendOnly: shared.appendOnly,
        alerts: shared.alerts,
        timeline: shared.timeline,
        recommendations: shared.recommendations,
        approvalQueueDepth: Array.isArray((state.ops.compliance || {}).approval_queue) ? state.ops.compliance.approval_queue.length : 0,
        escalationQueueDepth: Array.isArray((((state.ops.orchestration || {}).queue_snapshot || {}).tasks)) ? (((state.ops.orchestration || {}).queue_snapshot || {}).tasks.length) : 0,
        activeDrivers: safeNumber((phase17.driverStates || {}).available, 0) + safeNumber((phase17.driverStates || {}).assigned, 0)
      };
    }

    if (role === "driver_support") {
      return {
        sliceRole: "driver_support",
        advisoryOnly: shared.advisoryOnly,
        executionDisabled: shared.executionDisabled,
        replaySafe: shared.replaySafe,
        appendOnly: shared.appendOnly,
        alerts: shared.alerts,
        timeline: shared.timeline,
        recommendations: shared.recommendations,
        onboardingCount: Array.isArray((state.ops.compliance || {}).profiles) ? state.ops.compliance.profiles.length : 0,
        ticketCount: Array.isArray((((state.ops.orchestration || {}).notifications || {}).notifications)) ? (((state.ops.orchestration || {}).notifications || {}).notifications.length) : 0,
        trainingCount: Array.isArray((((state.ops.compliance || {}).phase25 || {}).regulatory_export_builder)) ? (((state.ops.compliance || {}).phase25 || {}).regulatory_export_builder.length) : 0
      };
    }

    if (role === "medical_coordinator") {
      return {
        sliceRole: "medical_coordinator",
        advisoryOnly: shared.advisoryOnly,
        executionDisabled: shared.executionDisabled,
        replaySafe: shared.replaySafe,
        appendOnly: shared.appendOnly,
        alerts: shared.alerts,
        timeline: shared.timeline,
        recommendations: shared.recommendations,
        activePatients: safeNumber((phase17.lifecycle || {}).REQUESTED, 0),
        transportsInProgress: safeNumber((phase17.lifecycle || {}).IN_PROGRESS, 0),
        providerCount: safeNumber((phase17.providerStates || {}).active, 0),
        facilityCount: safeNumber((phase17.providerStates || {}).pending, 0) + safeNumber((phase17.providerStates || {}).active, 0)
      };
    }

    return {
      sliceRole: "admin",
      advisoryOnly: shared.advisoryOnly,
      executionDisabled: shared.executionDisabled,
      replaySafe: shared.replaySafe,
      appendOnly: shared.appendOnly,
      alerts: shared.alerts,
      timeline: shared.timeline,
      recommendations: shared.recommendations,
      activeRides: safeNumber((phase17.lifecycle || {}).IN_PROGRESS, 0),
      driverActivity: safeNumber((phase17.driverStates || {}).available, 0),
      providerActivity: safeNumber((phase17.providerStates || {}).active, 0),
      riderActivity: safeNumber((phase17.lifecycle || {}).REQUESTED, 0)
    };
  }

  function renderEnhancedOperationalTimeline(title, subtitle, timelineItems, limit) {
    var events = Array.isArray(timelineItems) ? timelineItems.slice(0, limit || 10) : [];
    if (events.length === 0) {
      return renderPanelBlock(title, subtitle, '<p class="muted">No timeline updates in the current operational window.</p>', 'timeline');
    }

    var rows = events.map(function (item, index) {
      var sequence = safeText(item.sequence_number || item.sequence || ("seq-" + (index + 1)), "seq-unknown");
      var eventName = timelineHumanTitle(item);
      var severity = timelineSeverityLabel(item);
      var priorityLabel = severity === "HIGH" ? "Transport-Critical" : (severity === "MEDIUM" ? "Continuity-Sensitive" : "Routine Review");
      var category = safeText(item.subsystem || item.workflow_name, "operations");
      var source = safeText(item.source || item.subsystem || "runtime_governor", "runtime_governor");
      if (source === "runtime_governor") {
        source = "operations_control";
      } else if (source === "websocket") {
        source = "live_updates";
      }
      var actor = timelineRoleAssociation(item);
      var ts = safeText(item.timestamp || item.updated_at || item.emitted_at, "");
      var group = timelineTimestampGroup(ts);
      var hydrationState = hydrationIntegrityMeta(state.hydration.integrityState).label;

      return '<tr>' +
        '<td>' + escapeHtml(String(sequence)) + '</td>' +
        '<td><span class="status-dot">' + escapeHtml(titleizeWords(category)) + '</span></td>' +
        '<td>' + escapeHtml(eventName) + '</td>' +
        '<td><span class="badge ' + (severity === "HIGH" ? "badge-bad" : severity === "MEDIUM" ? "badge-warn" : "badge-good") + '">' + escapeHtml(priorityLabel) + '</span></td>' +
        '<td>' + escapeHtml(titleizeWords(actor)) + '</td>' +
        '<td>' + escapeHtml(titleizeWords(source)) + '</td>' +
        '<td>' + escapeHtml(ts) + '</td>' +
        '<td>' + escapeHtml(group) + '</td>' +
        '<td><span class="badge badge-soft">advisory</span></td>' +
        '<td><span class="badge badge-soft">' + escapeHtml(hydrationState) + '</span></td>' +
      '</tr>';
    }).join("");

    return renderPanelBlock(
      title,
      subtitle,
      '<div class="table-wrap"><table class="ops-table"><thead><tr><th>Sequence</th><th>Category</th><th>Event</th><th>Priority</th><th>Role</th><th>Source</th><th>Timestamp</th><th>Group</th><th>Advisory</th><th>Live Access</th></tr></thead><tbody>' + rows + '</tbody></table></div>' +
      '<p class="muted">Timeline rendering remains continuity protected in this surface.</p>',
      'timeline'
    );
  }

  function renderRoleMapPlaceholder(title, description, routeContext) {
    var context = routeContext && typeof routeContext === "object" ? routeContext : {};
    var pickup = safeText(context.pickup || context.pickup_address, "Pickup not set");
    var dropoff = safeText(context.dropoff || context.dropoff_address, "Destination not set");
    return renderPanelBlock(
      title,
      description,
      '<div class="command-map">' +
        '<div class="map-stage-copy"><strong>Map provider not configured</strong><p>Interactive maps require a map provider API key. Live pickup, destination, and route details are shown below.</p></div>' +
        '<div class="health-summary"><strong>Pickup:</strong> ' + escapeHtml(pickup) + '</div>' +
        '<div class="health-summary"><strong>Destination:</strong> ' + escapeHtml(dropoff) + '</div>' +
        '<div class="health-summary"><strong>Route:</strong> ' + escapeHtml(pickup) + ' → ' + escapeHtml(dropoff) + '</div>' +
      '</div>',
      'map'
    );
  }

  function renderRoleAiGuidance(roleLabel, guidance) {
    return renderPanelBlock(
      roleLabel + " AI Guidance",
      "Informational assistant guidance with advisory-only recommendations.",
      '<p>' + escapeHtml(guidance) + '</p>' +
      '<div class="command-actions">' +
        '<button class="preview-action" disabled>Advisory only</button>' +
        '<button class="preview-action" disabled>Supervisor confirmation required</button>' +
      '</div>' +
      '<p class="muted">No automatic dispatch, assignment, approval, escalation, or cancellation is enabled from this panel.</p>',
      'ai advisory'
    );
  }

  function ensureRiderAppState(slice) {
    var profile = riderProfileDefaults();
    if (!state.riderApp || typeof state.riderApp !== "object") {
      state.riderApp = {
        profile: profile,
        activeRequestId: "",
        activeTrip: emptyRiderActiveTrip(),
        recurringSchedule: [],
        notifications: [],
        tripHistory: [],
        lastAction: "Enter your details and request a ride",
        lastSubmit: null
      };
      return;
    }

    state.riderApp.profile = profile;
    if (!state.riderApp.activeTrip || typeof state.riderApp.activeTrip !== "object") {
      state.riderApp.activeTrip = emptyRiderActiveTrip();
    }
    if (!Array.isArray(state.riderApp.tripHistory)) {
      state.riderApp.tripHistory = [];
    }
    if (!Array.isArray(state.riderApp.recurringSchedule)) {
      state.riderApp.recurringSchedule = [];
    }
    if (!Array.isArray(state.riderApp.notifications)) {
      state.riderApp.notifications = [];
    }
  }

  function emptyRiderActiveTrip() {
    return {
      tripId: "",
      status: "none",
      pickup: "",
      dropoff: "",
      etaMin: "",
      driverName: "Awaiting assignment",
      vehicle: "",
      supportContact: "24/7 Rider Care"
    };
  }

  function renderRiderNotifications(notifications) {
    var rows = Array.isArray(notifications) ? notifications : [];
    if (rows.length === 0) {
      return '<p class="muted">No rider notifications.</p>';
    }
    return rows.map(function (item) {
      return '' +
        '<li class="driver-notification ' + escapeHtml(safeText(item.level, 'low')) + '">' +
          '<span>' + escapeHtml(safeText(item.text, 'Notification')) + '</span>' +
          '<small>' + escapeHtml(safeText(item.ts, 'now')) + '</small>' +
          '<button data-rider-action="dismiss_notification" data-note-id="' + escapeHtml(safeText(item.id, '')) + '">Dismiss</button>' +
        '</li>';
    }).join('');
  }

  function renderRiderRecurringRows(items) {
    var rows = Array.isArray(items) ? items : [];
    if (rows.length === 0) {
      return '<p class="muted">No recurring rides yet.</p>';
    }
    return rows.map(function (item) {
      return '<article class="tile"><h4>' + escapeHtml(safeText(item.id, 'REC')) + '</h4><p>' +
        escapeHtml(safeText(item.day, 'Day')) + ' • ' + escapeHtml(safeText(item.time, 'Time')) + '<br>' +
        escapeHtml(safeText(item.destination, 'Destination')) +
      '</p></article>';
    }).join('');
  }

  function renderRiderHistoryRows(items) {
    var rows = Array.isArray(items) ? items : [];
    if (rows.length === 0) {
      return '<p class="muted">No trip history available.</p>';
    }
    var body = rows.map(function (item) {
      return '<tr><td>' + escapeHtml(safeText(item.tripId, 'trip')) + '</td><td>' + escapeHtml(safeText(item.date, 'date')) + '</td><td>' +
        escapeHtml(safeText(item.route, 'route')) + '</td><td><span class="status-dot">' + escapeHtml(titleizeWords(safeText(item.status, 'completed'))) + '</span></td></tr>';
    }).join('');
    return '<div class="table-wrap"><table class="ops-table"><thead><tr><th>Trip ID</th><th>Date</th><th>Route</th><th>Status</th></tr></thead><tbody>' + body + '</tbody></table></div>';
  }

  function renderRiderAppExperience(slice) {
    ensureRiderAppState(slice);
    var riderState = safeObject(state.riderApp);
    var activeTrip = safeObject(riderState.activeTrip);
    var profile = riderProfileDefaults();
    var showReturnSection = safeText(profile.tripType, "one_way") === "round_trip";
    var showRecurrenceSection = safeText(profile.recurrence, "none") === "weekly";
    var showScheduledReturn = showReturnSection && safeText(profile.returnPickupType, "scheduled_time") !== "call_when_ready";
    var notifications = Array.isArray(riderState.notifications) ? riderState.notifications : [];
    var recurring = Array.isArray(riderState.recurringSchedule) ? riderState.recurringSchedule : [];
    var history = Array.isArray(riderState.tripHistory) ? riderState.tripHistory : [];
    var activeRequestId = safeText(riderState.activeRequestId, "");
    var lastSubmit = safeObject(riderState.lastSubmit);
    var submitStatus = safeObject(riderState.submitStatus);
    var submitBanner = "";
    if (safeText(submitStatus.message, "")) {
      var tone = safeText(submitStatus.level, "info");
      var bg = tone === "error" ? "#fef2f2" : (tone === "success" ? "#ecfdf5" : "#eff6ff");
      var border = tone === "error" ? "#fca5a5" : (tone === "success" ? "#86efac" : "#93c5fd");
      var color = tone === "error" ? "#991b1b" : (tone === "success" ? "#065f46" : "#1e3a8a");
      submitBanner =
        '<div class="rider-submit-status" style="margin:12px 0;padding:12px 14px;border-radius:10px;background:' + bg + ';border:1px solid ' + border + ';color:' + color + '">' +
          escapeHtml(safeText(submitStatus.message, "")) +
          (submitStatus.rideId ? ('<br>Ride ID: <code>' + escapeHtml(safeText(submitStatus.rideId, "")) + '</code>') : "") +
          (submitStatus.requestId ? ('<br>Request ID: <code>' + escapeHtml(safeText(submitStatus.requestId, "")) + '</code>') : "") +
          (submitStatus.status ? ('<br>Status: ' + escapeHtml(titleizeWords(safeText(submitStatus.status, "pending")))) : "") +
        '</div>';
    } else if (lastSubmit.rideId) {
      submitBanner =
        '<div class="rider-submit-success" style="margin:12px 0;padding:12px 14px;border-radius:10px;background:#ecfdf5;border:1px solid #86efac;color:#065f46">' +
          '<strong>Ride request submitted.</strong><br>' +
          'Ride ID: <code>' + escapeHtml(safeText(lastSubmit.rideId, "")) + '</code><br>' +
          'Request ID: <code>' + escapeHtml(safeText(lastSubmit.requestId, "")) + '</code><br>' +
          'Status: ' + escapeHtml(titleizeWords(safeText(lastSubmit.status, "pending"))) +
        '</div>';
    }

    var authBanner = "";
    if (isRiderSurfaceAuthenticated()) {
      authBanner =
        '<div class="rider-auth-session" style="margin:12px 0;padding:12px 14px;border-radius:10px;background:#ecfdf5;border:1px solid #86efac;color:#065f46;display:flex;justify-content:space-between;gap:12px;flex-wrap:wrap;align-items:center;">' +
          '<div><strong>Signed in as</strong> ' + escapeHtml(getRiderSurfacePresentation().displayName) + '</div>' +
          '<button type="button" class="preview-action rider-action" data-rider-action="sign_out">Sign Out</button>' +
        '</div>';
    } else {
      authBanner =
        '<div class="rider-auth-required" style="margin:12px 0;padding:12px 14px;border-radius:10px;background:#fff7ed;border:1px solid #fdba74;color:#9a3412">' +
          '<strong>Sign in required.</strong> Log in as a rider to submit ride requests. ' +
          '<button type="button" class="preview-action rider-action" data-rider-action="sign_in">Sign In</button>' +
        '</div>';
    }

    return renderPanelBlock(
      "Rider and Patient App",
      "Request rides, schedule recurring transportation, track live trip ETA, and manage support from a healthcare-first rider surface.",
      submitBanner + authBanner +
      '<div class="rider-app-grid">' +
        '<section class="rider-card">' +
          '<h4>Ride Request</h4>' +
          '<p class="muted">Create immediate or recurring transportation requests with appointment context.</p>' +
          '<div class="grid-2">' +
            '<label class="muted">Rider Name<input id="rider-name-input" type="text" value="' + escapeHtml(safeText(profile.name, "")) + '" placeholder="Your full name" oninput="window._amiUpdateRiderProfileDraft(\'name\', this.value)" style="width:100%;margin-top:6px;padding:10px;border-radius:10px;border:1px solid rgba(15,23,42,0.14);background:#fff"></label>' +
            '<label class="muted">Rider Phone<input id="rider-phone-input" type="text" value="' + escapeHtml(safeText(profile.phone, "")) + '" placeholder="+1 555 123 4567" oninput="window._amiUpdateRiderProfileDraft(\'phone\', this.value)" style="width:100%;margin-top:6px;padding:10px;border-radius:10px;border:1px solid rgba(15,23,42,0.14);background:#fff"></label>' +
            '<label class="muted">Pickup<input id="rider-pickup-input" type="text" value="' + escapeHtml(safeText(profile.pickup, "")) + '" placeholder="Pickup address" oninput="window._amiUpdateRiderProfileDraft(\'pickup\', this.value)" style="width:100%;margin-top:6px;padding:10px;border-radius:10px;border:1px solid rgba(15,23,42,0.14);background:#fff"></label>' +
            '<label class="muted">Dropoff<input id="rider-dropoff-input" type="text" value="' + escapeHtml(safeText(profile.dropoff, "")) + '" placeholder="Dropoff address" oninput="window._amiUpdateRiderProfileDraft(\'dropoff\', this.value)" style="width:100%;margin-top:6px;padding:10px;border-radius:10px;border:1px solid rgba(15,23,42,0.14);background:#fff"></label>' +
            '<label class="muted">Ride Type<select id="rider-ride-type-input" onchange="window._amiUpdateRiderProfileDraft(\'rideType\', this.value)" style="width:100%;margin-top:6px;padding:10px;border-radius:10px;border:1px solid rgba(15,23,42,0.14);background:#fff"><option value="healthcare"' + (safeText(profile.rideType, "healthcare") === "healthcare" ? ' selected' : '') + '>Healthcare</option><option value="work"' + (safeText(profile.rideType, "healthcare") === "work" ? ' selected' : '') + '>Work</option><option value="grocery"' + (safeText(profile.rideType, "healthcare") === "grocery" ? ' selected' : '') + '>Grocery</option><option value="church"' + (safeText(profile.rideType, "healthcare") === "church" ? ' selected' : '') + '>Church</option><option value="personal"' + (safeText(profile.rideType, "healthcare") === "personal" ? ' selected' : '') + '>Personal</option></select></label>' +
            '<label class="muted">Service Date<input id="rider-service-date-input" type="date" value="' + escapeHtml(safeText(profile.serviceDate, "")) + '" oninput="window._amiUpdateRiderProfileDraft(\'serviceDate\', this.value)" style="width:100%;margin-top:6px;padding:10px;border-radius:10px;border:1px solid rgba(15,23,42,0.14);background:#fff"></label>' +
            '<label class="muted">Requested Pickup Time<input id="rider-pickup-time-input" type="time" value="' + escapeHtml(safeText(profile.pickupTime, "")) + '" oninput="window._amiUpdateRiderProfileDraft(\'pickupTime\', this.value)" style="width:100%;margin-top:6px;padding:10px;border-radius:10px;border:1px solid rgba(15,23,42,0.14);background:#fff"></label>' +
            '<label class="muted">Required Arrival / Appointment Time<input id="rider-arrival-time-input" type="time" value="' + escapeHtml(safeText(profile.arrivalTime, "")) + '" oninput="window._amiUpdateRiderProfileDraft(\'arrivalTime\', this.value)" style="width:100%;margin-top:6px;padding:10px;border-radius:10px;border:1px solid rgba(15,23,42,0.14);background:#fff"></label>' +
            '<label class="muted">Trip Type<select id="rider-trip-type-input" onchange="window._amiUpdateRiderProfileDraft(\'tripType\', this.value); renderPage();" style="width:100%;margin-top:6px;padding:10px;border-radius:10px;border:1px solid rgba(15,23,42,0.14);background:#fff"><option value="one_way"' + (safeText(profile.tripType, "one_way") === "one_way" ? ' selected' : '') + '>One Way</option><option value="round_trip"' + (safeText(profile.tripType, "one_way") === "round_trip" ? ' selected' : '') + '>Round Trip</option></select></label>' +
            (showReturnSection
              ? '<label class="muted">Return Ride Mode<select id="rider-return-type-input" onchange="window._amiUpdateRiderProfileDraft(\'returnPickupType\', this.value); renderPage();" style="width:100%;margin-top:6px;padding:10px;border-radius:10px;border:1px solid rgba(15,23,42,0.14);background:#fff"><option value="scheduled_time"' + (safeText(profile.returnPickupType, "scheduled_time") === "scheduled_time" ? ' selected' : '') + '>Fixed Return Time</option><option value="call_when_ready"' + (safeText(profile.returnPickupType, "scheduled_time") === "call_when_ready" ? ' selected' : '') + '>Call When Ready</option></select></label>' +
                (showScheduledReturn
                  ? '<label class="muted">Fixed Return Pickup Time<input id="rider-return-time-input" type="time" value="' + escapeHtml(safeText(profile.returnPickupTime, "")) + '" oninput="window._amiUpdateRiderProfileDraft(\'returnPickupTime\', this.value)" style="width:100%;margin-top:6px;padding:10px;border-radius:10px;border:1px solid rgba(15,23,42,0.14);background:#fff"></label>'
                  : '<p class="muted">Return leg will dispatch when patient is marked ready.</p>') +
                '<label class="muted">Return Pickup Address<input id="rider-return-pickup-input" type="text" value="' + escapeHtml(safeText(profile.returnPickupAddress, profile.dropoff)) + '" placeholder="Clinic or return pickup location" oninput="window._amiUpdateRiderProfileDraft(\'returnPickupAddress\', this.value)" style="width:100%;margin-top:6px;padding:10px;border-radius:10px;border:1px solid rgba(15,23,42,0.14);background:#fff"></label>' +
                '<label class="muted">Return Destination Address<input id="rider-return-dropoff-input" type="text" value="' + escapeHtml(safeText(profile.returnDropoffAddress, profile.pickup)) + '" placeholder="Home or return destination" oninput="window._amiUpdateRiderProfileDraft(\'returnDropoffAddress\', this.value)" style="width:100%;margin-top:6px;padding:10px;border-radius:10px;border:1px solid rgba(15,23,42,0.14);background:#fff"></label>'
              : '') +
            '<label class="muted">Recurring Ride Option<select id="rider-recurrence-input" onchange="window._amiUpdateRiderProfileDraft(\'recurrence\', this.value); renderPage();" style="width:100%;margin-top:6px;padding:10px;border-radius:10px;border:1px solid rgba(15,23,42,0.14);background:#fff"><option value="none"' + (safeText(profile.recurrence, "none") === "none" ? ' selected' : '') + '>None</option><option value="weekly"' + (safeText(profile.recurrence, "none") === "weekly" ? ' selected' : '') + '>Weekly (Dialysis)</option></select></label>' +
            (showRecurrenceSection
              ? '<div class="muted" style="grid-column:1/-1">Recurring Weekdays: ' +
                renderRiderWeekdayCheckbox("mon", "Mon", profile.recurrenceWeekdays) +
                renderRiderWeekdayCheckbox("wed", "Wed", profile.recurrenceWeekdays) +
                renderRiderWeekdayCheckbox("tue", "Tue", profile.recurrenceWeekdays) +
                renderRiderWeekdayCheckbox("thu", "Thu", profile.recurrenceWeekdays) +
                renderRiderWeekdayCheckbox("fri", "Fri", profile.recurrenceWeekdays) +
                renderRiderWeekdayCheckbox("sat", "Sat", profile.recurrenceWeekdays) +
                renderRiderWeekdayCheckbox("sun", "Sun", profile.recurrenceWeekdays) +
                '</div>' +
                '<label class="muted">Recurrence Start Date<input id="rider-recurrence-start-input" type="date" value="' + escapeHtml(safeText(profile.recurrenceStartDate, profile.serviceDate)) + '" oninput="window._amiUpdateRiderProfileDraft(\'recurrenceStartDate\', this.value)" style="width:100%;margin-top:6px;padding:10px;border-radius:10px;border:1px solid rgba(15,23,42,0.14);background:#fff"></label>' +
                '<label class="muted">Recurrence End Date<input id="rider-recurrence-end-input" type="date" value="' + escapeHtml(safeText(profile.recurrenceEndDate, "")) + '" oninput="window._amiUpdateRiderProfileDraft(\'recurrenceEndDate\', this.value)" style="width:100%;margin-top:6px;padding:10px;border-radius:10px;border:1px solid rgba(15,23,42,0.14);background:#fff"></label>'
              : '') +
            '<label class="muted" style="display:flex;align-items:center;gap:8px;margin-top:6px"><input id="rider-same-driver-input" type="checkbox"' + (profile.sameDriverPreference ? ' checked' : '') + ' onchange="window._amiUpdateRiderProfileDraft(\'sameDriverPreference\', this.checked)"> Same-Driver Preference</label>' +
            '<label class="muted">Notes<textarea id="rider-notes-input" rows="3" placeholder="Optional notes (wheelchair, appointment time, etc.)" oninput="window._amiUpdateRiderProfileDraft(\'notes\', this.value)" style="width:100%;margin-top:6px;padding:10px;border-radius:10px;border:1px solid rgba(15,23,42,0.14);background:#fff">' + escapeHtml(safeText(profile.notes, "")) + '</textarea></label>' +
          '</div>' +
          '<div class="command-actions">' +
            '<button class="preview-action rider-action" data-rider-action="request_now"' + (riderState.submitInFlight ? ' disabled' : '') + '>' + (riderState.submitInFlight ? (safeText(riderState.submitStatus && riderState.submitStatus.message, "").indexOf("Checking status") >= 0 ? 'Checking ride status…' : 'Submitting ride…') : 'Request Ride Now') + '</button>' +
            '<button class="preview-action rider-action" data-rider-action="schedule_recurring"' + (riderState.submitInFlight ? ' disabled' : '') + '>Submit Scheduled Ride</button>' +
            '<button class="preview-action rider-action" data-rider-action="cancel_active_trip"' + (activeRequestId ? '' : ' disabled') + '>Cancel Active Ride</button>' +
          '</div>' +
          '<p class="muted">Latest action: ' + escapeHtml(safeText(riderState.lastAction, 'none')) + '</p>' +
        '</section>' +
        '<section class="rider-card">' +
          '<h4>Live Trip Tracking</h4>' +
          '<div class="grid-2">' +
            renderMetric("Trip", activeRequestId ? safeText(activeTrip.tripId, "Active ride") : "No active ride") +
            renderMetric("Status", activeRequestId ? titleizeWords(safeText(activeTrip.status, "pending")) : "None") +
            renderMetric("ETA", activeRequestId && safeText(activeTrip.etaMin, "") ? safeText(activeTrip.etaMin, "") + " min" : "pending") +
            renderMetric("Driver", activeRequestId ? safeText(activeTrip.driverName, "Awaiting assignment") : "Not assigned") +
            renderMetric("Vehicle", activeRequestId ? safeText(activeTrip.vehicle, "vehicle pending") : "—") +
            renderMetric("Support", safeText(activeTrip.supportContact, "Rider Care")) +
          '</div>' +
          '<p class="muted">' + (activeRequestId
            ? ('Pickup: ' + escapeHtml(safeText(activeTrip.pickup, "pickup")) + ' → Dropoff: ' + escapeHtml(safeText(activeTrip.dropoff, "dropoff")))
            : 'Submit a ride request to begin live trip tracking.') + '</p>' +
        '</section>' +
        '<section class="rider-card">' +
          '<h4>Recurring Schedule</h4>' +
          '<div class="grid-2">' + renderRiderRecurringRows(recurring) + '</div>' +
        '</section>' +
        '<section class="rider-card">' +
          '<h4>Notifications and Support</h4>' +
          '<div class="command-actions">' +
            '<button class="preview-action rider-action" data-rider-action="contact_support">Contact Support</button>' +
            '<button class="preview-action rider-action" data-rider-action="share_trip">Share Live Trip</button>' +
          '</div>' +
          '<ul class="driver-notification-list">' + renderRiderNotifications(notifications) + '</ul>' +
        '</section>' +
        '<section class="rider-card rider-wide">' +
          '<h4>Trip History</h4>' +
          renderRiderHistoryRows(history) +
        '</section>' +
      '</div>',
      "rider app"
    );
  }

  function normalizeDriverTripStatus(raw) {
    var value = safeText(raw, "queued").toLowerCase();
    var mapped = {
      reassignment_pending: "assigned",
      offered: "queued",
      pending: "queued",
      dispatchable: "queued",
      assigned: "assigned",
      accepted: "accepted",
      en_route_pickup: "driver_en_route",
      driver_en_route: "driver_en_route",
      arrived_pickup: "arrived",
      waiting_at_pickup: "arrived",
      at_pickup: "arrived",
      arrived: "arrived",
      rider_loaded: "rider_onboard",
      rider_onboard: "rider_onboard",
      trip_in_progress: "in_progress",
      in_progress: "in_progress",
      in_transit: "in_progress",
      arrived_destination: "arrived_destination",
      completed: "completed",
      no_show: "declined",
      cancelled: "cancelled",
      declined: "declined"
    };
    return mapped[value] || value;
  }

  function isAiProofRideName(name) {
    return isProofOrDemoTripMeta(name, "", "", "");
  }

  function isProofOrDemoTripMeta(name, pickup, dropoff, notes) {
    var blob = (
      safeText(name, "") + " " + safeText(pickup, "") + " " + safeText(dropoff, "") + " " + safeText(notes, "")
    ).toLowerCase();
    var i;
    for (i = 0; i < DRIVER_PROOF_MARKERS.length; i += 1) {
      if (blob.indexOf(DRIVER_PROOF_MARKERS[i]) >= 0) return true;
    }
    for (i = 0; i < DRIVER_SCRIPT_MARKERS.length; i += 1) {
      if (blob.indexOf(DRIVER_SCRIPT_MARKERS[i]) >= 0) return true;
    }
    return false;
  }

  function clearPlatformClientCaches() {
    clearDriverLiveTripState();
    state.liveWorkflow = {
      dispatchQueue: [],
      activeAssignments: [],
      activityFeed: [],
      drivers: [],
      rides: [],
      providers: [],
      customerRequests: [],
      vehicles: []
    };
    state.driverWorkflow = {
      driverId: "",
      workspace: null,
      activeRide: null,
      activeOffer: null,
      assignedRides: [],
      earnings: null
    };
    state.riderApp = {
      profile: riderProfileDefaults(),
      activeRequestId: "",
      activeTrip: emptyRiderActiveTrip(),
      recurringSchedule: [],
      notifications: [],
      tripHistory: [],
      lastAction: "Enter your details and request a ride",
      lastSubmit: null
    };
    if (state.assistant && typeof state.assistant === "object") {
      state.assistant.messages = [];
      state.assistant.toolEvents = [];
      state.assistant.previewCards = [];
      state.assistant.pendingIntent = null;
      state.assistant.pendingPrompt = "";
      state.assistant.draft = "";
      state.assistant.memoryEntries = [];
    }
    try {
      localStorage.removeItem("ops_shell_state");
      localStorage.removeItem("ops_cached_data");
      localStorage.removeItem("amicor_health_isf_runtime_state_v1");
      sessionStorage.removeItem("ops_driver_trip_cache_v1");
      sessionStorage.removeItem(SESSION_STATE_KEY);
    } catch (_) {}
  }

  async function syncPlatformResetEpoch(token) {
    if (!token) return false;
    try {
      var status = await fetchJson("/api/health-isf/ops/platform-reset-status", {}, token);
      var serverEpoch = safeText(status.platform_reset_epoch, "");
      var localEpoch = "";
      try {
        localEpoch = safeText(localStorage.getItem(PLATFORM_RESET_EPOCH_KEY), "");
      } catch (_) {}
      if (serverEpoch && serverEpoch !== localEpoch) {
        clearPlatformClientCaches();
        try {
          localStorage.setItem(PLATFORM_RESET_EPOCH_KEY, serverEpoch);
        } catch (_) {}
        return true;
      }
      if (status.system_ready_for_new_ride === true && localEpoch && serverEpoch && serverEpoch === localEpoch) {
        return false;
      }
      return false;
    } catch (_) {
      return false;
    }
  }

  function clearDriverLiveTripState(options) {
    var opts = options || {};
    state.driverApp = null;
    state.driverWorkflow = {
      driverId: "",
      workspace: null,
      activeRide: null,
      activeOffer: null,
      assignedRides: [],
      earnings: null
    };
    driverHydrateLockUntil = 0;
    driverLastConfirmedWorkflow = null;
    if (opts.resetBoundIdentity === true) {
      resetDriverBoundIdentity();
    }
    try {
      localStorage.removeItem("ops_shell_state");
      localStorage.removeItem("ops_cached_data");
      sessionStorage.removeItem("ops_driver_trip_cache_v1");
    } catch (_) {}
  }

  function parseDriverTripTimestamp(value) {
    var raw = safeText(value, "");
    if (!raw) return 0;
    var parsed = Date.parse(raw);
    return Number.isFinite(parsed) ? parsed : 0;
  }

  function driverTripLifecycleRank(status) {
    var token = normalizeDriverTripStatus(status);
    var order = {
      offered: 1,
      assigned: 2,
      accepted: 3,
      driver_en_route: 4,
      arrived: 5,
      rider_onboard: 6,
      in_progress: 7,
      in_transit: 7,
      arrived_destination: 8
    };
    return safeNumber(order[token], 0);
  }

  function finalizeDriverTripQueue(liveQueue, boundDriverId) {
    var queue = Array.isArray(liveQueue) ? liveQueue.slice() : [];
    var driverId = safeText(boundDriverId, "");
    queue = queue.filter(function (trip) {
      var tripId = safeText(trip.tripId, "");
      if (!tripId) return false;
      var status = normalizeDriverTripStatus(trip.status);
      if (isScheduledAssignmentState(status)) {
        return false;
      }
      if (["completed", "cancelled", "failed", "declined", "no_show", "expired", "reassignment_pending"].indexOf(status) >= 0) {
        return false;
      }
      if (driverId && safeText(trip.assignedDriver, "") && safeText(trip.assignedDriver, "") !== driverId) {
        return false;
      }
      return true;
    });
    queue.sort(function (a, b) {
      var aRank = driverTripLifecycleRank(a.status);
      var bRank = driverTripLifecycleRank(b.status);
      if (bRank !== aRank) return bRank - aRank;
      var aTs = parseDriverTripTimestamp(a.requestedAt || a.scheduledWindow);
      var bTs = parseDriverTripTimestamp(b.requestedAt || b.scheduledWindow);
      if (bTs !== aTs) return bTs - aTs;
      return safeText(b.tripId, "").localeCompare(safeText(a.tripId, ""));
    });
    if (queue.length > 1) {
      queue = queue.slice(0, 1);
    }
    return {
      queue: queue,
      activeTripId: queue.length > 0 ? safeText(queue[0].tripId, "") : ""
    };
  }

  function getSessionEmail() {
    try {
      if (window.AmiCorSession && typeof window.AmiCorSession.getIdentity === "function") {
        var identity = window.AmiCorSession.getIdentity() || {};
        return safeText(identity.email, "").toLowerCase();
      }
    } catch (_) {}
    return "";
  }

  async function resolveSessionDriverId(token) {
    if (isDriverMobileAppRoute()) {
      return getMobileSessionDriverId();
    }
    var persisted = readPersistedDriverSession();
    if (persisted && persisted.driver_id) {
      return persisted.driver_id;
    }
    try {
      var query = new URLSearchParams(String(window.location.search || ""));
      var queryDriverId = safeText(query.get("driver_id") || query.get("driverId") || "", "");
      if (queryDriverId) return queryDriverId;
    } catch (_) {}
    try {
      var boundDriverId = safeText(localStorage.getItem("amicor_driver_workflow_id") || "", "");
      if (boundDriverId) return boundDriverId;
      var runtimeRaw = localStorage.getItem("amicor_driver_runtime");
      if (runtimeRaw) {
        var runtime = JSON.parse(runtimeRaw);
        var runtimeDriverId = safeText(runtime && (runtime.driver_id || runtime.driverId), "");
        if (runtimeDriverId) return runtimeDriverId;
      }
    } catch (_) {}
    var email = getSessionEmail();
    if (!email && token) {
      try {
        var me = await fetchJson("/api/auth/me", {}, token);
        email = safeText(me.email, "").toLowerCase();
      } catch (_) {}
    }
    var targetPhone = SEED_DRIVER_PHONE_BY_EMAIL[email] || "";
    if (!token) return "";
    try {
      var drivers = await fetchJson("/api/health-isf/drivers?limit=200", {}, token);
      var rows = Array.isArray(drivers) ? drivers : [];
      if (targetPhone) {
        var targetDigits = targetPhone.replace(/\D/g, "");
        var phoneMatch = rows.find(function (row) {
          return String(row.phone || "").replace(/\D/g, "") === targetDigits;
        });
        if (phoneMatch && phoneMatch.id) {
          try {
            localStorage.setItem("amicor_driver_workflow_id", safeText(phoneMatch.id, ""));
          } catch (_) {}
          return safeText(phoneMatch.id, "");
        }
      }
    } catch (_) {}
    return "";
  }

  function buildDriverTripEntry(tripId, fields) {
    var payload = safeObject(fields);
    var requestedAt = safeText(payload.requestedAt || payload.scheduledWindow, "");
    return {
      tripId: safeText(tripId, ""),
      patient: safeText(payload.patient, "Rider"),
      riderPhone: safeText(payload.riderPhone, ""),
      pickup: safeText(payload.pickup, "Pickup pending"),
      dropoff: safeText(payload.dropoff, "Dropoff pending"),
      etaMin: safeNumber(payload.etaMin, 0),
      priority: safeText(payload.priority, "standard"),
      fare: safeNumber(payload.fare, 0),
      status: normalizeDriverTripStatus(payload.status || "queued"),
      type: safeText(payload.type, "transport"),
      scheduledWindow: safeText(payload.scheduledWindow, "Offer pending"),
      schedulingSummary: safeText(payload.schedulingSummary, ""),
      tripLeg: safeText(payload.tripLeg, ""),
      requestedAt: requestedAt,
      coordinationStatus: safeText(payload.coordinationStatus, "assignment_offered"),
      assignedDriver: safeText(payload.assignedDriver, ""),
      assignedDriverName: safeText(payload.assignedDriverName, ""),
      reservedByDriverId: safeText(payload.reservedByDriverId || payload.reserved_by_driver_id, ""),
      providerName: safeText(payload.providerName, ""),
      offerId: safeText(payload.offerId, ""),
      trustedFromBackend: payload.trustedFromBackend === true
    };
  }

  function isTerminalRideStatus(raw) {
    return TERMINAL_RIDE_STATUSES.indexOf(normalizeRideStatusToken(raw)) >= 0;
  }

  function isOperationalActiveRide(ride) {
    var row = safeObject(ride);
    if (!safeText(row.id || row.ride_id, "")) return false;
    if (isTerminalRideStatus(row.lifecycle_state || row.status || row.dispatch_status)) return false;
    if (
      isProofOrDemoTripMeta(
        row.passenger_name || row.rider_name,
        row.pickup_address || row.pickup,
        row.dropoff_address || row.dropoff,
        row.notes
      )
    ) {
      return false;
    }
    return true;
  }

  function filterActiveOperationalRides(rides) {
    return (Array.isArray(rides) ? rides : []).filter(isOperationalActiveRide);
  }

  function filterActiveCustomerRequests(rows) {
    return (Array.isArray(rows) ? rows : []).filter(function (row) {
      var status = normalizeRideStatusToken(row.dispatch_status || row.status);
      if (TERMINAL_RIDE_STATUSES.indexOf(status) >= 0) return false;
      if (
        isProofOrDemoTripMeta(
          row.rider_name || row.passenger_name,
          row.pickup_address,
          row.dropoff_address,
          row.notes
        )
      ) {
        return false;
      }
      return true;
    });
  }

  function normalizeRideStatusToken(raw) {
    return safeText(raw, "").toLowerCase().replace(/^ridestatus\./, "").replace(/^driverstatus\./, "");
  }

  function isScheduledAssignmentState(raw) {
    var token = normalizeRideStatusToken(raw);
    return token === "scheduled_offered" || token === "scheduled_accepted";
  }

  function isImmediateAssignmentState(raw) {
    var token = normalizeRideStatusToken(raw);
    if (isScheduledAssignmentState(token)) return false;
    return [
      "offered",
      "assigned",
      "awaiting_approval",
      "reassignment_pending",
      "accepted",
      "en_route_pickup",
      "arrived_pickup",
      "waiting_at_pickup",
      "pickup_complete",
      "rider_loaded",
      "in_progress",
      "trip_in_progress"
    ].indexOf(token) >= 0;
  }

  function driverTripNeedsAcceptance(status, assignmentState) {
    var tripStatus = normalizeDriverTripStatus(status);
    var normalizedAssignment = safeText(assignmentState, "").toLowerCase();
    if (isScheduledAssignmentState(normalizedAssignment)) {
      return false;
    }
    if (["offered", "assigned", "awaiting_approval", "pending_assignment"].indexOf(normalizedAssignment) >= 0) {
      return true;
    }
    return ["queued", "assigned", "offered", "pending"].indexOf(tripStatus) >= 0;
  }

  function appendUniqueDriverTrip(liveQueue, entry) {
    if (!entry || !safeText(entry.tripId, "")) return;
    if (!entry.trustedFromBackend && isProofOrDemoTripMeta(entry.patient, entry.pickup, entry.dropoff, "")) return;
    for (var i = 0; i < liveQueue.length; i += 1) {
      if (safeText(liveQueue[i].tripId, "") === safeText(entry.tripId, "")) {
        liveQueue[i] = entry;
        return;
      }
    }
    liveQueue.push(entry);
  }

  function resolveDriverTripLifecycleStatus(assignmentState, lifecycleState) {
    var assignment = safeText(assignmentState, "");
    var lifecycle = safeText(lifecycleState, "");
    if (!lifecycle && assignment) return assignment;
    if (!assignment && lifecycle) return lifecycle;
    var aRank = driverTripLifecycleRank(assignment);
    var lRank = driverTripLifecycleRank(lifecycle);
    if (lRank > aRank) return lifecycle;
    if (lRank === aRank && lifecycle) return lifecycle;
    return assignment;
  }

  function resolveAssignmentDriverId(source) {
    var row = safeObject(source);
    return safeText(row.driver_id || row.driverId, "");
  }

  function resolveRideDriverId(rideRow) {
    return safeText((safeObject(rideRow)).driver_id || (safeObject(rideRow)).driverId, "");
  }

  function validateMobileTripOwnership(sessionDriverId, rideRow, offerRow, assignmentRow, sourceTag) {
    sessionDriverId = safeText(sessionDriverId, "");
    var rideId = safeText(
      (safeObject(rideRow)).id || (safeObject(offerRow)).ride_id || (safeObject(assignmentRow)).ride_id,
      ""
    );
    var rideStatus = normalizeRideStatusToken(
      (safeObject(rideRow)).lifecycle_state || (safeObject(rideRow)).status
    );
    if (rideStatus && isTerminalRideStatus(rideStatus)) {
      return {
        accepted: false,
        reason: "terminal_ride_status",
        ride_id: rideId,
        assignment_driver_id: resolveAssignmentDriverId(offerRow) || resolveAssignmentDriverId(assignmentRow),
        source: sourceTag
      };
    }
    var offerDriverId = resolveAssignmentDriverId(offerRow);
    var assignmentDriverId = resolveAssignmentDriverId(assignmentRow);
    var rideDriverId = resolveRideDriverId(rideRow);
    var offerAssignmentState = safeText((safeObject(offerRow)).assignment_state, "").toLowerCase();
    var rowAssignmentState = safeText((safeObject(assignmentRow)).assignment_state, "").toLowerCase();
    var acceptedByDriverId = safeText(
      (safeObject(offerRow)).accepted_by_driver_id || (safeObject(assignmentRow)).accepted_by_driver_id,
      ""
    );
    var reservedOwnerId = safeText(
      (safeObject(rideRow)).scheduled_reservation_owner_id
        || (safeObject(offerRow)).scheduled_reservation_owner_id
        || (safeObject(assignmentRow)).scheduled_reservation_owner_id
        || (safeObject(offerRow)).accepted_by_driver_id
        || (safeObject(assignmentRow)).accepted_by_driver_id,
      ""
    );
    if (reservedOwnerId && reservedOwnerId !== sessionDriverId) {
      return {
        accepted: false,
        reason: "group_scheduled_reservation_owner",
        ride_id: rideId,
        assignment_driver_id: reservedOwnerId,
        source: sourceTag
      };
    }
    if (isScheduledAssignmentState(offerAssignmentState) || isScheduledAssignmentState(rowAssignmentState)) {
      return {
        accepted: false,
        reason: "scheduled_assignment_not_immediate",
        ride_id: rideId,
        assignment_driver_id: assignmentDriverId || offerDriverId || rideDriverId,
        source: sourceTag
      };
    }
    if (acceptedByDriverId && acceptedByDriverId !== sessionDriverId) {
      return {
        accepted: false,
        reason: "scheduled_reservation_owner_mismatch",
        ride_id: rideId,
        assignment_driver_id: acceptedByDriverId,
        source: sourceTag
      };
    }
    if (!sessionDriverId) {
      return {
        accepted: false,
        reason: "missing_session_driver",
        ride_id: rideId,
        assignment_driver_id: assignmentDriverId || offerDriverId || rideDriverId,
        source: sourceTag
      };
    }
    if (offerDriverId && offerDriverId !== sessionDriverId) {
      return {
        accepted: false,
        reason: "offer_driver_mismatch",
        ride_id: rideId,
        assignment_driver_id: offerDriverId,
        source: sourceTag
      };
    }
    if (assignmentDriverId && assignmentDriverId !== sessionDriverId) {
      return {
        accepted: false,
        reason: "assignment_driver_mismatch",
        ride_id: rideId,
        assignment_driver_id: assignmentDriverId,
        source: sourceTag
      };
    }
    if (rideDriverId && rideDriverId !== sessionDriverId) {
      var immediateOfferForSession = offerDriverId === sessionDriverId
        && isImmediateAssignmentState(offerAssignmentState || rowAssignmentState);
      var immediateAssignmentForSession = assignmentDriverId === sessionDriverId
        && isImmediateAssignmentState(rowAssignmentState || offerAssignmentState);
      if (!(immediateOfferForSession || immediateAssignmentForSession)) {
        return {
          accepted: false,
          reason: "ride_driver_mismatch",
          ride_id: rideId,
          assignment_driver_id: rideDriverId,
          source: sourceTag
        };
      }
    }
    return {
      accepted: true,
      reason: "accepted",
      ride_id: rideId,
      assignment_driver_id: offerDriverId || assignmentDriverId || rideDriverId || sessionDriverId,
      source: sourceTag
    };
  }

  function logDriverMobileHydrationDecision(sessionDriverId, decision, activeOfferEnvelope) {
    if (!isDriverMobileSessionRoute()) return;
    logDriverMobileAssignmentSync({
      event: "mobile_hydration_trip_filter",
      authenticated_driver_id: sessionDriverId,
      assignment_driver_id: safeText(decision.assignment_driver_id, "") || null,
      requested_ride_id: safeText(decision.ride_id, "") || null,
      api_response: {
        active_offer: activeOfferEnvelope || null,
        decision: decision
      },
      extra: {
        accepted: !!decision.accepted,
        reason: safeText(decision.reason, ""),
        source: safeText(decision.source, "")
      }
    });
  }

  function appendOwnedDriverTrip(sessionDriverId, liveQueue, entry, rideRow, offerRow, assignmentRow, sourceTag, activeOfferEnvelope) {
    var decision = validateMobileTripOwnership(sessionDriverId, rideRow, offerRow, assignmentRow, sourceTag);
    logDriverMobileHydrationDecision(sessionDriverId, decision, activeOfferEnvelope);
    if (!decision.accepted) return;
    if (decision.assignment_driver_id) {
      entry.assignedDriver = decision.assignment_driver_id;
    }
    appendUniqueDriverTrip(liveQueue, entry);
  }

  function ensureDriverMobileState(slice) {
    var driverWorkflow = safeObject(state.driverWorkflow);
    var buildSource = (function () {
      var build = {
        workspace: safeObject(driverWorkflow.workspace),
        activeRide: safeObject(driverWorkflow.activeRide),
        activeOffer: safeObject(driverWorkflow.activeOffer),
        assignedRides: Array.isArray(driverWorkflow.assignedRides) ? driverWorkflow.assignedRides : []
      };
      if (!driverLastConfirmedWorkflow) return build;
      if (safeText(driverLastConfirmedWorkflow.driverId, "") !== safeText(driverWorkflow.driverId, "")) return build;
      var confirmed = driverLastConfirmedWorkflow;
      var confirmedActive = safeObject(confirmed.activeRide);
      var confirmedRide = safeObject(confirmedActive.ride);
      var confirmedStatus = normalizeRideStatusToken(
        confirmedRide.lifecycle_state || confirmedRide.status || confirmedActive.assignment_state
      );
      if (["completed", "cancelled", "failed", "declined", "no_show", "expired"].indexOf(confirmedStatus) >= 0) {
        return build;
      }
      var buildActive = safeObject(build.activeRide);
      var confirmedRideId = safeText((safeObject(confirmedActive.ride)).id, "");
      if (confirmedActive.has_active_ride === true && confirmedRideId) {
        var confirmedRideDriverId = resolveRideDriverId(confirmedRide);
        if (confirmedRideDriverId && confirmedRideDriverId !== safeText(driverWorkflow.driverId, "")) {
          return build;
        }
        if (buildActive.has_active_ride !== true || !safeText((safeObject(buildActive.ride)).id, "")) {
          build.activeRide = confirmedActive;
        }
      }
      if (Array.isArray(confirmed.assignedRides) && confirmed.assignedRides.length && !build.assignedRides.length) {
        build.assignedRides = confirmed.assignedRides.slice();
      }
      var confirmedOffer = safeObject(confirmed.activeOffer);
      var buildOffer = safeObject(build.activeOffer);
      var confirmedOfferRow = safeObject(confirmedOffer.offer);
      if (
        safeText(confirmedOfferRow.ride_id, "")
        && !safeText((safeObject(buildOffer.offer)).ride_id, "")
        && resolveAssignmentDriverId(confirmedOfferRow) === safeText(driverWorkflow.driverId, "")
      ) {
        build.activeOffer = confirmedOffer;
      }
      return build;
    })();
    var liveWorkflow = safeObject(state.liveWorkflow);
    var liveWorkspace = safeObject(buildSource.workspace);
    var activeRidePayload = safeObject(buildSource.activeRide);
    var canonicalRide = safeObject(activeRidePayload.ride);
    var canonicalAssignment = safeObject(activeRidePayload.active_assignment);
    var activeRide = safeObject(liveWorkspace.active_ride);
    var activeAssignment = safeObject(liveWorkspace.active_assignment);
    var offerEnvelope = safeObject(buildSource.activeOffer);
    var activeOffer = safeObject(offerEnvelope.offer);
    var assignedRideRows = Array.isArray(buildSource.assignedRides) ? buildSource.assignedRides : [];
    var workflowDriverId = resolveCanonicalMobileDriverId()
      || safeText(driverWorkflow.driverId, "")
      || driverBoundDriverId
      || safeText((safeObject(state.driverApp)).currentDriverId, "");
    if (workflowDriverId) {
      var liveQueue = [];

      if (activeRidePayload.has_active_ride === true && safeText(canonicalRide.id, "")) {
        var canonicalStatus = resolveDriverTripLifecycleStatus(
          activeRidePayload.assignment_state,
          canonicalRide.lifecycle_state || canonicalRide.status
        ) || "assigned";
        if (isTerminalRideStatus(canonicalStatus)) {
          canonicalStatus = "";
        }
        if (
          canonicalStatus
          && ["reassignment_pending", "rejected", "expired", "dropoff_complete"].indexOf(
            canonicalStatus.toLowerCase()
          ) >= 0
        ) {
          canonicalStatus = safeText(canonicalRide.lifecycle_state || canonicalRide.status, "assigned");
        }
        if (canonicalStatus && !isTerminalRideStatus(canonicalStatus)) {
        appendOwnedDriverTrip(
          workflowDriverId,
          liveQueue,
          buildDriverTripEntry(safeText(canonicalRide.id, ""), {
          patient: canonicalRide.passenger_name,
          riderPhone: canonicalRide.passenger_phone || canonicalRide.rider_phone,
          pickup: canonicalRide.pickup_address || canonicalRide.pickup,
          dropoff: canonicalRide.dropoff_address || canonicalRide.dropoff,
          etaMin: activeRidePayload.eta_minutes,
          priority: canonicalRide.priority_tag,
          fare: canonicalRide.estimated_fare_usd,
          status: canonicalStatus,
          scheduledWindow: canonicalRide.requested_at || canonicalRide.appointment_time,
          requestedAt: canonicalRide.requested_at || canonicalRide.created_at,
          coordinationStatus: canonicalStatus,
          assignedDriver: resolveAssignmentDriverId(canonicalAssignment) || resolveRideDriverId(canonicalRide) || workflowDriverId,
          assignedDriverName: activeRidePayload.driver_name,
          offerId: canonicalAssignment.offer_id || canonicalAssignment.id,
          trustedFromBackend: true
        }),
          canonicalRide,
          activeOffer,
          canonicalAssignment,
          "active_ride_payload",
          offerEnvelope
        );
        }
      }

      var offerRideId = safeText(activeOffer.ride_id, "");
      var offerState = safeText(activeOffer.assignment_state || "offered", "offered").toLowerCase();
      if (
        offerRideId
        && !isProofOrDemoTripMeta(
          activeOffer.passenger_name,
          activeOffer.pickup_address,
          activeOffer.dropoff_address,
          activeOffer.notes
        )
        && (offerState === "offered" || offerState === "assigned" || offerState === "awaiting_approval" || offerState === "reassignment_pending")
      ) {
        appendOwnedDriverTrip(
          workflowDriverId,
          liveQueue,
          buildDriverTripEntry(offerRideId, {
          patient: activeOffer.passenger_name,
          riderPhone: activeOffer.passenger_phone || activeOffer.rider_phone,
          pickup: activeOffer.pickup_address,
          dropoff: activeOffer.dropoff_address,
          status: activeOffer.assignment_state || "offered",
          scheduledWindow: activeOffer.offer_expires_at || activeOffer.requested_at,
          requestedAt: activeOffer.requested_at || activeOffer.offer_expires_at,
          coordinationStatus: activeOffer.assignment_state,
          assignedDriver: resolveAssignmentDriverId(activeOffer) || workflowDriverId,
          reservedByDriverId: safeText(activeOffer.scheduled_reservation_owner_id, ""),
          offerId: activeOffer.id || activeOffer.offer_id
        }),
          null,
          activeOffer,
          null,
          "active_offer",
          offerEnvelope
        );
      }

      var workspaceRideId = safeText(activeRide.id, "");
      if (
        workspaceRideId
        && !isProofOrDemoTripMeta(
          activeRide.passenger_name,
          activeRide.pickup_address || activeRide.pickup,
          activeRide.dropoff_address || activeRide.dropoff,
          activeRide.notes
        )
      ) {
        var workspaceRideStatus = activeRide.lifecycle_state || activeRide.status;
        var workspaceAssignmentState = safeText(activeAssignment.assignment_state, offerState);
        if (
          !isScheduledAssignmentState(workspaceAssignmentState)
          && (
          driverTripNeedsAcceptance(workspaceRideStatus, workspaceAssignmentState)
          || ["accepted", "driver_en_route", "arrived", "rider_onboard", "in_progress", "in_transit"].indexOf(
            normalizeDriverTripStatus(workspaceRideStatus)
          ) >= 0
          )
        ) {
          appendOwnedDriverTrip(
            workflowDriverId,
            liveQueue,
            buildDriverTripEntry(workspaceRideId, {
            patient: activeRide.passenger_name,
            riderPhone: activeRide.passenger_phone || activeRide.rider_phone,
            pickup: activeRide.pickup_address || activeRide.pickup,
            dropoff: activeRide.dropoff_address || activeRide.dropoff,
            etaMin: liveWorkspace.eta_minutes,
            priority: activeRide.priority_tag,
            fare: activeRide.estimated_fare_usd,
            status: workspaceAssignmentState || workspaceRideStatus,
            scheduledWindow: activeRide.requested_at || activeRide.appointment_time,
            requestedAt: activeRide.requested_at || activeRide.created_at,
            coordinationStatus: workspaceAssignmentState || "assignment_active",
            assignedDriver: resolveAssignmentDriverId(activeAssignment) || resolveRideDriverId(activeRide) || workflowDriverId,
            offerId: activeAssignment.offer_id || activeAssignment.id
          }),
            activeRide,
            null,
            activeAssignment,
            "live_workspace_ride",
            offerEnvelope
          );
        }
      } else if (
        safeText(activeAssignment.ride_id, "")
        && !isProofOrDemoTripMeta(activeAssignment.passenger_name, "", "", "")
      ) {
        var assignmentRideId = safeText(activeAssignment.ride_id, "");
        var assignmentState = safeText(activeAssignment.assignment_state, "assigned").toLowerCase();
        if (isScheduledAssignmentState(assignmentState)) {
          return;
        }
        if (["offered", "assigned", "awaiting_approval", "accepted", "en_route_pickup", "arrived_pickup", "waiting_at_pickup", "arrived", "pickup_complete", "rider_loaded", "in_progress", "trip_in_progress"].indexOf(assignmentState) >= 0) {
          appendOwnedDriverTrip(
            workflowDriverId,
            liveQueue,
            buildDriverTripEntry(assignmentRideId, {
            patient: activeAssignment.passenger_name,
            pickup: activeRide.pickup_address || activeRide.pickup || "Pickup pending",
            dropoff: activeRide.dropoff_address || activeRide.dropoff || "Dropoff pending",
            status: assignmentState || activeAssignment.ride_status || "assigned",
            scheduledWindow: activeAssignment.offer_expires_at || activeAssignment.offered_at,
            coordinationStatus: assignmentState,
            assignedDriver: resolveAssignmentDriverId(activeAssignment) || workflowDriverId,
            offerId: activeAssignment.offer_id || activeAssignment.id
          }),
            activeRide,
            null,
            activeAssignment,
            "live_workspace_assignment",
            offerEnvelope
          );
        }
      }

      assignedRideRows.forEach(function (ride) {
        var rideId = safeText(ride.id || ride.ride_id, "");
        if (!rideId) return;
        if (isProofOrDemoTripMeta(ride.passenger_name, ride.pickup_address, ride.dropoff_address, ride.notes)) return;
        var rideStatus = normalizeRideStatusToken(ride.lifecycle_state || ride.status);
        if (["completed", "cancelled", "failed", "declined"].indexOf(rideStatus) >= 0) return;
        if (["queued", "pending", "requested"].indexOf(rideStatus) >= 0) {
          var isActiveOffer = offerRideId && offerRideId === rideId;
          var isActiveAssignment = workspaceRideId === rideId || safeText(activeAssignment.ride_id, "") === rideId;
          var hasActiveRide = activeRidePayload.has_active_ride === true && safeText(canonicalRide.id, "") === rideId;
          if (!isActiveOffer && !isActiveAssignment && !hasActiveRide) {
            return;
          }
        }
        appendOwnedDriverTrip(
          workflowDriverId,
          liveQueue,
          buildDriverTripEntry(rideId, {
          patient: ride.passenger_name,
          riderPhone: ride.passenger_phone,
          pickup: ride.pickup_address,
          dropoff: ride.dropoff_address,
          status: rideStatus || "assigned",
          scheduledWindow: ride.requested_at || ride.updated_at,
          requestedAt: ride.requested_at || ride.created_at,
          coordinationStatus: rideStatus || "assigned",
          assignedDriver: resolveRideDriverId(ride) || workflowDriverId,
          offerId: safeText(activeAssignment.offer_id, ""),
          trustedFromBackend: true
        }),
          ride,
          null,
          activeAssignment,
          "assigned_rides_row",
          offerEnvelope
        );
      });

      var finalized = finalizeDriverTripQueue(liveQueue, workflowDriverId);
      liveQueue = finalized.queue;
      var liveDriver = (Array.isArray(liveWorkflow.drivers) ? liveWorkflow.drivers : []).find(function (driver) {
        return safeText(driver.id || driver.driver_id, "") === workflowDriverId;
      }) || {};
      var earningsSummary = safeObject(driverWorkflow.earnings);
      var completedFromApi = Array.isArray(driverWorkflow.completedRides) ? driverWorkflow.completedRides.length : 0;
      var billingRowsForSummary = Array.isArray(driverWorkflow.billingHandoffs) ? driverWorkflow.billingHandoffs : [];
      var earningsDisplay = deriveDriverEarningsDisplayFields(
        earningsSummary,
        Array.isArray(driverWorkflow.completedRides) ? driverWorkflow.completedRides : [],
        billingRowsForSummary
      );
      var earningsTripCount = safeNumber(earningsSummary.trip_count, 0);
      var earningsTripCountToday = safeNumber(earningsSummary.trip_count_today, 0);
      // Canonical completed-trip count comes from backend financial/completed-ride APIs only.
      // Prefer today's completed count for the summary tile; fall back to lifetime API count.
      var completedCount = Math.max(
        earningsDisplay.completedTrips,
        earningsTripCountToday > 0 ? earningsTripCountToday : 0,
        completedFromApi,
        earningsTripCount
      );
      var shiftOnline = workflowDriverId !== "";
      if (isDriverMobileAppRoute() && getCanonicalMobileDriverContext().authenticated) {
        shiftOnline = true;
      } else if (liveDriver && Object.keys(liveDriver).length) {
        shiftOnline = safeText(liveDriver.status, "available") !== "offline"
          || asBoolean(liveDriver.is_online, false);
      }
      if (liveQueue.length > 0) {
        shiftOnline = true;
      }

      var priorDriverApp = safeObject(state.driverApp);
      var preservedSecondaryTab = safeText(priorDriverApp.secondaryTab, "earnings") || "earnings";
      var preservedNotifications = Array.isArray(priorDriverApp.notifications)
        ? priorDriverApp.notifications
        : [];
      var apiDocuments = Array.isArray(driverWorkflow.documents) ? driverWorkflow.documents : [];
      var documentRows = apiDocuments.length
        ? apiDocuments.map(function (doc) {
            return {
              name: safeText(doc.title || doc.name, safeText(doc.document_type, "Document")),
              status: safeText(doc.status, "issued"),
              expiresIn: safeText(doc.reference || doc.expiresIn, "n/a"),
              amount_usd: safeNumber(doc.amount_usd, 0),
              ride_id: safeText(doc.ride_id, ""),
              document_type: safeText(doc.document_type, "")
            };
          })
        : [];

      state.driverApp = {
        seedAssignedRide: "",
        currentDriverId: workflowDriverId,
        shiftOnline: shiftOnline,
        activeTripId: finalized.activeTripId,
        activeStage: liveQueue.length > 0 ? safeText(liveQueue[0].status, "queued") : "queued",
        secondaryTab: preservedSecondaryTab,
        acceptedCount: liveQueue.filter(function (trip) {
          return ["accepted", "driver_en_route", "arrived", "rider_onboard", "in_progress", "assigned", "offered"].indexOf(safeText(trip.status, "")) >= 0;
        }).length,
        declinedCount: safeNumber(priorDriverApp.declinedCount, 0),
        completedTrips: completedCount,
        earningsToday: earningsDisplay.earningsToday,
        earningsLifetime: earningsDisplay.earningsLifetime,
        completedRideHistory: Array.isArray(driverWorkflow.completedRides) && driverWorkflow.completedRides.length
          ? driverWorkflow.completedRides
          : [],
        billingHandoffs: Array.isArray(driverWorkflow.billingHandoffs) ? driverWorkflow.billingHandoffs : [],
        tripQueue: liveQueue,
        notifications: preservedNotifications,
        documents: documentRows,
        lastStatusUpdate: safeText(priorDriverApp.lastStatusUpdate, "Driver workspace synchronized"),
        lastActionResult: safeObject(priorDriverApp.lastActionResult),
        syncWarning: safeText(priorDriverApp.syncWarning, ""),
        mobileUiState: (function () {
          if (liveQueue.length > 0) return "active_ride";
          if (!isDriverMobileAppRoute()) {
            return safeText(priorDriverApp.mobileUiState, "awaiting_assignment");
          }
          var apiPending = driverRefreshHasOpenAssignment(
            activeRidePayload,
            assignedRideRows,
            offerEnvelope
          );
          if (apiPending) return "loading_assignment";
          return "awaiting_assignment";
        })()
      };
      restartDriverMobilePollInterval();
      return;
    }

    var priorEmpty = safeObject(state.driverApp);
    var emptyMobileCtx = getCanonicalMobileDriverContext();
    if (isDriverMobileAppRoute() && emptyMobileCtx.authenticated) {
      state.driverApp = {
        seedAssignedRide: "",
        currentDriverId: emptyMobileCtx.driverId,
        shiftOnline: true,
        activeTripId: "",
        activeStage: "queued",
        secondaryTab: safeText(priorEmpty.secondaryTab, "earnings") || "earnings",
        acceptedCount: 0,
        declinedCount: 0,
        completedTrips: safeNumber(priorEmpty.completedTrips, 0),
        earningsToday: safeNumber(priorEmpty.earningsToday, 0),
        earningsLifetime: safeNumber(priorEmpty.earningsLifetime, 0),
        tripQueue: [],
        notifications: Array.isArray(priorEmpty.notifications) ? priorEmpty.notifications : [],
        documents: Array.isArray(priorEmpty.documents) ? priorEmpty.documents : [],
        lastStatusUpdate: safeText(priorEmpty.lastStatusUpdate, "Loading assignment"),
        mobileUiState: (function () {
          var prior = safeText(priorEmpty.mobileUiState, "loading_assignment");
          if (prior === "api_error") return "awaiting_assignment";
          return prior;
        })()
      };
      return;
    }
    state.driverApp = {
      seedAssignedRide: "",
      currentDriverId: "",
      shiftOnline: false,
      activeTripId: "",
      activeStage: "queued",
      secondaryTab: safeText(priorEmpty.secondaryTab, "earnings") || "earnings",
      acceptedCount: 0,
      declinedCount: 0,
      completedTrips: 0,
      earningsToday: 0,
      earningsLifetime: 0,
      tripQueue: [],
      notifications: Array.isArray(priorEmpty.notifications) ? priorEmpty.notifications : [],
      documents: Array.isArray(priorEmpty.documents) ? priorEmpty.documents : [],
      lastStatusUpdate: "Awaiting Assignment"
    };
  }

  function driverMobileWaitingLabels() {
    return {
      riderName: "Awaiting Assignment",
      routePickup: "No pickup",
      routeDropoff: "No dropoff",
      rideId: "n/a",
      statusLabel: "Awaiting Assignment"
    };
  }

  function getDriverTripById(tripId) {
    var appState = safeObject(state.driverApp);
    var queue = Array.isArray(appState.tripQueue) ? appState.tripQueue : [];
    var normalized = safeText(tripId, "");
    if (!normalized) return null;
    for (var i = 0; i < queue.length; i += 1) {
      if (safeText(queue[i].tripId, "") === normalized) {
        return queue[i];
      }
    }
    return null;
  }

  function resolveDriverActiveTrip(tripId) {
    var normalized = safeText(tripId, "");
    if (!normalized) return null;
    var fromQueue = getDriverTripById(normalized);
    if (fromQueue) return fromQueue;

    var driverWorkflow = safeObject(state.driverWorkflow);
    var activeRidePayload = safeObject(driverWorkflow.activeRide);
    var ride = safeObject(activeRidePayload.ride);
    if (safeText(ride.id, "") !== normalized) {
      var assignedRows = Array.isArray(driverWorkflow.assignedRides) ? driverWorkflow.assignedRides : [];
      for (var i = 0; i < assignedRows.length; i += 1) {
        var row = assignedRows[i];
        if (safeText(row.id || row.ride_id, "") === normalized) {
          ride = row;
          break;
        }
      }
    }
    if (!safeText(ride.id, "")) return null;

    var status = resolveDriverTripLifecycleStatus(
      activeRidePayload.assignment_state,
      ride.lifecycle_state || ride.status
    ) || "assigned";
    if (
      ["reassignment_pending", "rejected", "expired", "dropoff_complete"].indexOf(
        status.toLowerCase()
      ) >= 0
    ) {
      status = safeText(ride.lifecycle_state || ride.status, "assigned");
    }
    return buildDriverTripEntry(safeText(ride.id, ""), {
      patient: ride.passenger_name,
      riderPhone: ride.passenger_phone || ride.rider_phone,
      pickup: ride.pickup_address || ride.pickup,
      dropoff: ride.dropoff_address || ride.dropoff,
      etaMin: activeRidePayload.eta_minutes,
      priority: ride.priority_tag,
      fare: ride.estimated_fare_usd,
      status: status,
      scheduledWindow: ride.scheduling_summary || ride.requested_at || ride.created_at,
      schedulingSummary: safeText(ride.scheduling_summary, ""),
      tripLeg: safeText(ride.trip_leg, ""),
      requestedAt: ride.requested_at || ride.created_at,
      coordinationStatus: status,
      assignedDriver: safeText(driverWorkflow.driverId, ""),
      assignedDriverName: activeRidePayload.driver_name,
      providerName: activeRidePayload.provider_name,
      trustedFromBackend: true
    });
  }

  function renderDriverQueueCards(queue, activeTripId) {
    if (!Array.isArray(queue) || queue.length === 0) {
      return '<p class="muted">No pending transport assignments at this time. The queue is currently clear.</p>';
    }
    return queue.map(function (trip) {
      var tripId = safeText(trip.tripId, "");
      var isActive = tripId === safeText(activeTripId, "");
      var priority = safeText(trip.priority, "low");
      var statusText = safeText(trip.status, "queued");
      var scheduledWindow = safeText(trip.scheduledWindow, "window pending");
      var coordinationStatus = safeText(trip.coordinationStatus, "coordination pending");
      return '' +
        '<article class="driver-trip-card' + (isActive ? ' active' : '') + '">' +
          '<header>' +
            '<strong>' + escapeHtml(tripId) + '</strong>' +
            '<span class="driver-priority ' + escapeHtml(priority) + '">' + escapeHtml(titleizeWords(priority)) + '</span>' +
          '</header>' +
          '<p><strong>' + escapeHtml(safeText(trip.patient, 'patient')) + '</strong> • ' + escapeHtml(titleizeWords(safeText(trip.type, 'ride'))) + '</p>' +
          '<p class="muted">Pickup Facility: ' + escapeHtml(safeText(trip.pickup, 'pickup')) + ' → Destination Facility: ' + escapeHtml(safeText(trip.dropoff, 'dropoff')) + '</p>' +
          '<div class="driver-trip-meta">' +
            '<span>ETA ' + escapeHtml(String(safeNumber(trip.etaMin, 0))) + ' min</span>' +
            '<span>Window ' + escapeHtml(scheduledWindow) + '</span>' +
            '<span>Coordination ' + escapeHtml(titleizeWords(coordinationStatus)) + '</span>' +
            '<span>$' + escapeHtml(String(safeNumber(trip.fare, 0).toFixed(2))) + '</span>' +
            '<span>' + escapeHtml(titleizeWords(statusText)) + '</span>' +
          '</div>' +
          '<button class="driver-select" data-driver-action="select_trip" data-trip-id="' + escapeHtml(tripId) + '">Open Transport</button>' +
        '</article>';
    }).join("");
  }

  function renderDriverNotifications(notifications) {
    if (!Array.isArray(notifications) || notifications.length === 0) {
      return '<p class="muted">No urgent driver notifications right now.</p>';
    }
    return notifications.map(function (item) {
      var level = safeText(item.level, "low");
      var itemId = safeText(item.id, "");
      return '' +
        '<li class="driver-notification ' + escapeHtml(level) + '">' +
          '<span>' + escapeHtml(safeText(item.text, 'Notification')) + '</span>' +
          '<small>' + escapeHtml(safeText(item.ts, 'now')) + '</small>' +
          '<button data-driver-action="dismiss_notification" data-note-id="' + escapeHtml(itemId) + '">Dismiss</button>' +
        '</li>';
    }).join("");
  }

  function renderDriverComplianceTable(documents) {
    var rows = Array.isArray(documents) ? documents : [];
    if (rows.length === 0) {
      return '<p class="muted">No trip documents yet. Complete a ride to generate receipts and payout statements.</p>';
    }

    var body = rows.map(function (doc) {
      var status = safeText(doc.status, "issued");
      var amount = safeNumber(doc.amount_usd, 0);
      return '<tr>' +
        '<td>' + escapeHtml(safeText(doc.name || doc.title, 'document')) + '</td>' +
        '<td>' + escapeHtml(titleizeWords(safeText(doc.document_type, 'trip_document'))) + '</td>' +
        '<td><span class="status-dot">' + escapeHtml(titleizeWords(status)) + '</span></td>' +
        '<td>' + escapeHtml(safeText(doc.expiresIn || doc.reference, 'n/a')) + '</td>' +
        '<td>$' + escapeHtml(amount.toFixed(2)) + '</td>' +
      '</tr>';
    }).join("");

    return '<div class="table-wrap"><table class="ops-table"><thead><tr><th>Document</th><th>Type</th><th>Status</th><th>Reference</th><th>Amount</th></tr></thead><tbody>' + body + '</tbody></table></div>';
  }

  function driverMapPointFromAddress(address, xShift, yShift) {
    var text = safeText(address, "");
    var hash = 0;
    for (var i = 0; i < text.length; i += 1) {
      hash = ((hash << 5) - hash) + text.charCodeAt(i);
      hash |= 0;
    }
    var x = 48 + ((Math.abs(hash) % 180) + safeNumber(xShift, 0));
    var y = 44 + ((Math.abs(hash >> 3) % 100) + safeNumber(yShift, 0));
    return {
      x: Math.max(26, Math.min(270, x)),
      y: Math.max(24, Math.min(154, y))
    };
  }

  function renderDriverOperationalMap(activeTrip) {
    if (!activeTrip) {
      return '<article class="driver-workflow-card"><h4>Driver Map Panel</h4><p class="muted">No active trip selected. Select or assign a trip to load pickup/dropoff routing.</p></article>';
    }
    var pickupAddress = safeText(activeTrip.pickup, "Pickup pending");
    var dropoffAddress = safeText(activeTrip.dropoff, "Dropoff pending");
    var tripStatus = titleizeWords(safeText(activeTrip.status, "queued"));
    var etaText = String(safeNumber(activeTrip.etaMin, 0)) + " min";
    var pickupPoint = driverMapPointFromAddress(pickupAddress, 0, 0);
    var dropoffPoint = driverMapPointFromAddress(dropoffAddress, 22, 16);
    var driverPoint = {
      x: Math.round((pickupPoint.x + dropoffPoint.x) / 2),
      y: Math.round((pickupPoint.y + dropoffPoint.y) / 2)
    };
    var routeDistance = Math.round(Math.hypot(dropoffPoint.x - pickupPoint.x, dropoffPoint.y - pickupPoint.y));

    return '' +
      '<article class="driver-workflow-card">' +
        '<h4>Driver Map Panel</h4>' +
        '<p class="muted">Live operational route generated from current trip pickup/dropoff values.</p>' +
        '<svg viewBox="0 0 320 190" width="100%" height="220" aria-label="Driver route map" style="background:linear-gradient(180deg,#f8fbff 0%,#eef5ff 100%);border:1px solid rgba(15,23,42,0.12);border-radius:12px;">' +
          '<path d="M18 160 L302 160" stroke="#d4ddea" stroke-width="8" fill="none"></path>' +
          '<path d="M26 20 L26 170" stroke="#e4ebf6" stroke-width="6" fill="none"></path>' +
          '<line x1="' + String(pickupPoint.x) + '" y1="' + String(pickupPoint.y) + '" x2="' + String(dropoffPoint.x) + '" y2="' + String(dropoffPoint.y) + '" stroke="#2563eb" stroke-width="4" stroke-dasharray="6 4"></line>' +
          '<circle cx="' + String(pickupPoint.x) + '" cy="' + String(pickupPoint.y) + '" r="7" fill="#16a34a"></circle>' +
          '<circle cx="' + String(dropoffPoint.x) + '" cy="' + String(dropoffPoint.y) + '" r="7" fill="#dc2626"></circle>' +
          '<rect x="' + String(driverPoint.x - 6) + '" y="' + String(driverPoint.y - 6) + '" width="12" height="12" rx="3" fill="#0f172a"></rect>' +
          '<text x="' + String(pickupPoint.x + 10) + '" y="' + String(pickupPoint.y - 10) + '" font-size="11" fill="#0f172a">Pickup</text>' +
          '<text x="' + String(dropoffPoint.x + 10) + '" y="' + String(dropoffPoint.y - 10) + '" font-size="11" fill="#0f172a">Dropoff</text>' +
          '<text x="' + String(driverPoint.x + 10) + '" y="' + String(driverPoint.y + 20) + '" font-size="11" fill="#0f172a">Driver</text>' +
        '</svg>' +
        '<div class="grid-3" style="margin-top:10px;">' +
          renderMetric('Route ETA', etaText, 'status') +
          renderMetric('Route Length', String(routeDistance), 'status') +
          renderMetric('Trip Status', tripStatus, 'status') +
        '</div>' +
        '<p class="muted">Pickup: ' + escapeHtml(pickupAddress) + '<br>Dropoff: ' + escapeHtml(dropoffAddress) + '</p>' +
      '</article>';
  }

  function renderDriverWorkflowControls(appState, activeTrip) {
    var shiftOnline = asBoolean(appState.shiftOnline, false);
    var stage = safeText(appState.activeStage, "queued");
    var statusText = shiftOnline ? "On shift" : "Off shift";
    var tripStatus = activeTrip ? normalizeDriverTripStatus(activeTrip.status) : "none";
    var canAccept = ["queued", "assigned", "offered", "pending"].indexOf(tripStatus) >= 0
      && ["accepted", "en_route_pickup", "driver_en_route", "arrived", "rider_onboard", "in_progress", "in_transit", "arrived_destination"].indexOf(tripStatus) < 0;
    var canStartRoute = ["accepted", "assigned"].indexOf(tripStatus) >= 0;
    var canArrive = ["driver_en_route", "en_route_pickup"].indexOf(tripStatus) >= 0;
    var canPickup = ["arrived", "at_pickup", "arrived_pickup", "waiting_at_pickup"].indexOf(tripStatus) >= 0;
    var canStartTransport = ["rider_onboard", "rider_loaded"].indexOf(tripStatus) >= 0;
    var canArriveDestination = ["in_progress", "in_transit", "trip_in_progress"].indexOf(tripStatus) >= 0;
    var canComplete = ["arrived_destination"].indexOf(tripStatus) >= 0;

    var disableAccept = !shiftOnline || !activeTrip || !canAccept;
    var disableDecline = !shiftOnline || !activeTrip || !canAccept;
    var disableStartRoute = !shiftOnline || !activeTrip || !canStartRoute;
    var disableArrive = !shiftOnline || !activeTrip || !canArrive;
    var disablePickup = !shiftOnline || !activeTrip || !canPickup;
    var disableStartTransport = !shiftOnline || !activeTrip || !canStartTransport;
    var disableArriveDestination = !shiftOnline || !activeTrip || !canArriveDestination;
    var disableComplete = !shiftOnline || !activeTrip || !canComplete;

    return '' +
      '<div class="driver-workflow-grid">' +
        '<div class="driver-workflow-card">' +
          '<h4>Shift and Medical Transport Workflow</h4>' +
          '<p class="muted">Status: <strong>' + escapeHtml(statusText) + '</strong> • Stage: <strong>' + escapeHtml(titleizeWords(stage)) + '</strong> • Continuity: <strong>protected</strong></p>' +
          '<p class="muted">Workflow: <strong>Accept Trip</strong> → <strong>Start Route / En Route to Pickup</strong> → <strong>Arrived at Pickup</strong> → <strong>Rider On Board / Picked Up</strong> → <strong>Start Transportation</strong> → <strong>Arrived at Destination</strong> → <strong>Complete Trip</strong></p>' +
          '<div class="command-actions">' +
            '<button class="preview-action driver-action" data-driver-action="toggle_shift">' + escapeHtml(shiftOnline ? 'End Shift' : 'Start Shift') + '</button>' +
            '<button class="preview-action driver-action" data-driver-action="accept_trip"' + (disableAccept ? ' disabled' : '') + '>Accept Trip</button>' +
            '<button class="preview-action driver-action" data-driver-action="decline_trip"' + (disableDecline ? ' disabled' : '') + '>Decline Transport</button>' +
            '<button class="preview-action driver-action" data-driver-action="start_route"' + (disableStartRoute ? ' disabled' : '') + '>Start Route / En Route to Pickup</button>' +
            '<button class="preview-action driver-action" data-driver-action="arrive_pickup"' + (disableArrive ? ' disabled' : '') + '>Arrived at Pickup</button>' +
            '<button class="preview-action driver-action" data-driver-action="start_trip"' + (disablePickup ? ' disabled' : '') + '>Rider On Board / Picked Up</button>' +
            '<button class="preview-action driver-action" data-driver-action="start_transport"' + (disableStartTransport ? ' disabled' : '') + '>Start Transportation</button>' +
            '<button class="preview-action driver-action" data-driver-action="arrive_destination"' + (disableArriveDestination ? ' disabled' : '') + '>Arrived at Destination</button>' +
            '<button class="preview-action driver-action" data-driver-action="complete_trip"' + (disableComplete ? ' disabled' : '') + '>Complete Trip</button>' +
          '</div>' +
          '<p class="muted">Latest update: ' + escapeHtml(safeText(appState.lastStatusUpdate, 'None')) + '</p>' +
        '</div>' +
        '<div class="driver-workflow-card">' +
          '<h4>Emergency and Driver Help</h4>' +
          '<p class="muted">Escalation opens a supervised incident trail and support ticket.</p>' +
          '<div class="command-actions">' +
            '<button class="driver-emergency" data-driver-action="emergency_help">Emergency SOS</button>' +
            '<button class="preview-action driver-action" data-driver-action="open_support">Open Support</button>' +
          '</div>' +
          '<p class="muted">All escalations are audit logged with role attribution and workflow trace IDs.</p>' +
        '</div>' +
      '</div>';
  }

  function renderDriverMobileLoginForm() {
    var loginState = safeObject(state.driverApp && state.driverApp.mobileLogin);
    var statusText = safeText(loginState.status, "Not signed in");
    var errorText = safeText(loginState.error, "");
    var phoneValue = escapeHtml(safeText(loginState.phone, ""));
    return wrapDriverMobilePage(
      '<div class="driver-workflow-card driver-mobile-auth" id="driver-mobile-login-panel">' +
        '<h4>Driver Login</h4>' +
        '<p class="muted">Sign in with your registered driver phone number (example: 917-555-1004). No dispatcher workspace access is required.</p>' +
        '<label for="driver-mobile-phone">Driver phone</label>' +
        '<input id="driver-mobile-phone" name="driver_mobile_phone" type="tel" inputmode="tel" autocomplete="tel" value="' + phoneValue + '" />' +
        '<label for="driver-mobile-id">Driver ID (optional)</label>' +
        '<input id="driver-mobile-id" name="driver_mobile_id" type="text" autocomplete="off" placeholder="Use only if phone matches multiple drivers" />' +
        '<div style="margin-top:12px;display:flex;gap:8px;flex-wrap:wrap;align-items:center;">' +
          '<button class="preview-action driver-action" id="driver-mobile-login-btn" type="button">Driver Login</button>' +
        '</div>' +
        '<p id="driver-mobile-login-status" style="margin-top:10px;"><strong>Login status:</strong> ' + escapeHtml(statusText) + '</p>' +
        (errorText
          ? '<p id="driver-mobile-login-error" class="runtime-strip-item" style="color:#b91c1c;margin-top:8px;">' + escapeHtml(errorText) + '</p>'
          : '<p id="driver-mobile-login-error" class="runtime-strip-item" style="display:none;color:#b91c1c;margin-top:8px;"></p>') +
      '</div>'
    );
  }

  function classifyDriverLoginFailure(error, response, body) {
    var status = response && response.status ? Number(response.status) : 0;
    var message = safeText(error && error.message, "");
    var detail = safeText(body && body.detail, "");
    if (Array.isArray(body && body.detail)) {
      detail = body.detail.map(function (item) {
        return safeText(item && item.msg, safeText(item, "validation_error"));
      }).join("; ");
    }
    if (message === "request_timeout") {
      return {
        category: "network_timeout",
        message: "Network timeout: login took longer than 30 seconds. The server may still be waking up — wait and try again."
      };
    }
    if (!response) {
      if (/failed to fetch|networkerror|load failed/i.test(message)) {
        return {
          category: "render_cold_start",
          message: "Cannot reach server (Render cold start or network issue). Wait about 30 seconds and try again."
        };
      }
      return {
        category: "network_timeout",
        message: message || "Network error during driver login."
      };
    }
    if (status === 404) {
      return {
        category: "driver_not_found",
        message: detail || "Driver not found for this phone number."
      };
    }
    if (status === 401 || status === 403) {
      return {
        category: "expired_session",
        message: detail || "Session expired or unauthorized. Sign in again."
      };
    }
    if (status === 502 || status === 503 || status === 504) {
      return {
        category: "render_cold_start",
        message: detail || ("Server unavailable (HTTP " + String(status) + "). Possible Render cold start — wait and retry.")
      };
    }
    if (status >= 500) {
      return {
        category: "render_cold_start",
        message: detail || ("Server error during login (HTTP " + String(status) + "). If the app was sleeping, wait and retry.")
      };
    }
    if (/multiple drivers match/i.test(detail)) {
      return {
        category: "driver_not_found",
        message: detail + " Enter the optional Driver ID and try again."
      };
    }
    return {
      category: "driver_not_found",
      message: detail || message || "Driver login failed."
    };
  }

  function classifyDriverPostLoginSyncFailure(error) {
    var message = safeText(error && error.message, "Driver assignment sync failed");
    if (message === "request_timeout") {
      return {
        category: "post_login_sync_failure",
        message: "Signed in, but assignment sync timed out after 30 seconds. Tap Retry Sync."
      };
    }
    if (/http_401|http_403|session invalid|auth required/i.test(message)) {
      return {
        category: "expired_session",
        message: "Signed in, but the driver session expired during sync. Sign in again."
      };
    }
    if (/http_404|driver not found/i.test(message)) {
      return {
        category: "driver_not_found",
        message: "Signed in, but driver profile was not found during sync."
      };
    }
    return {
      category: "post_login_sync_failure",
      message: "Signed in, but post-login sync failed: " + message
    };
  }

  async function submitDriverMobileLogin(options) {
    var opts = options || {};
    var phoneInput = document.getElementById("driver-mobile-phone");
    var driverIdInput = document.getElementById("driver-mobile-id");
    var loginButton = document.getElementById("driver-mobile-login-btn");
    var statusEl = document.getElementById("driver-mobile-login-status");
    var errorEl = document.getElementById("driver-mobile-login-error");
    var phone = readDriverMobilePhoneInput();
    var allowDriverId = opts.allowDriverId === true;
    var driverId = allowDriverId ? safeText(driverIdInput && driverIdInput.value, "").trim() : "";
    state.driverApp = safeObject(state.driverApp);
    state.driverApp.mobileLogin = safeObject(state.driverApp.mobileLogin);
    state.driverApp.mobileLogin.phone = phone;
    if (driverMobileLoginInFlight) {
      return { ok: false, error: "Login already in progress" };
    }
    if (!phone) {
      state.driverApp.mobileLogin.error = "Enter your driver phone number.";
      state.driverApp.mobileLogin.status = "Login failed";
      if (errorEl) {
        errorEl.style.display = "block";
        errorEl.textContent = state.driverApp.mobileLogin.error;
      }
      if (statusEl) {
        statusEl.innerHTML = "<strong>Login status:</strong> Login failed";
      }
      return { ok: false };
    }
    if (!allowDriverId && driverIdInput) {
      driverIdInput.value = "";
    }
    driverMobileLoginInFlight = true;
    if (loginButton) loginButton.disabled = true;
    state.driverApp.mobileLogin.status = "Signing in…";
    state.driverApp.mobileLogin.error = "";
    if (statusEl) {
      statusEl.innerHTML = "<strong>Login status:</strong> Signing in…";
    }
    if (errorEl) {
      errorEl.style.display = "none";
      errorEl.textContent = "";
    }
    var payload = { phone: phone };
    if (driverId) {
      payload.driver_id = driverId;
    }
    var loginResult = { ok: false };
    try {
      var response = await withTimeout(fetch("/api/health-isf/drivers/mobile-login", {
        method: "POST",
        headers: {
          "Accept": "application/json",
          "Content-Type": "application/json"
        },
        credentials: "same-origin",
        body: JSON.stringify(payload)
      }), DRIVER_MOBILE_LOGIN_TIMEOUT_MS);
      var body = {};
      try {
        body = await response.json();
      } catch (_) {}
      if (!response.ok) {
        var failure = classifyDriverLoginFailure(null, response, body);
        state.driverApp.mobileLogin.status = "Login failed";
        state.driverApp.mobileLogin.error = "[" + failure.category.replace(/_/g, " ") + "] " + failure.message;
        loginResult = { ok: false, error: failure.message, category: failure.category };
        if (/multiple drivers match/i.test(failure.message)) {
          loginResult.requiresDriverId = true;
        }
        return loginResult;
      }
      var priorSessionDriver = safeText((safeObject(state.driverApp)).currentDriverId, "");
      var nextSessionDriver = safeText(body.driver_id, "");
      if (priorSessionDriver && priorSessionDriver !== nextSessionDriver) {
        driverLastConfirmedWorkflow = null;
        clearDriverMobileWorkflowState({ driverId: nextSessionDriver });
      }
      persistDriverSession({
        driver_id: body.driver_id,
        session_token: body.session_token,
        session_id: body.session_id,
        organization_id: body.organization_id,
        driver_name: safeText(body.driver_name, "Driver")
      });
      driverMobileAuthCache = {
        valid: true,
        requires_login: false,
        driver_id: safeText(body.driver_id, ""),
        driver_name: safeText(body.driver_name, "Driver"),
        session_role: "driver",
        auth_role: "driver",
        organization_id: safeText(body.organization_id, ""),
        session_token: safeText(body.session_token, ""),
        session_id: safeText(body.session_id, ""),
        source: "mobile_login"
      };
      state.driverApp.currentDriverId = safeText(body.driver_id, "");
      state.driverApp.shiftOnline = true;
      state.driverApp.mobileUiState = "loading_assignment";
      state.driverApp.mobileLogin.status = "Signed in as driver " + safeText(body.driver_id, "");
      state.driverApp.mobileLogin.error = "";
      bindDriverIdentity(body.driver_id, { forceRebind: true });
      logDriverMobileAssignmentSync({
        event: "mobile_login",
        assignment_state: safeText(body.availability_state, ""),
        api_response: {
          driver_id: safeText(body.driver_id, ""),
          session_id: safeText(body.session_id, ""),
          session_state: safeText(body.session_state, ""),
          auth_state: safeText(body.auth_state, "")
        },
        http_status: 200,
        route: "/api/health-isf/drivers/mobile-login",
        frontend_state_transition: "login_required->loading_assignment",
        next_ui_state: "loading_assignment"
      });
      scheduleRenderPage({ immediate: true });
      try {
        await withTimeout(refreshDriverWorkflowData({ forceReset: true }), DRIVER_MOBILE_BOOTSTRAP_TIMEOUT_MS);
      } catch (syncError) {
        var syncFailure = classifyDriverPostLoginSyncFailure(syncError);
        state.driverApp.mobileUiState = "api_error";
        state.driverApp.mobileBootstrapError = syncFailure.message;
        state.driverApp.mobileLogin.error = "[" + syncFailure.category.replace(/_/g, " ") + "] " + syncFailure.message;
        markDriverSyncWarning(syncFailure.message);
        loginResult = { ok: true, response: body, syncFailed: true, category: syncFailure.category };
        return loginResult;
      }
      scheduleRenderPage({ immediate: true });
      loginResult = { ok: true, response: body };
      return loginResult;
    } catch (error) {
      var loginFailure = classifyDriverLoginFailure(error, null, null);
      state.driverApp.mobileLogin.status = "Login failed";
      state.driverApp.mobileLogin.error = "[" + loginFailure.category.replace(/_/g, " ") + "] " + loginFailure.message;
      loginResult = { ok: false, error: loginFailure.message, category: loginFailure.category };
      return loginResult;
    } finally {
      driverMobileLoginInFlight = false;
      if (loginButton) loginButton.disabled = false;
      if (safeText(state.driverApp.mobileLogin.status, "") === "Signing in…") {
        state.driverApp.mobileLogin.status = "Login failed";
        if (!safeText(state.driverApp.mobileLogin.error, "")) {
          state.driverApp.mobileLogin.error = "[network timeout] Login did not complete. Try again.";
        }
      }
      scheduleRenderPage({ immediate: true });
    }
  }

  function renderDriverMobileExperience(phase17, slice) {
    if (isDriverMobileSurface() && !hasValidDriverMobileSession()) {
      return renderDriverMobileLoginForm();
    }
    ensureDriverMobileState(slice);
    recoverDriverMobileSyncUiState();
    var persistedSession = readPersistedDriverSession();
    var sessionAuth = driverMobileAuthCache || (persistedSession ? {
      valid: true,
      driver_id: persistedSession.driver_id,
      driver_name: persistedSession.driver_name
    } : null);
    var appState = safeObject(state.driverApp);
    var workflow = safeObject(state.driverWorkflow);
    var upcomingSchedule = Array.isArray(workflow.upcomingSchedule) ? workflow.upcomingSchedule : [];
    var scheduledOffers = Array.isArray(workflow.scheduledOffers) ? workflow.scheduledOffers : [];
    var immediateOffer = safeObject((safeObject(workflow.activeOffer)).offer);
    var mobileUiState = safeText(appState.mobileUiState, "awaiting_assignment");
    var driverSessionHeader = "";
    if (sessionAuth && safeText(sessionAuth.driver_id, "")) {
      driverSessionHeader =
        '<div class="driver-session-banner" style="margin-bottom:12px;padding:10px 12px;border:1px solid #d1d5db;border-radius:8px;background:#f8fafc;display:flex;justify-content:space-between;gap:12px;flex-wrap:wrap;align-items:center;">' +
          '<div><strong>Active Driver:</strong> ' + escapeHtml(safeText(sessionAuth.driver_name, "Driver")) +
          ' <span class="muted">ID: ' + escapeHtml(safeText(sessionAuth.driver_id, "")) + '</span></div>' +
          '<button class="preview-action driver-action" type="button" data-driver-action="sign_out">Sign Out</button>' +
        '</div>';
    }
    if (mobileUiState === "loading_assignment") {
      return wrapDriverMobilePage(
        driverSessionHeader +
        '<div class="driver-workflow-card"><strong>Loading assignment</strong>' +
        '<p class="muted">Syncing active ride for the authenticated driver session…</p></div>'
      );
    }
    if (mobileUiState === "api_error") {
      return wrapDriverMobilePage(
        driverSessionHeader +
        '<div class="driver-workflow-card" style="border-color:#fca5a5;background:#fff7f7;">' +
        '<strong>Assignment sync error</strong>' +
        '<p class="muted">' + escapeHtml(
          safeText(
            appState.syncWarning,
            safeText(appState.mobileBootstrapError, "Unable to load driver assignment. Refresh to retry.")
          )
        ) + '</p>' +
        '<button class="preview-action driver-action" type="button" onclick="window.AmiOpsShellActions && window.AmiOpsShellActions.retryDriverMobileAssignmentSync && window.AmiOpsShellActions.retryDriverMobileAssignmentSync()">Retry Sync</button>' +
        '</div>'
      );
    }
    var queue = Array.isArray(appState.tripQueue) ? appState.tripQueue : [];
    var activeTrip = resolveDriverActiveTrip(appState.activeTripId) || getDriverTripById(appState.activeTripId);
    if (activeTrip && isDriverMobileSurface()) {
      appState.shiftOnline = true;
    }
    var waitingLabels = driverMobileWaitingLabels();
    var riderName = activeTrip ? safeText(activeTrip.patient, "Rider pending") : waitingLabels.riderName;
    var routePickup = activeTrip ? safeText(activeTrip.pickup, "Pickup pending") : waitingLabels.routePickup;
    var routeDropoff = activeTrip ? safeText(activeTrip.dropoff, "Destination pending") : waitingLabels.routeDropoff;
    var providerName = "Unassigned Provider";
    var assignedDriverLabel = "Unassigned Driver";
    var riderPhone = activeTrip ? safeText(activeTrip.riderPhone || activeTrip.phone, "") : "";
    var tripStatus = activeTrip ? normalizeDriverTripStatus(activeTrip.status) : "none";
    var shiftOnline = asBoolean(appState.shiftOnline, false);
    var isTerminal = ["completed", "cancelled", "declined"].indexOf(tripStatus) >= 0;
    var canAccept = ["queued", "assigned", "offered", "pending"].indexOf(tripStatus) >= 0
      && ["accepted", "en_route_pickup", "driver_en_route", "arrived", "rider_onboard", "in_progress", "in_transit", "arrived_destination"].indexOf(tripStatus) < 0;
    var canStartRoute = ["accepted", "assigned"].indexOf(tripStatus) >= 0;
    var canArrive = ["driver_en_route", "en_route_pickup"].indexOf(tripStatus) >= 0;
    var canPickup = ["arrived", "at_pickup", "arrived_pickup", "waiting_at_pickup"].indexOf(tripStatus) >= 0;
    var canStartTransport = ["rider_onboard", "rider_loaded"].indexOf(tripStatus) >= 0;
    var canArriveDestination = ["in_progress", "in_transit", "trip_in_progress"].indexOf(tripStatus) >= 0;
    var canComplete = ["arrived_destination"].indexOf(tripStatus) >= 0;
    var disableAccept = !shiftOnline || !activeTrip || !canAccept || isTerminal;
    var disableStartRoute = !shiftOnline || !activeTrip || !canStartRoute || isTerminal;
    var disableArrive = !shiftOnline || !activeTrip || !canArrive || isTerminal;
    var disableNoShow = !shiftOnline || !activeTrip || isTerminal;
    var disablePickup = !shiftOnline || !activeTrip || !canPickup || isTerminal;
    var disableStartTransport = !shiftOnline || !activeTrip || !canStartTransport || isTerminal;
    var disableArriveDestination = !shiftOnline || !activeTrip || !canArriveDestination || isTerminal;
    var disableComplete = !shiftOnline || !activeTrip || !canComplete || isTerminal;
    var secondaryTab = safeText(appState.secondaryTab, "earnings").toLowerCase();
    var etaText = String(activeTrip ? safeNumber(activeTrip.etaMin, 0) : 0) + " min";
    var notifications = Array.isArray(appState.notifications) ? appState.notifications : [];
    var allRides = Array.isArray((safeObject(state.liveWorkflow)).rides) ? state.liveWorkflow.rides : [];
    var providers = Array.isArray((safeObject(state.liveWorkflow)).providers) ? state.liveWorkflow.providers : [];
    var drivers = Array.isArray((safeObject(state.liveWorkflow)).drivers) ? state.liveWorkflow.drivers : [];
    var currentDriverId = safeText(appState.currentDriverId, "");
    var completedRides = Array.isArray(appState.completedRideHistory) ? appState.completedRideHistory.slice() : [];
    var workflowCompleted = Array.isArray((safeObject(state.driverWorkflow)).completedRides)
      ? state.driverWorkflow.completedRides
      : [];
    if (workflowCompleted.length) {
      var seenCompleted = {};
      completedRides.forEach(function (ride) {
        seenCompleted[safeText(ride.id, "")] = true;
      });
      workflowCompleted.forEach(function (ride) {
        var rideId = safeText(ride.id || ride.ride_id, "");
        if (!rideId || seenCompleted[rideId]) return;
        seenCompleted[rideId] = true;
        completedRides.unshift(ride);
      });
    }
    var workflowAssigned = Array.isArray((safeObject(state.driverWorkflow)).assignedRides)
      ? state.driverWorkflow.assignedRides
      : [];
    var assignedRides = workflowAssigned.slice();
    if (!assignedRides.length && !isDriverMobileSurface() && safeText(state.role, "").toLowerCase() !== "driver") {
      assignedRides = allRides.filter(function (ride) {
        var status = normalizeRideStatusToken(ride.status || ride.lifecycle_state);
        return ["pending", "assigned", "queued", "offered", "accepted", "driver_en_route", "arrived", "rider_onboard", "in_progress"].indexOf(status) >= 0
          && (!currentDriverId || safeText(ride.driver_id, "") === currentDriverId);
      });
    }
    if (!assignedRides.length && queue.length) {
      assignedRides = queue.filter(function (trip) {
        var status = safeText(trip.status, "").toLowerCase();
        return ["pending", "assigned", "queued", "driver_en_route", "arrived", "rider_onboard", "in_progress", "in_transit"].indexOf(status) >= 0;
      }).map(function (trip) {
        return {
          id: safeText(trip.tripId, "ride"),
          status: safeText(trip.status, "assigned"),
          pickup_address: safeText(trip.pickup, "pickup"),
          dropoff_address: safeText(trip.dropoff, "dropoff"),
          driver_id: safeText(currentDriverId || trip.assignedDriver, "")
        };
      });
    }
    var driverTimeline = Array.isArray((safeObject(state.driverWorkflow)).workspace && (safeObject(state.driverWorkflow)).workspace.timeline_states)
      ? (safeObject(state.driverWorkflow)).workspace.timeline_states
      : [];
    var result = safeObject(appState.lastActionResult);
    var billingHandoffs = Array.isArray(appState.billingHandoffs) ? appState.billingHandoffs : [];
    var workflowHandoffs = Array.isArray((safeObject(state.driverWorkflow)).billingHandoffs)
      ? state.driverWorkflow.billingHandoffs
      : [];
    billingHandoffs = dedupeBillingHandoffsByRideId(
      workflowHandoffs.length ? workflowHandoffs.concat(billingHandoffs) : billingHandoffs
    ).slice(0, 30);

    if (activeTrip) {
      var workflowActive = safeObject((safeObject(state.driverWorkflow)).activeRide);
      var workflowRide = safeObject(workflowActive.ride);
      var workflowAssignment = safeObject(workflowActive.active_assignment);
      var activeRide = safeText(workflowRide.id, "")
        ? workflowRide
        : (allRides.find(function (ride) {
            return safeText(ride.id, "") === safeText(activeTrip.tripId, "");
          }) || {});
      var assignedDriver = drivers.find(function (item) {
        return safeText(item.id, "") === safeText(activeTrip.assignedDriver || activeRide.driver_id || workflowRide.driver_id, "");
      }) || {};
      var provider = providers.find(function (item) {
        return safeText(item.id, "") === safeText(activeRide.provider_id || workflowRide.provider_id, "");
      }) || {};
      providerName = safeText(
        activeTrip.providerName || workflowActive.provider_name || provider.name || provider.provider_name,
        providerName
      );
      assignedDriverLabel = safeText(
        activeTrip.assignedDriverName
          || workflowActive.driver_name
          || assignedDriver.name
          || assignedDriver.driver_name
          || activeRide.driver_id
          || activeTrip.assignedDriver,
        assignedDriverLabel
      );
    }
    var acceptedCount = safeNumber(appState.acceptedCount, 0);
    var declinedCount = safeNumber(appState.declinedCount, 0);
    var completedTrips = safeNumber(appState.completedTrips, 0);
    var historyRides = Array.isArray(appState.completedRideHistory) ? appState.completedRideHistory : completedRides;
    var earningsPayload = safeObject((safeObject(state.driverWorkflow)).earnings);
    var earningsDisplay = deriveDriverEarningsDisplayFields(
      earningsPayload,
      historyRides,
      billingHandoffs
    );
    var earningsToday = earningsDisplay.earningsToday;
    var earningsLifetime = earningsDisplay.earningsLifetime;
    completedTrips = Math.max(completedTrips, earningsDisplay.completedTrips);
    var billingHandoffCount = Math.max(billingHandoffs.length, earningsDisplay.billingHandoffCount);
    var recentEarningsTrips = Array.isArray(earningsPayload.recent_trips) ? earningsPayload.recent_trips : [];
    var historyRows = historyRides.slice(0, 12).map(function (ride) {
      var fare = safeNumber(ride.fare_amount || ride.estimated_fare_usd || ride.ride_price_usd, 0);
      var payout = safeNumber(ride.driver_pay_usd || ride.payout_amount, 0);
      return '<li><strong>' + escapeHtml(safeText(ride.passenger_name, shortOperationalId(ride.id, "Trip"))) + '</strong> • '
        + escapeHtml(titleizeWords(safeText(ride.lifecycle_state || ride.status, "completed"))) + ' • '
        + escapeHtml(safeText(ride.pickup_address, "pickup"))
        + (fare > 0 ? ' • Fare $' + escapeHtml(fare.toFixed(2)) : '')
        + (payout > 0 ? ' • Pay $' + escapeHtml(payout.toFixed(2)) : '')
        + '</li>';
    }).join("");

    var secondaryContent = '';
    if (secondaryTab === "documents") {
      secondaryContent = '<h4>Trip Documents & Receipts</h4>' + renderDriverComplianceTable(appState.documents);
    } else if (secondaryTab === "history") {
      secondaryContent = '<h4>Completed Trip History</h4>' +
        (historyRows
          ? '<ul class="driver-notification-list">' + historyRows + '</ul>'
          : '<p class="muted">No completed trips yet.</p>') +
        '<h4 style="margin-top:12px;">Recent Notifications</h4><ul class="driver-notification-list">' + renderDriverNotifications(notifications) + '</ul>';
    } else {
      var earningsTripRows = (recentEarningsTrips.length ? recentEarningsTrips : historyRides).slice(0, 8).map(function (trip) {
        var pay = safeNumber(trip.driver_pay_usd || trip.payout_amount, 0);
        var price = safeNumber(trip.ride_price_usd || trip.fare_amount, 0);
        return '<tr><td>' + escapeHtml(shortOperationalId(trip.ride_id || trip.id, "ride")) + '</td><td>$'
          + escapeHtml(pay.toFixed(2)) + '</td><td>$' + escapeHtml(price.toFixed(2)) + '</td><td>'
          + escapeHtml(safeText(trip.completed_at || trip.updated_at, "n/a")) + '</td></tr>';
      }).join("");
      secondaryContent = '<h4>Earnings</h4>' +
        '<div class="grid-2">' +
          '<div class="tile"><strong>$' + escapeHtml(String(earningsToday.toFixed(2))) + '</strong><p class="muted">Today</p></div>' +
          '<div class="tile"><strong>$' + escapeHtml(String(earningsLifetime.toFixed(2))) + '</strong><p class="muted">Lifetime</p></div>' +
          '<div class="tile"><strong>' + escapeHtml(String(completedTrips)) + '</strong><p class="muted">Completed Trips</p></div>' +
          '<div class="tile"><strong>' + escapeHtml(String(billingHandoffCount)) + '</strong><p class="muted">Billing Handoffs</p></div>' +
        '</div>' +
        '<div class="table-wrap" style="margin-top:10px;"><table class="ops-table"><thead><tr><th>Ride</th><th>Driver Pay</th><th>Fare</th><th>Completed</th></tr></thead><tbody>' +
          (earningsTripRows || '<tr><td colspan="4">No earnings rows yet.</td></tr>') +
        '</tbody></table></div>';
    }

    return wrapDriverMobilePage(
      driverSessionHeader +
      '<div class="driver-mobile-layout">' +
        '<section class="driver-mobile-phone">' +
          '<header class="driver-mobile-head">' +
            '<div><strong>Available Offers</strong><p>Immediate dispatch offers only</p></div>' +
          '</header>' +
          '<article class="driver-workflow-card">' +
            (immediateOffer && safeText(immediateOffer.ride_id, "")
              ? '<p><strong>Offer:</strong> ' + escapeHtml(shortOperationalId(immediateOffer.ride_id, "ride")) +
                ' • ' + escapeHtml(safeText(immediateOffer.pickup_address, "Pickup")) + '</p>'
              : '<p class="muted">No immediate offers right now.</p>') +
          '</article>' +
          '<header class="driver-mobile-head" style="margin-top:12px;">' +
            '<div><strong>Upcoming Schedule</strong><p>Future reserved rides</p></div>' +
          '</header>' +
          '<article class="driver-workflow-card">' +
            (upcomingSchedule.length
              ? upcomingSchedule.map(function (item) {
                  var row = safeObject(item);
                  var acceptBtn = row.can_accept
                    ? '<button class="preview-action driver-action" data-driver-action="accept_scheduled_ride" data-trip-id="' + escapeHtml(safeText(row.ride_id, "")) + '">Accept Scheduled Ride</button>'
                    : '<span class="muted">Reserved</span>';
                  return '<div class="driver-schedule-row" style="margin-bottom:10px;padding-bottom:10px;border-bottom:1px solid #e5e7eb;">' +
                    '<p><strong>' + escapeHtml(safeText(row.rider_name, "Rider")) + '</strong> • ' + escapeHtml(titleizeWords(safeText(row.trip_leg, "one_way"))) + '</p>' +
                    '<p class="muted">' + escapeHtml(safeText(row.pickup_address, "Pickup")) + ' → ' + escapeHtml(safeText(row.dropoff_address, "Dropoff")) + '</p>' +
                    '<p class="muted">Pickup: ' + escapeHtml(safeText(row.pickup_time, "pending")) +
                    (safeText(row.return_pickup_time, "") ? (' • Return: ' + escapeHtml(safeText(row.return_pickup_time, ""))) : '') + '</p>' +
                    '<p class="muted">Reminder: ' + escapeHtml(safeText(row.reminder_status, "pending")) + '</p>' +
                    acceptBtn +
                  '</div>';
                }).join("")
              : '<p class="muted">No upcoming scheduled rides.</p>') +
          '</article>' +
          '<header class="driver-mobile-head" style="margin-top:12px;">' +
            '<div><strong>Current Trip</strong><p>' + escapeHtml(shiftOnline ? 'Online and dispatch-ready' : 'Offline') + '</p></div>' +
            '<span class="status-dot">' + escapeHtml(activeTrip ? titleizeWords(safeText(activeTrip.status, appState.activeStage)) : waitingLabels.statusLabel) + '</span>' +
          '</header>' +
          (activeTrip
            ? ''
            : '<p class="muted driver-awaiting-assignment">Awaiting Assignment — no immediate trip is loaded. Reserved rides stay in <strong>Upcoming Schedule</strong>; immediate offers appear under <strong>Available Offers</strong>.</p>') +
          '<article class="driver-workflow-card">' +
            '<h4>Primary Workflow</h4>' +
            (activeTrip
              ? ('<div class="table-wrap"><table class="ops-table"><tbody>' +
              '<tr><th>Ride ID</th><td>' + escapeHtml(shortOperationalId(activeTrip.tripId, "n/a")) + '</td></tr>' +
              '<tr><th>Rider Name</th><td>' + escapeHtml(riderName) + '</td></tr>' +
              '<tr><th>Pickup Address</th><td>' + escapeHtml(routePickup) + '</td></tr>' +
              '<tr><th>Destination Address</th><td>' + escapeHtml(routeDropoff) + '</td></tr>' +
              (safeText(activeTrip.schedulingSummary, "")
                ? '<tr><th>Scheduling</th><td>' + escapeHtml(safeText(activeTrip.schedulingSummary, "")) + (safeText(activeTrip.tripLeg, "") ? (' (' + escapeHtml(titleizeWords(safeText(activeTrip.tripLeg, ""))) + ')') : '') + '</td></tr>'
                : '') +
              '<tr><th>Provider</th><td>' + escapeHtml(providerName) + '</td></tr>' +
              '<tr><th>Driver Assigned</th><td>' + escapeHtml(assignedDriverLabel) + '</td></tr>' +
              '<tr><th>ETA</th><td>' + escapeHtml(etaText) + '</td></tr>' +
            '</tbody></table></div>' +
            '<div class="command-actions">' +
              '<button class="preview-action driver-action" data-driver-action="accept_trip" data-trip-id="' + escapeHtml(safeText(activeTrip.tripId, "")) + '"' + (disableAccept ? ' disabled' : '') + '>Accept Trip</button>' +
              '<button class="preview-action driver-action" data-driver-action="start_route" data-trip-id="' + escapeHtml(safeText(activeTrip.tripId, "")) + '"' + (disableStartRoute ? ' disabled' : '') + '>Start Route / En Route to Pickup</button>' +
              '<button class="preview-action driver-action" data-driver-action="arrive_pickup" data-trip-id="' + escapeHtml(safeText(activeTrip.tripId, "")) + '"' + (disableArrive ? ' disabled' : '') + '>Arrived at Pickup</button>' +
              '<button class="preview-action driver-action" data-driver-action="start_trip" data-trip-id="' + escapeHtml(safeText(activeTrip.tripId, "")) + '"' + (disablePickup ? ' disabled' : '') + '>Rider On Board / Picked Up</button>' +
              '<button class="preview-action driver-action" data-driver-action="start_transport" data-trip-id="' + escapeHtml(safeText(activeTrip.tripId, "")) + '"' + (disableStartTransport ? ' disabled' : '') + '>Start Transportation</button>' +
              '<button class="preview-action driver-action" data-driver-action="arrive_destination" data-trip-id="' + escapeHtml(safeText(activeTrip.tripId, "")) + '"' + (disableArriveDestination ? ' disabled' : '') + '>Arrived at Destination</button>' +
              '<button class="preview-action driver-action" data-driver-action="complete_trip" data-trip-id="' + escapeHtml(safeText(activeTrip.tripId, "")) + '"' + (disableComplete ? ' disabled' : '') + '>Complete Trip</button>' +
              (riderPhone
                ? '<button class="preview-action driver-action" data-driver-action="call_rider" data-trip-id="' + escapeHtml(safeText(activeTrip.tripId, "")) + '">Call Rider</button>'
                : '<button class="preview-action" disabled>Call Rider</button>') +
              '<button class="preview-action driver-action" data-driver-action="decline_trip" data-trip-id="' + escapeHtml(safeText(activeTrip.tripId, "")) + '"' + (disableNoShow ? ' disabled' : '') + '>No Show</button>' +
            '</div>')
              : '<p class="muted driver-no-immediate-workflow">Trip workflow controls appear here when an immediate offer or active assignment is loaded from the server.</p>') +
            '<p class="muted">Latest update: ' + escapeHtml(safeText(appState.lastStatusUpdate, 'None')) + '</p>' +
            (function () {
              var syncWarning = safeText(appState.syncWarning, "");
              var latestUpdate = safeText(appState.lastStatusUpdate, "");
              if (!syncWarning || syncWarning === latestUpdate) return "";
              return '<p class="muted" style="color:#b45309;">' + escapeHtml(syncWarning) + '</p>';
            })() +
          '</article>' +
          renderDriverOperationalMap(activeTrip) +
          '<article class="driver-workflow-card">' +
            '<h4>Result Output</h4>' +
            '<div class="grid-3">' +
              renderMetric('Last Action', safeText(result.last_action, 'none')) +
              renderMetric('API Status', safeText(result.api_status, 'idle'), safeText(result.api_status, 'idle') === 'ok' ? 'good' : (safeText(result.api_status, 'idle') === 'idle' ? 'warn' : 'bad')) +
              renderMetric('Database Record ID', safeText(result.db_record_id, 'n/a')) +
              renderMetric('Updated Table', safeText(result.updated_table, 'n/a')) +
              renderMetric('UI Refreshed', safeText(result.ui_refreshed, 'no')) +
              renderMetric('Current Ride Status', safeText(result.current_ride_status, safeText(activeTrip && activeTrip.status, 'unknown'))) +
            '</div>' +
          '</article>' +
          '<article class="driver-workflow-card">' +
            '<h4>Assigned Queue</h4>' +
            '<div class="driver-mobile-queue">' + renderDriverQueueCards(queue, appState.activeTripId) + '</div>' +
          '</article>' +
          '<article class="driver-workflow-card">' +
            '<h4>Live Lists</h4>' +
            '<div class="table-wrap"><table class="ops-table"><thead><tr><th>Assigned Rides</th><th>Status</th><th>Pickup</th><th>Dropoff</th></tr></thead><tbody>' +
              (assignedRides.length
                ? assignedRides.slice(0, 12).map(function (ride) {
                    return '<tr><td>' + escapeHtml(safeText(ride.id, 'ride')) + '</td><td>' + escapeHtml(safeText(ride.status, 'pending')) + '</td><td>' + escapeHtml(safeText(ride.pickup_address, 'pickup')) + '</td><td>' + escapeHtml(safeText(ride.dropoff_address, 'dropoff')) + '</td></tr>';
                  }).join('')
                : '<tr><td colspan="4">No assigned rides found.</td></tr>') +
            '</tbody></table></div>' +
            '<div class="table-wrap" style="margin-top:10px;"><table class="ops-table"><thead><tr><th>Completed Rides</th><th>Status</th><th>Driver</th><th>Updated</th></tr></thead><tbody>' +
              (completedRides.length
                ? completedRides.slice(0, 12).map(function (ride) {
                    return '<tr><td>' + escapeHtml(safeText(ride.passenger_name, shortOperationalId(ride.id, 'ride'))) + '</td><td>' + escapeHtml(safeText(ride.status, 'completed')) + '</td><td>' + escapeHtml(shortOperationalId(ride.driver_id, 'driver')) + '</td><td>' + escapeHtml(safeText(ride.updated_at || ride.completed_at, 'n/a')) + '</td></tr>';
                  }).join('')
                : '<tr><td colspan="4">No completed rides found for this driver.</td></tr>') +
            '</tbody></table></div>' +
            '<div class="table-wrap" style="margin-top:10px;"><table class="ops-table"><thead><tr><th>Active Trip Events</th><th>Sequence</th></tr></thead><tbody>' +
              (driverTimeline.length
                ? driverTimeline.slice(-10).map(function (eventState, idx) {
                    return '<tr><td>' + escapeHtml(safeText(eventState, 'event')) + '</td><td>' + escapeHtml(String(idx + 1)) + '</td></tr>';
                  }).join('')
                : '<tr><td colspan="2">No active trip events yet.</td></tr>') +
            '</tbody></table></div>' +
            '<div class="table-wrap" style="margin-top:10px;"><table class="ops-table"><thead><tr><th>Billing Handoff</th><th>Ride ID</th><th>Payment ID</th><th>Status</th></tr></thead><tbody>' +
              (billingHandoffs.length
                ? billingHandoffs.slice(0, 12).map(function (row) {
                    return '<tr><td>' + escapeHtml(shortOperationalId(row.handoff_id, 'handoff')) + '</td><td>' + escapeHtml(shortOperationalId(row.ride_id, 'ride')) + '</td><td>' + escapeHtml(shortOperationalId(row.payment_id, 'pending')) + '</td><td>' + escapeHtml(safeText(row.status, 'ready_for_billing')) + '</td></tr>';
                  }).join('')
                : '<tr><td colspan="4">No billing handoffs created yet.</td></tr>') +
            '</tbody></table></div>' +
          '</article>' +
        '</section>' +
        '<section class="driver-mobile-ops">' +
          '<article class="driver-workflow-card">' +
            '<h4>Secondary Tabs</h4>' +
            '<div class="command-actions">' +
              '<button class="preview-action driver-action' + (secondaryTab === "earnings" ? ' active' : '') + '" data-driver-action="show_earnings">Earnings</button>' +
              '<button class="preview-action driver-action' + (secondaryTab === "documents" ? ' active' : '') + '" data-driver-action="show_documents">Documents</button>' +
              '<button class="preview-action driver-action' + (secondaryTab === "history" ? ' active' : '') + '" data-driver-action="show_history">History</button>' +
            '</div>' +
            '<div class="driver-secondary-content">' + secondaryContent + '</div>' +
          '</article>' +
        '</section>' +
      '</div>'
    );
  }

  function renderRiderDashboard(phase17) {
    var slice = buildRoleHydrationSlice("rider", phase17);
    var supervisionStatus = safeText(((phase17 || {}).supervision || {}).supervision_status, "unknown");
    // Suppress "Unavailable" when auth token is present OR when supervision is healthy (backend data flowing)
    var isAuthenticated = asBoolean((state.hydration || {}).authTokenPresent, false);
    var supervisionHealthy = safeText((state.supervision || {}).supervision_status, "unknown") === "healthy";
    var riderEmptyState = (!slice.hasOperationalData && !isAuthenticated && !supervisionHealthy)
      ? renderPanelBlock(
        "Rider Workspace Unavailable",
        "Rider hydration data is not available yet.",
        '<p class="muted">The rider dashboard is loading with an empty state. Timeline, queue, routes, metrics, and alerts will populate when operational hydration arrives.</p>',
        "rider-empty-state"
      )
      : "";
    return [
      renderRoleIdentityPanel("rider", slice, supervisionStatus),
      riderEmptyState,
      renderHydrationStatusPanel("Rider", slice),
      renderOperationalHeartbeatPanel(slice),
      renderStreamStatusPanel(phase17),
      renderAuthDiagnosticsCard(slice),
      renderRiderAppExperience(slice),
      renderPanelBlock(
        "Rider Home Actions",
        "Quick access to the live rider workflow, support, and trip controls.",
        renderQuickLinks(roleWorkspaceLinks("rider", "homeLinks", [
          { href: "/app/riders", title: "Rider App", description: "Book rides, track active trips, and manage support.", note: "live" },
          { href: "/app/trips", title: "Trip Timeline", description: "See ride history, active trip context, and support posture.", note: "read-only" },
          { href: "/app/alerts", title: "Safety & Support", description: "Escalate ride concerns through supervised support flows.", note: "supervised" }
        ])),
        "rider-actions"
      ),
      renderRoleMapPlaceholder("Rider Trip Map Placeholder", "Pickup and drop-off context panel for the customer experience."),
      renderEnhancedOperationalTimeline("Ride Timeline", "Ride timeline with category/priority/source tags.", slice.timeline, 8),
      renderPanelBlock(
        "Rider Support Desk",
        "Guided support entry points for trip help, payment questions, and lost-item guidance.",
        '<div class="grid-2">' +
          '<div class="tile"><h4>Help Center</h4><p>Trip help, payment questions, and lost-item guidance flow through a supervised support desk.</p></div>' +
          '<div class="tile"><h4>Safety Contact</h4><p>Escalations attach to the live trip and dispatch history for audit continuity.</p></div>' +
          '<div class="tile"><h4>Saved Locations</h4><p>Home, clinic, and work anchors are ready for repeat booking shortcuts.</p></div>' +
          '<div class="tile"><h4>Notification Center</h4><p>' + escapeHtml(String((slice.alerts || []).length)) + ' advisory notice(s) currently visible.</p></div>' +
        '</div>',
        'support'
      ),
      renderRoleAiGuidance("Rider", "Driver is approaching pickup. Heavy traffic advisory may affect ETA. Pickup zone guidance is advisory only; no trip changes are executed.")
    ].join("");
  }

  function renderDriverRoleHomeDashboard(phase17) {
    var slice = buildRoleHydrationSlice("driver", phase17);
    var driverApp = safeObject(state.driverApp);
    var workflow = safeObject(state.driverWorkflow);
    var activeTripId = safeText(driverApp.activeTripId, "") || safeText((safeObject(workflow.activeRide && workflow.activeRide.ride)).id, "");
    var syncWarning = safeText(driverApp.syncWarning, "");
    return [
      renderRoleIdentityPanel("driver", slice, safeText((phase17.supervision || {}).supervision_status, "unknown")),
      renderHydrationStatusPanel("Driver", slice),
      renderOperationalHeartbeatPanel(slice),
      renderPanelBlock(
        "Driver Operations Home",
        "Command overview and entry points. Open Driver Mobile for live assignment sync and trip workflow.",
        '<div class="grid-4">' +
          renderMetric("Active Trip", activeTripId ? activeTripId.slice(0, 8) : "None") +
          renderMetric("Shift", driverApp.shiftOnline ? "Online" : "Offline") +
          renderMetric("Assignment Sync", syncWarning ? "Retry needed" : "Ready", syncWarning ? "warn" : "good") +
          renderMetric("Queued Offers", String(Array.isArray(workflow.tripQueue) ? workflow.tripQueue.length : 0)) +
        '</div>' +
        renderQuickLinks(roleWorkspaceLinks("driver", "homeLinks", [
          { href: "/app/mobile", title: "Driver Mobile App", description: "Accept assignments, run pickup workflow, and complete trips.", note: "live" },
          { href: "/app/trips", title: "Trip Timeline", description: "Review active and completed transport history.", note: "read-only" },
          { href: "/app/billing", title: "Earnings", description: "Trip payouts and billing handoff visibility.", note: "live" }
        ])),
        "driver-home"
      ),
      renderRoleAiGuidance("Driver", "Driver Mobile is the authoritative assignment surface. This dashboard stays read-only for trip actions.")
    ].join("");
  }

  function renderDriverDashboard(phase17) {
    var slice = buildRoleHydrationSlice("driver", phase17);
    if (state.route === "mobile") {
      return renderDriverMobileExperience(phase17, slice);
    }
    return renderDriverRoleHomeDashboard(phase17);
  }

  function renderProviderDashboard(phase17) {
    var slice = buildRoleHydrationSlice("provider", phase17);
    var workspace = state.ops.workspaceActivation || {};
    var modules = safeObject(workspace.workspace_modules);
    var providerSyncQueue = Array.isArray(modules.trip_provider_coordination)
      ? modules.trip_provider_coordination
      : (Array.isArray(modules.provider_sync_queue) ? modules.provider_sync_queue : []);
    var providerRows = providerSyncQueue.slice(0, 14).map(function (item, idx) {
      var priority = safeText(item.priority, "medium").toLowerCase();
      var pc = priority === "critical" || priority === "high" ? "badge badge-bad" : priority === "medium" ? "badge badge-warn" : "badge badge-soft";
      var stateText = safeText(item.task_state || item.state, "queued");
      return '<tr><td>' + escapeHtml(safeText(item.task_id || item.id, "PROV-" + String(idx + 1))) + '</td><td>' + escapeHtml(safeText(item.title || item.task_type, "provider_sync")) + '</td><td>' + escapeHtml(safeText(item.assigned_role || "provider")) + '</td><td><span class="' + pc + '">' + escapeHtml(priority) + '</span></td><td>' + escapeHtml(stateText) + '</td><td class="muted">' + escapeHtml(safeText(item.updated_at || item.created_at, "pending")) + '</td><td><button class="btn-action" onclick="window._amiHandleProviderSync(\'' + escapeHtml(safeText(item.task_id || item.id, "")) + '\')">Open Sync</button></td></tr>';
    }).join("");
    var queueHealth = safeObject((((state.ops.orchestration || {}).queue_health || {}).queue_pressure_dashboard));
    var complianceOverview = safeObject(((state.ops.compliance || {}).compliance_overview));
    return [
      renderRoleIdentityPanel("provider", slice, safeText((phase17.supervision || {}).supervision_status, "unknown")),
      renderHydrationStatusPanel("Provider", slice),
      renderOperationalHeartbeatPanel(slice),
      renderStreamStatusPanel(phase17),
      renderAuthDiagnosticsCard(slice),
      renderPanelBlock(
        "Provider Healthcare Portal",
        "Provider coverage balancing, response backlog management, and appointment-window coordination workflows.",
        '<div class="grid-4">' +
          renderMetric("Patients Scheduled", String(safeNumber((phase17.lifecycle || {}).REQUESTED, 0))) +
          renderMetric("Active Providers", String(safeNumber((phase17.providerStates || {}).active, 0))) +
          renderMetric("Active Facility Requests", String(safeNumber(slice.activeRides, 0))) +
          renderMetric("Pending Authorizations", String(safeNumber((complianceOverview.pending_authorizations), 0))) +
          renderMetric("Provider Coordination Load", String(safeNumber(queueHealth.pressure_index, 0))) +
          renderMetric("Provider Response Queue", String(providerSyncQueue.length)) +
          renderMetric("Transport Readiness", "live") +
          renderMetric("Regulated Posture", safeText((phase17.supervision || {}).supervision_status, "unknown")) +
        '</div>' +
        '<div class="grid-2">' +
          '<article class="tile"><h4>Provider Capacity</h4><p>Capacity reflects live dispatch demand, coverage balancing, and continuity-sensitive transport prioritization.</p></article>' +
          '<article class="tile"><h4>Facility Coordination</h4><p>Facility sync requests move through provider response queues when confirmation backlogs build.</p></article>' +
          '<article class="tile"><h4>Threshold Monitoring</h4><p>Provider delay signals surface for supervisor review before assignment recovery decisions.</p></article>' +
          '<article class="tile"><h4>Authorization Controls</h4><p>Authorization exceptions route through compliance and supervisor chains to protect appointment continuity.</p></article>' +
        '</div>',
        'provider'
      ),
      renderPanelBlock(
        "Provider Sync Queue",
        "Provider response queue and assignment balancing backlog under supervisor review.",
        '<div class="table-wrap"><table class="ops-table"><thead><tr><th>Task</th><th>Title</th><th>Role</th><th>Priority</th><th>State</th><th>Updated</th><th>Action</th></tr></thead><tbody>' + providerRows + '</tbody></table></div>',
        "provider-queue"
      ),
      renderRoleMapPlaceholder("Provider Coverage and Facility Map", "Regional service coverage, facility demand, and treatment route visualization."),
      renderEnhancedOperationalTimeline("Provider Operations Timeline", "Provider-facing operational history and alerts.", slice.timeline, 8),
      renderPanelBlock(
        "Provider Recommendations",
        "Advisory recommendations for scheduling, fleet utilization, billing readiness, and authorization throughput.",
        '<ul class="list">' +
          '<li><strong>Scheduling:</strong> auto-suggest recurring transport windows around high-volume treatment blocks.</li>' +
          '<li><strong>Reimbursement:</strong> prioritize claims with incomplete trip evidence before billing close.</li>' +
          '<li><strong>Authorization:</strong> escalate requests breaching approval SLA to supervisor queue.</li>' +
        '</ul>' +
        '<p class="muted">Recommendations are governed and supervised; no unsupervised financial or dispatch actions run from this panel.</p>',
        'recommendations'
      ),
      renderRoleAiGuidance("Provider", "Coverage gap, peak demand, and driver shortage advisories are informational only and require supervised decision workflows.")
    ].join("");
  }

  function renderDispatcherDashboard(phase17) {
    var dispatcherSlice = buildRoleHydrationSlice("dispatcher", phase17);
    var queuePressure = safeText((((state.ops.orchestration || {}).queue_health || {}).queue_pressure_dashboard || {}).state, "stable");
    var liveEvents = Array.isArray((((state.ops.orchestration || {}).live_stream || {}).events)) ? (((state.ops.orchestration || {}).live_stream || {}).events) : [];
    var requestedTrips = safeNumber((phase17.lifecycle || {}).REQUESTED, 0);
    var assignedTrips = safeNumber((phase17.lifecycle || {}).ASSIGNED, 0);
    var inProgressTrips = safeNumber((phase17.lifecycle || {}).IN_PROGRESS, 0);
    var openTrips = requestedTrips + assignedTrips + inProgressTrips;
    var assignmentCoverage = openTrips > 0 ? Math.round((assignedTrips / openTrips) * 100) : 0;
    var escalationAlerts = ((((state.ops.orchestration || {}).sla || {}).alerts) || []);
    return [
      renderRoleIdentityPanel("dispatcher", dispatcherSlice, safeText((phase17.supervision || {}).supervision_status, "unknown")),
      renderHydrationStatusPanel("Dispatcher", dispatcherSlice),
      renderOperationalHeartbeatPanel(dispatcherSlice),
      renderStreamStatusPanel(phase17),
      renderPanelBlock(
        "Dispatcher Operations Panel",
        "Medical transportation command center with assignment pressure, escalation ownership, and dispatch recovery posture.",
        '<div class="grid-4">' +
          renderMetric("Assignment Pressure", String(requestedTrips), requestedTrips > 0 ? "warn" : "good") +
          renderMetric("Coverage Recovery", String(assignedTrips), assignedTrips > 0 ? "good" : "warn") +
          renderMetric("Continuity-Sensitive Transports", String(inProgressTrips)) +
          renderMetric("Available Drivers", String(safeNumber((phase17.driverStates || {}).available, 0))) +
          renderMetric("Assignment Coverage", String(assignmentCoverage) + "%", assignmentCoverage >= 60 ? "good" : "warn") +
          renderMetric("Dispatch Flow Stability", queuePressure) +
          renderMetric("Active Escalations", String(escalationAlerts.length), escalationAlerts.length > 0 ? "warn" : "good") +
          renderMetric("Service Interruption Risks", String(countEventsByKeyword(phase17.events, "cancel"))) +
          renderMetric("Queue Stability", "managed") +
          renderMetric("Appointment-Window Coordination", "dispatcher enabled") +
        '</div>' +
        '<div class="divider"></div>' +
        '<div class="grid-4">' +
          renderMetric("Backlog Review", String(requestedTrips)) +
          renderMetric("Supervisor-Cleared Queue", String(assignedTrips)) +
          renderMetric("Active Transport Overflow Review", String(inProgressTrips)) +
          renderMetric("Queue Stability", String(assignmentCoverage) + "%", assignmentCoverage >= 60 ? "good" : "warn") +
        '</div>' +
        '<p class="muted">Ride flow visibility reflects current dispatch posture for clinic, dialysis, and continuity-sensitive transport coordination.</p>' +
        '<div class="divider"></div>' +
        renderQuickLinks(roleWorkspaceLinks("dispatcher", "dispatchLinks", [
          { href: "/app/dispatch", title: "Dispatch Center", description: "Open the live trip assignment center.", note: "primary" },
          { href: "/app/trips", title: "Trip Management", description: "Open the live trip flow board.", note: "live" },
          { href: "/app/drivers", title: "Driver Fleet", description: "Review drivers, assignments, and readiness.", note: "live" },
          { href: "/app/mobile", title: "Mobile Fleet View", description: "Switch to the mobile-ready operational view.", note: "responsive" }
        ])) +
        '<p class="muted">Assignment workflow and active transport controls remain supervision-guarded with service disruption prevention safeguards.</p>',
        'dispatcher'
      ),
      renderPanelBlock(
        "Dispatch Workbench",
        "Backlog control, route recovery coordination, and escalation management under supervisor oversight.",
        renderLiveDispatchBoard(),
        "dispatch-workbench"
      ),
      renderEnhancedOperationalTimeline("Dispatch Incident Feed", "Dispatch incidents, reassignment review, and provider response backlog updates.", liveEvents.concat(dispatcherSlice.timeline), 10),
      renderRoleAiGuidance("Dispatcher", "AI assistant proposes assignment balancing, priority routing, and escalation sequencing as supervised recommendations.")
    ].join("");
  }

  function renderAdminRoleDashboard() {
    var phase17 = getPhase17Context();
    var adminRevenue = state.adminRevenue && typeof state.adminRevenue === "object" ? state.adminRevenue : null;
    var billingCount = Array.isArray(state.liveWorkflow && state.liveWorkflow.billingHandoffs)
      ? state.liveWorkflow.billingHandoffs.length
      : 0;
    var platformRevenue = adminRevenue && adminRevenue.platform_revenue_total_usd != null
      ? ("$" + Number(adminRevenue.platform_revenue_total_usd).toFixed(2))
      : "$0.00";
    var completedTrips = adminRevenue && adminRevenue.completed_trip_count != null
      ? String(adminRevenue.completed_trip_count)
      : String(billingCount);
    return [
      renderPanelBlock(
        "Admin Overview",
        "Cross-surface operational summary for the live command platform.",
        '<div class="grid-4">' +
          renderMetric("Dispatch Queue", String(safeNumber((phase17.lifecycle || {}).REQUESTED, 0))) +
          renderMetric("Drivers Available", String(safeNumber((phase17.driverStates || {}).available, 0))) +
          renderMetric("Completed Trips", completedTrips) +
          renderMetric("Platform Revenue", platformRevenue) +
        '</div>' +
        '<div class="grid-2" style="margin-top:12px">' +
          renderMetric("Billing Handoffs", String(billingCount)) +
          renderMetric("AI Signals", String(phase17.assistantSignals || 0)) +
        '</div>',
        'admin'
      ),
      renderStreamStatusPanel(phase17),
      renderOperationsCommandCenter(),
      renderQuickLinks([
        { href: "/app/dashboard", title: "Dashboard", description: "Operational intelligence overview." },
        { href: "/app/dispatch", title: "Dispatch", description: "Live assignment and escalation control." },
        { href: "/app/billing", title: "Billing", description: "Completed-trip financial source of truth." },
        { href: "/app/drivers", title: "Drivers", description: "Driver operations workspace." },
        { href: "/app/riders", title: "Riders / Patients", description: "Rider and patient coordination." },
        { href: "/app/mobile", title: "Mobile Apps", description: "Driver and rider mobile surfaces." }
      ])
    ].join("");
  }

  function renderDashboard() {
    var phase17 = getPhase17Context();
    if (state.role === "dispatcher") return renderDispatcherDashboard(phase17);
    if (state.role === "rider") return renderRiderDashboard(phase17);
    if (state.role === "driver") return renderDriverRoleHomeDashboard(phase17);
    if (state.role === "provider") return renderProviderDashboard(phase17);
    if (state.role === "compliance_officer") return renderComplianceOfficerDashboard(phase17);
    if (state.role === "supervisor") return renderSupervisorDashboard(phase17);
    if (state.role === "driver_support") return renderDriverSupportDashboard(phase17);
    if (state.role === "medical_coordinator") return renderMedicalCoordinatorDashboard(phase17);
    return renderAdminRoleDashboard();
  }

  function renderComplianceOfficerDashboard(phase17) {
        var complianceSlice = buildRoleHydrationSlice("compliance_officer", phase17);
        var events = phase17.events || [];
        var warnings = countEventsByLevel(events, "warning");
        var errors = countEventsByLevel(events, "error");
        var workspace = state.ops.workspaceActivation || {};
        var modules = safeObject(workspace.workspace_modules);
        var sourceDocs = Array.isArray(modules.trip_audit_review) ? modules.trip_audit_review : (Array.isArray(((state.ops.compliance || {}).documents)) ? state.ops.compliance.documents : []);
        var expiringDocs = Array.isArray((((state.ops.compliance || {}).expiration_queue || {}).expiring_documents)) ? (((state.ops.compliance || {}).expiration_queue || {}).expiring_documents) : [];
        var expirationAlerts = Array.isArray(modules.compliance_expiration_alerts) ? modules.compliance_expiration_alerts : [];
        var onboardingQueue = Array.isArray(modules.compliance_onboarding_queue) ? modules.compliance_onboarding_queue : [];
        var evidenceFeed = Array.isArray(modules.compliance_evidence_feed) ? modules.compliance_evidence_feed : [];
        var complianceItems = sourceDocs.slice(0, 16).map(function (doc, idx) {
          var status = safeText(doc.status, "pending").toLowerCase();
          if (status === "expired" || status === "rejected") {
            status = "critical";
          } else if (status === "expiring" || status === "under_review") {
            status = "expiring";
          } else if (status === "approved" || status === "active") {
            status = "ok";
          } else {
            status = "watch";
          }
          return {
            id: safeText(doc.document_id || doc.id, "DOC-" + String(idx + 1)),
            driver: safeText(doc.driver_name || doc.owner_name || doc.driver_id, "unassigned"),
            type: safeText(doc.document_type || doc.type, "compliance_document"),
            expires: safeText(doc.expiration_date || doc.expires_on || doc.expires, "n/a"),
            status: status
          };
        });
        if (complianceItems.length === 0 && expiringDocs.length > 0) {
          complianceItems = expiringDocs.slice(0, 16).map(function (doc, idx) {
            return {
              id: safeText(doc.document_id || doc.id, "EXP-" + String(idx + 1)),
              driver: safeText(doc.driver_name || doc.driver_id, "unassigned"),
              type: safeText(doc.document_type || doc.type, "credential"),
              expires: safeText(doc.expiration_date || doc.expires_on || doc.expires, "n/a"),
              status: "expiring"
            };
          });
        }
        var tableRows = complianceItems.map(function(item) {
          var sc = item.status === "critical" ? "badge badge-bad" : item.status === "expiring" ? "badge badge-warn" : item.status === "watch" ? "badge badge-soft" : "badge badge-good";
          return '<tr><td>' + escapeHtml(item.id) + '</td><td>' + escapeHtml(item.driver) + '</td><td>' + escapeHtml(item.type) + '</td><td>' + escapeHtml(item.expires) + '</td><td><span class="' + sc + '">' + escapeHtml(item.status) + '</span></td><td><button class="btn-action" onclick="window._amiHandleComplianceReview(\'' + escapeHtml(item.id) + '\',\'' + escapeHtml(item.status) + '\')">Review</button></td></tr>';
        }).join("");
        var onboardingRows = onboardingQueue.slice(0, 12).map(function (item, idx) {
          var driverId = safeText(item.driver_id || item.profile_id, "DRV-" + String(idx + 1));
          return '<tr><td>' + escapeHtml(driverId) + '</td><td>' + escapeHtml(safeText(item.driver_name || item.full_name || item.name, "driver")) + '</td><td>' + escapeHtml(safeText(item.compliance_status, "pending")) + '</td><td>' + escapeHtml(safeText(item.approval_status, "pending")) + '</td><td><button class="btn-action" onclick="window._amiHandleComplianceOnboardingDecision(\'' + escapeHtml(driverId) + '\',true)">Approve</button> <button class="btn-action" onclick="window._amiHandleComplianceOnboardingDecision(\'' + escapeHtml(driverId) + '\',false)">Deny</button></td></tr>';
        }).join("");
        var expirationRows = expirationAlerts.slice(0, 12).map(function (item, idx) {
          return '<tr><td>' + escapeHtml(safeText(item.driver_id || item.document_id, "EXP-" + String(idx + 1))) + '</td><td>' + escapeHtml(safeText(item.type, "document")) + '</td><td>' + escapeHtml(safeText(item.status, "expiring_soon")) + '</td><td>' + escapeHtml(safeText(item.expiration_date, "n/a")) + '</td><td><button class="btn-action" onclick="window._amiHandleComplianceExpirationScan()">Refresh Alerts</button></td></tr>';
        }).join("");
        var evidenceRows = evidenceFeed.slice(0, 12).map(function (item, idx) {
          return '<tr><td>' + escapeHtml(safeText(item.event_id || item.sequence, "EVT-" + String(idx + 1))) + '</td><td>' + escapeHtml(safeText(item.action_type, "audit_event")) + '</td><td>' + escapeHtml(safeText(item.actor_role, "operations")) + '</td><td>' + escapeHtml(safeText(item.correlation_id, "n/a")) + '</td><td>' + escapeHtml(safeText(item.timestamp, "pending")) + '</td></tr>';
        }).join("");
        return [
          renderRoleIdentityPanel("compliance_officer", complianceSlice, "compliance mode"),
          renderPanelBlock("Compliance Command Center", "Credential expiration tracking, documentation verification backlog, and transport continuity protection.",
            '<div class="grid-4">' +
              renderMetric("Critical Expirations", String(complianceItems.filter(function (item) { return item.status === "critical"; }).length), "bad") + renderMetric("Expiring \u226430d", String(complianceItems.filter(function (item) { return item.status === "expiring"; }).length), "warn") +
              renderMetric("Documentation Verification Pending", String((((state.ops.compliance || {}).approval_queue || {}).pending_approvals) || complianceItems.length)) + renderMetric("Compliant Drivers", String((((state.ops.compliance || {}).compliance_overview || {}).compliance_rate) || 0) + "%", "good") +
              renderMetric("Open Violations", String(errors)) + renderMetric("Active Certifications", String(complianceItems.length)) +
              renderMetric("Avg Review Time", safeText((((state.ops.compliance || {}).approval_queue || {}).average_review_time), "2.4 hrs")) + renderMetric("Audit Events 24h", String(warnings + errors)) +
            '</div>', "compliance-kpis"),
          renderPanelBlock("Document Review Queue", "Credential and certification review — click Review to inspect each record.",
            '<div class="table-wrap"><table class="ops-table"><thead><tr><th>Doc ID</th><th>Driver</th><th>Document Type</th><th>Expires</th><th>Status</th><th>Action</th></tr></thead><tbody>' + tableRows + '</tbody></table></div>',
            "doc-queue"),
          renderPanelBlock("Onboarding Approval Queue", "Supervisor-linked onboarding approvals requiring compliance authority.",
            '<div class="table-wrap"><table class="ops-table"><thead><tr><th>Driver</th><th>Name</th><th>Compliance</th><th>Approval</th><th>Actions</th></tr></thead><tbody>' + onboardingRows + '</tbody></table></div>',
            'onboarding-queue'
          ),
          renderPanelBlock("Expiration Alerts", "Expiration accumulation and certification enforcement queue under active review.",
            '<div class="table-wrap"><table class="ops-table"><thead><tr><th>Target</th><th>Type</th><th>Status</th><th>Expires</th><th>Action</th></tr></thead><tbody>' + expirationRows + '</tbody></table></div>',
            'expiration-alerts'
          ),
          renderPanelBlock("Audit Evidence Feed", "Evidence feed for compliance reviews, approvals, and expirations.",
            '<div class="table-wrap"><table class="ops-table"><thead><tr><th>Event</th><th>Action</th><th>Actor</th><th>Correlation</th><th>Timestamp</th></tr></thead><tbody>' + evidenceRows + '</tbody></table></div>',
            'evidence-feed'
          ),
          renderComplianceOverviewPanel(phase17),
          renderExpirationQueuePanel(phase17),
          renderApprovalQueuePanel(phase17),
          renderComplianceTimelinePanel(phase17),
          renderEvidenceChainViewerPanel(phase17),
          renderRegulatoryExportBuilderPanel(phase17),
          renderPanelBlock("Regulatory Posture", "Compliance status across all credential classes.",
            '<div class="grid-3">' +
              renderMetric("HIPAA Posture", "compliant", "good") + renderMetric("DOT Compliance", "watch", "warn") +
              renderMetric("State Licensing", "3 gaps", "warn") + renderMetric("Background Checks", "2 expired", "bad") +
              renderMetric("Vehicle Inspections", "1 overdue", "warn") + renderMetric("Insurance Coverage", "active", "good") +
            '</div>' +
            renderNoticeList(["All review actions are continuity protected and audit-logged.", "Critical expirations trigger supervisor notification.", "Export bundles available from the Regulatory Export panel."]),
            "regulatory"),
          renderEnhancedOperationalTimeline("Compliance Audit Timeline", "Compliance events and review history.", complianceSlice.timeline, 12)
        ].join("");
      }

      function renderSupervisorDashboard(phase17) {
        var supervisorSlice = buildRoleHydrationSlice("supervisor", phase17);
        var events = phase17.events || [];
        var lifecycle = phase17.lifecycle || {};
        var driverStates = phase17.driverStates || {};
        var replayContinuity = safeObject(((state.ops.replay || {}).continuity));
        var queuePressure = safeObject((((state.ops.orchestration || {}).queue_health || {}).queue_pressure_dashboard));
        var continuityState = safeText(replayContinuity.continuity_state || replayContinuity.degraded_mode_state, "protected");
        var replaySafeState = asBoolean(replayContinuity.replay_safe, true) ? "verified" : "monitor";
        var hydrationState = hydrationIntegrityMeta(state.hydration.integrityState).label;
        var workspace = state.ops.workspaceActivation || {};
        var modules = safeObject(workspace.workspace_modules);
        var supervisorQueue = Array.isArray(modules.trip_failed_recovery) ? modules.trip_failed_recovery : (Array.isArray((((state.ops.compliance || {}).phase25 || {}).supervisor_review_queue)) ? (((state.ops.compliance || {}).phase25 || {}).supervisor_review_queue) : []);
        var escalationSignals = Array.isArray(modules.trip_escalation_indicators) ? modules.trip_escalation_indicators : [];
        var resolutionTimeline = Array.isArray(modules.trip_resolution_timeline) ? modules.trip_resolution_timeline : [];
        if (supervisorQueue.length === 0) {
          supervisorQueue = [];
        }
        if (escalationSignals.length === 0) {
          escalationSignals = [];
        }
        if (resolutionTimeline.length === 0) {
          resolutionTimeline = [];
        }
        var approvalItems = supervisorQueue.slice(0, 16).map(function (item, idx) {
          var urgency = safeText(item.urgency || item.priority || "medium", "medium").toLowerCase();
          var timeRaw = safeText(item.created_at || item.timestamp, "");
          var typeRaw = safeText(item.action_type || item.event_type || item.category, "supervised_request");
          var typeMap = {
            supervised_request: "Supervisor Review Request",
            escalation_override: "Escalation Override",
            manual_assignment_approval: "Manual Assignment Approval",
            rural_route_exception: "Rural Route Exception"
          };
          return {
            id: safeText(item.event_id || item.id, "APV-" + String(idx + 1)),
            type: safeText(typeMap[typeRaw], titleizeWords(typeRaw)),
            requestor: safeText(item.actor_role || item.requested_by || "operations"),
            urgency: urgency,
            timeRaw: timeRaw,
            time: formatOperationalTime(timeRaw)
          };
        });
        if (approvalItems.length === 0) {
          var fallbackTasks = Array.isArray((((state.ops.orchestration || {}).queue_snapshot || {}).tasks)) ? (((state.ops.orchestration || {}).queue_snapshot || {}).tasks) : [];
          approvalItems = fallbackTasks.slice(0, 12).map(function (task, idx) {
            var taskTimeRaw = safeText(task.created_at || task.updated_at, "");
            var taskTypeRaw = safeText(task.task_type || task.title, "queue_task");
            return {
              id: safeText(task.task_id || task.id, "TASK-" + String(idx + 1)),
              type: titleizeWords(taskTypeRaw),
              requestor: safeText(task.assigned_role || task.created_by_role, "operations"),
              urgency: safeText(task.priority || "medium", "medium").toLowerCase(),
              timeRaw: taskTimeRaw,
              time: formatOperationalTime(taskTimeRaw)
            };
          });
        }
        if (approvalItems.length === 0) {
          approvalItems = [];
        }
        approvalItems.sort(function (a, b) {
          return operationalTimeValue(b.timeRaw) - operationalTimeValue(a.timeRaw);
        });
        var approvalRows = approvalItems.map(function(item) {
          var uc = item.urgency === "high" ? "badge badge-bad" : item.urgency === "medium" ? "badge badge-warn" : "badge badge-soft";
          return '<tr><td>' + escapeHtml(item.id) + '</td><td>' + escapeHtml(item.type) + '</td><td>' + escapeHtml(item.requestor) + '</td><td><span class="' + uc + '">' + escapeHtml(item.urgency) + '</span></td><td class="muted">' + escapeHtml(item.time) + '</td>' +
            '<td><button class="btn-action btn-approve" onclick="window._amiHandleSupervisorApproval(\'' + escapeHtml(item.id) + '\',true)">Approve</button> <button class="btn-action btn-reject" onclick="window._amiHandleSupervisorApproval(\'' + escapeHtml(item.id) + '\',false)">Reject</button></td></tr>';
        }).join("");
        var recoveryRows = supervisorQueue.slice(0, 12).map(function (item, idx) {
          var tripId = safeText(item.trip_id || item.ride_id || item.id, "TRIP-" + String(idx + 1));
          var stateText = safeText(item.trip_state, "escalated");
          var recoveryStateMap = {
            escalated: "Escalated",
            pending_supervisor_review: "Awaiting Supervisor Review",
            supervisor_reviewed: "Supervisor Reviewed",
            assigned: "Assigned",
            resolved: "Completed"
          };
          return '<tr><td>' + escapeHtml(tripId) + '</td><td>' + escapeHtml(safeText(item.rider_name, "rider")) + '</td><td>' + escapeHtml(safeText(recoveryStateMap[stateText], titleizeWords(stateText))) + '</td><td>' + escapeHtml(String((item.transport_risk_indicators || []).length)) + '</td><td><button class="btn-action" onclick="window._amiHandleSupervisorRecovery(\'' + escapeHtml(tripId) + '\')">Recover</button> <button class="btn-action" onclick="window._amiHandleDispatchReassign(\'' + escapeHtml(tripId) + '\')">Reassign</button> <button class="btn-action" onclick="window._amiHandleSupervisorEmergency(\'' + escapeHtml(tripId) + '\')">Emergency</button></td></tr>';
        }).join("");
        if (!recoveryRows) {
          recoveryRows = '<tr><td colspan="5" class="muted">No failed-trip recovery cases in the current supervisor window.</td></tr>';
        }
        var orderedResolutionTimeline = resolutionTimeline.slice(0).sort(function (a, b) {
          return operationalTimeValue(safeText(b.timestamp, "")) - operationalTimeValue(safeText(a.timestamp, ""));
        });
        var resolutionRows = orderedResolutionTimeline.slice(0, 16).map(function (item, idx) {
          var stateText = safeText(item.trip_state, "pending");
          var stateLabelMap = {
            escalated: "Escalated",
            supervisor_reviewed: "Supervisor Reviewed",
            assigned: "Assigned",
            resolved: "Completed",
            pending_supervisor_review: "Awaiting Supervisor Review"
          };
          return '<tr><td>' + escapeHtml(String(idx + 1)) + '</td><td>' + escapeHtml(safeText(item.trip_id, "TRIP-" + String(idx + 1))) + '</td><td>' + escapeHtml(safeText(item.action || item.event_type, "workflow")) + '</td><td>' + escapeHtml(safeText(stateLabelMap[stateText], titleizeWords(stateText))) + '</td><td>' + escapeHtml(safeText(item.authority_source, "system")) + '</td><td>' + escapeHtml(formatOperationalTime(item.timestamp)) + '</td></tr>';
        }).join("");
        if (!resolutionRows) {
          resolutionRows = '<tr><td colspan="6" class="muted">No escalation resolution events recorded for this shift window.</td></tr>';
        }
        return [
          renderRoleIdentityPanel("supervisor", supervisorSlice, "supervisor mode"),
          renderPanelBlock("Supervisor Operations Center", "Shift oversight, escalation ownership, dispatch recovery visibility, and healthcare transport continuity.",
            '<div class="grid-4">' +
              renderMetric("Operational Review Queue", String(approvalItems.length), "warn") + renderMetric("Active Escalations", String(countEventsByLevel(events, "error"))) +
              renderMetric("Drivers On Shift", String(safeNumber(driverStates.available, 0) + safeNumber(driverStates.assigned, 0))) +
              renderMetric("Trips In Progress", safeText(lifecycle.IN_PROGRESS, "0")) +
              renderMetric("Continuity Escalations Under Review", String((((state.ops.orchestration || {}).sla || {}).alerts || []).length), "warn") + renderMetric("Avg Response Time", safeText((((state.ops.orchestration || {}).sla || {}).metrics || {}).average_response_time, "4.2 min")) +
              renderMetric("Team Utilization", "78%") + renderMetric("Supervisory Alerts", String(countEventsByLevel(events, "warning"))) +
              renderMetric("Operational Continuity", titleizeWords(continuityState)) + renderMetric("Continuity Protected", replaySafeState, replaySafeState === "verified" ? "good" : "warn") +
              renderMetric("Live Data", hydrationState, hydrationState === "HEALTHY" ? "good" : "warn") + renderMetric("Queue Pressure", titleizeWords(safeText(queuePressure.state, "stable"))) +
              renderMetric("Failed Recovery Queue", String(supervisorQueue.length), supervisorQueue.length > 0 ? "warn" : "good") +
              renderMetric("Escalation Indicators", String(escalationSignals.length), escalationSignals.length > 0 ? "warn" : "good") +
            '</div>', "supervisor-kpis"),
          renderPanelBlock("Operational Recovery Watch", "Supervisor visibility into continuity status, live-data verification, and escalation recovery posture.",
            '<div class="grid-3">' +
              renderMetric("Sequence Ordered", asBoolean(replayContinuity.sequence_monotonic, true) ? "yes" : "check", asBoolean(replayContinuity.sequence_monotonic, true) ? "good" : "warn") +
              renderMetric("Continuity Status", asBoolean(replayContinuity.replay_continuity, true) ? "healthy" : "monitor", asBoolean(replayContinuity.replay_continuity, true) ? "good" : "warn") +
              renderMetric("Recovery Attempts", String(safeNumber(replayContinuity.recovery_attempts, 0))) +
              renderMetric("Live Data Safe", asBoolean(replayContinuity.hydration_safe, true) ? "yes" : "monitor", asBoolean(replayContinuity.hydration_safe, true) ? "good" : "warn") +
              renderMetric("Supervisor Queue", String((((state.ops.orchestration || {}).queue_snapshot || {}).tasks || []).length)) +
              renderMetric("Escalation Awaiting Supervisor Clearance", String(((((state.ops.orchestration || {}).sla || {}).alerts) || []).length), ((((state.ops.orchestration || {}).sla || {}).alerts || []).length) > 0 ? "warn" : "good") +
            '</div>' +
            '<p class="muted">Continuity safeguards remain enforced during delay windows; supervisor controls stay authoritative and service interruption prevention remains active.</p>',
            'supervisor-continuity-watch'
          ),
          renderPanelBlock("Operational Review Queue", "Escalation and override requests awaiting supervisor clearance.",
            '<div class="table-wrap"><table class="ops-table"><thead><tr><th>ID</th><th>Type</th><th>Requestor</th><th>Urgency</th><th>Event Time</th><th>Action</th></tr></thead><tbody id="supervisor-approval-tbody">' + approvalRows + '</tbody></table></div>',
            "approval-queue"),
          renderPanelBlock("Failed Trip Recovery Queue", "Live failed-trip recovery, reassignment review, and emergency intervention workspace.",
            '<div class="table-wrap"><table class="ops-table"><thead><tr><th>Trip</th><th>Rider</th><th>State</th><th>Risk</th><th>Actions</th></tr></thead><tbody>' + recoveryRows + '</tbody></table></div>',
            'failed-trip-recovery'
          ),
          renderPanelBlock("Escalation Resolution Timeline", "Timeline of recovery, supervisor clearance, and dispatch resolution activity.",
            '<div class="table-wrap"><table class="ops-table"><thead><tr><th>Order</th><th>Trip</th><th>Action</th><th>State</th><th>Authority</th><th>Event Time</th></tr></thead><tbody>' + resolutionRows + '</tbody></table></div>',
            'resolution-timeline'
          ),
          renderSupervisorReviewQueuePanel(phase17),
          renderEscalationQueuePanel(phase17),
          renderSupervisorTaskInboxPanel(phase17),
          renderHandoffTrackerPanel(phase17),
          renderQueueHealthDashboardPanel(phase17),
          renderPanelBlock("Team Performance Monitor", "Dispatcher and driver performance metrics for the current shift.",
            '<div class="grid-3">' +
              renderMetric("Dispatchers Online", "3") + renderMetric("Avg Dispatch Time", "2.1 min") +
              renderMetric("Driver Utilization", "82%") + renderMetric("On-Time Pickups", "91%", "good") +
              renderMetric("Patient Satisfaction", "4.7 / 5", "good") + renderMetric("Escalation Rate", "3.2%") +
            '</div>', "team-performance"),
          renderEnhancedOperationalTimeline("Supervisor Activity Feed", "Supervisory events, approvals, and escalations.", supervisorSlice.timeline, 10)
        ].join("");
      }

      function renderDriverSupportDashboard(phase17) {
        var supportSlice = buildRoleHydrationSlice("driver_support", phase17);
        var events = phase17.events || [];
        var workspace = state.ops.workspaceActivation || {};
        var modules = safeObject(workspace.workspace_modules);
        var missingDocuments = Array.isArray(modules.missing_document_support) ? modules.missing_document_support : [];
        var activationIssues = Array.isArray(modules.app_activation_support) ? modules.app_activation_support : [];
        var payoutIssues = Array.isArray(modules.payout_support_issues) ? modules.payout_support_issues : [];
        var readinessRows = Array.isArray(modules.driver_readiness_training) ? modules.driver_readiness_training : [];
        var profiles = Array.isArray(((state.ops.compliance || {}).profiles)) ? state.ops.compliance.profiles : [];
        var onboardingItems = profiles.slice(0, 20).map(function (profile, idx) {
          var profileStatus = safeText(profile.approval_status || profile.compliance_status || "pending", "pending").toLowerCase();
          var status = profileStatus === "approved" ? "active" : profileStatus === "under_review" ? "review" : "pending";
          var progress = status === "active" ? 90 : status === "review" ? 70 : 40;
          return {
            id: safeText(profile.profile_id || profile.driver_id, "DRV-" + String(idx + 1)),
            name: safeText(profile.driver_name || profile.full_name || profile.name, "driver"),
            stage: safeText(profile.last_review_action || profile.compliance_status, "onboarding"),
            progress: progress,
            status: status
          };
        });
        var onboardingRows = onboardingItems.map(function(item) {
          var sc = item.status === "review" ? "badge badge-warn" : item.status === "active" ? "badge badge-good" : "badge badge-soft";
          var bar = '<div class="progress-bar-wrap"><div class="progress-bar-fill" style="width:' + item.progress + '%"></div><span class="progress-label">' + item.progress + '%</span></div>';
          return '<tr><td>' + escapeHtml(item.id) + '</td><td>' + escapeHtml(item.name) + '</td><td>' + escapeHtml(item.stage) + '</td><td>' + bar + '</td><td><span class="' + sc + '">' + escapeHtml(item.status) + '</span></td><td><button class="btn-action" onclick="window._amiHandleDriverSupport(\'' + escapeHtml(item.id) + '\')">View</button></td></tr>';
        }).join("");
        var notificationItems = Array.isArray((((state.ops.orchestration || {}).notifications || {}).notifications)) ? (((state.ops.orchestration || {}).notifications || {}).notifications) : [];
        var ticketItems = notificationItems.slice(0, 20).map(function (ticket, idx) {
          return {
            id: safeText(ticket.notification_id || ticket.id, "TKT-" + String(idx + 1)),
            driver: safeText(ticket.assignee_user_id || ticket.target_user_id || ticket.actor_id, "driver"),
            issue: safeText(ticket.title || ticket.message, "support ticket"),
            priority: safeText(ticket.priority || "medium", "medium").toLowerCase()
          };
        });
        var ticketRows = ticketItems.map(function(t) {
          var pc = t.priority === "high" ? "badge badge-bad" : t.priority === "medium" ? "badge badge-warn" : "badge badge-soft";
          return '<tr><td>' + escapeHtml(t.id) + '</td><td>' + escapeHtml(t.driver) + '</td><td>' + escapeHtml(t.issue) + '</td><td><span class="' + pc + '">' + escapeHtml(t.priority) + '</span></td><td><button class="btn-action" onclick="window._amiHandleTicket(\'' + escapeHtml(t.id) + '\')">Open</button></td></tr>';
        }).join("");
        return [
          renderRoleIdentityPanel("driver_support", supportSlice, "driver support mode"),
          renderPanelBlock("Driver Support & Onboarding Hub", "Onboarding pipeline, support queue, training status, and communication center.",
            '<div class="grid-4">' +
              renderMetric("Drivers Onboarding", String(onboardingItems.length)) + renderMetric("Avg Onboarding Days", "4.8") +
              renderMetric("Open Support Tickets", String(ticketItems.length), "warn") + renderMetric("Resolved Today", String(Math.max(0, safeNumber((phase17.lifecycle || {}).COMPLETED, 0))), "good") +
              renderMetric("Training Completions", String(readinessRows.filter(function (row) { return String(row.compliance_status || "").toLowerCase() === "approved"; }).length)) + renderMetric("Doc Reviews Pending", String(missingDocuments.length)) +
              renderMetric("Driver Satisfaction", "4.6 / 5", "good") + renderMetric("Active Drivers", String(safeNumber((phase17.driverStates || {}).available, 0))) +
            '</div>', "support-kpis"),
          renderPanelBlock("Onboarding Pipeline", "Current driver onboarding status — track each driver through the pipeline.",
            '<div class="table-wrap"><table class="ops-table"><thead><tr><th>ID</th><th>Name</th><th>Stage</th><th>Progress</th><th>Status</th><th>Action</th></tr></thead><tbody>' + onboardingRows + '</tbody></table></div>',
            "onboarding-pipeline"),
          renderPanelBlock("Support Ticket Queue", "Open driver support requests — investigate and resolve.",
            '<div class="table-wrap"><table class="ops-table"><thead><tr><th>Ticket</th><th>Driver</th><th>Issue</th><th>Priority</th><th>Action</th></tr></thead><tbody id="support-ticket-tbody">' + ticketRows + '</tbody></table></div>',
            "tickets"),
          renderPanelBlock("Driver Document Review", "Missing and expiring documents requiring support intervention.",
            '<div class="table-wrap"><table class="ops-table"><thead><tr><th>Document</th><th>Driver</th><th>Type</th><th>Status</th><th>Action</th></tr></thead><tbody>' + missingDocuments.slice(0, 14).map(function (doc, idx) {
              var statusText = safeText(doc.status, "missing").toLowerCase();
              var badge = statusText === "expired" || statusText === "rejected" ? "badge badge-bad" : "badge badge-warn";
              return '<tr><td>' + escapeHtml(safeText(doc.document_id || doc.id, "DOC-" + String(idx + 1))) + '</td><td>' + escapeHtml(safeText(doc.driver_name || doc.driver_id, "driver")) + '</td><td>' + escapeHtml(safeText(doc.document_type || doc.type, "document")) + '</td><td><span class="' + badge + '">' + escapeHtml(statusText) + '</span></td><td><button class="btn-action" onclick="window._amiHandleDriverSupport(\'' + escapeHtml(safeText(doc.driver_id || doc.driver_name, "")) + '\')">Assist</button></td></tr>';
            }).join("") + '</tbody></table></div>',
            "document-review"),
          renderPanelBlock("App Activation Assistance", "Activation/login issues for field drivers requiring support routing.",
            '<div class="table-wrap"><table class="ops-table"><thead><tr><th>Issue</th><th>Driver</th><th>Priority</th><th>Timestamp</th><th>Action</th></tr></thead><tbody>' + activationIssues.slice(0, 14).map(function (item, idx) {
              var priority = safeText(item.priority, "medium").toLowerCase();
              var badge = priority === "high" || priority === "critical" ? "badge badge-bad" : "badge badge-warn";
              return '<tr><td>' + escapeHtml(safeText(item.title || item.message, "activation issue")) + '</td><td>' + escapeHtml(safeText(item.assignee_user_id || item.target_user_id || item.actor_id, "driver")) + '</td><td><span class="' + badge + '">' + escapeHtml(priority) + '</span></td><td class="muted">' + escapeHtml(safeText(item.created_at || item.updated_at, "pending")) + '</td><td><button class="btn-action" onclick="window._amiHandleTicket(\'' + escapeHtml(safeText(item.notification_id || item.id, "")) + '\')">Open Ticket</button></td></tr>';
            }).join("") + '</tbody></table></div>',
            "activation-assistance"),
          renderPanelBlock("Payout Support Issues", "Driver payout and reimbursement support queue.",
            '<div class="table-wrap"><table class="ops-table"><thead><tr><th>Issue</th><th>Driver</th><th>Priority</th><th>Action</th></tr></thead><tbody>' + payoutIssues.slice(0, 14).map(function (item, idx) {
              var priority = safeText(item.priority, "medium").toLowerCase();
              var badge = priority === "high" || priority === "critical" ? "badge badge-bad" : "badge badge-soft";
              return '<tr><td>' + escapeHtml(safeText(item.title || item.message, "payout issue")) + '</td><td>' + escapeHtml(safeText(item.assignee_user_id || item.target_user_id || item.actor_id, "driver")) + '</td><td><span class="' + badge + '">' + escapeHtml(priority) + '</span></td><td><button class="btn-action" onclick="window._amiHandleTicket(\'' + escapeHtml(safeText(item.notification_id || item.id, "")) + '\')">Resolve</button></td></tr>';
            }).join("") + '</tbody></table></div>',
            "payout-support"),
          renderPanelBlock("Training & Certification Tracker", "Module completion rates and certification milestones.",
            '<div class="grid-3">' +
              renderMetric("Module 1: Orientation", "100%", "good") + renderMetric("Module 2: Safety", "94%", "good") +
              renderMetric("Module 3: NEMT Protocols", "78%", "warn") + renderMetric("Module 4: App Training", "82%") +
              renderMetric("Module 5: Compliance", "61%", "warn") + renderMetric("Certified Drivers", "89%") +
            '</div>' +
            renderSimpleBars([
              { label: "Orientation", value: 100, note: "%" }, { label: "Safety", value: 94, note: "%" },
              { label: "NEMT Protocols", value: 78, note: "%" }, { label: "Compliance Module", value: 61, note: "%" }
            ]), "training"),
          renderPanelBlock("Driver Readiness and Training Status", "Role-scoped readiness records derived from compliance/training posture.",
            '<div class="table-wrap"><table class="ops-table"><thead><tr><th>Driver</th><th>Compliance</th><th>Approval</th><th>Readiness</th></tr></thead><tbody>' + readinessRows.slice(0, 16).map(function (row, idx) {
              var complianceStatus = safeText(row.compliance_status, "pending").toLowerCase();
              var approvalStatus = safeText(row.approval_status, "pending").toLowerCase();
              var readiness = (complianceStatus === "approved" && approvalStatus === "approved") ? "ready" : "in_review";
              var badge = readiness === "ready" ? "badge badge-good" : "badge badge-warn";
              return '<tr><td>' + escapeHtml(safeText(row.driver_name || row.full_name || row.driver_id, "driver-" + String(idx + 1))) + '</td><td>' + escapeHtml(complianceStatus) + '</td><td>' + escapeHtml(approvalStatus) + '</td><td><span class="' + badge + '">' + escapeHtml(readiness) + '</span></td></tr>';
            }).join("") + '</tbody></table></div>',
            "readiness"),
          renderEnhancedOperationalTimeline("Support Activity Feed", "Driver support and onboarding events.", supportSlice.timeline, 10)
        ].join("");
      }

      function renderMedicalCoordinatorDashboard(phase17) {
        var medicalSlice = buildRoleHydrationSlice("medical_coordinator", phase17);
        var workspace = state.ops.workspaceActivation || {};
        var modules = safeObject(workspace.workspace_modules);
        var coordinationQueue = Array.isArray(modules.patient_ride_coordination_queue) ? modules.patient_ride_coordination_queue : [];
        var recurringSchedule = Array.isArray(modules.recurring_medical_schedule) ? modules.recurring_medical_schedule : [];
        var appointmentRisk = Array.isArray(modules.appointment_pickup_dropoff_risk) ? modules.appointment_pickup_dropoff_risk : [];
        var providerCoordination = Array.isArray(modules.provider_facility_coordination) ? modules.provider_facility_coordination : [];
        var patientEscalations = Array.isArray(modules.patient_support_escalation) ? modules.patient_support_escalation : [];
        var scheduleRows = coordinationQueue.slice(0, 18).map(function(item, idx) {
          var priority = safeText(item.priority, "routine").toLowerCase();
          var pc = priority === "urgent" || priority === "critical" ? "badge badge-bad" : priority === "high" ? "badge badge-warn" : "badge badge-soft";
          var status = safeText(item.task_state || item.state, "pending").toLowerCase();
          var sc = status === "assigned" || status === "in_progress" ? "badge badge-good" : status === "escalated" ? "badge badge-bad" : "badge badge-warn";
          var tripId = safeText(item.task_id || item.id, "NEMT-" + String(idx + 1));
          var needsAssign = status === "new" || status === "pending";
          var actionBtn = needsAssign
            ? '<button class="btn-action btn-assign" onclick="window._amiHandleNEMTAssign(\'' + escapeHtml(tripId) + '\')">Assign Driver</button>'
            : '<button class="btn-action" onclick="window._amiHandleNEMTView(\'' + escapeHtml(tripId) + '\')">Track</button>';
          return '<tr><td>' + escapeHtml(tripId) + '</td><td>' + escapeHtml(safeText(item.patient_name || item.title, "patient")) + '</td><td>' + escapeHtml(safeText(item.pickup_time || item.start_time || item.created_at, "pending")) + '</td><td>' + escapeHtml(safeText(item.destination || item.facility || item.title, "facility")) + '</td><td>' + escapeHtml(safeText(item.assignee_user_id || item.driver_id, needsAssign ? "Unassigned" : "Assigned")) + '</td><td><span class="' + sc + '">' + escapeHtml(status) + '</span></td><td><span class="' + pc + '">' + escapeHtml(priority) + '</span></td><td>' + actionBtn + '</td></tr>';
        }).join("");
        return [
          renderRoleIdentityPanel("medical_coordinator", medicalSlice, "medical coordination mode"),
          renderPanelBlock("Patient Transport Coordination Center", "Trip coordination queue, recurring medical rides, and operational patient movement controls.",
            '<div class="grid-4">' +
              renderMetric("Transports Today", String(coordinationQueue.length)) + renderMetric("In Transit Now", String(coordinationQueue.filter(function (item) { return String(item.task_state || item.state || "").toLowerCase() === "in_progress"; }).length), "good") +
              renderMetric("Urgent Transports", String(coordinationQueue.filter(function (item) { var p = String(item.priority || "").toLowerCase(); return p === "urgent" || p === "critical"; }).length), "warn") + renderMetric("Unassigned Trips", String(coordinationQueue.filter(function (item) { var s = String(item.task_state || item.state || "").toLowerCase(); return s === "new" || s === "pending"; }).length), "bad") +
              renderMetric("Clinical Providers", String(providerCoordination.length)) + renderMetric("Facilities Served", String(providerCoordination.length)) +
              renderMetric("Patient Escalations", String(patientEscalations.length)) + renderMetric("Appointment Risk Alerts", String(appointmentRisk.length), appointmentRisk.length > 0 ? "warn" : "good") +
            '</div>', "nemt-kpis"),
          renderPanelBlock("Trip Coordination Queue", "Live patient ride coordination queue with supervised assignment and tracking.",
            '<div class="table-wrap"><table class="ops-table"><thead><tr><th>Trip ID</th><th>Patient</th><th>Pickup</th><th>Destination</th><th>Driver</th><th>Status</th><th>Priority</th><th>Action</th></tr></thead><tbody id="nemt-schedule-tbody">' + scheduleRows + '</tbody></table></div>',
            "transport-schedule"),
          renderPanelBlock("Recurring Medical Ride Schedule", "Recurring dialysis/appointment-linked medical rides requiring coordination oversight.",
            '<div class="table-wrap"><table class="ops-table"><thead><tr><th>Ride</th><th>Title</th><th>Priority</th><th>Status</th><th>Action</th></tr></thead><tbody>' + recurringSchedule.slice(0, 14).map(function (item, idx) {
              var priority = safeText(item.priority, "medium").toLowerCase();
              var badge = priority === "urgent" || priority === "critical" ? "badge badge-bad" : "badge badge-soft";
              var rideId = safeText(item.task_id || item.id, "REC-" + String(idx + 1));
              return '<tr><td>' + escapeHtml(rideId) + '</td><td>' + escapeHtml(safeText(item.title || item.task_type, "recurring medical ride")) + '</td><td><span class="' + badge + '">' + escapeHtml(priority) + '</span></td><td>' + escapeHtml(safeText(item.task_state || item.state, "pending")) + '</td><td><button class="btn-action" onclick="window._amiHandleNEMTView(\'' + escapeHtml(rideId) + '\')">Open</button></td></tr>';
            }).join("") + '</tbody></table></div>',
            "recurring-rides"),
          renderPanelBlock("Appointment Pickup/Dropoff Risk", "SLA and timing risk indicators for appointment-critical patient transport.",
            '<div class="table-wrap"><table class="ops-table"><thead><tr><th>Task</th><th>Metric</th><th>Observed</th><th>Recommendation</th></tr></thead><tbody>' + appointmentRisk.slice(0, 14).map(function (risk, idx) {
              return '<tr><td>' + escapeHtml(safeText(risk.task_id, "RISK-" + String(idx + 1))) + '</td><td>' + escapeHtml(safeText(risk.metric, "pickup_dropoff_latency")) + '</td><td>' + escapeHtml(String(safeNumber(risk.observed_seconds, 0))) + 's</td><td>' + escapeHtml(safeText(risk.recommendation, "escalate for supervised review")) + '</td></tr>';
            }).join("") + '</tbody></table></div>',
            "appointment-risk"),
          renderPanelBlock("Patient/Provider Coordination", "Facility and provider coordination items tied to medical transport operations.",
            '<div class="table-wrap"><table class="ops-table"><thead><tr><th>Task</th><th>Title</th><th>State</th><th>Role</th><th>Action</th></tr></thead><tbody>' + providerCoordination.slice(0, 14).map(function (item, idx) {
              var taskId = safeText(item.task_id || item.id, "COORD-" + String(idx + 1));
              return '<tr><td>' + escapeHtml(taskId) + '</td><td>' + escapeHtml(safeText(item.title || item.task_type, "provider coordination")) + '</td><td>' + escapeHtml(safeText(item.task_state || item.state, "pending")) + '</td><td>' + escapeHtml(safeText(item.assigned_role, "provider")) + '</td><td><button class="btn-action" onclick="window._amiHandleMedicalFacilityCoordination(\'' + escapeHtml(taskId) + '\')">Coordinate</button></td></tr>';
            }).join("") + '</tbody></table></div>',
            "provider-coordination"),
          renderPanelBlock("Patient Support Escalation Panel", "Escalation tools for patient support disruptions and sensitive ride events.",
            '<div class="table-wrap"><table class="ops-table"><thead><tr><th>Escalation</th><th>Priority</th><th>Timestamp</th><th>Action</th></tr></thead><tbody>' + patientEscalations.slice(0, 14).map(function (item, idx) {
              var priority = safeText(item.priority, "medium").toLowerCase();
              var badge = priority === "high" || priority === "critical" ? "badge badge-bad" : "badge badge-warn";
              var escalationId = safeText(item.notification_id || item.id, "ESC-" + String(idx + 1));
              return '<tr><td>' + escapeHtml(safeText(item.title || item.message, "patient support escalation")) + '</td><td><span class="' + badge + '">' + escapeHtml(priority) + '</span></td><td class="muted">' + escapeHtml(safeText(item.created_at || item.updated_at, "pending")) + '</td><td><button class="btn-action" onclick="window._amiHandlePatientEscalation(\'' + escapeHtml(escalationId) + '\')">Escalate</button></td></tr>';
            }).join("") + '</tbody></table></div>',
            "patient-escalation"),
          renderEnhancedOperationalTimeline("Medical Transport Timeline", "Patient transport events and coordination log.", medicalSlice.timeline, 10)
        ].join("");
      }

      function renderLiveDispatchBoard() {
        var phase17 = getPhase17Context();
        var events = phase17.events || [];
        var workspace = state.ops.workspaceActivation || {};
        var modules = safeObject(workspace.workspace_modules);
        var liveWorkflow = safeObject(state.liveWorkflow);
        var runtime = dispatchSnapshot() || { trips: [], drivers: [], selectedDriverId: "" };
        var tripEntities = Array.isArray(modules.trip_operational_entities) ? modules.trip_operational_entities : [];
        var queueModule = Array.isArray(modules.trip_unassigned_queue) ? modules.trip_unassigned_queue : [];
        var activeRouteModule = Array.isArray(modules.trip_active_routes) ? modules.trip_active_routes : [];
        var driverAvailabilityModule = Array.isArray(modules.trip_driver_availability) ? modules.trip_driver_availability : [];
        var delayedRideModule = Array.isArray(modules.trip_delayed_rides) ? modules.trip_delayed_rides : [];
        var escalationModule = Array.isArray(modules.trip_escalation_indicators) ? modules.trip_escalation_indicators : [];
        var reassignmentModule = Array.isArray(modules.trip_reassignment_queue) ? modules.trip_reassignment_queue : [];
        var noDriverRecoveryModule = Array.isArray(modules.trip_no_driver_recovery) ? modules.trip_no_driver_recovery : [];
        var resolutionTimelineModule = Array.isArray(modules.trip_resolution_timeline) ? modules.trip_resolution_timeline : [];
        var liveQueue = Array.isArray(liveWorkflow.dispatchQueue) ? liveWorkflow.dispatchQueue : [];
        var liveAssignments = Array.isArray(liveWorkflow.activeAssignments) ? liveWorkflow.activeAssignments : [];
        var liveDrivers = Array.isArray(liveWorkflow.drivers) ? liveWorkflow.drivers : [];
        var liveActivityFeed = Array.isArray(liveWorkflow.activityFeed) ? liveWorkflow.activityFeed : [];

        function sanitizeDispatchState(raw) {
          var stateText = safeText(raw, "requested").toLowerCase();
          if (stateText.indexOf("ridestatus.") === 0) {
            stateText = stateText.slice("ridestatus.".length);
          }
          if (stateText.indexOf("driverstatus.") === 0) {
            stateText = stateText.slice("driverstatus.".length);
          }
          return stateText;
        }

        function normalizeTrip(item, fallbackState) {
          var normalized = safeObject(item);
          var tripId = safeText(normalized.trip_id || normalized.ride_id || normalized.id, "");
          var stateValue = sanitizeDispatchState(
            normalized.assignment_state
            || normalized.trip_state || normalized.state || normalized.workflow_state
            || normalized.ride_status || fallbackState || "requested"
          );
          return {
            id: tripId,
            state: stateValue,
            riderName: safeText(normalized.patient_name || normalized.rider_name || normalized.passenger_name || normalized.rider || normalized.rider_id, "Rider"),
            pickup: safeText(normalized.pickup || normalized.pickup_address || normalized.pickup_location || normalized.pickup_name, "Pickup"),
            dropoff: safeText(normalized.dropoff || normalized.dropoff_address || normalized.dropoff_location || normalized.destination, "Dropoff"),
            priority: safeText(normalized.priority, "standard").toLowerCase(),
            routeStatus: safeText(normalized.route_status || normalized.scheduling_status || normalized.status, "pending").toLowerCase(),
            requestedAt: safeText(normalized.requested_at || normalized.created_at || normalized.updated_at, ""),
            slaTargetMin: safeNumber(normalized.sla_target_minutes || normalized.sla_minutes || normalized.sla_target_min, 20),
            assignedDriverName: safeText(normalized.assigned_driver_name || normalized.recommended_driver_name || normalized.assigned_driver_id || normalized.driver_name || normalized.driver_id, "unassigned"),
            etaMin: safeNumber(normalized.eta_minutes || normalized.estimated_arrival_minutes || normalized.eta_min, 0),
            completedAt: safeText(normalized.completed_at || normalized.closed_at || "", ""),
            appointmentWindow: safeText(normalized.appointment_window || normalized.scheduling_summary || normalized.scheduled_window || normalized.window, "window pending"),
            coordinationNote: safeText(normalized.coordination_note || normalized.dispatcher_message || normalized.dispatcher_note || normalized.scheduling_summary || normalized.notes, "coordination pending"),
            tripLeg: safeText(normalized.trip_leg, ""),
            schedulingSummary: safeText(normalized.scheduling_summary, "")
          };
        }

        function buildDispatchTripsMerged() {
          var mergedSources = []
            .concat(liveQueue)
            .concat(liveAssignments)
            .concat(filterActiveOperationalRides(Array.isArray(liveWorkflow.rides) ? liveWorkflow.rides : []).map(function (ride) {
              var lifecycle = normalizeRideStatusToken(ride.lifecycle_state || ride.status);
              var assignmentState = ride.accepted_at
                ? "accepted"
                : (ride.driver_id ? (lifecycle === "assigned" ? "assigned" : "offered") : "pending_assignment");
              return {
                ride_id: ride.id,
                assignment_state: assignmentState,
                ride_status: lifecycle,
                passenger_name: ride.passenger_name,
                pickup_address: ride.pickup_address,
                dropoff_address: ride.dropoff_address,
                driver_id: ride.driver_id,
                driver_name: ride.driver_name,
                assigned_driver_name: ride.driver_name || ride.driver_id,
                requested_at: ride.requested_at || ride.created_at,
                created_at: ride.created_at,
                updated_at: ride.updated_at,
                scheduling_summary: ride.scheduling_summary,
                trip_leg: ride.trip_leg,
                appointment_window: ride.scheduling_summary
              };
            }))
            .concat(activeRouteModule)
            .concat(queueModule)
            .concat(tripEntities.filter(function (item) {
              return !item.driver_id && ["requested", "pending_review", "scheduled", "assigned", "pending", "queued"].indexOf(safeText(item.trip_state || item.state, "").toLowerCase()) >= 0;
            }));
          var seenTripIds = {};
          var deduped = [];
          mergedSources.forEach(function (item) {
            var trip = normalizeTrip(item, "requested");
            var tripId = safeText(trip.id, "");
            if (!tripId || seenTripIds[tripId]) {
              return;
            }
            if (["completed", "cancelled", "failed", "dropoff_complete"].indexOf(safeText(trip.state, "")) >= 0) {
              return;
            }
            if (isProofOrDemoTripMeta(trip.riderName, trip.pickup, trip.dropoff, trip.coordinationNote)) {
              return;
            }
            seenTripIds[tripId] = true;
            deduped.push(trip);
          });
          deduped.sort(function (a, b) {
            return operationalTimeValue(safeText(b.requestedAt, "")) - operationalTimeValue(safeText(a.requestedAt, ""));
          });
          return deduped;
        }

        var workflowTrips = buildDispatchTripsMerged();

        var trips = workflowTrips.length > 0
          ? workflowTrips
          : (Array.isArray(runtime.trips) ? runtime.trips : []).map(function (item) { return normalizeTrip(item, "requested"); });

        var drivers = driverAvailabilityModule.length > 0
          ? driverAvailabilityModule.map(function (driver) {
              return {
                id: safeText(driver.driver_id || driver.id, ""),
                name: safeText(driver.driver_name || driver.name, "Driver"),
                vehicle: safeText(driver.vehicle || driver.vehicle_type || "Vehicle", "Vehicle"),
                status: safeText(driver.status || driver.availability || "available", "available").toLowerCase(),
                etaMin: safeNumber(driver.next_eta_minutes || driver.eta_minutes || 0, 0)
              };
            })
          : (liveDrivers.length > 0 ? liveDrivers.map(function (driver) {
              return {
                id: safeText(driver.id || driver.driver_id, ""),
                name: safeText(driver.name || driver.driver_name, "Driver"),
                vehicle: safeText(driver.vehicle_type || driver.vehicle || "Vehicle", "Vehicle"),
                status: safeText(driver.status || driver.availability || "available", "available").toLowerCase(),
                etaMin: safeNumber(driver.next_eta_minutes || driver.eta_minutes || 0, 0)
              };
            })
          : (Array.isArray(runtime.drivers) ? runtime.drivers : []));
        var selectedDriverId = safeText(runtime.selectedDriverId, "");
        var queueTrips = trips.filter(function (trip) {
          var stateText = safeText(trip.state, "");
          if (["completed", "cancelled", "failed", "dropoff_complete"].indexOf(stateText) >= 0) {
            return false;
          }
          if (["accepted", "driver_en_route", "arrived", "rider_onboard", "in_progress", "in_transit", "arrived_destination", "pickup_complete", "en_route_pickup"].indexOf(stateText) >= 0) {
            return false;
          }
          return ["requested", "scheduled", "delayed", "pending", "new", "queued", "pending_review", "awaiting_approval", "pending_assignment", "offered", "searching", "dispatchable", "reassignment_pending"].indexOf(stateText) >= 0;
        });
        var activeTrips = trips.filter(function (trip) {
          var stateText = safeText(trip.state, "");
          if (["completed", "cancelled", "failed", "dropoff_complete"].indexOf(stateText) >= 0) {
            return false;
          }
          var hasDriver = safeText(trip.assignedDriverName, "").toLowerCase() !== "unassigned"
            && !!safeText(trip.assignedDriverName, "");
          if (["assigned", "accepted", "offered"].indexOf(stateText) >= 0 && hasDriver) {
            return true;
          }
          if (stateText === "reassignment_pending" && hasDriver) {
            return true;
          }
          return ["accepted", "arrived", "onboard", "in_transit", "pickup_enroute", "dropoff_enroute", "driver_en_route", "rider_onboard", "in_progress", "en_route_pickup", "pickup_complete"].indexOf(stateText) >= 0;
        });
        // Completed rides must never remain in AI/dispatch reassignment modules.
        reassignmentModule = reassignmentModule.filter(function (item) {
          var stateText = sanitizeDispatchState(item.assignment_status || item.ride_status || item.state);
          var rideStatus = sanitizeDispatchState(item.ride_status || item.lifecycle_state || "");
          return ["completed", "cancelled", "failed", "dropoff_complete"].indexOf(stateText) < 0
            && ["completed", "cancelled", "failed"].indexOf(rideStatus) < 0;
        });
        noDriverRecoveryModule = noDriverRecoveryModule.filter(function (item) {
          var rideStatus = sanitizeDispatchState(item.ride_status || item.lifecycle_state || item.state || "");
          return ["completed", "cancelled", "failed"].indexOf(rideStatus) < 0;
        });
        queueTrips.sort(function (a, b) {
          var priorityOrder = { urgent: 0, high: 1, medium: 2, standard: 3, low: 4 };
          var pA = priorityOrder[safeText(a.priority, "standard")] || 5;
          var pB = priorityOrder[safeText(b.priority, "standard")] || 5;
          if (pA !== pB) return pA - pB;
          return operationalTimeValue(safeText(b.requestedAt, "")) - operationalTimeValue(safeText(a.requestedAt, ""));
        });
        activeTrips.sort(function (a, b) {
          return safeNumber(a.etaMin, 0) - safeNumber(b.etaMin, 0);
        });
        var availableDrivers = drivers.filter(function (driver) {
          return ["available", "assigned", "busy"].indexOf(safeText(driver.status, "")) >= 0;
        });

        function tripWaitText(trip) {
          var requestedAt = Date.parse(safeText(trip.requestedAt, ""));
          if (!Number.isFinite(requestedAt)) return "0 min";
          return String(Math.max(0, Math.floor((Date.now() - requestedAt) / 60000))) + " min";
        }

        function tripSlaText(trip) {
          var requestedAt = Date.parse(safeText(trip.requestedAt, ""));
          var target = safeNumber(trip.slaTargetMin, 20);
          if (!Number.isFinite(requestedAt)) return "0 / " + String(target) + " min";
          var elapsed = Math.max(0, Math.floor((Date.now() - requestedAt) / 60000));
          return String(elapsed) + " / " + String(target) + " min";
        }

        function lifecycleBucket(stateValue) {
          var stateText = safeText(stateValue, "").toLowerCase();
          if (["requested", "scheduled", "pending", "new", "queued", "pending_review"].indexOf(stateText) >= 0) return "pending";
          if (["assigned", "accepted"].indexOf(stateText) >= 0) return "assigned";
          if (["arrived", "onboard", "in_transit", "pickup_enroute", "dropoff_enroute", "in_progress", "driver_en_route", "rider_onboard"].indexOf(stateText) >= 0) return "in_transit";
          if (["completed", "closed", "resolved"].indexOf(stateText) >= 0) return "completed";
          return "pending";
        }

        function lifecycleBadge(stateValue) {
          var bucket = lifecycleBucket(stateValue);
          var stateText = safeText(stateValue, "").toLowerCase();
          var labelMap = {
            requested: "Requested",
            scheduled: "Requested",
            pending: "Requested",
            assigned: "Assigned",
            accepted: "Assigned",
            driver_en_route: "Driver En Route",
            arrived: "Arrived at Pickup",
            patient_onboard: "Patient Onboard",
            onboard: "Patient Onboard",
            in_transit: "In Transit",
            in_progress: "In Transit",
            arrived_at_facility: "Arrived Facility",
            completed: "Completed",
            resolved: "Completed",
            escalated: "Escalated",
            supervisor_reviewed: "Supervisor Reviewed"
          };
          var label = labelMap[stateText] || (bucket === "in_transit" ? "In Transit" : titleizeWords(bucket));
          return '<span class="badge lifecycle lifecycle-' + escapeHtml(bucket) + '">' + escapeHtml(label) + '</span>';
        }

        var assignedWorkflowTrips = trips.filter(function (trip) {
          return lifecycleBucket(trip.state) === "assigned";
        });
        var inTransitWorkflowTrips = trips.filter(function (trip) {
          return lifecycleBucket(trip.state) === "in_transit";
        });
        var completedWorkflowTrips = trips.filter(function (trip) {
          return lifecycleBucket(trip.state) === "completed";
        });
        var driverEnRouteTrips = trips.filter(function (trip) {
          return safeText(trip.state, "").toLowerCase() === "driver_en_route";
        });
        var patientOnboardTrips = trips.filter(function (trip) {
          var stateText = safeText(trip.state, "").toLowerCase();
          return stateText === "patient_onboard" || stateText === "onboard";
        });
        var arrivedFacilityTrips = trips.filter(function (trip) {
          return safeText(trip.state, "").toLowerCase() === "arrived_at_facility";
        });
        var escalatedTrips = trips.filter(function (trip) {
          return safeText(trip.state, "").toLowerCase() === "escalated";
        });
        var supervisorReviewedTrips = resolutionTimelineModule.filter(function (item) {
          return safeText(item.trip_state, "").toLowerCase() === "supervisor_reviewed";
        });

        var queueRows = queueTrips.map(function (trip) {
          var priority = safeText(trip.priority, "standard");
          var pc = priority === "urgent" ? "badge badge-bad" : priority === "standard" ? "badge badge-soft" : "badge badge-neutral";
          var tripId = safeText(trip.id, "");
          return '<tr><td>' + escapeHtml(safeText(trip.id, "TRIP")) + '</td><td>' + escapeHtml(safeText(trip.riderName, "Rider")) + '</td><td>' + escapeHtml(safeText(trip.tripLeg, "—")) + '</td><td>' + escapeHtml(safeText(trip.pickup, "Pickup")) + '</td><td>' + escapeHtml(safeText(trip.dropoff, "Dropoff")) + '</td><td class="muted">' + escapeHtml(tripWaitText(trip)) + '</td><td><span class="' + pc + '">' + escapeHtml(priority) + '</span></td><td>' + lifecycleBadge(trip.state) + '</td><td class="muted time-stamp-cell">' + escapeHtml(formatOperationalTime(trip.requestedAt)) + '</td><td class="muted appointment-window-cell">' + escapeHtml(safeText(trip.appointmentWindow, "window pending")) + '</td><td class="muted coordination-note-cell">' + escapeHtml(safeText(trip.coordinationNote, "coordination pending")) + '</td><td><span class="badge badge-soft">' + escapeHtml(tripSlaText(trip)) + '</span></td>' +
            '<td><button class="btn-action btn-assign" onclick="window._amiHandleDispatchAssign(\'' + escapeHtml(tripId) + '\')">Assign</button> <button class="btn-action" onclick="window._amiHandleDispatchReassign(\'' + escapeHtml(tripId) + '\')">Reassign</button> <button class="btn-action" onclick="window._amiHandleDispatchEscalate(\'' + escapeHtml(tripId) + '\')">Escalate</button> <button class="btn-action" onclick="window._amiHandleDispatchCancel(\'' + escapeHtml(tripId) + '\')">Cancel</button> <button class="btn-action" onclick="window._amiHandleDispatchContactRider(\'' + escapeHtml(tripId) + '\')">Contact Rider</button> <button class="btn-action" onclick="window._amiHandleDispatchContactDriver(\'' + escapeHtml(tripId) + '\')">Contact Driver</button></td></tr>';
        }).join("");
        if (!queueRows) {
          queueRows = '<tr><td colspan="13" class="muted">No pending transport assignments. Intake queue is currently stable and all active transports are supervised.</td></tr>';
        }

        var driverCards = availableDrivers.map(function (driver) {
          var status = safeText(driver.status, "available");
          var selected = selectedDriverId && selectedDriverId === safeText(driver.id, "");
          var badgeClass = status === "available" ? "badge-good" : status === "assigned" ? "badge-soft" : "badge-warn";
          return '<div class="driver-card tile" style="outline:' + (selected ? '2px solid var(--accent)' : 'none') + '"><div class="driver-card-top"><strong>' + escapeHtml(safeText(driver.name, "Driver")) + '</strong><span class="badge ' + badgeClass + '">' + escapeHtml(status) + '</span></div>' +
            '<div class="driver-card-meta"><span>' + escapeHtml(safeText(driver.vehicle, "Vehicle")) + '</span><span>ID ' + escapeHtml(safeText(driver.id, "")) + '</span><span>ETA ' + escapeHtml(String(safeNumber(driver.etaMin, 0))) + ' min</span></div>' +
            '<button class="btn-action" style="width:100%;margin-top:8px" onclick="window._amiHandleDispatchDriverSelect(\'' + escapeHtml(safeText(driver.id, "")) + '\',\'' + escapeHtml(safeText(driver.name, "Driver")) + '\')">Select for Assignment</button></div>';
        }).join("");

        var activeRows = activeTrips.map(function (trip) {
          var tripId = safeText(trip.id, "");
          var routeStatusText = safeText(trip.routeStatus, "live");
          var routeStatusMap = {
            intake_review: "Intake Review",
            driver_assignment_confirmed: "Driver Assigned",
            rural_pickup_en_route: "Driver En Route",
            onboard_confirmed: "Patient Onboard",
            facility_route_active: "Active Facility Transport",
            facility_arrival_confirmed: "Arrived Facility",
            transport_completed: "Completed",
            driver_shortage_escalated: "Driver Shortage Escalated"
          };
          return '<tr><td>' + escapeHtml(safeText(trip.id, "TRIP")) + '</td><td>' + escapeHtml(safeText(trip.riderName, "Rider")) + '</td><td>' + escapeHtml(safeText(trip.assignedDriverName, "unassigned")) + '</td><td>' + lifecycleBadge(trip.state) + '</td><td>' + escapeHtml(String(safeNumber(trip.etaMin, 0))) + ' min</td><td><span class="badge badge-soft">' + escapeHtml(safeText(routeStatusMap[routeStatusText], titleizeWords(routeStatusText))) + '</span></td><td><button class="btn-action" onclick="window._amiHandleDispatchMarkArrived(\'' + escapeHtml(tripId) + '\')">Mark Arrived</button> <button class="btn-action" onclick="window._amiHandleDispatchComplete(\'' + escapeHtml(tripId) + '\')">Complete Ride</button> <button class="btn-action" onclick="window._amiHandleDispatchMonitor(\'' + escapeHtml(tripId) + '\')">Monitor</button></td></tr>';
        }).join("");
        if (!activeRows) {
          activeRows = '<tr><td colspan="7" class="muted">No active transports are currently in progress.</td></tr>';
        }

        var telemetry = window.AmiTelemetryEngine && typeof window.AmiTelemetryEngine.snapshot === "function" ? window.AmiTelemetryEngine.snapshot() : { kpis: {} };
        var kpis = telemetry.kpis || {};
        var dispatchSlaAlerts = safeNumber(kpis.slaBreaches, 0);
        var urgentSignals = safeNumber(kpis.urgentRideFlags, 0) + countEventsByKeyword(events, "urgent");
        var delayedRideAlerts = delayedRideModule.length > 0 ? delayedRideModule.length : safeNumber(kpis.delayedRideAlerts, 0);
        var dispatchTimelineEvents = liveActivityFeed.length > 0
          ? liveActivityFeed.map(function (item, idx) {
              return {
                sequence_number: idx + 1,
                category: "dispatch",
                event: safeText(item.action, "activity"),
                title: safeText(item.description, "Dispatch activity"),
                description: safeText(item.description, "Dispatch activity"),
                priority: "medium",
                role: safeText(item.actor_user_id, "operator"),
                source: safeText(item.driver_id || item.ride_id, "health_isf"),
                timestamp: safeText(item.created_at, ""),
                group: safeText(item.ride_id || item.id, "dispatch"),
                hydrationState: "live"
              };
            })
          : events;

        return [
          renderPanelBlock("Dispatcher Command Center Board", "Operational command center with active medical transport queues, assignment controls, and escalation-safe SLA visibility.",
            '<div class="grid-4">' +
              renderMetric("Pending Ride Queue", String(safeNumber(kpis.activeTripQueue, queueTrips.length)), "warn") +
              renderMetric("Assigned Awaiting Pickup", String(assignedWorkflowTrips.length), assignedWorkflowTrips.length > 0 ? "warn" : "good") +
              renderMetric("Available Drivers", String(safeNumber(kpis.driverAvailable, availableDrivers.length)), "good") +
              renderMetric("Drivers In Transit", String(Math.max(safeNumber(kpis.driverBusy, 0), inTransitWorkflowTrips.length))) +
              renderMetric("Active Trips", String(Math.max(safeNumber(kpis.inProgress, activeTrips.length), inTransitWorkflowTrips.length))) +
              renderMetric("Urgent Signals", String(Math.max(urgentSignals, 1)), "bad") +
              renderMetric("Delayed Ride Alerts", String(delayedRideAlerts), delayedRideAlerts > 0 ? "warn" : "good") +
              renderMetric("SLA Breaches", String(dispatchSlaAlerts), dispatchSlaAlerts > 0 ? "bad" : "good") +
            '</div>', "dispatch-kpis"),
          renderPanelBlock("Trip Progress Visibility", "Dispatcher progress scan from intake to assignment, transport, and completion.",
            '<div class="grid-4">' +
              renderMetric("Pending Intake", String(queueTrips.length), queueTrips.length > 0 ? "warn" : "good") +
              renderMetric("Assigned", String(assignedWorkflowTrips.length), assignedWorkflowTrips.length > 0 ? "warn" : "good") +
              renderMetric("Driver En Route", String(driverEnRouteTrips.length), driverEnRouteTrips.length > 0 ? "good" : "neutral") +
              renderMetric("Patient Onboard", String(patientOnboardTrips.length), patientOnboardTrips.length > 0 ? "good" : "neutral") +
              renderMetric("In Transit", String(inTransitWorkflowTrips.length), inTransitWorkflowTrips.length > 0 ? "good" : "neutral") +
              renderMetric("Arrived Facility", String(arrivedFacilityTrips.length), arrivedFacilityTrips.length > 0 ? "good" : "neutral") +
              renderMetric("Completed", String(completedWorkflowTrips.length), completedWorkflowTrips.length > 0 ? "good" : "neutral") +
              renderMetric("Escalated", String(escalatedTrips.length), escalatedTrips.length > 0 ? "warn" : "good") +
              renderMetric("Supervisor Reviewed", String(supervisorReviewedTrips.length), supervisorReviewedTrips.length > 0 ? "good" : "neutral") +
            '</div>' +
            '<p class="muted">Operational flow: Requested → Assigned → Driver En Route → Patient Onboard → In Transit → Arrived Facility → Completed → Escalated → Supervisor Reviewed.</p>',
            'dispatch-lifecycle'
          ),
          renderPanelBlock("Active Trip Queue", "Requested, scheduled, assigned, and delayed healthcare transport trips requiring dispatch action.",
            '<div class="table-wrap"><table class="ops-table"><thead><tr><th>Trip ID</th><th>Patient</th><th>Leg</th><th>Pickup Facility</th><th>Dropoff Facility</th><th>Wait Time</th><th>Priority</th><th>Trip Stage</th><th>Requested At</th><th>Appt Window</th><th>Coordination</th><th>SLA Window</th><th>Actions</th></tr></thead><tbody id="dispatch-queue-tbody">' + queueRows + '</tbody></table></div>',
            "dispatch-queue"),
          renderPanelBlock("Driver Status Board", "Driver statuses, selection, and assignment routing.",
            '<div id="available-drivers-grid" style="display:grid;grid-template-columns:repeat(auto-fill,minmax(220px,1fr));gap:12px">' + driverCards + '</div>',
            "available-drivers"),
          renderPanelBlock("Live Trip Management", "Trips currently in progress with route status indicators, patient transport context, and completion controls.",
            '<div class="table-wrap"><table class="ops-table"><thead><tr><th>Trip ID</th><th>Patient</th><th>Driver</th><th>Transport State</th><th>ETA</th><th>Route Status</th><th>Actions</th></tr></thead><tbody>' + activeRows + '</tbody></table></div>',
            "active-trips"),
          renderPanelBlock("Dispatch Escalation and Incident Watch", "Escalation and exception signals requiring supervised dispatch triage.",
            '<div class="table-wrap"><table class="ops-table"><thead><tr><th>Trip ID</th><th>Indicator</th><th>Priority</th><th>State</th></tr></thead><tbody>' + escalationModule.slice(0, 12).map(function (item, idx) {
              var priority = safeText(item.priority || item.severity, "medium").toLowerCase();
              var badge = priority === "high" || priority === "critical" ? "badge badge-bad" : priority === "medium" ? "badge badge-warn" : "badge badge-soft";
              var indicatorRaw = safeText(item.indicator || item.reason || item.title, "dispatch_exception");
              var stateRaw = safeText(item.state || item.trip_state, "active");
              return '<tr><td>' + escapeHtml(safeText(item.trip_id || item.ride_id || item.id, "TRIP-" + String(idx + 1))) + '</td><td>' + escapeHtml(titleizeWords(indicatorRaw)) + '</td><td><span class="' + badge + '">' + escapeHtml(priority) + '</span></td><td>' + escapeHtml(titleizeWords(stateRaw)) + '</td></tr>';
            }).join("") + '</tbody></table></div>',
            "dispatch-escalations"),
          renderPanelBlock("Reassignment Workflow Queue", "Live reassignment workflow for rejected, expired, and unstable trip offers.",
            '<div class="table-wrap"><table class="ops-table"><thead><tr><th>Trip</th><th>Rider</th><th>Assignment State</th><th>Driver</th><th>Actions</th></tr></thead><tbody>' + reassignmentModule.slice(0, 12).map(function (item, idx) {
              var tripId = safeText(item.trip_id || item.ride_id || item.id, "TRIP-" + String(idx + 1));
              var assignmentStateRaw = safeText(item.assignment_status, "reassignment_pending");
              return '<tr><td>' + escapeHtml(tripId) + '</td><td>' + escapeHtml(safeText(item.rider_name, "rider")) + '</td><td>' + escapeHtml(titleizeWords(assignmentStateRaw)) + '</td><td>' + escapeHtml(safeText(item.assigned_driver_name || item.driver_id, "unassigned")) + '</td><td><button class="btn-action" onclick="window._amiHandleDispatchReassign(\'' + escapeHtml(tripId) + '\')">Reassign</button> <button class="btn-action" onclick="window._amiHandleDispatchEscalate(\'' + escapeHtml(tripId) + '\')">Escalate</button></td></tr>';
            }).join("") + '</tbody></table></div>',
            'dispatch-reassignments'
          ),
          renderPanelBlock("No-Driver Recovery Watch", "Trips with no available driver that require manual recovery or supervisor routing.",
            '<div class="table-wrap"><table class="ops-table"><thead><tr><th>Trip</th><th>Rider</th><th>State</th><th>Risk</th><th>Actions</th></tr></thead><tbody>' + noDriverRecoveryModule.slice(0, 12).map(function (item, idx) {
              var tripId = safeText(item.trip_id || item.ride_id || item.id, "TRIP-" + String(idx + 1));
              var highRisk = Array.isArray(item.transport_risk_indicators) && item.transport_risk_indicators.length > 0;
              var noDriverStateRaw = safeText(item.trip_state, "scheduled");
              return '<tr><td>' + escapeHtml(tripId) + '</td><td>' + escapeHtml(safeText(item.rider_name, "rider")) + '</td><td>' + escapeHtml(titleizeWords(noDriverStateRaw)) + '</td><td><span class="badge ' + (highRisk ? 'badge-bad' : 'badge-warn') + '">' + escapeHtml(highRisk ? 'high' : 'watch') + '</span></td><td><button class="btn-action" onclick="window._amiHandleDispatchAssign(\'' + escapeHtml(tripId) + '\')">Assign</button> <button class="btn-action" onclick="window._amiHandleSupervisorEmergency(\'' + escapeHtml(tripId) + '\')">Supervisor</button></td></tr>';
            }).join("") + '</tbody></table></div>',
            'dispatch-no-driver-recovery'
          ),
          renderStreamStatusPanel(phase17),
          renderEnhancedOperationalTimeline("Dispatch Activity Feed", "Assignment and status events.", dispatchTimelineEvents, 10)
        ].join("");
      }

  function renderProviders() {
    if (state.role === "provider") {
      return renderProviderDashboard(getPhase17Context());
    }
    if (state.role === "medical_coordinator") {
      return renderMedicalCoordinatorDashboard(getPhase17Context());
    }
    if (state.role === "compliance_officer") {
      return renderComplianceOfficerDashboard(getPhase17Context());
    }
    if (state.role === "supervisor") {
      return renderSupervisorDashboard(getPhase17Context());
    }
    var supervision = state.supervision || {};
    var events = Array.isArray(supervision.recent_events) ? supervision.recent_events : [];
    var providerSignals = countEventsByKeyword(events, "provider");
    var queueCount = safeText((((supervision || {}).diagnostics_summary || {}).active_queue_counts || {}).runtime_governor_active_workflows, "0");
    var memory = (state.health || {}).memory_persistence || {};
    var providerAlerts = countEventsByLevel(events, "warning") + countEventsByLevel(events, "error");
    var liveProviders = Array.isArray((safeObject(state.liveWorkflow)).providers)
      ? state.liveWorkflow.providers
      : [];
    var activeProviders = liveProviders.filter(function (provider) {
      return provider && provider.is_active !== false;
    });
    var tableHtml = activeProviders.length
      ? activeProviders.slice(0, 40).map(function (provider) {
          return '<tr>' +
            '<td>' + escapeHtml(safeText(provider.name, "Provider")) + '</td>' +
            '<td><span class="status-dot">' + escapeHtml(provider.is_active === false ? "inactive" : "active") + '</span></td>' +
            '<td>' + escapeHtml(safeText(provider.service_type, "healthcare")) + '</td>' +
            '<td>' + escapeHtml(safeText(provider.phone, "n/a")) + '</td>' +
            '<td>' + escapeHtml(safeText(provider.address, "n/a")) + '</td>' +
            '</tr>';
        }).join("")
      : '<tr><td colspan="5" class="muted">No active providers loaded from backend.</td></tr>';

    return [
      renderPanelBlock(
        "Provider Operations Overview",
        "Live provider readiness from backend records.",
        '<div class="grid-4">' +
          renderMetric("Active Providers", String(activeProviders.length)) +
          renderMetric("Provider Signals", String(providerSignals)) +
          renderMetric("Dispatch Queue Depth", queueCount) +
          renderMetric("Operational Alerts", String(providerAlerts)) +
        '</div>',
        "providers"
      ),
      renderPanelBlock(
        "Active Providers",
        "Seeded and live providers only — no demo placeholders.",
        '<div class="table-wrap">' +
        '<table class="ops-table"><thead><tr><th>Provider</th><th>Status</th><th>Service</th><th>Phone</th><th>Address</th></tr></thead><tbody>' + tableHtml + '</tbody></table>' +
        '</div>' +
        '<p class="muted">Memory continuity: ' + escapeHtml(safeText(memory.status, "unknown")) +
        ' · Supervision: ' + escapeHtml(safeText(supervision.supervision_status, "unknown")) + '</p>',
        "table"
      )
    ].join("");
  }

  function renderDrivers() {
    var phase17 = getPhase17Context();
    if (state.role === "driver") {
      return renderDriverRoleHomeDashboard(phase17);
    }
    if (state.role === "driver_support") {
      return renderDriverSupportDashboard(phase17);
    }
    if (state.role === "compliance_officer") {
      return renderComplianceOfficerDashboard(phase17);
    }
    if (state.role === "dispatcher" || state.role === "supervisor") {
      return renderDispatcherDashboard(phase17);
    }

    var supervision = state.supervision || {};
    var events = Array.isArray(supervision.recent_events) ? supervision.recent_events : [];
    var driverSignals = countEventsByKeyword(events, "driver");
    var websocket = supervision.websocket_status || {};
    var activeRides = filterActiveOperationalRides(
      Array.isArray((safeObject(state.liveWorkflow)).rides) ? state.liveWorkflow.rides : []
    );
    var liveDrivers = Array.isArray((safeObject(state.liveWorkflow)).drivers)
      ? state.liveWorkflow.drivers
      : [];
    var availableDrivers = liveDrivers.filter(function (driver) {
      return safeText(driver.status || driver.availability_state, "").toLowerCase() === "available";
    });
    var routeTable = activeRides.length
      ? activeRides.slice(0, 20).map(function (ride) {
          return '<tr><td>' + escapeHtml(safeText(ride.passenger_name, shortOperationalId(ride.id, "ride"))) +
            '</td><td>' + escapeHtml(safeText(ride.lifecycle_state || ride.status, "active")) +
            '</td><td>' + escapeHtml(safeText(ride.driver_id, "unassigned").slice(0, 8)) +
            '</td><td>' + escapeHtml(safeText(ride.pickup_address, "pickup")) + '</td></tr>';
        }).join("")
      : '<tr><td colspan="4" class="muted">No active rides. Drivers are awaiting assignment.</td></tr>';

    return [
      renderPanelBlock(
        "Fleet Monitoring Overview",
        "Driver readiness and active in-progress rides only.",
        '<div class="grid-4">' +
          renderMetric("Drivers Available", String(availableDrivers.length)) +
          renderMetric("Active Rides", String(activeRides.length)) +
          renderMetric("Driver Connections", safeText(websocket.driver_connections, "0")) +
          renderMetric("Driver Signals", String(driverSignals)) +
        '</div>',
        "drivers"
      ),
      renderQuickLinks([
        { href: "/app/mobile", title: "Driver Mobile", description: "Open the driver mobile app experience.", note: "live" },
        { href: "/app/dispatch", title: "Dispatch Center", description: "Monitor live trip assignment and escalation.", note: "live" },
        { href: "/app/trips", title: "Trips", description: "View the trip lifecycle and route context.", note: "read-only" },
        { href: "/app/alerts", title: "Alerts", description: "Review fleet safety and compliance notices.", note: "supervised" }
      ]),
      renderPanelBlock(
        "Active Rides",
        "In-progress and waiting-dispatch rides only. Completed trips belong in History/Billing.",
        '<div class="table-wrap">' +
          '<table class="ops-table"><thead><tr><th>Rider</th><th>Status</th><th>Driver</th><th>Pickup</th></tr></thead><tbody>' + routeTable + '</tbody></table>' +
        '</div>',
        "dispatch"
      ),
      renderPanelBlock(
        "Driver Metrics and Fleet Status",
        "Live driver availability and activity.",
        '<div class="grid-3">' +
          renderMetric("Fleet Status", safeText(supervision.supervision_status, "unknown")) +
          renderMetric("Drivers Online", String(liveDrivers.length)) +
          renderMetric("Available", String(availableDrivers.length)) +
          renderMetric("Active Rides", String(activeRides.length)) +
          renderMetric("Driver Signals", String(driverSignals)) +
          renderMetric("Live Update State", safeText(websocket.status, "unknown")) +
        '</div>' +
        '<div class="tile"><h4>Driver Activity Feed</h4>' + renderFeedSummary(events, "driver") + '</div>',
        "fleet"
      ),
      renderPanelBlock(
        "Live Active Ride Table",
        "Operational rides awaiting or in transport.",
        '<div class="table-wrap">' +
          '<table class="ops-table"><thead><tr><th>Rider</th><th>Status</th><th>Driver</th><th>Pickup</th></tr></thead><tbody>' + routeTable + '</tbody></table>' +
        '</div>' +
        renderSimpleBars([
          { label: "Driver Signals", value: driverSignals, note: "driver-related events" },
          { label: "Active Rides", value: activeRides.length, note: "non-terminal rides" },
          { label: "Available Drivers", value: availableDrivers.length, note: "ready for assignment" }
        ]),
        "table"
      )
    ].join("");
  }

  function renderOperations() {
    var phase17 = getPhase17Context();
    var supervision = state.supervision || {};
    var health = state.health || {};
    var runtimeGovernor = supervision.runtime_governor || {};
    var websocket = supervision.websocket_status || {};
    var events = Array.isArray(supervision.recent_events) ? supervision.recent_events : [];
    var queueCounts = (((supervision || {}).diagnostics_summary || {}).active_queue_counts || {});
    var warnings = buildSystemNotices();
    var eventWarnings = countEventsByLevel(events, "warning");
    var eventErrors = countEventsByLevel(events, "error");
    return [
      renderStreamStatusPanel(phase17),
      renderComplianceOverviewPanel(phase17),
      renderExpirationQueuePanel(phase17),
      renderApprovalQueuePanel(phase17),
      renderComplianceTimelinePanel(phase17),
      renderEvidenceChainViewerPanel(phase17),
      renderDocumentLineageViewerPanel(phase17),
      renderSupervisorReviewQueuePanel(phase17),
      renderRegulatoryExportBuilderPanel(phase17),
      renderSignedAccessMonitorPanel(phase17),
      renderRetentionStatusDashboardPanel(phase17),
      renderSupervisorTaskInboxPanel(phase17),
      renderEscalationQueuePanel(phase17),
      renderAssignmentTimelinePanel(phase17),
      renderOperationalNotificationsPanel(phase17),
      renderHandoffTrackerPanel(phase17),
      renderQueueHealthDashboardPanel(phase17),
      renderResolutionApprovalQueuePanel(phase17),
      renderLiveOperationalStreamPanel(phase17),
      renderSlaAdvisoryMonitorPanel(phase17),
      renderQueuePressureDashboardPanel(phase17),
      renderResolutionAuditTimelinePanel(phase17),
      renderExportBundleConsolePanel(phase17),
      renderPanelBlock(
        "Operations Overview",
        "Supervisor intervention posture, dispatch stability, and continuity pressure derived from current operations visibility.",
        '<div class="grid-4">' +
          renderMetric("Operations Readiness", safeText(health.backend_status || supervision.backend_status, "unknown")) +
          renderMetric("Stability Status", safeText(supervision.health_classification, "unknown")) +
          renderMetric("Supervisor Control Visibility", safeText(runtimeGovernor.status, "unknown")) +
          renderMetric("Live Update Visibility", safeText(websocket.status, "unknown")) +
        '</div>',
        "operations"
      ),

      renderPanelBlock(
        "Activity Monitoring Cards",
        "Operational friction indicators, escalation accumulation, and queue-pressure visibility.",
        '<div class="grid-3">' +
          renderMetric("Recent Events", String(events.length)) +
          renderMetric("Warnings", String(eventWarnings)) +
          renderMetric("Errors", String(eventErrors)) +
          renderMetric("Priority Coordination Backlog", safeText(queueCounts.runtime_governor_active_workflows, "0")) +
          renderMetric("Active Requests", safeText(supervision.active_request_count, "0")) +
          renderMetric("Coordination Snapshot", safeText(supervision.diagnostics_version, "unknown")) +
        '</div>',
        "events"
      ),

      renderPanelBlock(
        "Operational Summary",
        "Read-only command summary for queue posture, escalation pressure, and continuity oversight.",
        '<div class="grid-2">' +
          '<div class="tile"><h4>Coordination Summary</h4>' + renderPayloadViewer("Coordination Summary", supervision.diagnostics_summary || {}, "read-only payload") + '</div>' +
          '<div class="tile"><h4>Queue Metrics</h4><p>Queue metrics are derived from existing supervision data and tracked for supervisor intervention.</p><p class="muted">Supervisor review backlog: ' + escapeHtml(safeText(queueCounts.runtime_governor_active_workflows, "0")) + '</p></div>' +
        '</div>',
        "diagnostics"
      ),

      renderPanelBlock(
        "Dispatch Flow Stability and Supervisor Control",
        "Operational visibility into field coordination channels and supervisor oversight readiness.",
        '<div class="grid-3">' +
          renderMetric("Dispatch Channel Status", safeText(websocket.status, "unknown"), healthToneFromStatus(websocket.status)) +
          renderMetric("Dispatcher Staffing Active", safeText(websocket.dispatcher_connections, "0")) +
          renderMetric("Driver Staffing Active", safeText(websocket.driver_connections, "0")) +
          renderMetric("Supervisor Review Active", safeText(runtimeGovernor.status, "unknown"), healthToneFromStatus(runtimeGovernor.status)) +
          renderMetric("Transport Readiness", safeText(runtimeGovernor.telemetry_status, "unknown")) +
          renderMetric("Queue Stability", safeText(supervision.health_classification, "unknown"), healthToneFromStatus(supervision.health_classification)) +
        '</div>',
        "governor"
      ),

      renderPanelBlock(
        "Supervision Activity Feed",
        "Recent dispatch coordination updates, route recovery actions, and supervisory notices.",
        renderRecentEvents(events, 12),
        "feed"
      ),

      renderPanelBlock(
        "Operational Pressure Watch",
        "Managed warning posture for continuity-sensitive transport operations.",
        renderNoticeList(warnings) + renderSimpleBars([
          { label: "Warnings", value: eventWarnings, note: "warning-level recent events" },
          { label: "Errors", value: eventErrors, note: "error-level recent events" },
          { label: "Queue Depth", value: safeNumber(queueCounts.runtime_governor_active_workflows, 0), note: "active workflow count" }
        ]),
        "warnings"
      )
    ].join("");
  }

  function renderOperationsLive() {
    var phase17 = getPhase17Context();
    return [
      renderPanelBlock(
        "Operations Live Projection",
        "Live supervised coordination projection with advisory-only resolution controls.",
        '<div class="grid-4">' +
          renderMetric("Advisory Only", "true") +
          renderMetric("Execution Disabled", "true") +
          renderMetric("Unsupervised Actions", "disabled") +
          renderMetric("Audit-Tracked", "yes") +
        '</div>' +
        '<p class="muted">This route is projection-only. Closures require authenticated human dual approval upstream.</p>',
        "operations-live"
      ),
      renderResolutionApprovalQueuePanel(phase17),
      renderLiveOperationalStreamPanel(phase17),
      renderSlaAdvisoryMonitorPanel(phase17),
      renderQueuePressureDashboardPanel(phase17),
      renderResolutionAuditTimelinePanel(phase17),
      renderExportBundleConsolePanel(phase17)
    ].join("");
  }

  function getPhase17Context() {
    var health = state.health || {};
    var supervision = state.supervision || {};
    var ops = state.ops || {};
    var dashboardSummary = ops.dashboardSummary || {};
    var opsVisibility = dashboardSummary.visibility || {};
    var phase16Overview = (((health || {}).phase16_operational_overview || {}).overview || {});
    var phase16Panels = phase16Overview.live_operational_telemetry_panels || {};
    var phase16Lifecycle = (phase16Overview.ride_lifecycle_engine || {}).state_counts || {};
    var phase16DriverStates = (phase16Overview.driver_state_registry || {}).states || {};
    var phase16ProviderStates = (phase16Overview.provider_state_registry || {}).states || {};
    var phase16WorkflowTimeline = (dashboardSummary.workflow_timeline || phase16Panels.workflow_timeline || []);
    var phase16EventPreview = (dashboardSummary.event_stream_preview || ((phase16Overview.operational_state_visualization || {}).event_stream_preview) || []);
    var phase16Alerts = (dashboardSummary.alerts || phase16Panels.operational_alerts || {});
    var geospatial = phase16Overview.geospatial_foundation || {};
    var events = Array.isArray(supervision.recent_events) ? supervision.recent_events : [];
    var runtimeGovernor = supervision.runtime_governor || {};
    var websocket = supervision.websocket_status || {};
    var memory = health.memory_persistence || {};
    var diagnostics = health.diagnostics || {};
    var validation = diagnostics.validation || {};
    var uptimeSeconds = safeNumber(supervision.uptime_seconds, 0);
    var uptimeText = safeText(supervision.uptime_human_readable, uptimeSeconds + "s");
    var activeRequests = safeNumber(supervision.active_request_count, 0);
    var throughput = throughputLabel(supervision.active_request_count, events.length);
    var assistantSignals = countEventsByKeyword(events, "assistant") + countEventsByKeyword(events, "ai");

    if (ops.liveStatus && typeof ops.liveStatus === "object") {
      runtimeGovernor = ops.liveStatus.runtime_governor_state || runtimeGovernor;
      websocket = ops.liveStatus.websocket_readiness || websocket;
    }

    return {
      health: health,
      supervision: supervision,
      overview: phase16Overview,
      panels: phase16Panels,
      lifecycle: dashboardSummary.rides ? (dashboardSummary.rides.state_counts || phase16Lifecycle) : phase16Lifecycle,
      driverStates: dashboardSummary.drivers ? (dashboardSummary.drivers.state_counts || phase16DriverStates) : phase16DriverStates,
      providerStates: dashboardSummary.providers ? (dashboardSummary.providers.state_counts || phase16ProviderStates) : phase16ProviderStates,
      workflowTimeline: phase16WorkflowTimeline,
      eventPreview: (ops.timeline || []).length > 0 ? ops.timeline : phase16EventPreview,
      alerts: phase16Alerts,
      geospatial: geospatial,
      events: events,
      runtimeGovernor: runtimeGovernor,
      websocket: websocket,
      memory: memory,
      validation: validation,
      uptimeSeconds: uptimeSeconds,
      uptimeText: uptimeText,
      activeRequests: activeRequests,
      throughput: throughput,
      assistantSignals: assistantSignals,
      recommendations: Array.isArray(ops.recommendations) ? ops.recommendations : (dashboardSummary.assistant_recommendations || []),
      stream: ops.stream || {},
      correlation: ops.correlation || { totalGroups: 0, groups: [] },
      compliance: ops.compliance || {},
      orchestration: ops.orchestration || {},
      visibility: opsVisibility,
      providerReady: countEventsByKeyword(events, "provider") > 0 ? "warming" : "baseline",
      driverReady: countEventsByKeyword(events, "driver") > 0 ? "warming" : "baseline",
      assistantReady: safeText(health.backend_status, "unknown") === "green" ? "ready" : "watch"
    };
  }

  function renderCommandCenterProtectedStatus() {
    return '<div class="protected-endpoint-list">' + [
      "/api/health-isf/operations/workflow-overview",
      "/api/health-isf/operations/workflow-events",
      "/api/health-isf/operations/lifecycle-matrix",
      "/api/health-isf/operations/command-center",
      "/api/health-isf/operations/timeline",
      "/api/health-isf/operations/map-preview",
      "/api/health-isf/operations/alerts"
    ].map(function (path) {
      return '<div class="endpoint-row"><strong>' + escapeHtml(path) + '</strong><span class="badge badge-warn">401 expected</span></div>';
    }).join("") + '</div>';
  }

  function renderCommandCenterMapPreview(phase17) {
    var geospatial = phase17.geospatial || {};
    var coordinateModel = geospatial.coordinate_entity_model || {};
    var driverRegistry = geospatial.driver_position_registry || {};
    var zoneModel = geospatial.operational_zone_abstraction || {};
    var overlayModel = geospatial.map_overlay_scaffolding || {};
    var routePlaceholder = geospatial.route_placeholder_model || {};
    var driverCoordinates = Array.isArray(coordinateModel.driver_coordinates) ? coordinateModel.driver_coordinates : [];
    var zones = Array.isArray(zoneModel.zones) ? zoneModel.zones : [];
    var overlays = Array.isArray(overlayModel.overlays) ? overlayModel.overlays : [];

    return [
      renderPanelBlock(
        "Map Panel Container",
        "Adapter-safe geospatial scaffold. No live GPS or external map provider lock-in.",
        '<div class="command-map">' +
          '<div class="map-grid"></div>' +
          '<div class="map-overlay map-overlay-zone">Zone overlay</div>' +
          '<div class="map-overlay map-overlay-route">Route preview</div>' +
          '<div class="map-overlay map-overlay-vehicle">Vehicle marker</div>' +
          '<div class="map-overlay map-overlay-pickup">Pickup</div>' +
          '<div class="map-overlay map-overlay-dropoff">Dropoff</div>' +
          '<div class="map-stage-copy"><strong>Provider-agnostic map preview</strong><p>Coordinate rendering remains placeholder-only until an adapter is intentionally chosen.</p></div>' +
        '</div>' +
        '<div class="grid-3 map-summary-grid">' +
          renderMetric("Driver Coordinates", String(driverCoordinates.length)) +
          renderMetric("Operational Zones", String(zones.length)) +
          renderMetric("Map Overlays", String(overlays.length)) +
          renderMetric("Route Engine", safeText(routePlaceholder.status, "scaffold_only")) +
          renderMetric("Driver Registry", safeText(driverRegistry.replay_safe, true) ? "Continuity Protected" : "watch") +
          renderMetric("External Provider Lock-In", safeText(routePlaceholder.external_provider_locked, false) ? "locked" : "none") +
        '</div>',
        "map-preview"
      ),

      renderPanelBlock(
        "Map Foundation Details",
        "Coordinate, overlay, and zone placeholders prepared for future adapters.",
        '<div class="grid-2">' +
          '<div class="tile"><h4>Coordinate Entity Model</h4>' + renderPayloadViewer("Coordinate Model", coordinateModel, "driver and incident coordinate scaffolding") + '</div>' +
          '<div class="tile"><h4>Operational Zone Abstraction</h4>' + renderPayloadViewer("Operational Zones", zoneModel, "provider-agnostic zone scaffolding") + '</div>' +
        '</div>' +
        '<div class="divider"></div>' +
        '<div class="grid-2">' +
          '<div class="tile"><h4>Route Preview Placeholder</h4><p>Routing remains intentionally disabled. Only preview scaffolding is available.</p><p class="muted">Route engine enabled: ' + escapeHtml(String(routePlaceholder.route_engine_enabled)) + '</p></div>' +
          '<div class="tile"><h4>Overlay Scaffolding</h4><p>Overlay layers are provider-agnostic and read-only.</p><p class="muted">Overlays: ' + escapeHtml(String(overlays.length)) + '</p></div>' +
        '</div>',
        "map foundation"
      )
    ].join("");
  }

  function renderCommandCenterSafePreview(phase17) {
    return [
      renderPanelBlock(
        "Safe Next-Action Preview",
        "Disabled preview-only buttons show how future operator flows will remain supervised.",
        '<div class="command-actions">' +
          '<button class="preview-action" disabled>Preview active operations summary</button>' +
          '<button class="preview-action" disabled>Preview delayed workflows</button>' +
          '<button class="preview-action" disabled>Preview protected endpoint status</button>' +
          '<button class="preview-action" disabled>Preview map foundation</button>' +
        '</div>' +
        '<p class="muted">All actions are disabled by design. No dispatch or direct change controls are exposed.</p>',
        "safe-preview"
      ),

      renderPanelBlock(
        "Protected Endpoint Status",
        "Expected authorization posture for read-only operational APIs.",
        renderCommandCenterProtectedStatus(),
        "protected-endpoints"
      )
    ].join("");
  }

  function renderAssistantRecommendationsPanel(phase17) {
    var delayedOperations = safeNumber((phase17.alerts || {}).delayed_operations, 0);
    var warnings = countEventsByLevel(phase17.events || [], "warning");
    var errors = countEventsByLevel(phase17.events || [], "error");
    var suggestions = Array.isArray(phase17.recommendations) && phase17.recommendations.length > 0
      ? phase17.recommendations.map(function (item) {
          return {
            title: safeText(item.title, "Operational recommendation"),
            detail: safeText(item.advisory, "Advisory-only recommendation."),
            safety: item.supervisor_review_required ? "supervisor review required" : "preview required"
          };
        })
      : [
          {
            title: "Review delayed rides",
            detail: "Inspect delayed workflow timeline rows and verify provider coverage before any supervised intervention.",
            safety: "preview required"
          },
          {
            title: "Validate driver/provider availability",
            detail: "Compare available drivers against active provider demand and confirm readiness gaps using read-only operations visibility.",
            safety: "preview required"
          },
          {
            title: "Check live operations health",
            detail: "Confirm supervisor controls and live update channels remain stable prior to any upstream supervised action.",
            safety: "preview required"
          }
        ];

    return renderPanelBlock(
      "Assistant Recommendations",
      "Read-only operational suggestions with explicit safety labels and no execution path.",
      '<div class="grid-3">' +
        renderMetric("Safety Status", "supervision-gated") +
        renderMetric("Delayed Operations", String(delayedOperations)) +
        renderMetric("Warnings / Errors", String(warnings) + " / " + String(errors)) +
      '</div>' +
      '<div class="divider"></div>' +
      '<ul class="list">' + suggestions.map(function (item) {
        return '<li><strong>' + escapeHtml(item.title) + '</strong> <span class="badge badge-warn">' + escapeHtml(item.safety) + '</span><br><span class="muted">' + escapeHtml(item.detail) + '</span></li>';
      }).join("") + '</ul>' +
      '<p class="muted">Recommendations are advisory only. This panel cannot dispatch, execute, or alter operational state.</p>',
      "assistant-recommendations"
    );
  }

  function renderLiveDispatchAssistantPanel() {
    var snapshot = safeObject(state.healthIsfAiSnapshot);
    var liveDispatch = safeObject(snapshot.live_dispatch);
    var focused = safeObject(liveDispatch.focused_ride);
    var queueIds = Array.isArray(liveDispatch.queue_ride_ids) ? liveDispatch.queue_ride_ids : [];
    var snapshotQueue = Array.isArray(liveDispatch.queue) ? liveDispatch.queue : [];
    var workflowQueue = Array.isArray((safeObject(state.liveWorkflow)).dispatchQueue) ? state.liveWorkflow.dispatchQueue : [];
    var dispatchQueue = snapshotQueue.length > 0 ? snapshotQueue : workflowQueue;
    var queueDepth = snapshotQueue.length > 0
      ? snapshotQueue.length
      : safeNumber(liveDispatch.queue_count, dispatchQueue.length);
    var newestRideId = safeText(focused.ride_id, queueIds.length > 0 ? safeText(queueIds[0], "") : (dispatchQueue[0] ? safeText(dispatchQueue[0].ride_id, "") : ""));
    var queueHtml = dispatchQueue.slice(0, 8).map(function (item) {
      var rideId = safeText(item.ride_id, "");
      var selected = rideId && rideId === newestRideId ? " badge-good" : " badge-soft";
      return '<li><strong>' + escapeHtml(safeText(item.passenger_name, "Passenger")) + '</strong>'
        + ' <span class="badge' + selected + '">' + escapeHtml(safeText(item.assignment_state, "queued")) + '</span>'
        + '<br><span class="muted">Ride ' + escapeHtml(rideId) + '</span></li>';
    }).join("");
    if (!queueHtml) {
      queueHtml = '<li class="muted">No live dispatch queue rows available. Refresh dispatch workspace.</li>';
    }
    return renderPanelBlock(
      "Live Dispatch Assignment Queue",
      "Same authoritative dispatch queue used by the dashboard assignment board.",
      '<div class="grid-3">' +
        renderMetric("Queue Depth", String(queueDepth)) +
        renderMetric("Focused Ride", newestRideId ? newestRideId.slice(0, 8) + "…" : "none") +
        renderMetric("Assignment State", escapeHtml(safeText(focused.assignment_state, "pending"))) +
      '</div>' +
      (newestRideId ? '<p class="muted">Focused ride ' + escapeHtml(newestRideId) + (focused.driver_name ? " · driver " + escapeHtml(safeText(focused.driver_name, "")) : "") + '</p>' : "") +
      '<ul class="list">' + queueHtml + '</ul>',
      "assistant-live-dispatch"
    );
  }

  function renderOperationsCommandCenter() {
    var phase17 = getPhase17Context();
    var events = phase17.events;
    var liveActivityFeed = Array.isArray((safeObject(state.liveWorkflow)).activityFeed) ? state.liveWorkflow.activityFeed : [];
    var supervision = phase17.supervision;
    var health = phase17.health;
    var websocket = phase17.websocket;
    var runtimeGovernor = phase17.runtimeGovernor;
    var panelCount = safeNumber((phase17.panels || {}).active_workflow_cards, 0);
    var delayedOperations = safeNumber((phase17.alerts || {}).delayed_operations, 0);
    var backlog = safeNumber((phase17.alerts || {}).event_stream_backlog, 0);
    var activeStates = phase17.lifecycle;

    return [
      renderStreamStatusPanel(phase17),

      renderPanelBlock(
        "Transport Command Center",
        "Live read-only command visibility for assignment pressure, escalation handling, and dispatch recovery.",
        '<div class="grid-4">' +
          renderMetric("Assignment Pressure", String(panelCount)) +
          renderMetric("Active Transport Delays", String(delayedOperations)) +
          renderMetric("Priority Coordination Backlog", String(backlog)) +
          renderMetric("Provider Response Backlog", String(phase17.activeRequests)) +
          renderMetric("Operations Readiness", safeText(health.backend_status || supervision.backend_status, "unknown"), healthToneFromStatus(health.backend_status || supervision.backend_status)) +
          renderMetric("Supervisor Review Active", safeText(supervision.supervision_status, "unknown"), healthToneFromStatus(supervision.supervision_status)) +
          renderMetric("Dispatch Flow Stability", safeText(websocket.status, "unknown"), healthToneFromStatus(websocket.status)) +
          renderMetric("Continuity Oversight", safeText(runtimeGovernor.status, "unknown"), healthToneFromStatus(runtimeGovernor.status)) +
        '</div>',
        "overview"
      ),

      renderPanelBlock(
        "Live Ride Operations",
        "Live trip states, transition visibility, and continuity-protected history.",
        '<div class="grid-3">' +
          renderMetric("Requested", safeText(activeStates.REQUESTED, "0")) +
          renderMetric("Assigned", safeText(activeStates.ASSIGNED, "0")) +
          renderMetric("Accepted", safeText(activeStates.ACCEPTED, "0")) +
          renderMetric("En Route", safeText(activeStates.EN_ROUTE, "0")) +
          renderMetric("In Progress", safeText(activeStates.IN_PROGRESS, "0")) +
          renderMetric("Completed", safeText(activeStates.COMPLETED, "0")) +
        '</div>' +
        '<div class="divider"></div>' +
        renderSimpleBars([
          { label: "Requested", value: safeNumber(activeStates.REQUESTED, 0), note: "lifecycle state count" },
          { label: "In Progress", value: safeNumber(activeStates.IN_PROGRESS, 0), note: "lifecycle state count" },
          { label: "Completed", value: safeNumber(activeStates.COMPLETED, 0), note: "lifecycle state count" }
        ]),
        "lifecycle-monitor"
      ),

      renderPanelBlock(
        "Driver/Provider Availability",
        "Read-safe readiness summaries for operational coordination.",
        '<div class="grid-4">' +
          renderMetric("Drivers Available", safeText(phase17.driverStates.available, "0")) +
          renderMetric("Drivers Assigned", safeText(phase17.driverStates.assigned, "0")) +
          renderMetric("Drivers Paused", safeText(phase17.driverStates.paused, "0")) +
          renderMetric("Providers Active", safeText(phase17.providerStates.active, "0")) +
          renderMetric("Providers Pending", safeText(phase17.providerStates.pending, "0")) +
          renderMetric("Providers Offline", safeText(phase17.providerStates.offline, "0")) +
          renderMetric("Provider Overloaded", safeText(phase17.providerStates.overloaded, "0")) +
          renderMetric("Provider Summary", phase17.providerReady) +
        '</div>',
        "readiness"
      ),

      renderPanelBlock(
        "Incident and Recovery Timeline",
        "Chronological incident handling, assignment balancing, and activity feed visibility.",
        '<div class="grid-2">' +
          '<div class="tile"><h4>Workflow Timeline</h4>' + renderRecentEvents((phase17?.workflowTimeline ?? []).map(function (row) {
            return {
              level: "info",
              subsystem: "workflow",
              event: safeText(row.status || row.event_type, "unknown"),
              timestamp: safeText(row.updated_at || row.timestamp, ""),
              details: { workflow_name: row.workflow_name, ride_id: row.ride_id, sequence: row.sequence_number }
            };
          }), 8) + '</div>' +
          '<div class="tile"><h4>Activity Feed Preview</h4>' + renderRecentEvents((liveActivityFeed.length > 0 ? liveActivityFeed : (phase17.eventPreview || [])).map(function (row) {
            return {
              level: "info",
              subsystem: "event_stream",
              event: safeText(row.action || row.event_type || row.status, "event"),
              timestamp: safeText(row.created_at || row.emitted_at || row.timestamp || row.updated_at, ""),
              details: { sequence: row.sequence || row.sequence_number, ride_id: row.ride_id, driver_id: row.driver_id }
            };
          }), 8) + '</div>' +
        '</div>' +
        '<div class="divider"></div>' +
        renderNoticeList([
          "Activity feed is continuity protected and oversight-aware.",
          "Escalations move into supervisor clearance when continuity is at risk.",
          "Timeline rows remain read-only until explicitly supervised upstream."
        ]),
        "timeline"
      ),

      renderCorrelationPanel(phase17),
      renderComplianceOverviewPanel(phase17),
      renderExpirationQueuePanel(phase17),
      renderApprovalQueuePanel(phase17),
      renderComplianceTimelinePanel(phase17),
      renderEvidenceChainViewerPanel(phase17),
      renderDocumentLineageViewerPanel(phase17),
      renderSupervisorReviewQueuePanel(phase17),
      renderRegulatoryExportBuilderPanel(phase17),
      renderSignedAccessMonitorPanel(phase17),
      renderRetentionStatusDashboardPanel(phase17),
      renderSupervisorTaskInboxPanel(phase17),
      renderEscalationQueuePanel(phase17),
      renderAssignmentTimelinePanel(phase17),
      renderOperationalNotificationsPanel(phase17),
      renderHandoffTrackerPanel(phase17),
      renderQueueHealthDashboardPanel(phase17),

      renderPanelBlock(
        "Operational Friction Signals",
        "Dispatch disruption indicators, continuity checkpoints, and supervisor-owned intervention triggers.",
        '<div class="grid-3">' +
          renderMetric("Delayed Operations", String(delayedOperations)) +
          renderMetric("Continuity Checkpoint", "active") +
          renderMetric("Audit Chain", "compatible") +
          renderMetric("Live Update Safe", "yes") +
          renderMetric("Supervisor Warnings", String(countEventsByLevel(events, "warning"))) +
          renderMetric("Supervisor Errors", String(countEventsByLevel(events, "error"))) +
        '</div>' +
        renderNoticeList(buildSystemNotices()),
        "alerts"
      ),

      renderPanelBlock(
        "Operational Decision Support",
        "Read-only assistant summary for active transports, delay reviews, and coordination bottlenecks.",
        '<div class="grid-2">' +
          '<div class="tile"><h4>Active Ride Summaries</h4><p>Phase 17 awareness remains preview-only and supervision-gated.</p><p class="muted">Assistant signals: ' + escapeHtml(String(phase17.assistantSignals)) + '</p></div>' +
          '<div class="tile"><h4>Operational Recommendations</h4><p>Suggested actions are advisory only and do not trigger execution.</p><p class="muted">Supervisor intervention is required before any field-facing change.</p></div>' +
        '</div>' +
        '<div class="divider"></div>' +
        renderSimpleBars([
          { label: "AI Signals", value: phase17.assistantSignals, note: "assistant-related operations visibility" },
          { label: "Warnings", value: countEventsByLevel(events, "warning"), note: "supervisory warning events" },
          { label: "Errors", value: countEventsByLevel(events, "error"), note: "supervisory error events" }
        ]),
        "ai-awareness"
      ),

      renderAssistantRecommendationsPanel(phase17),

      renderCommandCenterMapPreview(phase17),

      renderCommandCenterSafePreview(phase17),

      renderPanelBlock(
        "Command Stability Snapshot",
        "Supervision and transport-readiness snapshot for live command operations.",
        '<div class="grid-4">' +
          renderMetric("Supervision", safeText(supervision.supervision_status, "unknown"), healthToneFromStatus(supervision.supervision_status)) +
          renderMetric("Stability Classification", safeText(supervision.health_classification, "unknown"), healthToneFromStatus(supervision.health_classification)) +
          renderMetric("Uptime", phase17.uptimeText) +
          renderMetric("Request Throughput", phase17.throughput) +
          renderMetric("Command Posture", safeText(supervision.runtime_mode, "unknown").replace(/runtime/gi, "coordination")) +
          renderMetric("Memory Continuity", safeText(phase17.memory.status, "unknown")) +
          renderMetric("Validation Source", safeText(phase17.validation.source, "unknown")) +
          renderMetric("Field Coordination Status", safeText(websocket.status, "unknown"), healthToneFromStatus(websocket.status)) +
        '</div>',
        "supervision-status"
      ),

      renderPanelBlock(
        "Protected Endpoint Status and Navigation",
        "Command center route aliases and protected API mirror status.",
        renderQuickLinks([
          { href: "/app/dispatch", title: "Dispatch", description: "Operational command center surface.", note: "baseline" },
          { href: "/app/trips", title: "Trips", description: "Activity feed and workflow timeline view.", note: "read-only" },
          { href: "/app/mobile", title: "Mobile Apps", description: "Cross-surface mobile ecosystem routing.", note: "read-only" },
          { href: "/app/alerts", title: "Alerts", description: "Operational alerts and audit continuity.", note: "read-only" },
          { href: "/app/analytics", title: "Analytics", description: "Operational trend and performance analysis.", note: "read-only" }
        ]) + '<div class="divider"></div>' + renderCommandCenterProtectedStatus(),
        "protected-status"
      )
    ].join("");
  }

  function renderOperationsTimeline() {
    var phase17 = getPhase17Context();
    return [
      renderEnhancedOperationalTimeline(
        "Workflow Timeline View",
        "Workflow history with priority labels, role associations, timestamp grouping, and advisory markers.",
        unifiedTimelineItems(phase17),
        12
      ),
      renderPanelBlock(
        "Audit-Compatible Timeline Controls",
        "Preview-only controls and integrity metadata for audit-compatible viewing.",
        '<div class="grid-3">' +
          renderMetric("Replay Protection", "active") +
          renderMetric("Audit Chain", "compatible") +
          renderMetric("Live Update Safe", "yes") +
        '</div>' +
        renderNoticeList([
          "Timeline entries are read-only and continuity protected.",
          "No workflow changes are exposed from this surface.",
          "Confirmation-gated execution remains upstream only."
        ]),
        "timeline-controls"
      )
    ].join("");
  }

  function renderRides() {
    return renderOperationsCommandCenter();
  }

  function renderDispatcherOperationsWorkspace() {
    var live = safeObject(state.liveWorkflow);
    var workspaceState = safeObject(state.dispatcherWorkspace);
    var patientDraft = safeObject(workspaceState.patientDraft);
    var proof = safeObject(workspaceState.proof);
    var rides = filterActiveOperationalRides(Array.isArray(live.rides) ? live.rides : []);
    var providers = Array.isArray(live.providers) ? live.providers : [];
    var drivers = Array.isArray(live.drivers) ? live.drivers : [];
    var customerRequests = filterActiveCustomerRequests(
      Array.isArray(live.customerRequests) ? live.customerRequests : []
    );
    var availableDrivers = drivers.filter(function (driver) {
      var status = safeText(driver.status || driver.availability_state, "").toLowerCase();
      return status === "available" && driver.is_active !== false;
    });

    var dispatcherMessages = Array.isArray(workspaceState.messages) ? workspaceState.messages : [];
    var feedbackRows = dispatcherMessages.slice(0, 10).map(function (entry) {
      var tone = safeText(entry.level, "info").toLowerCase() === "success" ? "badge-good" : "badge-bad";
      var detail = safeText(entry.detail, "");
      return '<li><span class="badge ' + tone + '">' + escapeHtml(safeText(entry.level, "info")) + '</span> <strong>' + escapeHtml(safeText(entry.message, "Action result")) + '</strong>' + (detail ? '<br><span class="muted">' + escapeHtml(detail) + '</span>' : '') + '</li>';
    }).join("");
    if (!feedbackRows) {
      feedbackRows = '<li class="muted">No action results yet.</li>';
    }

    var providerOptions = providers.map(function (provider) {
      var providerId = safeText(provider.id, "");
      return '<option value="' + escapeHtml(providerId) + '">' + escapeHtml(safeText(provider.name, providerId)) + ' (' + escapeHtml(providerId) + ')</option>';
    }).join("");

    var requestOptions = customerRequests.slice(0, 150).map(function (request) {
      var requestId = safeText(request.id, "");
      return '<option value="' + escapeHtml(requestId) + '">' + escapeHtml(safeText(request.rider_name, "rider")) + ' - ' + escapeHtml(requestId) + '</option>';
    }).join("");

    var rideOptions = rides.slice(0, 150).map(function (ride) {
      var rideId = safeText(ride.id, "");
      return '<option value="' + escapeHtml(rideId) + '">' + escapeHtml(safeText(ride.passenger_name, "passenger")) + ' [' + escapeHtml(safeText(ride.status, "unknown")) + '] - ' + escapeHtml(rideId) + '</option>';
    }).join("");

    var workflowDriverOptions = drivers.slice(0, 200).map(function (driver) {
      var driverId = safeText(driver.id, "");
      var label = safeText(driver.name, driverId);
      return '<option value="' + escapeHtml(driverId) + '">' + escapeHtml(label) + ' (' + escapeHtml(driverId) + ')</option>';
    }).join("");

    var riderRows = customerRequests.slice(0, 100).map(function (request) {
      return '<tr><td>' + escapeHtml(safeText(request.id, "")) + '</td><td>' + escapeHtml(safeText(request.rider_name, "")) + '</td><td>' + escapeHtml(safeText(request.rider_phone, "")) + '</td><td>' + escapeHtml(safeText(request.dispatch_status, "pending")) + '</td><td>' + escapeHtml(safeText(request.ride_id, "n/a")) + '</td></tr>';
    }).join("");
    if (!riderRows) {
      riderRows = '<tr><td colspan="5" class="muted">No riders found.</td></tr>';
    }

    var driverRows = drivers.slice(0, 100).map(function (driver) {
      return '<tr><td>' + escapeHtml(safeText(driver.id, "")) + '</td><td>' + escapeHtml(safeText(driver.name, "")) + '</td><td>' + escapeHtml(safeText(driver.phone, "")) + '</td><td>' + escapeHtml(safeText(driver.status || driver.availability_state, "")) + '</td><td>' + escapeHtml(safeText(driver.vehicle_plate, "")) + '</td></tr>';
    }).join("");
    if (!driverRows) {
      driverRows = '<tr><td colspan="5" class="muted">No drivers found.</td></tr>';
    }

    var providerRows = providers.slice(0, 100).map(function (provider) {
      return '<tr><td>' + escapeHtml(safeText(provider.id, "")) + '</td><td>' + escapeHtml(safeText(provider.name, "")) + '</td><td>' + escapeHtml(safeText(provider.phone, "")) + '</td><td>' + escapeHtml(safeText(provider.service_type, "")) + '</td></tr>';
    }).join("");
    if (!providerRows) {
      providerRows = '<tr><td colspan="4" class="muted">No providers found.</td></tr>';
    }

    var rideRows = rides.slice(0, 120).map(function (ride) {
      return '<tr><td>' + escapeHtml(safeText(ride.id, "")) + '</td><td>' + escapeHtml(safeText(ride.passenger_name, "")) + '</td><td>' + escapeHtml(safeText(ride.status, "")) + '</td><td>' + escapeHtml(safeText(ride.driver_id, "unassigned")) + '</td><td>' + escapeHtml(safeText(ride.provider_id, "")) + '</td><td>' + escapeHtml(safeText(ride.pickup_address, "")) + '</td><td>' + escapeHtml(safeText(ride.dropoff_address, "")) + '</td></tr>';
    }).join("");
    if (!rideRows) {
      rideRows = '<tr><td colspan="7" class="muted">No rides found.</td></tr>';
    }

    return [
      renderPanelBlock(
        "Amicor Operations Control Center",
        "Create records, execute live ride workflow, and verify backend/UI proof in one screen.",
        '<article class="tile" style="margin-bottom:12px"><h4>Action Results</h4><ul class="list" id="dispatcher-action-results">' + feedbackRows + '</ul></article>' +
        '<div class="grid-2">' +
          '<article class="tile"><h4>1. Create Records</h4>' +
            '<label class="muted">Rider Name<input id="dispatcher-patient-name" type="text" value="' + escapeHtml(safeText(patientDraft.name, "")) + '" oninput="window._amiUpdateDispatcherPatientDraft(\'name\', this.value)" style="width:100%;margin-top:6px;padding:10px;border-radius:10px;border:1px solid rgba(15,23,42,0.14);background:#fff"></label>' +
            '<label class="muted">Rider Phone<input id="dispatcher-patient-phone" type="text" value="' + escapeHtml(safeText(patientDraft.phone, "")) + '" placeholder="+15550001111" oninput="window._amiUpdateDispatcherPatientDraft(\'phone\', this.value)" style="width:100%;margin-top:6px;padding:10px;border-radius:10px;border:1px solid rgba(15,23,42,0.14);background:#fff"></label>' +
            '<label class="muted">Pickup<input id="dispatcher-patient-pickup" type="text" value="' + escapeHtml(safeText(patientDraft.pickup, "")) + '" oninput="window._amiUpdateDispatcherPatientDraft(\'pickup\', this.value)" style="width:100%;margin-top:6px;padding:10px;border-radius:10px;border:1px solid rgba(15,23,42,0.14);background:#fff"></label>' +
            '<label class="muted">Dropoff<input id="dispatcher-patient-dropoff" type="text" value="' + escapeHtml(safeText(patientDraft.dropoff, "")) + '" oninput="window._amiUpdateDispatcherPatientDraft(\'dropoff\', this.value)" style="width:100%;margin-top:6px;padding:10px;border-radius:10px;border:1px solid rgba(15,23,42,0.14);background:#fff"></label>' +
            '<button class="btn-action" style="margin-top:10px" onclick="window._amiHandleDispatcherCreatePatient()">Create Rider</button>' +
            '<div class="divider"></div>' +
            '<label class="muted">Driver Name<input id="dispatcher-driver-name" type="text" style="width:100%;margin-top:6px;padding:10px;border-radius:10px;border:1px solid rgba(15,23,42,0.14);background:#fff"></label>' +
            '<label class="muted">Driver Phone<input id="dispatcher-driver-phone" type="text" placeholder="+15550001111" style="width:100%;margin-top:6px;padding:10px;border-radius:10px;border:1px solid rgba(15,23,42,0.14);background:#fff"></label>' +
            '<label class="muted">Vehicle Type<input id="dispatcher-driver-vehicle-type" type="text" value="medical_van" style="width:100%;margin-top:6px;padding:10px;border-radius:10px;border:1px solid rgba(15,23,42,0.14);background:#fff"></label>' +
            '<label class="muted">Vehicle Plate<input id="dispatcher-driver-vehicle-plate" type="text" style="width:100%;margin-top:6px;padding:10px;border-radius:10px;border:1px solid rgba(15,23,42,0.14);background:#fff"></label>' +
            '<button class="btn-action" style="margin-top:10px" onclick="window._amiHandleDispatcherCreateDriver()">Create Driver</button>' +
          '</article>' +
          '<article class="tile"><h4>Create Provider & Ride</h4>' +
            '<label class="muted">Provider Name<input id="dispatcher-provider-name" type="text" style="width:100%;margin-top:6px;padding:10px;border-radius:10px;border:1px solid rgba(15,23,42,0.14);background:#fff"></label>' +
            '<label class="muted">Provider Address<input id="dispatcher-provider-address" type="text" value="Main Clinic" style="width:100%;margin-top:6px;padding:10px;border-radius:10px;border:1px solid rgba(15,23,42,0.14);background:#fff"></label>' +
            '<label class="muted">Provider Phone<input id="dispatcher-provider-phone" type="text" placeholder="+15550002222" style="width:100%;margin-top:6px;padding:10px;border-radius:10px;border:1px solid rgba(15,23,42,0.14);background:#fff"></label>' +
            '<label class="muted">Service Type<input id="dispatcher-provider-service-type" type="text" value="healthcare_transport" style="width:100%;margin-top:6px;padding:10px;border-radius:10px;border:1px solid rgba(15,23,42,0.14);background:#fff"></label>' +
            '<button class="btn-action" style="margin-top:10px" onclick="window._amiHandleDispatcherCreateProvider()">Create Provider</button>' +
            '<div class="divider"></div>' +
            '<label class="muted">Rider Request<select id="dispatcher-ride-patient-request" style="width:100%;margin-top:6px;padding:10px;border-radius:10px;border:1px solid rgba(15,23,42,0.14);background:#fff"><option value="">Select Rider Request</option>' + requestOptions + '</select></label>' +
            '<button class="btn-action" style="margin-top:8px" onclick="window._amiHandleDispatcherUsePatientRequest()">Use Selected Rider</button>' +
            '<label class="muted">Passenger Name<input id="dispatcher-ride-passenger" type="text" style="width:100%;margin-top:6px;padding:10px;border-radius:10px;border:1px solid rgba(15,23,42,0.14);background:#fff"></label>' +
            '<label class="muted">Passenger Phone<input id="dispatcher-ride-phone" type="text" placeholder="+15550001111" style="width:100%;margin-top:6px;padding:10px;border-radius:10px;border:1px solid rgba(15,23,42,0.14);background:#fff"></label>' +
            '<label class="muted">Pickup<input id="dispatcher-ride-pickup" type="text" style="width:100%;margin-top:6px;padding:10px;border-radius:10px;border:1px solid rgba(15,23,42,0.14);background:#fff"></label>' +
            '<label class="muted">Dropoff<input id="dispatcher-ride-dropoff" type="text" style="width:100%;margin-top:6px;padding:10px;border-radius:10px;border:1px solid rgba(15,23,42,0.14);background:#fff"></label>' +
            '<label class="muted">Service Type<input id="dispatcher-ride-service" type="text" value="healthcare_transport" style="width:100%;margin-top:6px;padding:10px;border-radius:10px;border:1px solid rgba(15,23,42,0.14);background:#fff"></label>' +
            '<label class="muted">Provider<select id="dispatcher-ride-provider" style="width:100%;margin-top:6px;padding:10px;border-radius:10px;border:1px solid rgba(15,23,42,0.14);background:#fff"><option value="">Select Provider</option>' + providerOptions + '</select></label>' +
            '<button class="btn-action" style="margin-top:10px" onclick="window._amiHandleDispatcherCreateRide()">Create Ride Request</button>' +
          '</article>' +
        '</div>' +
        '<div class="divider"></div>' +
        '<article class="tile"><h4>3. Ride Workflow</h4>' +
          '<div class="grid-2">' +
            '<label class="muted">Ride<select id="dispatcher-workflow-ride-id" style="width:100%;margin-top:6px;padding:10px;border-radius:10px;border:1px solid rgba(15,23,42,0.14);background:#fff"><option value="">Select Ride</option>' + rideOptions + '</select></label>' +
            '<label class="muted">Driver<select id="dispatcher-workflow-driver-id" style="width:100%;margin-top:6px;padding:10px;border-radius:10px;border:1px solid rgba(15,23,42,0.14);background:#fff"><option value="">Select Driver</option>' + workflowDriverOptions + '</select></label>' +
          '</div>' +
          '<div style="display:flex;flex-wrap:wrap;gap:8px;margin-top:10px">' +
            '<button class="btn-action" onclick="window._amiHandleWorkflowAssignDriver()">Assign Driver</button>' +
            '<button class="btn-action" onclick="window._amiHandleWorkflowDriverAccept()">Driver Accepts</button>' +
            '<button class="btn-action" onclick="window._amiHandleWorkflowDriverArrived()">Driver Arrives</button>' +
            '<button class="btn-action" onclick="window._amiHandleWorkflowDriverPickup()">Driver Picks Up</button>' +
            '<button class="btn-action" onclick="window._amiHandleWorkflowDriverComplete()">Driver Completes Trip</button>' +
            '<button class="btn-action" onclick="window._amiHandleWorkflowCreateBilling()">Create Billing</button>' +
          '</div>' +
        '</article>' +
        '<div class="divider"></div>' +
        '<article class="tile"><h4>4. Proof Panel</h4>' +
          '<div class="grid-4">' +
            renderMetric("Last Action", safeText(proof.last_action, "none")) +
            renderMetric("API Status", safeText(proof.api_status, "idle"), safeText(proof.api_status, "").toLowerCase() === "ok" ? "good" : "warn") +
            renderMetric("Database Record ID", safeText(proof.db_record_id, "n/a")) +
            renderMetric("UI Updated", safeText(proof.ui_updated, "no"), safeText(proof.ui_updated, "").toLowerCase() === "yes" ? "good" : "warn") +
          '</div>' +
        '</article>',
        "operations-control-center"
      ),
      renderPanelBlock(
        "2. Live Operations",
        "Riders, drivers, providers, and rides currently returned by backend APIs.",
        '<div class="grid-2">' +
          '<article class="tile"><h4>Riders List</h4><div class="table-wrap"><table class="ops-table"><thead><tr><th>Request ID</th><th>Name</th><th>Phone</th><th>Status</th><th>Ride ID</th></tr></thead><tbody>' + riderRows + '</tbody></table></div></article>' +
          '<article class="tile"><h4>Drivers List</h4><div class="table-wrap"><table class="ops-table"><thead><tr><th>Driver ID</th><th>Name</th><th>Phone</th><th>Status</th><th>Plate</th></tr></thead><tbody>' + driverRows + '</tbody></table></div></article>' +
          '<article class="tile"><h4>Providers List</h4><div class="table-wrap"><table class="ops-table"><thead><tr><th>Provider ID</th><th>Name</th><th>Phone</th><th>Service Type</th></tr></thead><tbody>' + providerRows + '</tbody></table></div></article>' +
          '<article class="tile"><h4>Rides List</h4><div class="table-wrap"><table class="ops-table"><thead><tr><th>Ride ID</th><th>Passenger</th><th>Status</th><th>Driver</th><th>Provider</th><th>Pickup</th><th>Dropoff</th></tr></thead><tbody>' + rideRows + '</tbody></table></div></article>' +
        '</div>',
        "operations-live-lists"
      )
    ].join("");
  }

  function renderDispatch() {
    if (state.role === "dispatcher" || state.role === "supervisor" || state.role === "admin") return renderDispatcherOperationsWorkspace();
    return renderOperationsCommandCenter();
  }

  function renderTrips() {
    var phase17 = getPhase17Context();
    if (state.role === "medical_coordinator") {
      return renderMedicalCoordinatorDashboard(phase17);
    }
    if (state.role === "supervisor") {
      return renderSupervisorDashboard(phase17);
    }
    if (state.role === "compliance_officer") {
      return renderComplianceOfficerDashboard(phase17);
    }
    if (state.role === "driver_support") {
      return renderDriverSupportDashboard(phase17);
    }
    var timeline = unifiedTimelineItems(phase17);
    var activeTrips = filterActiveOperationalRides(
      Array.isArray((safeObject(state.liveWorkflow)).rides) ? state.liveWorkflow.rides : []
    );
    var activeTripRows = activeTrips.length
      ? activeTrips.slice(0, 30).map(function (ride) {
          return '<tr><td>' + escapeHtml(safeText(ride.passenger_name, shortOperationalId(ride.id, "ride"))) +
            '</td><td>' + escapeHtml(safeText(ride.lifecycle_state || ride.status, "active")) +
            '</td><td>' + escapeHtml(safeText(ride.pickup_address, "pickup")) +
            '</td><td>' + escapeHtml(safeText(ride.dropoff_address, "dropoff")) +
            '</td></tr>';
        }).join("")
      : '<tr><td colspan="4" class="muted">No active trips. Completed rides are in History/Billing.</td></tr>';
    return [
      renderPanelBlock(
        "Active Trips",
        "Waiting dispatch and in-progress rides only.",
        '<div class="table-wrap"><table class="ops-table"><thead><tr><th>Rider</th><th>Status</th><th>Pickup</th><th>Dropoff</th></tr></thead><tbody>' +
          activeTripRows +
        '</tbody></table></div>',
        "active-trips"
      ),
      renderPanelBlock(
        "Trip Lifecycle Monitor",
        "End-to-end trip stages from request through completion and settlement.",
        '<div class="grid-4">' +
          renderMetric("Requested", safeText((phase17.lifecycle || {}).REQUESTED, "0")) +
          renderMetric("Assigned", safeText((phase17.lifecycle || {}).ASSIGNED, "0")) +
          renderMetric("In Progress", safeText((phase17.lifecycle || {}).IN_PROGRESS, "0")) +
          renderMetric("Completed", safeText((phase17.lifecycle || {}).COMPLETED, "0")) +
        '</div>' +
        '<div class="divider"></div>' +
        renderSimpleBars([
          { label: "Requested", value: safeNumber((phase17.lifecycle || {}).REQUESTED, 0), note: "trip intake" },
          { label: "In Progress", value: safeNumber((phase17.lifecycle || {}).IN_PROGRESS, 0), note: "active trips" },
          { label: "Completed", value: safeNumber((phase17.lifecycle || {}).COMPLETED, 0), note: "closed trips" }
        ]),
        "trips"
      ),
      renderEnhancedOperationalTimeline(
        "Trip Timeline",
        "Chronological dispatch events, state transitions, and supervisory annotations.",
        timeline,
        14
      )
    ].join("");
  }

  function renderRiderDedicatedSurface() {
    var phase17 = getPhase17Context();
    var slice = buildRoleHydrationSlice("rider", phase17);
    return '<div class="rider-mobile-page">' + renderRiderAppExperience(slice) + "</div>";
  }

  function renderRidersRoute() {
    return renderRiderDedicatedSurface();
  }

  function renderVehicles() {
    var events = Array.isArray((state.supervision || {}).recent_events) ? state.supervision.recent_events : [];
    var vehicles = Array.isArray((safeObject(state.liveWorkflow)).vehicles)
      ? state.liveWorkflow.vehicles
      : [];
    var activeVehicles = vehicles.filter(function (vehicle) {
      return vehicle && vehicle.is_active !== false;
    });
    var tableRows = activeVehicles.length
      ? activeVehicles.slice(0, 40).map(function (vehicle) {
          return '<tr><td>' + escapeHtml(safeText(vehicle.vehicle_plate || vehicle.plate || vehicle.id, "vehicle")) +
            '</td><td>' + escapeHtml(safeText(vehicle.vehicle_type || vehicle.type, "transport")) +
            '</td><td>' + escapeHtml(safeText(vehicle.status, vehicle.is_active === false ? "inactive" : "operational")) +
            '</td><td>' + escapeHtml(safeText(vehicle.availability || vehicle.status, "available")) +
            '</td></tr>';
        }).join("")
      : '<tr><td colspan="4" class="muted">No active vehicles loaded from backend.</td></tr>';
    return renderPanelBlock(
      "Fleet Vehicles",
      "Live vehicle readiness from backend — no demo placeholders.",
      '<div class="grid-4">' +
        renderMetric("Vehicles Active", String(activeVehicles.length)) +
        renderMetric("Vehicle Signals", String(countEventsByKeyword(events, "vehicle"))) +
        renderMetric("Maintenance Signals", String(countEventsByKeyword(events, "maintenance"))) +
        renderMetric("Fleet Posture", safeText((state.supervision || {}).supervision_status, "unknown")) +
      '</div>' +
      '<div class="divider"></div>' +
      '<div class="table-wrap">' +
      '<table class="ops-table"><thead><tr><th>Vehicle</th><th>Type</th><th>Status</th><th>Availability</th></tr></thead><tbody>' +
      tableRows +
      '</tbody></table>' +
      '</div>',
      "vehicles"
    );
  }

  function renderBilling() {
    var revenue = state.revenueWorkflow && typeof state.revenueWorkflow === "object" ? state.revenueWorkflow : null;
    var kpis = revenue && revenue.kpis ? revenue.kpis : {};
    var handoffs = dedupeBillingHandoffsByRideId(
      Array.isArray(state.liveWorkflow && state.liveWorkflow.billingHandoffs)
        ? state.liveWorkflow.billingHandoffs
        : []
    );
    var tripDocuments = Array.isArray(state.liveWorkflow && state.liveWorkflow.tripDocuments)
      ? state.liveWorkflow.tripDocuments
      : [];
    var rides = Array.isArray(state.liveWorkflow && state.liveWorkflow.rides) ? state.liveWorkflow.rides : [];
    var adminRevenue = state.adminRevenue && typeof state.adminRevenue === "object" ? state.adminRevenue : null;

    // Billing handoffs are the single source of truth for completed/billable trips.
    var completedRows = handoffs.map(function (row) {
      var rideId = safeText(row && row.ride_id, "");
      var matchedRide = rides.find(function (ride) {
        return safeText(ride && ride.id, "") === rideId;
      }) || {};
      return {
        id: rideId,
        passenger_name: safeText(
          (row && row.passenger_name) || matchedRide.passenger_name,
          "Passenger"
        ),
        fare_amount: safeNumber(row && row.fare_amount, 0),
        driver_pay: safeNumber(row && row.driver_pay, 0),
        platform_revenue: safeNumber(row && row.platform_revenue, 0),
        billing_status: safeText(row && row.billing_status, "ready"),
        payment_transaction_id: safeText(row && row.payment_transaction_id, ""),
        payout_id: safeText(row && row.payout_id, ""),
        completed_at: safeText(row && row.completed_at, ""),
        lifecycle_state: "completed",
        status: "completed"
      };
    });

    var completedTrips = adminRevenue && adminRevenue.completed_trip_count != null
      ? String(adminRevenue.completed_trip_count)
      : String(completedRows.length);
    var platformRevenue = adminRevenue && adminRevenue.platform_revenue_total_usd != null
      ? ("$" + Number(adminRevenue.platform_revenue_total_usd).toFixed(2))
      : ("$" + completedRows.reduce(function (sum, row) { return sum + safeNumber(row.platform_revenue, 0); }, 0).toFixed(2));
    var rideRevenue = adminRevenue && adminRevenue.ride_revenue_total_usd != null
      ? ("$" + Number(adminRevenue.ride_revenue_total_usd).toFixed(2))
      : ("$" + completedRows.reduce(function (sum, row) { return sum + safeNumber(row.fare_amount, 0); }, 0).toFixed(2));
    var driverPayoutTotal = adminRevenue && adminRevenue.driver_payout_total_usd != null
      ? ("$" + Number(adminRevenue.driver_payout_total_usd).toFixed(2))
      : ("$" + completedRows.reduce(function (sum, row) { return sum + safeNumber(row.driver_pay, 0); }, 0).toFixed(2));
    var paymentCount = completedRows.filter(function (row) {
      return !!safeText(row.payment_transaction_id, "");
    }).length;
    var activePipeline = filterActiveOperationalRides(rides).filter(function (ride) {
      return !!safeText(ride.driver_id, "");
    });

    return renderPanelBlock(
      "Billing & Claims",
      "Single source of truth for completed trips: fare, driver payout, platform revenue, payments, and receipts.",
      '<div class="grid-4">' +
        renderMetric("Completed Trips", completedTrips) +
        renderMetric("Billing Handoffs", String(completedRows.length)) +
        renderMetric("Platform Revenue", platformRevenue) +
        renderMetric("Gross Ride Revenue", rideRevenue) +
      '</div>' +
      '<div class="grid-3" style="margin-top:12px">' +
        renderMetric("Driver Payouts", driverPayoutTotal) +
        renderMetric("Payment Records", String(paymentCount)) +
        renderMetric("Trip Documents", String(tripDocuments.length)) +
      '</div>' +
      '<div class="divider"></div>' +
      (activePipeline.length
        ? '<section class="panel"><h4>Active trips (awaiting completion)</h4><table class="data-table"><thead><tr><th>Passenger</th><th>Ride</th><th>Driver</th><th>Status</th><th>Pickup</th></tr></thead><tbody>'
          + activePipeline.slice(0, 20).map(function (ride) {
              return '<tr><td>' + escapeHtml(safeText(ride.passenger_name, "Passenger")) + '</td><td>'
                + escapeHtml(String(ride.id || "").slice(0, 10)) + '</td><td>'
                + escapeHtml(safeText(ride.driver_name || ride.driver_id, "assigned").slice(0, 12)) + '</td><td>'
                + escapeHtml(safeText(ride.lifecycle_state || ride.status, "active")) + '</td><td>'
                + escapeHtml(safeText(ride.pickup_address, "pickup")) + '</td></tr>';
            }).join("")
          + '</tbody></table></section>'
        : '<p class="muted">No active assigned trips in billing pipeline. Assigned rides appear here until trip completion creates a billing handoff.</p>') +
      '<div class="divider"></div>' +
      (completedRows.length
        ? '<section class="panel"><h4>Completed trips (billing ledger)</h4><table class="data-table"><thead><tr><th>Passenger</th><th>Ride</th><th>Fare</th><th>Driver Pay</th><th>Platform</th><th>Payment</th><th>Status</th></tr></thead><tbody>'
          + completedRows.slice(0, 40).map(function (row) {
              return '<tr><td>' + escapeHtml(safeText(row.passenger_name, "Passenger")) + '</td><td>'
                + escapeHtml(String(row.id || "").slice(0, 10)) + '</td><td>$'
                + escapeHtml(safeNumber(row.fare_amount, 0).toFixed(2)) + '</td><td>$'
                + escapeHtml(safeNumber(row.driver_pay, 0).toFixed(2)) + '</td><td>$'
                + escapeHtml(safeNumber(row.platform_revenue, 0).toFixed(2)) + '</td><td>'
                + escapeHtml(shortOperationalId(row.payment_transaction_id, "pending")) + '</td><td>'
                + escapeHtml(safeText(row.billing_status, "ready")) + '</td></tr>';
            }).join("")
          + '</tbody></table></section>'
        : '<p class="muted">No completed billing records yet. Complete a trip to create fare, payout, payment, and handoff rows.</p>') +
      '<div class="divider"></div>' +
      (tripDocuments.length
        ? '<section class="panel"><h4>Trip documents & receipts</h4><table class="data-table"><thead><tr><th>Document</th><th>Type</th><th>Ride</th><th>Reference</th><th>Amount</th><th>Status</th></tr></thead><tbody>'
          + tripDocuments.slice(0, 24).map(function (doc) {
              return '<tr><td>' + escapeHtml(safeText(doc.title || doc.name, "Document")) + '</td><td>'
                + escapeHtml(titleizeWords(safeText(doc.document_type, "document"))) + '</td><td>'
                + escapeHtml(String(safeText(doc.ride_id, "")).slice(0, 10)) + '</td><td>'
                + escapeHtml(safeText(doc.reference, "n/a")) + '</td><td>$'
                + escapeHtml(safeNumber(doc.amount_usd, 0).toFixed(2)) + '</td><td>'
                + escapeHtml(safeText(doc.status, "issued")) + '</td></tr>';
            }).join("")
          + '</tbody></table></section>'
        : '<p class="muted">No trip documents generated yet.</p>') +
      renderQuickLinks([
        { href: "/app/trips", title: "Trip Ledger", description: "Review completed trip records and fare evidence.", note: "live" },
        { href: "/app/analytics", title: "Admin Revenue", description: "Platform and ride revenue totals from financial records.", note: "analytics" },
        { href: "/app/drivers", title: "Driver Earnings", description: "Driver payout totals synchronized from billing completion.", note: "live" }
      ]),
      "billing"
    );
  }

  function renderAnalytics() {
    var phase17 = getPhase17Context();
    var events = phase17.events || [];
    return renderPanelBlock(
      "Operational Analytics",
      "Performance, utilization, and supervision trend intelligence.",
      '<div class="grid-4">' +
        renderMetric("Trip Throughput", phase17.throughput) +
        renderMetric("Active Requests", String(phase17.activeRequests)) +
        renderMetric("Warning Events", String(countEventsByLevel(events, "warning"))) +
        renderMetric("AI Advisory Signals", String(phase17.assistantSignals)) +
      '</div>' +
      '<div class="divider"></div>' +
      renderSimpleBars([
        { label: "Operations", value: safeNumber(phase17.activeRequests, 0), note: "active request pressure" },
        { label: "Warnings", value: countEventsByLevel(events, "warning"), note: "safety watch" },
        { label: "Errors", value: countEventsByLevel(events, "error"), note: "requires review" },
        { label: "AI Signals", value: safeNumber(phase17.assistantSignals, 0), note: "advisory activity" }
      ]),
      "analytics"
    );
  }

  function renderMobile() {
    var phase17 = getPhase17Context();
    return renderDriverMobileExperience(phase17, buildRoleHydrationSlice("driver", phase17));
  }

  function renderSettings() {
    return renderPanelBlock(
      "Platform Settings",
      "Organization, policy, and role-scoped configuration controls.",
      '<div class="grid-3">' +
        renderMetric("Role Profiles", String(Object.keys(ROLE_PROFILE).length)) +
        renderMetric("Route Policies", String(Object.keys(ROLE_ACCESS).length)) +
        renderMetric("Governance Mode", "supervision-first") +
      '</div>' +
      renderNoticeList([
        "All high-risk actions require supervised confirmation.",
        "Role access is applied at route level.",
        "Execution pathways remain disabled in this operational shell."
      ]),
      "settings"
    );
  }

  function renderOperationsMapPreview() {
    return renderCommandCenterMapPreview(getPhase17Context());
  }

  function renderOperationsAlerts() {
    var phase17 = getPhase17Context();
    var supervision = phase17.supervision;
    var websocket = phase17.websocket;
    return [
      renderPanelBlock(
        "Operational Alerts",
        "Supervision state changes, delayed operations, and audit continuity.",
        '<div class="grid-4">' +
          renderMetric("Delayed Operations", String(safeNumber((phase17.alerts || {}).delayed_operations, 0))) +
          renderMetric("Replay Protection", "active") +
          renderMetric("Audit Chain", "active") +
          renderMetric("Live Update Health", safeText(websocket.status, "unknown"), healthToneFromStatus(websocket.status)) +
        '</div>' +
        renderNoticeList(buildSystemNotices()),
        "alerts-view"
      ),
      renderPanelBlock(
        "System Supervision and Protected Endpoints",
        "Protected endpoint posture and governance-safe operational metadata.",
        '<div class="grid-2">' +
          '<div class="tile"><h4>Supervision Status</h4><p>' + escapeHtml(safeText(supervision.supervision_status, "unknown")) + '</p><p class="muted">Execution remains disabled by default.</p></div>' +
          '<div class="tile"><h4>Audit Continuity</h4><p>Timeline events remain audit-compatible and correlation-safe.</p><p class="muted">No unsafe state changes or unsupervised loops are available.</p></div>' +
        '</div>' +
        '<div class="divider"></div>' +
        renderCommandCenterProtectedStatus(),
        "alerts-status"
      )
    ].join("");
  }

  function assistantStateTone(status) {
    var key = String(status || "monitoring").toLowerCase();
    if (key === "responding") return "warn";
    if (key === "supervision-ready") return "good";
    if (key === "idle") return "neutral";
    return "neutral";
  }

  function assistantStateLabel(status) {
    var key = String(status || "monitoring").toLowerCase();
    if (key === "responding") return "responding";
    if (key === "supervision-ready") return "supervision-ready";
    if (key === "idle") return "idle";
    return "monitoring";
  }

  function toolStatusTone(status) {
    var key = String(status || "informational").toLowerCase();
    if (key === "completed") return "good";
    if (key === "failed") return "bad";
    if (key === "pending") return "warn";
    return "neutral";
  }

  function recomputeAssistantRuntimeState() {
    if (state.assistant.isResponding) {
      state.assistant.runtimeState = "responding";
      return;
    }

    if (state.route === "ai-assistant") {
      if (safeText((state.supervision || {}).supervision_status, "unknown") === "healthy") {
        state.assistant.runtimeState = "supervision-ready";
        if ((state.assistant.messages || []).length > 1) {
          state.assistant.runtimeState = "idle";
        }
        return;
      }
      state.assistant.runtimeState = "monitoring";
      return;
    }

    state.assistant.runtimeState = "monitoring";
  }

  function addAssistantMessage(type, title, text) {
    state.assistant.messages.push({
      id: "msg-" + Date.now() + "-" + Math.floor(Math.random() * 1000),
      type: safeText(type, "assistant"),
      title: safeText(title, "Assistant"),
      text: safeText(text, ""),
      timestamp: new Date().toISOString()
    });
    state.assistant.messages = state.assistant.messages.slice(-24);
  }

  function addToolEvent(status, label, detail) {
    state.assistant.toolEvents.push({
      id: "tool-" + Date.now() + "-" + Math.floor(Math.random() * 1000),
      status: safeText(status, "informational"),
      label: safeText(label, "Tool event"),
      detail: safeText(detail, ""),
      timestamp: new Date().toISOString()
    });
    state.assistant.toolEvents = state.assistant.toolEvents.slice(-24);
  }

  function updateToolEventStatus(eventId, nextStatus, nextDetail) {
    state.assistant.toolEvents = state.assistant.toolEvents.map(function (event) {
      if (event.id !== eventId) return event;
      return {
        id: event.id,
        status: safeText(nextStatus, event.status),
        label: event.label,
        detail: safeText(nextDetail, event.detail),
        timestamp: event.timestamp
      };
    });
  }

  function endpointForIntent(intent) {
    var normalized = String(intent || "preview").toLowerCase();
    if (normalized === "simulate") return "/api/assistant/simulate";
    if (normalized === "inspect") return "/api/assistant/inspect";
    return "/api/assistant/preview";
  }

  function evaluateGuardrailPolicy(intent, promptText, role) {
    var normalizedIntent = String(intent || "preview").toLowerCase();
    var normalizedPrompt = String(promptText || "").toLowerCase();
    var normalizedRole = String(role || "admin").toLowerCase();
    var policy = "ALLOWED";
    var reasons = [];

    if (!normalizedPrompt.trim()) {
      policy = "BLOCKED";
      reasons.push("PROMPT_REQUIRED");
    }

    if (/(autonomous|auto-run|background|loop|dispatch now|execute immediately|persist|delete)/.test(normalizedPrompt)) {
      policy = "BLOCKED";
      reasons.push("BLOCKED_AUTONOMOUS_PATTERN");
    }

    if (/(restart|shutdown|deploy|workflow|dispatch)/.test(normalizedPrompt)) {
      if (policy !== "BLOCKED") {
        policy = "REQUIRES_CONFIRMATION";
      }
      reasons.push("SUPERVISION_REQUIRED_ACTION");
    }

    if ((normalizedRole === "provider" || normalizedRole === "driver") && (normalizedIntent === "simulate" || normalizedIntent === "confirm")) {
      if (policy !== "BLOCKED") {
        policy = "REQUIRES_CONFIRMATION";
      }
      reasons.push("ROLE_RESTRICTION_APPLIED");
    }

    if (reasons.length === 0) {
      reasons.push("SAFE_DRY_RUN_PATH");
    }

    return {
      state: policy,
      reasons: reasons
    };
  }

  function signatureForAuditEvent(auditEvent) {
    var seed = [
      safeText(state.assistant.sessionNonce, "nonce"),
      safeText(auditEvent.type, "event"),
      safeText(auditEvent.intent, "n/a"),
      safeText(auditEvent.prompt, ""),
      safeText(auditEvent.timestamp, "")
    ].join("|");
    var hash = 0;
    for (var i = 0; i < seed.length; i += 1) {
      hash = ((hash << 5) - hash) + seed.charCodeAt(i);
      hash |= 0;
    }
    return "sig-" + Math.abs(hash).toString(16);
  }

  function addAuditEvent(type, intent, promptText, detail) {
    var auditEvent = {
      id: "audit-" + Date.now() + "-" + Math.floor(Math.random() * 1000),
      type: safeText(type, "assistant_event"),
      intent: safeText(intent, "n/a"),
      prompt: safeText(promptText, ""),
      detail: safeText(detail, ""),
      timestamp: new Date().toISOString()
    };
    auditEvent.signature = signatureForAuditEvent(auditEvent);
    state.assistant.auditEvents.push(auditEvent);
    state.assistant.auditEvents = state.assistant.auditEvents.slice(-48);
  }

  function addPreviewCardFromResponse(intent, policyState, responsePayload) {
    var payload = normalizePreviewPayload(responsePayload || {});
    var preview = payload.preview_card || {};
    var verification = payload.confirmation_verification || {};
    var securityState = payload.security_state || {};
    var governance = payload.governance || {};
    var tokenExpiresIn = safeNumber(securityState.token_expires_in_seconds, 0);
    var policyVersion = safeText(
      governance.policy_version,
      safeText(securityState.policy_version, safeText(verification.policy_version, "unknown"))
    );
    var correlationId = safeText(
      governance.correlation_id,
      safeText(securityState.correlation_id, safeText(verification.correlation_id, ""))
    );

    state.assistant.securityState = {
      verifiedPreview: Boolean(securityState.verified_preview),
      signedConfirmation: Boolean(securityState.signed_confirmation),
      tokenExpiresInSeconds: tokenExpiresIn,
      dryRunOnly: securityState.dry_run_only !== false,
      executionDisabled: securityState.execution_disabled !== false,
      supervisionEnforced: securityState.supervision_enforced !== false,
      durableVerifiedPreview: securityState.durable_verified_preview === true || governance.durable_verified_preview === true,
      auditChainActive: securityState.audit_chain_active === true || governance.audit_chain_active === true,
      distributedReplayProtection: securityState.distributed_replay_protection === true || governance.distributed_replay_protection === true,
      policyVersion: policyVersion,
      correlationId: correlationId
    };

    state.assistant.previewCards.push({
      id: "preview-" + Date.now() + "-" + Math.floor(Math.random() * 1000),
      intent: safeText(intent, "preview"),
      proposedOperation: safeText(preview.proposed_operation, safeText(intent, "preview")),
      affectedSystems: Array.isArray(preview.affected_systems) ? preview.affected_systems : [],
      supervisionClassification: safeText(preview.supervision_classification, "supervision_protected"),
      runtimeImpact: safeText(preview.runtime_impact, "no_runtime_changes"),
      allowedStatus: safeText(preview.allowed_status, policyState),
      reasonCodes: Array.isArray(preview.reason_codes) ? preview.reason_codes : [],
      endpoint: safeText(payload.endpoint, endpointForIntent(intent)),
      summary: payload.requested_action_summary || {},
      verificationStatus: safeText(verification.status, "UNVERIFIED_PREVIEW"),
      requestHash: safeText(verification.request_hash, ""),
      tokenExpiresInSeconds: tokenExpiresIn,
      policyVersion: policyVersion,
      correlationId: correlationId,
      timestamp: new Date().toISOString()
    });
    state.assistant.previewCards = state.assistant.previewCards.slice(-12);
  }

  async function executeConfirmedIntent(intent, promptText, policy) {
    var normalizedIntent = String(intent || "preview").toLowerCase();
    if (normalizedIntent === "cancel") {
      state.assistant.pendingIntent = null;
      addToolEvent("informational", "Intent canceled", "Confirmation canceled by operator.");
      addAuditEvent("confirmation_canceled", normalizedIntent, promptText, "Pending intent canceled before preview call.");
      addAssistantMessage("assistant", "Assistant", "Intent canceled. No request was made.");
      persistSessionState();
      renderPage();
      return;
    }

    if (normalizedIntent === "confirm") {
      state.assistant.pendingIntent = null;
      addToolEvent("informational", "Confirmation accepted", "Operator accepted a confirmation-only intent. No execution path is available.");
      addAuditEvent("confirmation_accepted", normalizedIntent, promptText, "Confirmation acknowledged with no execution.");
      addAssistantMessage("assistant", "Assistant", "Confirmation recorded. Phase 12 remains dry-run only; no execution occurred.");
      persistSessionState();
      renderPage();
      return;
    }

    var endpoint = endpointForIntent(normalizedIntent);
    state.assistant.isResponding = true;
    addToolEvent("pending", "Workflow request queued", "Preparing " + normalizedIntent + " request via " + endpoint + ".");
    updateToolEventStatus(state.assistant.toolEvents[state.assistant.toolEvents.length - 1].id, "pending", "Awaiting supervised preview response.");
    recomputeAssistantRuntimeState();
    persistSessionState();
    renderPage();

    try {
      var previewPayload = normalizePreviewPayload(await postJson(endpoint, {
        intent: normalizedIntent,
        prompt: promptText,
        role: state.role,
        scope: "assistant-workspace",
        session_id: state.assistant.sessionNonce,
        context: {
          route: state.route,
          session_id: state.assistant.sessionNonce,
          supervision_status: safeText((state.supervision || {}).supervision_status, "unknown"),
          operational_trip_context: safeObject((((state.ops.workspaceActivation || {}).workspace_modules || {}).ai_operational_copilot_context)),
          trip_state_distribution: safeObject(((((state.ops.workspaceActivation || {}).workspace_modules || {}).trip_snapshot || {}).state_distribution))
        }
      }));

      var confirmation = previewPayload.confirmation || {};
      var integrity = previewPayload.integrity || {};
      var signedToken = safeText(confirmation.signed_token, "");

      if (!signedToken) {
        addAuditEvent("blocked_action_attempted", normalizedIntent, promptText, "No signed confirmation token was issued by operations policy.");
        addToolEvent("failed", "Confirmation blocked", "Operations policy prevented signed confirmation token issuance.");
        addAssistantMessage("assistant", "Assistant", "Request was blocked by security policy. No preview approval was completed.");
        state.assistant.pendingIntent = null;
        return;
      }

      addToolEvent("pending", "Signed confirmation issued", "Token generated. Verifying token-bound confirmation now.");

      var verifiedPayload = await postJson("/api/assistant/confirm", {
        token: signedToken,
        intent_id: safeText(confirmation.intent_id, ""),
        action_type: safeText(confirmation.action_type, normalizedIntent),
        session_id: safeText(confirmation.session_id, state.assistant.sessionNonce),
        intent_hash: safeText(integrity.intent_hash, ""),
        preview_payload_hash: safeText(integrity.preview_payload_hash, ""),
        dependency_graph_hash: safeText(integrity.dependency_graph_hash, ""),
        safety_classification_hash: safeText(integrity.safety_classification_hash, ""),
        supervision_classification: normalizeSupervisionClassification(previewPayload.supervision_classification, "supervision_enforced"),
        nonce: safeText(confirmation.nonce, ""),
        correlation_id: safeText(confirmation.correlation_id, ""),
        policy_version: safeText(confirmation.policy_version, "")
      });

      addPreviewCardFromResponse(normalizedIntent, policy.state, verifiedPayload);
      pushExecutionHistory(verifiedPayload.workflow_execution || {});
      addAuditEvent("confirmation_accepted", normalizedIntent, promptText, "Signed confirmation verified with replay-protected preview integrity.");
      addAssistantMessage("assistant", "Assistant Workflow", "Verified review completed with supervisor confirmation and saved operational action records.");
      state.assistant.pendingIntent = null;
      addToolEvent("completed", "Operational action record saved", "Preview approval verified and operational action record saved via /api/assistant/confirm.");
      await safeLogAssistantEvent("workflow", "assistant_execution_confirmed", "success", {
        intent: normalizedIntent,
        correlation_id: safeText((verifiedPayload.workflow_execution || {}).correlation_id, ""),
        execution_id: safeText((verifiedPayload.workflow_execution || {}).execution_id, "")
      }, "");
      await refreshAssistantPersistence();
    } catch (error) {
      state.assistant.pendingIntent = null;
      addToolEvent("failed", "Workflow request failed", "Workflow preview failed: " + safeText(error && error.message, "unknown_error") + ".");
      addAssistantMessage("assistant", "Assistant", "Workflow request ended safely. No operational state change path was triggered.");
      await safeLogAssistantEvent("workflow", "assistant_execution_failed", "failed", { intent: normalizedIntent }, safeText(error && error.message, "unknown_error"));
    } finally {
      state.assistant.isResponding = false;
      recomputeAssistantRuntimeState();
      persistSessionState();
      if (state.route === "ai-assistant") {
        renderPage();
      }
    }
  }

  function renderAssistantMessages(messages) {
    if (!Array.isArray(messages) || messages.length === 0) {
      return '<p class="muted">No local interaction history yet.</p>';
    }

    return '<div class="assistant-message-list">' + messages.slice(-12).map(function (message) {
      var role = safeText(message.type, "assistant");
      var title = normalizePresentationText(message.title || "message");
      var text = normalizePresentationText(message.text || "");
      var timestamp = safeText(message.timestamp, "unknown");
      return '<article class="assistant-message assistant-message-' + escapeHtml(role) + '">' +
        '<header><strong>' + escapeHtml(title) + '</strong><span>' + escapeHtml(timestamp) + '</span></header>' +
        '<p>' + escapeHtml(text) + '</p>' +
        '</article>';
    }).join("") + '</div>';
  }

  function renderToolEvents(events) {
    if (!Array.isArray(events) || events.length === 0) {
      return '<p class="muted">No operational activity events yet.</p>';
    }

    return '<ul class="tool-event-list">' + events.slice(-12).map(function (event) {
      var status = safeText(event.status, "informational");
      var tone = toolStatusTone(status);
      return '<li class="tool-event-item">' +
        '<span class="badge badge-' + tone + '">' + escapeHtml(status) + '</span>' +
        '<div class="tool-event-copy"><strong>' + escapeHtml(normalizePresentationText(event.label || "Tool event")) + '</strong><p>' + escapeHtml(normalizePresentationText(event.detail || "")) + '</p><small>' + escapeHtml(safeText(event.timestamp, "")) + '</small></div>' +
        '</li>';
    }).join("") + '</ul>';
  }

  function renderCollapsiblePanel(panelKey, heading, contentHtml) {
    var collapsed = Boolean((state.assistant.collapsible || {})[panelKey]);
    return '<section class="tile collapsible-panel ' + (collapsed ? "is-collapsed" : "") + '">' +
      '<button type="button" class="collapse-toggle" data-collapse-panel="' + escapeHtml(panelKey) + '">' +
      '<span>' + escapeHtml(heading) + '</span><span class="collapse-indicator">' + (collapsed ? "+" : "-") + '</span>' +
      '</button>' +
      '<div class="collapse-body">' + contentHtml + '</div>' +
      '</section>';
  }

  function renderMemorySummary() {
    var supervision = state.supervision || {};
    var profile = ROLE_PROFILE[state.role] || ROLE_PROFILE.admin;
    var sessionCount = (state.assistant.messages || []).length;
    return '<div class="memory-grid">' +
      '<div class="memory-card"><h5>Operational Session Context</h5><p>' + escapeHtml(String(sessionCount)) + ' local interaction entries retained in session storage.</p></div>' +
      '<div class="memory-card"><h5>Operational Context</h5><p>Command status: ' + escapeHtml(safeText((state.health || {}).backend_status, "unknown")) + ', supervision: ' + escapeHtml(safeText(supervision.supervision_status, "unknown")) + '.</p></div>' +
      '<div class="memory-card"><h5>Role Context</h5><p>' + escapeHtml(profile.context) + '</p></div>' +
      '<div class="memory-card"><h5>Supervision Notes</h5><p>Health classification: ' + escapeHtml(safeText(supervision.health_classification, "unknown")) + '. Operational mode remains monitoring-only.</p></div>' +
      '<div class="memory-card"><h5>Pending Prompt</h5><p>' + escapeHtml(safeText(state.assistant.pendingPrompt, "No pending prompt.")) + '</p></div>' +
      '</div>';
  }

  function pushExecutionHistory(execution) {
    if (!execution || typeof execution !== "object") return;
    var item = normalizeExecutionRecord(execution);
    state.assistant.executionHistory = [item].concat((state.assistant.executionHistory || []).filter(function (entry) {
      return safeText(entry.execution_id, "") !== item.execution_id;
    })).slice(0, 16);
  }

  function renderExecutionHistory(items) {
    if (!Array.isArray(items) || items.length === 0) {
      return '<p class="muted">No operational action records yet.</p>';
    }

    return '<ul class="audit-list">' + items.slice(0, 8).map(function (item) {
      var status = safeText(item.status, "pending");
      return '<li class="audit-item">' +
        '<div><strong>' + escapeHtml(safeText(item.action_type, "preview")) + '</strong><p>Operational action ' + escapeHtml(safeText(item.execution_id, "n/a")) + ' is <span class="badge badge-' + toolStatusTone(status) + '">' + escapeHtml(status) + '</span>.</p><p class="muted">Intent ' + escapeHtml(safeText(item.intent_id, "n/a")) + ' | Correlation ' + escapeHtml(safeText(item.correlation_id, "n/a")) + '</p></div>' +
        '<small>' + escapeHtml(safeText(item.completed_at || item.failed_at || item.started_at || item.queued_at, "unknown")) + '</small>' +
      '</li>';
    }).join("") + '</ul>';
  }

  function renderPersistentMemoryEntries(items) {
    if (!Array.isArray(items) || items.length === 0) {
      return '<p class="muted">No saved operational context entries loaded for this account yet.</p>';
    }
    return '<ul class="audit-list">' + items.slice(0, 8).map(function (item) {
      var content = item.content || {};
      var text = safeText(content.note || content.status || content.intent_id || "memory entry", "memory entry");
      return '<li class="audit-item">' +
        '<div><strong>' + escapeHtml(safeText(item.title, "memory")) + '</strong><p>' + escapeHtml(text) + '</p><p class="muted">Type: ' + escapeHtml(safeText(item.memory_type, "memory")) + ' | Role: ' + escapeHtml(safeText(item.role, "unknown")) + '</p></div>' +
        '<small>' + escapeHtml(safeText(item.created_at, "unknown")) + '</small>' +
      '</li>';
    }).join("") + '</ul>';
  }

  function guardrailTone(policyState) {
    var key = String(policyState || "ALLOWED").toUpperCase();
    if (key === "BLOCKED") return "bad";
    if (key === "REQUIRES_CONFIRMATION") return "warn";
    return "good";
  }

  function renderPreviewCards(cards) {
    if (!Array.isArray(cards) || cards.length === 0) {
      return '<p class="muted">No preview cards yet. Submit a prompt and confirm preview, inspect, or simulate.</p>';
    }

    return '<div class="preview-card-list">' + cards.slice(-6).reverse().map(function (card) {
      var status = safeText(card.allowedStatus, "ALLOWED");
      var reasons = Array.isArray(card.reasonCodes) ? card.reasonCodes : [];
      var systems = Array.isArray(card.affectedSystems) ? card.affectedSystems : [];
      var verifyStatus = safeText(card.verificationStatus, "UNVERIFIED_PREVIEW");
      return '<article class="preview-card">' +
        '<header><strong>' + escapeHtml(safeText(card.proposedOperation, "preview")) + '</strong><span>' + escapeHtml(safeText(card.timestamp, "")) + '</span></header>' +
        '<p><strong>Affected systems:</strong> ' + escapeHtml(systems.join(", ") || "assistant_workspace") + '</p>' +
        '<p><strong>Supervision:</strong> ' + escapeHtml(safeText(card.supervisionClassification, "supervision_protected")) + '</p>' +
        '<p><strong>Operations impact:</strong> ' + escapeHtml(safeText(card.runtimeImpact, "no_runtime_changes")) + '</p>' +
        '<p><strong>Verification:</strong> <span class="badge badge-' + (verifyStatus === "VERIFIED_PREVIEW" ? "good" : "warn") + '">' + escapeHtml(verifyStatus) + '</span></p>' +
        '<p><strong>Status:</strong> <span class="badge badge-' + guardrailTone(status) + '">' + escapeHtml(status) + '</span></p>' +
        '<p><strong>Token expires in:</strong> ' + escapeHtml(String(safeNumber(card.tokenExpiresInSeconds, 0))) + 's</p>' +
        '<p><strong>Policy version:</strong> ' + escapeHtml(safeText(card.policyVersion, "unknown")) + '</p>' +
        '<p><strong>Correlation ID:</strong> ' + escapeHtml(safeText(card.correlationId, "n/a")) + '</p>' +
        '<p><strong>Reason codes:</strong> ' + escapeHtml(reasons.join(", ") || "SAFE_DRY_RUN_PATH") + '</p>' +
        '<p class="muted">Endpoint: ' + escapeHtml(safeText(card.endpoint, "")) + '</p>' +
      '</article>';
    }).join("") + '</div>';
  }

  function renderAuditEvents(events) {
    if (!Array.isArray(events) || events.length === 0) {
      return '<p class="muted">No audit events captured for this session yet.</p>';
    }

    return '<ul class="audit-list">' + events.slice(-12).reverse().map(function (event) {
      return '<li class="audit-item">' +
        '<div><strong>' + escapeHtml(safeText(event.type, "assistant_event")) + '</strong><p>' + escapeHtml(safeText(event.detail, "")) + '</p></div>' +
        '<small>' + escapeHtml(safeText(event.timestamp, "")) + ' | ' + escapeHtml(safeText(event.signature, "sig-missing")) + '</small>' +
      '</li>';
    }).join("") + '</ul>';
  }

  function renderSafetyIndicators() {
    var security = state.assistant.securityState || {};
    var tokenSeconds = Math.max(0, safeNumber(security.tokenExpiresInSeconds, 0));
    var tokenTone = tokenSeconds > 30 ? "good" : tokenSeconds > 0 ? "warn" : "bad";

    return '<div class="safety-indicator-row">' +
      '<span class="badge badge-' + (security.verifiedPreview ? "good" : "warn") + '">VERIFIED PREVIEW</span>' +
      '<span class="badge badge-' + (security.durableVerifiedPreview ? "good" : "warn") + '">DURABLE VERIFIED PREVIEW</span>' +
      '<span class="badge badge-' + (security.signedConfirmation ? "good" : "warn") + '">SIGNED CONFIRMATION</span>' +
      '<span class="badge badge-' + tokenTone + '">TOKEN EXPIRES IN ' + escapeHtml(String(tokenSeconds)) + 's</span>' +
      '<span class="badge badge-' + (security.dryRunOnly ? "good" : "bad") + '">DRY RUN ONLY</span>' +
      '<span class="badge badge-' + (security.executionDisabled ? "good" : "bad") + '">EXECUTION DISABLED</span>' +
      '<span class="badge badge-' + (security.supervisionEnforced ? "good" : "bad") + '">SUPERVISION ENFORCED</span>' +
      '<span class="badge badge-' + (security.auditChainActive ? "good" : "warn") + '">AUDIT CHAIN ACTIVE</span>' +
      '<span class="badge badge-' + (security.distributedReplayProtection ? "good" : "warn") + '">DISTRIBUTED REPLAY PROTECTION</span>' +
      '<span class="badge badge-good">POLICY VERSION ' + escapeHtml(safeText(security.policyVersion, "unknown")) + '</span>' +
      '<span class="badge badge-good">CORRELATION ' + escapeHtml(safeText(security.correlationId, "n/a")) + '</span>' +
    '</div>';
  }

  function renderPendingIntentCard(pendingIntent) {
    if (!pendingIntent) {
      return '<div class="intent-confirmation-panel"><h4>Confirmation Required</h4><p class="muted">Select an intent to prepare a confirmation payload.</p></div>';
    }

    var policy = pendingIntent.policy || { state: "REQUIRES_CONFIRMATION", reasons: ["CONFIRMATION_REQUIRED"] };
    return '<div class="intent-confirmation-panel">' +
      '<h4>Confirmation Required: ' + escapeHtml(safeText(pendingIntent.intent, "preview")) + '</h4>' +
      '<p><strong>Policy:</strong> <span class="badge badge-' + guardrailTone(policy.state) + '">' + escapeHtml(safeText(policy.state, "REQUIRES_CONFIRMATION")) + '</span></p>' +
      '<p><strong>Reason codes:</strong> ' + escapeHtml((policy.reasons || []).join(", ") || "SAFE_DRY_RUN_PATH") + '</p>' +
      '<p><strong>Prompt:</strong> ' + escapeHtml(safeText(pendingIntent.prompt, "")) + '</p>' +
      '<div class="confirmation-actions">' +
        '<button type="button" class="assistant-submit" data-confirm-intent="true" ' + ((policy.state === "BLOCKED" || state.assistant.isResponding) ? "disabled" : "") + '>Verify and Confirm</button>' +
        '<button type="button" class="assistant-submit secondary" data-cancel-intent="true">Cancel</button>' +
      '</div>' +
    '</div>';
  }

  function renderAssistant() {
    var supervision = state.supervision || {};
    var health = state.health || {};
    var events = Array.isArray(supervision.recent_events) ? supervision.recent_events : [];
    var status = safeText(health.backend_status, "unknown");
    var assistantSignals = countEventsByKeyword(events, "assistant") + countEventsByKeyword(events, "ai");
    var runtimeState = assistantStateLabel(state.assistant.runtimeState);
    var runtimeTone = assistantStateTone(runtimeState);
    var draft = safeText(state.assistant.draft, "");
    var isResponding = Boolean(state.assistant.isResponding);
    var activityCount = (state.assistant.messages || []).length;
    var pendingIntent = state.assistant.pendingIntent;
    var currentPolicy = pendingIntent && pendingIntent.policy ? pendingIntent.policy : evaluateGuardrailPolicy("preview", safeText(state.assistant.pendingPrompt, ""), state.role);

    return [
      '<section class="panel assistant-runtime-banner">' +
        '<div class="assistant-runtime-copy">' +
          '<span class="section-eyebrow">controlled interaction layer</span>' +
          '<h3>Assistant operational state: ' + escapeHtml(runtimeState) + '</h3>' +
          '<p>Conversation stays in the current operational session, with supervision-safe monitoring.</p>' +
        '</div>' +
        '<div class="assistant-runtime-pills">' +
          '<span class="badge badge-' + runtimeTone + '">' + escapeHtml(runtimeState) + '</span>' +
          '<span class="badge badge-' + healthToneFromStatus(status) + '">operations ' + escapeHtml(status) + '</span>' +
          '<span class="badge badge-' + healthToneFromStatus(supervision.supervision_status) + '">supervision ' + escapeHtml(safeText(supervision.supervision_status, "unknown")) + '</span>' +
        '</div>' +
      '</section>',

      renderLiveDispatchAssistantPanel(),

      '<section class="panel assistant-workspace-head">' +
        '<div class="assistant-head-row">' +
          '<div><h3>Durable Governance and Operational Foundation</h3><p class="section-subtitle">User-confirmed intents now persist signed governance proofs and safe operational action records with replay protection.</p></div>' +
          '<div class="assistant-head-stats">' +
            renderMetric("Session Messages", String(activityCount)) +
            renderMetric("Tool Signals", String((state.assistant.toolEvents || []).length)) +
            renderMetric("Supervision Events", String(events.length)) +
            renderMetric("Operational Actions", String((state.assistant.executionHistory || []).length)) +
          '</div>' +
        '</div>' +
        renderSafetyIndicators() +
      '</section>',

      renderPanelBlock(
        "Conversation Workspace",
        "Input stays in the current operational session. Intents require explicit confirmation before dry-run review calls.",
        '<div class="assistant-grid">' +
          '<div class="assistant-main">' +
            '<section class="tile conversation-tile">' +
              '<h4>Conversation Input Area</h4>' +
              '<p>Messages remain in the current session. Review calls are supervision-confirmed and read-only.</p>' +
              '<form id="assistant-form" class="assistant-form" novalidate>' +
                '<label for="assistant-input" class="sr-only">Assistant input</label>' +
                '<textarea id="assistant-input" rows="4" maxlength="1200" placeholder="Ask for a status summary, operational explanation, or supervision context...">' + escapeHtml(draft) + '</textarea>' +
                '<div class="assistant-form-actions">' +
                  '<div class="assistant-suggested">' +
                    '<button type="button" class="ghost-chip" data-assistant-prompt="Summarize current operations status and supervision posture.">Status summary</button>' +
                    '<button type="button" class="ghost-chip" data-assistant-prompt="Show current operational governance posture and live update channel status.">Operational posture</button>' +
                    '<button type="button" class="ghost-chip" data-assistant-prompt="List monitoring notes for my role context.">Role notes</button>' +
                  '</div>' +
                  '<button type="submit" class="assistant-submit" ' + (isResponding ? 'disabled' : '') + '>Send</button>' +
                '</div>' +
              '</form>' +
              '<div class="intent-button-row">' +
                '<button type="button" class="ghost-chip intent-chip" data-assistant-intent="preview">preview</button>' +
                '<button type="button" class="ghost-chip intent-chip" data-assistant-intent="inspect">inspect</button>' +
                '<button type="button" class="ghost-chip intent-chip" data-assistant-intent="simulate">simulate</button>' +
                '<button type="button" class="ghost-chip intent-chip" data-assistant-intent="confirm">confirm</button>' +
                '<button type="button" class="ghost-chip intent-chip" data-assistant-intent="cancel">cancel</button>' +
              '</div>' +
              '<div class="guardrail-policy"><strong>Guardrail policy:</strong> <span class="badge badge-' + guardrailTone(currentPolicy.state) + '">' + escapeHtml(currentPolicy.state) + '</span> <span class="muted">' + escapeHtml((currentPolicy.reasons || []).join(", ")) + '</span></div>' +
              renderPendingIntentCard(pendingIntent) +
              (isResponding ? '<div class="assistant-loading"><span class="dot-flash"></span><span>processing supervisor confirmation and operational action records...</span></div>' : '<div class="assistant-loading placeholder-stream">Operational action flow is controlled and supervision-safe.</div>') +
            '</section>' +
            renderCollapsiblePanel("history", "Message History", renderAssistantMessages(state.assistant.messages)) +
            renderCollapsiblePanel("preview", "Assistant Operational Preview Cards", renderPreviewCards(state.assistant.previewCards)) +
            renderCollapsiblePanel("execution", "Operational Action Status", renderExecutionHistory(state.assistant.executionHistory)) +
          '</div>' +
          '<div class="assistant-side">' +
            renderCollapsiblePanel("tools", "Operational Activity Stream", renderToolEvents(state.assistant.toolEvents)) +
            renderCollapsiblePanel("memory", "Operational Session Context", renderMemorySummary()) +
            renderCollapsiblePanel("persistent", "Saved Operational Context", renderPersistentMemoryEntries(state.assistant.memoryEntries)) +
            renderCollapsiblePanel("audit", "Interaction Audit Trail (Session + Operations Chain)", renderAuditEvents(state.assistant.auditEvents)) +
            renderCollapsiblePanel("session", "Session Conversation State", '<div class="grid-2">' +
              renderMetric("Current Role", state.role) +
              renderMetric("Workspace State", runtimeState) +
              renderMetric("Recent Interaction History", String((state.assistant.messages || []).length)) +
              renderMetric("Tool Events", String((state.assistant.toolEvents || []).length)) +
              renderMetric("Preview Cards", String((state.assistant.previewCards || []).length)) +
              renderMetric("Audit Events", String((state.assistant.auditEvents || []).length)) +
              '</div>' +
              '<div class="divider"></div>' +
              '<p class="muted">Session state remains in browser session storage, with operational action and context summaries persisted in operations records.</p>') +
          '</div>' +
        '</div>',
        "workspace"
      ),

      renderPanelBlock(
        "Context Summary Cards",
        "Session state and operational context for the assistant surface.",
        '<div class="grid-3">' +
          renderMetric("Session State", runtimeState) +
          renderMetric("Coordination Mode", safeText(supervision.runtime_mode, "unknown").replace(/runtime/gi, "coordination")) +
          renderMetric("Status Version", safeText(supervision.diagnostics_version, "unknown")) +
          renderMetric("Active Requests", safeText(supervision.active_request_count, "0")) +
          renderMetric("Uptime", safeText(supervision.uptime_human_readable, "unknown")) +
          renderMetric("Context Signals", String(assistantSignals + (state.assistant.messages || []).length)) +
          renderMetric("Guardrail State", safeText(currentPolicy.state, "ALLOWED"), guardrailTone(currentPolicy.state)) +
          renderMetric("Pending Intent", safeText((pendingIntent || {}).intent, "none")) +
          renderMetric("Safety Boundary", "active") +
        '</div>',
        "context"
      ),

      renderPanelBlock(
        "Session State Display",
        "View-only payloads supporting future assistant coordination without direct changes.",
        '<div class="grid-2">' +
          '<div class="tile">' + renderPayloadViewer("Health Snapshot", health, "current operations readiness data") + '</div>' +
          '<div class="tile">' + renderPayloadViewer("Supervision Snapshot", supervision, "current supervision data") + '</div>' +
        '</div>' +
        '<div class="divider"></div>' +
        renderNoticeList([
          "Operational actions remain supervision-safe and policy-gated for all intents.",
          "Conversation interactions remain within the current operational session.",
          "Operations records store operational action and context summaries.",
          "All intents require explicit confirmation before workflow dispatch."
        ]),
        "session"
      )
    ].join("");
  }

  function renderSystemHealth() {
    var supervision = state.supervision || {};
    var health = state.health || {};
    var diagnostics = health.diagnostics || {};
    var runtime = health.runtime || {};
    var validation = diagnostics.validation || {};
    var runtimeGovernor = diagnostics.runtime_governor || {};
    var websocket = diagnostics.websocket || {};
    var memoryPersistence = diagnostics.memory_persistence || {};
    var activeRequests = safeNumber(supervision.active_request_count, 0);
    var healthClass = safeText(supervision.health_classification, "unknown");
    var depStatuses = [runtimeGovernor.status, websocket.status, memoryPersistence.status, validation.backend_status];

    return [
      renderHealthBanner(health, supervision),

      renderPanelBlock(
        "Operational Readiness Banner",
        "Composite readiness posture assembled from the current read-only snapshots.",
        '<div class="grid-4">' +
          renderMetric("Operational Readiness", safeText(health.backend_status || supervision.backend_status, "unknown"), healthToneFromStatus(health.backend_status || supervision.backend_status)) +
          renderMetric("Supervision Status", safeText(supervision.supervision_status, "unknown"), healthToneFromStatus(supervision.supervision_status)) +
          renderMetric("Stability Classification", healthClass, healthToneFromStatus(healthClass)) +
          renderMetric("Uptime", safeText(supervision.uptime_human_readable, "unknown")) +
        '</div>',
        "diagnostics"
      ),

      renderPanelBlock(
        "Service Dependency Cards",
        "Supervisor controls, live updates, memory continuity, and validation status.",
        '<div class="grid-4">' +
          renderMetric("Supervisor Control", safeText(runtimeGovernor.status, "unknown"), healthToneFromStatus(runtimeGovernor.status)) +
          renderMetric("Operations Visibility", safeText(runtimeGovernor.telemetry_status, "unknown")) +
          renderMetric("Live Update Channel", safeText(websocket.status, "unknown"), healthToneFromStatus(websocket.status)) +
          renderMetric("Memory Persistence", safeText(memoryPersistence.status, "unknown"), healthToneFromStatus(memoryPersistence.status)) +
        '</div>',
        "dependencies"
      ),

      renderPanelBlock(
        "Operations Activity Grid",
        "Read-only operations metrics and live process indicators.",
        '<div class="grid-3">' +
          renderMetric("Process Memory (MB)", safeText(supervision.process_memory_mb, "unavailable")) +
          renderMetric("Process CPU (%)", safeText(supervision.process_cpu_percent, "unavailable")) +
          renderMetric("Active Requests", String(activeRequests)) +
          renderMetric("Active Connections", safeText(websocket.active_connections, "0")) +
          renderMetric("Dispatcher Connections", safeText(websocket.dispatcher_connections, "0")) +
          renderMetric("Driver Connections", safeText(websocket.driver_connections, "0")) +
        '</div>',
        "runtime"
      ),

      renderUptimeBlock(safeText(supervision.uptime_human_readable, "unknown"), safeNumber(supervision.uptime_seconds, 0)),

      renderPanelBlock(
        "Failure Classification Summary",
        "Classification and dependency posture with safe operations visibility detail.",
        '<div class="grid-3">' +
          renderMetric("Overall Classification", healthClass, healthToneFromStatus(healthClass)) +
          renderMetric("Required Dependencies", depStatuses.join(", ")) +
          renderMetric("Validation Readiness Status", safeText(validation.backend_status, "unknown")) +
          renderMetric("Memory Status", safeText((health.memory_persistence || {}).status, "unknown")) +
          renderMetric("Operations Status", safeText((health.runtime_governor || {}).status, "unknown")) +
          renderMetric("Operations Note", safeText((diagnostics || {}).note, "informational_only")) +
        '</div>',
        "classification"
      ),

      renderPanelBlock(
        "Operations Snapshot Viewer",
        "Read-only operations snapshots are shown for inspection only.",
        '<div class="grid-2">' +
          '<div class="tile">' + renderPayloadViewer("Readiness Snapshot", diagnostics, "source: operations readiness snapshot") + '</div>' +
          '<div class="tile">' + renderPayloadViewer("Supervision Summary", supervision.diagnostics_summary || {}, "source: supervision snapshot") + '</div>' +
        '</div>',
        "payloads"
      ),

      renderPanelBlock(
        "Supervision State Snapshot",
        "Operations visibility baseline, validation, and recent supervisory events.",
        '<div class="grid-2">' +
          '<div class="tile">' +
            renderMetric("Uptime", safeText(supervision.uptime_human_readable, "unknown")) +
            renderMetric("Generated At", safeText(supervision.generated_at, "unknown")) +
            renderMetric("Coordination Mode", safeText(supervision.runtime_mode, "unknown").replace(/runtime/gi, "coordination")) +
          '</div>' +
          '<div class="tile">' + renderPayloadViewer("Validation Baseline", validation || {}, "health snapshot validation data") + '</div>' +
        '</div>' +
        '<div class="divider"></div>' +
        renderRecentEvents(supervision.recent_events, 10),
        "snapshot"
      )
    ].join("");
  }

  function handleAssistantSubmit(event) {
    if (event) {
      event.preventDefault();
    }

    var input = document.getElementById("assistant-input");
    if (!input) return;
    var promptText = String(input.value || "").trim();
    if (!promptText || state.assistant.isResponding) {
      return;
    }

    state.assistant.draft = "";
    state.assistant.pendingPrompt = promptText;
    input.value = "";
    addAssistantMessage("user", "Operator", promptText);
    addAuditEvent("prompt_submitted", "none", promptText, "Prompt captured for explicit intent confirmation.");
    addToolEvent("informational", "Prompt captured", "Select an intent and confirm before dry-run request dispatch.");
    state.assistant.pendingIntent = null;
    void safeLogAssistantEvent("validation", "assistant_prompt_submitted", "success", {
      prompt_length: promptText.length,
      role: state.role
    }, "");
    recomputeAssistantRuntimeState();
    persistSessionState();
    renderPage();
  }

  function setPendingIntent(intent) {
    var promptText = safeText(state.assistant.pendingPrompt, "").trim();
    var normalizedIntent = String(intent || "preview").toLowerCase();
    var policy = evaluateGuardrailPolicy(normalizedIntent, promptText, state.role);

    state.assistant.pendingIntent = {
      intent: normalizedIntent,
      status: "awaiting_confirmation",
      prompt: promptText,
      policy: policy,
      createdAt: new Date().toISOString()
    };

    addAuditEvent("intent_selected", normalizedIntent, promptText, "Intent selected and waiting for explicit confirmation.");
    if (normalizedIntent === "preview") {
      addAuditEvent("preview_requested", normalizedIntent, promptText, "Preview requested by operator.");
    } else if (normalizedIntent === "simulate") {
      addAuditEvent("simulation_viewed", normalizedIntent, promptText, "Simulation intent selected by operator.");
    }
    void safeLogAssistantEvent("workflow", "assistant_intent_selected", "success", {
      intent: normalizedIntent,
      policy_state: safeText(policy.state, "ALLOWED")
    }, "");
    persistSessionState();
    renderPage();
  }

  async function handleIntentConfirmation() {
    var pending = state.assistant.pendingIntent;
    if (!pending || state.assistant.isResponding) {
      return;
    }
    await executeConfirmedIntent(pending.intent, pending.prompt, pending.policy || { state: "REQUIRES_CONFIRMATION", reasons: [] });
  }

  function handleIntentCancel() {
    if (!state.assistant.pendingIntent) {
      return;
    }
    var pending = state.assistant.pendingIntent;
    addAuditEvent("confirmation_canceled", safeText(pending.intent, "preview"), safeText(pending.prompt, ""), "Operator canceled pending intent from confirmation panel.");
    state.assistant.pendingIntent = null;
    addToolEvent("informational", "Confirmation canceled", "Pending intent canceled by operator before dry-run request.");
    persistSessionState();
    renderPage();
  }

  function bindAssistantWorkspaceEvents() {
    var form = document.getElementById("assistant-form");
    var input = document.getElementById("assistant-input");
    var collapseButtons = Array.prototype.slice.call(document.querySelectorAll("[data-collapse-panel]"));
    var suggestionButtons = Array.prototype.slice.call(document.querySelectorAll("[data-assistant-prompt]"));
    var intentButtons = Array.prototype.slice.call(document.querySelectorAll("[data-assistant-intent]"));
    var confirmButton = document.querySelector("[data-confirm-intent]");
    var cancelIntentButton = document.querySelector("[data-cancel-intent]");

    if (form) {
      form.addEventListener("submit", handleAssistantSubmit);
    }

    if (input) {
      input.addEventListener("input", function () {
        state.assistant.draft = String(input.value || "");
        persistSessionState();
      });
    }

    collapseButtons.forEach(function (button) {
      button.addEventListener("click", function () {
        var panel = String(button.getAttribute("data-collapse-panel") || "");
        if (!panel) return;
        state.assistant.collapsible[panel] = !Boolean(state.assistant.collapsible[panel]);
        persistSessionState();
        renderPage();
      });
    });

    suggestionButtons.forEach(function (button) {
      button.addEventListener("click", function () {
        var prompt = String(button.getAttribute("data-assistant-prompt") || "");
        if (!prompt) return;
        if (input) {
          input.value = prompt;
          state.assistant.draft = prompt;
          persistSessionState();
          input.focus();
        }
      });
    });

    intentButtons.forEach(function (button) {
      button.addEventListener("click", function () {
        var intent = String(button.getAttribute("data-assistant-intent") || "preview");
        setPendingIntent(intent);
      });
    });

    if (confirmButton) {
      confirmButton.addEventListener("click", function () {
        void handleIntentConfirmation();
      });
    }

    if (cancelIntentButton) {
      cancelIntentButton.addEventListener("click", function () {
        handleIntentCancel();
      });
    }
  }

  function renderErrorPanel() {
    return [
      '<section class="panel">',
      '<h3>Operations data connectivity warning</h3>',
      '<p class="muted">The shell remains available. Previously loaded records are preserved when a refresh fails.</p>',
      '<p><strong>Error:</strong> ' + escapeHtml(state.error || "operations_fetch_unavailable") + '</p>',
      '<p class="muted">Tap Retry to reload live data. Billing totals and lists will not be replaced with empty placeholders during a refresh failure.</p>',
      '<button class="preview-action" type="button" onclick="window.AmiOpsShellActions && window.AmiOpsShellActions.retryOperationsHydration && window.AmiOpsShellActions.retryOperationsHydration()">Retry</button>',
      '</section>'
    ].join("");
  }

  function renderDriverMobileLoadingPanel() {
    var appState = safeObject(state.driverApp);
    var errorText = safeText(appState.mobileBootstrapError, "");
    var syncWarning = safeText(appState.syncWarning, "");
    var detail = errorText || syncWarning;
    return wrapDriverMobilePage(
      '<div class="driver-workflow-card driver-mobile-loading">' +
        '<strong>Loading driver assignment</strong>' +
        '<p class="muted">Preparing the dedicated Driver Mobile session. Enterprise operations hydration is skipped on this route.</p>' +
        (detail
          ? '<p class="driver-mobile-load-error" style="color:#b91c1c;margin-top:10px;"><strong>Sync error:</strong> ' + escapeHtml(detail) + '</p>'
          : '') +
      '</div>'
    );
  }

  function renderDriverMobileApiErrorPanel() {
    var appState = safeObject(state.driverApp);
    var detail = safeText(appState.mobileBootstrapError, "") || safeText(appState.syncWarning, "Driver assignment sync failed.");
    return wrapDriverMobilePage(
      '<div class="driver-workflow-card" style="border-color:#fca5a5;background:#fff7f7;">' +
        '<strong>Driver Mobile load error</strong>' +
        '<p class="muted">' + escapeHtml(detail) + '</p>' +
        '<button class="preview-action driver-action" type="button" onclick="window.AmiOpsShellActions && window.AmiOpsShellActions.refreshDriverWorkflowData && window.AmiOpsShellActions.refreshDriverWorkflowData({})">Retry</button>' +
      '</div>'
    );
  }

  function renderPage() {
    if (!state.loading && (isDispatcherDraftFieldActive() || isRiderDraftFieldActive())) {
      window.__amiDispatcherDraftRenderDeferred = true;
      console.info("[Dispatcher Pickup Render]", {
        stage: "renderPage:deferred",
        activeElementId: document.activeElement && document.activeElement.id ? document.activeElement.id : null,
        activeElementTag: document.activeElement && document.activeElement.tagName ? document.activeElement.tagName : null,
        activeIsPickup: (document.activeElement && document.activeElement.id === "dispatcher-patient-pickup") || (document.activeElement && document.activeElement.id === "dispatcher-ride-pickup"),
        lastRefreshTriggerSource: safeText(state.runtime && state.runtime.lastRefreshTriggerSource, ""),
      });
      return;
    }
    window.__amiDispatcherDraftRenderDeferred = false;
    traceDispatcherPickupRender("renderPage:start");
    applyDedicatedSurfaceLayout();
    state.runtime.lastRenderTimestamp = new Date().toISOString();
    var routeMeta = ROUTES[state.route] || ROUTES.dashboard;
    document.body.setAttribute("data-route", state.route);
    els.pageTitle.textContent = routeMeta.title;
    els.pageSubtitle.textContent = routeMeta.subtitle;
    updateTopBadges();

    if (state.loading) {
      if (state.role === "dispatcher" && state.route === "dispatch") {
        syncPageContentHtml(
          els.pageContent,
          '<section class="panel"><p class="muted">Loading latest backend snapshots. Dispatcher actions remain available.</p></section>' +
          renderDispatcherOperationsWorkspace()
        );
        return;
      }
      if (isDriverMobileAppRoute()) {
        syncPageContentHtml(els.pageContent, renderDriverMobileLoadingPanel());
        return;
      }
      syncPageContentHtml(
        els.pageContent,
        '<section class="panel hydration-loading">' +
          '<div class="hydration-spinner" aria-hidden="true"></div>' +
          '<h3>Preparing Command Surface</h3>' +
          '<p class="muted">Loading dispatch, supervision, and continuity views for this role...</p>' +
          '<div class="loading-skeleton-grid">' +
            '<div class="loading-skeleton"></div>' +
            '<div class="loading-skeleton"></div>' +
            '<div class="loading-skeleton"></div>' +
          '</div>' +
        '</section>'
      );
      return;
    }

    if (state.error && !state.health && !state.supervision) {
      els.pageContent.innerHTML = renderErrorPanel();
      return;
    }

    var pageHtml = "";
    if (state.route === "dashboard") {
      pageHtml = renderDashboard();
    } else if (state.route === "dispatch") {
      pageHtml = renderDispatch();
    } else if (state.route === "trips") {
      pageHtml = renderTrips();
    } else if (state.route === "riders") {
      pageHtml = renderRidersRoute();
    } else if (state.route === "providers") {
      pageHtml = renderProviders();
    } else if (state.route === "drivers") {
      pageHtml = renderDrivers();
    } else if (state.route === "vehicles") {
      pageHtml = renderVehicles();
    } else if (state.route === "billing") {
      pageHtml = renderBilling();
    } else if (state.route === "analytics") {
      pageHtml = renderAnalytics();
    } else if (state.route === "alerts") {
      pageHtml = renderOperationsAlerts();
    } else if (state.route === "mobile") {
      pageHtml = renderMobile();
    } else if (state.route === "settings") {
      pageHtml = renderSettings();
    } else if (state.route === "ai-assistant") {
      pageHtml = renderAssistant();
      bindAssistantWorkspaceEvents();
    } else {
      pageHtml = renderSystemHealth();
    }

    var warningBanner = "";
    if (!isDriverMobileAppRoute() && state.fetchWarnings.length > 0) {
      var warningRows = warningDisplayEntries().slice(0, 3).map(function (entry) {
        return '<span class="runtime-strip-item">' + escapeHtml(entry.message) + '</span>';
      }).join("");
      warningBanner =
        '<section class="runtime-strip">' +
          '<span class="runtime-strip-label">Operations Notices</span>' +
          warningRows +
          '<span class="runtime-strip-meta">' + renderHydrationIntegrityBadge((state.hydration || {}).integrityState) + '</span>' +
        '</section>';
    }

    if (!pageHtml || !String(pageHtml).trim()) {
      pageHtml =
        '<section class="panel">' +
          '<h3>Workspace temporarily unavailable</h3>' +
          '<p class="muted">Live data could not be rendered. Your session is still active — try refreshing this view.</p>' +
          '<button class="preview-action" type="button" id="ops-empty-reload">Reload workspace</button>' +
        '</section>';
    }

    var fullHtml = pageHtml + warningBanner;
    var dataSig = computePageDataSignature();
    updateLastUpdatedLabel();
    if (!state.loading && dataSig === state.runtime.lastPageDataSignature && els.pageContent.__stableHtml === fullHtml) {
      traceDispatcherPickupRender("renderPage:skipped-stable");
      if (canUseDriverWorkspaceActions()) {
        bindDriverWorkspaceEvents();
      } else if (isDriverMobileSurface()) {
        bindDriverWorkspaceEvents();
      }
      if ((state.route === "dashboard" || state.route === "mobile" || state.route === "riders") && (state.role === "rider" || state.route === "riders")) {
        bindRiderWorkspaceEvents();
      }
      return;
    }
    state.runtime.lastPageDataSignature = dataSig;
    if (els.pageContent && els.pageContent.innerText && els.pageContent.innerText.indexOf("Preparing Command Surface") >= 0) {
      els.pageContent.__stableHtml = "";
    }
    var domChanged = setHtmlIfChanged(els.pageContent, fullHtml);
    if (!domChanged) {
      traceDispatcherPickupRender("renderPage:skipped-html");
    }
    var reloadButton = document.getElementById("ops-empty-reload");
    if (reloadButton) {
      reloadButton.addEventListener("click", function () {
        loadBackendData({ silent: false }).catch(function () {});
      });
    }
    var healthActionButtons = document.querySelectorAll('[data-nova-action="system_health"]');
    healthActionButtons.forEach(function (button) {
      button.textContent = "Review operations status";
    });
    if (canUseDriverWorkspaceActions()) {
      bindDriverWorkspaceEvents();
    } else if (isDriverMobileSurface()) {
      bindDriverWorkspaceEvents();
    }
    if ((state.route === "dashboard" || state.route === "mobile" || state.route === "riders") && (state.role === "rider" || state.route === "riders")) {
      bindRiderWorkspaceEvents();
    }
    traceDispatcherPickupRender("renderPage:end");
  }

  function bindDriverWorkspaceEvents() {
    var host = els.pageContent;
    if (!host) return;

    var loginButton = document.getElementById("driver-mobile-login-btn");
    if (loginButton && loginButton.getAttribute("data-ami-login-bound") !== "1") {
      loginButton.setAttribute("data-ami-login-bound", "1");
      loginButton.addEventListener("click", function () {
        void submitDriverMobileLogin({ allowDriverId: !!safeText(document.getElementById("driver-mobile-id") && document.getElementById("driver-mobile-id").value, "").trim() });
      });
    }
    var phoneInput = document.getElementById("driver-mobile-phone");
    if (phoneInput) {
      var savedPhone = safeText((safeObject(state.driverApp)).mobileLogin && state.driverApp.mobileLogin.phone, "");
      if (savedPhone && !safeText(phoneInput.value, "")) {
        phoneInput.value = savedPhone;
      }
      phoneInput.addEventListener("input", function (event) {
        syncDriverMobilePhoneState(safeText(event && event.target && event.target.value, ""));
      });
      phoneInput.addEventListener("change", function (event) {
        syncDriverMobilePhoneState(safeText(event && event.target && event.target.value, ""));
      });
      phoneInput.addEventListener("keydown", function (event) {
        if (event && event.key === "Enter") {
          event.preventDefault();
          void submitDriverMobileLogin();
        }
      });
    }

    var actionButtons = Array.prototype.slice.call(host.querySelectorAll("[data-driver-action]"));
    actionButtons.forEach(function (button) {
      if (button.getAttribute("data-ami-action-bound") === "1") return;
      button.setAttribute("data-ami-action-bound", "1");
      button.addEventListener("click", async function () {
        if (driverActionInFlight) return;
        var action = safeText(button.getAttribute("data-driver-action"), "");
        var tripId = safeText(button.getAttribute("data-trip-id"), "");
        var noteId = safeText(button.getAttribute("data-note-id"), "");
        driverActionInFlight = true;
        button.disabled = true;
        try {
          await handleDriverWorkspaceAction(action, tripId, noteId);
        } finally {
          driverActionInFlight = false;
          button.disabled = false;
        }
      });
    });
  }

  function addDriverNotification(level, text) {
    var appState = safeObject(state.driverApp);
    if (!Array.isArray(appState.notifications)) {
      appState.notifications = [];
    }
    appState.notifications.unshift({
      id: "note-" + String(Date.now()),
      level: safeText(level, "low"),
      text: safeText(text, "Driver update"),
      ts: "now"
    });
    state.driverApp = appState;
  }

  async function handleDriverWorkspaceAction(action, tripId, noteId) {
    state = window.AmiOpsShellState || state;
    var appState = safeObject(state.driverApp);
    if (!safeText(appState.currentDriverId, "") && safeText((safeObject(state.driverWorkflow)).driverId, "")) {
      appState.currentDriverId = safeText(state.driverWorkflow.driverId, "");
    }
    if (!Array.isArray(appState.tripQueue)) {
      appState.tripQueue = [];
    }
    state.driverApp = appState;

    var activeTrip = resolveDriverActiveTrip(tripId || appState.activeTripId)
      || getDriverTripById(tripId || appState.activeTripId);
    var updated = false;
    var handlerMutatedApp = false;

    var runtime = window.AmiDriverRuntime;
    var currentDriverId = safeText(appState.currentDriverId || (safeObject(state.driverWorkflow)).driverId, "");

    if (action === "mobile_login") {
      await submitDriverMobileLogin();
      return;
    }

    if (action === "sign_out") {
      clearPersistedDriverSession();
      driverMobileAuthCache = null;
      driverLastConfirmedWorkflow = null;
      clearDriverMobileWorkflowState({ driverId: "" });
      resetDriverMobileAfterCompletion();
      state.driverApp = safeObject(state.driverApp);
      state.driverApp.mobileUiState = "login_required";
      state.driverApp.mobileLogin = safeObject(state.driverApp.mobileLogin);
      state.driverApp.mobileLogin.status = "Not signed in";
      state.driverApp.mobileLogin.error = "";
      clearDriverMobileSyncError();
      state.driverApp.lastStatusUpdate = "Signed out";
      window.AmiOpsShellState = state;
      scheduleRenderPage({ immediate: true });
      return;
    }

    if (action === "accept_trip") {
      var visibleTripId = safeText(appState.activeTripId, "") || safeText(tripId, "");
      if (!visibleTripId) {
        window.alert("Accept Trip only applies to the currently visible ride.");
        return;
      }
      if (safeText(tripId, "") && safeText(tripId, visibleTripId) !== visibleTripId) {
        window.alert("Accept Trip only applies to the currently visible ride.");
        return;
      }
      appState.activeTripId = visibleTripId;
      activeTrip = resolveDriverActiveTrip(visibleTripId) || getDriverTripById(visibleTripId);
    }

    if (action === "start_route") {
      var startRouteTripId = safeText(appState.activeTripId, "") || safeText(tripId, "");
      if (!startRouteTripId) {
        window.alert("Start Route only applies to the currently visible ride.");
        return;
      }
      if (safeText(tripId, "") && safeText(tripId, startRouteTripId) !== startRouteTripId) {
        window.alert("Start Route only applies to the currently visible ride.");
        return;
      }
      appState.activeTripId = startRouteTripId;
      activeTrip = resolveDriverActiveTrip(startRouteTripId) || getDriverTripById(startRouteTripId);
    }

    if (action === "toggle_shift") {
      if (!currentDriverId) {
        window.alert("Driver profile is not bound yet. Refresh the workspace after dispatch assignment.");
        return;
      }
      var nextShiftStatus = appState.shiftOnline ? "offline" : "available";
      var shiftResult = await window._amiHandleDriverShiftReadiness(currentDriverId, nextShiftStatus);
      if (!shiftResult) {
        return;
      }
      appState.shiftOnline = nextShiftStatus === "available";
      appState.lastStatusUpdate = appState.shiftOnline ? "Shift started and available for dispatch" : "Shift ended";
      addDriverNotification("medium", appState.lastStatusUpdate + ".");
      updated = true;
    } else if (action === "select_trip") {
      appState.activeTripId = safeText(tripId, appState.activeTripId);
      appState.lastStatusUpdate = "Opened trip " + safeText(appState.activeTripId, "");
      updated = true;
    } else if (action === "accept_scheduled_ride") {
      if (!currentDriverId) {
        window.alert("Driver profile is not bound yet.");
        return;
      }
      var scheduledTripId = safeText(tripId, "");
      if (!scheduledTripId) {
        window.alert("Select a scheduled ride to accept.");
        return;
      }
      try {
        await _amiAcceptScheduledRideWithRecovery(currentDriverId, scheduledTripId);
        appState.lastStatusUpdate = "Scheduled ride reserved: " + scheduledTripId;
        addDriverNotification("medium", "Scheduled ride accepted and added to Upcoming Schedule.");
        updated = true;
        await refreshDriverWorkflowData({ forceReset: false });
      } catch (err) {
        window.alert("Unable to accept scheduled ride: " + safeText(err && err.message, "unknown error"));
      }
      return;
    } else if (action === "accept_trip" && activeTrip) {
      if (!currentDriverId) {
        window.alert("Driver profile is not bound yet.");
        return;
      }
      var reservedOwnerId = safeText(activeTrip.reservedByDriverId || activeTrip.reserved_by_driver_id, "");
      if (reservedOwnerId && reservedOwnerId !== currentDriverId) {
        window.alert("This ride is reserved for another driver.");
        return;
      }
      if (!(await window._amiHandleDriverAcceptTrip(safeText(activeTrip.tripId, "")))) {
        return;
      }
      handlerMutatedApp = true;
      updated = true;
    } else if (action === "decline_trip" && activeTrip) {
      if (!currentDriverId) {
        window.alert("Driver profile is not bound yet.");
        return;
      }
      if (!(await window._amiHandleDriverDeclineTrip(safeText(activeTrip.tripId, "")))) {
        return;
      }
      updated = true;
    } else if (action === "call_rider" && activeTrip) {
      if (!currentDriverId) {
        window.alert("Driver profile is not bound yet.");
        return;
      }
      if (!(await window._amiHandleDriverCallRider(safeText(activeTrip.tripId, "")))) {
        return;
      }
      updated = true;
    } else if (action === "start_route" && activeTrip) {
      if (!currentDriverId) {
        window.alert("Driver profile is not bound yet.");
        return;
      }
      if (!(await window._amiHandleDriverStartRoute(safeText(activeTrip.tripId, "")))) {
        return;
      }
      handlerMutatedApp = true;
      updated = true;
    } else if (action === "arrive_pickup" && activeTrip) {
      if (!currentDriverId) {
        window.alert("Driver profile is not bound yet.");
        return;
      }
      if (!(await window._amiHandleDriverArriveTrip(safeText(activeTrip.tripId, "")))) {
        return;
      }
      handlerMutatedApp = true;
      updated = true;
    } else if (action === "start_trip" && activeTrip) {
      if (!currentDriverId) {
        window.alert("Driver profile is not bound yet.");
        return;
      }
      if (!(await window._amiHandleDriverStartTrip(safeText(activeTrip.tripId, "")))) {
        return;
      }
      handlerMutatedApp = true;
      updated = true;
    } else if (action === "start_transport" && activeTrip) {
      if (!currentDriverId) {
        window.alert("Driver profile is not bound yet.");
        return;
      }
      if (!(await window._amiHandleDriverProgressTrip(safeText(activeTrip.tripId, "")))) {
        return;
      }
      handlerMutatedApp = true;
      updated = true;
    } else if (action === "arrive_destination" && activeTrip) {
      if (!currentDriverId) {
        window.alert("Driver profile is not bound yet.");
        return;
      }
      if (!(await window._amiHandleDriverArriveDestination(safeText(activeTrip.tripId, "")))) {
        return;
      }
      handlerMutatedApp = true;
      updated = true;
    } else if (action === "complete_trip" && activeTrip) {
      if (!currentDriverId) {
        window.alert("Driver profile is not bound yet.");
        return;
      }
      if (!(await window._amiHandleDriverCompleteTrip(safeText(activeTrip.tripId, "")))) {
        return;
      }
      handlerMutatedApp = true;
      updated = true;
    } else if (action === "dismiss_notification" && noteId) {
      appState.notifications = (Array.isArray(appState.notifications) ? appState.notifications : []).filter(function (item) {
        return safeText(item.id, "") !== noteId;
      });
      updated = true;
    } else if (action === "emergency_help") {
      if (runtime && typeof runtime.delayTrip === "function" && activeTrip) {
        runtime.delayTrip(safeText(activeTrip.tripId, ""));
      }
      appState.lastStatusUpdate = "Emergency assistance requested";
      addDriverNotification("high", "Emergency assistance requested. Dispatcher and safety team notified.");
      updated = true;
    } else if (action === "open_support") {
      appState.lastStatusUpdate = "Driver support ticket opened";
      addDriverNotification("medium", "Driver support ticket opened for current trip context.");
      updated = true;
    } else if (action === "show_earnings") {
      appState.secondaryTab = "earnings";
      updated = true;
    } else if (action === "show_documents") {
      appState.secondaryTab = "documents";
      updated = true;
    } else if (action === "show_history") {
      appState.secondaryTab = "history";
      updated = true;
    }

    if (updated) {
      state = window.AmiOpsShellState || state;
      var liveApp = handlerMutatedApp ? safeObject(state.driverApp) : appState;
      if (!handlerMutatedApp) {
        state.driverApp = liveApp;
      } else {
        if (appState.secondaryTab) {
          liveApp.secondaryTab = appState.secondaryTab;
        }
        if (typeof appState.shiftOnline === "boolean") {
          liveApp.shiftOnline = appState.shiftOnline;
        }
        if (Array.isArray(appState.notifications)) {
          liveApp.notifications = appState.notifications;
        }
        state.driverApp = liveApp;
      }
      window.AmiOpsShellState = state;
      lockDriverHydration(3000);
      persistSessionState();
      scheduleRenderPage();
    }
  }

  function bindRiderWorkspaceEvents() {
    var host = els.pageContent;
    if (!host) return;
    var actionButtons = Array.prototype.slice.call(host.querySelectorAll("[data-rider-action]"));
    actionButtons.forEach(function (button) {
      button.addEventListener("click", async function () {
        var action = safeText(button.getAttribute("data-rider-action"), "");
        var noteId = safeText(button.getAttribute("data-note-id"), "");
        await handleRiderWorkspaceAction(action, noteId);
      });
    });
    [
      "rider-name-input",
      "rider-phone-input",
      "rider-pickup-input",
      "rider-dropoff-input",
      "rider-ride-type-input",
      "rider-notes-input"
    ].forEach(function (fieldId) {
      var field = document.getElementById(fieldId);
      if (!field) return;
      field.addEventListener("blur", function () {
        setTimeout(function () {
          if (typeof flushDeferredDispatcherDraftRender === "function") {
            flushDeferredDispatcherDraftRender();
          }
        }, 0);
      });
    });
  }

  function addRiderNotification(level, text) {
    var riderState = safeObject(state.riderApp);
    if (!Array.isArray(riderState.notifications)) {
      riderState.notifications = [];
    }
    riderState.notifications.unshift({
      id: "rnote-" + String(Date.now()),
      text: safeText(text, "Rider update"),
      level: safeText(level, "low"),
      ts: "now"
    });
    state.riderApp = riderState;
  }

  async function handleRiderWorkspaceAction(action, noteId) {
    var riderState = safeObject(state.riderApp);
    if (!riderState) return;
    var updated = false;
    var runtime = window.AmiRiderRuntime;

    if (action === "sign_in") {
      var signedIn = await ensureAuthenticatedSession("Sign in as a rider before requesting a ride.");
      if (signedIn) {
        riderState.lastAction = "Signed in — ready to request a ride";
        state.riderApp = riderState;
        persistSessionState();
        renderPage();
      }
      return;
    } else if (action === "sign_out") {
      try {
        if (window.AmiCorSession && typeof window.AmiCorSession.logout === "function") {
          await window.AmiCorSession.logout();
        } else if (window.AmiCorSession && typeof window.AmiCorSession.clear === "function") {
          window.AmiCorSession.clear();
        }
      } catch (_) {}
      riderState.submitInFlight = false;
      riderState.submitStatus = {};
      riderState.lastAction = "Signed out";
      state.riderApp = riderState;
      persistSessionState();
      try {
        var logoutBtn = document.getElementById("btn-logout");
        if (logoutBtn) logoutBtn.hidden = true;
      } catch (_) {}
      renderPage();
      return;
    } else if (action === "request_now") {
      var submitResult = await submitRiderRideRequest(false);
      if (submitResult && submitResult.ok === false && submitResult.confirmedFailure) {
        window.alert(submitResult.message || "We could not confirm your ride request. Refresh and check ride history before trying again.");
      }
      return;
    } else if (action === "schedule_recurring") {
      var recurringResult = await submitRiderRideRequest(true);
      if (recurringResult && recurringResult.ok === false && recurringResult.confirmedFailure) {
        window.alert(recurringResult.message || "We could not confirm your recurring ride request. Refresh and check ride history before trying again.");
      }
      return;
    } else if (action === "cancel_active_trip") {
      try {
        await cancelActiveRiderRequest();
        return;
      } catch (_) {
        window.alert("Unable to cancel the active rider request.");
        return;
      }
    } else if (action === "contact_support") {
      if (runtime && typeof runtime.supportEscalation === "function") {
        var activeId = safeText((safeObject(riderState.activeTrip) || {}).tripId, "");
        runtime.supportEscalation(activeId);
      }
      riderState.lastAction = "Support contacted";
      addRiderNotification("medium", "Support specialist joined your trip context.");
      updated = true;
    } else if (action === "share_trip") {
      riderState.lastAction = "Live trip shared";
      addRiderNotification("low", "Live trip link shared with care contact.");
      updated = true;
    } else if (action === "dismiss_notification" && noteId) {
      riderState.notifications = (Array.isArray(riderState.notifications) ? riderState.notifications : []).filter(function (item) {
        return safeText(item.id, "") !== noteId;
      });
      updated = true;
    }

    if (updated) {
      state.riderApp = riderState;
      persistSessionState();
      renderPage();
    }
  }

  function withTimeout(promise, timeoutMs) {
    return new Promise(function (resolve, reject) {
      var completed = false;
      var timer = setTimeout(function () {
        if (completed) return;
        completed = true;
        reject(new Error("request_timeout"));
      }, timeoutMs);

      promise.then(function (value) {
        if (completed) return;
        completed = true;
        clearTimeout(timer);
        resolve(value);
      }).catch(function (error) {
        if (completed) return;
        completed = true;
        clearTimeout(timer);
        reject(error);
      });
    });
  }

  function unwrapApiPayload(payload) {
    if (payload && typeof payload === "object" && Object.prototype.hasOwnProperty.call(payload, "ok") && Object.prototype.hasOwnProperty.call(payload, "data")) {
      return payload.data;
    }
    return payload;
  }

  function logRiderSubmitEvent(eventName, detail) {
    var entry = {
      event: eventName,
      ts: new Date().toISOString(),
      detail: detail || {}
    };
    if (!window.__amiRiderSubmitLog) window.__amiRiderSubmitLog = [];
    window.__amiRiderSubmitLog.push(entry);
    try {
      console.info("[rider-submit]", eventName, entry.detail);
    } catch (_) {}
  }

  async function fetchJson(url, requestOptions, explicitToken) {
    var options = safeObject(requestOptions);
    var method = safeText(options.method, "GET").toUpperCase();
    var scopedUrl = withOrganizationScope(url);
    var useDriverSessionOnly = shouldUseDriverSessionFirstFetch(scopedUrl);
    if (!useDriverSessionOnly && window.AmiCorSession && typeof window.AmiCorSession.ensureReady === "function") {
      try {
        await window.AmiCorSession.ensureReady();
      } catch (_) {}
    }
    var token = getAccessToken() || explicitToken;
    var headers = applyDriverSessionHeaders({ "Accept": "application/json" }, token, scopedUrl);
    if (useDriverSessionOnly) {
      delete headers.Authorization;
      delete headers.authorization;
    }
    if (options.headers && typeof options.headers === "object") {
      Object.keys(options.headers).forEach(function (key) {
        headers[key] = options.headers[key];
      });
    }
    if (options.body != null && !headers["Content-Type"] && !headers["content-type"]) {
      headers["Content-Type"] = "application/json";
    }
    if (!useDriverSessionOnly && token && !headers.Authorization && !headers.authorization) {
      headers.Authorization = "Bearer " + token;
    }
    var retries = method === "GET" ? 2 : 0;
    var fetchTimeoutMs = resolveDriverMobileFetchTimeoutMs(scopedUrl, options.timeoutMs);
    if (!fetchTimeoutMs) {
      fetchTimeoutMs = method === "GET" ? 20000 : 12000;
    }
    var attempt = 0;
    async function performFetch(currentToken) {
      var nextHeaders = applyDriverSessionHeaders({ "Accept": "application/json" }, currentToken, scopedUrl);
      if (options.headers && typeof options.headers === "object") {
        Object.keys(options.headers).forEach(function (key) {
          nextHeaders[key] = options.headers[key];
        });
      }
      if (options.body != null && !nextHeaders["Content-Type"] && !nextHeaders["content-type"]) {
        nextHeaders["Content-Type"] = "application/json";
      }
      if (!useDriverSessionOnly && currentToken && !nextHeaders.Authorization && !nextHeaders.authorization) {
        nextHeaders.Authorization = "Bearer " + currentToken;
      }
      if (useDriverSessionOnly) {
        delete nextHeaders.Authorization;
        delete nextHeaders.authorization;
      }
      var requestInit = {
        method: method,
        headers: nextHeaders,
        body: options.body,
        credentials: "same-origin"
      };
      if (options.signal) {
        requestInit.signal = options.signal;
      }
      if (!useDriverSessionOnly && window.AmiCorSession && typeof window.AmiCorSession.authFetch === "function") {
        return window.AmiCorSession.authFetch(scopedUrl, requestInit);
      }
      return fetch(scopedUrl, requestInit);
    }
    while (attempt <= retries) {
      try {
        var response = await withTimeout(performFetch(token), fetchTimeoutMs);

        if (!response.ok) {
          throw new Error(scopedUrl + ":http_" + response.status);
        }

        if (response.status === 204) {
          return {};
        }

        return unwrapApiPayload(await response.json());
      } catch (error) {
        var message = safeText(error && error.message, "");
        var transient = message.indexOf("request_timeout") >= 0 || message.indexOf("Failed to fetch") >= 0 || message.indexOf("NetworkError") >= 0;
        if (!(method === "GET" && transient && attempt < retries)) {
          throw error;
        }
        attempt += 1;
        await sleepMs(400 * Math.pow(2, attempt - 1));
      }
    }
    return {};
  }

  function isHttpStatusError(reason, statusCode) {
    if (!reason || typeof statusCode !== "number") return false;
    var text = "";
    if (typeof reason === "string") {
      text = reason;
    } else if (reason && typeof reason.message === "string") {
      text = reason.message;
    }
    return text.indexOf(":http_" + String(statusCode)) >= 0;
  }

  function clearAccessTokenArtifacts() {
    // SECURITY FIX: Do not clear amicor_session and amicor_identity here.
    // Those are managed by sessionManager.js and should only be cleared by that module.
    // ops-shell.js should not perform cross-module session cleanup.
    // If auth fails, let sessionManager detect it via authFetch() and refresh attempts.
    // This prevents race conditions where ops startup interferes with fresh login.
    try {
      // Only clear ops-specific cached state, not core session artifacts
      localStorage.removeItem("ops_shell_state");
      localStorage.removeItem("ops_cached_data");
    } catch (_) {}
  }

  function bootstrapAppSession() {
    try {
      if (window.AmiCorSession && typeof window.AmiCorSession.restore === "function") {
        window.AmiCorSession.restore();
      }
    } catch (_) {}
  }

  async function ensurePlatformSessionReady() {
    bootstrapAppSession();
    try {
      if (window.AmiCorSession && typeof window.AmiCorSession.ensureReady === "function") {
        await withTimeout(window.AmiCorSession.ensureReady(), SESSION_READY_TIMEOUT_MS);
      }
    } catch (_) {}
    state.hydration = safeObject(state.hydration);
    state.hydration.authTokenPresent = !!getAccessToken();
  }

  function applyLoginIdentity(identity) {
    if (!identity || typeof identity !== "object") {
      return;
    }
    var normalized = {
      userId: identity.userId || identity.user_id,
      email: identity.email,
      name: identity.name || identity.display_name,
      role: identity.role,
      authorizedRoles: identity.authorizedRoles || identity.authorized_roles,
      organizationId: identity.organizationId || identity.organization_id,
      organizationName: identity.organizationName || identity.organization_name,
      accessToken: identity.accessToken || identity.access_token,
      refreshToken: identity.refreshToken || identity.refresh_token,
      tokenExpiresAt: identity.tokenExpiresAt,
      createdAt: identity.createdAt
    };
    if (window.AmiCorSession && typeof window.AmiCorSession.start === "function") {
      window.AmiCorSession.start(normalized);
    }
    if (window.AmiCorSession && typeof window.AmiCorSession.applyAuthTokens === "function") {
      window.AmiCorSession.applyAuthTokens({
        access_token: normalized.accessToken,
        refresh_token: normalized.refreshToken,
        role: normalized.role,
        authorized_roles: normalized.authorizedRoles,
        expires_in: normalized.tokenExpiresAt
          ? Math.max(60, Math.round((Number(normalized.tokenExpiresAt) - Date.now()) / 1000))
          : undefined
      });
    }
    var nextRole = safeText(identity.role, "").toLowerCase();
    if (nextRole && ROLE_ACCESS[nextRole]) {
      state.role = nextRole;
      saveRole(nextRole);
      if (els.roleSelect) {
        els.roleSelect.value = nextRole;
      }
    }
    state.hydration = safeObject(state.hydration);
    state.hydration.authTokenPresent = !!getAccessToken();
    void syncPlatformRoleAuth(getPlatformRole()).then(function () {
      updateTopBadges();
    });
  }

  function ensureAuthenticatedSession(message) {
    bootstrapAppSession();
    var readyPromise = Promise.resolve(true);
    if (window.AmiCorSession && typeof window.AmiCorSession.ensureReady === "function") {
      readyPromise = window.AmiCorSession.ensureReady().then(function (ready) {
        return ready !== false;
      }).catch(function () {
        return false;
      });
    }
    return readyPromise.then(function () {
      if (getAccessToken()) {
        return true;
      }
      if (!(window.AmiCorAuthUI && typeof window.AmiCorAuthUI.showLogin === "function")) {
        window.alert(message || "Sign in required to continue.");
        return false;
      }
      return new Promise(function (resolve) {
      var settled = false;
      var dismissWatch = null;
      var authDeadline = null;
      function finish(ok) {
        if (settled) return;
        settled = true;
        if (dismissWatch) clearInterval(dismissWatch);
        if (authDeadline) clearTimeout(authDeadline);
        resolve(!!ok && !!getAccessToken());
      }
      function openLogin() {
        window.AmiCorAuthUI.showLogin(function (identity) {
          applyLoginIdentity(identity);
          finish(true);
          loadBackendData({ silent: true }).finally(function () {
            renderPage();
          });
        }, openSignup);
        dismissWatch = setInterval(function () {
          if (getAccessToken()) {
            finish(true);
            return;
          }
          if (!document.getElementById("amicor-auth-overlay")) {
            finish(false);
          }
        }, 400);
        authDeadline = setTimeout(function () {
          finish(!!getAccessToken());
        }, 90000);
      }
      function openSignup() {
        if (!(window.AmiCorAuthUI && typeof window.AmiCorAuthUI.showSignup === "function")) {
          openLogin();
          return;
        }
        window.AmiCorAuthUI.showSignup(function (identity) {
          applyLoginIdentity(identity);
          finish(true);
          loadBackendData({ silent: true }).finally(function () {
            renderPage();
          });
        }, openLogin);
      }
      openLogin();
    });
    });
  }

  function buildAuthorizedRequestInit(scopedUrl, requestInit) {
    var init = Object.assign({}, requestInit || {});
    if (!init.credentials) {
      init.credentials = "same-origin";
    }
    var token = getAccessToken();
    var headers = applyDriverSessionHeaders(Object.assign({}, init.headers || {}), token, scopedUrl);
    if (shouldUseDriverSessionFirstFetch(scopedUrl)) {
      delete headers.Authorization;
      delete headers.authorization;
    } else if (token && !headers.Authorization && !headers.authorization) {
      headers.Authorization = "Bearer " + token;
    }
    init.headers = headers;
    return init;
  }

  async function authorizedFetch(scopedUrl, requestInit, timeoutMs) {
    bootstrapAppSession();
    var driverSessionFirst = shouldUseDriverSessionFirstFetch(scopedUrl);
    if (!driverSessionFirst && window.AmiCorSession && typeof window.AmiCorSession.ensureReady === "function") {
      try {
        await window.AmiCorSession.ensureReady();
      } catch (_) {}
    }

    async function executeFetch() {
      var init = buildAuthorizedRequestInit(scopedUrl, requestInit);
      if (driverSessionFirst) {
        return fetch(scopedUrl, init);
      }
      if (window.AmiCorSession && typeof window.AmiCorSession.authFetch === "function") {
        return window.AmiCorSession.authFetch(scopedUrl, init);
      }
      return fetch(scopedUrl, init);
    }

    var authTimeoutMs = resolveDriverMobileFetchTimeoutMs(scopedUrl, timeoutMs) || timeoutMs || 12000;
    var response = await withTimeout(executeFetch(), authTimeoutMs);
    if (
      !driverSessionFirst
      && response.status === 401
      && window.AmiCorSession
      && typeof window.AmiCorSession.refreshAccessToken === "function"
      && window.AmiCorSession.getRefreshToken()
    ) {
      var refreshed = await window.AmiCorSession.refreshAccessToken(true);
      if (refreshed) {
        response = await withTimeout(executeFetch(), authTimeoutMs);
      }
    }
    return response;
  }

  async function postJson(url, payload, timeoutMs, options) {
    var opts = options || {};
    var scopedUrl = withOrganizationScope(url);
    var headers = {
      "Accept": "application/json",
      "Content-Type": "application/json"
    };
    if (opts.idempotencyKey) {
      headers["X-Idempotency-Key"] = String(opts.idempotencyKey);
    }
    var postTimeoutMs = resolveDriverMobileFetchTimeoutMs(scopedUrl, timeoutMs) || timeoutMs || 12000;
    var response = await authorizedFetch(scopedUrl, {
      method: "POST",
      headers: headers,
      body: JSON.stringify(payload || {})
    }, postTimeoutMs);

    if (!response.ok) {
      var postStatus = response.status;
      var errDetail = scopedUrl + ":http_" + postStatus;
      try {
        var errBody = await response.json();
        if (errBody && errBody.detail) {
          errDetail = String(errBody.detail) + " :http_" + postStatus;
        }
      } catch (_) {}
      throw new Error(errDetail);
    }
    return unwrapApiPayload(await response.json());
  }

  async function sendJson(url, method, payload, timeoutMs) {
    var scopedUrl = withOrganizationScope(url);
    var sendTimeoutMs = resolveDriverMobileFetchTimeoutMs(scopedUrl, timeoutMs) || timeoutMs || 12000;
    var response = await authorizedFetch(scopedUrl, {
      method: safeText(method, "POST").toUpperCase(),
      headers: {
        "Accept": "application/json",
        "Content-Type": "application/json"
      },
      body: payload == null ? null : JSON.stringify(payload)
    }, sendTimeoutMs);

    if (!response.ok) {
      var sendStatus = response.status;
      var errDetail = scopedUrl + ":http_" + sendStatus;
      try {
        var errBody = await response.json();
        if (errBody && errBody.detail) {
          errDetail = String(errBody.detail) + " :http_" + sendStatus;
        }
      } catch (_) {}
      throw new Error(errDetail);
    }
    if (response.status === 204) {
      return {};
    }
    return unwrapApiPayload(await response.json());
  }

  function normalizeRiderPhone(phone) {
    return safeText(phone, "").replace(/[^\d+]/g, "").slice(0, 20);
  }

  function riderProfileDefaults() {
    var existing = safeObject(state.riderApp);
    var profile = safeObject(existing.profile);
    var weekdays = Array.isArray(profile.recurrenceWeekdays) ? profile.recurrenceWeekdays : [];
    return {
      name: safeText(profile.name, ""),
      phone: normalizeRiderPhone(profile.phone || ""),
      pickup: safeText(profile.pickup, ""),
      dropoff: safeText(profile.dropoff, ""),
      notes: safeText(profile.notes, ""),
      rideType: safeText(profile.rideType, "healthcare"),
      serviceDate: safeText(profile.serviceDate, ""),
      pickupTime: safeText(profile.pickupTime, ""),
      arrivalTime: safeText(profile.arrivalTime, ""),
      tripType: safeText(profile.tripType, "one_way"),
      returnPickupType: safeText(profile.returnPickupType, "scheduled_time"),
      returnPickupTime: safeText(profile.returnPickupTime, ""),
      returnPickupAddress: safeText(profile.returnPickupAddress, ""),
      returnDropoffAddress: safeText(profile.returnDropoffAddress, ""),
      recurrence: safeText(profile.recurrence, "none"),
      recurrenceWeekdays: weekdays,
      recurrenceStartDate: safeText(profile.recurrenceStartDate, ""),
      recurrenceEndDate: safeText(profile.recurrenceEndDate, ""),
      sameDriverPreference: profile.sameDriverPreference === true || profile.sameDriverPreference === "true"
    };
  }

  function renderRiderWeekdayCheckbox(day, label, selectedDays) {
    var days = Array.isArray(selectedDays) ? selectedDays : [];
    var checked = days.indexOf(day) >= 0 ? " checked" : "";
    return '<label style="display:inline-flex;align-items:center;gap:4px;margin-right:8px"><input type="checkbox" value="' + day + '"' + checked + ' onchange="window._amiToggleRiderWeekday(\'' + day + '\', this.checked)"> ' + label + '</label>';
  }

  function riderDateTimeToIso(dateStr, timeStr) {
    var datePart = safeText(dateStr, "");
    var timePart = safeText(timeStr, "");
    if (!datePart && !timePart) {
      return null;
    }
    if (timePart.indexOf("T") >= 0) {
      var parsed = new Date(timePart);
      return isNaN(parsed.getTime()) ? null : parsed.toISOString();
    }
    if (datePart && timePart) {
      var combined = new Date(datePart + "T" + timePart);
      return isNaN(combined.getTime()) ? null : combined.toISOString();
    }
    if (datePart) {
      var dateOnly = new Date(datePart + "T00:00:00");
      return isNaN(dateOnly.getTime()) ? null : dateOnly.toISOString();
    }
    return null;
  }

  function buildRiderSchedulingPayload(formValues, options) {
    var opts = options || {};
    var forceWeekly = opts.forceWeekly === true;
    var recurrence = forceWeekly ? "weekly" : safeText(formValues.recurrence, "none");
    if (recurrence !== "weekly") {
      recurrence = "none";
    }
    var tripType = safeText(formValues.tripType, "one_way");
    var returnType = safeText(formValues.returnPickupType, "scheduled_time");
    var payload = {
      service_date: safeText(formValues.serviceDate, "") || null,
      pickup_time: riderDateTimeToIso(formValues.serviceDate, formValues.pickupTime),
      arrival_time: riderDateTimeToIso(formValues.serviceDate, formValues.arrivalTime),
      trip_type: tripType === "round_trip" ? "round_trip" : "one_way",
      return_pickup_type: returnType === "call_when_ready" ? "call_when_ready" : "scheduled_time",
      return_pickup_time: returnType === "call_when_ready"
        ? null
        : riderDateTimeToIso(formValues.serviceDate, formValues.returnPickupTime),
      recurrence: recurrence,
      recurrence_weekdays: Array.isArray(formValues.recurrenceWeekdays) ? formValues.recurrenceWeekdays : [],
      recurrence_start_date: safeText(formValues.recurrenceStartDate, formValues.serviceDate) || null,
      recurrence_end_date: safeText(formValues.recurrenceEndDate, "") || null,
      return_pickup_address: safeText(formValues.returnPickupAddress, formValues.dropoff) || null,
      return_dropoff_address: safeText(formValues.returnDropoffAddress, formValues.pickup) || null,
      same_driver_preference: formValues.sameDriverPreference === true,
      recurring: recurrence === "weekly",
      recurring_pattern: recurrence === "weekly"
        ? { type: "weekly", days: Array.isArray(formValues.recurrenceWeekdays) ? formValues.recurrenceWeekdays : [] }
        : null
    };
    if (payload.arrival_time) {
      payload.scheduled_time = payload.arrival_time;
    }
    return payload;
  }

  function mapCustomerRequestToHistoryRow(item) {
    var requestRow = safeObject(item);
    return {
      requestId: safeText(requestRow.id, ""),
      tripId: safeText(requestRow.ride_id, safeText(requestRow.id, "trip")),
      date: safeText(requestRow.created_at || requestRow.updated_at || requestRow.pending_at, "date"),
      route: safeText(requestRow.pickup_address, "Pickup") + " -> " + safeText(requestRow.dropoff_address, "Dropoff"),
      status: safeText(requestRow.dispatch_status, "pending"),
      schedulingSummary: safeText(requestRow.scheduling_summary, ""),
      tripType: safeText(requestRow.trip_type, "one_way"),
      linkedRideCount: safeNumber(requestRow.created_ride_count, 1),
      riderName: safeText(requestRow.rider_name, "Rider"),
      pickup: safeText(requestRow.pickup_address, "Pickup"),
      dropoff: safeText(requestRow.dropoff_address, "Dropoff"),
      notes: safeText(requestRow.notes, "")
    };
  }

  function applyRiderWorkspacePayload(payload) {
    var riderState = safeObject(state.riderApp);
    var profile = riderProfileDefaults();
    var history = Array.isArray(payload.history) ? payload.history.map(mapCustomerRequestToHistoryRow) : [];
    var activeRide = safeObject(payload.activeRide);
    var activeRequest = safeObject(payload.activeRequest);
    var timeline = Array.isArray(payload.timeline) ? payload.timeline : [];
    var notifications = timeline.slice(0, 6).map(function (item, index) {
      var entry = safeObject(item);
      return {
        id: safeText(entry.id || entry.event_id, "rnote-live-" + String(index + 1)),
        text: safeText(entry.description || entry.message || entry.event_type, "Ride update received"),
        level: safeText(entry.severity, "low"),
        ts: safeText(entry.created_at || entry.timestamp, "now")
      };
    });
    if (notifications.length === 0) {
      notifications = Array.isArray(riderState.notifications) ? riderState.notifications : [];
    }

    var hasActiveRide = !!(
      safeText(activeRequest.requestId || activeRequest.id, "") ||
      safeText(activeRide.id || activeRide.ride_id, "")
    );
    var tripStatus = safeText(activeRide.status || activeRequest.status, "pending").toLowerCase();
    var trackingStates = ["assigned", "offered", "accepted", "in_progress", "driver_en_route", "arrived", "pickup_complete", "rider_loaded", "trip_in_progress", "en_route_pickup"];
    var liveTracking = hasActiveRide && trackingStates.indexOf(tripStatus) >= 0;
    var driverAssigned = !!(safeText(activeRide.driver_name || activeRide.assigned_driver_name, "") && safeText(activeRide.driver_name || activeRide.assigned_driver_name, "") !== "Awaiting assignment");

    state.riderApp = {
      profile: profile,
      activeRequestId: hasActiveRide ? safeText(activeRequest.requestId || activeRequest.id, "") : "",
      submitInFlight: false,
      activeTrip: hasActiveRide ? {
        tripId: safeText(activeRide.id || activeRequest.tripId, safeText(activeRequest.ride_id, "")),
        status: safeText(activeRide.status || activeRequest.status, "pending"),
        pickup: safeText(activeRide.pickup_address || activeRide.pickup || activeRequest.pickup, profile.pickup),
        dropoff: safeText(activeRide.dropoff_address || activeRide.dropoff || activeRequest.dropoff, profile.dropoff),
        etaMin: safeText(payload.etaMinutes, activeRide.estimated_duration_minutes || "pending"),
        driverName: safeText(activeRide.driver_name || activeRide.assigned_driver_name, driverAssigned ? "Assigned driver" : "Awaiting assignment"),
        vehicle: safeText(activeRide.vehicle_id || activeRide.vehicle, driverAssigned ? "En route" : "Vehicle pending"),
        supportContact: "24/7 Rider Care"
      } : emptyRiderActiveTrip(),
      recurringSchedule: Array.isArray(riderState.recurringSchedule) ? riderState.recurringSchedule : [],
      notifications: notifications,
      tripHistory: history,
      timeline: timeline,
      lastAction: safeText(payload.lastAction, history.length > 0 ? "Rider workspace synchronized" : "Ready to request a ride"),
      lastSubmit: riderState.lastSubmit || null,
      submitStatus: hasActiveRide ? {
        level: liveTracking ? "success" : "info",
        message: liveTracking
          ? "Driver assigned — live tracking is active."
          : (safeText(riderState.submitStatus && riderState.submitStatus.message, "") || "Ride request submitted — awaiting driver assignment."),
        rideId: safeText(activeRide.id || activeRequest.ride_id || (riderState.lastSubmit && riderState.lastSubmit.rideId), ""),
        requestId: safeText(activeRequest.requestId || activeRequest.id, ""),
        status: tripStatus
      } : (riderState.submitStatus || null)
    };
  }

  async function refreshRiderWorkspaceData(options) {
    var opts = options || {};
    var profile = riderProfileDefaults();
    var phone = normalizeRiderPhone(profile.phone);
    state.riderApp = safeObject(state.riderApp);
    state.riderApp.profile = profile;
    if (!phone) {
      return;
    }

    var historyUrl = "/api/health-isf/customers/workspace/history?rider_phone=" + encodeURIComponent(phone) + "&limit=25";
    var activeUrl = "/api/health-isf/customers/workspace/active?rider_phone=" + encodeURIComponent(phone);
    var trackingUrl = "/api/health-isf/customers/workspace/live-tracking?rider_phone=" + encodeURIComponent(phone) + "&limit=40";
    var settled = await Promise.allSettled([
      fetchJson(historyUrl),
      fetchJson(activeUrl),
      fetchJson(trackingUrl)
    ]);

    var historyPayload = settled[0].status === "fulfilled" ? safeObject(unwrapApiPayload(settled[0].value)) : {};
    var activePayload = settled[1].status === "fulfilled" ? safeObject(unwrapApiPayload(settled[1].value)) : {};
    var trackingPayload = settled[2].status === "fulfilled" ? safeObject(unwrapApiPayload(settled[2].value)) : {};
    var historyRows = Array.isArray(historyPayload.history) ? historyPayload.history : [];
    var activeRequest = historyRows.map(mapCustomerRequestToHistoryRow).find(function (item) {
      var status = safeText(item.status, "").toLowerCase();
      return ["pending", "approved", "dispatchable", "broadcasted", "accepted", "assigned", "in_progress"].indexOf(status) >= 0;
    }) || null;

    applyRiderWorkspacePayload({
      history: historyRows,
      activeRide: safeObject(activePayload.active_ride || trackingPayload.active_ride),
      activeRequest: activeRequest,
      timeline: Array.isArray(trackingPayload.timeline) ? trackingPayload.timeline : [],
      etaMinutes: trackingPayload.eta_minutes,
      lastAction: opts.lastAction
    });
  }

  function dedupeBillingHandoffsByRideId(rows) {
    var seen = {};
    var out = [];
    (Array.isArray(rows) ? rows : []).forEach(function (row) {
      var rideId = safeText(row && (row.ride_id || row.rideId), "");
      if (!rideId || seen[rideId]) return;
      seen[rideId] = true;
      out.push(row);
    });
    return out;
  }

  function mapBillingHandoffRows(rows) {
    return dedupeBillingHandoffsByRideId(rows).map(function (row) {
      return {
        handoff_id: safeText(row.handoff_id, ""),
        ride_id: safeText(row.ride_id, ""),
        passenger_name: safeText(row.passenger_name, ""),
        payment_id: safeText(row.payment_transaction_id, "pending"),
        ride_price_usd: safeNumber(row.fare_amount, 0),
        driver_pay_usd: safeNumber(row.driver_pay, 0),
        platform_revenue_usd: safeNumber(row.platform_revenue, 0),
        status: safeText(row.billing_status, "pending")
      };
    });
  }

  function isSameLocalDay(value) {
    var raw = safeText(value, "");
    if (!raw) return false;
    try {
      var parsed = new Date(raw);
      if (!Number.isFinite(parsed.getTime())) return false;
      var now = new Date();
      return parsed.getFullYear() === now.getFullYear()
        && parsed.getMonth() === now.getMonth()
        && parsed.getDate() === now.getDate();
    } catch (_) {
      return false;
    }
  }

  function sumDriverPayRows(rows) {
    return (Array.isArray(rows) ? rows : []).reduce(function (total, row) {
      return total + safeNumber(row.driver_pay_usd || row.payout_amount || row.driver_pay, 0);
    }, 0);
  }

  function deriveDriverEarningsDisplayFields(earningsPayload, completedRideRows, billingHandoffRows) {
    var earnings = safeObject(earningsPayload);
    var completed = Array.isArray(completedRideRows) ? completedRideRows : [];
    var handoffs = dedupeBillingHandoffsByRideId(Array.isArray(billingHandoffRows) ? billingHandoffRows : []);
    var recentTrips = Array.isArray(earnings.recent_trips) ? earnings.recent_trips : [];
    var sourceRows = recentTrips.length ? recentTrips : completed;

    var earningsToday = safeNumber(earnings.earnings_today_usd, NaN);
    var earningsLifetime = safeNumber(earnings.earnings_lifetime_usd, NaN);
    var completedTrips = safeNumber(earnings.trip_count_today, NaN);
    if (!Number.isFinite(completedTrips) || completedTrips <= 0) {
      completedTrips = safeNumber(earnings.trip_count, NaN);
    }

    if ((!Number.isFinite(earningsLifetime) || earningsLifetime <= 0) && sourceRows.length) {
      earningsLifetime = sumDriverPayRows(sourceRows);
    }
    if (!Number.isFinite(earningsLifetime)) {
      earningsLifetime = 0;
    }

    if ((!Number.isFinite(earningsToday) || earningsToday <= 0) && sourceRows.length) {
      var todayRows = sourceRows.filter(function (row) {
        return isSameLocalDay(row.completed_at || row.updated_at || row.created_at);
      });
      if (todayRows.length) {
        earningsToday = sumDriverPayRows(todayRows);
      }
    }
    if (!Number.isFinite(earningsToday)) {
      earningsToday = 0;
    }

    if (!Number.isFinite(completedTrips) || completedTrips <= 0) {
      completedTrips = Math.max(completed.length, recentTrips.length, safeNumber(earnings.trip_count, 0));
    }

    return {
      earningsToday: earningsToday,
      earningsLifetime: earningsLifetime,
      completedTrips: completedTrips,
      billingHandoffCount: handoffs.length
    };
  }

  function syncDriverEarningsSummaryToApp(appState, earningsPayload, completedRideRows, billingHandoffRows) {
    var app = safeObject(appState);
    var display = deriveDriverEarningsDisplayFields(earningsPayload, completedRideRows, billingHandoffRows);
    app.earningsToday = display.earningsToday;
    app.earningsLifetime = display.earningsLifetime;
    app.completedTrips = Math.max(safeNumber(app.completedTrips, 0), display.completedTrips);
    if (Array.isArray(billingHandoffRows) && billingHandoffRows.length) {
      app.billingHandoffs = billingHandoffRows;
    }
    return app;
  }

  function driverWorkflowPartialFromProbe(activeRidePayload, workspacePayload, offerEnvelope, assignedRideRows) {
    var activeRide = safeObject(activeRidePayload);
    return {
      activeRide: activeRidePayload || { has_active_ride: false },
      workspace: workspacePayload,
      activeOffer: offerEnvelope,
      assignedRides: assignedRideRows || [],
      upcomingSchedule: Array.isArray(activeRide.upcoming_schedule) ? activeRide.upcoming_schedule : [],
      scheduledOffers: Array.isArray(activeRide.scheduled_offers)
        ? activeRide.scheduled_offers
        : (Array.isArray(activeRide.upcoming_schedule)
          ? activeRide.upcoming_schedule.filter(function (item) { return item && item.can_accept === true; })
          : [])
    };
  }

  function applyDriverWorkflowSnapshot(resolvedDriverId, snapshot, partial, options) {
    var opts = options || {};
    var preserveOnEmpty = opts.preserveOnEmpty === true;
    var payload = safeObject(snapshot);
    var priorWorkflow = safeObject(state.driverWorkflow);
    var priorWorkflowDriverId = safeText(priorWorkflow.driverId, "");
    var driverIdentityChanged = priorWorkflowDriverId && priorWorkflowDriverId !== safeText(resolvedDriverId, "");
    var priorApp = safeObject(state.driverApp);
    var priorTripId = priorDriverTripIdFromState();
    var earningsPayload = payload.earnings ? safeObject(payload.earnings) : safeObject(priorWorkflow.earnings);
    var completedRideRows = Array.isArray(payload.completed_rides)
      ? payload.completed_rides
      : (Array.isArray(priorWorkflow.completedRides) ? priorWorkflow.completedRides : []);
    var billingHandoffRows = Array.isArray(payload.billing_handoffs)
      ? mapBillingHandoffRows(payload.billing_handoffs)
      : (Array.isArray(priorWorkflow.billingHandoffs) ? priorWorkflow.billingHandoffs : []);
    var documentRows = Array.isArray(payload.documents)
      ? payload.documents
      : (Array.isArray(priorWorkflow.documents) ? priorWorkflow.documents : []);

    var nextActiveRide = partial.activeRide != null ? partial.activeRide : priorWorkflow.activeRide;
    var nextWorkspace = partial.workspace != null ? partial.workspace : priorWorkflow.workspace;
    var nextActiveOffer = partial.activeOffer != null ? partial.activeOffer : priorWorkflow.activeOffer;
    var nextAssignedRides = Array.isArray(partial.assignedRides)
      ? partial.assignedRides
      : (Array.isArray(priorWorkflow.assignedRides) ? priorWorkflow.assignedRides : []);
    var nextUpcomingSchedule = Array.isArray(partial.upcomingSchedule)
      ? partial.upcomingSchedule
      : (driverIdentityChanged ? [] : (Array.isArray(priorWorkflow.upcomingSchedule) ? priorWorkflow.upcomingSchedule : []));
    var nextScheduledOffers = Array.isArray(partial.scheduledOffers)
      ? partial.scheduledOffers
      : (driverIdentityChanged ? [] : (Array.isArray(priorWorkflow.scheduledOffers) ? priorWorkflow.scheduledOffers : []));

    var priorActiveRide = safeObject(priorWorkflow.activeRide);
    var priorRideId = safeText((safeObject(priorActiveRide.ride)).id, "") || priorTripId;
    var priorRideStatus = normalizeRideStatusToken(
      (safeObject(priorActiveRide.ride)).lifecycle_state
        || (safeObject(priorActiveRide.ride)).status
        || priorActiveRide.assignment_state
    );
    var priorRideTerminal = priorRideId && isTerminalRideStatus(priorRideStatus);
    var incomingActiveRide = safeObject(partial.activeRide);
    var incomingRideId = safeText((safeObject(incomingActiveRide.ride)).id, "");
    var priorTripCompleted = priorTripCompletedInSnapshot(priorRideId, payload) || priorRideTerminal;
    if (
      partial.activeRide != null
      && priorActiveRide.has_active_ride === true
      && priorRideId
      && !priorTripCompleted
      && incomingActiveRide.has_active_ride !== true
      && (!incomingRideId || incomingRideId !== priorRideId)
    ) {
      nextActiveRide = priorActiveRide;
    }
    if (
      Array.isArray(partial.assignedRides)
      && partial.assignedRides.length === 0
      && Array.isArray(priorWorkflow.assignedRides)
      && priorWorkflow.assignedRides.length > 0
      && priorRideId
      && !priorTripCompleted
    ) {
      var priorStillAssigned = priorWorkflow.assignedRides.some(function (row) {
        return safeText(row.id || row.ride_id, "") === priorRideId;
      });
      if (priorStillAssigned) {
        nextAssignedRides = priorWorkflow.assignedRides;
      }
    }

    if (preserveOnEmpty && !driverIdentityChanged) {
      if (partial.activeRide == null) nextActiveRide = priorWorkflow.activeRide;
      if (partial.workspace == null) nextWorkspace = priorWorkflow.workspace;
      if (partial.activeOffer == null) nextActiveOffer = priorWorkflow.activeOffer;
      if (!Array.isArray(partial.assignedRides)) {
        nextAssignedRides = Array.isArray(priorWorkflow.assignedRides) ? priorWorkflow.assignedRides : [];
      }
      if (!payload.earnings) earningsPayload = safeObject(priorWorkflow.earnings);
      if (!Array.isArray(payload.completed_rides)) {
        completedRideRows = Array.isArray(priorWorkflow.completedRides) ? priorWorkflow.completedRides : [];
      }
      if (!Array.isArray(payload.billing_handoffs)) {
        billingHandoffRows = Array.isArray(priorWorkflow.billingHandoffs) ? priorWorkflow.billingHandoffs : [];
      }
    }

    state.driverWorkflow = {
      driverId: resolvedDriverId,
      workspace: nextWorkspace,
      activeRide: nextActiveRide,
      activeOffer: nextActiveOffer,
      assignedRides: nextAssignedRides,
      upcomingSchedule: nextUpcomingSchedule,
      scheduledOffers: nextScheduledOffers,
      completedRides: completedRideRows,
      billingHandoffs: billingHandoffRows,
      documents: documentRows,
      earnings: earningsPayload
    };

    state.driverApp = safeObject(state.driverApp);
    state.driverApp.currentDriverId = resolvedDriverId;
    state.driverApp.secondaryTab = safeText(priorApp.secondaryTab, "earnings") || "earnings";
    syncDriverEarningsSummaryToApp(state.driverApp, earningsPayload, completedRideRows, billingHandoffRows);
    if (completedRideRows.length) {
      state.driverApp.completedRideHistory = completedRideRows;
    } else if (Array.isArray(priorApp.completedRideHistory) && priorApp.completedRideHistory.length) {
      state.driverApp.completedRideHistory = priorApp.completedRideHistory;
    } else {
      state.driverApp.completedRideHistory = [];
    }
    if (billingHandoffRows.length) {
      state.driverApp.billingHandoffs = billingHandoffRows;
    } else if (Array.isArray(priorApp.billingHandoffs) && priorApp.billingHandoffs.length) {
      state.driverApp.billingHandoffs = priorApp.billingHandoffs;
    } else {
      state.driverApp.billingHandoffs = [];
    }
    state.driverApp.documents = documentRows.length
      ? documentRows.map(function (doc) {
          return {
            name: safeText(doc.title || doc.name, safeText(doc.document_type, "Document")),
            status: safeText(doc.status, "issued"),
            expiresIn: safeText(doc.reference || doc.expiresIn, "n/a"),
            amount_usd: safeNumber(doc.amount_usd, 0),
            ride_id: safeText(doc.ride_id, ""),
            document_type: safeText(doc.document_type, "")
          };
        })
      : (Array.isArray(priorApp.documents) ? priorApp.documents : []);
    driverLastConfirmedWorkflow = {
      driverId: resolvedDriverId,
      activeRide: nextActiveRide,
      workspace: nextWorkspace,
      activeOffer: nextActiveOffer,
      assignedRides: nextAssignedRides,
      upcomingSchedule: nextUpcomingSchedule,
      scheduledOffers: nextScheduledOffers,
      earnings: earningsPayload,
      completedRides: completedRideRows,
      billingHandoffs: billingHandoffRows
    };
    var confirmedActiveRide = safeObject(nextActiveRide);
    var confirmedRideRow = safeObject(confirmedActiveRide.ride);
    var confirmedRideStatus = normalizeRideStatusToken(
      confirmedRideRow.lifecycle_state || confirmedRideRow.status || confirmedActiveRide.assignment_state
    );
    var hasOpenWorkload = (
      confirmedActiveRide.has_active_ride === true
      && confirmedRideStatus
      && TERMINAL_RIDE_STATUSES.indexOf(confirmedRideStatus) < 0
    ) || (
      Array.isArray(nextAssignedRides)
      && nextAssignedRides.some(function (row) {
        return !isTerminalRideStatus(row.lifecycle_state || row.status);
      })
    ) || !!safeText((safeObject(nextActiveOffer.offer)).ride_id, "");
    if (!hasOpenWorkload) {
      driverLastConfirmedWorkflow = null;
    }
  }

  async function refreshDriverWorkflowData(options) {
    if (driverWorkflowRefreshPromise) {
      return driverWorkflowRefreshPromise;
    }
    driverWorkflowRefreshPromise = refreshDriverWorkflowDataImpl(options).finally(function () {
      driverWorkflowRefreshPromise = null;
    });
    return driverWorkflowRefreshPromise;
  }

  async function refreshDriverWorkflowDataImpl(options) {
    var opts = options || {};
    var refreshSeq = ++driverWorkflowRefreshSeq;
    var token = opts.token || getAccessToken();
    var mobileCtx = getCanonicalMobileDriverContext();
    var driverSessionToken = mobileCtx.sessionToken || getDriverSessionToken();
    var roleView = safeText(state.role, "").toLowerCase();
    var driverMobileView = isDriverMobileSurface() || roleView === "driver";
    if (isDriverMobileAppRoute() && mobileCtx.authenticated) {
      state.driverApp = safeObject(state.driverApp);
      var priorMobileUi = safeText(state.driverApp.mobileUiState, "loading_assignment");
      if (
        !priorMobileUi
        || priorMobileUi === "awaiting_assignment"
        || priorMobileUi === "api_error"
      ) {
        state.driverApp.mobileUiState = "loading_assignment";
      }
      if (priorMobileUi === "api_error") {
        clearDriverMobileSyncError();
      }
      state.driverApp.currentDriverId = mobileCtx.driverId;
      state.driverApp.shiftOnline = true;
    }
    if (opts.forceReset === true) {
      var resetApp = safeObject(state.driverApp);
      resetApp.activeTripId = "";
      resetApp.activeStage = "queued";
      resetApp.tripQueue = [];
      state.driverApp = resetApp;
    }
    if (!token && !driverSessionToken) {
      if (driverMobileView && driverLastConfirmedWorkflow) {
        markDriverSyncWarning("Authentication required. Showing last confirmed driver trip.");
        return;
      }
      if (isDriverMobileAppRoute()) {
        state.driverApp = safeObject(state.driverApp);
        state.driverApp.mobileUiState = "login_required";
        logDriverMobileRefreshSync({
          event: "assignment_refresh_auth_required",
          frontend_state_transition: "session_missing->login_required",
          next_ui_state: "login_required",
          api_response: { reason: "missing_platform_and_driver_session" }
        });
        scheduleRenderPage();
        return;
      }
      clearDriverLiveTripState({ resetBoundIdentity: true });
      return;
    }

    var resolvedDriverId = "";
    if (driverMobileView) {
      if (isDriverMobileSurface()) {
        var mobileAuth = await resolveDriverMobileAuth(token);
        if (!mobileAuth.valid) {
          logDriverPoll({
            seq: refreshSeq,
            driver_id: "",
            applied: false,
            ignored_reason: "driver_login_required",
            auth_role: mobileAuth.auth_role
          });
          scheduleRenderPage();
          return;
        }
        resolvedDriverId = bindDriverIdentity(mobileAuth.driver_id);
      } else {
        resolvedDriverId = await resolveBoundDriverId(token, { forceRebind: opts.forceReset === true });
      }
    } else {
      var liveWorkflow = safeObject(state.liveWorkflow);
      var activeAssignments = Array.isArray(liveWorkflow.activeAssignments) ? liveWorkflow.activeAssignments : [];
      var existingDriverId = safeText((safeObject(state.driverWorkflow)).driverId, "");
      var driverCandidates = [];
      function pushDriverCandidate(list, candidate) {
        var normalized = safeText(candidate, "");
        if (!normalized || list.indexOf(normalized) >= 0) return;
        list.push(normalized);
      }
      filterActiveOperationalRides(Array.isArray(liveWorkflow.rides) ? liveWorkflow.rides : []).forEach(function (ride) {
        pushDriverCandidate(driverCandidates, safeText(ride.driver_id, ""));
      });
      activeAssignments.forEach(function (item) {
        pushDriverCandidate(driverCandidates, safeText(item.driver_id, ""));
      });
      pushDriverCandidate(driverCandidates, existingDriverId);
      pushDriverCandidate(driverCandidates, safeText((safeObject(state.driverApp)).currentDriverId, ""));
      resolvedDriverId = safeText(driverCandidates[0], "");
    }

    if (!resolvedDriverId) {
      logDriverPoll({
        seq: refreshSeq,
        driver_id: "",
        applied: false,
        ignored_reason: "missing_bound_driver_id"
      });
      if (driverMobileView && driverLastConfirmedWorkflow) {
        markDriverSyncWarning("Unable to resolve authenticated driver identity. Showing last confirmed trip.");
        return;
      }
      return;
    }
    bindDriverIdentity(resolvedDriverId);

    var fetchOpts = {};
    var driverBase = "/api/health-isf/drivers/" + encodeURIComponent(resolvedDriverId);
    var criticalProbe = await Promise.allSettled([
      fetchJson(driverBase + "/active-ride", fetchOpts, token),
      fetchJson(driverBase + "/live-workspace", fetchOpts, token),
      fetchJson(driverBase + "/active-offer", fetchOpts, token)
    ]);
    var completionProbe = await Promise.allSettled([
      fetchJson(driverBase + "/completion-snapshot?limit=50", fetchOpts, token)
    ]);
    var assignedProbeResult;
    if (isDriverMobileAppRoute()) {
      assignedProbeResult = await Promise.race([
        Promise.resolve(
          fetchJson(driverBase + "/assigned-rides?limit=15", fetchOpts, token)
        ).then(function (value) {
          return { status: "fulfilled", value: value };
        }, function (reason) {
          return { status: "rejected", reason: reason };
        }),
        new Promise(function (resolve) {
          setTimeout(function () {
            resolve({ status: "rejected", reason: new Error("assigned_rides_deferred") });
          }, DRIVER_MOBILE_FETCH_TIMEOUT_MS);
        })
      ]);
    } else {
      var assignedSettled = await Promise.allSettled([
        fetchJson(driverBase + "/assigned-rides", fetchOpts, token)
      ]);
      assignedProbeResult = assignedSettled[0];
    }
    var probe = [
      criticalProbe[0],
      criticalProbe[1],
      criticalProbe[2],
      assignedProbeResult
    ];

    if (refreshSeq !== driverWorkflowRefreshSeq) {
      logDriverPoll({
        seq: refreshSeq,
        driver_id: resolvedDriverId,
        applied: false,
        ignored_reason: "stale_sequence",
        latest_seq: driverWorkflowRefreshSeq
      });
      return;
    }
    if (refreshSeq < driverLastAppliedRefreshSeq) {
      logDriverPoll({
        seq: refreshSeq,
        driver_id: resolvedDriverId,
        applied: false,
        ignored_reason: "older_than_last_applied",
        last_applied_seq: driverLastAppliedRefreshSeq
      });
      return;
    }
    function probeStatus(index) {
      if (!probe[index]) return "missing";
      if (probe[index].status === "fulfilled") return 200;
      var reason = safeText(probe[index].reason && probe[index].reason.message, "error");
      var match = reason.match(/http_(\d+)/);
      return match ? Number(match[1]) : "failed";
    }

    function completionProbeStatus() {
      if (!completionProbe[0]) return "missing";
      if (completionProbe[0].status === "fulfilled") return 200;
      var completionReason = safeText(completionProbe[0].reason && completionProbe[0].reason.message, "error");
      var completionMatch = completionReason.match(/http_(\d+)/);
      return completionMatch ? Number(completionMatch) : "failed";
    }

    function driverCoreProbeAuthFailed() {
      var statuses = [probeStatus(0), probeStatus(1), probeStatus(2), probeStatus(3)];
      var authFailures = statuses.filter(function (status) {
        return status === 401 || status === 403;
      }).length;
      return authFailures >= 2;
    }

    function driverCoreProbeNotFound() {
      var statuses = [probeStatus(0), probeStatus(1), probeStatus(2), probeStatus(3)];
      var notFound = statuses.filter(function (status) {
        return status === 404;
      }).length;
      return notFound >= 2;
    }

    function invalidateDriverMobileSession(message) {
      clearPersistedDriverSession();
      driverMobileAuthCache = null;
      state.driverApp = safeObject(state.driverApp);
      state.driverApp.mobileUiState = "login_required";
      state.driverApp.currentDriverId = "";
      state.driverApp.activeTripId = "";
      state.driverApp.tripQueue = [];
      state.driverApp.mobileLogin = safeObject(state.driverApp.mobileLogin);
      state.driverApp.mobileLogin.status = "Not signed in";
      state.driverApp.mobileLogin.error = safeText(message, "Driver session invalid.");
      markDriverSyncWarning(safeText(message, "Driver session invalid. Sign in again."));
    }

    var activeRidePayload = probe[0].status === "fulfilled" ? safeObject(probe[0].value) : null;
    var workspacePayload = probe[1].status === "fulfilled" ? safeObject(probe[1].value) : null;
    var offerEnvelope = probe[2].status === "fulfilled" ? safeObject(probe[2].value) : null;
    var assignedRideRows = probe[3].status === "fulfilled" && Array.isArray(probe[3].value) ? probe[3].value : null;
    var completionSnapshot = completionProbe[0] && completionProbe[0].status === "fulfilled"
      ? safeObject(completionProbe[0].value)
      : null;

    var activeRideOk = probe[0].status === "fulfilled";
    var workspaceOk = probe[1].status === "fulfilled";
    var offerOk = probe[2].status === "fulfilled";
    var assignedOk = probe[3].status === "fulfilled";
    var completionOk = !!(completionProbe[0] && completionProbe[0].status === "fulfilled");
    var driverMobileCoreHealthy = activeRideOk || workspaceOk || offerOk;
    var coreProbeOk = driverMobileCoreHealthy || assignedOk;
    var apiHealthy = isDriverMobileAppRoute() ? driverMobileCoreHealthy : coreProbeOk;
    var returnedRideId = safeText((safeObject(activeRidePayload && activeRidePayload.ride)).id, "");
    var lifecycleState = safeText(
      activeRidePayload && (activeRidePayload.assignment_state || (activeRidePayload.ride && (activeRidePayload.ride.lifecycle_state || activeRidePayload.ride.status))),
      ""
    );

    var priorWorkflow = safeObject(state.driverWorkflow);
    var priorWorkflowDriverId = safeText(priorWorkflow.driverId, "");
    var priorTripId = priorDriverTripIdFromState();
    if (priorWorkflowDriverId && priorWorkflowDriverId !== resolvedDriverId) {
      driverLastConfirmedWorkflow = null;
    }
    var openAssignment = driverRefreshHasOpenAssignment(activeRidePayload, assignedRideRows || [], offerEnvelope);
    var authoritativeEmpty = apiHealthy && !openAssignment;
    var priorCompleted = priorTripCompletedInSnapshot(priorTripId, completionSnapshot);
    var wouldClearActiveTrip = driverRefreshWouldClearActiveTrip(
      priorTripId,
      activeRidePayload,
      assignedRideRows,
      offerEnvelope,
      completionSnapshot
    );
    var preserveOnEmpty = !apiHealthy || (wouldClearActiveTrip && priorTripId && !priorCompleted && !authoritativeEmpty);
    if (priorWorkflowDriverId && priorWorkflowDriverId !== resolvedDriverId) {
      preserveOnEmpty = false;
    }
    if (isDriverMobileAppRoute() && driverMobileCoreHealthy && openAssignment) {
      preserveOnEmpty = false;
    }
    var incomingTripIds = driverRefreshCollectTripIds(activeRidePayload, assignedRideRows || [], offerEnvelope);
    var hasFreshOpenAssignment = openAssignment && apiHealthy && incomingTripIds.some(function (tripId) {
      return !!tripId && tripId !== priorTripId;
    });
    if (hasFreshOpenAssignment) {
      preserveOnEmpty = false;
    }
    if (priorTripId && isTerminalRideStatus(
      normalizeRideStatusToken(
        (safeObject(priorWorkflow.activeRide && priorWorkflow.activeRide.ride)).lifecycle_state
          || (safeObject(priorWorkflow.activeRide && priorWorkflow.activeRide.ride)).status
          || (safeObject(priorWorkflow.activeRide)).assignment_state
      )
    )) {
      preserveOnEmpty = false;
    }
    var responseObservedAt = Date.now();

    if (refreshSeq < driverLastAppliedRefreshSeq) {
      logDriverPoll({
        seq: refreshSeq,
        driver_id: resolvedDriverId,
        applied: false,
        ignored_reason: "older_than_last_applied",
        last_applied_seq: driverLastAppliedRefreshSeq,
        observed_at: responseObservedAt
      });
      return;
    }
    if (responseObservedAt + 5 < driverLastAppliedObservedAt) {
      logDriverPoll({
        seq: refreshSeq,
        driver_id: resolvedDriverId,
        applied: false,
        ignored_reason: "stale_observed_at",
        last_applied_at: driverLastAppliedObservedAt,
        observed_at: responseObservedAt
      });
      return;
    }

    if (preserveOnEmpty) {
      if (isDriverMobileSurface() && authoritativeEmpty && apiHealthy) {
        resetDriverMobileAfterCompletion();
        clearDriverSyncWarning();
        state.driverApp = safeObject(state.driverApp);
        state.driverApp.mobileBootstrapError = "";
        applyDriverWorkflowSnapshot(
          resolvedDriverId,
          completionOk ? completionSnapshot : null,
          driverWorkflowPartialFromProbe(activeRidePayload, workspacePayload, offerEnvelope, assignedRideRows),
          { preserveOnEmpty: false }
        );
        driverLastAppliedRefreshSeq = refreshSeq;
        driverLastAppliedObservedAt = responseObservedAt;
        ensureDriverMobileState(null);
        scheduleRenderPage(0);
        return;
      }
      if (isDriverMobileAppRoute() && !driverMobileCoreHealthy) {
        state.driverApp = safeObject(state.driverApp);
        var priorUiOnApiError = safeText(state.driverApp.mobileUiState, "loading_assignment");
        if (driverCoreProbeNotFound()) {
          invalidateDriverMobileSession(
            "Driver profile was not found on this server. Sign in again with your registered driver phone."
          );
          logDriverMobileRefreshSync({
            event: "assignment_refresh_driver_not_found",
            requested_ride_id: returnedRideId,
            assignment_state: lifecycleState,
            api_response: {
              http_status: {
                active_ride: probeStatus(0),
                live_workspace: probeStatus(1),
                active_offer: probeStatus(2),
                assigned_rides: probeStatus(3),
                completion_snapshot: completionProbeStatus()
              }
            },
            frontend_state_transition: priorUiOnApiError + "->login_required",
            next_ui_state: "login_required",
            extra: { refresh_seq: refreshSeq, ignored_reason: "driver_profile_not_found" }
          });
          ensureDriverMobileState(null);
          scheduleRenderPage(0);
          return;
        }
        if (driverCoreProbeAuthFailed()) {
          invalidateDriverMobileSession("Driver session expired. Sign in with your registered phone again.");
          logDriverMobileRefreshSync({
            event: "assignment_refresh_auth_expired",
            requested_ride_id: returnedRideId,
            assignment_state: lifecycleState,
            api_response: {
              http_status: {
                active_ride: probeStatus(0),
                live_workspace: probeStatus(1),
                active_offer: probeStatus(2),
                assigned_rides: probeStatus(3),
                completion_snapshot: completionProbeStatus()
              }
            },
            frontend_state_transition: priorUiOnApiError + "->login_required",
            next_ui_state: "login_required",
            extra: { refresh_seq: refreshSeq, ignored_reason: "driver_session_auth_failed" }
          });
          ensureDriverMobileState(null);
          scheduleRenderPage(0);
          return;
        }
        state.driverApp.mobileUiState = "api_error";
        state.driverApp.shiftOnline = true;
        state.driverApp.currentDriverId = resolvedDriverId;
        markDriverSyncWarning("Driver assignment sync failed. Retry sync or sign out and sign in again.");
        logDriverMobileRefreshSync({
          event: "assignment_refresh_failed",
          requested_ride_id: returnedRideId,
          assignment_state: lifecycleState,
          api_response: {
            active_ride: activeRidePayload,
            assigned_rides_count: Array.isArray(assignedRideRows) ? assignedRideRows.length : null,
            http_status: {
              active_ride: probeStatus(0),
              live_workspace: probeStatus(1),
              active_offer: probeStatus(2),
              assigned_rides: probeStatus(3),
              completion_snapshot: completionProbeStatus()
            }
          },
          http_status: probeStatus(0),
          route: driverBase + "/active-ride",
          frontend_state_transition: priorUiOnApiError + "->api_error",
          next_ui_state: "api_error",
          extra: { refresh_seq: refreshSeq, ignored_reason: "partial_or_failed_response" }
        });
        ensureDriverMobileState(null);
        scheduleRenderPage(0);
        return;
      }
      markDriverSyncWarning("Driver refresh incomplete. Showing last confirmed trip.");
      logDriverPoll({
        seq: refreshSeq,
        driver_id: resolvedDriverId,
        http_status: {
          active_ride: probeStatus(0),
          live_workspace: probeStatus(1),
          active_offer: probeStatus(2),
          assigned_rides: probeStatus(3),
          completion_snapshot: completionProbeStatus()
        },
        returned_ride_id: returnedRideId,
        lifecycle_state: lifecycleState,
        applied: false,
        ignored_reason: !apiHealthy
          ? "partial_or_failed_response"
          : (wouldClearActiveTrip ? "active_trip_downgrade_rejected" : "authoritative_empty_rejected"),
        observed_at: responseObservedAt
      });
      if (driverLastConfirmedWorkflow && safeText(driverLastConfirmedWorkflow.driverId, "") === resolvedDriverId) {
        if (!authoritativeEmpty) {
          applyDriverWorkflowSnapshot(
            resolvedDriverId,
            completionOk ? completionSnapshot : null,
            {
              activeRide: driverLastConfirmedWorkflow.activeRide,
              workspace: driverLastConfirmedWorkflow.workspace,
              activeOffer: driverLastConfirmedWorkflow.activeOffer,
              assignedRides: driverLastConfirmedWorkflow.assignedRides
            },
            { preserveOnEmpty: true }
          );
        } else {
          driverLastConfirmedWorkflow = null;
        }
      } else if (priorTripId && priorWorkflow.activeRide && !authoritativeEmpty) {
        applyDriverWorkflowSnapshot(
          resolvedDriverId,
          completionOk ? completionSnapshot : null,
          {
            activeRide: priorWorkflow.activeRide,
            workspace: priorWorkflow.workspace,
            activeOffer: priorWorkflow.activeOffer,
            assignedRides: Array.isArray(priorWorkflow.assignedRides) ? priorWorkflow.assignedRides : []
          },
          { preserveOnEmpty: true }
        );
      }
      if (isDriverMobileSurface()) {
        if (authoritativeEmpty && apiHealthy) {
          resetDriverMobileAfterCompletion();
          clearDriverSyncWarning();
          state.driverApp = safeObject(state.driverApp);
          state.driverApp.mobileBootstrapError = "";
          ensureDriverMobileState(null);
          scheduleRenderPage(0);
          return;
        }
        if (driverMobileCoreHealthy && openAssignment) {
          applyDriverWorkflowSnapshot(
            resolvedDriverId,
            completionOk ? completionSnapshot : null,
            driverWorkflowPartialFromProbe(activeRidePayload, workspacePayload, offerEnvelope, assignedRideRows),
            { preserveOnEmpty: false }
          );
          driverLastAppliedRefreshSeq = refreshSeq;
          driverLastAppliedObservedAt = responseObservedAt;
          clearDriverMobileSyncError();
          ensureDriverMobileState(null);
          scheduleRenderPage(0);
          return;
        }
        state.driverApp = safeObject(state.driverApp);
        var priorUiOnStale = safeText(state.driverApp.mobileUiState, "loading_assignment");
        state.driverApp.mobileUiState = "api_error";
        markDriverSyncWarning("Unable to confirm active assignment. Retry sync or wait for dispatch.");
        logDriverMobileRefreshSync({
          event: "assignment_refresh_preserved_stale",
          requested_ride_id: returnedRideId,
          assignment_state: lifecycleState,
          api_response: {
            active_ride: activeRidePayload,
            assigned_rides_count: Array.isArray(assignedRideRows) ? assignedRideRows.length : null,
            http_status: {
              active_ride: probeStatus(0),
              live_workspace: probeStatus(1),
              active_offer: probeStatus(2),
              assigned_rides: probeStatus(3),
              completion_snapshot: completionProbeStatus()
            }
          },
          route: driverBase + "/active-ride",
          frontend_state_transition: priorUiOnStale + "->api_error",
          next_ui_state: "api_error",
          extra: {
            refresh_seq: refreshSeq,
            ignored_reason: !apiHealthy
              ? "partial_or_failed_response"
              : (wouldClearActiveTrip ? "active_trip_downgrade_rejected" : "authoritative_empty_rejected")
          }
        });
        ensureDriverMobileState(null);
        scheduleRenderPage(0);
      }
      return;
    }

    clearDriverSyncWarning();
    state.driverApp = safeObject(state.driverApp);
    state.driverApp.mobileBootstrapError = "";
    var offerPayload = safeObject(offerEnvelope && offerEnvelope.offer);
    if (
      offerPayload
      && isProofOrDemoTripMeta(
        offerPayload.passenger_name,
        offerPayload.pickup_address,
        offerPayload.dropoff_address,
        offerPayload.notes
      )
    ) {
      offerEnvelope = { offer: null };
    }

    applyDriverWorkflowSnapshot(
      resolvedDriverId,
      completionSnapshot,
      driverWorkflowPartialFromProbe(activeRidePayload, workspacePayload, offerEnvelope, assignedRideRows),
      { preserveOnEmpty: !completionOk }
    );
    driverLastAppliedRefreshSeq = refreshSeq;
    driverLastAppliedObservedAt = responseObservedAt;

    logDriverPoll({
      seq: refreshSeq,
      driver_id: resolvedDriverId,
      http_status: {
        active_ride: probeStatus(0),
        live_workspace: probeStatus(1),
        active_offer: probeStatus(2),
        assigned_rides: probeStatus(3),
        completion_snapshot: completionProbeStatus()
      },
      returned_ride_id: returnedRideId,
      lifecycle_state: lifecycleState,
      has_active_ride: !!(activeRidePayload && activeRidePayload.has_active_ride),
      assigned_count: Array.isArray(assignedRideRows) ? assignedRideRows.length : 0,
      applied: true,
      ignored_reason: "",
      observed_at: responseObservedAt,
      last_applied_seq: driverLastAppliedRefreshSeq
    });
    var nextMobileUiState = openAssignment ? "active_ride" : "awaiting_assignment";
    if (isDriverMobileAppRoute()) {
      state.driverApp = safeObject(state.driverApp);
      var priorMobileUi = safeText(state.driverApp.mobileUiState, "loading_assignment");
      state.driverApp.mobileUiState = nextMobileUiState;
      restartDriverMobilePollInterval();
      logDriverMobileRefreshSync({
        event: "assignment_refresh_applied",
        requested_ride_id: returnedRideId,
        assignment_state: lifecycleState,
        api_response: {
          has_active_ride: !!(activeRidePayload && activeRidePayload.has_active_ride),
          assignment_state: lifecycleState,
          ride_id: returnedRideId,
          assigned_count: Array.isArray(assignedRideRows) ? assignedRideRows.length : 0,
          http_status: {
            active_ride: probeStatus(0),
            live_workspace: probeStatus(1),
            active_offer: probeStatus(2),
            assigned_rides: probeStatus(3),
            completion_snapshot: completionProbeStatus()
          }
        },
        http_status: 200,
        route: driverBase + "/active-ride",
        frontend_state_transition: priorMobileUi + "->" + nextMobileUiState,
        next_ui_state: nextMobileUiState,
        extra: { refresh_seq: refreshSeq, applied: true }
      });
    }

    if (isDriverMobileSurface()) {
      ensureDriverMobileState(null);
      if (isDriverMobileSessionRoute()) {
        var appAfterHydration = safeObject(state.driverApp);
        var offerRow = safeObject(offerEnvelope && offerEnvelope.offer);
        var activeRideRow = safeObject(activeRidePayload && activeRidePayload.ride);
        var activeAssignmentRow = safeObject(activeRidePayload && activeRidePayload.active_assignment);
        var assignmentDriverId = resolveAssignmentDriverId(offerRow)
          || resolveAssignmentDriverId(activeAssignmentRow)
          || resolveRideDriverId(activeRideRow)
          || null;
        var hydrationRideId = safeText(appAfterHydration.activeTripId, "")
          || returnedRideId
          || safeText(offerRow.ride_id, "")
          || null;
        logDriverMobileAssignmentSync({
          event: "mobile_hydration_summary",
          authenticated_driver_id: resolvedDriverId,
          assignment_driver_id: assignmentDriverId,
          requested_ride_id: hydrationRideId,
          assignment_state: lifecycleState || safeText(offerRow.assignment_state, "") || null,
          api_response: {
            active_offer: offerEnvelope,
            active_ride: activeRidePayload,
            trip_queue_len: Array.isArray(appAfterHydration.tripQueue) ? appAfterHydration.tripQueue.length : 0,
            active_trip_id: safeText(appAfterHydration.activeTripId, "") || null,
            mobile_ui_state: safeText(appAfterHydration.mobileUiState, "")
          },
          route: driverBase + "/active-offer",
          http_status: probeStatus(2),
          extra: {
            refresh_seq: refreshSeq,
            open_assignment: openAssignment,
            hydration_reason: Array.isArray(appAfterHydration.tripQueue) && appAfterHydration.tripQueue.length
              ? "accepted_trips_in_queue"
              : (openAssignment ? "api_open_assignment" : "awaiting_assignment")
          }
        });
      }
      scheduleRenderPage(0);
    }

    if (opts.lastAction) {
      state.driverApp = safeObject(state.driverApp);
      state.driverApp.lastStatusUpdate = safeText(opts.lastAction, "Driver workspace synchronized");
    }
  }

  function readRiderFormValues() {
    var currentProfile = riderProfileDefaults();
    var nameInput = document.getElementById("rider-name-input");
    var phoneInput = document.getElementById("rider-phone-input");
    var pickupInput = document.getElementById("rider-pickup-input");
    var dropoffInput = document.getElementById("rider-dropoff-input");
    var notesInput = document.getElementById("rider-notes-input");
    var rideTypeInput = document.getElementById("rider-ride-type-input");
    var serviceDateInput = document.getElementById("rider-service-date-input");
    var pickupTimeInput = document.getElementById("rider-pickup-time-input");
    var arrivalTimeInput = document.getElementById("rider-arrival-time-input");
    var tripTypeInput = document.getElementById("rider-trip-type-input");
    var returnTypeInput = document.getElementById("rider-return-type-input");
    var returnTimeInput = document.getElementById("rider-return-time-input");
    var returnPickupInput = document.getElementById("rider-return-pickup-input");
    var returnDropoffInput = document.getElementById("rider-return-dropoff-input");
    var recurrenceInput = document.getElementById("rider-recurrence-input");
    var recurrenceStartInput = document.getElementById("rider-recurrence-start-input");
    var recurrenceEndInput = document.getElementById("rider-recurrence-end-input");
    var sameDriverInput = document.getElementById("rider-same-driver-input");
    return {
      name: safeText(nameInput && nameInput.value, currentProfile.name),
      phone: normalizeRiderPhone(phoneInput && phoneInput.value || currentProfile.phone),
      pickup: safeText(pickupInput && pickupInput.value, currentProfile.pickup),
      dropoff: safeText(dropoffInput && dropoffInput.value, currentProfile.dropoff),
      notes: safeText(notesInput && notesInput.value, currentProfile.notes),
      rideType: safeText(rideTypeInput && rideTypeInput.value, currentProfile.rideType),
      serviceDate: safeText(serviceDateInput && serviceDateInput.value, currentProfile.serviceDate),
      pickupTime: safeText(pickupTimeInput && pickupTimeInput.value, currentProfile.pickupTime),
      arrivalTime: safeText(arrivalTimeInput && arrivalTimeInput.value, currentProfile.arrivalTime),
      tripType: safeText(tripTypeInput && tripTypeInput.value, currentProfile.tripType),
      returnPickupType: safeText(returnTypeInput && returnTypeInput.value, currentProfile.returnPickupType),
      returnPickupTime: safeText(returnTimeInput && returnTimeInput.value, currentProfile.returnPickupTime),
      returnPickupAddress: safeText(returnPickupInput && returnPickupInput.value, currentProfile.returnPickupAddress),
      returnDropoffAddress: safeText(returnDropoffInput && returnDropoffInput.value, currentProfile.returnDropoffAddress),
      recurrence: safeText(recurrenceInput && recurrenceInput.value, currentProfile.recurrence),
      recurrenceWeekdays: Array.isArray(currentProfile.recurrenceWeekdays) ? currentProfile.recurrenceWeekdays.slice() : [],
      recurrenceStartDate: safeText(recurrenceStartInput && recurrenceStartInput.value, currentProfile.recurrenceStartDate),
      recurrenceEndDate: safeText(recurrenceEndInput && recurrenceEndInput.value, currentProfile.recurrenceEndDate),
      sameDriverPreference: !!(sameDriverInput ? sameDriverInput.checked : currentProfile.sameDriverPreference)
    };
  }

  function makeRiderIdempotencyKey() {
    if (window.crypto && typeof window.crypto.randomUUID === "function") {
      return "rider-submit-" + window.crypto.randomUUID();
    }
    return "rider-submit-" + Date.now() + "-" + Math.random().toString(36).slice(2, 10);
  }

  async function recoverCustomerRequestByIdempotency(idempotencyKey, options) {
    var key = safeText(idempotencyKey, "");
    if (!key) {
      return null;
    }
    var opts = options || {};
    var attempts = safeNumber(opts.maxAttempts, RIDER_RECOVERY_MAX_ATTEMPTS);
    for (var i = 0; i < attempts; i += 1) {
      try {
        var url = "/api/health-isf/customer-requests/idempotency/" + encodeURIComponent(key);
        var response = await authorizedFetch(withOrganizationScope(url), {
          method: "GET",
          headers: { "Accept": "application/json" }
        }, 15000);
        if (response.status === 202) {
          if (typeof opts.onProcessing === "function") {
            opts.onProcessing(i + 1, attempts);
          }
          await new Promise(function (resolve) {
            setTimeout(resolve, RIDER_RECOVERY_POLL_MS);
          });
          continue;
        }
        if (response.status === 404) {
          await new Promise(function (resolve) {
            setTimeout(resolve, RIDER_RECOVERY_POLL_MS);
          });
          continue;
        }
        if (response.ok) {
          return unwrapApiPayload(await response.json());
        }
      } catch (_) {}
      await new Promise(function (resolve) {
        setTimeout(resolve, RIDER_RECOVERY_POLL_MS);
      });
    }
    return null;
  }

  async function recoverCustomerRequestByPhone(formValues, idempotencyKey) {
    var phone = normalizeRiderPhone(formValues && formValues.phone);
    if (!phone) {
      return null;
    }
    try {
      var historyUrl = "/api/health-isf/customers/workspace/history?rider_phone=" + encodeURIComponent(phone) + "&limit=10";
      var historyPayload = await fetchJson(historyUrl);
      var history = safeObject(unwrapApiPayload(historyPayload));
      var rows = Array.isArray(history.history) ? history.history : [];
      var pickupNorm = safeText(formValues.pickup, "").trim().toLowerCase();
      var dropoffNorm = safeText(formValues.dropoff, "").trim().toLowerCase();
      var cutoff = Date.now() - (5 * 60 * 1000);
      for (var i = 0; i < rows.length; i += 1) {
        var row = safeObject(rows[i]);
        var submittedAt = safeText(row.submitted_at || row.created_at, "");
        var ts = submittedAt ? new Date(submittedAt).getTime() : 0;
        if (ts && ts < cutoff) {
          continue;
        }
        var rowPickup = safeText(row.pickup_address || row.pickup, "").trim().toLowerCase();
        var rowDropoff = safeText(row.dropoff_address || row.dropoff, "").trim().toLowerCase();
        if (rowPickup === pickupNorm && rowDropoff === dropoffNorm && safeText(row.id, "")) {
          return row;
        }
      }
    } catch (_) {}
    return null;
  }

  function applyRiderSubmitSuccess(created, formValues, recurring, recoveredAfterTimeout, idempotencyKey) {
    var rideId = safeText(created.ride_id, "");
    var requestId = safeText(created.id, "");
    var dispatchStatus = safeText(created.dispatch_status, "pending");

    state.riderApp = safeObject(state.riderApp);
    state.riderApp.profile = formValues;
    state.riderApp.activeRequestId = requestId;
    state.riderApp.lastSubmit = {
      rideId: rideId,
      requestId: requestId,
      status: dispatchStatus,
      submittedAt: new Date().toISOString()
    };
    state.riderApp.submitStatus = {
      level: "success",
      message: recoveredAfterTimeout ? "Ride request confirmed after network delay." : "Ride request submitted successfully.",
      rideId: rideId,
      requestId: requestId,
      status: dispatchStatus
    };
    state.riderApp.activeTrip = {
      tripId: rideId,
      status: dispatchStatus,
      pickup: formValues.pickup,
      dropoff: formValues.dropoff,
      etaMin: "",
      driverName: "Awaiting assignment",
      vehicle: "Vehicle pending",
      supportContact: "24/7 Rider Care"
    };

    logRiderSubmitEvent(recoveredAfterTimeout ? "rider_submit_recovered" : "rider_submit_success", {
      idempotencyKey: idempotencyKey,
      rideId: rideId,
      requestId: requestId,
      dispatchStatus: dispatchStatus,
      recurring: recurring === true
    });

    void refreshRiderWorkspaceData({
      lastAction: recurring === true
        ? ("Recurring ride scheduled. Ride ID: " + rideId)
        : ("Ride request submitted. Ride ID: " + rideId)
    }).catch(function () {});

    window.dispatchEvent(new CustomEvent("ami:ops-runtime-updated", {
      detail: { source: "rider-ride-created", rideId: rideId, requestId: requestId }
    }));
    requestSilentRefresh("rider-ride-created");

    addRiderNotification(
      recurring === true ? "low" : "medium",
      recurring === true
        ? ("Recurring ride request submitted. Ride ID: " + rideId)
        : ("Ride request submitted. Ride ID: " + rideId + " is now in the dispatcher queue.")
    );
    persistSessionState();
    renderPage();
    window.alert(
      (recoveredAfterTimeout
        ? "Ride request confirmed after network delay."
        : (recurring === true ? "Recurring ride scheduled successfully." : "Ride request submitted successfully.")) +
      "\n\nRide ID: " + rideId +
      "\nRequest ID: " + requestId +
      "\nStatus: " + dispatchStatus +
      (recoveredAfterTimeout ? "\n\nRecovered using request key: " + idempotencyKey : "") +
      "\n\nDispatch can now review and assign a driver."
    );
    return { ok: true, request: created, rideId: rideId, requestId: requestId };
  }

  async function submitRiderRideRequest(recurring) {
    var authed = await ensureAuthenticatedSession("Sign in as a rider before requesting a ride.");
    if (!authed) {
      state.riderApp = safeObject(state.riderApp);
      state.riderApp.submitStatus = {
        level: "error",
        message: "Sign in as a rider before requesting a ride."
      };
      persistSessionState();
      renderPage();
      window.alert("Sign in as a rider before requesting a ride.");
      return { ok: false, error: "auth_required" };
    }

    state.riderApp = safeObject(state.riderApp);
    if (state.riderApp.submitInFlight) {
      window.alert("A ride request is already being submitted. Please wait for the current request to finish.");
      return { ok: false, error: "submit_in_flight" };
    }

    var formValues = readRiderFormValues();
    if (!formValues.name || !formValues.phone || !formValues.pickup || !formValues.dropoff) {
      state.riderApp.submitStatus = {
        level: "error",
        message: "Enter rider name, phone, pickup, and dropoff before submitting the request."
      };
      persistSessionState();
      renderPage();
      window.alert("Enter rider name, phone, pickup, and dropoff before submitting the request.");
      return { ok: false };
    }
    if (formValues.pickup.trim().toLowerCase() === formValues.dropoff.trim().toLowerCase()) {
      state.riderApp.submitStatus = {
        level: "error",
        message: "Pickup and dropoff must be different addresses."
      };
      persistSessionState();
      renderPage();
      window.alert("Pickup and dropoff must be different addresses.");
      return { ok: false };
    }

    var idempotencyKey = safeText(state.riderApp.pendingIdempotencyKey, "") || makeRiderIdempotencyKey();
    state.riderApp.submitInFlight = true;
    state.riderApp.pendingIdempotencyKey = idempotencyKey;
    state.riderApp.submitStatus = {
      level: "info",
      message: "Submitting ride…"
    };
    persistSessionState();
    renderPage();

    logRiderSubmitEvent("rider_submit_started", {
      idempotencyKey: idempotencyKey,
      recurring: recurring === true
    });

    var payload = {
      rider_name: formValues.name,
      rider_phone: formValues.phone,
      pickup_address: formValues.pickup,
      dropoff_address: formValues.dropoff,
      ride_type: formValues.rideType || "healthcare",
      notes: formValues.notes || null,
      client_request_key: idempotencyKey
    };
    var schedulingPayload = buildRiderSchedulingPayload(formValues, { forceWeekly: recurring === true });
    Object.keys(schedulingPayload).forEach(function (key) {
      payload[key] = schedulingPayload[key];
    });

    var created = null;
    var recoveredAfterTimeout = false;
    var submitError = "";
    try {
      created = await postJson("/api/health-isf/customer-requests", payload, RIDER_SUBMIT_TIMEOUT_MS, {
        idempotencyKey: idempotencyKey
      });
    } catch (err) {
      submitError = err && err.message ? err.message : "unknown error";
      if (
        (submitError === "Invalid token" || submitError === "Token expired" || submitError.indexOf("Token signature invalid") >= 0)
        && window.AmiCorSession
        && typeof window.AmiCorSession.refreshAccessToken === "function"
        && window.AmiCorSession.getRefreshToken()
      ) {
        var refreshed = await window.AmiCorSession.refreshAccessToken(true);
        if (refreshed) {
          try {
            created = await postJson("/api/health-isf/customer-requests", payload, RIDER_SUBMIT_TIMEOUT_MS, {
              idempotencyKey: idempotencyKey
            });
            submitError = "";
          } catch (retryErr) {
            submitError = retryErr && retryErr.message ? retryErr.message : submitError;
          }
        }
      }
    }

    if (created && safeText(created.id, "")) {
      state.riderApp.submitInFlight = false;
      state.riderApp.pendingIdempotencyKey = "";
      persistSessionState();
      renderPage();
      return applyRiderSubmitSuccess(created, formValues, recurring, false, idempotencyKey);
    }

    var timedOut = submitError === "request_timeout" || submitError.indexOf("request_timeout") >= 0;
    if (timedOut) {
      logRiderSubmitEvent("rider_submit_timeout_recovery_started", { idempotencyKey: idempotencyKey });
      state.riderApp.submitStatus = {
        level: "info",
        message: "Your ride request is still processing. Checking status…"
      };
      persistSessionState();
      renderPage();

      created = await recoverCustomerRequestByIdempotency(idempotencyKey, {
        maxAttempts: RIDER_RECOVERY_MAX_ATTEMPTS,
        onProcessing: function (attempt, maxAttempts) {
          state.riderApp.submitStatus = {
            level: "info",
            message: "Your ride request is still processing. Checking status… (" + attempt + "/" + maxAttempts + ")"
          };
          persistSessionState();
          renderPage();
        }
      });

      if (created && safeText(created.id, "")) {
        recoveredAfterTimeout = true;
      } else {
        created = await recoverCustomerRequestByPhone(formValues, idempotencyKey);
        if (created && safeText(created.id, "")) {
          recoveredAfterTimeout = true;
        }
      }
    }

    if (created && safeText(created.id, "")) {
      state.riderApp.submitInFlight = false;
      state.riderApp.pendingIdempotencyKey = "";
      persistSessionState();
      renderPage();
      return applyRiderSubmitSuccess(created, formValues, recurring, recoveredAfterTimeout, idempotencyKey);
    }

    logRiderSubmitEvent("rider_submit_confirmed_failed", {
      idempotencyKey: idempotencyKey,
      error: submitError || "recovery_exhausted",
      timedOut: timedOut
    });

    var failureMessage = timedOut
      ? "We could not confirm your ride request yet. The server may still be waking up or processing your request.\n\nWait a moment, refresh this page, and check ride history before submitting again.\n\nRequest key: " + idempotencyKey
      : "Ride request failed: " + (submitError || "unknown error");

    state.riderApp.submitInFlight = false;
    state.riderApp.pendingIdempotencyKey = "";
    state.riderApp.submitStatus = {
      level: "error",
      message: timedOut
        ? "Could not confirm ride status yet. Refresh and check ride history."
        : "Ride request failed: " + (submitError || "unknown error")
    };
    persistSessionState();
    renderPage();
    return {
      ok: false,
      confirmedFailure: true,
      message: failureMessage,
      idempotencyKey: idempotencyKey
    };
  }

  async function cancelActiveRiderRequest() {
    var riderState = safeObject(state.riderApp);
    var requestId = safeText(riderState.activeRequestId, "");
    if (!requestId) {
      window.alert("There is no active ride request available to cancel.");
      return { ok: false };
    }

    await sendJson("/api/health-isf/customers/workspace/" + encodeURIComponent(requestId) + "/cancel", "POST", {});
    await refreshRiderWorkspaceData({ lastAction: "Ride request cancelled" });
    addRiderNotification("medium", "Ride request cancelled.");
    persistSessionState();
    renderPage();
    return { ok: true };
  }

  async function safeLogAssistantEvent(eventType, eventName, status, payload, errorMessage) {
    try {
      await postJson("/api/assistant/events", {
        event_type: safeText(eventType, "client"),
        event_name: safeText(eventName, "event"),
        status: safeText(status, "info"),
        session_id: safeText(state.assistant.sessionNonce, ""),
        route: safeText(state.route, "dashboard"),
        payload: payload || {},
        error_message: safeText(errorMessage, "") || null
      });
    } catch (_) {}
  }

  async function refreshAssistantPersistence() {
    var token = getAccessToken();
    if (!token) {
      state.assistant.executionHistory = [];
      state.assistant.memoryEntries = [];
      state.assistant.auditEvents = state.assistant.auditEvents.slice(-48);
      return;
    }
    var settled = await Promise.allSettled([
      fetchJson("/api/assistant/executions?limit=12"),
      fetchJson("/api/assistant/memory?session_id=" + encodeURIComponent(String(state.assistant.sessionNonce || "")) + "&limit=12"),
      fetchJson("/api/assistant/events?session_id=" + encodeURIComponent(String(state.assistant.sessionNonce || "")) + "&limit=12")
    ]);
    if (settled[0].status === "fulfilled") {
      var execItems = ((settled[0].value || {}).items || []);
      if (Array.isArray(execItems)) {
        state.assistant.executionHistory = execItems.slice(0, 16).map(normalizeExecutionRecord);
      }
    }
    if (settled[1].status === "fulfilled") {
      var memoryItems = ((settled[1].value || {}).items || []);
      if (Array.isArray(memoryItems)) {
        state.assistant.memoryEntries = memoryItems.slice(0, 20).map(normalizeMemoryRecord);
      }
    }
    if (settled[2].status === "fulfilled") {
      var backendEvents = ((settled[2].value || {}).items || []);
      if (Array.isArray(backendEvents)) {
        var existingEvents = Array.isArray(state.assistant.auditEvents) ? state.assistant.auditEvents : [];
        var seenSignatures = {};
        var mergedEvents = [];
        backendEvents.map(normalizeAuditRecord).forEach(function (event) {
          var signature = safeText(event.signature, safeText(event.event_id, safeText(event.timestamp, "")));
          if (signature && !seenSignatures[signature]) {
            seenSignatures[signature] = true;
            mergedEvents.push(event);
          }
        });
        existingEvents.map(normalizeAuditRecord).forEach(function (event) {
          var signature = safeText(event.signature, safeText(event.id, safeText(event.timestamp, "")));
          if (signature && !seenSignatures[signature]) {
            seenSignatures[signature] = true;
            mergedEvents.push(event);
          }
        });
        state.assistant.auditEvents = mergedEvents.slice(-48);
      }
    }
  }

  function getAccessToken() {
    try {
      if (window.AmiCorSession && typeof window.AmiCorSession.getAccessToken === "function") {
        if (!window.AmiCorSession.getAccessToken() && typeof window.AmiCorSession.restore === "function") {
          window.AmiCorSession.restore();
        }
        var runtimeToken = window.AmiCorSession.getAccessToken();
        if (runtimeToken) {
          return String(runtimeToken);
        }
      }
    } catch (_) {}
    return "";
  }

  function getOrganizationId() {
    if (isDriverMobileAppRoute()) {
      var persistedDriver = readPersistedDriverSession();
      var driverOrg = safeText(persistedDriver && persistedDriver.organization_id, "").trim();
      if (driverOrg) {
        return driverOrg;
      }
      if (driverMobileAuthCache && safeText(driverMobileAuthCache.organization_id, "").trim()) {
        return safeText(driverMobileAuthCache.organization_id, "").trim();
      }
    }

    try {
      if (window.AmiCorSession && typeof window.AmiCorSession.getOrganizationId === "function") {
        var runtimeOrgId = safeText(window.AmiCorSession.getOrganizationId(), "").trim();
        if (runtimeOrgId) {
          return runtimeOrgId;
        }
      }
    } catch (_) {}

    try {
      var sessionRaw = localStorage.getItem("amicor_session");
      if (sessionRaw) {
        var session = JSON.parse(sessionRaw);
        if (session && typeof session === "object") {
          var sessionOrgId = safeText(session.organizationId || session.organization_id, "").trim();
          if (sessionOrgId) {
            return sessionOrgId;
          }
        }
      }
    } catch (_) {}

    try {
      var identityRaw = localStorage.getItem("amicor_identity");
      if (identityRaw) {
        var identity = JSON.parse(identityRaw);
        if (identity && typeof identity === "object") {
          var identityOrgId = safeText(identity.organizationId || identity.organization_id, "").trim();
          if (identityOrgId) {
            return identityOrgId;
          }
        }
      }
    } catch (_) {}

    return "";
  }

  function withOrganizationScope(path) {
    var original = safeText(path, "");
    if (!original) {
      return original;
    }
    var scopedPrefixes = ["/api/health-isf", "/api/enterprise", "/api/ai", "/api/nova"];
    var shouldScope = scopedPrefixes.some(function (prefix) {
      return original.indexOf(prefix) === 0;
    });
    if (!shouldScope || /[?&]organization_id=/.test(original)) {
      return original;
    }
    var orgId = getOrganizationId();
    if (!orgId) {
      return original;
    }
    var joiner = original.indexOf("?") === -1 ? "?" : "&";
    return original + joiner + "organization_id=" + encodeURIComponent(orgId);
  }

  function mergeTimeline(existing, incoming) {
    var merged = {};
    (Array.isArray(existing) ? existing : []).forEach(function (item) {
      var key = safeText(item.event_id || item.sequence_number, "");
      if (key) merged[key] = item;
    });
    (Array.isArray(incoming) ? incoming : []).forEach(function (item) {
      var key = safeText(item.event_id || item.sequence_number, "");
      if (key) merged[key] = item;
    });
    return Object.keys(merged).map(function (key) {
      return merged[key];
    }).sort(function (a, b) {
      return safeNumber(b.sequence_number, 0) - safeNumber(a.sequence_number, 0);
    }).slice(0, 120);
  }

  async function loadDriverMobileBootstrap(options) {
    var opts = options || {};
    var silent = opts.silent === true;
    var bootstrapTimedOut = false;
    var bootstrapRefreshSettled = false;
    var bootstrapTimer = null;

    if (!silent) {
      state.loading = true;
      state.error = null;
      state.fetchWarnings = [];
      state.driverApp = safeObject(state.driverApp);
      state.driverApp.mobileBootstrapError = "";
      if (!state.driverApp.mobileUiState) {
        state.driverApp.mobileUiState = hasValidDriverMobileSession() ? "loading_assignment" : "login_required";
      }
      renderPage();
    }

    bootstrapTimer = setTimeout(function () {
      if (!state.loading || bootstrapRefreshSettled) return;
      bootstrapTimedOut = true;
      state.loading = false;
      state.driverApp = safeObject(state.driverApp);
      if (safeText(state.driverApp.mobileUiState, "") !== "awaiting_assignment") {
        state.driverApp.mobileUiState = "api_error";
        state.driverApp.mobileBootstrapError = "Driver mobile bootstrap timed out after " + String(DRIVER_MOBILE_BOOTSTRAP_TIMEOUT_MS) + "ms";
        markDriverSyncWarning(state.driverApp.mobileBootstrapError);
      }
      renderPage();
    }, DRIVER_MOBILE_BOOTSTRAP_TIMEOUT_MS);

    try {
      var settled = await Promise.allSettled([
        fetchJson("/api/system/health"),
        fetchJson("/api/system/supervision")
      ]);
      if (settled[0].status === "fulfilled") {
        state.health = settled[0].value || {};
      } else {
        var healthErr = settled[0].reason;
        state.fetchWarnings.push("health_snapshot_unavailable");
        state.driverApp = safeObject(state.driverApp);
        state.driverApp.mobileBootstrapError = safeText(healthErr && healthErr.message, "/api/system/health unavailable");
      }
      if (settled[1].status === "fulfilled") {
        state.supervision = settled[1].value || {};
      } else {
        var supervisionErr = settled[1].reason;
        state.fetchWarnings.push("supervision_snapshot_unavailable");
        if (!state.driverApp.mobileBootstrapError) {
          state.driverApp.mobileBootstrapError = safeText(supervisionErr && supervisionErr.message, "/api/system/supervision unavailable");
        }
      }
      state.runtime.backendHealth = (settled[0].status === "fulfilled" || settled[1].status === "fulfilled") ? "up" : "down";

      await resolveDriverMobileAuth(getAccessToken());
      if (!hasValidDriverMobileSession()) {
        state.driverApp.mobileUiState = "login_required";
        state.driverApp.mobileBootstrapError = "";
        clearDriverSyncWarning();
      } else {
        state.driverApp.mobileUiState = "loading_assignment";
        state.driverApp.shiftOnline = true;
        try {
          await refreshDriverWorkflowData({ forceReset: opts.forceDriverReset === true }).finally(function () {
            bootstrapRefreshSettled = true;
          });
          recoverDriverMobileSyncUiState();
          state.driverApp.mobileBootstrapError = "";
        } catch (syncErr) {
          state.driverApp.mobileUiState = "api_error";
          state.driverApp.mobileBootstrapError = safeText(syncErr && syncErr.message, "driver_assignment_sync_failed");
          markDriverSyncWarning(state.driverApp.mobileBootstrapError);
        }
      }
    } catch (err) {
      state.driverApp = safeObject(state.driverApp);
      state.driverApp.mobileUiState = "api_error";
      state.driverApp.mobileBootstrapError = safeText(err && err.message, "driver_mobile_bootstrap_failed");
    } finally {
      if (bootstrapTimer) {
        clearTimeout(bootstrapTimer);
      }
      if (bootstrapTimedOut && bootstrapRefreshSettled) {
        recoverDriverMobileSyncUiState();
        state.loading = false;
        state.hydration = {
          authTokenPresent: !!getAccessToken() || hasValidDriverMobileSession(),
          opsHydrated: false,
          roleSlice: "driver",
          lastUpdatedAt: new Date().toISOString(),
          warningCount: state.fetchWarnings.length,
          integrityState: state.driverApp.mobileUiState === "api_error" ? "DEGRADED" : "replay_safe"
        };
        recomputeAssistantRuntimeState();
        persistSessionState();
        renderPage();
      } else if (!bootstrapTimedOut) {
        state.loading = false;
        state.hydration = {
          authTokenPresent: !!getAccessToken() || hasValidDriverMobileSession(),
          opsHydrated: false,
          roleSlice: "driver",
          lastUpdatedAt: new Date().toISOString(),
          warningCount: state.fetchWarnings.length,
          integrityState: state.driverApp.mobileUiState === "api_error" ? "DEGRADED" : "replay_safe"
        };
        recomputeAssistantRuntimeState();
        persistSessionState();
        renderPage();
      }
    }
  }

  var hydrationDiagSeq = 0;
  var enterpriseOpsHydrationInFlight = false;

  function beginOpsHydrationDiagnostic(route, role, silent) {
    return {
      id: "hydr-" + Date.now() + "-" + (++hydrationDiagSeq),
      route: safeText(route, "dashboard"),
      role: safeText(role, "admin"),
      silent: silent === true,
      loading_start: new Date().toISOString(),
      requests: [],
      rejected: [],
      loading_end: null,
      final_state: null
    };
  }

  function recordOpsHydrationRequest(diag, name, phase, status, durationMs, error) {
    if (!diag) return;
    var row = {
      name: safeText(name, "unknown"),
      phase: safeText(phase, "request"),
      status: status == null ? null : Number(status),
      duration_ms: durationMs == null ? null : Number(durationMs),
      error: safeText(error, "") || null,
      at: new Date().toISOString()
    };
    diag.requests.push(row);
    if (error) {
      diag.rejected.push(row);
    }
  }

  function finishOpsHydrationDiagnostic(diag, finalState) {
    if (!diag) return;
    diag.loading_end = new Date().toISOString();
    diag.final_state = safeObject(finalState);
    try {
      console.info("[OpsHydration]", diag);
    } catch (_) {}
    void postOpsHydrationDiagnostic(diag);
  }

  async function postOpsHydrationDiagnostic(diag) {
    try {
      await withTimeout(fetch("/api/health-isf/ops-shell/hydration-diag-log", {
        method: "POST",
        headers: { "Accept": "application/json", "Content-Type": "application/json" },
        credentials: "same-origin",
        body: JSON.stringify(diag || {})
      }), 4000);
    } catch (_) {}
  }

  function clearStaleEnterpriseLoadingHtml() {
    if (!els.pageContent) return;
    var text = safeText(els.pageContent.innerText, "");
    if (text.indexOf("Preparing Command Surface") >= 0) {
      els.pageContent.__stableHtml = "";
      state.runtime.lastPageDataSignature = "";
    }
  }

  function finalizeShellHydration(hasToken, settled, opsFailures) {
    state.fetchWarnings = dedupeWarnings(state.fetchWarnings);
    restoreLastGoodLiveWorkflowIfNeeded();
    var integrityState = computeHydrationIntegrity(
      hasToken,
      opsFailures,
      state.fetchWarnings,
      settled[0] && settled[0].status === "fulfilled",
      (settled[1] && settled[1].status === "fulfilled") || (settled[2] && settled[2].status === "fulfilled")
    );
    if (state.fetchWarnings.length === 2) {
      state.error = "operations_fetch_unavailable";
    } else if (state.fetchWarnings.length > 0) {
      state.error = "partial_operations_data";
    }
    state.hydration = {
      authTokenPresent: hasToken,
      opsHydrated: hasToken && opsFailures === 0 && state.fetchWarnings.indexOf("enterprise_ops_background_pending") < 0,
      roleSlice: state.role,
      lastUpdatedAt: new Date().toISOString(),
      warningCount: state.fetchWarnings.length,
      integrityState: integrityState
    };
    recomputeAssistantRuntimeState();
    persistSessionState();
  }

  function scheduleEnterpriseMonitoringHydration(token, timelineCursor, loadGen, diag) {
    if (!token) return;
    if (enterpriseOpsHydrationInFlight) return;
    enterpriseOpsHydrationInFlight = true;
    state.fetchWarnings = dedupeWarnings((state.fetchWarnings || []).concat(["enterprise_ops_background_pending"]));
    void hydrateEnterpriseMonitoringOps(token, timelineCursor, loadGen, diag).finally(function () {
      enterpriseOpsHydrationInFlight = false;
    });
  }

  async function hydrateEssentialWorkflowData(token, opts) {
    var previousWorkflow = safeObject(
      (state.runtime && state.runtime.lastGoodLiveWorkflow) || state.liveWorkflow
    );
    var workflowSettled = await Promise.allSettled([
      fetchJson("/api/health-isf/dispatch/queue?limit=80&read_only=true", {}, token),
      fetchJson("/api/health-isf/dispatch/active-assignments?limit=80", {}, token),
      fetchJson("/api/health-isf/activity-feed?limit=40", {}, token)
    ]);
    if (workflowSettled[0].status === "rejected") {
      state.fetchWarnings.push("dispatch_queue_unavailable");
    }
    if (workflowSettled[1].status === "rejected") {
      state.fetchWarnings.push("active_assignments_unavailable");
    }
    if (workflowSettled[2].status === "rejected") {
      state.fetchWarnings.push("activity_feed_unavailable");
    }
    var liveWorkflow = {
      dispatchQueue: workflowSettled[0].status === "fulfilled" && Array.isArray(workflowSettled[0].value) ? workflowSettled[0].value : null,
      activeAssignments: workflowSettled[1].status === "fulfilled" && Array.isArray(workflowSettled[1].value) ? workflowSettled[1].value : null,
      activityFeed: workflowSettled[2].status === "fulfilled" && Array.isArray((workflowSettled[2].value || {}).activities) ? (workflowSettled[2].value || {}).activities : null,
      drivers: null,
      rides: null,
      providers: null,
      customerRequests: null,
      vehicles: null,
      billingHandoffs: null,
      tripDocuments: null
    };
    try {
      liveWorkflow.drivers = await fetchJson("/api/health-isf/drivers?limit=120", {}, token);
    } catch (_) {
      state.fetchWarnings.push("drivers_unavailable");
    }
    try {
      liveWorkflow.rides = await fetchJson("/api/health-isf/rides?limit=120&active_only=true&exclude_test=true", {}, token);
    } catch (_) {
      state.fetchWarnings.push("rides_unavailable");
    }
    try {
      liveWorkflow.billingHandoffs = await fetchJson("/api/health-isf/operations/billing-handoffs?limit=100", {}, token);
    } catch (_) {
      state.fetchWarnings.push("billing_handoffs_unavailable");
    }
    try {
      liveWorkflow.tripDocuments = await fetchJson("/api/health-isf/operations/trip-documents?limit=200", {}, token);
    } catch (_) {
      state.fetchWarnings.push("trip_documents_unavailable");
    }
    try {
      state.adminRevenue = await fetchJson("/api/health-isf/operations/admin-revenue", {}, token);
    } catch (_) {
      state.fetchWarnings.push("admin_revenue_unavailable");
      state.adminRevenue = state.adminRevenue || (state.runtime && state.runtime.lastGoodAdminRevenue) || null;
    }
    var workflowReferenceSettled = await Promise.allSettled([
      fetchJson("/api/health-isf/providers?limit=120", {}, token),
      fetchJson("/api/health-isf/customer-requests?limit=120", {}, token),
      fetchJson("/api/health-isf/vehicles/active?limit=40", {}, token)
    ]);
    if (workflowReferenceSettled[0].status === "rejected") {
      state.fetchWarnings.push("providers_unavailable");
    }
    if (workflowReferenceSettled[1].status === "rejected") {
      state.fetchWarnings.push("customer_requests_unavailable");
    }
    if (workflowReferenceSettled[2].status === "rejected") {
      state.fetchWarnings.push("vehicles_unavailable");
    }
    state.liveWorkflow = mergeLiveWorkflowSnapshot(previousWorkflow, {
      dispatchQueue: liveWorkflow.dispatchQueue,
      activeAssignments: liveWorkflow.activeAssignments,
      drivers: Array.isArray(liveWorkflow.drivers) ? liveWorkflow.drivers : null,
      activityFeed: liveWorkflow.activityFeed,
      rides: liveWorkflow.rides == null ? null : filterOperationalRidesForHydration(liveWorkflow.rides),
      billingHandoffs: Array.isArray(liveWorkflow.billingHandoffs)
        ? dedupeBillingHandoffsByRideId(liveWorkflow.billingHandoffs)
        : null,
      tripDocuments: Array.isArray(liveWorkflow.tripDocuments) ? liveWorkflow.tripDocuments : null,
      providers: workflowReferenceSettled[0].status === "fulfilled" && Array.isArray(workflowReferenceSettled[0].value) ? workflowReferenceSettled[0].value : null,
      customerRequests: workflowReferenceSettled[1].status === "fulfilled" && Array.isArray(workflowReferenceSettled[1].value) ? workflowReferenceSettled[1].value : null,
      vehicles: workflowReferenceSettled[2].status === "fulfilled" && Array.isArray(workflowReferenceSettled[2].value) ? workflowReferenceSettled[2].value : null
    });
    recordLastGoodLiveWorkflow();
    if (canUseDriverWorkspaceActions()) {
      try {
        var driverMobileReset = isDriverMobileSurface() && opts && opts.forceDriverReset === true;
        if (driverMobileReset) {
          clearDriverLiveTripState({ resetBoundIdentity: false });
        }
        await refreshDriverWorkflowData({ token: token, forceReset: driverMobileReset });
      } catch (_) {
        state.fetchWarnings.push("driver_workspace_unavailable");
      }
    }
    try {
      var focusRideId = "";
      var dispatchRows = Array.isArray(liveWorkflow.dispatchQueue) ? liveWorkflow.dispatchQueue.slice() : [];
      dispatchRows = dispatchRows.filter(function (row) {
        return !isOperationalExcludedRideMeta(
          row.passenger_name || row.rider_name,
          row.pickup_address,
          row.dropoff_address,
          row.notes
        );
      });
      dispatchRows.sort(function (a, b) {
        var aTs = Date.parse(safeText(a.requested_at || a.created_at, "")) || 0;
        var bTs = Date.parse(safeText(b.requested_at || b.created_at, "")) || 0;
        return bTs - aTs;
      });
      if (dispatchRows.length > 0) {
        focusRideId = safeText(dispatchRows[0].ride_id, "");
      }
      var aiSnapshotUrl = "/api/health-isf/ai-dispatch/snapshot?publish=false"
        + (focusRideId ? "&ride_id=" + encodeURIComponent(focusRideId) : "");
      void withTimeout(fetchJson(aiSnapshotUrl, {}, token), AI_SNAPSHOT_TIMEOUT_MS).then(function (snapshot) {
        state.healthIsfAiSnapshot = snapshot;
        var snapshotDispatch = safeObject((safeObject(snapshot)).live_dispatch);
        if (Array.isArray(snapshotDispatch.queue) && snapshotDispatch.queue.length > 0) {
          state.liveWorkflow = safeObject(state.liveWorkflow);
          state.liveWorkflow.dispatchQueue = snapshotDispatch.queue.filter(function (row) {
            return !isOperationalExcludedRideMeta(
              row.passenger_name || row.rider_name,
              row.pickup_address,
              row.dropoff_address,
              row.notes
            );
          });
        }
        if (!state.loading) {
          renderPage();
        }
      }).catch(function () {
        state.healthIsfAiSnapshot = state.healthIsfAiSnapshot || null;
        state.fetchWarnings.push("ai_dispatch_snapshot_unavailable");
      });
    } catch (_) {
      state.healthIsfAiSnapshot = null;
      state.fetchWarnings.push("ai_dispatch_snapshot_unavailable");
    }
  }
  async function hydrateEnterpriseMonitoringOps(token, timelineCursor, loadGen, diag) {
    if (!token) return;
    var opsFailures = 0;
    var started = Date.now();
    var opsSettled = await Promise.allSettled([
      fetchJson("/api/ops/dashboard-summary"),
      fetchJson("/api/ops/live-status"),
      fetchJson("/api/ops/alerts"),
      fetchJson("/api/ops/recommendations"),
      fetchJson("/api/ops/stream?after_sequence=" + encodeURIComponent(String(timelineCursor)) + "&limit=60&role_view=" + encodeURIComponent(String(state.role || "admin")), {}, token),
      fetchJson("/api/ops/compliance/dashboard-summary?role_view=" + encodeURIComponent(String(state.role || "admin")), {}, token),
      fetchJson("/api/ops/orchestration/queue?role_view=" + encodeURIComponent(String(state.role || "admin")), {}, token),
      fetchJson("/api/ops/orchestration/timeline?after_sequence=0&limit=120&role_view=" + encodeURIComponent(String(state.role || "admin")), {}, token),
      fetchJson("/api/ops/orchestration/notifications?limit=120&role_view=" + encodeURIComponent(String(state.role || "admin")), {}, token),
      fetchJson("/api/ops/orchestration/live-stream?after_sequence=0&limit=120&role_view=" + encodeURIComponent(String(state.role || "admin")), {}, token),
      fetchJson("/api/ops/orchestration/sla?role_view=" + encodeURIComponent(String(state.role || "admin")), {}, token),
      fetchJson("/api/ops/orchestration/queue-health?role_view=" + encodeURIComponent(String(state.role || "admin")), {}, token),
      fetchJson("/api/ops/orchestration/export-bundle?role_view=" + encodeURIComponent(String(state.role || "admin")), {}, token),
      fetchJson("/api/ops/federation/regions?role_view=" + encodeURIComponent(String(state.role || "admin")), {}, token),
      fetchJson("/api/ops/federation/queues?role_view=" + encodeURIComponent(String(state.role || "admin")), {}, token),
      fetchJson("/api/ops/federation/capacity?role_view=" + encodeURIComponent(String(state.role || "admin")), {}, token),
      fetchJson("/api/ops/federation/continuity?role_view=" + encodeURIComponent(String(state.role || "admin")), {}, token),
      fetchJson("/api/ops/federation/health?role_view=" + encodeURIComponent(String(state.role || "admin")), {}, token),
      fetchJson("/api/ops/federation/export-bundle?role_view=" + encodeURIComponent(String(state.role || "admin")), {}, token),
      fetchJson("/api/ops/replay/timeline?after_sequence=0&limit=120&role_view=" + encodeURIComponent(String(state.role || "admin")), {}, token),
      fetchJson("/api/ops/replay/projection?after_sequence=0&limit=120&role_view=" + encodeURIComponent(String(state.role || "admin")), {}, token),
      fetchJson("/api/ops/replay/comparison?role_view=" + encodeURIComponent(String(state.role || "admin")), {}, token),
      fetchJson("/api/ops/replay/continuity?role_view=" + encodeURIComponent(String(state.role || "admin")), {}, token),
      fetchJson("/api/ops/replay/evidence?role_view=" + encodeURIComponent(String(state.role || "admin")), {}, token),
      fetchJson("/api/ops/replay/export-bundle?role_view=" + encodeURIComponent(String(state.role || "admin")), {}, token),
      fetchJson("/api/ops/predictive/governance", { method: "POST", body: JSON.stringify({ replay_session_id: ((state.ops.replay || {}).timeline || {}).replay_session_id || null, prediction_scope: "governance" }) }, token),
      fetchJson("/api/ops/predictive/constraints", { method: "POST", body: JSON.stringify({ replay_session_id: ((state.ops.replay || {}).timeline || {}).replay_session_id || null, constraint_domain: "operational_constraints" }) }, token),
      fetchJson("/api/ops/predictive/capacity", { method: "POST", body: JSON.stringify({ replay_session_id: ((state.ops.replay || {}).timeline || {}).replay_session_id || null, capacity_scope: "capacity_pressure" }) }, token),
      fetchJson("/api/ops/predictive/risk", { method: "POST", body: JSON.stringify({ replay_session_id: ((state.ops.replay || {}).timeline || {}).replay_session_id || null, risk_domain: "governance_risk" }) }, token),
      fetchJson("/api/ops/predictive/anomaly", { method: "POST", body: JSON.stringify({ replay_session_id: ((state.ops.replay || {}).timeline || {}).replay_session_id || null, anomaly_scope: "operational_anomaly" }) }, token),
      fetchJson("/api/ops/predictive/drift?replay_session_id=" + encodeURIComponent(String(((state.ops.replay || {}).timeline || {}).replay_session_id || "")) + "&role_view=" + encodeURIComponent(String(state.role || "admin")), {}, token),
      fetchJson("/api/ops/predictive/recommendations?replay_session_id=" + encodeURIComponent(String(((state.ops.replay || {}).timeline || {}).replay_session_id || "")) + "&role_view=" + encodeURIComponent(String(state.role || "admin")), {}, token),
      fetchJson("/api/ops/predictive/trends?replay_session_id=" + encodeURIComponent(String(((state.ops.replay || {}).timeline || {}).replay_session_id || "")) + "&role_view=" + encodeURIComponent(String(state.role || "admin")), {}, token),
      fetchJson("/api/ops/predictive/evidence?replay_session_id=" + encodeURIComponent(String(((state.ops.replay || {}).timeline || {}).replay_session_id || "")) + "&role_view=" + encodeURIComponent(String(state.role || "admin")), {}, token),
      fetchJson("/api/ops/predictive/export-bundle?replay_session_id=" + encodeURIComponent(String(((state.ops.replay || {}).timeline || {}).replay_session_id || "")) + "&role_view=" + encodeURIComponent(String(state.role || "admin")), {}, token),
      fetchJson("/api/ops/governance/provenance", { method: "POST", body: JSON.stringify({ replay_session_id: ((state.ops.replay || {}).timeline || {}).replay_session_id || null, decision_scope: "governance_decision" }) }, token),
      fetchJson("/api/ops/governance/explanations", { method: "POST", body: JSON.stringify({ replay_session_id: ((state.ops.replay || {}).timeline || {}).replay_session_id || null, explanation_scope: "governance_explanation" }) }, token),
      fetchJson("/api/ops/governance/reasoning", { method: "POST", body: JSON.stringify({ replay_session_id: ((state.ops.replay || {}).timeline || {}).replay_session_id || null, reasoning_scope: "advisory_reasoning" }) }, token),
      fetchJson("/api/ops/governance/memory", { method: "POST", body: JSON.stringify({ replay_session_id: ((state.ops.replay || {}).timeline || {}).replay_session_id || null, memory_window: "long_horizon", trend_window: "long_horizon" }) }, token),
      fetchJson("/api/ops/governance/ancestry?replay_session_id=" + encodeURIComponent(String(((state.ops.replay || {}).timeline || {}).replay_session_id || "")) + "&role_view=" + encodeURIComponent(String(state.role || "admin")), {}, token),
      fetchJson("/api/ops/governance/lineage?replay_session_id=" + encodeURIComponent(String(((state.ops.replay || {}).timeline || {}).replay_session_id || "")) + "&role_view=" + encodeURIComponent(String(state.role || "admin")), {}, token),
      fetchJson("/api/ops/governance/history?replay_session_id=" + encodeURIComponent(String(((state.ops.replay || {}).timeline || {}).replay_session_id || "")) + "&role_view=" + encodeURIComponent(String(state.role || "admin")), {}, token),
      fetchJson("/api/ops/governance/trends?replay_session_id=" + encodeURIComponent(String(((state.ops.replay || {}).timeline || {}).replay_session_id || "")) + "&role_view=" + encodeURIComponent(String(state.role || "admin")), {}, token),
      fetchJson("/api/ops/governance/export-bundle?replay_session_id=" + encodeURIComponent(String(((state.ops.replay || {}).timeline || {}).replay_session_id || "")) + "&role_view=" + encodeURIComponent(String(state.role || "admin")), {}, token),
      fetchJson("/api/ops/governance/policy/matrix", { method: "POST", body: JSON.stringify({ replay_session_id: ((state.ops.replay || {}).timeline || {}).replay_session_id || null, policy_scope: "governance_policy_constraints" }) }, token),
      fetchJson("/api/ops/governance/framework/map", { method: "POST", body: JSON.stringify({ replay_session_id: ((state.ops.replay || {}).timeline || {}).replay_session_id || null, policy_scope: "governance_policy_constraints" }) }, token),
      fetchJson("/api/ops/governance/policy/evaluate", { method: "POST", body: JSON.stringify({ replay_session_id: ((state.ops.replay || {}).timeline || {}).replay_session_id || null, policy_scope: "governance_policy_constraints" }) }, token),
      fetchJson("/api/ops/governance/policy/score", { method: "POST", body: JSON.stringify({ replay_session_id: ((state.ops.replay || {}).timeline || {}).replay_session_id || null, policy_scope: "governance_policy_constraints" }) }, token),
      fetchJson("/api/ops/governance/rationale/build", { method: "POST", body: JSON.stringify({ replay_session_id: ((state.ops.replay || {}).timeline || {}).replay_session_id || null }) }, token),
      fetchJson("/api/ops/governance/policy/lineage?replay_session_id=" + encodeURIComponent(String(((state.ops.replay || {}).timeline || {}).replay_session_id || "")) + "&role_view=" + encodeURIComponent(String(state.role || "admin")), {}, token),
      fetchJson("/api/ops/governance/policy/history?replay_session_id=" + encodeURIComponent(String(((state.ops.replay || {}).timeline || {}).replay_session_id || "")) + "&role_view=" + encodeURIComponent(String(state.role || "admin")), {}, token),
      fetchJson("/api/ops/governance/violations?replay_session_id=" + encodeURIComponent(String(((state.ops.replay || {}).timeline || {}).replay_session_id || "")) + "&role_view=" + encodeURIComponent(String(state.role || "admin")), {}, token),
      fetchJson("/api/ops/governance/constraints?role_view=" + encodeURIComponent(String(state.role || "admin")), {}, token),
      fetchJson("/api/ops/governance/frameworks?role_view=" + encodeURIComponent(String(state.role || "admin")), {}, token),
      fetchJson("/api/ops/governance/risk/evaluate", { method: "POST", body: JSON.stringify({ replay_session_id: ((state.ops.replay || {}).timeline || {}).replay_session_id || null }) }, token)
    ]);

    var coreOpsRejectedAsUnauthorized = opsSettled.slice(0, 5).every(function (result) {
      return result.status === "rejected" && isHttpStatusError(result.reason, 401);
    });

    if (coreOpsRejectedAsUnauthorized) {
      // Do not wipe the signed-in session when /api/ops/* rejects but health-isf
      // workflow APIs remain authorized. Rider/dispatch/driver/billing must stay live.
      state.fetchWarnings.push("ops_secondary_auth_limited");
      state.ops.dashboardSummary = null;
      state.ops.liveStatus = null;
      state.ops.alerts = [];
      state.ops.recommendations = [];
    }

    // Re-check token after restore; never force guest/token-missing when a valid session exists.
    if (!getAccessToken()) {
      return;
    }

    if (opsSettled[0].status === "fulfilled") {
      state.ops.dashboardSummary = opsSettled[0].value || null;
      state.ops.visibility = ((opsSettled[0].value || {}).visibility || {});
    } else {
      opsFailures += 1;
    }
    if (opsSettled[1].status === "fulfilled") {
      state.ops.liveStatus = opsSettled[1].value || null;
    } else {
      opsFailures += 1;
    }
    if (opsSettled[2].status === "fulfilled") {
      state.ops.alerts = (opsSettled[2].value || {}).alerts || [];
    } else {
      opsFailures += 1;
    }
    if (opsSettled[3].status === "fulfilled") {
      state.ops.recommendations = (opsSettled[3].value || {}).recommendations || [];
    } else {
      opsFailures += 1;
    }
    if (opsSettled[4].status === "fulfilled") {
      var streamPayload = opsSettled[4].value || {};
      var streamEvents = Array.isArray(streamPayload.contract_events) ? streamPayload.contract_events.map(contractEventToTimelineItem) : [];
      state.ops.timeline = mergeTimeline(state.ops.timeline, streamEvents || []);
      state.ops.timelineCursor = safeNumber(streamPayload.next_cursor, timelineCursor);
      state.ops.stream = {
        connected: asBoolean((streamPayload.stream_status || {}).connected, false),
        mode: safeText((streamPayload.stream_status || {}).mode, "polling_fallback"),
        fallbackPollingActive: asBoolean((streamPayload.stream_status || {}).fallback_polling_active, true),
        lastEventReceived: safeText((streamPayload.stream_status || {}).last_event_received, null),
        eventCount: safeNumber((streamPayload.stream_status || {}).event_count, streamEvents.length),
        timelineSyncStatus: safeText((streamPayload.stream_status || {}).timeline_sync_status, "idle"),
        supervisionSafe: asBoolean((streamPayload.stream_status || {}).supervision_safe, true),
        replaySafe: asBoolean((streamPayload.stream_status || {}).replay_safe, true)
      };
      state.ops.correlation = {
        totalGroups: safeNumber((streamPayload.correlation || {}).total_groups, 0),
        groups: Array.isArray((streamPayload.correlation || {}).groups) ? (streamPayload.correlation || {}).groups : []
      };
      if (state.ops.stream.mode === "polling_fallback") {
        state.fetchWarnings.push("stream_polling_fallback");
      }
    } else {
      state.fetchWarnings.push("streaming_unavailable");
      try {
        var timelinePayload = await fetchJson("/api/ops/timeline?after_sequence=" + encodeURIComponent(String(timelineCursor)) + "&limit=60");
        state.ops.timeline = mergeTimeline(state.ops.timeline, timelinePayload.events || []);
        state.ops.timelineCursor = safeNumber(timelinePayload.next_cursor, timelineCursor);
        state.ops.stream = {
          connected: false,
          mode: "polling_fallback",
          fallbackPollingActive: true,
          lastEventReceived: (Array.isArray(timelinePayload.events) && timelinePayload.events.length > 0) ? safeText(timelinePayload.events[timelinePayload.events.length - 1].timestamp, null) : null,
          eventCount: Array.isArray(timelinePayload.events) ? timelinePayload.events.length : 0,
          timelineSyncStatus: "active",
          supervisionSafe: true,
          replaySafe: true
        };
        state.ops.correlation = { totalGroups: 0, groups: [] };
        state.fetchWarnings.push("stream_polling_fallback");
      } catch (_) {
        opsFailures += 1;
      }
    }
    if (opsSettled[5].status === "fulfilled") {
      var compliancePayload = opsSettled[5].value || {};
      state.ops.compliance = {
        compliance_overview: compliancePayload.compliance_overview || null,
        expiration_queue: compliancePayload.expiration_queue || null,
        approval_queue: compliancePayload.approval_queue || null,
        compliance_timeline: Array.isArray(compliancePayload.compliance_timeline) ? compliancePayload.compliance_timeline : [],
        phase25: {
          evidence_chain_viewer: Array.isArray(((compliancePayload.phase25 || {}).evidence_chain_viewer)) ? (compliancePayload.phase25 || {}).evidence_chain_viewer : [],
          document_lineage_viewer: Array.isArray(((compliancePayload.phase25 || {}).document_lineage_viewer)) ? (compliancePayload.phase25 || {}).document_lineage_viewer : [],
          supervisor_review_queue: Array.isArray(((compliancePayload.phase25 || {}).supervisor_review_queue)) ? (compliancePayload.phase25 || {}).supervisor_review_queue : [],
          regulatory_export_builder: Array.isArray(((compliancePayload.phase25 || {}).regulatory_export_builder)) ? (compliancePayload.phase25 || {}).regulatory_export_builder : [],
          signed_access_monitor: Array.isArray(((compliancePayload.phase25 || {}).signed_access_monitor)) ? (compliancePayload.phase25 || {}).signed_access_monitor : [],
          retention_status_dashboard: Array.isArray(((compliancePayload.phase25 || {}).retention_status_dashboard)) ? (compliancePayload.phase25 || {}).retention_status_dashboard : []
        },
        profiles: Array.isArray(compliancePayload.profiles) ? compliancePayload.profiles : [],
        documents: Array.isArray(compliancePayload.documents) ? compliancePayload.documents : []
      };
    } else {
      state.fetchWarnings.push("compliance_unavailable");
    }

    if (
      opsSettled[6].status === "fulfilled" &&
      opsSettled[7].status === "fulfilled" &&
      opsSettled[8].status === "fulfilled" &&
      opsSettled[9].status === "fulfilled" &&
      opsSettled[10].status === "fulfilled" &&
      opsSettled[11].status === "fulfilled" &&
      opsSettled[12].status === "fulfilled"
    ) {
      state.ops.orchestration = {
        queue_snapshot: opsSettled[6].value || { tasks: [], queue_health: {} },
        timeline_projection: opsSettled[7].value || { events: [], next_cursor: 0 },
        notifications: opsSettled[8].value || { notifications: [] },
        live_stream: opsSettled[9].value || { events: [], next_cursor: 0, checkpoint: null, stream_cursor: null },
        sla: opsSettled[10].value || { alerts: [], metrics: {} },
        queue_health: opsSettled[11].value || { queue_pressure_dashboard: {} },
        export_bundle: opsSettled[12].value || { bundle_id: null, bundle_checksum: null, replay_reconstruction: {} }
      };
    } else {
      state.fetchWarnings.push("orchestration_unavailable");
    }

    if (
      opsSettled[13].status === "fulfilled" &&
      opsSettled[14].status === "fulfilled" &&
      opsSettled[15].status === "fulfilled" &&
      opsSettled[16].status === "fulfilled" &&
      opsSettled[17].status === "fulfilled" &&
      opsSettled[18].status === "fulfilled"
    ) {
      state.ops.federation = {
        regions: opsSettled[13].value || { regions: [] },
        queues: opsSettled[14].value || { regions: [] },
        capacity: opsSettled[15].value || { forecasts: [] },
        continuity: opsSettled[16].value || { continuity_projection: [] },
        health: opsSettled[17].value || { regions: [] },
        export_bundle: opsSettled[18].value || { bundle_id: null, bundle_checksum: null, payload: {} }
      };
    } else {
      state.fetchWarnings.push("federation_unavailable");
    }

    if (
      opsSettled[19].status === "fulfilled" &&
      opsSettled[20].status === "fulfilled" &&
      opsSettled[21].status === "fulfilled" &&
      opsSettled[22].status === "fulfilled" &&
      opsSettled[23].status === "fulfilled" &&
      opsSettled[24].status === "fulfilled"
    ) {
      state.ops.replay = {
        session: { frames: [] },
        scenario: null,
        branch: null,
        timeline: opsSettled[19].value || { events: [] },
        projection: opsSettled[20].value || { events: [] },
        comparison: opsSettled[21].value || { comparisons: [] },
        continuity: opsSettled[22].value || null,
        evidence: opsSettled[23].value || { payload: {} },
        export_bundle: opsSettled[24].value || { bundle_id: null, bundle_checksum: null, payload: {} }
      };
    } else {
      state.fetchWarnings.push("replay_unavailable");
    }

    if (
      opsSettled[25].status === "fulfilled" &&
      opsSettled[26].status === "fulfilled" &&
      opsSettled[27].status === "fulfilled" &&
      opsSettled[28].status === "fulfilled" &&
      opsSettled[29].status === "fulfilled" &&
      opsSettled[30].status === "fulfilled" &&
      opsSettled[31].status === "fulfilled" &&
      opsSettled[32].status === "fulfilled" &&
      opsSettled[33].status === "fulfilled" &&
      opsSettled[34].status === "fulfilled"
    ) {
      state.ops.predictive = {
        governance: opsSettled[25].value || null,
        constraints: opsSettled[26].value || null,
        capacity: opsSettled[27].value || null,
        risk: opsSettled[28].value || null,
        anomaly: opsSettled[29].value || null,
        drift: opsSettled[30].value || { drift_events: [] },
        recommendations: opsSettled[31].value || { recommendations: [] },
        trends: opsSettled[32].value || { trends: [] },
        evidence: opsSettled[33].value || { payload: {} },
        export_bundle: opsSettled[34].value || { bundle_id: null, bundle_checksum: null, payload: {} }
      };
    } else {
      state.fetchWarnings.push("predictive_unavailable");
    }

    if (
      opsSettled[35].status === "fulfilled" &&
      opsSettled[36].status === "fulfilled" &&
      opsSettled[37].status === "fulfilled" &&
      opsSettled[38].status === "fulfilled" &&
      opsSettled[39].status === "fulfilled" &&
      opsSettled[40].status === "fulfilled" &&
      opsSettled[41].status === "fulfilled" &&
      opsSettled[42].status === "fulfilled" &&
      opsSettled[43].status === "fulfilled" &&
      opsSettled[44].status === "fulfilled" &&
      opsSettled[45].status === "fulfilled" &&
      opsSettled[46].status === "fulfilled" &&
      opsSettled[47].status === "fulfilled" &&
      opsSettled[48].status === "fulfilled" &&
      opsSettled[49].status === "fulfilled" &&
      opsSettled[50].status === "fulfilled" &&
      opsSettled[51].status === "fulfilled" &&
      opsSettled[52].status === "fulfilled" &&
      opsSettled[53].status === "fulfilled" &&
      opsSettled[54].status === "fulfilled"
    ) {
      state.ops.governance = {
        provenance: opsSettled[35].value || null,
        explanations: opsSettled[36].value || null,
        reasoning: opsSettled[37].value || null,
        memory: opsSettled[38].value || null,
        ancestry: opsSettled[39].value || { ancestry_trace: [] },
        lineage: opsSettled[40].value || null,
        history: opsSettled[41].value || null,
        trends: opsSettled[42].value || null,
        export_bundle: opsSettled[43].value || { bundle_id: null, bundle_checksum: null, payload: {} },
        policyMatrix: opsSettled[44].value || { policy_matrix: [], constraint_versions: [] },
        policyFrameworkMap: opsSettled[45].value || { frameworks: [], framework_rule_mappings: [] },
        policyEvaluations: opsSettled[46].value || { constraint_evaluations: [], constraint_violations: [], regulatory_evidence_refs: [] },
        policyScore: opsSettled[47].value || null,
        rationaleChain: opsSettled[48].value || { rationale_chain: [], decision_trace: [] },
        policyLineage: opsSettled[49].value || { policy_lineage: [] },
        policyHistory: opsSettled[50].value || { constraint_history: [], score_history: [] },
        policyViolations: opsSettled[51].value || { violations: [] },
        policyConstraints: opsSettled[52].value || { constraints: [] },
        policyFrameworks: opsSettled[53].value || { frameworks: [] },
        risk: opsSettled[54].value || { recommendations: [] }
      };
    } else {
      state.fetchWarnings.push("governance_unavailable");
    }

    recordOpsHydrationRequest(diag, "enterprise_ops_bundle", "background_complete", 200, Date.now() - started, null);
    if (loadGen !== state.runtime.hydrationLoadGen) return;
    state.fetchWarnings = dedupeWarnings((state.fetchWarnings || []).filter(function (w) { return w !== "enterprise_ops_background_pending"; }));
    if (opsFailures > 0) state.fetchWarnings.push("ops_hydration_partial");
    state.hydration.opsHydrated = opsFailures === 0;
    state.hydration.lastUpdatedAt = new Date().toISOString();
    persistSessionState();
    if (!state.loading) renderPage();
  }

  async function loadBackendData(options) {
    var opts = options || {};
    var silent = opts.silent === true;
    var hydrationLoadGen = 0;
    var hydrationDiag = null;
    var hasToken = false;
    var settled = [];
    var hydrationTimedOut = false;
    var hydrationTimer = null;

    if (isDriverMobileAppRoute()) {
      return loadDriverMobileBootstrap(opts);
    }

    refreshInFlight = true;
    hydrationDiag = beginOpsHydrationDiagnostic(state.route, state.role, silent);
    if (!silent) {
      state.loading = true;
      state.error = null;
      state.fetchWarnings = [];
      hydrationTimer = setTimeout(function () {
        if (!state.loading) return;
        hydrationTimedOut = true;
        state.loading = false;
        state.fetchWarnings = dedupeWarnings((state.fetchWarnings || []).concat(["hydration_timeout"]));
        restoreLastGoodLiveWorkflowIfNeeded();
        state.error = "partial_operations_data";
        clearStaleEnterpriseLoadingHtml();
        renderPage();
      }, ENTERPRISE_HYDRATION_TIMEOUT_MS);
      renderPage();
    }

    try {
    await ensurePlatformSessionReady();

    settled = await Promise.allSettled([
      fetchJson("/api/health"),
      fetchJson("/api/system/health"),
      fetchJson("/api/system/supervision")
    ]);

    var apiHealthOk = settled[0].status === "fulfilled";
    if (settled[1].status === "fulfilled") {
      state.health = settled[1].value || {};
    } else if (settled[0].status === "fulfilled" && settled[0].value && settled[0].value.data) {
      state.health = { status: safeText((settled[0].value.data || {}).status, "ok") };
      state.fetchWarnings.push("health_snapshot_unavailable");
    } else {
      state.fetchWarnings.push("health_snapshot_unavailable");
    }

    if (settled[2].status === "fulfilled") {
      state.supervision = settled[2].value || {};
    } else {
      state.fetchWarnings.push("supervision_snapshot_unavailable");
    }

    var backendHealthy = apiHealthOk || settled[1].status === "fulfilled" || settled[2].status === "fulfilled";
    if (backendHealthy) {
      state.runtime.backendHealth = "up";
      state.runtime.backendDownConsecutive = 0;
      state.runtime.silentRetryCount = 0;
      state.runtime.refreshPausedUntilMs = 0;
    } else {
      state.runtime.backendHealth = "down";
      state.runtime.backendDownConsecutive = safeNumber(state.runtime.backendDownConsecutive, 0) + 1;
      state.runtime.silentRetryCount = safeNumber(state.runtime.silentRetryCount, 0) + 1;
      state.runtime.reconnectCount = safeNumber(state.runtime.reconnectCount, 0) + 1;
      state.runtime.lastReconnectReason = "backend_unreachable";
      state.fetchWarnings.push("backend_unreachable");
      if (state.runtime.backendDownConsecutive >= MAX_BACKEND_DOWN_RETRY_BEFORE_PAUSE) {
        state.runtime.refreshPausedUntilMs = Date.now() + BACKEND_DOWN_PAUSE_MS;
      }
    }

    var token = getAccessToken();
    hasToken = Boolean(token);
    if (token) {
      var resetSynced = await syncPlatformResetEpoch(token);
      if (resetSynced) {
        opts.forceDriverReset = true;
      }
    }
    var timelineCursor = safeNumber((state.ops || {}).timelineCursor, 0);
    var opsFailures = 0;

    if (hasToken) {
      if (state.route === "dispatch") {
        try {
          var dispatchPreviousWorkflow = safeObject(
            (state.runtime && state.runtime.lastGoodLiveWorkflow) || state.liveWorkflow
          );
          var dispatchWorkflowSettled = await Promise.allSettled([
            fetchJson("/api/health-isf/dispatch/queue?limit=80&read_only=true", {}, token),
            fetchJson("/api/health-isf/dispatch/active-assignments?limit=80", {}, token),
            fetchJson("/api/health-isf/activity-feed?limit=40", {}, token)
          ]);
          if (dispatchWorkflowSettled[0].status === "rejected") {
            state.fetchWarnings.push("dispatch_queue_unavailable");
          }
          var dispatchLiveWorkflow = {
            dispatchQueue: dispatchWorkflowSettled[0].status === "fulfilled" && Array.isArray(dispatchWorkflowSettled[0].value) ? dispatchWorkflowSettled[0].value : null,
            activeAssignments: dispatchWorkflowSettled[1].status === "fulfilled" && Array.isArray(dispatchWorkflowSettled[1].value) ? dispatchWorkflowSettled[1].value : null,
            activityFeed: dispatchWorkflowSettled[2].status === "fulfilled" && Array.isArray((dispatchWorkflowSettled[2].value || {}).activities) ? (dispatchWorkflowSettled[2].value || {}).activities : null,
            drivers: null,
            rides: null,
            providers: null,
            customerRequests: null,
            vehicles: null
          };

          try {
            dispatchLiveWorkflow.drivers = await fetchJson("/api/health-isf/drivers?limit=120", {}, token);
          } catch (_) {
            state.fetchWarnings.push("drivers_unavailable");
          }

          try {
            dispatchLiveWorkflow.rides = await fetchJson("/api/health-isf/rides?limit=20&active_only=true&exclude_test=true", {}, token);
          } catch (_) {
            state.fetchWarnings.push("rides_unavailable");
          }

          var dispatchReferenceSettled = await Promise.allSettled([
            fetchJson("/api/health-isf/providers?limit=20", {}, token),
            fetchJson("/api/health-isf/customer-requests?limit=40", {}, token),
            fetchJson("/api/health-isf/vehicles/active?limit=40", {}, token)
          ]);
          state.liveWorkflow = mergeLiveWorkflowSnapshot(dispatchPreviousWorkflow, {
            dispatchQueue: dispatchLiveWorkflow.dispatchQueue,
            activeAssignments: dispatchLiveWorkflow.activeAssignments,
            drivers: Array.isArray(dispatchLiveWorkflow.drivers) ? dispatchLiveWorkflow.drivers : null,
            activityFeed: dispatchLiveWorkflow.activityFeed,
            rides: Array.isArray(dispatchLiveWorkflow.rides) ? dispatchLiveWorkflow.rides : null,
            providers: dispatchReferenceSettled[0].status === "fulfilled" && Array.isArray(dispatchReferenceSettled[0].value) ? dispatchReferenceSettled[0].value : null,
            customerRequests: dispatchReferenceSettled[1].status === "fulfilled" && Array.isArray(dispatchReferenceSettled[1].value) ? dispatchReferenceSettled[1].value : null,
            vehicles: dispatchReferenceSettled[2].status === "fulfilled" && Array.isArray(dispatchReferenceSettled[2].value) ? dispatchReferenceSettled[2].value : null
          });
          recordLastGoodLiveWorkflow();
          renderPage();
        } catch (_) {
          state.fetchWarnings.push("live_workflow_feed_unavailable");
          restoreLastGoodLiveWorkflowIfNeeded();
        }

        try {
          state.ops.workspaceActivation = await fetchJson(
            "/api/ops/workspace/activation?role_view=" + encodeURIComponent(String(state.role || "admin")),
            {},
            token
          );
        } catch (_) {
          state.fetchWarnings.push("workspace_activation_unavailable");
          state.ops.workspaceActivation = {
            role_view: state.role || "admin",
            role_scope: state.role || "admin",
            summary: null,
            compliance: null,
            orchestration: null,
            workspace_modules: {},
            allowed_actions: [],
            governance: {
              advisory_only: true,
              supervision_required: true,
              execution_disabled: true,
              append_only: true,
              replay_safe: true
            }
          };
        }

        state.fetchWarnings = dedupeWarnings(state.fetchWarnings);
        state.hydration = {
          authTokenPresent: hasToken,
          opsHydrated: true,
          roleSlice: state.role,
          lastUpdatedAt: new Date().toISOString(),
          warningCount: state.fetchWarnings.length,
          integrityState: computeHydrationIntegrity(
            hasToken,
            0,
            state.fetchWarnings,
            apiHealthOk || settled[1].status === "fulfilled",
            settled[2].status === "fulfilled"
          )
        };
        recomputeAssistantRuntimeState();
        persistSessionState();
        state.runtime.hydrationLoadGen = safeNumber(state.runtime.hydrationLoadGen, 0) + 1;
        scheduleEnterpriseMonitoringHydration(token, timelineCursor, state.runtime.hydrationLoadGen, hydrationDiag);
        return;
      }

      if (state.route === "billing") {
        state.liveWorkflow = safeObject(state.liveWorkflow);
        if (!Array.isArray(state.liveWorkflow.rides)) {
          state.liveWorkflow.rides = [];
        }
        if (!Array.isArray(state.liveWorkflow.billingHandoffs)) {
          state.liveWorkflow.billingHandoffs = [];
        }
        try {
          state.revenueWorkflow = await fetchJson("/api/health-isf/operations/revenue-workflow?window_hours=24", {}, token);
        } catch (_) {
          state.fetchWarnings.push("revenue_workflow_unavailable");
          state.revenueWorkflow = state.revenueWorkflow || null;
        }
        try {
          state.adminRevenue = await fetchJson("/api/health-isf/operations/admin-revenue", {}, token);
        } catch (_) {
          state.fetchWarnings.push("admin_revenue_unavailable");
          state.adminRevenue = state.adminRevenue || (state.runtime && state.runtime.lastGoodAdminRevenue) || null;
        }
        try {
          var billingRideRows = await fetchJson("/api/health-isf/rides?limit=40&history_only=true", {}, token);
          var billingActiveRows = await fetchJson("/api/health-isf/rides?limit=40&active_only=true&exclude_test=true", {}, token);
          var billingRideMap = {};
          (Array.isArray(billingRideRows) ? billingRideRows : []).forEach(function (row) {
            billingRideMap[safeText(row.id, "")] = row;
          });
          (Array.isArray(billingActiveRows) ? billingActiveRows : []).forEach(function (row) {
            billingRideMap[safeText(row.id, "")] = row;
          });
          state.liveWorkflow.rides = Object.keys(billingRideMap).map(function (key) {
            return billingRideMap[key];
          });
        } catch (_) {
          state.fetchWarnings.push("billing_rides_unavailable");
        }
        try {
          var billingHandoffRows = await fetchJson("/api/health-isf/operations/billing-handoffs?limit=100", {}, token);
          state.liveWorkflow.billingHandoffs = dedupeBillingHandoffsByRideId(
            Array.isArray(billingHandoffRows) ? billingHandoffRows : []
          );
        } catch (_) {
          state.fetchWarnings.push("billing_handoffs_unavailable");
        }
        try {
          var tripDocumentRows = await fetchJson("/api/health-isf/operations/trip-documents?limit=200", {}, token);
          state.liveWorkflow.tripDocuments = Array.isArray(tripDocumentRows) ? tripDocumentRows : state.liveWorkflow.tripDocuments;
        } catch (_) {
          state.fetchWarnings.push("trip_documents_unavailable");
        }
        recordLastGoodLiveWorkflow();
        window.AmiOpsShellState = state;
        state.hydration = {
          authTokenPresent: hasToken,
          opsHydrated: true,
          roleSlice: state.role,
          lastUpdatedAt: new Date().toISOString(),
          warningCount: state.fetchWarnings.length,
          integrityState: computeHydrationIntegrity(
            hasToken,
            0,
            state.fetchWarnings,
            apiHealthOk || settled[1].status === "fulfilled",
            settled[2].status === "fulfilled"
          )
        };
        recomputeAssistantRuntimeState();
        persistSessionState();
        state.runtime.hydrationLoadGen = safeNumber(state.runtime.hydrationLoadGen, 0) + 1;
        scheduleEnterpriseMonitoringHydration(token, timelineCursor, state.runtime.hydrationLoadGen, hydrationDiag);
        return;
      }

      var hydrationLoadGen = safeNumber(state.runtime.hydrationLoadGen, 0) + 1;
      state.runtime.hydrationLoadGen = hydrationLoadGen;
      scheduleEnterpriseMonitoringHydration(token, timelineCursor, hydrationLoadGen, hydrationDiag);

      if (state.role === "rider" || state.route === "riders") {
        try {
          await refreshRiderWorkspaceData();
        } catch (_) {
          state.fetchWarnings.push("rider_workspace_unavailable");
        }
      }

      if (state.route === "riders") {
        try {
          var riderRequestRows = await fetchJson("/api/health-isf/customer-requests?limit=80", {}, token);
          state.liveWorkflow = safeObject(state.liveWorkflow);
          state.liveWorkflow.customerRequests = Array.isArray(riderRequestRows) ? riderRequestRows : [];
        } catch (_) {
          state.fetchWarnings.push("rider_requests_unavailable");
        }
      } else {
        try {
          await hydrateEssentialWorkflowData(token, opts);
        } catch (_) {
          state.fetchWarnings.push("live_workflow_feed_unavailable");
        }
      }

      if (opsFailures > 0) {
        state.fetchWarnings.push("ops_hydration_partial");
      }

      try {
        state.ops.workspaceActivation = await fetchJson(
          "/api/ops/workspace/activation?role_view=" + encodeURIComponent(String(state.role || "admin")),
          {},
          token
        );
      } catch (_) {
        state.fetchWarnings.push("workspace_activation_unavailable");
        state.ops.workspaceActivation = {
          role_view: state.role || "admin",
          role_scope: state.role || "admin",
          summary: null,
          compliance: null,
          orchestration: null,
          workspace_modules: {},
          allowed_actions: [],
          governance: {
            advisory_only: true,
            supervision_required: true,
            execution_disabled: true,
            append_only: true,
            replay_safe: true
          }
        };
      }

      if ((state.role === "provider" || state.role === "admin") && (!state.ops.dashboardSummary || safeText(state.ops.visibility.show_provider_metrics, true) === "false")) {
        state.fetchWarnings.push("provider_slice_missing");
      }
    } else {
      state.fetchWarnings.push("ops_auth_required");
      state.ops.dashboardSummary = null;
      state.ops.liveStatus = null;
      state.ops.alerts = [];
      state.ops.recommendations = [];
      state.ops.timeline = [];
      state.ops.timelineCursor = 0;
      state.ops.stream = {
        connected: false,
        mode: "polling_fallback",
        fallbackPollingActive: true,
        lastEventReceived: null,
        eventCount: 0,
        timelineSyncStatus: "idle",
        supervisionSafe: true,
        replaySafe: true
      };
      state.ops.correlation = { totalGroups: 0, groups: [] };
      state.ops.compliance = {
        compliance_overview: null,
        expiration_queue: null,
        approval_queue: null,
        compliance_timeline: [],
        phase25: {
          evidence_chain_viewer: [],
          document_lineage_viewer: [],
          supervisor_review_queue: [],
          regulatory_export_builder: [],
          signed_access_monitor: [],
          retention_status_dashboard: []
        },
        profiles: [],
        documents: []
      };
      state.ops.orchestration = {
        queue_snapshot: {
          tasks: [],
          queue_health: {}
        },
        live_stream: {
          events: [],
          next_cursor: 0,
          checkpoint: null,
          stream_cursor: null
        },
        timeline_projection: {
          events: [],
          next_cursor: 0
        },
        notifications: {
          notifications: []
        },
        sla: {
          alerts: [],
          metrics: {}
        },
        queue_health: {
          queue_pressure_dashboard: {}
        },
        export_bundle: {
          bundle_id: null,
          bundle_checksum: null,
          replay_reconstruction: {}
        }
      };
      state.ops.federation = {
        regions: { regions: [] },
        queues: { regions: [] },
        capacity: { forecasts: [] },
        continuity: { continuity_projection: [] },
        health: { regions: [] },
        export_bundle: { bundle_id: null, bundle_checksum: null, payload: {} }
      };
      state.ops.replay = {
        session: { frames: [] },
        scenario: null,
        branch: null,
        timeline: { events: [] },
        projection: { events: [] },
        comparison: { comparisons: [] },
        continuity: null,
        evidence: { payload: {} },
        export_bundle: { bundle_id: null, bundle_checksum: null, payload: {} }
      };
      state.ops.predictive = {
        governance: null,
        constraints: null,
        capacity: null,
        risk: null,
        anomaly: null,
        drift: { drift_events: [] },
        recommendations: { recommendations: [] },
        trends: { trends: [] },
        evidence: { payload: {} },
        export_bundle: { bundle_id: null, bundle_checksum: null, payload: {} }
      };
      state.ops.governance = {
        provenance: null,
        explanations: null,
        reasoning: null,
        memory: null,
        ancestry: { ancestry_trace: [] },
        lineage: null,
        history: null,
        trends: null,
        policyMatrix: { policy_matrix: [], constraint_versions: [] },
        policyFrameworkMap: { frameworks: [], framework_rule_mappings: [] },
        policyEvaluations: { constraint_evaluations: [], constraint_violations: [], regulatory_evidence_refs: [] },
        policyScore: null,
        rationaleChain: { rationale_chain: [], decision_trace: [] },
        policyLineage: { policy_lineage: [] },
        policyHistory: { constraint_history: [], score_history: [] },
        policyViolations: { violations: [] },
        policyConstraints: { constraints: [] },
        policyFrameworks: { frameworks: [] },
        risk: { recommendations: [] },
        export_bundle: { bundle_id: null, bundle_checksum: null, payload: {} }
      };
      state.ops.workspaceActivation = {
        role_view: state.role || "admin",
        role_scope: state.role || "admin",
        summary: null,
        compliance: null,
        orchestration: null,
        workspace_modules: {},
        allowed_actions: [],
        governance: {
          advisory_only: true,
          supervision_required: true,
          execution_disabled: true,
          append_only: true,
          replay_safe: true
        }
      };
    }

    finalizeShellHydration(hasToken, settled, 0);
    recordLastGoodLiveWorkflow();
    } catch (err) {
      state.error = safeText(err && err.message, "operations_fetch_unavailable");
      if (isDriverMobileAppRoute()) {
        state.driverApp = safeObject(state.driverApp);
        state.driverApp.mobileUiState = "api_error";
        state.driverApp.mobileBootstrapError = state.error;
      }
      finishOpsHydrationDiagnostic(hydrationDiag, { error: state.error, route: state.route, role: state.role });
    } finally {
      if (hydrationTimer) {
        clearTimeout(hydrationTimer);
      }
      refreshInFlight = false;
      if (!hydrationTimedOut) {
        state.loading = false;
        clearStaleEnterpriseLoadingHtml();
        renderPage();
      }
      if (hydrationDiag) {
        finishOpsHydrationDiagnostic(hydrationDiag, { route: state.route, role: state.role, loading: false });
      }
    }
  }

  function startRefreshLoop() {
    restartDriverMobilePollInterval();
  }

  function restartDriverMobilePollInterval() {
    if (refreshHandle) {
      clearInterval(refreshHandle);
      refreshHandle = null;
    }
    var intervalMs = STABLE_POLL_INTERVAL_MS;
    if (isDriverMobileAppRoute()) {
      var mobileUi = safeText((safeObject(state.driverApp)).mobileUiState, "awaiting_assignment");
      if (mobileUi === "awaiting_assignment" || mobileUi === "loading_assignment") {
        intervalMs = DRIVER_AWAITING_POLL_INTERVAL_MS;
      }
    }
    refreshHandle = setInterval(function () {
      requestSilentRefresh("interval");
    }, intervalMs);
  }

  function cleanupLifecycleBindings() {
    if (refreshHandle) {
      clearInterval(refreshHandle);
      refreshHandle = null;
    }
    windowEventBindings.forEach(function (binding) {
      try {
        window.removeEventListener(binding.eventName, binding.handler);
      } catch (_) {}
    });
    documentEventBindings.forEach(function (binding) {
      try {
        document.removeEventListener(binding.eventName, binding.handler);
      } catch (_) {}
    });
    navEventBindings.forEach(function (binding) {
      try {
        binding.element.removeEventListener("click", binding.handler);
      } catch (_) {}
    });
    if (els.roleSelect && roleSelectChangeHandler) {
      try {
        els.roleSelect.removeEventListener("change", roleSelectChangeHandler);
      } catch (_) {}
    }
    if (runtimeUpdateHandler) {
      try {
        window.removeEventListener("ami:ops-runtime-updated", runtimeUpdateHandler);
      } catch (_) {}
    }
    windowEventBindings = [];
    documentEventBindings = [];
    navEventBindings = [];
    roleSelectChangeHandler = null;
    runtimeUpdateHandler = null;
    eventsBound = false;
  }

  function notifyDriverAssignmentIssued(detail) {
    try {
      localStorage.setItem("amicor_driver_assignment_ping", String(Date.now()));
    } catch (_) {}
    try {
      window.dispatchEvent(new CustomEvent("ami:driver-assignment-issued", { detail: detail || {} }));
    } catch (_) {}
  }

  window._amiNotifyDriverAssignmentIssued = notifyDriverAssignmentIssued;

  function requestSilentRefresh(source) {
    var triggerSource = safeText(source, "unknown");
    if (document.hidden) return;
    if (isDriverMobileSurface()) {
      if (refreshInFlight) return;
      refreshInFlight = true;
      refreshDriverWorkflowData({ lastAction: "Driver workspace synchronized (" + triggerSource + ")" }).catch(function () {}).finally(function () {
        refreshInFlight = false;
        if (!isDriverHydrationLocked()) {
          scheduleRenderPage();
        }
      });
      return;
    }
    if (refreshInFlight) return;
    if (shouldThrottleRefreshTrigger(triggerSource)) return;
    if (isDispatcherDraftFieldActive()) {
      console.info("[Dispatcher Pickup Trace]", {
        stage: "silentRefresh:deferred",
        triggerSource: triggerSource,
        activeElementId: document.activeElement && document.activeElement.id ? document.activeElement.id : null,
        activeElementTag: document.activeElement && document.activeElement.tagName ? document.activeElement.tagName : null,
        lastRefreshTriggerSource: safeText(state.runtime && state.runtime.lastRefreshTriggerSource, ""),
        route: safeText(state.route, ""),
      });
      return;
    }
    var userActiveRecently = (Date.now() - safeNumber(state.runtime.lastUserActivityAt, 0)) < USER_ACTIVITY_COOLDOWN_MS;
    if (state.runtime.operatorMode && userActiveRecently && (triggerSource === "focus" || triggerSource === "visibility" || triggerSource === "storage")) {
      return;
    }
    if (typeof navigator !== "undefined" && navigator.onLine === false) {
      state.fetchWarnings = dedupeWarnings((state.fetchWarnings || []).concat(["network_offline"]));
      if (!state.loading) {
        renderPage();
      }
      return;
    }
    refreshInFlight = true;
    loadBackendData({ silent: true }).catch(function () {
      state.fetchWarnings = dedupeWarnings((state.fetchWarnings || []).concat(["refresh_unavailable"]));
      state.runtime.reconnectCount = safeNumber(state.runtime.reconnectCount, 0) + 1;
      state.runtime.lastReconnectReason = "silent_refresh_failed";
      if (!state.loading) {
        renderPage();
      }
    }).finally(function () {
      refreshInFlight = false;
    });
  }

  function setRoute(route, pushHistory) {
    var source = arguments.length > 2 ? safeText(arguments[2], "route") : "route";
    var requested = ROUTES[route] ? route : "dashboard";
    var pathLockedRoute = dedicatedRouteFromPath(window.location.pathname);
    var target = requested;
    if (pathLockedRoute) {
      target = pathLockedRoute;
    } else if (requested === "mobile" || requested === "riders") {
      target = requested;
    } else if (!routeAllowed(state.role, target)) {
      target = defaultRouteForRole(state.role);
    }
    state.runtime.lastNavigationSource = source;
    state.route = target;
    state.roleRoutes[state.role] = target;
    if (target === "mobile") {
      persistMobileSurfacePreference("driver");
    } else if (target === "riders") {
      persistMobileSurfacePreference("rider");
    }
    recomputeAssistantRuntimeState();
    renderNav();
    renderPage();
    if (target === "ai-assistant") {
      void refreshAssistantPersistence().then(function () {
        persistSessionState();
        if (state.route === "ai-assistant") {
          renderPage();
        }
      });
    }
    persistSessionState();
    if (target === "mobile" || target === "drivers") {
      void resolveDriverMobileAuth(getAccessToken()).then(function () {
        updateTopBadges();
        scheduleRenderPage({ immediate: true });
      });
    }
    if (pushHistory) {
      var nextPath = safeText((ROUTES[target] || {}).path, routePathForRole(target, state.role));
      if (String(window.location.pathname || "") !== String(nextPath || "")) {
        history.pushState({ route: target, role: state.role }, "", nextPath);
      }
    }
    if (getAccessToken() && !refreshInFlight) {
      loadBackendData({ silent: true }).catch(function () {});
    }
  }

  function bindEvents() {
    if (eventsBound) return;
    eventsBound = true;

    els.navLinks.forEach(function (link) {
      var navClickHandler = function (event) {
        if (state.runtime.operatorMode && event && event.isTrusted === false) {
          state.runtime.suppressSyntheticClicks = safeNumber(state.runtime.suppressSyntheticClicks, 0) + 1;
          event.preventDefault();
          return;
        }
        event.preventDefault();
        markUserActivity("nav-click");
        var route = String(link.getAttribute("data-route") || "dashboard");
        setRoute(route, true, "nav-click");
      };
      navEventBindings.push({ element: link, handler: navClickHandler });
      link.addEventListener("click", navClickHandler);
    });

    roleSelectChangeHandler = function () {
      markUserActivity("role-switch");
      switchRoleView(String(els.roleSelect.value || "admin"), true);
    };
    els.roleSelect.addEventListener("change", roleSelectChangeHandler);

    var onPopState = function () {
      var roleFromPath = roleFromOperationalPath(window.location.pathname);
      if (roleFromPath && ROLE_ACCESS[roleFromPath]) {
        state.role = roleFromPath;
        saveRole(roleFromPath);
        if (els.roleSelect) {
          els.roleSelect.value = roleFromPath;
        }
      }
      setRoute(routeFromPath(window.location.pathname), false, "popstate");
    };
    windowEventBindings.push({ eventName: "popstate", handler: onPopState });
    window.addEventListener("popstate", onPopState);

    var onFocus = function () {
      requestSilentRefresh("focus");
    };
    windowEventBindings.push({ eventName: "focus", handler: onFocus });
    window.addEventListener("focus", onFocus);

    var onVisibilityChange = function () {
      if (!document.hidden) {
        requestSilentRefresh("visibility");
      }
    };
    documentEventBindings.push({ eventName: "visibilitychange", handler: onVisibilityChange });
    document.addEventListener("visibilitychange", onVisibilityChange);

    if (els.pageContent) {
      var riderActionDelegate = function (event) {
        var target = event && event.target;
        if (!target || !target.closest) return;
        var button = target.closest("[data-rider-action]");
        if (!button || !els.pageContent.contains(button)) return;
        event.preventDefault();
        var action = safeText(button.getAttribute("data-rider-action"), "");
        var noteId = safeText(button.getAttribute("data-note-id"), "");
        void handleRiderWorkspaceAction(action, noteId);
      };
      documentEventBindings.push({ eventName: "click", handler: riderActionDelegate, element: els.pageContent });
      els.pageContent.addEventListener("click", riderActionDelegate);

      var driverActionDelegate = function (event) {
        var target = event && event.target;
        if (!target || !target.closest) return;
        var button = target.closest("[data-driver-action]");
        if (!button || !els.pageContent.contains(button)) return;
        if (button.disabled) return;
        event.preventDefault();
        if (driverActionInFlight) return;
        var action = safeText(button.getAttribute("data-driver-action"), "");
        var tripId = safeText(button.getAttribute("data-trip-id"), "");
        var noteId = safeText(button.getAttribute("data-note-id"), "");
        driverActionInFlight = true;
        button.disabled = true;
        void handleDriverWorkspaceAction(action, tripId, noteId).finally(function () {
          driverActionInFlight = false;
          button.disabled = false;
        });
      };
      documentEventBindings.push({ eventName: "click", handler: driverActionDelegate, element: els.pageContent });
      els.pageContent.addEventListener("click", driverActionDelegate);
    }

    var onStorage = function (event) {
      if (!event || !event.key) return;
      if (event.key === "amicor_session" || event.key === "amicor_identity") {
        requestSilentRefresh("storage");
      }
      if (event.key === DRIVER_SESSION_STORAGE_KEY || event.key === "amicor_driver_workflow_id") {
        driverMobileAuthCache = null;
        void resolveDriverMobileAuth(getAccessToken()).then(function () {
          updateTopBadges();
          scheduleRenderPage();
          if (isDriverMobileSurface()) {
            refreshDriverWorkflowData({ token: getAccessToken() }).catch(function () {});
          }
        });
      }
      if (event.key === "amicor_driver_assignment_ping" && isDriverMobileSurface()) {
        refreshDriverWorkflowData({ lastAction: "Driver assignment ping (storage)" }).catch(function () {});
      }
    };
    windowEventBindings.push({ eventName: "storage", handler: onStorage });
    window.addEventListener("storage", onStorage);

    var onPlatformSessionRecovered = function () {
      state.hydration = safeObject(state.hydration);
      state.hydration.authTokenPresent = !!getAccessToken();
      requestSilentRefresh("session-recovered");
      scheduleRenderPage();
    };
    ["amicor:session-recovered", "amicor:workspace-role-updated"].forEach(function (eventName) {
      windowEventBindings.push({ eventName: eventName, handler: onPlatformSessionRecovered });
      window.addEventListener(eventName, onPlatformSessionRecovered);
    });
    var onPlatformSessionInvalid = function () {
      state.hydration = safeObject(state.hydration);
      state.hydration.authTokenPresent = false;
      state.hydration.integrityState = "AUTH_REQUIRED";
      scheduleRenderPage();
    };
    windowEventBindings.push({ eventName: "amicor:session-invalid", handler: onPlatformSessionInvalid });
    window.addEventListener("amicor:session-invalid", onPlatformSessionInvalid);

    var onDriverSessionUpdated = function () {
      driverMobileAuthCache = null;
      void resolveDriverMobileAuth(getAccessToken()).then(function () {
        updateTopBadges();
        scheduleRenderPage();
        refreshDriverWorkflowData({ token: getAccessToken() }).catch(function () {});
      });
    };
    windowEventBindings.push({ eventName: "ami:driver-session-updated", handler: onDriverSessionUpdated });
    window.addEventListener("ami:driver-session-updated", onDriverSessionUpdated);

    var onDriverAssignmentIssued = function () {
      if (!isDriverMobileSurface()) return;
      refreshDriverWorkflowData({ lastAction: "Driver assignment issued (event)" }).catch(function () {});
    };
    windowEventBindings.push({ eventName: "ami:driver-assignment-issued", handler: onDriverAssignmentIssued });
    window.addEventListener("ami:driver-assignment-issued", onDriverAssignmentIssued);

    var onOnline = function () {
      requestSilentRefresh("online");
    };
    windowEventBindings.push({ eventName: "online", handler: onOnline });
    window.addEventListener("online", onOnline);

    var onOffline = function () {
      state.fetchWarnings = dedupeWarnings((state.fetchWarnings || []).concat(["network_offline"]));
      if (!state.loading) {
        renderPage();
      }
    };
    windowEventBindings.push({ eventName: "offline", handler: onOffline });
    window.addEventListener("offline", onOffline);

    var onUnhandledRejection = function (event) {
      var rejectionReason = safeText(event && event.reason && event.reason.message ? event.reason.message : event && event.reason, "").toLowerCase();
      var warningCode = rejectionReason.indexOf("abort") >= 0 ? "client_request_aborted" : "client_unhandled_rejection";
      state.fetchWarnings = dedupeWarnings((state.fetchWarnings || []).concat([warningCode]));
      if (!state.loading) {
        renderPage();
      }
    };
    windowEventBindings.push({ eventName: "unhandledrejection", handler: onUnhandledRejection });
    window.addEventListener("unhandledrejection", onUnhandledRejection);

    var onError = function () {
      state.fetchWarnings = dedupeWarnings((state.fetchWarnings || []).concat(["client_runtime_error"]));
      if (!state.loading) {
        renderPage();
      }
    };
    windowEventBindings.push({ eventName: "error", handler: onError });
    window.addEventListener("error", onError);

    var markActivity = function () {
      markUserActivity("operator-activity");
    };
    ["click", "scroll", "wheel", "keydown", "touchstart"].forEach(function (eventName) {
      windowEventBindings.push({ eventName: eventName, handler: markActivity });
      window.addEventListener(eventName, markActivity, { passive: true });
    });

    runtimeUpdateHandler = function () {
      persistSessionState();
      if (isDriverMobileAppRoute()) {
        requestSilentRefresh("runtime-event");
        return;
      }
      if (state.role === "rider") {
        refreshRiderWorkspaceData({ lastAction: "Live ride update received" }).catch(function () {}).finally(function () {
          if (!state.loading) {
            scheduleRenderPage();
          }
        });
      }
      requestSilentRefresh("runtime-event");
    };
    window.addEventListener("ami:ops-runtime-updated", runtimeUpdateHandler);

    var onPageHide = function () {
      cleanupLifecycleBindings();
    };
    windowEventBindings.push({ eventName: "pagehide", handler: onPageHide });
    window.addEventListener("pagehide", onPageHide);
  }

  function applyPlatformResetFromUrl() {
    try {
      var params = new URLSearchParams(window.location.search || "");
      if (params.get("platform_reset") !== "1") return;
      clearPlatformClientCaches();
      if (window.history && window.history.replaceState) {
        params.delete("platform_reset");
        var nextQuery = params.toString();
        var nextUrl = window.location.pathname + (nextQuery ? "?" + nextQuery : "");
        window.history.replaceState({}, "", nextUrl);
      }
    } catch (_) {}
  }

  async function initialize() {
    applyPlatformResetFromUrl();
    state.assistant = buildDefaultAssistantState();
    state.runtime.operatorMode = isOperatorModeEnabled();
    await ensurePlatformSessionReady();
    var pathRoute = routeFromPath(window.location.pathname);
    state.role = initializePlatformRole(pathRoute);
    await syncPlatformRoleAuth(getPlatformRole());
    hydrateSessionState();
    alignPlatformRoleWithDedicatedPath(pathRoute);
    recomputeAssistantRuntimeState();
    var deepLinkedRole = roleFromOperationalPath(window.location.pathname);
    if (deepLinkedRole && ROLE_ACCESS[deepLinkedRole]) {
      state.role = deepLinkedRole;
      savePlatformRole(deepLinkedRole);
    }
    els.roleSelect.value = getPlatformRole();
    var rememberedRoute = safeText((state.roleRoutes || {})[state.role], "");
    var initialRoute = resolveInitialAppRoute(pathRoute, rememberedRoute);
    setRoute(initialRoute, false, "initialize");
    if ((initialRoute === "mobile" || initialRoute === "riders") && pathRoute === "dashboard") {
      var dedicatedPath = routePathForRole(initialRoute, state.role);
      if (window.history && window.history.replaceState && String(window.location.pathname || "") !== String(dedicatedPath || "")) {
        window.history.replaceState({ route: initialRoute, role: state.role }, "", dedicatedPath);
      }
    }
    bindEvents();
    startRefreshLoop();
    if (isDriverMobileSurface()) {
      updateTopBadges();
    }
    loadBackendData({ forceDriverReset: false });
    void refreshAssistantPersistence();
  }

  window.AmiOpsShellActions = {
    submitWorkspaceAction: async function (actionType, payload, roleView) {
      var action = safeText(actionType, "").toLowerCase();
      if (!action) {
        return { ok: false, detail: "action_type_required" };
      }
      var targetRole = safeText(roleView, state.role || "admin");
      var response = await fetchJson(
        "/api/ops/workspace/action?role_view=" + encodeURIComponent(targetRole),
        {
          method: "POST",
          body: JSON.stringify({ action_type: action, payload: safeObject(payload) })
        }
      );
      return { ok: true, response: response };
    },
    requestJson: async function (url, method, payload) {
      try {
        var response = await fetchJson(
          safeText(url, ""),
          {
            method: safeText(method, "GET").toUpperCase(),
            body: payload == null ? undefined : JSON.stringify(payload)
          }
        );
        return { ok: true, response: response };
      } catch (err) {
        return { ok: false, detail: (err && err.message) ? err.message : "request_failed" };
      }
    },
    refreshData: async function () {
      try {
        await loadBackendData({ silent: true });
        return { ok: true };
      } catch (err) {
        return { ok: false, detail: (err && err.message) ? err.message : "refresh_failed" };
      }
    },
    retryOperationsHydration: async function () {
      try {
        state.error = null;
        state.fetchWarnings = [];
        await loadBackendData({ silent: false });
        return { ok: true };
      } catch (err) {
        restoreLastGoodLiveWorkflowIfNeeded();
        return { ok: false, detail: (err && err.message) ? err.message : "retry_failed" };
      }
    },
    sendJson: sendJson,
    refreshDriverWorkflowData: refreshDriverWorkflowData,
    retryDriverMobileAssignmentSync: retryDriverMobileAssignmentSync,
    applyDriverWorkflowSnapshot: applyDriverWorkflowSnapshot,
    scheduleRenderPage: scheduleRenderPage,
    lockDriverHydration: lockDriverHydration,
    ensureAuthenticatedSession: ensureAuthenticatedSession,
    getAccessToken: getAccessToken,
    getMobileSessionDriverId: getMobileSessionDriverId,
    getCanonicalMobileDriverContext: getCanonicalMobileDriverContext,
    resolveCanonicalMobileDriverId: resolveCanonicalMobileDriverId,
    resetDriverMobileAfterCompletion: resetDriverMobileAfterCompletion,
    logDriverMobileAssignmentSync: logDriverMobileAssignmentSync
  };

  window.AmiOpsShellState = state;
  window.AmiOpsShellRender = renderPage;

  initialize();
})();

// ── Interactive event handlers ────────────────────────────────────────────────

var state = window.AmiOpsShellState || {};

if (typeof safeNumber !== "function") {
  function safeNumber(value, fallback) {
    var numeric = Number(value);
    if (!Number.isFinite(numeric)) {
      return Number.isFinite(Number(fallback)) ? Number(fallback) : 0;
    }
    return numeric;
  }
}

if (typeof safeText !== "function") {
  function safeText(value, fallback) {
    if (value === null || value === undefined) {
      return fallback === null || fallback === undefined ? "" : String(fallback);
    }
    return String(value);
  }
}

if (typeof safeObject !== "function") {
  function safeObject(value) {
    return value && typeof value === "object" ? value : {};
  }
}

function normalizeDriverTripStatus(raw) {
  var value = safeText(raw, "queued").toLowerCase();
  var mapped = {
    reassignment_pending: "assigned",
    offered: "queued",
    pending: "queued",
    dispatchable: "queued",
    assigned: "assigned",
    accepted: "accepted",
    en_route_pickup: "driver_en_route",
    driver_en_route: "driver_en_route",
    arrived_pickup: "arrived",
    waiting_at_pickup: "arrived",
    at_pickup: "arrived",
    arrived: "arrived",
    rider_loaded: "rider_onboard",
    rider_onboard: "rider_onboard",
    trip_in_progress: "in_progress",
    in_progress: "in_progress",
    in_transit: "in_progress",
    arrived_destination: "arrived_destination",
    completed: "completed",
    no_show: "declined",
    cancelled: "cancelled",
    declined: "declined"
  };
  return mapped[value] || value;
}

function resolveDriverTripLifecycleStatus(assignmentState, lifecycleState) {
  var assignment = safeText(assignmentState, "");
  var lifecycle = safeText(lifecycleState, "");
  if (!lifecycle && assignment) return assignment;
  if (!assignment && lifecycle) return lifecycle;
  var order = {
    queued: 1,
    assigned: 2,
    offered: 2,
    pending: 2,
    accepted: 3,
    driver_en_route: 4,
    en_route_pickup: 4,
    arrived: 5,
    arrived_pickup: 5,
    waiting_at_pickup: 5,
    rider_onboard: 6,
    rider_loaded: 6,
    in_progress: 7,
    trip_in_progress: 7,
    in_transit: 7,
    arrived_destination: 8,
    completed: 9
  };
  var aKey = normalizeDriverTripStatus(assignment);
  var lKey = normalizeDriverTripStatus(lifecycle);
  var aRank = order[aKey] || 0;
  var lRank = order[lKey] || 0;
  if (lRank > aRank) return lifecycle;
  if (lRank === aRank && lifecycle) return lifecycle;
  return assignment;
}

function _amiStatusFromRouteProgressPayload(payload, fallback) {
  var workspace = safeObject(payload);
  var activeRide = safeObject(workspace.active_ride || payload);
  var assignment = safeObject(workspace.active_assignment);
  return resolveDriverTripLifecycleStatus(
    safeText(assignment.assignment_state, ""),
    safeText(activeRide.lifecycle_state || activeRide.status, fallback)
  );
}

function _amiCanonicalMobileDriverId(shell) {
  if (window.AmiOpsShellActions && typeof window.AmiOpsShellActions.resolveCanonicalMobileDriverId === "function") {
    var sessionBound = safeText(window.AmiOpsShellActions.resolveCanonicalMobileDriverId(), "");
    if (sessionBound) return sessionBound;
  }
  shell = shell || _amiDriverShellState();
  return safeText((safeObject(shell.driverApp)).currentDriverId || (safeObject(shell.driverWorkflow)).driverId, "");
}

function _amiDriverShellState() {
  state = window.AmiOpsShellState || state || {};
  if (!window.AmiOpsShellState) {
    window.AmiOpsShellState = state;
  }
  return state;
}

function _amiPatchDriverTripStatus(tripId, nextStatus) {
  var shell = _amiDriverShellState();
  shell.driverApp = safeObject(shell.driverApp);
  var queue = Array.isArray(shell.driverApp.tripQueue) ? shell.driverApp.tripQueue : [];
  var normalized = normalizeDriverTripStatus(nextStatus);
  queue.forEach(function (trip) {
    if (safeText(trip.tripId, "") === safeText(tripId, "")) {
      trip.status = normalized;
      trip.coordinationStatus = safeText(nextStatus, normalized);
    }
  });
  shell.driverApp.tripQueue = queue;
  shell.driverApp.activeTripId = safeText(tripId, shell.driverApp.activeTripId);
  shell.driverApp.activeStage = normalized;
  shell.driverApp.lastStatusUpdate = safeText(nextStatus, "updated");
  window.AmiOpsShellState = shell;
  return shell;
}

async function _amiSubmitWorkspaceAction(actionType, payload, roleView) {
  if (!window.AmiOpsShellActions || typeof window.AmiOpsShellActions.submitWorkspaceAction !== "function") {
    return { ok: false, detail: "workspace_action_gateway_unavailable" };
  }
  try {
    return await window.AmiOpsShellActions.submitWorkspaceAction(actionType, payload, roleView);
  } catch (err) {
    return { ok: false, detail: (err && err.message) ? err.message : "workspace_action_failed" };
  }
}

async function _amiRequestJson(url, method, payload) {
  if (!window.AmiOpsShellActions || typeof window.AmiOpsShellActions.requestJson !== "function") {
    return { ok: false, detail: "workspace_request_gateway_unavailable" };
  }
  try {
    return await window.AmiOpsShellActions.requestJson(url, method, payload);
  } catch (err) {
    return { ok: false, detail: (err && err.message) ? err.message : "request_failed" };
  }
}

async function _amiEnsureDispatcherAuth(message) {
  if (window.AmiOpsShellActions && typeof window.AmiOpsShellActions.getAccessToken === "function") {
    if (window.AmiOpsShellActions.getAccessToken()) {
      return true;
    }
  }
  if (window.AmiOpsShellActions && typeof window.AmiOpsShellActions.ensureAuthenticatedSession === "function") {
    return await window.AmiOpsShellActions.ensureAuthenticatedSession(message || "Sign in to use dispatch actions.");
  }
  window.alert(message || "Sign in to use dispatch actions.");
  return false;
}

async function _amiEnsureDispatchWriteRole(message) {
  if (!(await _amiEnsureDispatcherAuth(message))) {
    return false;
  }
  var writeRoles = ["admin", "dispatcher", "supervisor"];
  function currentJwtRole() {
    if (window.AmiCorSession && typeof window.AmiCorSession.getRole === "function") {
      return safeText(window.AmiCorSession.getRole(), "").toLowerCase();
    }
    return "";
  }
  if (writeRoles.indexOf(currentJwtRole()) >= 0) {
    return true;
  }
  var authorized = [];
  if (window.AmiCorSession && typeof window.AmiCorSession.getSessionProfile === "function") {
    var profile = safeObject(window.AmiCorSession.getSessionProfile());
    if (Array.isArray(profile.authorizedRoles)) {
      authorized = profile.authorizedRoles.map(function (item) {
        return safeText(item, "").toLowerCase();
      });
    }
  }
  if (!authorized.length && window.AmiCorSession && typeof window.AmiCorSession.getCurrent === "function") {
    var identity = safeObject((window.AmiCorSession.getCurrent() || {}).identity);
    if (Array.isArray(identity.authorizedRoles)) {
      authorized = identity.authorizedRoles.map(function (item) {
        return safeText(item, "").toLowerCase();
      });
    }
  }
  var platformRole = "";
  try {
    platformRole = safeText(window.localStorage.getItem("amicor_platform_role"), "").toLowerCase();
  } catch (_err) {}
  var preferred = writeRoles.indexOf(platformRole) >= 0
    ? platformRole
    : (["dispatcher", "admin", "supervisor"].find(function (item) {
        return authorized.indexOf(item) >= 0;
      }) || "");
  if (!preferred || !(window.AmiCorSession && typeof window.AmiCorSession.switchWorkspaceRole === "function")) {
    window.alert("Insufficient role permissions. Switch to dispatcher or admin before creating rides.");
    return false;
  }
  try {
    await window.AmiCorSession.switchWorkspaceRole(preferred);
  } catch (err) {
    window.alert(safeText(err && err.message, "Unable to switch workspace role for ride creation."));
    return false;
  }
  return writeRoles.indexOf(currentJwtRole()) >= 0;
}

async function _amiRefreshDispatcherWorkspace() {
  var token = window.AmiOpsShellActions && typeof window.AmiOpsShellActions.getAccessToken === "function"
    ? window.AmiOpsShellActions.getAccessToken()
    : "";
  if (!token || !window.AmiOpsShellActions || typeof window.AmiOpsShellActions.requestJson !== "function") {
    if (window.AmiOpsShellActions && typeof window.AmiOpsShellActions.refreshData === "function") {
      await window.AmiOpsShellActions.refreshData();
    }
    return;
  }
  state.liveWorkflow = safeObject(state.liveWorkflow);
  var settled = await Promise.allSettled([
    window.AmiOpsShellActions.requestJson("/api/health-isf/providers?limit=200", "GET"),
    window.AmiOpsShellActions.requestJson("/api/health-isf/customer-requests?limit=200", "GET"),
    window.AmiOpsShellActions.requestJson("/api/health-isf/rides?limit=200&active_only=true&exclude_test=true", "GET"),
    window.AmiOpsShellActions.requestJson("/api/health-isf/drivers?limit=120", "GET"),
    window.AmiOpsShellActions.requestJson("/api/health-isf/dispatch/queue?limit=200", "GET")
  ]);
  if (settled[0].status === "fulfilled" && settled[0].value && settled[0].value.ok && Array.isArray(settled[0].value.response)) {
    state.liveWorkflow.providers = settled[0].value.response;
  }
  if (settled[1].status === "fulfilled" && settled[1].value && settled[1].value.ok && Array.isArray(settled[1].value.response)) {
    state.liveWorkflow.customerRequests = settled[1].value.response;
  }
  if (settled[2].status === "fulfilled" && settled[2].value && settled[2].value.ok && Array.isArray(settled[2].value.response)) {
    state.liveWorkflow.rides = settled[2].value.response;
  }
  if (settled[3].status === "fulfilled" && settled[3].value && settled[3].value.ok && Array.isArray(settled[3].value.response)) {
    state.liveWorkflow.drivers = settled[3].value.response;
  }
  if (settled[4].status === "fulfilled" && settled[4].value && settled[4].value.ok && Array.isArray(settled[4].value.response)) {
    state.liveWorkflow.dispatchQueue = settled[4].value.response;
  }
  if (typeof window.AmiOpsShellRender === "function") {
    window.AmiOpsShellRender();
  }
}

function _amiValue(id) {
  var el = document.getElementById(id);
  return safeText(el && el.value, "");
}

function _amiSetValue(id, value) {
  var el = document.getElementById(id);
  if (el) {
    el.value = safeText(value, "");
  }
}

function _amiLiveCustomerRequests() {
  var live = safeObject(state.liveWorkflow);
  return Array.isArray(live.customerRequests) ? live.customerRequests : [];
}

function _amiLiveRides() {
  var live = safeObject(state.liveWorkflow);
  return Array.isArray(live.rides) ? live.rides : [];
}

function _amiRecordDispatcherAction(level, message, detail) {
  var workspace = safeObject(state.dispatcherWorkspace);
  if (!Array.isArray(workspace.messages)) {
    workspace.messages = [];
  }
  workspace.messages.unshift({
    id: "dispatch-msg-" + String(Date.now()) + "-" + String(Math.floor(Math.random() * 1000)),
    level: safeText(level, "info"),
    message: safeText(message, "Action result"),
    detail: safeText(detail, ""),
    ts: new Date().toISOString()
  });
  workspace.messages = workspace.messages.slice(0, 30);
  state.dispatcherWorkspace = workspace;
  if (typeof window.AmiOpsShellRender === "function") {
    window.AmiOpsShellRender();
  }
}

function _amiSetDispatcherProof(lastAction, apiStatus, dbRecordId, uiUpdated) {
  var workspace = safeObject(state.dispatcherWorkspace);
  var proof = safeObject(workspace.proof);
  proof.last_action = safeText(lastAction, safeText(proof.last_action, "none"));
  proof.api_status = safeText(apiStatus, safeText(proof.api_status, "idle"));
  proof.db_record_id = safeText(dbRecordId, safeText(proof.db_record_id, "n/a"));
  proof.ui_updated = uiUpdated ? "yes" : "no";
  workspace.proof = proof;
  state.dispatcherWorkspace = workspace;
  if (typeof window.AmiOpsShellRender === "function") {
    window.AmiOpsShellRender();
  }
}

function _amiDispatcherError(message, detail) {
  _amiRecordDispatcherAction("error", message, detail);
  _amiSetDispatcherProof(message, "error", "n/a", false);
}

function _amiDispatcherSuccess(message, detail) {
  _amiRecordDispatcherAction("success", message, detail);
  _amiSetDispatcherProof(message, "ok", safeText(detail, "n/a"), true);
}

window._amiUpdateDispatcherPatientDraft = function(field, value) {
  var workspace = safeObject(state.dispatcherWorkspace);
  var draft = safeObject(workspace.patientDraft);
  var key = safeText(field, "").toLowerCase();
  if (!key) return;
  if (key !== "name" && key !== "phone" && key !== "pickup" && key !== "dropoff") return;
  draft[key] = safeText(value, "");
  workspace.patientDraft = draft;
  state.dispatcherWorkspace = workspace;
};

window._amiTraceDispatcherPickupEvent = function(stage, fieldId, value, relatedTarget) {
  try {
    console.info("[Dispatcher Pickup Trace]", {
      stage: safeText(stage, "unknown"),
      fieldId: safeText(fieldId, ""),
      valueLength: safeText(value, "").length,
      activeElementId: document.activeElement && document.activeElement.id ? document.activeElement.id : null,
      activeElementTag: document.activeElement && document.activeElement.tagName ? document.activeElement.tagName : null,
      relatedTarget: safeText(relatedTarget, ""),
      lastRefreshTriggerSource: safeText(state.runtime && state.runtime.lastRefreshTriggerSource, ""),
      lastRefreshTriggerAt: safeText(state.runtime && state.runtime.lastRefreshTriggerAt, ""),
      currentRoute: safeText(state.route, ""),
    });
    if (safeText(stage, "") === "blur") {
      setTimeout(function () {
        flushDeferredDispatcherDraftRender();
      }, 0);
    }
  } catch (_) {}
};

function traceDispatcherPickupRender(stage) {
  try {
    var activeElement = document.activeElement || null;
    var activeId = activeElement && activeElement.id ? String(activeElement.id) : "";
    var activeTag = activeElement && activeElement.tagName ? String(activeElement.tagName) : "";
    var activeIsPickup = activeId === "dispatcher-patient-pickup" || activeId === "dispatcher-ride-pickup";
    console.info("[Dispatcher Pickup Render]", {
      stage: safeText(stage, "unknown"),
      activeElementId: activeId || null,
      activeElementTag: activeTag || null,
      activeIsPickup: activeIsPickup,
      lastRefreshTriggerSource: safeText(state.runtime && state.runtime.lastRefreshTriggerSource, ""),
      lastRefreshTriggerAt: safeText(state.runtime && state.runtime.lastRefreshTriggerAt, ""),
      route: safeText(state.route, ""),
      loading: !!state.loading,
    });
  } catch (_) {}
}

function isDispatcherDraftFieldActive() {
  var activeElement = document.activeElement || null;
  if (!activeElement || !activeElement.id) return false;
  return [
    "dispatcher-patient-name",
    "dispatcher-patient-phone",
    "dispatcher-patient-pickup",
    "dispatcher-patient-dropoff",
    "dispatcher-ride-passenger",
    "dispatcher-ride-phone",
    "dispatcher-ride-pickup",
    "dispatcher-ride-dropoff",
    "dispatcher-ride-service"
  ].indexOf(String(activeElement.id)) >= 0;
}

function isRiderDraftFieldActive() {
  var activeElement = document.activeElement || null;
  if (!activeElement || !activeElement.id) return false;
  return [
    "rider-name-input",
    "rider-phone-input",
    "rider-pickup-input",
    "rider-dropoff-input",
    "rider-ride-type-input",
    "rider-notes-input"
  ].indexOf(String(activeElement.id)) >= 0;
}

function flushDeferredDispatcherDraftRender() {
  if (!window.__amiDispatcherDraftRenderDeferred) return;
  if (isDispatcherDraftFieldActive() || isRiderDraftFieldActive()) return;
  window.__amiDispatcherDraftRenderDeferred = false;
  renderPage();
}

window._amiUpdateRiderProfileDraft = function(field, value) {
  var shellState = window.AmiOpsShellState || state || {};
  shellState.riderApp = shellState.riderApp && typeof shellState.riderApp === "object" ? shellState.riderApp : {};
  shellState.riderApp.profile = shellState.riderApp.profile && typeof shellState.riderApp.profile === "object"
    ? shellState.riderApp.profile
    : {};
  var key = safeText(field, "");
  if (!key) return;
  if (key === "phone") {
    shellState.riderApp.profile.phone = safeText(value, "").replace(/[^\d+]/g, "").slice(0, 20);
  } else if (key === "sameDriverPreference") {
    shellState.riderApp.profile.sameDriverPreference = value === true || value === "true";
  } else {
    shellState.riderApp.profile[key] = safeText(value, "");
  }
  try {
    var raw = sessionStorage.getItem("amicor_shell_session_v1");
    var parsed = raw ? JSON.parse(raw) : {};
    if (!parsed || typeof parsed !== "object") parsed = {};
    parsed.riderApp = {
      profile: shellState.riderApp.profile,
      activeRequestId: safeText(shellState.riderApp.activeRequestId, ""),
      lastSubmit: shellState.riderApp.lastSubmit || null
    };
    sessionStorage.setItem("amicor_shell_session_v1", JSON.stringify(parsed));
  } catch (_) {}
};

window._amiToggleRiderWeekday = function(day, checked) {
  var shellState = window.AmiOpsShellState || state || {};
  shellState.riderApp = shellState.riderApp && typeof shellState.riderApp === "object" ? shellState.riderApp : {};
  shellState.riderApp.profile = shellState.riderApp.profile && typeof shellState.riderApp.profile === "object"
    ? shellState.riderApp.profile
    : {};
  var weekdays = Array.isArray(shellState.riderApp.profile.recurrenceWeekdays)
    ? shellState.riderApp.profile.recurrenceWeekdays.slice()
    : [];
  var normalized = safeText(day, "").toLowerCase().slice(0, 3);
  var idx = weekdays.indexOf(normalized);
  if (checked && idx < 0) {
    weekdays.push(normalized);
  } else if (!checked && idx >= 0) {
    weekdays.splice(idx, 1);
  }
  shellState.riderApp.profile.recurrenceWeekdays = weekdays;
  window._amiUpdateRiderProfileDraft("recurrenceWeekdays", weekdays.join(","));
  shellState.riderApp.profile.recurrenceWeekdays = weekdays;
};

window._amiHandleDispatcherCreatePatient = async function() {
  if (!(await _amiEnsureDispatcherAuth("Sign in as admin or dispatcher before creating a rider."))) {
    return;
  }
  var riderName = _amiValue("dispatcher-patient-name");
  var riderPhone = _amiValue("dispatcher-patient-phone");
  var pickup = _amiValue("dispatcher-patient-pickup");
  var dropoff = _amiValue("dispatcher-patient-dropoff");
  window._amiUpdateDispatcherPatientDraft("name", riderName);
  window._amiUpdateDispatcherPatientDraft("phone", riderPhone);
  window._amiUpdateDispatcherPatientDraft("pickup", pickup);
  window._amiUpdateDispatcherPatientDraft("dropoff", dropoff);
  if (!riderName || !riderPhone || !pickup || !dropoff) {
    _amiDispatcherError("Create Patient failed", "Missing required patient fields.");
    window.alert("Enter patient name, phone, pickup, and dropoff.");
    return;
  }
  var result = await _amiRequestJson(
    "/api/health-isf/customer-requests",
    "POST",
    {
      rider_name: riderName,
      rider_phone: riderPhone,
      pickup_address: pickup,
      dropoff_address: dropoff,
      ride_type: "healthcare",
      recurring: false
    }
  );
  if (!result || result.ok === false) {
    _amiDispatcherError("Create Patient failed", safeText(result && result.detail, "backend request failed"));
    window.alert("Unable to create patient request.");
    return;
  }
  var createdRequestId = safeText((safeObject(result.response)).id, "");
  await _amiRefreshDispatcherWorkspace();
  var foundPatient = (Array.isArray((safeObject(state.liveWorkflow)).customerRequests) ? state.liveWorkflow.customerRequests : []).some(function (item) {
    return safeText(item.id, "") === createdRequestId;
  });
  if (createdRequestId && foundPatient) {
    var workspace = safeObject(state.dispatcherWorkspace);
    if (Array.isArray(workspace.messages)) {
      workspace.messages = workspace.messages.filter(function (entry) {
        return !(safeText(entry && entry.level, "") === "error" && safeText(entry && entry.message, "") === "Create Patient failed");
      });
      state.dispatcherWorkspace = workspace;
    }
    window._amiUpdateDispatcherPatientDraft("name", "");
    window._amiUpdateDispatcherPatientDraft("phone", "");
    window._amiUpdateDispatcherPatientDraft("pickup", "");
    window._amiUpdateDispatcherPatientDraft("dropoff", "");
    _amiSetValue("dispatcher-patient-name", "");
    _amiSetValue("dispatcher-patient-phone", "");
    _amiSetValue("dispatcher-patient-pickup", "");
    _amiSetValue("dispatcher-patient-dropoff", "");
    _amiDispatcherSuccess("Create Rider succeeded", "request_id=" + createdRequestId);
    _amiSetDispatcherProof("Create Rider", "ok", createdRequestId, true);
  } else {
    _amiDispatcherError("Create Patient partial", "Created request was not found in refreshed customer request list.");
    _amiSetDispatcherProof("Create Rider", "partial", createdRequestId || "n/a", false);
  }
};

window._amiHandleDispatcherCreateDriver = async function() {
  var name = _amiValue("dispatcher-driver-name");
  var phone = _amiValue("dispatcher-driver-phone");
  var vehicleType = _amiValue("dispatcher-driver-vehicle-type");
  var vehiclePlate = _amiValue("dispatcher-driver-vehicle-plate");
  if (!name || !phone || !vehicleType || !vehiclePlate) {
    _amiDispatcherError("Create Driver failed", "Missing required driver fields.");
    window.alert("Enter driver name, phone, vehicle type, and vehicle plate.");
    return;
  }
  var result = await _amiRequestJson(
    "/api/health-isf/drivers",
    "POST",
    {
      name: name,
      phone: phone,
      vehicle_type: vehicleType,
      vehicle_plate: vehiclePlate
    }
  );
  if (!result || result.ok === false) {
    _amiDispatcherError("Create Driver failed", safeText(result && result.detail, "backend request failed"));
    window.alert("Unable to create driver.");
    return;
  }
  var createdDriverId = safeText((safeObject(result.response)).id, "");
  if (createdDriverId) {
    await _amiRequestJson(
      "/api/health-isf/drivers/" + encodeURIComponent(createdDriverId) + "/set-status",
      "POST",
      { status: "available" }
    );
  }
  await _amiRefreshDispatcherWorkspace();
  var createdDriverFound = (Array.isArray((safeObject(state.liveWorkflow)).drivers) ? state.liveWorkflow.drivers : []).some(function (item) {
    return safeText(item.id, "") === createdDriverId;
  });
  if (createdDriverId && createdDriverFound) {
    _amiDispatcherSuccess("Create Driver succeeded", "Driver saved and visible in Available Drivers.");
    _amiSetDispatcherProof("Create Driver", "ok", createdDriverId, true);
  } else {
    _amiDispatcherError("Create Driver partial", "Driver created but not visible as available after refresh.");
    _amiSetDispatcherProof("Create Driver", "partial", createdDriverId || "n/a", false);
  }
};

window._amiHandleDispatcherCreateProvider = async function() {
  if (!(await _amiEnsureDispatcherAuth("Sign in as admin or dispatcher before creating a provider."))) {
    return;
  }
  var name = _amiValue("dispatcher-provider-name");
  var address = _amiValue("dispatcher-provider-address");
  var phone = _amiValue("dispatcher-provider-phone");
  var serviceType = _amiValue("dispatcher-provider-service-type") || "health_system";
  if (!name || !address || !phone) {
    _amiDispatcherError("Create Provider failed", "Name, address, and phone are required.");
    window.alert("Enter provider name, address, and phone.");
    return;
  }
  var result = await _amiRequestJson(
    "/api/health-isf/providers",
    "POST",
    {
      name: name,
      address: address,
      phone: phone,
      service_type: serviceType
    }
  );
  if (!result || result.ok === false) {
    _amiDispatcherError("Create Provider failed", safeText(result && result.detail, "backend request failed"));
    window.alert("Unable to create provider.");
    return;
  }

  var createdProviderId = safeText((safeObject(result.response)).id, "");
  await _amiRefreshDispatcherWorkspace();
  var foundProvider = (Array.isArray((safeObject(state.liveWorkflow)).providers) ? state.liveWorkflow.providers : []).some(function (item) {
    return safeText(item.id, "") === createdProviderId;
  });
  if (createdProviderId && foundProvider) {
    _amiDispatcherSuccess("Create Provider succeeded", "provider_id=" + createdProviderId);
    _amiSetDispatcherProof("Create Provider", "ok", createdProviderId, true);
  } else {
    _amiDispatcherError("Create Provider partial", "Provider created but not visible in refreshed provider list.");
    _amiSetDispatcherProof("Create Provider", "partial", createdProviderId || "n/a", false);
  }
};

window._amiHandleDispatcherCreateRide = async function() {
  if (!(await _amiEnsureDispatchWriteRole("Sign in as admin or dispatcher before creating a ride."))) {
    return;
  }
  var passengerName = _amiValue("dispatcher-ride-passenger");
  var passengerPhone = _amiValue("dispatcher-ride-phone");
  var pickup = _amiValue("dispatcher-ride-pickup");
  var dropoff = _amiValue("dispatcher-ride-dropoff");
  var serviceType = _amiValue("dispatcher-ride-service");
  var providerId = _amiValue("dispatcher-ride-provider");
  if (!providerId) {
    var liveProviders = Array.isArray((safeObject(state.liveWorkflow)).providers) ? state.liveWorkflow.providers : [];
    if (liveProviders.length === 1) {
      providerId = safeText(liveProviders[0].id, "");
      _amiSetValue("dispatcher-ride-provider", providerId);
    }
  }
  if (!passengerName || !passengerPhone || !pickup || !dropoff || !serviceType || !providerId) {
    _amiDispatcherError("Create Ride failed", "Missing ride, passenger, or provider fields.");
    window.alert("Enter passenger, phone, pickup, dropoff, service type, and provider. If the provider list is empty, sign in and click Reload workspace, or create a provider first.");
    return;
  }
  var result = await _amiRequestJson(
    "/api/health-isf/rides",
    "POST",
    {
      passenger_name: passengerName,
      passenger_phone: passengerPhone,
      pickup_address: pickup,
      dropoff_address: dropoff,
      service_type: serviceType,
      provider_id: providerId,
      estimated_distance_miles: 5,
      priority_tag: "normal"
    }
  );
  if (!result || result.ok === false) {
    _amiDispatcherError("Create Ride failed", safeText(result && result.detail, "backend request failed"));
    window.alert("Unable to create ride.");
    return;
  }
  var createdRideId = safeText((safeObject(result.response)).id, "");
  await _amiRefreshDispatcherWorkspace();
  var foundRide = (Array.isArray((safeObject(state.liveWorkflow)).rides) ? state.liveWorkflow.rides : []).some(function (item) {
    return safeText(item.id, "") === createdRideId;
  });
  if (createdRideId && foundRide) {
    _amiDispatcherSuccess("Create Ride succeeded", "ride_id=" + createdRideId);
    _amiSetDispatcherProof("Create Ride", "ok", createdRideId, true);
  } else {
    _amiDispatcherError("Create Ride partial", "Ride created but not visible in refreshed Ride Operations list.");
    _amiSetDispatcherProof("Create Ride", "partial", createdRideId || "n/a", false);
  }
};

window._amiHandleDispatcherUsePatientRequest = function() {
  var requestId = _amiValue("dispatcher-ride-patient-request");
  if (!requestId) {
    _amiDispatcherError("Load Patient failed", "Select an existing patient request first.");
    return;
  }
  var request = _amiLiveCustomerRequests().find(function (item) {
    return safeText(item.id, "") === requestId;
  });
  if (!request) {
    _amiDispatcherError("Load Patient failed", "Selected patient request is not available in current backend data.");
    return;
  }
  _amiSetValue("dispatcher-ride-passenger", safeText(request.rider_name, ""));
  _amiSetValue("dispatcher-ride-phone", safeText(request.rider_phone, ""));
  _amiSetValue("dispatcher-ride-pickup", safeText(request.pickup_address, ""));
  _amiSetValue("dispatcher-ride-dropoff", safeText(request.dropoff_address, ""));
  _amiDispatcherSuccess("Loaded existing patient", "Ride form hydrated from backend patient request " + requestId + ".");
};

window._amiHandleDispatcherUseSelectedRide = function() {
  var rideId = _amiValue("dispatcher-edit-ride-select");
  if (!rideId) {
    _amiDispatcherError("Load Ride failed", "Select an existing ride first.");
    return;
  }
  var ride = _amiLiveRides().find(function (item) {
    return safeText(item.id, "") === rideId;
  });
  if (!ride) {
    _amiDispatcherError("Load Ride failed", "Selected ride is not available in current backend data.");
    return;
  }
  _amiSetValue("dispatcher-edit-ride-id", rideId);
  _amiSetValue("dispatcher-edit-ride-status", safeText(ride.status, "requested"));
  _amiSetValue("dispatcher-edit-ride-vehicle", safeText(ride.vehicle_id, ""));
  _amiDispatcherSuccess("Loaded existing ride", "Ride " + rideId + " loaded for status and vehicle updates.");
};

window._amiHandleDispatcherEditRideStatus = async function() {
  var rideId = _amiValue("dispatcher-edit-ride-id");
  var status = _amiValue("dispatcher-edit-ride-status");
  if (!rideId || !status) {
    _amiDispatcherError("Edit Ride failed", "Ride ID and status are required.");
    window.alert("Enter ride ID and status.");
    return;
  }
  var result = await _amiRequestJson(
    "/api/health-isf/rides/" + encodeURIComponent(rideId) + "/status",
    "PATCH",
    { status: status }
  );
  if (!result || result.ok === false) {
    _amiDispatcherError("Edit Ride failed", safeText(result && result.detail, "backend request failed"));
    window.alert("Unable to update ride status.");
    return;
  }
  _amiDispatcherSuccess("Edit Ride succeeded", "Ride status updated in backend.");
  await _amiRefreshDispatcherWorkspace();
};

window._amiHandleDispatcherAssignVehicle = async function() {
  var rideId = _amiValue("dispatcher-edit-ride-id");
  var vehicleId = _amiValue("dispatcher-edit-ride-vehicle");
  if (!rideId || !vehicleId) {
    _amiDispatcherError("Assign Vehicle failed", "Ride ID and vehicle are required.");
    window.alert("Enter ride ID and choose a vehicle.");
    return;
  }
  var result = await _amiRequestJson(
    "/api/health-isf/rides/" + encodeURIComponent(rideId) + "/assign-vehicle",
    "PATCH",
    { vehicle_id: vehicleId }
  );
  if (!result || result.ok === false) {
    _amiDispatcherError("Assign Vehicle failed", safeText(result && result.detail, "backend request failed"));
    window.alert("Unable to assign vehicle.");
    return;
  }
  _amiDispatcherSuccess("Assign Vehicle succeeded", "Vehicle assigned to ride in backend.");
  await _amiRefreshDispatcherWorkspace();
};

window._amiHandleDispatchAssignFromSelect = async function(tripId) {
  var selected = _amiValue("dispatch-driver-" + String(tripId));
  if (!selected) {
    _amiDispatcherError("Assign Driver failed", "Select a driver before assigning.");
    window.alert("Select a driver before assigning.");
    return;
  }
  var result = await _amiRequestJson(
    "/api/health-isf/rides/" + encodeURIComponent(tripId) + "/assign-driver",
    "PATCH",
    { driver_id: selected }
  );
  if (!result || result.ok === false) {
    _amiDispatcherError("Assign Driver failed", safeText(result && result.detail, "workspace action failed"));
    window.alert("Unable to assign driver for " + tripId + ".");
    return;
  }
  await _amiRefreshDispatcherWorkspace();
  var assigned = (Array.isArray((safeObject(state.liveWorkflow)).rides) ? state.liveWorkflow.rides : []).find(function (item) {
    return safeText(item.id, "") === safeText(tripId, "");
  });
  if (assigned && safeText(assigned.driver_id, "") === selected) {
    _amiDispatcherSuccess("Assign Driver succeeded", "Ride " + tripId + " updated with assigned driver.");
    _amiSetDispatcherProof("Assign Driver", "ok", tripId, true);
  } else {
    _amiDispatcherError("Assign Driver partial", "Assignment request sent but refreshed ride does not show selected driver.");
    _amiSetDispatcherProof("Assign Driver", "partial", tripId, false);
  }
};

window._amiHandleDispatchReassignFromSelect = async function(tripId) {
  var selected = _amiValue("dispatch-driver-" + String(tripId));
  if (!selected) {
    _amiDispatcherError("Reassign Driver failed", "Select a driver before reassigning.");
    window.alert("Select a driver before reassigning.");
    return;
  }
  var result = await _amiSubmitWorkspaceAction(
    "dispatch.reassign_driver",
    { trip_id: tripId, driver_id: selected },
    "dispatcher"
  );
  if (!result || result.ok === false) {
    _amiDispatcherError("Reassign Driver failed", safeText(result && result.detail, "workspace action failed"));
    window.alert("Unable to reassign driver for " + tripId + ".");
    return;
  }
  await _amiRefreshDispatcherWorkspace();
  var reassigned = (Array.isArray((safeObject(state.liveWorkflow)).rides) ? state.liveWorkflow.rides : []).find(function (item) {
    return safeText(item.id, "") === safeText(tripId, "");
  });
  if (reassigned && safeText(reassigned.driver_id, "") === selected) {
    _amiDispatcherSuccess("Reassign Driver succeeded", "Ride " + tripId + " updated with reassigned driver.");
  } else {
    _amiDispatcherError("Reassign Driver partial", "Reassignment request sent but refreshed ride does not show selected driver.");
  }
};

window._amiHandleDispatchRide = async function(tripId) {
  var result = await _amiSubmitWorkspaceAction(
    "driver.start_route",
    { trip_id: tripId },
    "dispatcher"
  );
  if (!result || result.ok === false) {
    _amiDispatcherError("Dispatch Ride failed", safeText(result && result.detail, "workspace action failed"));
    window.alert("Unable to dispatch ride " + tripId + ".");
    return;
  }
  _amiDispatcherSuccess("Dispatch Ride succeeded", "Trip " + tripId + " moved to en-route.");
  await _amiRefreshDispatcherWorkspace();
};

window._amiHandleDispatchStartTrip = async function(tripId) {
  var result = await _amiSubmitWorkspaceAction(
    "driver.update_route_progress",
    { trip_id: tripId, route_progress_percent: 90 },
    "dispatcher"
  );
  if (!result || result.ok === false) {
    _amiDispatcherError("Start Trip failed", safeText(result && result.detail, "workspace action failed"));
    window.alert("Unable to start trip " + tripId + ".");
    return;
  }
  _amiDispatcherSuccess("Start Trip succeeded", "Trip " + tripId + " moved in progress.");
  await _amiRefreshDispatcherWorkspace();
};

window._amiHandleDispatchMarkOnboard = async function(tripId) {
  var result = await _amiSubmitWorkspaceAction(
    "dispatch.mark_onboard",
    { trip_id: tripId },
    "dispatcher"
  );
  if (!result || result.ok === false) {
    _amiDispatcherError("Passenger Onboard failed", safeText(result && result.detail, "workspace action failed"));
    window.alert("Unable to mark passenger onboard for " + tripId + ".");
    return;
  }
  _amiDispatcherSuccess("Passenger Onboard succeeded", "Trip " + tripId + " marked onboard.");
  await _amiRefreshDispatcherWorkspace();
};

function _amiDebugLoggingEnabled() {
  try {
    return localStorage.getItem("amicor_debug_logs") === "true";
  } catch (_) {
    return false;
  }
}

function _amiDebugLog() {
  if (!_amiDebugLoggingEnabled()) return;
  if (typeof console !== "undefined" && console && typeof console.log === "function") {
    console.log.apply(console, arguments);
  }
}

window._amiHandleComplianceReview = async function(docId, status) {
  var msg = status === "critical"
    ? "CRITICAL: Mark " + docId + " as under review and notify supervisor?"
    : "Open review workflow for document " + docId + "?";
  if (!window.confirm(msg)) return;
  var reviewResult = await _amiSubmitWorkspaceAction(
    "compliance.review_deficiency",
    { document_id: docId, status: status },
    "compliance_officer"
  );
  if (!reviewResult || reviewResult.ok === false) {
    window.alert("Unable to submit compliance review action.");
    return;
  }
  var rows = document.querySelectorAll("#page-content table tr");
  rows.forEach(function(row) {
    if (row.textContent.indexOf(docId) !== -1) {
      var btn = row.querySelector("button");
      if (btn) { btn.textContent = "Under Review"; btn.disabled = true; btn.style.opacity = "0.5"; }
    }
  });
  _amiDebugLog("[Compliance] Review initiated for", docId, "status:", status);
};

window._amiHandleComplianceOnboardingDecision = async function(driverId, approved) {
  var actionType = approved ? "compliance.approve_onboarding" : "compliance.deny_onboarding";
  var result = await _amiSubmitWorkspaceAction(
    actionType,
    { driver_id: driverId, reason: approved ? "compliance_approved_in_workspace" : "compliance_denied_in_workspace" },
    "compliance_officer"
  );
  if (!result || result.ok === false) {
    window.alert("Unable to submit onboarding decision for " + driverId + ".");
    return;
  }
};

window._amiHandleComplianceExpirationScan = async function() {
  var result = await _amiSubmitWorkspaceAction(
    "compliance.flag_document_expiration",
    {},
    "compliance_officer"
  );
  if (!result || result.ok === false) {
    window.alert("Unable to refresh expiration alerts.");
    return;
  }
  window.alert("Expiration alerts refreshed.");
};

window._amiHandleSupervisorApproval = async function(approvalId, approved) {
  var action = approved ? "APPROVE" : "REJECT";
  if (!window.confirm(action + " request " + approvalId + "?")) return;
  var actionType = approved ? "supervisor.approve_override" : "supervisor.reject_override";
  var decisionResult = await _amiSubmitWorkspaceAction(
    actionType,
    { approval_id: approvalId, decision: approved ? "approved" : "rejected" },
    "supervisor"
  );
  if (!decisionResult || decisionResult.ok === false) {
    window.alert("Unable to submit supervisor decision.");
    return;
  }
  var tbody = document.getElementById("supervisor-approval-tbody");
  if (tbody) {
    var rows = tbody.querySelectorAll("tr");
    rows.forEach(function(row) {
      if (row.textContent.indexOf(approvalId) !== -1) {
        row.style.transition = "opacity 0.3s";
        row.style.opacity = "0";
        setTimeout(function() { if (row.parentNode) row.parentNode.removeChild(row); }, 320);
      }
    });
  }
  _amiDebugLog("[Supervisor]", action, "for", approvalId);
};

window._amiHandleSupervisorRecovery = async function(tripId) {
  var result = await _amiSubmitWorkspaceAction(
    "supervisor.approve_recovery",
    { trip_id: tripId },
    "supervisor"
  );
  if (!result || result.ok === false) {
    window.alert("Unable to approve recovery for " + tripId + ".");
    return;
  }
};

window._amiHandleSupervisorEmergency = async function(tripId) {
  var result = await _amiSubmitWorkspaceAction(
    "supervisor.trigger_emergency_coordination",
    { trip_id: tripId },
    "supervisor"
  );
  if (!result || result.ok === false) {
    window.alert("Unable to trigger emergency coordination for " + tripId + ".");
    return;
  }
};

window._amiHandleDriverSupport = async function(driverId) {
  var result = await _amiSubmitWorkspaceAction(
    "driver_support.route_escalation",
    { driver_id: driverId },
    "driver_support"
  );
  if (!result || result.ok === false) {
    window.alert("Unable to route driver support escalation for " + driverId + ".");
    return;
  }
  window.alert("Driver support escalation submitted for " + driverId + ".");
  _amiDebugLog("[DriverSupport] View driver", driverId);
};

window._amiHandleTicket = async function(ticketId) {
  var result = await _amiSubmitWorkspaceAction(
    "driver_support.open_ticket",
    { ticket_id: ticketId },
    "driver_support"
  );
  if (!result || result.ok === false) {
    window.alert("Unable to open support ticket " + ticketId + ".");
    return;
  }
  window.alert("Support workflow opened for ticket " + ticketId + ".");
  _amiDebugLog("[DriverSupport] Open ticket", ticketId);
};

window._amiHandleProviderSync = async function(taskId) {
  var result = await _amiSubmitWorkspaceAction(
    "provider.open_sync_handoff",
    { task_id: taskId },
    "provider"
  );
  if (!result || result.ok === false) {
    window.alert("Unable to open provider sync handoff.");
    return;
  }
  window.alert("Provider sync handoff submitted.");
};

window._amiHandleNEMTAssign = async function(tripId) {
  var driverName = window.prompt("Assign driver to " + tripId + ".\nEnter driver name or ID:");
  if (!driverName || !driverName.trim()) return;
  var assignResult = await _amiSubmitWorkspaceAction(
    "dispatch.assign_driver",
    { trip_id: tripId, driver_id: driverName.trim() },
    "dispatcher"
  );
  if (!assignResult || assignResult.ok === false) {
    window.alert("Unable to submit assignment request for " + tripId + ".");
    return;
  }
  var tbody = document.getElementById("nemt-schedule-tbody");
  if (tbody) {
    var rows = tbody.querySelectorAll("tr");
    rows.forEach(function(row) {
      if (row.textContent.indexOf(tripId) !== -1) {
        var cells = row.querySelectorAll("td");
        if (cells[4]) cells[4].textContent = driverName.trim();
        var btn = row.querySelector("button");
        if (btn) { btn.textContent = "Track"; btn.className = "btn-action"; btn.setAttribute("onclick", "window._amiHandleNEMTView('" + tripId + "')"); }
        var statusCell = cells[5];
        if (statusCell) statusCell.innerHTML = '<span class="badge badge-soft">assigned</span>';
      }
    });
  }
  _amiDebugLog("[NEMT] Assigned", driverName, "to", tripId);
};

window._amiHandleNEMTView = async function(tripId) {
  var viewResult = await _amiSubmitWorkspaceAction(
    "medical_coordinator.review_appointment_risk",
    { trip_id: tripId, intent: "track_transport" },
    "medical_coordinator"
  );
  if (!viewResult || viewResult.ok === false) {
    window.alert("Unable to load transport tracking context for " + tripId + ".");
    return;
  }
  window.alert("Tracking transport " + tripId + " in supervised medical coordination mode.");
  _amiDebugLog("[NEMT] Track trip", tripId);
};

window._amiHandlePatientEscalation = async function(escalationId) {
  var escalateResult = await _amiSubmitWorkspaceAction(
    "medical_coordinator.escalate_patient_support",
    { escalation_id: escalationId },
    "medical_coordinator"
  );
  if (!escalateResult || escalateResult.ok === false) {
    window.alert("Unable to submit patient escalation " + escalationId + ".");
    return;
  }
  window.alert("Patient escalation submitted for supervised review.");
};

window._amiHandleMedicalFacilityCoordination = async function(taskId) {
  var coordinateResult = await _amiSubmitWorkspaceAction(
    "medical_coordinator.coordinate_facility",
    { task_id: taskId },
    "medical_coordinator"
  );
  if (!coordinateResult || coordinateResult.ok === false) {
    window.alert("Unable to submit facility coordination action.");
    return;
  }
  window.alert("Facility coordination action submitted for supervised workflow.");
};

async function _amiAcceptScheduledRideWithRecovery(driverId, rideId) {
  var acceptUrl = "/api/health-isf/drivers/" + encodeURIComponent(driverId) + "/accept-scheduled-ride";
  var scheduleUrl = "/api/health-isf/drivers/" + encodeURIComponent(driverId) + "/upcoming-schedule";
  var acceptTimeoutMs = 60000;
  var maxAttempts = 3;
  var lastErr = null;
  for (var attempt = 0; attempt < maxAttempts; attempt++) {
    try {
      return await _amiSendJson(acceptUrl, "POST", { ride_id: rideId }, acceptTimeoutMs);
    } catch (err) {
      lastErr = err;
      var msg = safeText(err && err.message, "");
      var transient = msg.indexOf("request_timeout") >= 0 || msg.indexOf("Failed to fetch") >= 0 || msg.indexOf("NetworkError") >= 0;
      if (transient) {
        try {
          var schedulePayload = safeObject(await _amiSendJson(scheduleUrl, "GET", null));
          var entries = Array.isArray(schedulePayload.upcoming_schedule) ? schedulePayload.upcoming_schedule : [];
          var alreadyAccepted = entries.some(function (entry) {
            var entryRideId = safeText(entry.ride_id || entry.id, "");
            var assignmentState = safeText(entry.assignment_state || entry.status || entry.lifecycle_state, "").toLowerCase();
            return entryRideId === rideId && (
              assignmentState === "scheduled_accepted"
              || assignmentState.indexOf("accepted") >= 0
              || entry.can_accept === false
            );
          });
          if (alreadyAccepted) {
            return { ride_id: rideId, assignment_state: "scheduled_accepted", recovered_after_timeout: true };
          }
        } catch (_) {}
      }
      if (transient && attempt < maxAttempts - 1) {
        await new Promise(function (resolve) {
          setTimeout(resolve, 500 * Math.pow(2, attempt));
        });
        continue;
      }
      throw err;
    }
  }
  throw lastErr || new Error("accept_scheduled_ride_failed");
}

async function _amiSendJson(url, method, payload, timeoutMs) {
  var httpMethod = safeText(method, "POST").toUpperCase();
  if (httpMethod === "GET") {
    if (window.AmiOpsShellActions && typeof window.AmiOpsShellActions.requestJson === "function") {
      var getResult = await window.AmiOpsShellActions.requestJson(url, "GET", null);
      if (!getResult || getResult.ok === false) {
        throw new Error(safeText(getResult && getResult.detail, "request_failed"));
      }
      return safeObject(getResult.response);
    }
    throw new Error("request_json_unavailable");
  }
  if (!window.AmiOpsShellActions || typeof window.AmiOpsShellActions.sendJson !== "function") {
    throw new Error("send_json_unavailable");
  }
  return window.AmiOpsShellActions.sendJson(url, method, payload, timeoutMs);
}

function _amiRouteProgressCompletionSucceeded(progressPayload, tripId) {
  var workspace = safeObject(progressPayload);
  var normalizedTripId = safeText(tripId, "");
  var activeRide = safeObject(workspace.active_ride);
  var activeRideId = safeText(activeRide.id || activeRide.ride_id, "");
  var activeLifecycle = safeText(activeRide.lifecycle_state || activeRide.status, "").toLowerCase();
  return activeRideId === normalizedTripId && activeLifecycle === "completed";
}

function _amiResolveCompletionRidePayload(progressPayload, tripId) {
  var workspace = safeObject(progressPayload);
  var normalizedTripId = safeText(tripId, "");
  var activeRide = safeObject(workspace.active_ride);
  var activeRideId = safeText(activeRide.id || activeRide.ride_id, "");
  var activeLifecycle = safeText(activeRide.lifecycle_state || activeRide.status, "").toLowerCase();
  if (activeRideId === normalizedTripId && activeLifecycle === "completed") {
    return activeRide;
  }
  return null;
}

async function _amiFetchRideLifecycleState(tripId, driverId) {
  var normalizedTripId = safeText(tripId, "");
  var resolvedDriverId = safeText(driverId, "") || _amiCanonicalMobileDriverId();
  if (resolvedDriverId && normalizedTripId) {
    try {
      var snapshot = safeObject(await _amiSendJson(
        "/api/health-isf/drivers/" + encodeURIComponent(resolvedDriverId) + "/completion-snapshot?limit=50",
        "GET",
        null
      ));
      var completedRows = Array.isArray(snapshot.completed_rides) ? snapshot.completed_rides : [];
      if (completedRows.some(function (row) {
        return safeText(row.id || row.ride_id, "") === normalizedTripId;
      })) {
        return "completed";
      }
    } catch (_) {}
    try {
      var activePayload = safeObject(await _amiSendJson(
        "/api/health-isf/drivers/" + encodeURIComponent(resolvedDriverId) + "/active-ride",
        "GET",
        null
      ));
      var activeRide = safeObject(activePayload.ride);
      if (safeText(activeRide.id || activeRide.ride_id, "") === normalizedTripId) {
        return safeText(activeRide.lifecycle_state || activeRide.status, "").toLowerCase();
      }
      if (activePayload.has_active_ride !== true) {
        var completedRides = await _amiSendJson(
          "/api/health-isf/drivers/" + encodeURIComponent(resolvedDriverId) + "/completed-rides?limit=20",
          "GET",
          null
        );
        if (Array.isArray(completedRides) && completedRides.some(function (row) {
          return safeText(row.id || row.ride_id, "") === normalizedTripId;
        })) {
          return "completed";
        }
      }
    } catch (_) {}
  }
  try {
    var ride = safeObject(await _amiSendJson("/api/health-isf/rides/" + encodeURIComponent(normalizedTripId), "GET", null));
    return safeText(ride.lifecycle_state || ride.status, "").toLowerCase();
  } catch (_) {
    return "";
  }
}

async function _amiResolveDriverForTrip(driverId, tripId) {
  var resolvedDriverId = safeText(driverId, "");
  var sessionDriverId = "";
  if (window.AmiOpsShellActions && typeof window.AmiOpsShellActions.getMobileSessionDriverId === "function") {
    sessionDriverId = safeText(window.AmiOpsShellActions.getMobileSessionDriverId(), "");
    if (sessionDriverId) {
      resolvedDriverId = sessionDriverId;
    }
  }
  try {
    var ride = safeObject(await _amiSendJson("/api/health-isf/rides/" + encodeURIComponent(tripId), "GET", null));
    if (!sessionDriverId) {
      var assignedDriverId = safeText(ride.driver_id, "");
      if (assignedDriverId) {
        resolvedDriverId = assignedDriverId;
      }
    }
    return { driverId: resolvedDriverId, ride: ride };
  } catch (_) {
    return { driverId: resolvedDriverId, ride: null };
  }
}

async function _amiAdvanceRideForCompletion(driverId, tripId) {
  var resolved = await _amiResolveDriverForTrip(driverId, tripId);
  driverId = safeText(resolved.driverId, driverId);
  var ride = safeObject(resolved.ride);
  var lifecycle = safeText(ride.lifecycle_state || ride.status, "").toLowerCase();
  var lifecycleOrder = {
    queued: 0,
    requested: 0,
    pending: 0,
    assigned: 0,
    accepted: 0,
    driver_en_route: 0,
    en_route_pickup: 0,
    arrived: 1,
    arrived_pickup: 1,
    rider_onboard: 2,
    rider_loaded: 2,
    in_progress: 3,
    in_transit: 3,
    trip_in_progress: 3,
    arrived_destination: 4,
    completed: 5
  };
  var progression = [
    "en_route_pickup",
    "arrived_pickup",
    "rider_loaded",
    "trip_in_progress",
    "arrived_destination"
  ];
  var startIndex = lifecycleOrder[lifecycle];
  if (startIndex === undefined) {
    startIndex = 0;
  }
  if (startIndex >= progression.length) {
    return { driverId: driverId, ride: ride };
  }
  for (var i = startIndex; i < progression.length; i += 1) {
    try {
      var progressPayload = await _amiSendJson(
        "/api/health-isf/drivers/" + encodeURIComponent(driverId) + "/route-progress",
        "POST",
        { ride_id: tripId, target_state: progression[i] }
      );
      ride = safeObject(progressPayload.active_ride || progressPayload.ride || ride);
    } catch (_) {}
  }
  return { driverId: driverId, ride: ride };
}

async function _amiRefreshDriverWorkflow(lastAction) {
  if (!window.AmiOpsShellActions || typeof window.AmiOpsShellActions.refreshDriverWorkflowData !== "function") {
    return;
  }
  await window.AmiOpsShellActions.refreshDriverWorkflowData({ lastAction: safeText(lastAction, "Driver workspace synchronized") });
}

function _amiScheduleRenderPage() {
  if (window.AmiOpsShellActions && typeof window.AmiOpsShellActions.scheduleRenderPage === "function") {
    window.AmiOpsShellActions.scheduleRenderPage();
    return;
  }
  if (typeof window.AmiOpsShellRender === "function") {
    window.AmiOpsShellRender();
  }
}

function _amiLockDriverHydration(ms) {
  if (window.AmiOpsShellActions && typeof window.AmiOpsShellActions.lockDriverHydration === "function") {
    window.AmiOpsShellActions.lockDriverHydration(ms);
  }
}

function _amiDriverTripStatus(tripId) {
  var appState = safeObject(state.driverApp);
  var queue = Array.isArray(appState.tripQueue) ? appState.tripQueue : [];
  var match = queue.find(function (trip) {
    return safeText(trip.tripId, "") === safeText(tripId, "");
  });
  return safeText(match && match.status, "").toLowerCase();
}

function _amiDriverTripPhone(tripId) {
  var appState = safeObject(state.driverApp);
  var queue = Array.isArray(appState.tripQueue) ? appState.tripQueue : [];
  var match = queue.find(function (trip) {
    return safeText(trip.tripId, "") === safeText(tripId, "");
  });
  return safeText(match && match.riderPhone, "");
}

async function _amiAfterDriverWorkflowRefresh(lastAction) {
  try {
    var shell = _amiDriverShellState();
    var onMobileRoute = safeText(shell.route, "") === "mobile";
    if (
      onMobileRoute
      && window.AmiOpsShellActions
      && typeof window.AmiOpsShellActions.refreshDriverWorkflowData === "function"
    ) {
      await window.AmiOpsShellActions.refreshDriverWorkflowData({
        lastAction: safeText(lastAction, "Driver workspace synchronized")
      });
    } else if (window.AmiOpsShellActions && typeof window.AmiOpsShellActions.refreshData === "function") {
      await window.AmiOpsShellActions.refreshData();
    } else {
      await _amiRefreshDriverWorkflow(lastAction);
    }
  } catch (_) {}
  _amiScheduleRenderPage();
}

function _amiLogDriverMobileSync(entry) {
  if (window.AmiOpsShellActions && typeof window.AmiOpsShellActions.logDriverMobileAssignmentSync === "function") {
    window.AmiOpsShellActions.logDriverMobileAssignmentSync(entry || {});
  }
}

function _amiDriverAcceptHttpStatus(err, code) {
  var text = safeText(err && err.message, "").toLowerCase();
  if (text.indexOf(":http_" + String(code)) >= 0) {
    return true;
  }
  if (code === 401) {
    return text.indexOf("authentication required") >= 0
      || text.indexOf("unauthorized") >= 0
      || text.indexOf("session expired") >= 0;
  }
  if (code === 409) {
    return text.indexOf("already accepted") >= 0
      || text.indexOf("conflict") >= 0
      || text.indexOf("cannot accept") >= 0
      || text.indexOf("lifecycle") >= 0;
  }
  return false;
}

function _amiDriverMobileSessionStillActive() {
  try {
    if (window.AmiOpsShellActions && typeof window.AmiOpsShellActions.getCanonicalMobileDriverContext === "function") {
      return !!window.AmiOpsShellActions.getCanonicalMobileDriverContext().authenticated;
    }
  } catch (_) {}
  return false;
}

async function _amiRecoverAcceptedDriverTrip(driverId, tripId) {
  if (!driverId || !tripId) {
    return null;
  }
  try {
    var workspace = safeObject(await _amiSendJson(
      "/api/health-isf/drivers/" + encodeURIComponent(driverId) + "/active-ride",
      "GET",
      null
    ));
    var ride = safeObject(workspace.ride || workspace.active_ride);
    var rideId = safeText(ride.id || ride.ride_id || workspace.ride_id, "");
    if (rideId !== safeText(tripId, "")) {
      return null;
    }
    var assignmentState = safeText(workspace.assignment_state, "").toLowerCase();
    var lifecycle = safeText(ride.lifecycle_state || ride.status, "").toLowerCase();
    var acceptedStates = ["accepted", "en_route_pickup", "driver_en_route", "arrived", "arrived_pickup", "pickup_complete", "rider_loaded", "in_progress", "trip_in_progress"];
    if (ride.accepted_at || acceptedStates.indexOf(assignmentState) >= 0 || acceptedStates.indexOf(lifecycle) >= 0) {
      return {
        active_ride: ride,
        assignment_state: assignmentState || lifecycle || "accepted",
        recovered: true
      };
    }
  } catch (_) {}
  return null;
}

async function _amiFinalizeDriverAcceptTrip(tripId, payload, driverId, alreadyAccepted) {
  var shell = _amiDriverShellState();
  var activeRide = safeObject(payload.active_ride || payload);
  var displayStatus = _amiStatusFromRouteProgressPayload(payload, "accepted");
  shell = _amiPatchDriverTripStatus(tripId, displayStatus);
  shell.driverApp.lastActionResult = {
    last_action: "Accept Trip",
    api_status: "ok",
    db_record_id: safeText(activeRide.id, tripId),
    updated_table: "health_isf_rides",
    ui_refreshed: "yes",
    current_ride_status: displayStatus
  };
  window.AmiOpsShellState = shell;
  _amiScheduleRenderPage();
  _amiLogDriverMobileSync({
    event: "accept_ride",
    requested_ride_id: tripId,
    assignment_state: safeText(activeRide.lifecycle_state || activeRide.status, "accepted"),
    api_response: activeRide,
    http_status: 200,
    route: "/api/health-isf/drivers/" + driverId + "/accept-ride",
    frontend_state_transition: "active_ride->active_ride",
    extra: { action: "Accept Trip", already_accepted: !!alreadyAccepted }
  });
  try {
    _amiLockDriverHydration(3500);
    await _amiAfterDriverWorkflowRefresh("Accepted trip " + tripId);
  } catch (_) {}
  return true;
}

window._amiHandleDriverAcceptTrip = async function(tripId) {
  var shell = _amiDriverShellState();
  var driverId = _amiCanonicalMobileDriverId(shell);
  if (!driverId || !tripId) return false;
  var payload = null;
  var acceptErr = null;
  try {
    payload = await _amiSendJson(
      "/api/health-isf/drivers/" + encodeURIComponent(driverId) + "/accept-ride",
      "POST",
      { ride_id: tripId }
    );
  } catch (err) {
    acceptErr = err;
    if (_amiDriverAcceptHttpStatus(err, 401) && typeof window._amiClearDriverSession === "function" && !_amiDriverMobileSessionStillActive()) {
      window._amiClearDriverSession();
    }
    if (_amiDriverAcceptHttpStatus(acceptErr, 409)) {
      _amiLogDriverMobileSync({
        event: "accept_ride_denied_reserved",
        requested_ride_id: tripId,
        route: "/api/health-isf/drivers/" + driverId + "/accept-ride",
        api_response: {
          error: safeText(acceptErr && acceptErr.message, "reserved_for_other_driver")
        },
        frontend_state_transition: "active_ride->active_ride",
        extra: { action: "Accept Trip", denied: true }
      });
      window.alert("This ride is reserved for another driver.");
      return false;
    }
    var recovered = await _amiRecoverAcceptedDriverTrip(driverId, tripId);
    if (recovered) {
      return await _amiFinalizeDriverAcceptTrip(tripId, recovered, driverId, true);
    }
    _amiLogDriverMobileSync({
      event: "accept_ride_failed",
      requested_ride_id: tripId,
      route: "/api/health-isf/drivers/" + driverId + "/accept-ride",
      api_response: {
        error: safeText(acceptErr && acceptErr.message, "accept_failed")
      },
      frontend_state_transition: "active_ride->active_ride",
      extra: { action: "Accept Trip" }
    });
    if (_amiDriverAcceptHttpStatus(acceptErr, 401)) {
      window.alert("Driver session expired. Sign in again, then tap Accept Trip.");
    } else {
      window.alert(
        "Unable to submit driver accept action for " + tripId + ". "
        + safeText(acceptErr && acceptErr.message, "")
      );
    }
    shell = _amiDriverShellState();
    shell.driverApp = safeObject(shell.driverApp);
    shell.driverApp.lastActionResult = {
      last_action: "Accept Trip",
      api_status: "error",
      db_record_id: safeText(tripId, "n/a"),
      updated_table: "health_isf_rides",
      ui_refreshed: "no",
      current_ride_status: "unchanged"
    };
    window.AmiOpsShellState = shell;
    return false;
  }
  if (!payload) {
    var recoveredEmpty = await _amiRecoverAcceptedDriverTrip(driverId, tripId);
    if (recoveredEmpty) {
      return await _amiFinalizeDriverAcceptTrip(tripId, recoveredEmpty, driverId, true);
    }
    window.alert("Unable to submit driver accept action for " + tripId + ".");
    return false;
  }
  return await _amiFinalizeDriverAcceptTrip(tripId, payload, driverId, false);
};

window._amiHandleDriverArriveTrip = async function(tripId) {
  var shell = _amiDriverShellState();
  var driverId = _amiCanonicalMobileDriverId(shell);
  if (!driverId || !tripId) return false;

  function routeProgressHttpStatus(err, code) {
    var text = safeText(err && err.message, "");
    return text.indexOf(":http_" + String(code)) >= 0;
  }

  function arriveFailureMessage(err) {
    return safeText(err && err.message, "arrived_pickup_failed");
  }

  function clearStaleDriverTrip(staleTripId) {
    shell = _amiDriverShellState();
    shell.driverApp = safeObject(shell.driverApp);
    if (safeText(shell.driverApp.activeTripId, "") === safeText(staleTripId, "")) {
      shell.driverApp.activeTripId = "";
      shell.driverApp.activeStage = "queued";
    }
    shell.driverApp.tripQueue = (Array.isArray(shell.driverApp.tripQueue) ? shell.driverApp.tripQueue : []).filter(function (trip) {
      return safeText(trip.tripId, "") !== safeText(staleTripId, "");
    });
    window.AmiOpsShellState = shell;
    if (window.AmiOpsShellActions && typeof window.AmiOpsShellActions.resetDriverMobileAfterCompletion === "function") {
      window.AmiOpsShellActions.resetDriverMobileAfterCompletion();
    }
  }

  function applyArriveSuccess(payload, recovered) {
    var nextStatus = _amiStatusFromRouteProgressPayload(payload, "arrived_pickup");
    var activeRide = safeObject(payload.active_ride || payload);
    shell = _amiPatchDriverTripStatus(tripId, nextStatus);
    shell.driverApp.lastActionResult = {
      last_action: "Arrived at Pickup",
      api_status: "ok",
      db_record_id: safeText(activeRide.id, tripId),
      updated_table: "health_isf_rides",
      ui_refreshed: "yes",
      current_ride_status: nextStatus
    };
    window.AmiOpsShellState = shell;
    _amiScheduleRenderPage();
    _amiLogDriverMobileSync({
      event: recovered ? "arrive_trip_recovered" : "route_progress",
      requested_ride_id: tripId,
      assignment_state: nextStatus,
      api_response: activeRide,
      http_status: 200,
      route: "/api/health-isf/drivers/" + driverId + "/route-progress",
      frontend_state_transition: "active_ride->active_ride",
      extra: { action: "Arrived at Pickup", target_state: "arrived_pickup", recovered: !!recovered }
    });
  }

  async function postRouteProgress(targetState) {
    return await _amiSendJson(
      "/api/health-isf/drivers/" + encodeURIComponent(driverId) + "/route-progress",
      "POST",
      { ride_id: tripId, target_state: targetState },
      45000
    );
  }

  var queue = Array.isArray(shell.driverApp.tripQueue) ? shell.driverApp.tripQueue : [];
  var tripRow = queue.find(function (trip) {
    return safeText(trip.tripId, "") === safeText(tripId, "");
  });

  var payload = null;
  var arriveErr = null;
  try {
    payload = await postRouteProgress("arrived_pickup");
  } catch (err) {
    arriveErr = err;
    if (routeProgressHttpStatus(err, 400) || routeProgressHttpStatus(err, 409)) {
      try {
        payload = await postRouteProgress("arrived_pickup");
        arriveErr = null;
      } catch (retryErr) {
        arriveErr = retryErr;
      }
    }
  }

  if (!payload) {
    var lifecycle = await _amiFetchRideLifecycleState(tripId);
    var arrivedStates = ["arrived", "arrived_pickup", "waiting_at_pickup", "at_pickup"];
    if (arrivedStates.indexOf(lifecycle) >= 0) {
      try {
        payload = { active_ride: await _amiSendJson("/api/health-isf/rides/" + encodeURIComponent(tripId), "GET", null) };
      } catch (_) {
        payload = { active_ride: { id: tripId, lifecycle_state: lifecycle, status: lifecycle } };
      }
    } else if (["completed", "cancelled", "failed", "declined", "no_show"].indexOf(lifecycle) >= 0) {
      clearStaleDriverTrip(tripId);
      _amiLogDriverMobileSync({
        event: "arrive_trip_stale_cleared",
        requested_ride_id: tripId,
        route: "/api/health-isf/drivers/" + driverId + "/route-progress",
        api_response: { lifecycle_state: lifecycle, error: arriveFailureMessage(arriveErr) },
        extra: { action: "Arrived at Pickup", target_state: "arrived_pickup" }
      });
      await _amiAfterDriverWorkflowRefresh("Cleared stale ride " + tripId);
      window.alert(
        "This ride is already " + lifecycle + ". Your active trip list was refreshed so you can continue with the current assignment."
      );
      return false;
    } else {
      try {
        var rideLookup = safeObject(await _amiSendJson("/api/health-isf/rides/" + encodeURIComponent(tripId), "GET", null));
        var assignedDriverId = safeText(rideLookup.driver_id, "");
        if (assignedDriverId && assignedDriverId !== safeText(driverId, "")) {
          clearStaleDriverTrip(tripId);
          _amiLogDriverMobileSync({
            event: "arrive_trip_stale_cleared",
            requested_ride_id: tripId,
            route: "/api/health-isf/drivers/" + driverId + "/route-progress",
            api_response: {
              lifecycle_state: lifecycle,
              assigned_driver_id: assignedDriverId,
              error: arriveFailureMessage(arriveErr)
            },
            extra: { action: "Arrived at Pickup", target_state: "arrived_pickup", reason: "driver_mismatch" }
          });
          await _amiAfterDriverWorkflowRefresh("Cleared reassigned ride " + tripId);
          window.alert("This ride is no longer assigned to you. Your trip list was refreshed.");
          return false;
        }
      } catch (_) {}
    }
  }

  if (!payload) {
    _amiLogDriverMobileSync({
      event: "route_progress_failed",
      requested_ride_id: tripId,
      route: "/api/health-isf/drivers/" + driverId + "/route-progress",
      api_response: { error: arriveFailureMessage(arriveErr) },
      extra: { action: "Arrived at Pickup", target_state: "arrived_pickup" }
    });
    window.alert("Unable to submit driver arrive action for " + tripId + ". " + arriveFailureMessage(arriveErr));
    shell = _amiDriverShellState();
    shell.driverApp = safeObject(shell.driverApp);
    shell.driverApp.lastActionResult = {
      last_action: "Arrived at Pickup",
      api_status: "error",
      db_record_id: safeText(tripId, "n/a"),
      updated_table: "health_isf_rides",
      ui_refreshed: "no",
      current_ride_status: "unchanged"
    };
    window.AmiOpsShellState = shell;
    return false;
  }

  applyArriveSuccess(payload, !!arriveErr);
  try {
    _amiLockDriverHydration(3500);
    await _amiAfterDriverWorkflowRefresh("Arrived at pickup for " + tripId);
  } catch (_) {}
  return true;
};

window._amiHandleDriverStartRoute = async function(tripId) {
  var shell = _amiDriverShellState();
  var driverId = _amiCanonicalMobileDriverId(shell);
  if (!driverId || !tripId) return false;
  try {
    var payload = await _amiSendJson(
      "/api/health-isf/drivers/" + encodeURIComponent(driverId) + "/route-progress",
      "POST",
      { ride_id: tripId, target_state: "en_route_pickup" }
    );
    var nextStatus = _amiStatusFromRouteProgressPayload(payload, "driver_en_route");
    var activeRide = safeObject(payload.active_ride || payload);
    shell = _amiPatchDriverTripStatus(tripId, nextStatus);
    shell.driverApp.lastActionResult = {
      last_action: "Start Route / En Route to Pickup",
      api_status: "ok",
      db_record_id: safeText(activeRide.id, tripId),
      updated_table: "health_isf_rides",
      ui_refreshed: "yes",
      current_ride_status: nextStatus
    };
    window.AmiOpsShellState = shell;
    _amiScheduleRenderPage();
    _amiLogDriverMobileSync({
      event: "route_progress",
      requested_ride_id: tripId,
      assignment_state: nextStatus,
      api_response: activeRide,
      http_status: 200,
      route: "/api/health-isf/drivers/" + driverId + "/route-progress",
      frontend_state_transition: "active_ride->active_ride",
      extra: { action: "Start Route / En Route to Pickup", target_state: "en_route_pickup" }
    });
  } catch (_) {
    window.alert("Unable to start route for " + tripId + ".");
    return false;
  }
  try {
    await _amiAfterDriverWorkflowRefresh("En route to pickup for " + tripId);
  } catch (_) {}
  return true;
};

window._amiHandleDriverStartTrip = async function(tripId) {
  var shell = _amiDriverShellState();
  var driverId = _amiCanonicalMobileDriverId(shell);
  if (!driverId || !tripId) return false;
  try {
    var payload = await _amiSendJson(
      "/api/health-isf/drivers/" + encodeURIComponent(driverId) + "/route-progress",
      "POST",
      { ride_id: tripId, target_state: "rider_loaded" }
    );
    var nextStatus = _amiStatusFromRouteProgressPayload(payload, "rider_loaded");
    var activeRide = safeObject(payload.active_ride || payload);
    shell = _amiPatchDriverTripStatus(tripId, nextStatus);
    shell.driverApp.lastActionResult = {
      last_action: "Rider On Board / Picked Up",
      api_status: "ok",
      db_record_id: safeText(activeRide.id, tripId),
      updated_table: "health_isf_rides",
      ui_refreshed: "yes",
      current_ride_status: nextStatus
    };
    window.AmiOpsShellState = shell;
    _amiScheduleRenderPage();
    _amiLogDriverMobileSync({
      event: "route_progress",
      requested_ride_id: tripId,
      assignment_state: nextStatus,
      api_response: activeRide,
      http_status: 200,
      route: "/api/health-isf/drivers/" + driverId + "/route-progress",
      frontend_state_transition: "active_ride->active_ride",
      extra: { action: "Rider On Board / Picked Up", target_state: "rider_loaded" }
    });
  } catch (_) {
    _amiLogDriverMobileSync({
      event: "route_progress_failed",
      requested_ride_id: tripId,
      route: "/api/health-isf/drivers/" + driverId + "/route-progress",
      api_response: { error: "rider_loaded_failed" },
      extra: { action: "Rider On Board / Picked Up", target_state: "rider_loaded" }
    });
    window.alert("Unable to submit driver start action for " + tripId + ".");
    shell = _amiDriverShellState();
    shell.driverApp = safeObject(shell.driverApp);
    shell.driverApp.lastActionResult = {
      last_action: "Rider On Board / Picked Up",
      api_status: "error",
      db_record_id: safeText(tripId, "n/a"),
      updated_table: "health_isf_rides",
      ui_refreshed: "no",
      current_ride_status: "unchanged"
    };
    window.AmiOpsShellState = shell;
    return false;
  }
  try {
    await _amiAfterDriverWorkflowRefresh("Patient onboard for " + tripId);
  } catch (_) {}
  return true;
};

window._amiHandleDriverOnboardTrip = async function(tripId) {
  return window._amiHandleDriverStartTrip(tripId);
};

window._amiHandleDriverProgressTrip = async function(tripId) {
  var shell = _amiDriverShellState();
  var driverId = _amiCanonicalMobileDriverId(shell);
  if (!driverId || !tripId) return false;
  try {
    var payload = await _amiSendJson(
      "/api/health-isf/drivers/" + encodeURIComponent(driverId) + "/route-progress",
      "POST",
      { ride_id: tripId, target_state: "trip_in_progress" }
    );
    var nextStatus = _amiStatusFromRouteProgressPayload(payload, "trip_in_progress");
    var activeRide = safeObject(payload.active_ride || payload);
    shell = _amiPatchDriverTripStatus(tripId, nextStatus);
    shell.driverApp.lastActionResult = {
      last_action: "Start Transportation",
      api_status: "ok",
      db_record_id: safeText(activeRide.id, tripId),
      updated_table: "health_isf_rides",
      ui_refreshed: "yes",
      current_ride_status: nextStatus
    };
    window.AmiOpsShellState = shell;
    _amiScheduleRenderPage();
    _amiLogDriverMobileSync({
      event: "route_progress",
      requested_ride_id: tripId,
      assignment_state: nextStatus,
      api_response: activeRide,
      http_status: 200,
      route: "/api/health-isf/drivers/" + driverId + "/route-progress",
      frontend_state_transition: "active_ride->active_ride",
      extra: { action: "Start Transportation", target_state: "trip_in_progress" }
    });
  } catch (_) {
    _amiLogDriverMobileSync({
      event: "route_progress_failed",
      requested_ride_id: tripId,
      route: "/api/health-isf/drivers/" + driverId + "/route-progress",
      api_response: { error: "trip_in_progress_failed" },
      extra: { action: "Start Transportation", target_state: "trip_in_progress" }
    });
    window.alert("Unable to update route progress for " + tripId + ".");
    shell = _amiDriverShellState();
    shell.driverApp = safeObject(shell.driverApp);
    shell.driverApp.lastActionResult = {
      last_action: "Start Transportation",
      api_status: "error",
      db_record_id: safeText(tripId, "n/a"),
      updated_table: "health_isf_rides",
      ui_refreshed: "no",
      current_ride_status: "unchanged"
    };
    window.AmiOpsShellState = shell;
    return false;
  }
  try {
    await _amiAfterDriverWorkflowRefresh("Transit progress updated for " + tripId);
  } catch (_) {}
  return true;
};

window._amiHandleDriverArriveDestination = async function(tripId) {
  var shell = _amiDriverShellState();
  var driverId = _amiCanonicalMobileDriverId(shell);
  if (!driverId || !tripId) return false;
  try {
    var payload = await _amiSendJson(
      "/api/health-isf/drivers/" + encodeURIComponent(driverId) + "/route-progress",
      "POST",
      { ride_id: tripId, target_state: "arrived_destination" }
    );
    var nextStatus = _amiStatusFromRouteProgressPayload(payload, "arrived_destination");
    var activeRide = safeObject(payload.active_ride || payload);
    shell = _amiPatchDriverTripStatus(tripId, nextStatus);
    shell.driverApp.lastActionResult = {
      last_action: "Arrived at Destination",
      api_status: "ok",
      db_record_id: safeText(activeRide.id, tripId),
      updated_table: "health_isf_rides",
      ui_refreshed: "yes",
      current_ride_status: nextStatus
    };
    window.AmiOpsShellState = shell;
    _amiScheduleRenderPage();
    _amiLogDriverMobileSync({
      event: "route_progress",
      requested_ride_id: tripId,
      assignment_state: nextStatus,
      api_response: activeRide,
      http_status: 200,
      route: "/api/health-isf/drivers/" + driverId + "/route-progress",
      frontend_state_transition: "active_ride->active_ride",
      extra: { action: "Arrived at Destination", target_state: "arrived_destination" }
    });
  } catch (_) {
    window.alert("Unable to mark arrived at destination for " + tripId + ".");
    return false;
  }
  try {
    await _amiAfterDriverWorkflowRefresh("Arrived at destination for " + tripId);
  } catch (_) {}
  return true;
};

window._amiHandleDriverCompleteTrip = async function(tripId) {
  var shell = _amiDriverShellState();
  var driverId = _amiCanonicalMobileDriverId(shell);
  if (window.AmiOpsShellActions && typeof window.AmiOpsShellActions.getMobileSessionDriverId === "function") {
    var boundId = safeText(window.AmiOpsShellActions.getMobileSessionDriverId(), "");
    if (boundId) driverId = boundId;
  }
  if (!driverId || !tripId) return false;
  var completeTimeoutMs = 45000;
  var handoffId = "";
  var paymentId = "";
  var completedRideId = safeText(tripId, "");
  var handoff = {};
  var payload = null;
  try {
    var progressPayload = await _amiSendJson(
      "/api/health-isf/drivers/" + encodeURIComponent(driverId) + "/route-progress",
      "POST",
      { ride_id: tripId, target_state: "completed" },
      completeTimeoutMs
    );
    payload = _amiResolveCompletionRidePayload(progressPayload, tripId);
    if (!payload) {
      payload = await _amiSendJson(
        "/api/health-isf/drivers/" + encodeURIComponent(driverId) + "/dropoff-complete",
        "POST",
        { ride_id: tripId },
        completeTimeoutMs
      );
    }
    try {
      handoff = safeObject(await _amiSendJson(
        "/api/health-isf/rides/" + encodeURIComponent(tripId) + "/completion-handoff",
        "GET",
        null
      ));
      handoffId = safeText(handoff.billing_handoff_id, "");
      paymentId = safeText(handoff.payment_transaction_id, "");
      shell = _amiDriverShellState();
      shell.driverApp = safeObject(shell.driverApp);
      if (!Array.isArray(shell.driverApp.billingHandoffs)) {
        shell.driverApp.billingHandoffs = [];
      }
      var nextHandoff = {
        handoff_id: handoffId || ("handoff-" + String(Date.now())),
        ride_id: safeText(tripId, ""),
        payment_id: paymentId || "pending",
        ride_price_usd: safeNumber(handoff.ride_price_usd, 0),
        driver_pay_usd: safeNumber(handoff.driver_pay_usd, 0),
        platform_revenue_usd: safeNumber(handoff.platform_revenue_usd, 0),
        status: safeText(handoff.billing_handoff_status, "pending")
      };
      shell.driverApp.billingHandoffs = dedupeBillingHandoffsByRideId(
        [nextHandoff].concat(shell.driverApp.billingHandoffs)
      ).slice(0, 30);
    } catch (_) {}
    var completedRide = safeObject(payload);
    completedRideId = safeText(completedRide.id || completedRide.ride_id, tripId);
    shell = _amiDriverShellState();
    shell.driverApp = safeObject(shell.driverApp);
    shell.driverApp.activeTripId = "";
    shell.driverApp.activeStage = "queued";
    shell.driverApp.tripQueue = (Array.isArray(shell.driverApp.tripQueue) ? shell.driverApp.tripQueue : []).filter(function (trip) {
      return safeText(trip.tripId, "") !== safeText(tripId, "");
    });
    if (handoff && Object.keys(handoff).length) {
      shell.driverWorkflow = safeObject(shell.driverWorkflow);
      var priorCompleted = Array.isArray(shell.driverWorkflow.completedRides) ? shell.driverWorkflow.completedRides : [];
      var alreadyListed = priorCompleted.some(function (ride) {
        return safeText(ride.id || ride.ride_id, "") === safeText(tripId, "");
      });
      if (!alreadyListed) {
        priorCompleted.unshift(completedRide);
      }
      shell.driverWorkflow.completedRides = priorCompleted;
      shell.driverApp.completedRideHistory = priorCompleted;
      syncDriverEarningsSummaryToApp(
        shell.driverApp,
        safeObject(shell.driverWorkflow.earnings),
        priorCompleted,
        shell.driverApp.billingHandoffs
      );
      if (handoff && Object.keys(handoff).length) {
        var handoffPay = safeNumber(handoff.driver_pay_usd, 0);
        if (handoffPay > 0) {
          shell.driverApp.earningsToday = safeNumber(shell.driverApp.earningsToday, 0) + handoffPay;
          shell.driverApp.earningsLifetime = safeNumber(shell.driverApp.earningsLifetime, 0) + handoffPay;
        }
      }
    }
    shell.driverApp.lastActionResult = {
      last_action: "Complete Trip",
      api_status: "ok",
      db_record_id: paymentId || completedRideId,
      updated_table: paymentId ? "health_isf_payments" : "health_isf_rides",
      ui_refreshed: "yes",
      current_ride_status: safeText(completedRide.lifecycle_state || completedRide.status, "completed")
    };
    window.AmiOpsShellState = shell;
    if (window.AmiOpsShellActions && typeof window.AmiOpsShellActions.resetDriverMobileAfterCompletion === "function") {
      window.AmiOpsShellActions.resetDriverMobileAfterCompletion();
    }
    _amiScheduleRenderPage();
  } catch (err) {
    var lifecycleAfterError = await _amiFetchRideLifecycleState(tripId, driverId);
    if (lifecycleAfterError === "completed") {
      _amiLogDriverMobileSync({
        event: "complete_trip_recovered",
        requested_ride_id: tripId,
        route: "/api/health-isf/drivers/" + driverId + "/route-progress",
        api_response: {
          lifecycle_state: lifecycleAfterError,
          error: safeText(err && err.message, "complete_request_failed")
        },
        extra: { action: "Complete Trip", recovered: true }
      });
      shell = _amiDriverShellState();
      shell.driverApp = safeObject(shell.driverApp);
      shell.driverApp.activeTripId = "";
      shell.driverApp.activeStage = "queued";
      shell.driverApp.tripQueue = (Array.isArray(shell.driverApp.tripQueue) ? shell.driverApp.tripQueue : []).filter(function (trip) {
        return safeText(trip.tripId, "") !== safeText(tripId, "");
      });
      shell.driverApp.lastActionResult = {
        last_action: "Complete Trip",
        api_status: "ok",
        db_record_id: safeText(tripId, "n/a"),
        updated_table: "health_isf_rides",
        ui_refreshed: "yes",
        current_ride_status: "completed"
      };
      window.AmiOpsShellState = shell;
      if (window.AmiOpsShellActions && typeof window.AmiOpsShellActions.resetDriverMobileAfterCompletion === "function") {
        window.AmiOpsShellActions.resetDriverMobileAfterCompletion();
      }
      _amiScheduleRenderPage();
    } else {
      _amiLogDriverMobileSync({
        event: "complete_trip_failed",
        requested_ride_id: tripId,
        route: "/api/health-isf/drivers/" + driverId + "/route-progress",
        api_response: { error: safeText(err && err.message, "complete_request_failed") },
        extra: { action: "Complete Trip" }
      });
      window.alert("Unable to submit driver complete action for " + tripId + ".");
      shell = _amiDriverShellState();
      shell.driverApp = safeObject(shell.driverApp);
      shell.driverApp.lastActionResult = {
        last_action: "Complete Trip",
        api_status: "error",
        db_record_id: safeText(tripId, "n/a"),
        updated_table: "health_isf_rides",
        ui_refreshed: "no",
        current_ride_status: "unchanged"
      };
      window.AmiOpsShellState = shell;
      return false;
    }
  }
  try {
    _amiLockDriverHydration(3500);
    if (window.AmiOpsShellActions && typeof window.AmiOpsShellActions.refreshDriverWorkflowData === "function") {
      await window.AmiOpsShellActions.refreshDriverWorkflowData({
        lastAction: "Completed trip " + completedRideId
      });
    } else {
      await _amiRefreshDriverWorkflow("Completed trip " + completedRideId);
    }
  } catch (_) {}
  _amiScheduleRenderPage();
  return true;
};

window._amiHandleDriverCallRider = async function(tripId) {
  var driverId = _amiCanonicalMobileDriverId();
  if (!driverId || !tripId) return false;
  try {
    var payload = await _amiSendJson(
      "/api/health-isf/drivers/" + encodeURIComponent(driverId) + "/contact-rider",
      "POST",
      { ride_id: tripId, channel: "sms" }
    );
    var dialTarget = safeText((safeObject(payload)).dial_target, "");
    state.driverApp = safeObject(state.driverApp);
    state.driverApp.lastActionResult = {
      last_action: "Call Rider",
      api_status: "ok",
      db_record_id: safeText((safeObject(payload)).reference, tripId),
      updated_table: "health_isf_dispatch_logs",
      ui_refreshed: "yes",
      current_ride_status: "rider_notified"
    };
    if (dialTarget && typeof window !== "undefined") {
      var shouldDial = window.confirm("SMS sent to rider. Open phone dialer for " + dialTarget + "?");
      if (shouldDial) {
        window.location.href = "tel:" + dialTarget;
      }
    }
    return true;
  } catch (error) {
    var message = safeText(error && error.message, "SMS/contact provider not configured yet");
    if (message.toLowerCase().indexOf("not configured") >= 0 || message.toLowerCase().indexOf("sms") >= 0) {
      window.alert("SMS/contact provider not configured yet");
      return false;
    }
    window.alert("Unable to contact rider for " + tripId + ": " + message);
    return false;
  }
};

window._amiHandleDriverDeclineTrip = async function(tripId) {
  var driverId = _amiCanonicalMobileDriverId();
  var driverWorkflow = safeObject(state.driverWorkflow);
  var offerEnvelope = safeObject(driverWorkflow.activeOffer);
  var offer = safeObject(offerEnvelope.offer);
  var offerId = safeText(offer.id || offer.offer_id, "");
  var tripStatus = _amiDriverTripStatus(tripId);

  if (driverId && ["assigned", "driver_en_route", "arrived", "accepted", "en_route_pickup", "arrived_pickup"].indexOf(tripStatus) >= 0) {
    try {
      await _amiSendJson(
        "/api/health-isf/drivers/" + encodeURIComponent(driverId) + "/no-show",
        "POST",
        { ride_id: tripId, note: "Rider no-show reported from driver mobile workspace" }
      );
      state.driverApp = safeObject(state.driverApp);
      state.driverApp.lastActionResult = {
        last_action: "No Show",
        api_status: "ok",
        db_record_id: tripId,
        updated_table: "health_isf_rides",
        ui_refreshed: "yes",
        current_ride_status: "no_show"
      };
      _amiLockDriverHydration(3500);
      await _amiAfterDriverWorkflowRefresh("No-show recorded for " + tripId);
      return true;
    } catch (_) {
      window.alert("Unable to record no-show for " + tripId + ".");
      return false;
    }
  }

  if (!offerId) {
    window.alert("No active assignment offer is available to decline for " + tripId + ".");
    return false;
  }
  try {
    await _amiSendJson("/api/health-isf/dispatch/offers/" + encodeURIComponent(offerId) + "/reject?reason=" + encodeURIComponent("driver_declined_in_workspace"), "POST", {});
    _amiLockDriverHydration(3500);
    await _amiAfterDriverWorkflowRefresh("Declined trip " + tripId);
    return true;
  } catch (_) {
    window.alert("Unable to decline the assignment for " + tripId + ".");
    return false;
  }
};

window._amiHandleDriverIncident = async function(tripId) {
  var note = window.prompt("Describe the incident for " + tripId + ":", "patient_delay") || "patient_delay";
  var result = await _amiSubmitWorkspaceAction(
    "driver.report_incident",
    { trip_id: tripId, note: note },
    "driver"
  );
  if (!result || result.ok === false) {
    window.alert("Unable to report incident for " + tripId + ".");
    return;
  }
};

window._amiHandleDriverShiftReadiness = async function(driverId, status) {
  var sessionToken = "";
  try {
    var persisted = JSON.parse(localStorage.getItem("amicor_driver_session") || "null");
    sessionToken = safeText(persisted && persisted.session_token, "");
  } catch (_) {}
  var platformToken = "";
  try {
    var sessionRaw = localStorage.getItem("amicor_session");
    if (sessionRaw) {
      var sessionObj = JSON.parse(sessionRaw);
      platformToken = safeText(sessionObj && (sessionObj.access_token || sessionObj.token), "");
    }
  } catch (_) {}
  if (sessionToken && !platformToken) {
    try {
      await _amiSendJson("/api/health-isf/drivers/availability", "POST", {
        driver_id: driverId,
        availability_state: status === "available" ? "available" : "offline",
        session_token: sessionToken
      });
      var shell = _amiDriverShellState();
      shell.driverApp = safeObject(shell.driverApp);
      shell.driverApp.shiftOnline = status === "available";
      window.AmiOpsShellState = shell;
      await _amiRefreshDriverWorkflow("Shift readiness updated");
      return true;
    } catch (_) {
      window.alert("Unable to update shift readiness for " + driverId + ".");
      return false;
    }
  }
  var result = await _amiSubmitWorkspaceAction(
    "driver.update_shift_readiness",
    { driver_id: driverId, status: status },
    "driver"
  );
  if (!result || result.ok === false) {
    window.alert("Unable to update shift readiness for " + driverId + ".");
    return false;
  }
  try {
    await _amiRefreshDriverWorkflow("Shift readiness updated");
  } catch (_) {}
  return true;
};

window._amiHandleDispatchAssign = async function(tripId) {
  var selectedDriverId = _amiValue("dispatch-driver-" + String(tripId));
  if (!selectedDriverId && window.AmiDispatchRuntime && typeof window.AmiDispatchRuntime.snapshot === "function") {
    var snapshot = window.AmiDispatchRuntime.snapshot();
    selectedDriverId = String((snapshot || {}).selectedDriverId || "");
  }
  if (!selectedDriverId) {
    _amiDispatcherError("Assign Driver failed", "Select a driver first, then assign the trip.");
    window.alert("Select a driver first, then assign the trip.");
    return;
  }
  var actionResult = await _amiSubmitWorkspaceAction(
    "dispatch.assign_driver",
    { trip_id: tripId, driver_id: selectedDriverId },
    "dispatcher"
  );
  if (!actionResult || actionResult.ok === false) {
    _amiDispatcherError("Assign Driver failed", safeText(actionResult && actionResult.detail, "workspace action failed"));
    window.alert("Unable to submit supervised assignment for " + tripId + ".");
    return;
  }
  _amiDispatcherSuccess("Assign Driver succeeded", "Trip " + tripId + " assigned.");
  await _amiRefreshDispatcherWorkspace();
  _amiDebugLog("[Dispatch] Assigned", selectedDriverId, "to", tripId);
};

window._amiHandleDispatchEscalate = async function(tripId) {
  var actionResult = await _amiSubmitWorkspaceAction(
    "dispatch.escalate_ride",
    { trip_id: tripId },
    "dispatcher"
  );
  if (!actionResult || actionResult.ok === false) {
    window.alert("Unable to submit escalation for " + tripId + ".");
    return;
  }
  if (!window.AmiDispatchRuntime || typeof window.AmiDispatchRuntime.escalateTrip !== "function") return;
  var result = window.AmiDispatchRuntime.escalateTrip(tripId);
  if (!result || result.ok === false) {
    window.alert("Unable to escalate trip " + tripId + ".");
    return;
  }
  _amiDebugLog("[Dispatch] Escalated", tripId);
};

window._amiHandleDispatchDriverSelect = function(driverId, driverName) {
  if (window.AmiDispatchRuntime && typeof window.AmiDispatchRuntime.selectDriver === "function") {
    window.AmiDispatchRuntime.selectDriver(driverId);
  }
  _amiDebugLog("[Dispatch] Selected driver", driverName, driverId);
};

window._amiHandleDispatchMonitor = function(tripId) {
  if (window.AmiOperationalEvents && typeof window.AmiOperationalEvents.emit === "function") {
    window.AmiOperationalEvents.emit("dispatch_monitor_trip", { tripId: tripId });
    window.dispatchEvent(new CustomEvent("ami:ops-runtime-updated"));
  }
  _amiDebugLog("[Dispatch] Monitor trip", tripId);
};

window._amiHandleDispatchReassign = async function(tripId) {
  var selectedDriverId = _amiValue("dispatch-driver-" + String(tripId));
  if (!selectedDriverId && window.AmiDispatchRuntime && typeof window.AmiDispatchRuntime.snapshot === "function") {
    var snapshot = window.AmiDispatchRuntime.snapshot();
    selectedDriverId = String((snapshot || {}).selectedDriverId || "");
  }
  if (!selectedDriverId) {
    _amiDispatcherError("Reassign Driver failed", "Select a driver before reassigning.");
    window.alert("Select a driver before reassigning.");
    return;
  }
  var actionResult = await _amiSubmitWorkspaceAction(
    "dispatch.reassign_driver",
    { trip_id: tripId, driver_id: selectedDriverId },
    "dispatcher"
  );
  if (!actionResult || actionResult.ok === false) {
    _amiDispatcherError("Reassign Driver failed", safeText(actionResult && actionResult.detail, "workspace action failed"));
    window.alert("Unable to submit reassignment for " + tripId + ".");
    return;
  }
  _amiDispatcherSuccess("Reassign Driver succeeded", "Trip " + tripId + " reassigned.");
  await _amiRefreshDispatcherWorkspace();
};

window._amiHandleDispatchCancel = async function(tripId) {
  var actionResult = await _amiSubmitWorkspaceAction(
    "dispatch.cancel_ride",
    { trip_id: tripId },
    "dispatcher"
  );
  if (!actionResult || actionResult.ok === false) {
    _amiDispatcherError("Cancel Ride failed", safeText(actionResult && actionResult.detail, "workspace action failed"));
    window.alert("Unable to submit cancellation for " + tripId + ".");
    return;
  }
  _amiDispatcherSuccess("Cancel Ride succeeded", "Trip " + tripId + " cancelled.");
  await _amiRefreshDispatcherWorkspace();
};

window._amiHandleDispatchDriverAccept = async function(tripId) {
  var actionResult = await _amiRequestJson(
    "/api/health-isf/rides/" + encodeURIComponent(tripId) + "/status",
    "PATCH",
    { status: "driver_en_route" }
  );
  if (!actionResult || actionResult.ok === false) {
    _amiDispatcherError("Driver Accept failed", safeText(actionResult && actionResult.detail, "backend request failed"));
    window.alert("Unable to set driver-accepted state for " + tripId + ".");
    return;
  }
  _amiDispatcherSuccess("Driver Accept succeeded", "ride_id=" + tripId);
  await _amiRefreshDispatcherWorkspace();
  var ride = (Array.isArray((safeObject(state.liveWorkflow)).rides) ? state.liveWorkflow.rides : []).find(function (item) {
    return safeText(item.id, "") === safeText(tripId, "");
  });
  var ok = ride && safeText(ride.status, "").toLowerCase() === "driver_en_route";
  _amiSetDispatcherProof("Driver Accepts", ok ? "ok" : "partial", tripId, !!ok);
};

window._amiHandleDispatchMarkArrived = async function(tripId) {
  var actionResult = await _amiRequestJson(
    "/api/health-isf/dispatcher/rides/" + encodeURIComponent(tripId) + "/mark-arrived",
    "PATCH",
    {}
  );
  if (!actionResult || actionResult.ok === false) {
    _amiDispatcherError("Arrive failed", safeText(actionResult && actionResult.detail, "workspace action failed"));
    window.alert("Unable to submit arrive update for " + tripId + ".");
    return;
  }
  _amiDispatcherSuccess("Arrive succeeded", "Trip " + tripId + " marked arrived.");
  await _amiRefreshDispatcherWorkspace();
  var ride = (Array.isArray((safeObject(state.liveWorkflow)).rides) ? state.liveWorkflow.rides : []).find(function (item) {
    return safeText(item.id, "") === safeText(tripId, "");
  });
  var ok = ride && safeText(ride.status, "").toLowerCase() === "arrived";
  _amiSetDispatcherProof("Driver Arrives", ok ? "ok" : "partial", tripId, !!ok);
};

window._amiHandleDispatchPickup = async function(tripId) {
  var actionResult = await _amiRequestJson(
    "/api/health-isf/dispatcher/rides/" + encodeURIComponent(tripId) + "/mark-onboard",
    "PATCH",
    {}
  );
  if (!actionResult || actionResult.ok === false) {
    _amiDispatcherError("Pickup failed", safeText(actionResult && actionResult.detail, "backend request failed"));
    window.alert("Unable to submit pickup update for " + tripId + ".");
    return;
  }
  _amiDispatcherSuccess("Pickup succeeded", "ride_id=" + tripId);
  await _amiRefreshDispatcherWorkspace();
  var ride = (Array.isArray((safeObject(state.liveWorkflow)).rides) ? state.liveWorkflow.rides : []).find(function (item) {
    return safeText(item.id, "") === safeText(tripId, "");
  });
  var ok = ride && safeText(ride.status, "").toLowerCase() === "rider_onboard";
  _amiSetDispatcherProof("Driver Picks Up", ok ? "ok" : "partial", tripId, !!ok);
};

async function _amiAppendDispatcherBillingProof(tripId) {
  var rideKey = safeText(tripId, "").trim();
  if (!rideKey) {
    return;
  }

  async function readPayments() {
    var token = "";
    var organizationId = "";
    try {
      var sessionRaw = localStorage.getItem("amicor_session");
      if (sessionRaw) {
        var session = JSON.parse(sessionRaw);
        token = safeText(session && (session.accessToken || session.access_token), token);
        organizationId = safeText(session && (session.organization_id || session.organizationId), organizationId);
      }
    } catch (_) {}
    try {
      var identityRaw = localStorage.getItem("amicor_identity");
      if (identityRaw) {
        var identity = JSON.parse(identityRaw);
        if (!token) {
          token = safeText(identity && (identity.accessToken || identity.access_token), token);
        }
        if (!organizationId) {
          organizationId = safeText(identity && (identity.organization_id || identity.organizationId), organizationId);
        }
      }
    } catch (_) {}

    var url = "/api/health-isf/payments/rides/" + encodeURIComponent(rideKey);
    if (organizationId) {
      url += "?organization_id=" + encodeURIComponent(organizationId);
    }

    var headers = { "Accept": "application/json" };
    if (token) {
      headers.Authorization = "Bearer " + token;
    }

    var response = await fetch(url, {
      method: "GET",
      headers: headers,
      credentials: "same-origin"
    });

    if (!response.ok) {
      throw new Error(url + ":http_" + response.status);
    }

    var payload = await response.json();
    if (Array.isArray(payload)) {
      return payload;
    }
    if (payload && Array.isArray(payload.payments)) {
      return payload.payments;
    }
    return [];
  }

  try {
    var payments = await readPayments();
    if (!payments.length) {
      await new Promise(function(resolve) {
        setTimeout(resolve, 700);
      });
      payments = await readPayments();
    }

    if (!payments.length) {
      _amiDispatcherError("Billing/Payment proof pending", "No payment transaction is visible yet for ride " + rideKey + ".");
      return;
    }

    var latest = safeObject(payments[0]);
    var paymentId = safeText(latest.payment_id || latest.id, "unknown");
    var paymentStatus = safeText(latest.status, "unknown");
    var settlementStatus = safeText(latest.settlement_status, "unknown");
    var invoiceReference = safeText(latest.invoice_reference, "n/a");
    _amiDispatcherSuccess(
      "Billing/Payment proof",
      "payment_id=" + paymentId + ", status=" + paymentStatus + ", settlement=" + settlementStatus + ", invoice=" + invoiceReference + "."
    );
  } catch (error) {
    _amiDispatcherError("Billing/Payment proof failed", safeText(error && error.message, "Unable to fetch payment proof."));
  }
}

window._amiHandleDispatchComplete = async function(tripId) {
  var actionResult = await _amiRequestJson(
    "/api/health-isf/dispatcher/rides/" + encodeURIComponent(tripId) + "/complete",
    "PATCH",
    {}
  );
  if (!actionResult || actionResult.ok === false) {
    _amiDispatcherError("Complete Ride failed", safeText(actionResult && actionResult.detail, "workspace action failed"));
    window.alert("Unable to submit completion for " + tripId + ".");
    return;
  }
  _amiDispatcherSuccess("Complete Ride succeeded", "Trip " + tripId + " completed.");
  await _amiRefreshDispatcherWorkspace();
  var ride = (Array.isArray((safeObject(state.liveWorkflow)).rides) ? state.liveWorkflow.rides : []).find(function (item) {
    return safeText(item.id, "") === safeText(tripId, "");
  });
  var ok = ride && safeText(ride.status, "").toLowerCase() === "completed";
  _amiSetDispatcherProof("Driver Completes Trip", ok ? "ok" : "partial", tripId, !!ok);
};

window._amiHandleDispatchCreateBilling = async function(tripId) {
  var invoiceReference = "MVP-" + String(Date.now());
  var actionResult = await _amiRequestJson(
    "/api/health-isf/payments/intents",
    "POST",
    {
      ride_id: tripId,
      amount_usd: 45,
      currency: "USD",
      invoice_reference: invoiceReference,
      capture_immediately: false
    }
  );
  if (!actionResult || actionResult.ok === false) {
    _amiDispatcherError("Create Billing failed", safeText(actionResult && actionResult.detail, "backend request failed"));
    window.alert("Unable to create billing record for " + tripId + ".");
    return;
  }

  var payment = safeObject(actionResult.response);
  var paymentId = safeText(payment.id, "");
  _amiDispatcherSuccess("Create Billing succeeded", paymentId ? ("payment_id=" + paymentId) : ("ride_id=" + tripId));
  await _amiRefreshDispatcherWorkspace();
  _amiSetDispatcherProof("Create Billing", "ok", paymentId || tripId, true);
  await _amiAppendDispatcherBillingProof(tripId);
};

window._amiHandleWorkflowAssignDriver = async function() {
  var rideId = _amiValue("dispatcher-workflow-ride-id");
  var driverId = _amiValue("dispatcher-workflow-driver-id");
  if (!rideId || !driverId) {
    _amiDispatcherError("Assign Driver failed", "Select ride and driver first.");
    window.alert("Select ride and driver first.");
    return;
  }
  _amiSetValue("dispatch-driver-" + String(rideId), driverId);
  await window._amiHandleDispatchAssignFromSelect(rideId);
};

window._amiHandleWorkflowDriverAccept = async function() {
  var rideId = _amiValue("dispatcher-workflow-ride-id");
  if (!rideId) {
    _amiDispatcherError("Driver Accept failed", "Select a ride first.");
    window.alert("Select a ride first.");
    return;
  }
  await window._amiHandleDispatchDriverAccept(rideId);
};

window._amiHandleWorkflowDriverArrived = async function() {
  var rideId = _amiValue("dispatcher-workflow-ride-id");
  if (!rideId) {
    _amiDispatcherError("Arrived failed", "Select a ride first.");
    window.alert("Select a ride first.");
    return;
  }
  await window._amiHandleDispatchMarkArrived(rideId);
};

window._amiHandleWorkflowDriverPickup = async function() {
  var rideId = _amiValue("dispatcher-workflow-ride-id");
  if (!rideId) {
    _amiDispatcherError("Pickup failed", "Select a ride first.");
    window.alert("Select a ride first.");
    return;
  }
  await window._amiHandleDispatchPickup(rideId);
};

window._amiHandleWorkflowDriverComplete = async function() {
  var rideId = _amiValue("dispatcher-workflow-ride-id");
  if (!rideId) {
    _amiDispatcherError("Complete failed", "Select a ride first.");
    window.alert("Select a ride first.");
    return;
  }
  await window._amiHandleDispatchComplete(rideId);
};

window._amiHandleWorkflowCreateBilling = async function() {
  var rideId = _amiValue("dispatcher-workflow-ride-id");
  if (!rideId) {
    _amiDispatcherError("Create Billing failed", "Select a ride first.");
    window.alert("Select a ride first.");
    return;
  }
  await window._amiHandleDispatchCreateBilling(rideId);
};

window._amiHandleDispatchContactRider = async function(tripId) {
  try {
    await _amiSubmitWorkspaceAction(
      "dispatch.contact_rider",
      { trip_id: tripId },
      "dispatcher"
    );
  } catch (error) {
    window.alert(safeText(error && error.message, "SMS/contact provider not configured yet"));
    return;
  }
  if (window.AmiDispatchRuntime && typeof window.AmiDispatchRuntime.contactRider === "function") {
    window.AmiDispatchRuntime.contactRider(tripId);
  }
};

window._amiHandleDispatchContactDriver = async function(tripId) {
  try {
    await _amiSubmitWorkspaceAction(
      "dispatch.contact_driver",
      { trip_id: tripId },
      "dispatcher"
    );
  } catch (error) {
    window.alert(safeText(error && error.message, "SMS/contact provider not configured yet"));
    return;
  }
  if (window.AmiDispatchRuntime && typeof window.AmiDispatchRuntime.contactDriver === "function") {
    window.AmiDispatchRuntime.contactDriver(tripId);
  }
};

