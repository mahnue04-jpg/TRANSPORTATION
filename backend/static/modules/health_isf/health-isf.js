(function initHealthISFModule() {
  const HEALTH_HASH_PREFIX = "#/health-isf/";
  const PRIMARY_ROUTE = "dashboard";
  const VIEW_ROUTES = ["dashboard", "rides", "dispatch", "drivers", "providers", "customer", "analytics", "billing", "grant", "admin", "onboarding"];
  const RUNTIME_STATE_STORAGE_KEY = "amicor_health_isf_runtime_state_v1";
  const SHELL_ROLE_OVERRIDE_STORAGE_KEY = "amicor_health_isf_shell_role_override_v1";
  const API_REQUEST_TIMEOUT_MS = 45000;
  const REALTIME_RECONNECT_COOLDOWN_MS = 12000;
  const REALTIME_STALE_THRESHOLD_MS = 45000;
  const NAVIGATION_COOLDOWN_MS = 650;
  const REFRESH_TRIGGER_COOLDOWN_MS = 1800;
  const HYDRATION_EVENT_COOLDOWN_MS = 5000;
  const HASH_ROUTE_SUPPRESSION_MS = 2000;
  const RECONNECT_BURST_WINDOW_MS = 30000;
  const RECONNECT_BURST_LIMIT = 6;
  const ROLE_ROUTE_ACCESS = {
    admin: VIEW_ROUTES.slice(),
    dispatcher: VIEW_ROUTES.slice(),
    staff: VIEW_ROUTES.slice(),
    customer: ["dashboard", "customer", "analytics"],
    driver: ["dashboard", "rides", "analytics"],
    provider: ["dashboard", "providers", "analytics", "customer"],
    guest: ["dashboard"],
  };

  const state = {
    active: false,
    authGateVisible: false,
    pendingRoute: null,
    route: PRIMARY_ROUTE,
    dashboard: null,
    enterpriseDashboard: null,
    aiSnapshot: null,
    operationalStatus: null,
    operationalExpansion: null,
    governanceStatus: null,
    governanceApprovals: [],
    operationalEventFeed: [],
    operationalEventKeys: [],
    operationalMemorySnapshot: null,
    operationalMemoryReferences: [],
    operationalReplayHistory: [],
    runtimeDiagnostics: null,
    novaContinuityBrief: null,
    novaAssistanceRecommendations: [],
    novaLiveEvents: [],
    novaMemoryFabric: null,
    websocketDiagnostics: null,
    rides: [],
    drivers: [],
    providers: [],
    providerTransportQueue: [],
    customerRequests: [],
    customerQueueMetrics: null,
    dispatchQueue: [],
    dispatchActiveAssignments: [],
    dispatchTimeline: [],
    driverPoolMetrics: null,
    driverApplications: [],
    recurringTemplates: [],
    grantSnapshot: null,
    selectedDriverId: null,
    selectedDriverAssignedRides: [],
    driverRuntimeStatus: null,
    driverRuntimeToken: null,
    driverIncomingOffer: null,
    driverLiveWorkspace: null,
    selectedRideId: null,
    selectedRideHistory: [],
    selectedRideDispatchHistory: [],
    selectedOperationalTimeline: [],
    selectedRideWorkflowProof: null,
    refreshTimer: null,
    realtimeRefreshTimer: null,
    socket: null,
    reconnectTimer: null,
    reconnectAttempt: 0,
    reconnectBackoffMs: 1500,
    lastRealtimeConnectAtMs: 0,
    lastRealtimeActivityAtMs: 0,
    lastRealtimeReconnectAtMs: 0,
    createRideSubmitting: false,
    lastRealtimeMessageAt: null,
    websocketStatus: "idle",
    rideRealtimeEvents: {},
    aiRecommendations: {},
    realtimeDedup: [],
    voice: {
      mode: null,
      recognition: null,
      listening: false,
      transcript: "",
      interim: "",
      supported: !!(window.webkitSpeechRecognition || window.SpeechRecognition),
      submitOnEnd: false,
    },
    filters: {
      status: "all",
      provider: "all",
      driver: "all",
      priority: "all",
      query: "",
    },
    hydration: {
      lastRefreshAt: null,
      lastRefreshError: null,
      aiSnapshotDegraded: false,
      aiSnapshotError: null,
    },
    pendingRequests: 0,
    lastApiError: null,
    lastCompletedAction: null,
    lastFailedAction: null,
    lastActionAt: null,
    activeOrganizationId: null,
    shellRoleOverride: null,
    customerWorkspace: {
      riderPhone: "",
      history: [],
      activeRide: null,
      timeline: [],
      etaMinutes: null,
    },
    adminSummary: null,
    adminRoleSessions: null,
    adminLiveOperations: null,
    adminDispatchAlerts: null,
    runtimeState: null,
    runtimeReplay: null,
    previewRuntimeStatus: null,
    previewRuntimeLastCheck: null,
    serviceCategories: [],
    shellProfile: null,
    executionEvents: [],
    phase57AutoscrollPinned: true,
    phase57LastRenderAt: null,
    phase58Retention: 180,
    phase58TimelineWindowSize: 28,
    phase58TimelineOffset: 0,
    phase58TimelineFilters: {
      severity: "all",
      role: "all",
      category: "all",
      query: "",
    },
    phase59SupervisorReview: {},
    phase59OverrideIntents: [],
    refreshPromise: null,
    providerHydrationPromise: null,
    refreshQueued: false,
    routeMutationInProgress: false,
    navSync: {
      suppressHashRoute: null,
      suppressHashRouteUntilMs: 0,
      lastNavigateAtMs: 0,
      lastNavigateRoute: null,
      lastNavigateSource: null,
      lastForcedNavigateAtMs: 0,
      lastRefreshBySource: {},
      lastHydrationBySource: {},
      lastReconnectBySource: {},
    },
    stability: {
      routeTransitions: 0,
      suppressedNavigations: 0,
      forcedNavigationCalls: 0,
      shellRenderCount: 0,
      shellRenderReplacements: 0,
      reconnectAttempts: 0,
      reconnectSuppressed: 0,
      reconnectBursts: 0,
      hydrationTriggers: 0,
      hydrationSuppressed: 0,
      refreshSuppressed: 0,
      automationEventsSuppressed: 0,
      reconnectWindowStartMs: 0,
      reconnectWindowCount: 0,
    },
  };

  function stampNow() {
    return new Date().toISOString();
  }

  function isDevelopmentPreviewMode() {
    try {
      const params = new URLSearchParams(String(window.location.search || ''));
      const queryValue = String(params.get('developer_mode') || '').toLowerCase();
      const storageValue = String(window.localStorage.getItem('amicor_developer_mode') || '').toLowerCase();
      return ['1', 'true', 'on', 'yes'].indexOf(queryValue) !== -1
        || ['1', 'true', 'on', 'yes'].indexOf(storageValue) !== -1;
    } catch (_err) {
      return false;
    }
  }

  function persistRuntimeState(reason) {
    try {
      if (!window.sessionStorage) return;
      const snapshot = {
        route: VIEW_ROUTES.includes(state.route) ? state.route : PRIMARY_ROUTE,
        selectedRideId: state.selectedRideId || null,
        filters: Object.assign({}, state.filters),
        activeOrganizationId: state.activeOrganizationId || null,
        websocketStatus: state.websocketStatus,
        updatedAt: stampNow(),
        reason: reason || "update",
      };
      window.sessionStorage.setItem(RUNTIME_STATE_STORAGE_KEY, JSON.stringify(snapshot));
      if (state.shellRoleOverride) {
        window.sessionStorage.setItem(SHELL_ROLE_OVERRIDE_STORAGE_KEY, String(state.shellRoleOverride));
      } else {
        window.sessionStorage.removeItem(SHELL_ROLE_OVERRIDE_STORAGE_KEY);
      }
    } catch (_err) {}
  }

  function restoreRuntimeState() {
    try {
      if (!window.sessionStorage) return;
      const raw = window.sessionStorage.getItem(RUNTIME_STATE_STORAGE_KEY);
      if (!raw) return;
      const parsed = JSON.parse(raw);
      if (!parsed || typeof parsed !== "object") return;

      const restoredRoute = String(parsed.route || "").toLowerCase();
      if (VIEW_ROUTES.includes(restoredRoute)) {
        state.route = restoredRoute;
      }

      if (parsed.filters && typeof parsed.filters === "object") {
        state.filters.status = String(parsed.filters.status || state.filters.status || "all");
        state.filters.provider = String(parsed.filters.provider || state.filters.provider || "all");
        state.filters.driver = String(parsed.filters.driver || state.filters.driver || "all");
        state.filters.priority = String(parsed.filters.priority || state.filters.priority || "all");
        state.filters.query = String(parsed.filters.query || state.filters.query || "").trim();
      }

      if (parsed.selectedRideId) {
        state.selectedRideId = String(parsed.selectedRideId);
      }
      if (parsed.activeOrganizationId) {
        state.activeOrganizationId = String(parsed.activeOrganizationId);
      }
      if (parsed.websocketStatus) {
        state.websocketStatus = String(parsed.websocketStatus);
      }
      const roleOverride = String(window.sessionStorage.getItem(SHELL_ROLE_OVERRIDE_STORAGE_KEY) || "").trim().toLowerCase();
      if (roleOverride && ROLE_ROUTE_ACCESS[roleOverride]) {
        state.shellRoleOverride = roleOverride;
      }
    } catch (_err) {}
  }

  function getEffectiveShellRole(baseRole) {
    const fallbackRole = String(baseRole || "guest").toLowerCase();
    const override = String(state.shellRoleOverride || "").toLowerCase();
    if (override && ROLE_ROUTE_ACCESS[override]) {
      return override;
    }
    return ROLE_ROUTE_ACCESS[fallbackRole] ? fallbackRole : "guest";
  }

  function logDiag(topic, payload) {
    if (!isDevelopmentPreviewMode()) return;
    try {
      console.log("[Health ISF] " + topic, payload || {});
    } catch (_err) {}
  }

  function normalizeApiError(error) {
    const message = String(error && error.message ? error.message : error || "Request failed");
    const lower = message.toLowerCase();
    if (lower.indexOf("aborted") !== -1 || lower.indexOf("timeout") !== -1) {
      return "Operational request timed out";
    }
    if (lower.indexOf("401") !== -1 || lower.indexOf("403") !== -1 || lower.indexOf("auth") !== -1 || lower.indexOf("token") !== -1) {
      return "Authentication session expired";
    }
    if (lower.indexOf("failed to fetch") !== -1 || lower.indexOf("network") !== -1) {
      return "Realtime execution reconnecting";
    }
    return message;
  }

  function incrementStabilityCounter(key, amount) {
    if (!state.stability || !Object.prototype.hasOwnProperty.call(state.stability, key)) return;
    const step = Number.isFinite(Number(amount)) ? Number(amount) : 1;
    state.stability[key] = Number(state.stability[key] || 0) + step;
  }

  function operatorIsolationEnabled() {
    try {
      const params = new URLSearchParams(String(window.location.search || ""));
      const queryValue = String(params.get("operator_isolation") || "").toLowerCase();
      const storageValue = String(window.localStorage.getItem("amicor_operator_isolation") || "").toLowerCase();
      const disabled = ["0", "false", "off", "no"];
      if (disabled.indexOf(queryValue) !== -1) return false;
      if (disabled.indexOf(storageValue) !== -1) return false;
      return true;
    } catch (_err) {
      return true;
    }
  }

  function shouldSuppressSyntheticEvent(event, source) {
    if (!operatorIsolationEnabled()) return false;
    if (!event || typeof event.isTrusted !== "boolean") return false;
    if (event.isTrusted) return false;
    incrementStabilityCounter("automationEventsSuppressed", 1);
    logDiag("Synthetic event suppressed", { source: source || "unknown" });
    return true;
  }

  function shouldThrottleBySource(bucket, source, cooldownMs) {
    const map = state.navSync[bucket];
    if (!map || typeof map !== "object") return false;
    const key = String(source || "unknown");
    const now = nowMs();
    const lastAt = Number(map[key] || 0);
    if (lastAt > 0 && now - lastAt < cooldownMs) {
      return true;
    }
    map[key] = now;
    return false;
  }

  function triggerRefresh(source, options) {
    const opts = options && typeof options === "object" ? options : {};
    if (!state.active) return;
    const refreshSource = String(source || "unknown");
    const bypassCooldown = !!opts.bypassCooldown;
    if (!bypassCooldown && shouldThrottleBySource("lastRefreshBySource", refreshSource, REFRESH_TRIGGER_COOLDOWN_MS)) {
      incrementStabilityCounter("refreshSuppressed", 1);
      logDiag("Refresh suppressed", { source: refreshSource, reason: "cooldown" });
      return null;
    }
    return refreshData();
  }

  function triggerHydrationRefresh(source, options) {
    const opts = options && typeof options === "object" ? options : {};
    if (!state.active) return;
    const hydrationSource = String(source || "unknown");
    if (!opts.bypassCooldown && shouldThrottleBySource("lastHydrationBySource", hydrationSource, HYDRATION_EVENT_COOLDOWN_MS)) {
      incrementStabilityCounter("hydrationSuppressed", 1);
      logDiag("Hydration suppressed", { source: hydrationSource, reason: "cooldown" });
      return;
    }
    incrementStabilityCounter("hydrationTriggers", 1);
    logDiag("Hydration trigger", { source: hydrationSource });
    triggerRefresh(hydrationSource, { bypassCooldown: true });
    reconnectRealtime(hydrationSource, { onlyIfStale: true });
  }

  function recordExecutionEvent(event) {
    state.executionEvents.unshift(Object.assign({
      at: stampNow(),
      route: state.route,
      websocketStatus: state.websocketStatus,
      pendingRequests: state.pendingRequests,
      authActive: !!(window.AmiCorSession && typeof window.AmiCorSession.isActive === "function" && window.AmiCorSession.isActive()),
    }, event || {}));
    state.executionEvents = state.executionEvents.slice(0, 60);
  }

  function operationalTone(severity) {
    const value = String(severity || "info").toLowerCase();
    if (["critical", "high", "danger", "error"].includes(value)) return "danger";
    if (["medium", "warn", "warning", "attention"].includes(value)) return "warn";
    return "live";
  }

  function firstDefined() {
    for (let index = 0; index < arguments.length; index += 1) {
      const candidate = arguments[index];
      if (candidate !== undefined && candidate !== null && String(candidate).trim() !== "") {
        return candidate;
      }
    }
    return null;
  }

  function normalizeServiceCategory(value) {
    const raw = String(value || "").trim().toLowerCase().replace(/-/g, "_");
    if (!raw) return "medical_transport";
    if (raw === "healthcare" || raw === "dialysis" || raw === "discharge" || raw === "oncology") return "medical_transport";
    if (raw === "recurring") return "recurring_transport";
    if (raw === "provider") return "provider_transport";
    return raw;
  }

  function formatServiceCategoryLabel(value) {
    const key = normalizeServiceCategory(value);
    const map = {
      medical_transport: "Medical Transport",
      recurring_transport: "Recurring Transport",
      provider_transport: "Provider Transport",
      future_medical_logistics: "Future Medical Logistics",
      future_pharmacy_delivery: "Future Pharmacy Delivery",
    };
    return map[key] || key.replace(/_/g, " ");
  }

  function summarizeOperationalPayload(eventType, payload) {
    const summary = firstDefined(
      payload.summary,
      payload.message,
      payload.reason,
      payload.description,
      payload.operational_summary,
      payload.explanation,
      payload.detail,
      payload.title
    );
    if (summary) return String(summary);
    return String(eventType || "operational_event").replace(/_/g, " ");
  }

  function normalizeOperationalEvent(rawEvent, source) {
    const payload = rawEvent && rawEvent.payload && typeof rawEvent.payload === "object"
      ? rawEvent.payload
      : (rawEvent && typeof rawEvent === "object" ? rawEvent : {});
    const eventType = String(firstDefined(rawEvent && rawEvent.event_type, rawEvent && rawEvent.eventType, rawEvent && rawEvent.type, payload.event_type, payload.eventType, "operational_event") || "operational_event");
    const timestamp = String(firstDefined(rawEvent && rawEvent.timestamp, rawEvent && rawEvent.created_at, payload.timestamp, payload.created_at, new Date().toISOString()));
    const normalizedSource = String(firstDefined(rawEvent && rawEvent.source, rawEvent && rawEvent.origin, source, payload.source, eventType.includes("memory") ? "memory" : "backend") || "backend");
    const severity = String(firstDefined(rawEvent && rawEvent.severity, payload.severity, eventType.includes("incident") || eventType.includes("escalat") ? "high" : eventType.includes("approval") ? "medium" : "info") || "info");
    const recommendationOnly = Boolean(firstDefined(rawEvent && rawEvent.recommendation_only, payload.recommendation_only, payload.recommendationOnly, /recommendation/i.test(eventType)));
    const approvalRequired = Boolean(firstDefined(rawEvent && rawEvent.approval_required, payload.approval_required, payload.approvalRequired, recommendationOnly));
    const confidence = Number(firstDefined(rawEvent && rawEvent.confidence, payload.confidence, payload.priority_score, 0) || 0);
    const impactedSurface = String(firstDefined(rawEvent && rawEvent.impacted_surface, payload.impacted_surface, payload.surface, payload.target_surface, eventType.includes("driver") ? "Driver" : eventType.includes("provider") ? "Provider" : eventType.includes("approval") ? "Governance" : "Dashboard") || "Dashboard");
    const recommendationStatus = approvalRequired ? (payload.approved ? "approved" : "approval required") : (recommendationOnly ? "recommendation only" : "observed");
    const synchronizationImpact = String(firstDefined(payload.synchronization_impact, payload.replay_safe, payload.reconnect_safe, payload.backend_authoritative, payload.tenant_scoped, "replay-safe") || "replay-safe");
    const tenantScope = String(firstDefined(rawEvent && rawEvent.tenant_scope, payload.tenant_scope, payload.organization_id, state.activeOrganizationId, "tenant-scoped") || "tenant-scoped");
    const eventId = String(firstDefined(rawEvent && rawEvent.event_id, rawEvent && rawEvent.id, payload.event_id, payload.id, [eventType, normalizedSource, timestamp, confidence].join("|")));

    return {
      eventId,
      timestamp,
      eventType,
      source: normalizedSource,
      severity,
      summary: summarizeOperationalPayload(eventType, payload),
      recommendationStatus,
      recommendationOnly,
      approvalRequired,
      confidence,
      impactedSurface,
      operationalRisk: String(firstDefined(rawEvent && rawEvent.operational_risk, payload.operational_risk, severity) || severity),
      synchronizationImpact,
      tenantScope,
      payload,
    };
  }

  function recordOperationalEvent(rawEvent, source) {
    const item = normalizeOperationalEvent(rawEvent, source);
    const key = [item.eventId, item.eventType, item.timestamp, item.source].join("|");
    if (state.operationalEventKeys.indexOf(key) !== -1) return null;
    state.operationalEventKeys.unshift(key);
    state.operationalEventKeys = state.operationalEventKeys.slice(0, 200);
    state.operationalEventFeed.unshift(item);
    state.operationalEventFeed = state.operationalEventFeed.slice(0, 200);
    return item;
  }

  function seedOperationalEventFeed(snapshot) {
    const expansion = snapshot && snapshot.operational_intelligence_expansion ? snapshot.operational_intelligence_expansion : snapshot || {};
    const distributed = expansion.distributed_operational_event_fabric || {};
    const publications = Array.isArray(distributed.event_publication_results) ? distributed.event_publication_results : [];
    publications.forEach((event) => recordOperationalEvent(event, "snapshot"));

    const approvals = Array.isArray((expansion.human_oversight_intelligence || {}).approval_workflows)
      ? expansion.human_oversight_intelligence.approval_workflows
      : [];
    approvals.forEach((approval) => {
      recordOperationalEvent({
        event_id: approval.approval_id || approval.id || approval.event_id,
        event_type: "governance_approval_event",
        timestamp: approval.approval_timestamp || approval.updated_at || approval.created_at,
        severity: approval.approved_by ? "medium" : "warn",
        payload: {
          summary: approval.status || "approval review",
          message: approval.action_type || "Governance approval queued",
          approval_required: approval.approval_required !== false,
          approved: Boolean(approval.approved_by),
          confidence: approval.confidence_score || 0,
          impacted_surface: approval.action_type || "Governance",
          tenant_scope: approval.tenant_scope || state.activeOrganizationId || "tenant-scoped",
          synchronization_impact: approval.rollback_available ? "rollback-ready" : "approval-bound",
        },
      }, "governance");
    });
  }

  function getOperationalExpansionSnapshot() {
    return state.operationalExpansion || (state.operationalStatus && state.operationalStatus.operational_intelligence_expansion) || {};
  }

  function getOperationalDecisionRecommendations() {
    const expansion = getOperationalExpansionSnapshot();
    const decisionRecommendations = ((expansion.operational_decision_intelligence || {}).recommendations || []).map((item) => Object.assign({ recommendation_family: "decision" }, item));
    const coordinationRecommendations = ((expansion.multi_agent_operational_coordination || {}).recommendations || []).map((item) => Object.assign({ recommendation_family: "coordination" }, item));
    const dispatchRecommendations = ((expansion.dispatch_intelligence || {}).recommendations || []).map((item) => Object.assign({ recommendation_family: "dispatch" }, item));
    return dispatchRecommendations.concat(decisionRecommendations, coordinationRecommendations);
  }

  function getOperationalMemorySnapshot() {
    const expansion = getOperationalExpansionSnapshot();
    return expansion.operational_memory_fabric || state.operationalMemorySnapshot || null;
  }

  function getNovaAssistanceRecommendations() {
    return Array.isArray(state.novaAssistanceRecommendations) ? state.novaAssistanceRecommendations : [];
  }

  function getNovaLiveEvents() {
    return Array.isArray(state.novaLiveEvents) ? state.novaLiveEvents : [];
  }

  function summarizeNovaContinuity() {
    const brief = state.novaContinuityBrief || {};
    const focus = Array.isArray(brief.strategic_focus) ? brief.strategic_focus : [];
    const actions = Array.isArray(brief.next_actions) ? brief.next_actions : [];
    const risks = Array.isArray(brief.unresolved_operational_risks) ? brief.unresolved_operational_risks : [];
    if (actions.length) return String(actions[0]);
    if (focus.length) return String(focus[0]);
    if (risks.length) return String(risks[0]);
    return "Continuity signals are syncing from operational memory.";
  }

  function mapNovaRecommendation(recommendation, surface) {
    const rec = recommendation && typeof recommendation === "object" ? recommendation : {};
    const targetSurface = String((rec.impacted_surface || rec.category || "")).toLowerCase();
    if (surface && targetSurface && targetSurface.indexOf(String(surface).toLowerCase()) === -1 && targetSurface !== "operational_summaries") {
      return null;
    }
    const reason = firstDefined(rec.reason, rec.summary, rec.suggested_action, "Operational recommendation");
    const action = firstDefined(rec.suggested_action, rec.summary, "Review recommendation");
    return {
      title: firstDefined(rec.title, rec.category, "AI recommendation"),
      action_type: firstDefined(rec.category, "operational"),
      recommendation_type: firstDefined(rec.category, "operational"),
      impacted_surface: firstDefined(rec.impacted_surface, surface || "Operational shell"),
      operational_risk: firstDefined(rec.operational_risk, rec.priority, "low"),
      confidence: Number(firstDefined(rec.confidence, 0) || 0),
      approval_required: !!rec.approval_required,
      execution_mode: firstDefined(rec.execution_mode, "recommendation_only"),
      synchronization_impact: firstDefined(rec.synchronization_impact, "replay-safe"),
      reasoning: String(reason || "Operational recommendation"),
      summary: String(action || "Review recommendation"),
      impact: firstDefined(rec.impact, rec.operational_risk, "medium"),
      urgency: firstDefined(rec.urgency, rec.priority, "medium"),
      related_event_ids: Array.isArray(rec.related_event_ids) ? rec.related_event_ids.slice(0, 8) : [],
      timestamp: firstDefined(rec.timestamp, stampNow()),
      category: firstDefined(rec.category, "operational"),
      source: "nova",
    };
  }

  function getUnifiedOperationalRecommendations(surface, limit) {
    const targetSurface = surface || "";
    const local = getOperationalDecisionRecommendations().map(function (item) {
      const mapped = Object.assign({}, item || {});
      mapped.source = firstDefined(mapped.source, "health_isf");
      mapped.timestamp = firstDefined(mapped.timestamp, stampNow());
      return mapped;
    });
    const nova = getNovaAssistanceRecommendations()
      .map(function (item) { return mapNovaRecommendation(item, targetSurface); })
      .filter(function (item) { return !!item; });
    const live = getNovaLiveEvents().map(function (evt) {
      const eventType = firstDefined(evt && evt.event_type, "operational_event");
      const severity = firstDefined(evt && evt.severity, "medium");
      return {
        title: firstDefined(evt && evt.summary, eventType),
        action_type: "operational",
        recommendation_type: "operational",
        impacted_surface: firstDefined(evt && evt.impacted_surface, targetSurface || "Operational shell"),
        operational_risk: severity,
        confidence: Number(firstDefined(evt && evt.confidence, 0.8) || 0.8),
        approval_required: severity === "critical" || severity === "high",
        execution_mode: "recommendation_only",
        synchronization_impact: "replay-safe",
        reasoning: firstDefined(evt && evt.summary, "Operational event detected"),
        summary: firstDefined(evt && evt.recommended_action, "Review live event"),
        impact: severity === "critical" || severity === "high" ? "high" : severity,
        urgency: severity,
        related_event_ids: evt && evt.event_id ? [String(evt.event_id)] : [],
        timestamp: firstDefined(evt && evt.detected_at, stampNow()),
        category: "operational",
        source: "nova_live",
      };
    });
    const merged = live.concat(nova).concat(local);
    return merged.slice(0, Math.max(1, Number(limit || 8)));
  }

  function buildNovaMemoryReferences(fabric) {
    const memory = fabric && typeof fabric === "object" ? fabric : {};
    const refs = [];
    const unresolved = Array.isArray(memory.unresolved_priorities) ? memory.unresolved_priorities : [];
    const opRisks = Array.isArray(memory.operational_risks) ? memory.operational_risks : [];
    const recentExec = Array.isArray(memory.recent_execution_history) ? memory.recent_execution_history : [];
    const recommendationHistory = Array.isArray(memory.recommendation_history) ? memory.recommendation_history : [];

    unresolved.slice(0, 5).forEach(function (item) {
      refs.push({
        title: "Unresolved priority",
        summary: String(item || ""),
        stream: "founder_continuity",
        severity: "warn",
        replay_safe: true,
        timestamp: memory.updated_at || stampNow(),
      });
    });

    opRisks.slice(0, 8).forEach(function (item) {
      refs.push({
        title: "Operational risk",
        summary: firstDefined(item && item.summary, "Risk tracked in memory fabric"),
        stream: "operational_risks",
        severity: firstDefined(item && item.severity, "warn"),
        replay_safe: true,
        timestamp: firstDefined(item && item.at, memory.updated_at, stampNow()),
      });
    });

    recentExec.slice(0, 8).forEach(function (item) {
      refs.push({
        title: firstDefined(item && item.event_type, "execution"),
        summary: firstDefined(item && item.summary, "Execution event"),
        stream: "recent_execution_history",
        severity: "info",
        replay_safe: true,
        timestamp: firstDefined(item && item.at, memory.updated_at, stampNow()),
      });
    });

    recommendationHistory.slice(0, 8).forEach(function (item) {
      refs.push({
        title: firstDefined(item && item.category, "recommendation"),
        summary: firstDefined(item && item.suggested_action, item && item.summary, "Recommendation captured"),
        stream: "recommendation_history",
        severity: firstDefined(item && item.priority, "info"),
        replay_safe: true,
        timestamp: firstDefined(item && item.timestamp, memory.updated_at, stampNow()),
      });
    });

    return refs;
  }

  function getWebsocketMetrics() {
    const ops = state.operationalStatus || {};
    const telemetry = ops.telemetry || {};
    const diagnostics = state.runtimeDiagnostics || {};
    const checkBundle = diagnostics.checks || {};
    const websocket = Object.assign({}, telemetry.websocket || {}, checkBundle.websocket || {});
    const queue = checkBundle.queue || {};
    const latency = checkBundle.latency || {};
    const metrics = Object.assign({}, telemetry.metrics || {}, {
      queue_depth_live: Number(queue.event_count || 0),
      failed_events_live: Number(queue.failed_events || 0),
      operational_latency_seconds: Number((latency.latency_ms || 0) / 1000),
    });
    const sync = ((getOperationalExpansionSnapshot().distributed_operational_event_fabric || {}).synchronization) || {};
    const replay = ((getOperationalExpansionSnapshot().distributed_operational_event_fabric || {}).replay_integrity) || {};
    return { websocket, metrics, sync, replay };
  }

  function getGovernanceSnapshot() {
    const ops = state.operationalStatus || {};
    const expansion = getOperationalExpansionSnapshot();
    return state.governanceStatus || expansion.human_oversight_intelligence || ops.governance_status || null;
  }

  function operational_event_card(event) {
    const sev = String(event.severity || 'info').toLowerCase();
    const sevIcon = { critical: '🔴', high: '🟠', medium: '🟡', warn: '🟡', info: '🔵', low: '⚪' }[sev] || '🔵';
    const timeStr = event.timestamp ? formatDateShort(event.timestamp) : '';
    return [
      '<article class="op-event-card sev-' + escapeHtml(sev) + '">',
      '<span class="op-event-icon">' + sevIcon + '</span>',
      '<div class="op-event-body">',
      '<div class="op-event-title">' + escapeHtml(event.eventType || 'operational_event') + '</div>',
      '<div class="op-event-summary">' + escapeHtml(event.summary || 'Operational event') + '</div>',
      '</div>',
      '<div class="op-event-meta">',
      '<span class="op-event-time">' + escapeHtml(timeStr) + '</span>',
      '<span class="op-event-sev ' + escapeHtml(sev) + '">' + escapeHtml(sev) + '</span>',
      '</div>',
      '</article>',
    ].join('');
  }

  function realtime_event_stream(items, emptyText) {
    if (!Array.isArray(items) || !items.length) {
      return op_empty_state(emptyText || 'Operational feed initializing — realtime events will appear here', '📡');
    }
    return '<div class="op-event-feed">' + items.map(operational_event_card).join('') + '</div>';
  }

  function operational_event_feed(items, emptyText) {
    return realtime_event_stream(items, emptyText);
  }

  /* ── Phase 5C helpers ──────────────────────────────────────── */
  function op_empty_state(label, icon) {
    return [
      '<div class="op-empty-state">',
      '<div class="op-empty-icon">' + (icon || '◌') + '</div>',
      '<div class="op-empty-label">' + escapeHtml(label || 'No data available') + '</div>',
      '<div class="op-empty-sub">Live data will appear as systems connect</div>',
      '</div>',
    ].join('');
  }

  function hc_section(title, body, opts) {
    const collapsed = opts && opts.collapsed;
    const badge = opts && opts.badge ? '<span class="hc-badge' + (opts.badgeTone ? ' ' + opts.badgeTone : '') + '">' + escapeHtml(opts.badge) + '</span>' : '';
    const pulse = opts && opts.pulse !== false ? '<span class="hc-pulse' + (opts.pulseTone ? ' ' + opts.pulseTone : '') + '"></span>' : '';
    const id = 'hcs-' + Math.random().toString(36).slice(2, 9);
    return [
      '<div class="hc-section' + (collapsed ? '' : ' open') + '" id="' + id + '">',
      '<button class="hc-toggle" data-hc-id="' + id + '" type="button">',
      '<span class="hc-toggle-label">' + pulse + escapeHtml(title) + badge + '</span>',
      '<span class="hc-chevron">▶</span>',
      '</button>',
      '<div class="hc-body">' + body + '</div>',
      '</div>',
    ].join('');
  }

  function operational_activity_timeline(items, emptyText) {
    if (!Array.isArray(items) || !items.length) {
      return '<p class="health-summary">' + escapeHtml(emptyText || 'No activity timeline available.') + '</p>';
    }
    return '<ul class="health-timeline-feed operational-activity-timeline">' + items.map((item) => {
      return '<li><span class="health-pill ' + operationalTone(item.severity) + '">' + escapeHtml(item.eventType || 'event') + '</span><strong>' + escapeHtml(item.summary || 'Operational activity') + '</strong><small>' + escapeHtml(formatDateShort(item.timestamp)) + '</small></li>';
    }).join('') + '</ul>';
  }

  function recommendation_confidence_meter(value) {
    const numeric = Number(value || 0);
    const score = clampPercent(numeric <= 1 ? numeric * 100 : numeric);
    return '<div class="health-confidence-meter"><div class="health-confidence-meter-bar"><span style="width:' + score + '%"></span></div><small>' + escapeHtml(score.toFixed(1) + '% confidence') + '</small></div>';
  }

  function operational_reasoning_view(recommendation) {
    const reasoning = recommendation.reasoning || recommendation.explanation || recommendation.explanation_summary || recommendation.reasoning_summary || recommendation.summary || 'No reasoning provided.';
    return '<p class="health-summary operational-reasoning-view">' + escapeHtml(reasoning) + '</p>';
  }

  function recommendation_approval_status(recommendation) {
    if (recommendation.approved || String(recommendation.status || '').toLowerCase() === 'approved') {
      return '<span class="health-op-badge live">Approved</span>';
    }
    if (recommendation.approval_required === false || String(recommendation.execution_mode || '').toLowerCase() === 'recommendation_only') {
      return '<span class="health-op-badge live">Recommendation only</span>';
    }
    return '<span class="health-op-badge warn">Approval required</span>';
  }

  function explainable_ai_card(recommendation) {
    const confidence = Number(firstDefined(recommendation.confidence, recommendation.priority_score, 0) || 0);
    const approvalRequired = recommendation.approval_required !== false && recommendation.execution_mode !== 'recommendation_only';
    const impactedSurface = String(firstDefined(recommendation.impacted_surface, recommendation.surface, recommendation.target_surface, recommendation.recommendation_family, 'Operational shell') || 'Operational shell');
    const riskLevel = String(firstDefined(recommendation.operational_risk, recommendation.risk_level, recommendation.risk, approvalRequired ? 'medium' : 'low') || 'low');
    return [
      '<article class="health-stack-item accent explainable-ai-card">',
      '<div class="health-stack-title-row"><strong>' + escapeHtml(recommendation.title || recommendation.action_type || recommendation.recommendation_type || 'AI recommendation') + '</strong><span class="health-op-badge ' + operationalTone(riskLevel) + '">' + escapeHtml(riskLevel) + '</span></div>',
      operational_reasoning_view(recommendation),
      recommendation_confidence_meter(confidence),
      '<div class="health-event-meta">',
      '<span class="health-op-badge live">' + escapeHtml(impactedSurface) + '</span>',
      recommendation_approval_status(recommendation),
      '<span class="health-op-badge ' + (String(recommendation.synchronization_impact || recommendation.replay_safe || '').toLowerCase().indexOf('safe') !== -1 ? 'live' : 'warn') + '">' + escapeHtml(String(recommendation.synchronization_impact || recommendation.replay_safe || 'replay-safe')) + '</span>',
      '</div>',
      '</article>',
    ].join('');
  }

  function operational_recommendation_panel(items, emptyText) {
    if (!Array.isArray(items) || !items.length) {
      return op_empty_state(emptyText || 'AI operational analysis preparing...', '🧠');
    }
    return '<div class="health-stack-list operational-recommendation-panel">' + items.map(explainable_ai_card).join('') + '</div>';
  }

  function operational_memory_reference_card(reference) {
    const title = firstDefined(reference.title, reference.reason, reference.category, reference.stream, 'Memory reference');
    const summary = firstDefined(reference.summary, reference.note, reference.explanation, reference.message, 'Replay-safe operational memory reference.');
    const source = firstDefined(reference.stream, reference.source, reference.kind, 'memory');
    const confidence = Number(firstDefined(reference.confidence, 0) || 0);
    return [
      '<article class="health-stack-item operational-memory-reference-card">',
      '<div class="health-stack-title-row"><strong>' + escapeHtml(title) + '</strong><span class="health-op-badge live">' + escapeHtml(source) + '</span></div>',
      '<p>' + escapeHtml(summary) + '</p>',
      '<div class="health-event-meta">',
      '<span class="health-op-badge live">' + escapeHtml(reference.replay_safe !== false ? 'replay-safe' : 'review') + '</span>',
      '<span class="health-op-badge ' + operationalTone(reference.severity || 'info') + '">' + escapeHtml(reference.severity || 'info') + '</span>',
      '<span class="health-op-badge live">' + escapeHtml(confidence ? Number(confidence).toFixed(2) : 'n/a') + '</span>',
      '</div>',
      '<small>' + escapeHtml(formatDateShort(reference.timestamp || reference.created_at || reference.generated_at)) + '</small>',
      '</article>',
    ].join('');
  }

  function replay_safe_history_timeline(items, emptyText) {
    if (!Array.isArray(items) || !items.length) {
      return '<p class="health-summary">' + escapeHtml(emptyText || 'No replay-safe history available.') + '</p>';
    }
    return '<ul class="health-timeline-feed replay-safe-history-timeline">' + items.map((item) => {
      return '<li><span class="health-pill ' + operationalTone(item.severity || 'info') + '">' + escapeHtml(item.title || item.type || 'memory') + '</span><strong>' + escapeHtml(item.summary || item.reason || 'Replay-safe memory reference') + '</strong><small>' + escapeHtml(formatDateShort(item.timestamp || item.created_at || item.generated_at)) + '</small></li>';
    }).join('') + '</ul>';
  }

  function operational_memory_panel(memorySnapshot, references, emptyText) {
    if (!memorySnapshot) {
      return op_empty_state(emptyText || 'Awaiting memory fabric synchronization', '🧩');
    }
    const patternSummary = memorySnapshot.pattern_summary || {};
    const recallSummary = memorySnapshot.recall_summary || {};
    const incidentMemory = Array.isArray(memorySnapshot.incident_history_memory) ? memorySnapshot.incident_history_memory : [];
    const escalationMemory = Array.isArray(memorySnapshot.escalation_pattern_memory) ? memorySnapshot.escalation_pattern_memory : [];
    const providerMemory = Array.isArray(memorySnapshot.provider_continuity_history) ? memorySnapshot.provider_continuity_history : [];
    const driverMemory = Array.isArray(memorySnapshot.driver_operational_trend_memory) ? memorySnapshot.driver_operational_trend_memory : [];
    const congestionMemory = Array.isArray(memorySnapshot.operational_congestion_history) ? memorySnapshot.operational_congestion_history : [];
    const learningMemory = Array.isArray(memorySnapshot.regional_operational_learning) ? memorySnapshot.regional_operational_learning : [];
    const topRefs = (references || []).slice(0, 6);
    return [
      '<div class="health-stack-list operational-memory-panel">',
      '<article class="health-stack-item accent">',
      '<div class="health-stack-title-row"><strong>Operational memory fabric</strong><span class="health-op-badge live">' + escapeHtml(memorySnapshot.replay_safe ? 'replay-safe' : 'watch') + '</span></div>',
      '<p>' + escapeHtml('Backend-authoritative memory references ' + formatNumber(patternSummary.total_memory_references || 0) + ' historical anchors with ' + formatNumber(recallSummary.recent_recall_count || 0) + ' replay-safe recall hits.') + '</p>',
      '<div class="health-event-meta">',
      '<span class="health-op-badge live">Incidents ' + escapeHtml(formatNumber(incidentMemory.length)) + '</span>',
      '<span class="health-op-badge live">Escalations ' + escapeHtml(formatNumber(escalationMemory.length)) + '</span>',
      '<span class="health-op-badge live">Providers ' + escapeHtml(formatNumber(providerMemory.length)) + '</span>',
      '<span class="health-op-badge live">Drivers ' + escapeHtml(formatNumber(driverMemory.length)) + '</span>',
      '<span class="health-op-badge live">Congestion ' + escapeHtml(formatNumber(congestionMemory.length)) + '</span>',
      '<span class="health-op-badge live">Learning ' + escapeHtml(formatNumber(learningMemory.length)) + '</span>',
      '</div>',
      '</article>',
      operational_memory_reference_card({
        title: 'Pattern summary',
        summary: patternSummary.replay_safe_summary || patternSummary.summary || 'Pattern summary available from backend memory.',
        stream: 'pattern_summary',
        timestamp: memorySnapshot.generated_at,
        severity: 'info',
        replay_safe: memorySnapshot.replay_safe,
      }),
      operational_memory_reference_card({
        title: 'Recall summary',
        summary: recallSummary.replay_safe_operational_recall ? 'Replay-safe operational recall enabled.' : (recallSummary.summary || 'Operational recall available.'),
        stream: 'recall_summary',
        timestamp: memorySnapshot.generated_at,
        severity: 'info',
        replay_safe: recallSummary.replay_safe_operational_recall !== false,
      }),
      topRefs.map(operational_memory_reference_card).join(''),
      '</div>',
      '<h4 style="margin:12px 0 8px;">Replay-safe history</h4>',
      replay_safe_history_timeline(topRefs, 'No memory references yet.'),
    ].join('');
  }

  function realtime_connection_status(websocket) {
    const status = String(state.websocketStatus || 'idle');
    const tone = status === 'connected' ? 'live' : (status === 'auth_required' || status === 'error' ? 'danger' : 'warn');
    return '<div class="health-status-chip"><span class="health-op-badge ' + tone + '">' + escapeHtml(status) + '</span></div>';
  }

  function operational_stream_metrics(metrics, websocket, sync, replay) {
    return '<div class="enterprise-inline-grid">'
      + MetricCard('Websocket state', state.websocketStatus, 'Realtime connection status', state.websocketStatus === 'connected' ? 'ok' : 'warn')
      + MetricCard('Reconnect attempts', formatNumber(state.reconnectAttempt), 'Replay-safe reconnect attempts', state.reconnectAttempt ? 'warn' : 'ok')
      + MetricCard('Active sessions', formatNumber(websocket.active_connections || websocket.active_connections_count || 0), 'Tenant-scoped websocket sessions', websocket.active_connections || websocket.active_connections_count ? 'ok' : 'warn')
      + MetricCard('Event throughput', formatNumber(metrics.dispatch_throughput_per_minute || metrics.websocket_event_throughput || 0), 'Operational stream volume per minute', 'ok')
      + MetricCard('Operational latency', Number(metrics.average_assignment_time_seconds || metrics.operational_latency_seconds || 0).toFixed(1) + ' s', 'Backend-authoritative latency visibility', 'warn')
      + MetricCard('Synchronization', sync.replay_safe ? 'replay-safe' : 'watch', 'Continuity and synchronization health', sync.replay_safe ? 'ok' : 'warn')
      + MetricCard('Replay integrity', replay.replay_safe ? 'replay-safe' : 'watch', 'Replay-safe websocket reconnect status', replay.replay_safe ? 'ok' : 'warn')
      + '</div>';
  }

  function websocket_runtime_monitor(metrics, websocket, sync, replay) {
    return [
      '<div class="health-stack-list websocket-runtime-monitor">',
      '<article class="health-stack-item accent">',
      '<div class="health-stack-title-row"><strong>Websocket runtime</strong>' + realtime_connection_status(websocket) + '</div>',
      '<p>' + escapeHtml('Reconnect attempts ' + formatNumber(state.reconnectAttempt) + ' · continuity ' + (sync.replay_safe ? 'safe' : 'watch') + ' · stream latency ' + Number(metrics.average_assignment_time_seconds || metrics.operational_latency_seconds || 0).toFixed(1) + ' s') + '</p>',
      '<div class="health-event-meta">',
      '<span class="health-op-badge live">Active ' + escapeHtml(formatNumber(websocket.active_connections || websocket.active_connections_count || 0)) + '</span>',
      '<span class="health-op-badge ' + (websocket.disconnects_last_5m ? 'warn' : 'live') + '">Disconnects 5m ' + escapeHtml(formatNumber(websocket.disconnects_last_5m || 0)) + '</span>',
      '<span class="health-op-badge live">Event seq ' + escapeHtml(formatNumber(sync.latest_sequence || ((sync.event_bus || {}).latest_sequence || 0))) + '</span>',
      '<span class="health-op-badge ' + (replay.replay_safe ? 'live' : 'warn') + '">Replay ' + escapeHtml(replay.replay_safe ? 'safe' : 'watch') + '</span>',
      '</div>',
      '</article>',
      operational_stream_metrics(metrics, websocket, sync, replay),
      '</div>',
    ].join('');
  }

  function synchronization_health_panel(sync, replay) {
    const eventBus = sync.event_bus || {};
    const status = String(sync.status || eventBus.status || 'healthy').toLowerCase();
    return [
      '<div class="health-stack-list synchronization-health-panel">',
      '<article class="health-stack-item">',
      '<div class="health-stack-title-row"><strong>Synchronization health</strong><span class="health-op-badge ' + operationalTone(status) + '">' + escapeHtml(status) + '</span></div>',
      '<p>' + escapeHtml('Event bus sequence ' + formatNumber(eventBus.latest_sequence || 0) + ' · continuity ' + (sync.replay_safe ? 'replay-safe' : 'review') + ' · reconnect ' + (sync.reconnect_safe ? 'safe' : 'watch')) + '</p>',
      '<div class="health-event-meta">',
      '<span class="health-op-badge live">Tenant ' + escapeHtml(sync.tenant_scoped !== false ? 'scoped' : 'mixed') + '</span>',
      '<span class="health-op-badge live">Backend authoritative</span>',
      '<span class="health-op-badge ' + (replay.replay_safe ? 'live' : 'warn') + '">Replay integrity ' + escapeHtml(replay.replay_safe ? 'safe' : 'watch') + '</span>',
      '</div>',
      '</article>',
      '</div>',
    ].join('');
  }

  function governance_enforcement_view(status) {
    if (!status) {
      return '<p class="health-summary">Governance status unavailable.</p>';
    }
    return [
      '<div class="health-stack-list governance-enforcement-view">',
      '<article class="health-stack-item accent">',
      '<div class="health-stack-title-row"><strong>Governance enforcement</strong><span class="health-op-badge live">backend-authoritative</span></div>',
      '<p>' + escapeHtml('Approval required ' + String(status.approval_required) + ' · rollback required ' + String(status.rollback_required) + ' · tenant scoped ' + String(status.tenant_scoped)) + '</p>',
      '<div class="health-event-meta">',
      '<span class="health-op-badge live">Audits ' + escapeHtml(formatNumber(status.audit_count || 0)) + '</span>',
      '<span class="health-op-badge live">Approvals ' + escapeHtml(formatNumber(status.approval_count || 0)) + '</span>',
      '<span class="health-op-badge live">Reasoning ' + escapeHtml(formatNumber(status.reasoning_count || 0)) + '</span>',
      '<span class="health-op-badge live">Predictions ' + escapeHtml(formatNumber(status.prediction_count || 0)) + '</span>',
      '<span class="health-op-badge live">Executions ' + escapeHtml(formatNumber(status.execution_count || 0)) + '</span>',
      '</div>',
      '</article>',
      '</div>',
    ].join('');
  }

  function audit_visibility_feed(items, emptyText) {
    if (!Array.isArray(items) || !items.length) {
      return '<p class="health-summary">' + escapeHtml(emptyText || 'No audit records available.') + '</p>';
    }
    return '<div class="health-stack-list audit-visibility-feed">' + items.map((item) => {
      return [
        '<article class="health-stack-item">',
        '<div class="health-stack-title-row"><strong>' + escapeHtml(item.event_type || item.action_type || 'audit_event') + '</strong><span class="health-op-badge live">audit</span></div>',
        '<p>' + escapeHtml(item.summary || item.action_type || item.reasoning || item.summary_text || 'Governance audit record') + '</p>',
        '<small>' + escapeHtml(formatDateShort(item.created_at || item.approval_timestamp || item.updated_at || item.timestamp)) + '</small>',
        '</article>',
      ].join('');
    }).join('') + '</div>';
  }

  function operational_approval_queue(items, emptyText) {
    if (!Array.isArray(items) || !items.length) {
      return '<p class="health-summary">' + escapeHtml(emptyText || 'No approvals awaiting action.') + '</p>';
    }
    return '<div class="health-stack-list operational-approval-queue">' + items.map((approval) => {
      const tone = approval.approved_by ? 'live' : 'warn';
      const payload = approval.action_payload && typeof approval.action_payload === "object" ? approval.action_payload : {};
      const payloadSummary = firstDefined(payload.summary, payload.reasoning, payload.message, approval.tenant_scope, 'Governance approval review');
      return [
        '<article class="health-stack-item">',
        '<div class="health-stack-title-row"><strong>' + escapeHtml(approval.action_type || 'Approval') + '</strong><span class="health-op-badge ' + tone + '">' + escapeHtml(approval.status || (approval.approved_by ? 'approved' : 'pending')) + '</span></div>',
        '<p>' + escapeHtml(payloadSummary) + '</p>',
        '<div class="health-event-meta">',
        '<span class="health-op-badge ' + (approval.approval_required ? 'warn' : 'live') + '">' + escapeHtml(approval.approval_required ? 'approval required' : 'advisory') + '</span>',
        '<span class="health-op-badge live">' + escapeHtml(approval.tenant_scope || 'tenant-scoped') + '</span>',
        '<span class="health-op-badge live">' + escapeHtml(Number(approval.confidence_score || 0).toFixed(2)) + '</span>',
        '</div>',
        '<small>' + escapeHtml(formatDateShort(approval.created_at || approval.updated_at || approval.approval_timestamp)) + '</small>',
        '</article>',
      ].join('');
    }).join('') + '</div>';
  }

  function governance_status_panel(status, approvals, audits) {
    return [
      '<div class="health-stack-list governance-status-panel">',
      '<article class="health-stack-item accent">',
      '<div class="health-stack-title-row"><strong>Governance status</strong><span class="health-op-badge live">tenant scoped</span></div>',
      '<p>' + escapeHtml('Approval threshold ' + Number(status && status.confidence_threshold || 0).toFixed(2) + ' · append-only audit ' + String(status && status.append_only_audit)) + '</p>',
      '</article>',
      '</div>',
      '<h4 style="margin:12px 0 8px;">Approval queue</h4>',
      operational_approval_queue(approvals, 'No approval queue items.'),
      '<h4 style="margin:12px 0 8px;">Audit visibility</h4>',
      audit_visibility_feed(audits, 'No audit visibility records.'),
    ].join('');
  }

  function hasActiveSession() {
    return !!(window.AmiCorSession
      && typeof window.AmiCorSession.isActive === "function"
      && window.AmiCorSession.isActive());
  }

  function getSessionProfile() {
    const previewOpsMode = /[?&](phase62verify|liveVerify)=1\b/.test(String(window.location && window.location.search || ""));

    if (window.AmiCorSession && typeof window.AmiCorSession.getSessionProfile === "function") {
      const profile = Object.assign({}, window.AmiCorSession.getSessionProfile());
      if (previewOpsMode && !profile.active && String(profile.role || "guest").toLowerCase() !== "guest") {
        profile.active = true;
        profile.accessTokenPresent = true;
        if (profile.tokenExpiresInMinutes === null || profile.tokenExpiresInMinutes === undefined) {
          profile.tokenExpiresInMinutes = 30;
        }
      }
      return profile;
    }

    const identity = window.AmiCorSession && typeof window.AmiCorSession.getCurrent === "function"
      ? (window.AmiCorSession.getCurrent() || {}).identity || null
      : null;
    const role = window.AmiCorSession && typeof window.AmiCorSession.getRole === "function"
      ? String(window.AmiCorSession.getRole() || "guest").toLowerCase()
      : "guest";

    const profile = {
      sessionId: null,
      active: hasActiveSession(),
      userId: identity && identity.userId ? String(identity.userId) : null,
      email: identity && identity.email ? String(identity.email) : null,
      displayName: identity && identity.name ? String(identity.name) : "Guest",
      role,
      organizationId: window.AmiCorSession && typeof window.AmiCorSession.getOrganizationId === "function"
        ? window.AmiCorSession.getOrganizationId()
        : null,
      organizationName: identity && identity.organizationName ? String(identity.organizationName) : null,
      accessTokenPresent: !!(window.AmiCorSession && typeof window.AmiCorSession.getAccessToken === "function" && window.AmiCorSession.getAccessToken()),
      refreshTokenPresent: !!(window.AmiCorSession && typeof window.AmiCorSession.getRefreshToken === "function" && window.AmiCorSession.getRefreshToken()),
      tokenExpiresAt: identity && identity.tokenExpiresAt ? Number(identity.tokenExpiresAt) : null,
      tokenExpiresInMinutes: null,
      runtimeHost: window.location && window.location.host ? String(window.location.host).toLowerCase() : "",
    };

    if (previewOpsMode && !profile.active && role !== "guest") {
      profile.active = true;
      profile.accessTokenPresent = true;
      profile.tokenExpiresInMinutes = 30;
    }

    return profile;
  }

  function getAllowedRoutesForRole(role) {
    return ROLE_ROUTE_ACCESS[String(role || "guest").toLowerCase()] || ROLE_ROUTE_ACCESS.guest;
  }

  function clampRouteForRole(route, role) {
    const target = VIEW_ROUTES.includes(route) ? route : PRIMARY_ROUTE;
    const allowed = getAllowedRoutesForRole(role);
    return allowed.indexOf(target) !== -1 ? target : allowed[0];
  }

  function injectShellStyles() {
    if (document.getElementById("amicor-health-shell-runtime-styles")) return;
    const style = document.createElement("style");
    style.id = "amicor-health-shell-runtime-styles";
    style.textContent = [
      ".health-isf-shell .health-isf-header{display:flex;flex-wrap:wrap;align-items:flex-start;gap:12px}",
      ".health-shell-session{display:flex;flex-wrap:wrap;gap:8px;align-items:center;margin-top:10px}",
      ".health-shell-chip{display:inline-flex;align-items:center;gap:6px;padding:6px 10px;border-radius:999px;border:1px solid rgba(255,255,255,0.12);background:rgba(255,255,255,0.04);color:var(--text);font-size:0.74rem;font-weight:700;letter-spacing:0.01em}",
      ".health-shell-chip[data-tone=ok]{border-color:rgba(100,220,180,0.35);color:#97ffd9}",
      ".health-shell-chip[data-tone=warn]{border-color:rgba(255,182,74,0.35);color:#ffd28a}",
      ".health-shell-chip[data-tone=danger]{border-color:rgba(255,108,108,0.35);color:#ffb1b1}",
      ".health-shell-auth-gate{display:flex;flex-direction:column;gap:14px;margin:16px 0 4px;padding:18px;border-radius:18px;border:1px solid rgba(255,255,255,0.08);background:linear-gradient(135deg, rgba(13,16,24,0.96), rgba(21,28,40,0.96));box-shadow:0 18px 36px rgba(0,0,0,0.26)}",
      ".health-shell-auth-gate h3{margin:0;font-size:1.1rem}",
      ".health-shell-auth-gate p{margin:0;color:var(--text-dim);line-height:1.5}",
      ".health-shell-auth-actions{display:flex;flex-wrap:wrap;gap:10px}",
      ".health-shell-auth-actions .toolbar-btn{min-width:0}",
      ".health-isf-shell[data-shell-mode=auth-gate] .health-isf-subnav,.health-isf-shell[data-shell-mode=auth-gate] .health-isf-grid{display:none !important}",
      ".health-runtime-shell{display:none !important}",
      ".health-isf-shell[data-diagnostics-visible=true] .health-runtime-shell{display:block !important}",
      ".health-tab.is-locked{opacity:0.42;filter:saturate(0.7);cursor:not-allowed}",
      ".health-shell-route-hint{font-size:0.76rem;color:var(--text-dim);margin-left:auto;max-width:100%}",
    ].join("\n");
    document.head.appendChild(style);
  }

  function ensureShellChrome() {
    const els = getEls();
    if (!els.shell) return;

    injectShellStyles();

    const header = els.shell.querySelector(".health-isf-header");
    const actions = els.shell.querySelector(".health-isf-actions");
    const tabs = els.shell.querySelector(".health-isf-subnav");

    if (header && !document.getElementById("health-shell-session")) {
      const sessionBar = document.createElement("div");
      sessionBar.id = "health-shell-session";
      sessionBar.className = "health-shell-session";
      sessionBar.setAttribute("aria-live", "polite");
      header.insertBefore(sessionBar, actions || null);
    }

    if (tabs && !document.getElementById("health-shell-auth-gate")) {
      const authGate = document.createElement("section");
      authGate.id = "health-shell-auth-gate";
      authGate.className = "health-shell-auth-gate";
      authGate.hidden = true;
      authGate.innerHTML = [
        '<div>',
        '<h3>Authenticate to enter the operational shell</h3>',
        '<p id="health-shell-auth-copy">Your live operations workspace is role-aware and requires an active session before route access or websocket attachment.</p>',
        '</div>',
        '<div class="health-shell-auth-actions">',
        '<button type="button" class="toolbar-btn" data-health-action="shell-login">Sign in</button>',
        '<button type="button" class="toolbar-btn" data-health-action="shell-signup">Create account</button>',
        '<button type="button" class="toolbar-btn" data-health-action="close">Exit operations shell</button>',
        '</div>',
        '<div id="health-shell-route-hint" class="health-shell-route-hint"></div>',
      ].join("");
      tabs.parentNode.insertBefore(authGate, tabs);
    }
  }

  function openAuthFlow(mode) {
    if (!window.AmiCorAuthUI) return;
    const targetRoute = state.pendingRoute || routeFromHash(window.location.hash) || PRIMARY_ROUTE;
    const completeAuth = (identity) => {
      if (window.AmiCorSession && typeof window.AmiCorSession.start === "function") {
        window.AmiCorSession.start(identity);
      }
      state.authGateVisible = false;
      state.pendingRoute = null;
      renderRuntimeShell("auth_success");
      navigate(clampRouteForRole(targetRoute, getSessionProfile().role), true);
    };

    const showLogin = () => window.AmiCorAuthUI.showLogin(completeAuth, showSignup);
    const showSignup = () => window.AmiCorAuthUI.showSignup(completeAuth, showLogin);

    if (mode === "signup") {
      showSignup();
    } else {
      showLogin();
    }
  }

  function renderRuntimeShell(reason) {
    const els = getEls();
    if (!els.shell) return;

    ensureShellChrome();
    incrementStabilityCounter("shellRenderCount", 1);

    const profile = getSessionProfile();
    const effectiveRole = getEffectiveShellRole(profile.role);
    const allowedRoutes = getAllowedRoutesForRole(effectiveRole);
    const shellMode = profile.active ? "operational" : "auth-gate";
    const developerMode = isDevelopmentPreviewMode();
    const diagnosticsVisible = developerMode || effectiveRole === "admin";
    state.shellProfile = Object.assign({}, profile, { effectiveRole: effectiveRole });
    state.authGateVisible = !profile.active;
    els.shell.dataset.shellMode = shellMode;
    els.shell.dataset.devPreview = developerMode ? "true" : "false";
    els.shell.dataset.diagnosticsVisible = diagnosticsVisible ? "true" : "false";

    const headerTitle = els.shell.querySelector(".health-isf-header h2");
    const headerCopy = els.shell.querySelector(".health-isf-header p");
    if (headerTitle) {
      headerTitle.textContent = profile.active ? "Health ISF Workspace" : "Authenticate to enter Health ISF Workspace";
    }
    if (headerCopy) {
      headerCopy.textContent = profile.active
        ? "Live dispatch queue, assignment controls, trip lifecycle management, and provider coordination inside Amicor Platform."
        : "Sign in to access Health ISF operational routes, dispatcher controls, and role-based workflows.";
    }

    const sessionBar = document.getElementById("health-shell-session");
    if (sessionBar) {
      incrementStabilityCounter("shellRenderReplacements", 1);
      const roleLabel = String(effectiveRole || "guest").replace(/^./, (m) => m.toUpperCase());
      const routeLabel = profile.active ? clampRouteForRole(state.route, effectiveRole) : "locked";
      const expiryLabel = profile.tokenExpiresInMinutes === null ? "no expiry" : profile.tokenExpiresInMinutes + " min";
      const notifications = (state.operationalEventFeed || []).filter(function (event) {
        const severity = String((event && (event.severity || event.alert_level || event.priority)) || "").toLowerCase();
        return severity === "urgent" || severity === "high" || severity === "critical";
      }).length;
      const roleOptions = Object.keys(ROLE_ROUTE_ACCESS).filter(function (role) {
        return role !== "guest";
      }).map(function (role) {
        const selected = effectiveRole === role ? " selected" : "";
        return '<option value="' + escapeHtml(role) + '"' + selected + '>' + escapeHtml(role) + '</option>';
      }).join("");
      sessionBar.innerHTML = [
        '<span class="health-shell-chip" data-tone="' + (profile.active ? "ok" : "warn") + '">' + escapeHtml(profile.active ? (profile.displayName || "Authenticated user") : "Session required") + '</span>',
        '<span class="health-shell-chip">Organization: ' + escapeHtml(profile.organizationName || profile.organizationId || "tenant scoped") + '</span>',
        '<span class="health-shell-chip">Role: ' + escapeHtml(roleLabel) + '</span>',
        '<span class="health-shell-chip">Route: ' + escapeHtml(routeLabel) + '</span>',
        '<span class="health-shell-chip" data-tone="' + (notifications > 0 ? 'warn' : 'ok') + '">Notifications: ' + escapeHtml(String(notifications)) + '</span>',
        '<span class="health-shell-chip">Shift: ' + escapeHtml(profile.active ? 'active' : 'inactive') + '</span>',
        (diagnosticsVisible ? '<span class="health-shell-chip" data-tone="warn">Diagnostics Overlay</span>' : ''),
        '<span class="health-shell-chip">Token: ' + escapeHtml(profile.accessTokenPresent ? expiryLabel : "missing") + '</span>',
        '<label class="health-shell-chip">Workspace <select data-health-action="switch-role" id="health-shell-role-switch">' + roleOptions + '</select></label>',
        '<button type="button" class="toolbar-btn" data-health-action="clear-role-override">Use session role</button>',
        profile.active
          ? '<button type="button" class="toolbar-btn" data-health-action="logout">Sign out</button>'
          : '<button type="button" class="toolbar-btn" data-health-action="shell-login">Sign in</button>',
      ].join("");
    }

    const topbarOrg = document.getElementById("ops-topbar-org");
    const topbarRole = document.getElementById("ops-topbar-role");
    const topbarNotifications = document.getElementById("ops-topbar-notifications");
    const topbarShift = document.getElementById("ops-topbar-shift");
    if (topbarOrg) {
      topbarOrg.textContent = "Org: " + String(profile.organizationName || profile.organizationId || "tenant scoped");
    }
    if (topbarRole) {
      topbarRole.textContent = "Role: " + String(effectiveRole || "guest");
    }
    if (topbarNotifications) {
      const urgentCount = (state.operationalEventFeed || []).filter(function (event) {
        const severity = String((event && (event.severity || event.alert_level || event.priority)) || "").toLowerCase();
        return severity === "urgent" || severity === "high" || severity === "critical";
      }).length;
      topbarNotifications.textContent = "Notifications: " + String(urgentCount);
    }
    if (topbarShift) {
      topbarShift.textContent = "Shift: " + (profile.active ? "active" : "inactive");
    }

    const gate = document.getElementById("health-shell-auth-gate");
    if (gate) {
      gate.hidden = profile.active;
      const copy = document.getElementById("health-shell-auth-copy");
      const hint = document.getElementById("health-shell-route-hint");
      if (copy) {
        copy.textContent = profile.active
          ? ""
          : "You asked for " + (state.pendingRoute || state.route || PRIMARY_ROUTE) + ", but the route is guarded until a valid session is restored.";
      }
      if (hint) {
        hint.textContent = profile.active
          ? ""
          : "Allowed after sign-in: " + allowedRoutes.join(", ");
      }
    }

    els.tabs.forEach((tab) => {
      const route = String(tab.getAttribute("data-health-route") || "dashboard").toLowerCase();
      const allowed = allowedRoutes.indexOf(route) !== -1;
      tab.hidden = profile.active ? false : route !== PRIMARY_ROUTE;
      tab.disabled = profile.active ? false : !allowed;
      tab.classList.toggle("is-locked", profile.active ? !allowed : !allowed);
      tab.setAttribute("aria-disabled", profile.active ? (allowed ? "false" : "true") : (allowed ? "false" : "true"));
    });

    const roleSwitch = document.getElementById("health-shell-role-switch");
    if (roleSwitch) {
      roleSwitch.value = effectiveRole;
      roleSwitch.disabled = !profile.active;
    }

    els.views.forEach((view) => {
      view.hidden = !profile.active;
    });

    if (reason) {
      logDiag("Shell render", { reason, mode: shellMode, route: state.route, role: effectiveRole, allowedRoutes: allowedRoutes.slice() });
    }
  }

  function safeJson(response) {
    return response.json().catch(() => ({}));
  }

  function withOrganizationScope(path) {
    const original = String(path || "");
    const scopedPrefixes = ["/api/health-isf", "/api/enterprise", "/api/ai", "/api/nova"];
    const shouldScope = scopedPrefixes.some(function (prefix) {
      return original.startsWith(prefix);
    });
    if (!shouldScope) return original;
    if (/[?&]organization_id=/.test(original)) return original;

    const orgId = getOrganizationId();
    if (!orgId) return original;

    const joiner = original.indexOf("?") === -1 ? "?" : "&";
    return original + joiner + "organization_id=" + encodeURIComponent(String(orgId));
  }

  async function fetchJson(path, options) {
    state.pendingRequests += 1;
    state.lastApiError = null;
    const opts = Object.assign({}, options || {});
    const timeoutMs = Number.isFinite(Number(opts.timeoutMs)) ? Number(opts.timeoutMs) : API_REQUEST_TIMEOUT_MS;
    const actionName = opts.actionName ? String(opts.actionName) : "api_request";
    delete opts.timeoutMs;
    delete opts.actionName;
    const actionId = "hisf-" + actionName + "-" + Date.now() + "-" + Math.random().toString(36).slice(2, 8);
    const startedAt = Date.now();
    const controller = new AbortController();
    const timeout = setTimeout(function () {
      controller.abort("health_isf_request_timeout");
    }, timeoutMs);

    let res;
    const method = opts.method ? String(opts.method).toUpperCase() : "GET";
    const scopedPath = withOrganizationScope(path);
    try {
      const headers = Object.assign({}, opts.headers || {}, {
        "X-Client-Action-Id": actionId,
      });
      const requestOptions = Object.assign({}, opts, { headers: headers, signal: controller.signal });
      recordExecutionEvent({ stage: "started", actionName: actionName, actionId: actionId, path: scopedPath, method: method });
      if (window.AmiCorSession && typeof window.AmiCorSession.authFetch === "function") {
        res = await window.AmiCorSession.authFetch(scopedPath, requestOptions);
      } else {
        res = await fetch(scopedPath, requestOptions);
      }
      if (!res) {
        throw new Error("Network request failed — session may be expired");
      }
      const data = await safeJson(res);
      logDiag("API response", {
        path: scopedPath,
        method,
        status: res.status,
        ok: res.ok,
        keys: data && typeof data === "object" ? Object.keys(data).slice(0, 8) : [],
        sizeHint: Array.isArray(data) ? data.length : null,
      });
      if (!res.ok) {
        const message = data && data.detail ? data.detail : "Request failed";
        const normalized = normalizeApiError(message);
        state.lastApiError = normalized;
        throw new Error(normalized);
      }
      recordExecutionEvent({
        stage: "completed",
        actionName: actionName,
        actionId: actionId,
        path: scopedPath,
        method: method,
        status: res.status,
        durationMs: Date.now() - startedAt,
      });
      return data;
    } catch (error) {
      const normalized = normalizeApiError(error);
      state.lastApiError = normalized;
      recordExecutionEvent({
        stage: "failed",
        actionName: actionName,
        actionId: actionId,
        path: scopedPath,
        method: method,
        status: res && typeof res.status === "number" ? res.status : null,
        durationMs: Date.now() - startedAt,
        error: normalized,
      });
      throw new Error(normalized);
    } finally {
      clearTimeout(timeout);
      state.pendingRequests = Math.max(0, state.pendingRequests - 1);
    }
  }

  function getEls() {
    return {
      shell: document.getElementById("health-isf-shell"),
      frame: document.getElementById("conversation-frame"),
      statusBar: document.getElementById("status-bar"),
      inputWrap: document.getElementById("input-wrap"),
      searchResults: document.getElementById("conversation-search-results"),
      workflow: document.getElementById("workflow-center"),
      tabs: document.querySelectorAll(".health-tab[data-health-route]"),
      views: document.querySelectorAll("[data-health-view]"),
      navOpeners: document.querySelectorAll("[data-health-nav-open]"),
      actions: document.querySelectorAll("[data-health-action]"),
      modal: document.getElementById("health-create-ride-modal"),
      form: document.getElementById("health-create-ride-form"),
      createInlineError: document.getElementById("health-create-ride-inline-error"),
      createSubmit: document.querySelector("[data-health-create-submit]"),
      createSubmitLabel: document.querySelector("[data-create-label]"),
      providerSelect: document.getElementById("health-provider-select"),
      filterStatus: document.getElementById("health-filter-status"),
      filterProvider: document.getElementById("health-filter-provider"),
      filterDriver: document.getElementById("health-filter-driver"),
      filterPriority: document.getElementById("health-filter-priority"),
      filterQuery: document.getElementById("health-ride-search"),
      queuePending: document.getElementById("health-queue-pending"),
      queueActive: document.getElementById("health-queue-active"),
      queueCompleted: document.getElementById("health-queue-completed"),
      queueProblem: document.getElementById("health-queue-problem"),
      queuePendingCount: document.getElementById("health-queue-count-pending"),
      queueActiveCount: document.getElementById("health-queue-count-active"),
      queueCompletedCount: document.getElementById("health-queue-count-completed"),
      queueProblemCount: document.getElementById("health-queue-count-problem"),
      rideDetailsModal: document.getElementById("health-ride-details-modal"),
      rideDetailsContent: document.getElementById("health-ride-details-content"),
      dashboardCards: document.getElementById("health-dashboard-cards"),
      dispatchSummary: document.getElementById("health-dispatch-summary"),
      aiOpsCenter: document.getElementById("health-ai-ops-center"),
      aiRecommendations: document.getElementById("health-ai-recommendations"),
      aiAlerts: document.getElementById("health-ai-alerts"),
      aiNotifications: document.getElementById("health-ai-notifications"),
      aiTimeline: document.getElementById("health-ai-timeline"),
      aiTranscript: document.getElementById("health-ai-transcript"),
      voicePtt: document.getElementById("health-voice-ptt"),
      voiceStop: document.getElementById("health-voice-stop"),
      aiRefresh: document.getElementById("health-ai-refresh"),
      aiReplay: document.getElementById("health-ai-replay"),
      ridesTable: document.getElementById("health-rides-table"),
      driverCards: document.getElementById("health-drivers-cards"),
      providerCards: document.getElementById("health-providers-cards"),
      onboardingSeed: document.getElementById("health-onboarding-seed"),
      onboardingStatus: document.getElementById("health-onboarding-status"),
      onboardingForm: document.getElementById("health-driver-application-form"),
      onboardingSummary: document.getElementById("health-driver-applications-summary"),
      onboardingList: document.getElementById("health-driver-applications-list"),
      grantMetrics: document.getElementById("health-grant-metrics"),
      grantScreenshots: document.getElementById("health-grant-screenshots"),
      recurringTemplates: document.getElementById("health-recurring-templates"),
      rideMix: document.getElementById("health-analytics-ride-mix"),
      driverCapacity: document.getElementById("health-analytics-driver-capacity"),
      providerPerformance: document.getElementById("health-analytics-provider-performance"),
      operationalLoad: document.getElementById("health-analytics-operational-load"),
      aiAnalyticsRecommendations: document.getElementById("health-analytics-ai-recommendations"),
      emergencyStats: document.getElementById("health-analytics-emergency-stats"),
      dashboardOperationalFeed: document.getElementById("health-dashboard-operational-feed"),
      dashboardRecommendations: document.getElementById("health-dashboard-recommendations"),
      dashboardMemory: document.getElementById("health-dashboard-memory"),
      dashboardGovernance: document.getElementById("health-dashboard-governance"),
      dashboardWebsocket: document.getElementById("health-dashboard-websocket"),
      dashboardSync: document.getElementById("health-dashboard-sync"),
      driverOperationalFeed: document.getElementById("health-driver-operational-feed"),
      driverRecommendations: document.getElementById("health-driver-recommendations"),
      driverMemory: document.getElementById("health-driver-memory"),
      driverGovernance: document.getElementById("health-driver-governance"),
      driverWebsocket: document.getElementById("health-driver-websocket"),
      driverSync: document.getElementById("health-driver-sync"),
      providerOperationalFeed: document.getElementById("health-provider-operational-feed"),
      providerRecommendations: document.getElementById("health-provider-recommendations"),
      providerMemory: document.getElementById("health-provider-memory"),
      providerGovernance: document.getElementById("health-provider-governance"),
      providerWebsocket: document.getElementById("health-provider-websocket"),
      providerSync: document.getElementById("health-provider-sync"),
      analyticsOperationalFeed: document.getElementById("health-analytics-operational-feed"),
      analyticsRecommendations: document.getElementById("health-analytics-recommendations"),
      analyticsGovernance: document.getElementById("health-analytics-governance"),
      analyticsAudit: document.getElementById("health-analytics-audit"),
      analyticsMemory: document.getElementById("health-analytics-memory"),
      analyticsWebsocket: document.getElementById("health-analytics-websocket"),
      analyticsSync: document.getElementById("health-analytics-sync"),
      intakeVoice: document.getElementById("health-intake-voice"),
      intakeAssist: document.getElementById("health-intake-ai-assist"),
      intakeTranscript: document.getElementById("health-intake-transcript"),
      intakeAssistOutput: document.getElementById("health-intake-assist-output"),
      customerRequestForm: document.getElementById("health-customer-request-form"),
      customerQueueMetrics: document.getElementById("health-customer-queue-metrics"),
      requestActionId: document.getElementById("health-request-action-id"),
      requestDriverId: document.getElementById("health-request-driver-id"),
      requestApprove: document.getElementById("health-request-approve"),
      requestAutoDispatch: document.getElementById("health-request-auto-dispatch"),
      requestAssignDriver: document.getElementById("health-request-assign-driver"),
      requestReassign: document.getElementById("health-request-reassign"),
      requestCancel: document.getElementById("health-request-cancel"),
      requestComplete: document.getElementById("health-request-complete"),
      requestActionStatus: document.getElementById("health-request-action-status"),
      dispatchAutoAssign: document.getElementById("health-dispatch-auto-assign"),
      dispatchReassign: document.getElementById("health-dispatch-reassign"),
      dispatchRefreshIntel: document.getElementById("health-dispatch-refresh-intel"),
      dispatchIntelQueue: document.getElementById("health-dispatch-intel-queue"),
      dispatchActiveAssignments: document.getElementById("health-dispatch-active-assignments"),
      dispatchTimeline: document.getElementById("health-dispatch-timeline"),
      rideWorkflowProof: document.getElementById("health-ride-workflow-proof"),
      dispatchWorklist: document.getElementById("health-dispatch-worklist"),
      dispatchWorkflow: document.getElementById("health-dispatch-workflow"),
      dispatchAssignments: document.getElementById("health-dispatch-assignments"),
      driverAssignedRides: document.getElementById("health-driver-assigned-rides"),
      onboardingForm: document.getElementById("health-driver-application-form"),
      onboardingSeed: document.getElementById("health-onboarding-seed"),
      onboardingStatus: document.getElementById("health-onboarding-status"),
      onboardingSummary: document.getElementById("health-driver-applications-summary"),
      onboardingList: document.getElementById("health-driver-applications-list"),
      grantMetrics: document.getElementById("health-grant-metrics"),
      grantScreenshots: document.getElementById("health-grant-screenshots"),
      recurringTemplates: document.getElementById("health-recurring-templates"),
      driverRuntimeId: document.getElementById("health-driver-runtime-id"),
      driverRuntimePhone: document.getElementById("health-driver-runtime-phone"),
      driverRuntimeAvailability: document.getElementById("health-driver-runtime-availability"),
      driverRuntimeToken: document.getElementById("health-driver-runtime-token"),
      driverLogin: document.getElementById("health-driver-login"),
      driverLogout: document.getElementById("health-driver-logout"),
      driverSetAvailability: document.getElementById("health-driver-set-availability"),
      driverHeartbeat: document.getElementById("health-driver-heartbeat"),
      driverRefreshStatus: document.getElementById("health-driver-refresh-status"),
      driverRuntimeStatus: document.getElementById("health-driver-runtime-status"),
      driverIncomingOffer: document.getElementById("health-driver-incoming-offer"),
      driverOfferAccept: document.getElementById("health-driver-offer-accept"),
      driverOfferReject: document.getElementById("health-driver-offer-reject"),
      driverOfferRefresh: document.getElementById("health-driver-offer-refresh"),
      driverOfferStream: document.getElementById("health-driver-offer-stream"),
      driverAuthAssignment: document.getElementById("health-driver-auth-assignment"),
      driverAuthHistory: document.getElementById("health-driver-auth-history"),
      driverPoolMetrics: document.getElementById("health-driver-pool-metrics"),
      customerActiveRide: document.getElementById("health-customer-active-ride"),
      customerRequestHistory: document.getElementById("health-customer-request-history"),
      customerBookingManagement: document.getElementById("health-customer-booking-management"),
      customerAssignment: document.getElementById("health-customer-assignment"),
      customerSupport: document.getElementById("health-customer-support"),
      customerTimeline: document.getElementById("health-customer-timeline"),
      adminSummary: document.getElementById("health-admin-summary"),
      adminRoleSessions: document.getElementById("health-admin-role-sessions"),
      adminWebsocket: document.getElementById("health-admin-websocket"),
      adminRuntimeValidation: document.getElementById("health-admin-runtime-validation"),
      adminLifecycleAudit: document.getElementById("health-admin-lifecycle-audit"),
      billingKpis: document.getElementById("health-billing-kpis"),
      billingClaims: document.getElementById("health-billing-claims"),
      billingAging: document.getElementById("health-billing-aging"),
    };
  }

  function routeFromHash(hashValue) {
    const hash = String(hashValue || "").trim().toLowerCase();
    if (!hash.startsWith(HEALTH_HASH_PREFIX)) return null;
    const part = hash.slice(HEALTH_HASH_PREFIX.length).split(/[/?#]/)[0] || PRIMARY_ROUTE;
    return VIEW_ROUTES.includes(part) ? part : PRIMARY_ROUTE;
  }

  function setHash(route) {
    const target = HEALTH_HASH_PREFIX + route;
    if (window.location.hash !== target) {
      window.location.hash = target;
    }
  }

  function pillClass(status) {
    const value = String(status || "").toLowerCase();
    if (value === "available" || value === "completed" || value === "healthy") return "ok";
    if (value === "busy" || value === "assigned" || value === "accepted" || value === "pending" || value === "en_route_pickup" || value === "waiting_at_pickup" || value === "in_transit") return "warn";
    return "danger";
  }

  function formatNumber(value) {
    const num = Number(value || 0);
    return Number.isFinite(num) ? num.toLocaleString() : "0";
  }

  function card(label, value) {
    return '<article class="health-card"><div class="label">' + label + '</div><div class="value">' + value + "</div></article>";
  }

  function escapeHtml(input) {
    return String(input || "")
      .replace(/&/g, "&amp;")
      .replace(/</g, "&lt;")
      .replace(/>/g, "&gt;")
      .replace(/\"/g, "&quot;")
      .replace(/'/g, "&#39;");
  }

  function statusTone(status) {
    const value = String(status || "").toLowerCase();
    if (["healthy", "online", "available", "stable", "standby", "ready", "low", "ok", "on shift"].includes(value)) return "ok";
    if (["watch", "busy", "limited", "pending", "accepted", "in_transit", "critical_watch", "medium"].includes(value)) return "warn";
    return "danger";
  }

  function badgeTone(status) {
    const tone = statusTone(status);
    return tone === "ok" ? "live" : tone;
  }

  function clampPercent(value) {
    const num = Number(value || 0);
    if (!Number.isFinite(num)) return 0;
    return Math.max(0, Math.min(100, num));
  }

  function formatPercent(value) {
    return clampPercent(value).toFixed(1) + "%";
  }

  function toDateValue(value) {
    const dt = value ? new Date(value) : null;
    return dt && !Number.isNaN(dt.getTime()) ? dt : null;
  }

  function minutesBetween(startValue, endValue) {
    const start = toDateValue(startValue);
    const end = toDateValue(endValue) || new Date();
    if (!start || !end) return null;
    return Math.max(0, Math.round((end.getTime() - start.getTime()) / 60000));
  }

  function formatMinutesCompact(minutes) {
    const total = Number(minutes);
    if (!Number.isFinite(total)) return "-";
    if (total >= 120) return (total / 60).toFixed(1) + " hr";
    return Math.round(total) + " min";
  }

  function formatRelativeTime(value) {
    const dt = toDateValue(value);
    if (!dt) return "-";
    const minutes = Math.max(0, Math.round((Date.now() - dt.getTime()) / 60000));
    if (minutes < 1) return "just now";
    if (minutes < 60) return minutes + " min ago";
    const hours = Math.round(minutes / 60);
    if (hours < 24) return hours + " hr ago";
    const days = Math.round(hours / 24);
    return days + " day" + (days === 1 ? "" : "s") + " ago";
  }

  function deriveRideEtaMinutes(ride) {
    if (!ride) return null;
    const appointment = toDateValue(ride.appointment_time);
    if (appointment) {
      return Math.max(0, Math.round((appointment.getTime() - Date.now()) / 60000));
    }
    const estimated = Number(ride.estimated_duration_minutes || 0);
    if (!estimated) return null;
    const elapsed = minutesBetween(ride.requested_at, new Date().toISOString()) || 0;
    return Math.max(0, estimated - elapsed);
  }

  function MetricCard(label, value, detail, tone) {
    const variant = tone ? " enterprise-metric-card-" + tone : "";
    return [
      '<article class="health-card enterprise-metric-card' + variant + '">',
      '<div class="label">' + escapeHtml(label) + '</div>',
      '<div class="value">' + escapeHtml(String(value || "-")) + '</div>',
      '<p class="enterprise-metric-detail">' + escapeHtml(detail || "Live enterprise operations feed") + '</p>',
      '</article>',
    ].join("");
  }

  function StatusPill(label, tone) {
    const variant = tone || statusTone(label);
    return '<span class="health-pill ' + variant + '">' + escapeHtml(label || "unknown") + '</span>';
  }

  function SLABadge(value) {
    let label = "watch";
    let score = null;
    if (value && typeof value === "object") {
      label = String(value.status || "watch");
      score = Number(value.score);
    } else if (typeof value === "number") {
      score = value;
      label = value >= 85 ? "healthy" : value >= 65 ? "watch" : "critical";
    } else if (value) {
      label = String(value);
    }
    return '<span class="health-op-badge ' + badgeTone(label) + '">' + escapeHtml(label) + (Number.isFinite(score) ? ' · ' + Number(score).toFixed(1) + '%' : '') + '</span>';
  }

  function getEnterpriseAlerts() {
    if (state.enterpriseDashboard && Array.isArray(state.enterpriseDashboard.operational_alerts)) {
      return state.enterpriseDashboard.operational_alerts;
    }
    if (state.aiSnapshot && Array.isArray(state.aiSnapshot.alerts)) {
      return state.aiSnapshot.alerts;
    }
    return [];
  }

  function getEnterpriseRecommendations() {
    if (state.enterpriseDashboard && Array.isArray(state.enterpriseDashboard.ai_recommendations)) {
      return state.enterpriseDashboard.ai_recommendations;
    }
    if (state.aiSnapshot && state.aiSnapshot.recommendations && Array.isArray(state.aiSnapshot.recommendations.dispatcher_recommendation_payloads)) {
      return state.aiSnapshot.recommendations.dispatcher_recommendation_payloads;
    }
    return [];
  }

  function summarizeRideRisk(ride) {
    if (!ride) return "low";
    if (Boolean(ride.is_emergency) || ["emergency", "urgent", "high"].includes(getPriorityTag(ride))) return "high";
    if (isOverdueRide(ride) || (!ride.driver_id && String(ride.status || "").toLowerCase() === "pending")) return "medium";
    return "low";
  }

  function summarizeDriverAvailability(driver, activeAssignments) {
    const status = String(driver && driver.status || "").toLowerCase();
    if (["offline", "unavailable"].includes(status)) return "offline";
    if (activeAssignments >= 2 || ["busy", "in_transit", "en_route_pickup", "waiting_at_pickup"].includes(status)) return "limited";
    return "available";
  }

  function summarizeDriverShiftState(driver, activeAssignments) {
    const status = String(driver && driver.status || "").toLowerCase();
    if (!driver || driver.is_active === false || ["offline", "unavailable"].includes(status)) return "off shift";
    if (activeAssignments > 0) return "on route";
    return "on shift";
  }

  function getProviderRows() {
    const analytics = state.enterpriseDashboard && state.enterpriseDashboard.analytics ? state.enterpriseDashboard.analytics : (state.aiSnapshot && state.aiSnapshot.analytics ? state.aiSnapshot.analytics : {});
    const providerPerf = analytics.provider_performance || {};
    const leaderMap = {};
    (providerPerf.leaders || []).forEach(function (item) {
      leaderMap[String(item.provider_id || "")] = item;
    });
    const alerts = getEnterpriseAlerts();
    const rows = state.providers.map(function (provider) {
      const providerId = String(provider.id || "");
      const rides = state.rides.filter(function (ride) {
        return String(ride.provider_id || "") === providerId;
      });
      const activeRides = rides.filter(function (ride) {
        return ["pending", "accepted", "in_transit"].includes(String(ride.status || "").toLowerCase());
      });
      const queueSize = rides.filter(function (ride) {
        return ["pending", "accepted"].includes(String(ride.status || "").toLowerCase());
      }).length;
      const delayedCount = rides.filter(isOverdueRide).length;
      const activeDrivers = new Set(activeRides.map(function (ride) { return String(ride.driver_id || ""); }).filter(Boolean)).size;
      const leader = leaderMap[providerId] || {};
      const completed = Number(leader.completed || rides.filter(function (ride) { return String(ride.status || "").toLowerCase() === "completed"; }).length);
      const cancelled = Number(leader.cancelled || rides.filter(function (ride) { return String(ride.status || "").toLowerCase() === "cancelled"; }).length);
      const active = Number(leader.active || activeRides.length);
      const denominator = Math.max(active + completed + cancelled, 1);
      const sla = clampPercent(((completed + Math.max(0, active - cancelled)) / denominator) * 100);
      const responseSamples = rides.map(function (ride) {
        return minutesBetween(ride.requested_at, ride.accepted_at);
      }).filter(function (value) {
        return Number.isFinite(value);
      });
      const avgResponse = responseSamples.length
        ? responseSamples.reduce(function (sum, value) { return sum + Number(value || 0); }, 0) / responseSamples.length
        : null;
      const alertCount = alerts.filter(function (item) {
        return String(item.details && item.details.provider_id || "") === providerId;
      }).length + (queueSize >= 3 ? 1 : 0) + (delayedCount > 0 ? 1 : 0);
      const utilization = clampPercent((active / Math.max(activeDrivers || active || 1, 1)) * 48);
      const status = !provider.is_active ? "offline" : (alertCount > 0 || delayedCount > 0 || queueSize >= 3 ? "watch" : "online");
      return {
        id: providerId,
        name: provider.name || "Provider",
        serviceType: provider.service_type || "Network",
        status: status,
        activeDrivers: activeDrivers,
        sla: sla,
        queueSize: queueSize,
        utilization: utilization,
        alerts: alertCount,
        responseTimeMinutes: avgResponse,
        completed: completed,
        active: active,
        updatedAt: provider.updated_at,
      };
    }).sort(function (a, b) {
      return b.queueSize - a.queueSize || b.alerts - a.alerts || a.name.localeCompare(b.name);
    });

    if (rows.length) return rows;
    if (state.enterpriseDashboard) {
      const enterpriseMetrics = state.enterpriseDashboard.metrics || {};
      return [{
        id: "network-aggregate",
        name: "Network Aggregate",
        serviceType: "Fallback live summary",
        status: state.enterpriseDashboard.dispatch_health || "watch",
        activeDrivers: Number((state.enterpriseDashboard.utilization_metrics || {}).available_drivers || 0),
        sla: Number((state.enterpriseDashboard.sla_status || {}).score || 0),
        queueSize: Number(state.enterpriseDashboard.pending_rides || 0),
        utilization: Number((state.enterpriseDashboard.utilization_metrics || {}).driver_utilization_percent || 0),
        alerts: getEnterpriseAlerts().length,
        responseTimeMinutes: Number((state.enterpriseDashboard.metrics || {}).average_assignment_time_seconds || 0) / 60,
        completed: Number(enterpriseMetrics.completed_rides || state.enterpriseDashboard.completed_rides || 0),
        active: Number(state.enterpriseDashboard.active_rides || 0),
        updatedAt: state.enterpriseDashboard.last_synced_at,
      }];
    }
    return [];
  }

  function getDriverRows() {
    const analytics = state.enterpriseDashboard && state.enterpriseDashboard.analytics ? state.enterpriseDashboard.analytics : (state.aiSnapshot && state.aiSnapshot.analytics ? state.aiSnapshot.analytics : {});
    const driverEfficiency = analytics.driver_efficiency || {};
    const leaderMap = {};
    (driverEfficiency.leaders || []).forEach(function (item) {
      leaderMap[String(item.driver_id || "")] = item;
    });
    const rows = state.drivers.map(function (driver) {
      const driverId = String(driver.id || "");
      const assignedRides = state.rides.filter(function (ride) {
        return String(ride.driver_id || "") === driverId && ["accepted", "in_transit", "pending"].includes(String(ride.status || "").toLowerCase());
      });
      const leader = leaderMap[driverId] || {};
      const activeAssignments = assignedRides.length;
      const utilization = clampPercent(activeAssignments * 35 + (String(driver.status || "").toLowerCase() === "available" ? 15 : 30));
      const idleMinutes = String(driver.status || "").toLowerCase() === "available" ? minutesBetween(driver.updated_at, new Date().toISOString()) : null;
      const eta = assignedRides.length
        ? Math.min.apply(null, assignedRides.map(function (ride) { return deriveRideEtaMinutes(ride) || Number(ride.estimated_duration_minutes || 0) || 0; }).filter(Boolean))
        : null;
      const availability = summarizeDriverAvailability(driver, activeAssignments);
      return {
        id: driverId,
        name: driver.name || "Driver",
        status: String(driver.status || "unknown"),
        assignedRides: activeAssignments,
        idleMinutes: idleMinutes,
        etaMinutes: eta,
        utilization: leader.active ? clampPercent((Number(leader.active || 0) / Math.max(Number(leader.active || 0) + Number(leader.completed || 0), 1)) * 100) : utilization,
        availability: availability,
        shiftState: summarizeDriverShiftState(driver, activeAssignments),
        totalTrips: Number(driver.total_trips || 0),
        rating: Number(driver.rating || 0),
        updatedAt: driver.updated_at,
      };
    }).sort(function (a, b) {
      return b.assignedRides - a.assignedRides || a.name.localeCompare(b.name);
    });

    if (rows.length) return rows;
    if (state.enterpriseDashboard) {
      const enterpriseMetrics = state.enterpriseDashboard.metrics || {};
      return [{
        id: "driver-aggregate",
        name: "Fleet Aggregate",
        status: state.enterpriseDashboard.dispatch_health || "watch",
        assignedRides: Number(state.enterpriseDashboard.active_rides || 0),
        idleMinutes: null,
        etaMinutes: Number((state.enterpriseDashboard.metrics || {}).pickup_delay_seconds || 0) / 60,
        utilization: Number((state.enterpriseDashboard.utilization_metrics || {}).driver_utilization_percent || 0),
        availability: Number(state.enterpriseDashboard.available_drivers || 0) > 0 ? "available" : "limited",
        shiftState: Number(state.enterpriseDashboard.available_drivers || 0) > 0 ? "on shift" : "watch",
        totalTrips: Number(enterpriseMetrics.total_trips_completed || state.enterpriseDashboard.total_trips_completed || 0),
        rating: 0,
        updatedAt: state.enterpriseDashboard.last_synced_at,
      }];
    }
    return [];
  }

  function getRideRows(rides) {
    const recommendations = getEnterpriseRecommendations();
    return (rides || []).map(function (ride) {
      const recommendation = recommendations.find(function (item) {
        return String(item.ride_id || "") === String(ride.id || "");
      });
      const queueName = String(ride.status || "").toLowerCase() === "pending"
        ? "Pending"
        : ["accepted", "in_transit"].includes(String(ride.status || "").toLowerCase())
          ? "Active"
          : String(ride.status || "").toLowerCase() === "completed"
            ? "Completed"
            : "Problem";
      return {
        id: ride.id,
        passenger: ride.passenger_name || "Passenger",
        provider: lookupProviderName(ride.provider_id),
        driver: lookupDriverName(ride.driver_id),
        status: String(ride.status || "unknown"),
        priority: getPriorityTag(ride),
        emergency: Boolean(ride.is_emergency),
        delayed: isOverdueRide(ride),
        etaMinutes: deriveRideEtaMinutes(ride),
        slaRisk: summarizeRideRisk(ride),
        queueName: queueName,
        recommendation: recommendation ? String(recommendation.summary || recommendation.explanation_summary || recommendation.action_type || "AI recommendation ready") : "Monitoring live dispatch signals",
        updatedAt: ride.accepted_at || ride.requested_at,
      };
    });
  }

  function ProviderTable(rows) {
    if (!rows.length) return '<p class="health-summary">Provider operations feed unavailable.</p>';
    const body = rows.map(function (row) {
      return [
        '<tr>',
        '<td><strong>' + escapeHtml(row.name) + '</strong><br><small>' + escapeHtml(row.serviceType) + '</small></td>',
        '<td>' + StatusPill(row.status) + '</td>',
        '<td>' + escapeHtml(String(row.activeDrivers)) + '</td>',
        '<td>' + SLABadge(row.sla) + '</td>',
        '<td>' + escapeHtml(String(row.queueSize)) + '</td>',
        '<td>' + escapeHtml(formatPercent(row.utilization)) + '</td>',
        '<td>' + escapeHtml(String(row.alerts)) + '</td>',
        '<td>' + escapeHtml(formatMinutesCompact(row.responseTimeMinutes)) + '</td>',
        '</tr>',
      ].join("");
    }).join("");
    return '<div class="enterprise-table-wrap"><table class="health-table"><thead><tr><th>Provider</th><th>Status</th><th>Active Drivers</th><th>SLA</th><th>Queue</th><th>Utilization</th><th>Alerts</th><th>Response</th></tr></thead><tbody>' + body + '</tbody></table></div>';
  }

  function DriverTable(rows) {
    if (!rows.length) return '<p class="health-summary">Driver operations feed unavailable.</p>';
    const body = rows.map(function (row) {
      return [
        '<tr>',
        '<td><strong>' + escapeHtml(row.name) + '</strong><br><small>Trips ' + escapeHtml(String(row.totalTrips)) + ' · Rating ' + escapeHtml(row.rating ? row.rating.toFixed(1) : 'n/a') + '</small></td>',
        '<td>' + StatusPill(row.status) + '</td>',
        '<td>' + escapeHtml(String(row.assignedRides)) + '</td>',
        '<td>' + escapeHtml(row.idleMinutes === null ? 'On route' : formatMinutesCompact(row.idleMinutes)) + '</td>',
        '<td>' + escapeHtml(formatMinutesCompact(row.etaMinutes)) + '</td>',
        '<td>' + escapeHtml(formatPercent(row.utilization)) + '</td>',
        '<td>' + StatusPill(row.availability, statusTone(row.availability)) + '</td>',
        '<td>' + escapeHtml(row.shiftState) + '</td>',
        '<td><button class="health-row-btn" data-driver-inspect="' + escapeHtml(row.id) + '">Inspect</button></td>',
        '</tr>',
      ].join("");
    }).join("");
    return '<div class="enterprise-table-wrap"><table class="health-table"><thead><tr><th>Driver</th><th>Status</th><th>Assigned</th><th>Idle Time</th><th>ETA</th><th>Utilization</th><th>Availability</th><th>Shift State</th><th>Actions</th></tr></thead><tbody>' + body + '</tbody></table></div>';
  }

  function RideQueue(rows) {
    if (!rows.length) return '<p class="health-summary">Ride queue is clear.</p>';
    const body = rows.map(function (row) {
      return [
        '<tr>',
        '<td><strong>' + escapeHtml(row.passenger) + '</strong><br><small>' + escapeHtml(String(row.id || '').slice(0, 8)) + '</small></td>',
        '<td>' + escapeHtml(row.provider) + '</td>',
        '<td>' + escapeHtml(row.driver) + '</td>',
        '<td>' + StatusPill(row.status) + '</td>',
        '<td><span class="health-priority-badge ' + escapeHtml(row.priority) + '">' + escapeHtml(row.priority) + '</span></td>',
        '<td>' + escapeHtml(row.queueName) + '</td>',
        '<td>' + SLABadge(row.slaRisk) + '</td>',
        '<td>' + escapeHtml(formatMinutesCompact(row.etaMinutes)) + '</td>',
        '<td><small>' + escapeHtml(row.recommendation) + '</small></td>',
        '</tr>',
      ].join("");
    }).join("");
    return '<div class="enterprise-table-wrap"><table class="health-table"><thead><tr><th>Ride</th><th>Provider</th><th>Driver</th><th>Status</th><th>Priority</th><th>Queue</th><th>SLA Risk</th><th>ETA</th><th>AI Recommendation</th></tr></thead><tbody>' + body + '</tbody></table></div>';
  }

  function AlertPanel(items, emptyText) {
    return renderNotificationList(items || [], emptyText || "No live alerts.");
  }

  function buildLineChartPath(values, width, height) {
    if (!values.length) return "";
    const maxValue = Math.max(1, ...values.map(function (item) { return Number(item.value || 0); }));
    const stepX = values.length > 1 ? width / (values.length - 1) : width;
    return values.map(function (item, index) {
      const x = Math.round(index * stepX);
      const y = Math.round(height - ((Number(item.value || 0) / maxValue) * height));
      return (index === 0 ? "M" : "L") + x + " " + y;
    }).join(" ");
  }

  function AnalyticsChart(config) {
    const chartType = String(config && config.type || "bar");
    const items = Array.isArray(config && config.items) ? config.items : [];
    const points = Array.isArray(config && config.points) ? config.points : [];
    const emptyText = String(config && config.emptyText || "No live chart data yet.");
    const stamp = config && config.timestamp ? formatDateShort(config.timestamp) : null;

    if (chartType === "line") {
      const series = points.length ? points : [{ label: "T-5", value: 1 }, { label: "T-4", value: 2 }, { label: "T-3", value: 2 }, { label: "T-2", value: 3 }, { label: "T-1", value: 2 }, { label: "Now", value: 4 }];
      const path = buildLineChartPath(series, 300, 96);
      const labels = '<div class="enterprise-line-labels">' + series.map(function (item) {
        return '<span>' + escapeHtml(item.label) + '</span>';
      }).join("") + '</div>';
      return [
        '<div class="enterprise-line-chart">',
        '<svg viewBox="0 0 300 110" preserveAspectRatio="none" aria-hidden="true">',
        '<path class="enterprise-line-chart-grid" d="M0 96 L300 96"></path>',
        '<path class="enterprise-line-chart-path" d="' + path + '"></path>',
        '</svg>',
        labels,
        '<div class="enterprise-chart-footer">' + escapeHtml((config && config.footer) || (stamp ? 'Updated ' + stamp : 'Live operational trend')) + '</div>',
        '</div>',
      ].join("");
    }

    if (!items.length) {
      return '<p class="health-summary">' + escapeHtml(emptyText) + '</p>';
    }

    const maxValue = Math.max(1, ...items.map(function (item) { return Number(item.value || 0); }));
    const rows = items.map(function (item) {
      const pct = Math.round((Number(item.value || 0) / maxValue) * 100);
      return [
        '<div class="health-chart-row">',
        '<span class="name">' + escapeHtml(item.label || item.name || "item") + '</span>',
        '<span class="health-chart-track"><span class="health-chart-fill" style="width:' + pct + '%"></span></span>',
        '<strong>' + escapeHtml(String(item.displayValue != null ? item.displayValue : item.value)) + '</strong>',
        '</div>',
      ].join("");
    }).join("");
    return '<div class="health-chart-list">' + rows + '</div><div class="enterprise-chart-footer">' + escapeHtml((config && config.footer) || (stamp ? 'Updated ' + stamp : 'Live analytics')) + '</div>';
  }

  function showToastSafe(text, type) {
    if (typeof window.showToast === "function") {
      window.showToast(text, type || "");
      return;
    }
    window.alert(text);
  }

  function sanitizeInput(value) {
    return String(value || "")
      .replace(/[\x00-\x08\x0B\x0C\x0E-\x1F\x7F]/g, "")
      .replace(/\s+/g, " ")
      .trim();
  }

  function parseOptionalJson(raw, fieldName, errors) {
    const value = sanitizeInput(raw);
    if (!value) return null;
    try {
      return JSON.parse(value);
    } catch (_err) {
      errors[fieldName] = "Must be valid JSON";
      return null;
    }
  }

  function clearCreateRideErrors() {
    const els = getEls();
    if (els.createInlineError) {
      els.createInlineError.hidden = true;
      els.createInlineError.textContent = "";
    }
    if (!els.form) return;
    els.form.querySelectorAll("[data-field-error]").forEach((node) => {
      node.textContent = "";
    });
    els.form.querySelectorAll(".has-error").forEach((node) => {
      node.classList.remove("has-error");
    });
  }

  function renderCreateRideErrors(errors, fallbackMessage) {
    const els = getEls();
    clearCreateRideErrors();
    if (els.createInlineError && fallbackMessage) {
      els.createInlineError.hidden = false;
      els.createInlineError.textContent = fallbackMessage;
    }
    if (!els.form) return;
    Object.keys(errors || {}).forEach((field) => {
      const errorNode = els.form.querySelector('[data-field-error="' + field + '"]');
      const inputNode = els.form.querySelector('[name="' + field + '"]');
      if (errorNode) errorNode.textContent = errors[field];
      if (inputNode) inputNode.classList.add("has-error");
    });
  }

  function setCreateRideSubmitting(active) {
    const els = getEls();
    state.createRideSubmitting = !!active;
    if (!els.form) return;
    const controls = els.form.querySelectorAll("input, select, textarea, button");
    controls.forEach((node) => {
      if (node.getAttribute("data-health-action") === "dismiss-modal" && active) return;
      node.disabled = active;
    });
    if (els.createSubmitLabel) {
      els.createSubmitLabel.textContent = active ? "Creating Ride..." : "Create Ride";
    }
  }

  function validateCreateRidePayload(payload) {
    const errors = {};
    if (!payload.passenger_name) errors.passenger_name = "Passenger name is required";
    if (!/^\+?[0-9()\-\s]{7,20}$/.test(payload.passenger_phone || "")) {
      errors.passenger_phone = "Use a valid phone format";
    }
    if (!payload.pickup_address) errors.pickup_address = "Pickup address is required";
    if (!payload.dropoff_address) errors.dropoff_address = "Dropoff address is required";
    if (payload.pickup_address && payload.dropoff_address && payload.pickup_address.toLowerCase() === payload.dropoff_address.toLowerCase()) {
      errors.dropoff_address = "Dropoff must be different from pickup";
    }
    if (!payload.service_type) errors.service_type = "Service type is required";
    if (!payload.provider_id) errors.provider_id = "Provider selection is required";
    if (!(Number(payload.estimated_distance_miles) > 0)) {
      errors.estimated_distance_miles = "Distance must be greater than 0";
    }
    if (payload.estimated_duration_minutes !== null && payload.estimated_duration_minutes !== undefined) {
      if (!(Number(payload.estimated_duration_minutes) > 0)) {
        errors.estimated_duration_minutes = "Duration must be greater than 0";
      }
    }
    return errors;
  }

  function getWsContext() {
    if (!window.AmiCorSession || typeof window.AmiCorSession.getAccessToken !== "function") {
      console.warn("[Health ISF] AmiCorSession not available");
      return null;
    }
    
    // Try to restore session from storage if needed
    if (typeof window.AmiCorSession.restore === "function") {
      const restored = window.AmiCorSession.restore();
      if (!restored && !window.AmiCorSession.isActive()) {
        console.warn("[Health ISF] Session not active and restore failed");
        return null;
      }
    }
    
    const token = String(window.AmiCorSession.getAccessToken() || "");
    const userId = String(window.AmiCorSession.getUserId() || "");
    const role = String(window.AmiCorSession.getRole() || "dispatcher").toLowerCase();
    
    if (!token || !userId) {
      console.warn("[Health ISF] Missing token or userId", { token: !!token, userId: !!userId });
      return null;
    }
    
    const parts = token.split(".");
    if (parts.length < 2) {
      console.warn("[Health ISF] Token malformed (not JWT)", { partCount: parts.length });
      return null;
    }
    
    try {
      const payload = JSON.parse(atob(parts[1].replace(/-/g, "+").replace(/_/g, "/")));
      const organizationId = String(payload.organization_id || "");
      if (!organizationId) {
        console.warn("[Health ISF] Token missing organization_id");
        return null;
      }
      logDiag("WebSocket context ready", { organizationId, userId, role });
      return { token, userId, role, organizationId };
    } catch (_err) {
      console.warn("[Health ISF] Failed to parse token JWT", _err);
      return null;
    }
  }

  function scheduleRealtimeRefresh() {
    if (state.realtimeRefreshTimer) return;
    state.realtimeRefreshTimer = setTimeout(() => {
      state.realtimeRefreshTimer = null;
      triggerRefresh("realtime-event");
    }, 400);
  }

  function getRealtimePayloadDetails(payload) {
    return payload && typeof payload.details === "object" && payload.details ? payload.details : {};
  }

  function getRealtimeRideId(payload) {
    const details = getRealtimePayloadDetails(payload);
    return String(firstDefined(payload && payload.ride_id, details.ride_id, details.rideId, "") || "");
  }

  function getRealtimeDriverId(payload) {
    const details = getRealtimePayloadDetails(payload);
    return String(firstDefined(payload && payload.driver_id, payload && payload.to_driver_id, details.driver_id, details.to_driver_id, details.toDriverId, "") || "");
  }

  function socketIsStale(now) {
    const current = Number(now || nowMs());
    const lastActivityMs = Number(state.lastRealtimeActivityAtMs || state.lastRealtimeConnectAtMs || 0);
    if (lastActivityMs <= 0) return true;
    return (current - lastActivityMs) >= REALTIME_STALE_THRESHOLD_MS;
  }

  function monitorRealtimeHealth(source) {
    if (!state.active) return;
    if (state.websocketStatus !== "connected") return;
    if (document.visibilityState && document.visibilityState !== "visible") return;
    const now = nowMs();
    if (!socketIsStale(now)) return;
    logDiag("Realtime socket stale", {
      source: source || "health-monitor",
      staleMs: now - Number(state.lastRealtimeActivityAtMs || state.lastRealtimeConnectAtMs || 0),
      thresholdMs: REALTIME_STALE_THRESHOLD_MS,
    });
    reconnectRealtime(source || "health-monitor", { force: true, onlyIfStale: true, bypassCooldown: true });
  }

  function nowMs() {
    return Date.now();
  }

  function reconnectThrottleMs(reason) {
    if (reason === "session-recovered") return 3000;
    if (reason === "socket_error" || reason === "socket_closed" || reason === "auth_failure") return 1500;
    return REALTIME_RECONNECT_COOLDOWN_MS;
  }

  function canReconnectRealtime(reason, options) {
    if (!state.active) {
      incrementStabilityCounter("reconnectSuppressed", 1);
      return false;
    }

    const opts = options && typeof options === "object" ? options : {};
    const force = !!opts.force;
    const onlyIfStale = !!opts.onlyIfStale;
    const now = nowMs();

    if (state.websocketStatus === "connecting") {
      incrementStabilityCounter("reconnectSuppressed", 1);
      return false;
    }
    if (state.reconnectTimer && !force) {
      incrementStabilityCounter("reconnectSuppressed", 1);
      return false;
    }

    const socket = state.socket;
    const readyState = socket ? socket.readyState : null;
    const isConnected = readyState === WebSocket.OPEN;

    if (isConnected && !force) {
      if (!onlyIfStale) return false;
      const lastActivityMs = Number(state.lastRealtimeActivityAtMs || state.lastRealtimeConnectAtMs || 0);
      const staleMs = lastActivityMs > 0 ? (now - lastActivityMs) : Number.POSITIVE_INFINITY;
      if (!socketIsStale(now)) {
        logDiag("Realtime reconnect skipped (socket healthy)", {
          reason: reason || "unknown",
          staleMs,
          thresholdMs: REALTIME_STALE_THRESHOLD_MS,
        });
        incrementStabilityCounter("reconnectSuppressed", 1);
        return false;
      }
    }

    const throttleMs = reconnectThrottleMs(reason);
    const sinceLastReconnect = now - Number(state.lastRealtimeReconnectAtMs || 0);
    if (!force && sinceLastReconnect >= 0 && sinceLastReconnect < throttleMs) {
      logDiag("Realtime reconnect throttled", {
        reason: reason || "unknown",
        sinceLastReconnect,
        throttleMs,
      });
      incrementStabilityCounter("reconnectSuppressed", 1);
      return false;
    }

    return true;
  }

  function resetRealtimeBackoff() {
    state.reconnectAttempt = 0;
    state.reconnectBackoffMs = 1500;
    if (state.reconnectTimer) {
      clearTimeout(state.reconnectTimer);
      state.reconnectTimer = null;
    }
  }

  function scheduleRealtimeReconnect(reason, authFailure) {
    if (!state.active) return;
    if (state.reconnectTimer) return;

    const hasSession = !!(window.AmiCorSession
      && typeof window.AmiCorSession.isActive === "function"
      && window.AmiCorSession.isActive());
    const hasToken = !!(window.AmiCorSession
      && typeof window.AmiCorSession.getAccessToken === "function"
      && window.AmiCorSession.getAccessToken());
    if (authFailure && (!hasSession || !hasToken)) {
      state.websocketStatus = "auth_required";
      logDiag("WebSocket reconnect halted", {
        reason: reason || "unknown",
        hasSession,
        hasToken,
      });
      renderAIOperations();
      return;
    }

    const delay = Math.min(state.reconnectBackoffMs, 12000);
    incrementStabilityCounter("reconnectAttempts", 1);
    const now = nowMs();
    const windowStart = Number(state.stability.reconnectWindowStartMs || 0);
    if (!windowStart || now - windowStart > RECONNECT_BURST_WINDOW_MS) {
      state.stability.reconnectWindowStartMs = now;
      state.stability.reconnectWindowCount = 1;
    } else {
      state.stability.reconnectWindowCount = Number(state.stability.reconnectWindowCount || 0) + 1;
      if (state.stability.reconnectWindowCount >= RECONNECT_BURST_LIMIT) {
        incrementStabilityCounter("reconnectBursts", 1);
      }
    }
    state.reconnectAttempt += 1;
    state.reconnectBackoffMs = Math.min(Math.floor(state.reconnectBackoffMs * 1.6), 12000);
    state.websocketStatus = authFailure ? "auth_recovering" : "reconnecting";
    logDiag("WebSocket reconnect scheduled", {
      reason: reason || "unknown",
      authFailure: !!authFailure,
      delayMs: delay,
      attempt: state.reconnectAttempt,
    });
    renderAIOperations();

    state.reconnectTimer = setTimeout(() => {
      state.reconnectTimer = null;
      connectRealtimeSocket();
    }, delay);
  }

  function parseRealtimeMessage(rawData) {
    let parsed;
    try {
      parsed = JSON.parse(rawData);
    } catch (_err) {
      return null;
    }
    if (!parsed || typeof parsed !== "object") return null;
    if (String(parsed.type || "") === "event_batch" && Array.isArray(parsed.events)) {
      const events = parsed.events.map((item) => {
        if (!item || typeof item !== "object") return null;
        return {
          type: "event",
          eventType: String(item.event_type || ""),
          payload: item.payload && typeof item.payload === "object" ? item.payload : {},
          timestamp: String(item.timestamp || new Date().toISOString()),
        };
      }).filter((item) => item && item.eventType);
      if (!events.length) return null;
      return { type: "batch", events: events };
    }

    const eventType = String(parsed.event_type || "");
    const payload = parsed.payload && typeof parsed.payload === "object" ? parsed.payload : {};
    if (!eventType) return null;
    const known = [
      "ride_created",
      "ride_status_changed",
      "ride-created",
      "ride-approved",
      "ride-dispatchable",
      "ride-in-progress",
      "ride-completed",
      "ride_assigned",
      "ride_reassigned",
      "ride_escalated",
      "ride_retry",
      "ride_completed",
      "pickup_completed",
      "driver_status_changed",
      "driver_active_ride_state",
      "ride_lifecycle_sync",
      "driver-offer-issued",
      "driver-offer-accepted",
      "driver-location-updated",
      "provider-request-created",
      "dispatch_changed",
      "workflow_recovery_completed",
      "workflow_reassignment_executed",
      "workflow_replay_completed",
      "workflow_escalated",
      "intelligence_recommendations",
      "intelligence_summary",
      "intelligence_risk",
      "orchestration_update",
      "autonomous_operations_snapshot",
    ];
    if (!known.includes(eventType)) return null;
    return {
      type: "event",
      eventType,
      payload,
      timestamp: String(parsed.timestamp || new Date().toISOString()),
    };
  }

  function getOrganizationId() {
    try {
      if (window.AmiCorSession && typeof window.AmiCorSession.getOrganizationId === "function") {
        const sessionOrg = String(window.AmiCorSession.getOrganizationId() || "").trim();
        if (sessionOrg) {
          state.activeOrganizationId = sessionOrg;
          return sessionOrg;
        }
      }
    } catch (_err) {}

    const ctx = getWsContext();
    const orgId = ctx ? ctx.organizationId : "";
    state.activeOrganizationId = orgId || null;
    return orgId;
  }

  function getPriorityTag(ride) {
    return String(ride && ride.priority_tag ? ride.priority_tag : "normal").toLowerCase();
  }

  function isOverdueRide(ride) {
    const status = String(ride.status || "").toLowerCase();
    if (status === "completed" || status === "cancelled") return false;
    const requestedAt = ride.requested_at ? new Date(ride.requested_at).getTime() : 0;
    if (!requestedAt) return false;
    const overdueMs = 35 * 60 * 1000;
    return Date.now() - requestedAt > overdueMs;
  }

  function hasOperationalWarning(ride) {
    const status = String(ride.status || "").toLowerCase();
    return isOverdueRide(ride) || status === "cancelled" || (!ride.driver_id && status !== "completed");
  }

  function getDispatchLoadBadge() {
    const active = state.rides.filter((ride) => ["accepted", "in_transit"].includes(String(ride.status || "").toLowerCase())).length;
    const available = state.drivers.filter((driver) => String(driver.status || "").toLowerCase() === "available").length;
    if (!available && active > 0) return { text: "No drivers available", className: "danger" };
    if (active > available * 2) return { text: "Dispatch load high", className: "warn" };
    return { text: "Dispatch load stable", className: "live" };
  }

  function normalizedLifecycleStatus(status) {
    const value = String(status || "").toLowerCase().replace(/-/g, "_");
    if (["pending", "queued", "searching", "dispatchable"].includes(value)) return "queued";
    if (["accepted", "offered", "driver_offer_issued", "en_route_pickup", "waiting_at_pickup", "arrived_pickup", "rider_loaded", "trip_in_progress", "in_transit"].includes(value)) return "active";
    if (["completed", "arrived_destination", "dropoff_complete"].includes(value)) return "completed";
    return "problem";
  }

  function buildLifecycleRows() {
    const rides = Array.isArray(state.rides) ? state.rides : [];
    const replayEvents = state.runtimeReplay && Array.isArray(state.runtimeReplay.events) ? state.runtimeReplay.events : [];
    const replayByRide = {};

    replayEvents.forEach(function (evt) {
      const details = evt && typeof evt.details === "object" ? evt.details : {};
      const rideId = String(details.ride_id || details.rideId || "");
      if (!rideId) return;
      if (!replayByRide[rideId]) replayByRide[rideId] = [];
      replayByRide[rideId].push(evt);
    });

    return rides.map(function (ride) {
      const rideId = String(ride.id || "");
      const replay = replayByRide[rideId] || [];
      const lifecycle = normalizedLifecycleStatus(ride.status);
      const hasRecovery = replay.some(function (evt) {
        const alias = String(evt.event_alias || evt.event_name || "").toLowerCase();
        return alias.indexOf("replay") !== -1 || alias.indexOf("recovery") !== -1;
      });
      const hasEscalation = replay.some(function (evt) {
        const alias = String(evt.event_alias || evt.event_name || "").toLowerCase();
        return alias.indexOf("escalat") !== -1;
      });
      const stale = isOverdueRide(ride);
      const recurring = normalizeServiceCategory(ride.service_type || "") === "recurring_transport";
      return {
        rideId: rideId,
        rider: String(ride.passenger_name || "Passenger"),
        lifecycle: lifecycle,
        status: String(ride.status || "unknown"),
        recurring: recurring,
        stale: stale,
        delayedMinutes: stale ? (minutesBetween(ride.requested_at, new Date().toISOString()) || 0) : 0,
        assignment: String(lookupDriverName(ride.driver_id) || "Unassigned"),
        hasRecovery: hasRecovery,
        hasEscalation: hasEscalation,
      };
    });
  }

  function lifecycleProgressionPanel(rows) {
    const buckets = {
      queued: [],
      active: [],
      completed: [],
      problem: [],
    };
    rows.forEach(function (row) {
      const key = buckets[row.lifecycle] ? row.lifecycle : "problem";
      buckets[key].push(row);
    });

    function lifecycleColumn(title, key, tone) {
      const list = buckets[key] || [];
      return '<section class="phase56-lifecycle-column">'
        + '<h4>' + escapeHtml(title) + ' <span class="health-queue-count">' + escapeHtml(String(list.length)) + '</span></h4>'
        + (list.length
          ? list.slice(0, 6).map(function (row) {
              return '<article class="phase56-lifecycle-item ' + escapeHtml(tone) + '">'
                + '<div class="phase56-lifecycle-title"><strong>' + escapeHtml(row.rider) + '</strong><span class="health-pill ' + pillClass(row.status) + '">' + escapeHtml(row.status) + '</span></div>'
                + '<div class="phase56-lifecycle-meta">'
                + '<span>Ride ' + escapeHtml(String(row.rideId || "").slice(0, 8)) + '</span>'
                + '<span>Driver ' + escapeHtml(row.assignment) + '</span>'
                + '</div>'
                + '<div class="phase56-lifecycle-badges">'
                + (row.recurring ? '<span class="health-op-badge live">recurring</span>' : '')
                + (row.stale ? '<span class="health-op-badge danger">stale ' + escapeHtml(formatMinutesCompact(row.delayedMinutes)) + '</span>' : '')
                + (row.hasRecovery ? '<span class="health-op-badge warn">recovery</span>' : '')
                + (row.hasEscalation ? '<span class="health-op-badge danger">escalated</span>' : '')
                + '</div>'
                + '</article>';
            }).join("")
          : '<p class="health-summary">No rides.</p>')
        + '</section>';
    }

    return '<div class="phase56-lifecycle-grid">'
      + lifecycleColumn("Queue", "queued", "queued")
      + lifecycleColumn("Active", "active", "active")
      + lifecycleColumn("Completed", "completed", "completed")
      + lifecycleColumn("Recovery", "problem", "problem")
      + '</div>';
  }

  function dispatchOwnershipPanel() {
    const assignments = Array.isArray(state.dispatchActiveAssignments) ? state.dispatchActiveAssignments : [];
    const rows = assignments.slice(0, 10).map(function (item) {
      const locked = !!item.ownership_locked;
      const ownerId = String(item.ownership_locked_by_user_id || "");
      const ownerLabel = locked ? (item.ownership_is_current_user ? "my lock" : "locked") : "unlocked";
      const reconnectState = state.websocketStatus === "connected" ? "connected" : "reconnecting";
      const tone = locked && !item.ownership_is_current_user ? "warn" : "live";
      return '<article class="phase56-ownership-item">'
        + '<div class="phase56-ownership-title"><strong>' + escapeHtml(String(item.passenger_name || "Passenger")) + '</strong><span class="health-pill ' + pillClass(item.assignment_state || "offered") + '">' + escapeHtml(item.assignment_state || "offered") + '</span></div>'
        + '<div class="phase56-ownership-meta">Ride ' + escapeHtml(String(item.ride_id || "").slice(0, 8)) + ' · driver ' + escapeHtml(String(item.driver_name || "pending")) + '</div>'
        + '<div class="phase56-ownership-badges">'
        + '<span class="health-op-badge ' + tone + '">Owner ' + escapeHtml(ownerLabel + (ownerId ? " " + ownerId.slice(0, 8) : "")) + '</span>'
        + '<span class="health-op-badge ' + (reconnectState === "connected" ? "live" : "warn") + '">WS ' + escapeHtml(reconnectState) + '</span>'
        + '<span class="health-op-badge ' + (item.offer_expires_at ? "warn" : "live") + '">Expires ' + escapeHtml(item.offer_expires_at ? formatRelativeTime(item.offer_expires_at) : "n/a") + '</span>'
        + '</div>'
        + '</article>';
    }).join("");

    return rows || '<p class="health-summary">No assignment ownership rows currently active.</p>';
  }

  function recurringTransportPanel() {
    const templates = Array.isArray(state.recurringTemplates) ? state.recurringTemplates : [];
    const rides = Array.isArray(state.rides) ? state.rides : [];
    const recurringRides = rides.filter(function (ride) {
      return normalizeServiceCategory(ride.service_type || "") === "recurring_transport";
    });

    const grouped = {};
    templates.forEach(function (tpl) {
      const key = String(tpl.rider_phone || tpl.rider_name || tpl.id || "group");
      if (!grouped[key]) grouped[key] = [];
      grouped[key].push(tpl);
    });

    const groups = Object.keys(grouped).slice(0, 8).map(function (key) {
      const items = grouped[key] || [];
      const top = items[0] || {};
      const missed = items.filter(function (it) { return String(it.last_status || "").toLowerCase() === "missed"; }).length;
      const timeline = items.map(function (it) {
        const recur = it.recurrence && Array.isArray(it.recurrence.days) ? it.recurrence.days.join(",") : "schedule";
        return '<span class="health-op-badge ' + (String(it.last_status || "").toLowerCase() === "missed" ? "danger" : "live") + '">' + escapeHtml(recur) + '</span>';
      }).join("");
      return '<article class="phase56-recurring-item">'
        + '<div class="phase56-recurring-title"><strong>' + escapeHtml(String(top.rider_name || key)) + '</strong><span class="health-op-badge ' + (missed ? "danger" : "live") + '">missed ' + escapeHtml(String(missed)) + '</span></div>'
        + '<p>Provider ' + escapeHtml(String(lookupProviderName(top.provider_id) || "unassigned")) + ' · pickup ' + escapeHtml(String(top.preferred_pickup_time || "n/a")) + '</p>'
        + '<div class="phase56-recurring-timeline">' + timeline + '</div>'
        + '</article>';
    }).join("");

    return '<div class="enterprise-inline-grid">'
      + MetricCard('Recurring templates', formatNumber(templates.length), 'Configured recurring ride groups', templates.length ? 'ok' : 'warn')
      + MetricCard('Recurring rides live', formatNumber(recurringRides.length), 'Active recurring transport instances', recurringRides.length ? 'warn' : 'ok')
      + MetricCard('Missed recurring', formatNumber(templates.filter(function (it) { return String(it.last_status || '').toLowerCase() === 'missed'; }).length), 'Missed recurring trip indicators', templates.some(function (it) { return String(it.last_status || '').toLowerCase() === 'missed'; }) ? 'danger' : 'ok')
      + '</div>'
      + (groups || '<p class="health-summary">Recurring groups will appear once templates are available.</p>');
  }

  function websocketRuntimeFeedPanel() {
    const feed = (Array.isArray(state.operationalEventFeed) ? state.operationalEventFeed : []).filter(function (item) {
      const src = String(item.source || "").toLowerCase();
      const typ = String(item.eventType || "").toLowerCase();
      return src === "websocket" || typ.indexOf("dispatch") !== -1 || typ.indexOf("workflow") !== -1 || typ.indexOf("ride_") !== -1;
    }).slice(0, 10);
    const replay = state.runtimeReplay && typeof state.runtimeReplay === "object" ? state.runtimeReplay : null;
    const replaySafe = replay && replay.replay_safe !== false;
    const hydrationOk = !state.hydration.lastRefreshError && !!state.hydration.lastRefreshAt;
    const reconnectLabel = state.reconnectAttempt ? ("attempt " + state.reconnectAttempt) : "none";

    return '<div class="enterprise-inline-grid">'
      + MetricCard('Websocket', state.websocketStatus, 'Realtime transport stream status', state.websocketStatus === 'connected' ? 'ok' : 'warn')
      + MetricCard('Reconnect', reconnectLabel, 'Recovery attempts for runtime continuity', state.reconnectAttempt ? 'warn' : 'ok')
      + MetricCard('Hydration', hydrationOk ? 'synced' : 'pending', 'Runtime hydration completion state', hydrationOk ? 'ok' : 'warn')
      + MetricCard('Replay integrity', replaySafe ? 'safe' : 'watch', 'Replay safety in current runtime snapshot', replaySafe ? 'ok' : 'warn')
      + '</div>'
      + operational_event_feed(feed, 'No websocket event feed rows yet.');
  }

  function toLowerSafe(value) {
    return String(value || "").toLowerCase();
  }

  function eventHasSignal(value, keys) {
    const text = toLowerSafe(value);
    if (!text) return false;
    return (keys || []).some(function (key) {
      return text.indexOf(String(key || "").toLowerCase()) !== -1;
    });
  }

  function classifyPhase57Event(event) {
    const item = event && typeof event === "object" ? event : {};
    const payload = item.payload && typeof item.payload === "object" ? item.payload : {};
    const eventType = toLowerSafe(item.eventType || item.event_type || item.type);
    const payloadName = toLowerSafe(payload.event_name || payload.event || payload.action || payload.status);
    const summary = toLowerSafe(item.summary || payload.summary || payload.message || payload.reason);
    const combined = [eventType, payloadName, summary].join(" ");

    if (eventHasSignal(combined, ["ride_created", "ride created"])) {
      return { key: "ride_created", label: "ride_created", tone: "live" };
    }
    if (eventHasSignal(combined, ["ride_assigned", "driver_offer_accepted", "assigned"])) {
      return { key: "dispatcher_assigned", label: "dispatcher_assigned", tone: "live" };
    }
    if (eventHasSignal(combined, ["claim", "ownership claim", "dispatch claim", "locked by"])) {
      return { key: "ownership_claimed", label: "ownership_claimed", tone: "warn" };
    }
    if (eventHasSignal(combined, ["handoff", "reassigned", "reassignment", "ownership handoff"])) {
      return { key: "ownership_handoff", label: "ownership_handoff", tone: "warn" };
    }
    if (eventHasSignal(combined, ["escalat", "supervisor"])) {
      return { key: "escalation_triggered", label: "escalation_triggered", tone: "danger" };
    }
    if (eventHasSignal(combined, ["ride_completed", "ride completed", "dropoff_complete", "completed"])) {
      return { key: "ride_completed", label: "ride_completed", tone: "live" };
    }
    if (eventHasSignal(combined, ["reconnect", "socket_closed", "socket_error", "auth_recovering", "recovery_completed"])) {
      return { key: "websocket_reconnected", label: "websocket_reconnected", tone: "warn" };
    }
    if (eventHasSignal(combined, ["replay", "workflow_replay_completed", "synchronization", "event bus sequence"])) {
      return { key: "replay_synchronized", label: "replay_synchronized", tone: "live" };
    }
    return null;
  }

  function getPhase57RealtimeEvents(limit) {
    const sourceEvents = Array.isArray(state.operationalEventFeed) ? state.operationalEventFeed : [];
    const normalized = sourceEvents.map(function (item) {
      const classification = classifyPhase57Event(item);
      if (!classification) return null;
      return {
        eventType: classification.label,
        tone: classification.tone,
        summary: item.summary || item.recommendationStatus || "Operational event",
        timestamp: item.timestamp || stampNow(),
        source: item.source || "runtime",
        rideId: firstDefined(item.payload && item.payload.ride_id, item.payload && item.payload.rideId, item.payload && item.payload.dispatch_ride_id, ""),
      };
    }).filter(function (item) { return !!item; });

    const replayEvents = state.runtimeReplay && Array.isArray(state.runtimeReplay.events)
      ? state.runtimeReplay.events.slice(0, 50).map(function (evt) {
          const eventName = firstDefined(evt && evt.event_alias, evt && evt.event_name, evt && evt.type, "runtime_replay");
          const synthetic = {
            eventType: String(eventName || "runtime_replay"),
            summary: firstDefined(evt && evt.summary, evt && evt.reason, evt && evt.status, "Replay synchronization event"),
            timestamp: firstDefined(evt && evt.created_at, evt && evt.timestamp, stampNow()),
            payload: evt && typeof evt.details === "object" ? evt.details : {},
            source: "replay",
          };
          const classification = classifyPhase57Event(synthetic);
          if (!classification) return null;
          return {
            eventType: classification.label,
            tone: classification.tone,
            summary: synthetic.summary,
            timestamp: synthetic.timestamp,
            source: "replay",
            rideId: firstDefined(synthetic.payload && synthetic.payload.ride_id, synthetic.payload && synthetic.payload.rideId, ""),
          };
        }).filter(function (item) { return !!item; })
      : [];

    const reconnectEvents = [];
    if (state.reconnectAttempt > 0 || state.websocketStatus === "reconnecting" || state.websocketStatus === "auth_recovering") {
      reconnectEvents.push({
        eventType: "websocket_reconnected",
        tone: state.websocketStatus === "connected" ? "live" : "warn",
        summary: "Reconnect attempts " + formatNumber(state.reconnectAttempt) + " with status " + String(state.websocketStatus || "idle"),
        timestamp: firstDefined(state.lastRealtimeMessageAt, state.hydration.lastRefreshAt, stampNow()),
        source: "runtime",
        rideId: "",
      });
    }

    const merged = normalized.concat(replayEvents).concat(reconnectEvents);
    merged.sort(function (a, b) {
      const ta = new Date(a.timestamp || 0).getTime();
      const tb = new Date(b.timestamp || 0).getTime();
      return ta - tb;
    });
    const max = Math.max(8, Number(limit || 24));
    return merged.slice(Math.max(0, merged.length - max));
  }

  function getPhase57ExecutiveMetrics() {
    const rides = Array.isArray(state.rides) ? state.rides : [];
    const assignments = Array.isArray(state.dispatchActiveAssignments) ? state.dispatchActiveAssignments : [];
    const activeRides = rides.filter(function (ride) {
      const status = toLowerSafe(ride && ride.status);
      return status === "accepted" || status === "in_transit";
    }).length;
    const pendingAssignments = assignments.filter(function (item) {
      const assignmentState = toLowerSafe(item && item.assignment_state);
      return assignmentState === "offered" || assignmentState === "pending" || assignmentState === "queued";
    }).length;
    const delayedRides = rides.filter(function (ride) { return isOverdueRide(ride); }).length;
    const availableDrivers = (Array.isArray(state.drivers) ? state.drivers : []).filter(function (driver) {
      return toLowerSafe(driver && driver.status) === "available";
    }).length;
    const dispatcherLoad = availableDrivers > 0 ? (activeRides / Math.max(1, availableDrivers)) : activeRides;
    const wsHealthy = state.websocketStatus === "connected" && state.reconnectAttempt < 3;
    const wsMetrics = getWebsocketMetrics();
    const syncHealthy = Boolean(wsMetrics.sync && wsMetrics.sync.replay_safe !== false && wsMetrics.sync.reconnect_safe !== false);
    const replayQueue = state.runtimeReplay && Array.isArray(state.runtimeReplay.events) ? state.runtimeReplay.events.length : 0;
    const escalations = getPhase57RealtimeEvents(40).filter(function (item) {
      return item.eventType === "escalation_triggered";
    }).length;
    const coordinationLoad = pendingAssignments + escalations + delayedRides;

    return [
      MetricCard("Active rides", formatNumber(activeRides), "Rides currently in execution", activeRides ? "ok" : "warn"),
      MetricCard("Pending assignments", formatNumber(pendingAssignments), "Dispatch offers waiting for resolution", pendingAssignments ? "warn" : "ok"),
      MetricCard("Delayed rides", formatNumber(delayedRides), "SLA watchlist from live ride timestamps", delayedRides ? "danger" : "ok"),
      MetricCard("Dispatcher load", Number(dispatcherLoad).toFixed(2), "Active rides per available driver", dispatcherLoad > 1.6 ? "danger" : dispatcherLoad > 1 ? "warn" : "ok"),
      MetricCard("WebSocket health", wsHealthy ? "healthy" : state.websocketStatus, "Connection and reconnect pressure", wsHealthy ? "ok" : "warn"),
      MetricCard("Sync health", syncHealthy ? "stable" : "watch", "Replay-safe runtime synchronization", syncHealthy ? "ok" : "warn"),
      MetricCard("Replay queue", formatNumber(replayQueue), "Runtime replay events currently retained", replayQueue > 80 ? "warn" : "ok"),
      MetricCard("Coordination load", formatNumber(coordinationLoad), "Pending coordination across locks, escalations, delays", coordinationLoad > 12 ? "danger" : "warn"),
    ].join("");
  }

  function phase57EventRow(item) {
    const tone = toLowerSafe(item && item.tone) || "live";
    return [
      '<article class="phase57-event-row ' + escapeHtml(tone) + '">',
      '<div class="phase57-event-main">',
      '<strong>' + escapeHtml(item.eventType || 'Operational Event') + '</strong>',
      '<p>' + escapeHtml(item.summary || 'Realtime transport event') + '</p>',
      '</div>',
      '<div class="phase57-event-meta">',
      '<span class="health-op-badge ' + escapeHtml(tone) + '">' + escapeHtml(item.source || 'runtime') + '</span>',
      (item.rideId ? '<span class="health-op-badge live">Ride ' + escapeHtml(String(item.rideId).slice(0, 8)) + '</span>' : ''),
      '<small>' + escapeHtml(formatDateShort(item.timestamp)) + '</small>',
      '</div>',
      '</article>',
    ].join('');
  }

  function phase57EventSkeleton() {
    return [
      '<div class="phase57-skeleton-grid">',
      '<div class="phase57-skeleton-line"></div>',
      '<div class="phase57-skeleton-line short"></div>',
      '<div class="phase57-skeleton-line"></div>',
      '</div>',
    ].join('');
  }

  function phase57RealtimeEventStreamPanel() {
    const hydrated = !!state.hydration.lastRefreshAt && !state.hydration.lastRefreshError;
    if (!hydrated) {
      return '<div class="phase57-loading-wrap">' + phase57EventSkeleton() + '</div>';
    }
    const rows = getPhase57RealtimeEvents(28);
    return [
      '<div class="phase57-event-stream-shell">',
      '<div class="phase57-event-stream-head">',
      '<span class="health-op-badge ' + (state.websocketStatus === 'connected' ? 'live' : 'warn') + '">WS ' + escapeHtml(state.websocketStatus) + '</span>',
      '<span class="health-op-badge ' + (state.hydration.lastRefreshError ? 'danger' : 'live') + '">Hydration ' + escapeHtml(state.hydration.lastRefreshError ? 'degraded' : 'stable') + '</span>',
      '<span class="health-op-badge ' + ((state.runtimeReplay && state.runtimeReplay.replay_safe !== false) ? 'live' : 'warn') + '">Replay ' + escapeHtml((state.runtimeReplay && state.runtimeReplay.replay_safe !== false) ? 'safe' : 'watch') + '</span>',
      '</div>',
      '<div id="phase57-event-stream-scroll" class="phase57-event-stream-scroll">',
      (rows.length
        ? rows.map(phase57EventRow).join('')
        : '<p class="health-summary">Realtime event stream is active and waiting for transport operations.</p>'),
      '</div>',
      '</div>',
    ].join('');
  }

  function phase57CoordinationPanel() {
    const assignments = Array.isArray(state.dispatchActiveAssignments) ? state.dispatchActiveAssignments : [];
    const locks = assignments.filter(function (item) { return !!(item && item.ownership_locked); });
    const handoffs = getPhase57RealtimeEvents(40).filter(function (evt) {
      return evt.eventType === 'ownership_handoff';
    });
    const escalations = getPhase57RealtimeEvents(40).filter(function (evt) {
      return evt.eventType === 'escalation_triggered';
    });
    const indicators = [
      '<span class="health-op-badge ' + (locks.length ? 'warn' : 'live') + '">Locks ' + escapeHtml(formatNumber(locks.length)) + '</span>',
      '<span class="health-op-badge ' + (handoffs.length ? 'warn' : 'live') + '">Handoffs ' + escapeHtml(formatNumber(handoffs.length)) + '</span>',
      '<span class="health-op-badge ' + (escalations.length ? 'danger' : 'live') + '">Escalations ' + escapeHtml(formatNumber(escalations.length)) + '</span>',
      '<span class="health-op-badge ' + (state.websocketStatus === 'connected' ? 'live' : 'warn') + '">Status ' + escapeHtml(state.websocketStatus) + '</span>',
    ].join('');

    const ownershipRows = assignments.slice(0, 6).map(function (item) {
      const owner = firstDefined(item && item.ownership_locked_by_user_id, item && item.dispatcher_id, 'unclaimed');
      const lockLabel = item && item.ownership_locked ? 'locked' : 'unlocked';
      return '<article class="phase57-coordination-row">'
        + '<strong>' + escapeHtml(firstDefined(item && item.passenger_name, 'Passenger')) + '</strong>'
        + '<p>Ride ' + escapeHtml(String(firstDefined(item && item.ride_id, '')).slice(0, 8)) + ' · owner ' + escapeHtml(String(owner).slice(0, 8)) + '</p>'
        + '<div class="phase57-coordination-badges">'
        + '<span class="health-op-badge ' + (item && item.ownership_locked ? 'warn' : 'live') + '">' + escapeHtml(lockLabel) + '</span>'
        + '<span class="health-op-badge live">' + escapeHtml(firstDefined(item && item.assignment_state, 'offered')) + '</span>'
        + '</div>'
        + '</article>';
    }).join('');

    return [
      '<div class="phase57-coordination-shell">',
      '<div class="phase57-coordination-indicators">' + indicators + '</div>',
      '<div class="phase57-coordination-grid">',
      '<section>',
      '<h5>Active dispatcher ownership</h5>',
      (ownershipRows || '<p class="health-summary">No active ownership locks currently visible.</p>'),
      '</section>',
      '<section>',
      '<h5>Supervisor escalation status</h5>',
      (escalations.length ? escalations.slice(-6).map(phase57EventRow).join('') : '<p class="health-summary">No supervisor escalations in current runtime window.</p>'),
      '</section>',
      '</div>',
      '<section>',
      '<h5>Handoff visibility</h5>',
      (handoffs.length ? handoffs.slice(-6).map(phase57EventRow).join('') : '<p class="health-summary">No ownership handoffs captured in current runtime window.</p>'),
      '</section>',
      '</div>',
    ].join('');
  }

  function phase57RoleVisualizationPrep() {
    const profile = state.shellProfile && typeof state.shellProfile === 'object' ? state.shellProfile : getSessionProfile();
    const activeRole = getEffectiveShellRole(profile && profile.role);
    const roles = ["dispatcher", "rider", "driver", "provider", "supervisor"];
    const routeMap = {
      rider: "customer",
      supervisor: "admin",
    };
    return '<div class="phase57-role-grid">' + roles.map(function (role) {
      const resolved = routeMap[role] || role;
      const allowedRoutes = getAllowedRoutesForRole(resolved);
      const supported = Array.isArray(allowedRoutes) && allowedRoutes.length > 0;
      const isActive = role === activeRole || (role === "rider" && activeRole === "customer") || (role === "supervisor" && activeRole === "admin");
      return '<article class="phase57-role-card ' + (isActive ? 'active' : '') + '">'
        + '<div class="phase57-role-head"><strong>' + escapeHtml(role) + '</strong><span class="health-op-badge ' + (supported ? 'live' : 'warn') + '">' + (supported ? 'ready' : 'limited') + '</span></div>'
        + '<p>Route visibility: ' + escapeHtml((allowedRoutes || []).join(', ') || 'none') + '</p>'
        + '<small>' + escapeHtml(isActive ? 'Current runtime role' : 'Prepared for additive visualization overlays') + '</small>'
        + '</article>';
    }).join('') + '</div>';
  }

  function hydratePhase57Autoscroll() {
    const container = document.getElementById('phase57-event-stream-scroll');
    if (!container) return;
    const nearBottom = (container.scrollHeight - container.scrollTop - container.clientHeight) < 56;
    if (typeof state.phase57AutoscrollPinned !== 'boolean') {
      state.phase57AutoscrollPinned = true;
    }
    if (state.phase57AutoscrollPinned || nearBottom) {
      container.scrollTop = container.scrollHeight;
      state.phase57AutoscrollPinned = true;
    }
    if (!container.dataset.phase57Bound) {
      container.addEventListener('scroll', function () {
        const pinned = (container.scrollHeight - container.scrollTop - container.clientHeight) < 56;
        state.phase57AutoscrollPinned = pinned;
      }, { passive: true });
      container.dataset.phase57Bound = '1';
    }
    state.phase57LastRenderAt = stampNow();
  }

  function phase58SeverityTone(severity) {
    const level = toLowerSafe(severity);
    if (level === "critical") return "danger";
    if (level === "warning") return "warn";
    return "live";
  }

  function phase58SeverityRank(severity) {
    const level = toLowerSafe(severity);
    if (level === "critical") return 3;
    if (level === "warning") return 2;
    return 1;
  }

  function phase58SeverityFromTone(tone) {
    const t = toLowerSafe(tone);
    if (t === "danger") return "critical";
    if (t === "warn") return "warning";
    return "info";
  }

  function phase58TimeMs(value) {
    const ms = new Date(value || 0).getTime();
    return Number.isNaN(ms) ? 0 : ms;
  }

  function phase58EventAgeSeconds(value) {
    const ts = phase58TimeMs(value);
    if (!ts) return Number.POSITIVE_INFINITY;
    return Math.max(0, (Date.now() - ts) / 1000);
  }

  function phase58RoleFromEventLabel(label) {
    const text = toLowerSafe(label);
    if (text.indexOf("supervisor") !== -1 || text.indexOf("escalation") !== -1) return "supervisor";
    if (text.indexOf("driver") !== -1) return "driver";
    if (text.indexOf("dispatch") !== -1 || text.indexOf("assignment") !== -1 || text.indexOf("ownership") !== -1 || text.indexOf("ride") !== -1) return "dispatcher";
    return "system";
  }

  function phase58IncidentSignals() {
    const rides = Array.isArray(state.rides) ? state.rides : [];
    const assignments = Array.isArray(state.dispatchActiveAssignments) ? state.dispatchActiveAssignments : [];
    const replayQueue = state.runtimeReplay && Array.isArray(state.runtimeReplay.events) ? state.runtimeReplay.events.length : 0;
    const availableDrivers = (Array.isArray(state.drivers) ? state.drivers : []).filter(function (driver) {
      return toLowerSafe(driver && driver.status) === "available";
    }).length;
    const activeRides = rides.filter(function (ride) {
      const status = toLowerSafe(ride && ride.status);
      return status === "accepted" || status === "in_transit";
    }).length;
    const pendingAssignments = assignments.filter(function (item) {
      const assignmentState = toLowerSafe(item && item.assignment_state);
      return assignmentState === "offered" || assignmentState === "pending" || assignmentState === "queued";
    });
    const escalationEvents = getPhase57RealtimeEvents(80).filter(function (item) {
      return item.eventType === "escalation_triggered";
    });
    const reconnectEvents = getPhase57RealtimeEvents(80).filter(function (item) {
      return item.eventType === "websocket_reconnected";
    });
    const delayedRides = rides.filter(function (ride) { return isOverdueRide(ride); });
    const stalledAssignments = pendingAssignments.filter(function (item) {
      const ageSec = phase58EventAgeSeconds(firstDefined(item && item.updated_at, item && item.requested_at, item && item.created_at));
      return ageSec > 600;
    });
    const reconnectStormCount = Math.max(state.reconnectAttempt || 0, reconnectEvents.length);
    const dispatcherLoadRatio = availableDrivers > 0 ? (activeRides / Math.max(1, availableDrivers)) : activeRides;
    const hydrationAgeSec = phase58EventAgeSeconds(state.hydration && state.hydration.lastRefreshAt);
    const orphanedOwnership = assignments.filter(function (item) {
      const assignmentState = toLowerSafe(item && item.assignment_state);
      const active = assignmentState === "offered" || assignmentState === "pending" || assignmentState === "accepted" || assignmentState === "in_transit";
      const locked = Boolean(item && item.ownership_locked);
      const owner = String(firstDefined(item && item.ownership_locked_by_user_id, item && item.dispatcher_id, "")).trim();
      return active && (!locked || !owner);
    });
    const signals = [];

    if (delayedRides.length) {
      signals.push({
        code: "delayed_rides",
        title: "Delayed ride pressure",
        severity: delayedRides.length >= 6 ? "critical" : "warning",
        category: "incident",
        role: "dispatcher",
        timestamp: firstDefined(delayedRides[0] && delayedRides[0].requested_at, stampNow()),
        summary: formatNumber(delayedRides.length) + " rides are overdue against dispatch SLA windows.",
      });
    }

    if (stalledAssignments.length) {
      signals.push({
        code: "stalled_assignments",
        title: "Stalled assignments",
        severity: stalledAssignments.length >= 4 ? "critical" : "warning",
        category: "incident",
        role: "dispatcher",
        timestamp: firstDefined(stalledAssignments[0] && stalledAssignments[0].updated_at, stalledAssignments[0] && stalledAssignments[0].requested_at, stampNow()),
        summary: formatNumber(stalledAssignments.length) + " assignment offers are stalled beyond 10 minutes.",
      });
    }

    if (reconnectStormCount >= 3) {
      signals.push({
        code: "reconnect_storm",
        title: "Reconnect storm",
        severity: reconnectStormCount >= 6 ? "critical" : "warning",
        category: "recovery",
        role: "system",
        timestamp: firstDefined(state.lastRealtimeMessageAt, state.hydration.lastRefreshAt, stampNow()),
        summary: "Reconnect activity has spiked to " + formatNumber(reconnectStormCount) + " recent recovery events.",
      });
    }

    if (state.websocketStatus !== "connected") {
      signals.push({
        code: "websocket_degradation",
        title: "WebSocket degradation",
        severity: state.websocketStatus === "disconnected" ? "critical" : "warning",
        category: "recovery",
        role: "system",
        timestamp: firstDefined(state.lastRealtimeMessageAt, stampNow()),
        summary: "Realtime websocket status is " + String(state.websocketStatus || "idle") + ".",
      });
    }

    if (replayQueue > 60) {
      signals.push({
        code: "replay_backlog_pressure",
        title: "Replay backlog pressure",
        severity: replayQueue > 120 ? "critical" : "warning",
        category: "recovery",
        role: "system",
        timestamp: firstDefined(state.previewRuntimeLastCheck, stampNow()),
        summary: "Replay queue retains " + formatNumber(replayQueue) + " runtime events.",
      });
    }

    if (dispatcherLoadRatio > 1.3 || escalationEvents.length > 0) {
      signals.push({
        code: "dispatcher_overload",
        title: "Dispatcher overload",
        severity: dispatcherLoadRatio > 2 || escalationEvents.length >= 3 ? "critical" : "warning",
        category: "dispatch",
        role: "dispatcher",
        timestamp: firstDefined(escalationEvents[0] && escalationEvents[0].timestamp, stampNow()),
        summary: "Load ratio " + Number(dispatcherLoadRatio).toFixed(2) + " with " + formatNumber(escalationEvents.length) + " unresolved escalations.",
      });
    }

    if ((state.hydration && state.hydration.lastRefreshError) || hydrationAgeSec > 180) {
      signals.push({
        code: "hydration_timeout_recovery",
        title: "Hydration timeout recovery",
        severity: hydrationAgeSec > 360 || Boolean(state.hydration && state.hydration.lastRefreshError) ? "critical" : "warning",
        category: "recovery",
        role: "system",
        timestamp: firstDefined(state.hydration && state.hydration.lastRefreshAt, stampNow()),
        summary: state.hydration && state.hydration.lastRefreshError
          ? "Hydration reported error: " + String(state.hydration.lastRefreshError)
          : "Hydration freshness is " + formatNumber(Math.round(hydrationAgeSec)) + "s old.",
      });
    }

    if (orphanedOwnership.length) {
      signals.push({
        code: "orphaned_ride_ownership",
        title: "Orphaned ride ownership",
        severity: orphanedOwnership.length >= 4 ? "critical" : "warning",
        category: "dispatch",
        role: "dispatcher",
        timestamp: firstDefined(orphanedOwnership[0] && orphanedOwnership[0].updated_at, stampNow()),
        summary: formatNumber(orphanedOwnership.length) + " active assignments are missing stable ownership lock context.",
      });
    }

    if (!signals.length) {
      signals.push({
        code: "resilience_nominal",
        title: "Resilience nominal",
        severity: "info",
        category: "incident",
        role: "system",
        timestamp: stampNow(),
        summary: "No critical transport incidents detected in the current retention window.",
      });
    }

    return signals.sort(function (a, b) {
      const scoreDelta = phase58SeverityRank(b.severity) - phase58SeverityRank(a.severity);
      if (scoreDelta !== 0) return scoreDelta;
      return phase58TimeMs(b.timestamp) - phase58TimeMs(a.timestamp);
    }).slice(0, 12);
  }

  function phase58TimelineFilters() {
    const existing = state.phase58TimelineFilters && typeof state.phase58TimelineFilters === "object"
      ? state.phase58TimelineFilters
      : {};
    return {
      severity: toLowerSafe(existing.severity || "all") || "all",
      role: toLowerSafe(existing.role || "all") || "all",
      category: toLowerSafe(existing.category || "all") || "all",
      query: String(existing.query || ""),
    };
  }

  function phase58UnifiedTimeline(limit) {
    const retention = Math.max(60, Math.min(320, Number(limit || state.phase58Retention || 180)));
    const realtimeEntries = getPhase57RealtimeEvents(retention).map(function (item) {
      return {
        source: "runtime",
        category: "runtime",
        role: phase58RoleFromEventLabel(item.eventType),
        severity: phase58SeverityFromTone(item.tone),
        title: item.eventType || "runtime_event",
        summary: item.summary || "Realtime transport event",
        timestamp: item.timestamp || stampNow(),
      };
    });

    const dispatchEntries = (Array.isArray(state.dispatchTimeline) ? state.dispatchTimeline : []).slice(-retention).map(function (item) {
      const kind = toLowerSafe(item && (item.kind || item.type || item.event_type));
      const severity = toLowerSafe(item && item.severity) || (kind.indexOf("escalat") !== -1 ? "warning" : "info");
      const role = kind.indexOf("supervisor") !== -1 || kind.indexOf("escalat") !== -1 ? "supervisor" : "dispatcher";
      return {
        source: "dispatch",
        category: "dispatch",
        role: role,
        severity: severity === "danger" ? "critical" : severity,
        title: String(firstDefined(item && item.kind, item && item.type, "dispatch_event")).replace(/_/g, " "),
        summary: firstDefined(item && item.summary, item && item.message, "Dispatch timeline event"),
        timestamp: firstDefined(item && item.timestamp, item && item.created_at, stampNow()),
      };
    });

    const rideEntries = (Array.isArray(state.rides) ? state.rides : []).filter(function (ride) {
      return isOverdueRide(ride) || Boolean(ride && ride.is_emergency);
    }).slice(0, 40).map(function (ride) {
      return {
        source: "rides",
        category: "ride",
        role: "dispatcher",
        severity: isOverdueRide(ride) ? "warning" : "info",
        title: isOverdueRide(ride) ? "ride_delay_watch" : "ride_priority_signal",
        summary: "Ride " + String(firstDefined(ride && ride.id, "")).slice(0, 8) + " passenger " + String(firstDefined(ride && ride.passenger_name, "Passenger")),
        timestamp: firstDefined(ride && ride.updated_at, ride && ride.requested_at, stampNow()),
      };
    });

    const incidentEntries = phase58IncidentSignals().map(function (signal) {
      return {
        source: "incident",
        category: signal.category || "incident",
        role: signal.role || "system",
        severity: signal.severity || "info",
        title: signal.title || signal.code || "incident",
        summary: signal.summary || "Operational incident signal",
        timestamp: signal.timestamp || stampNow(),
      };
    });

    const merged = realtimeEntries.concat(dispatchEntries, rideEntries, incidentEntries);
    const dedup = {};
    const unique = [];
    merged.forEach(function (entry) {
      const key = [entry.source, entry.category, entry.title, entry.summary, entry.timestamp].join("|");
      if (dedup[key]) return;
      dedup[key] = true;
      unique.push(entry);
    });
    unique.sort(function (a, b) {
      const timeDelta = phase58TimeMs(b.timestamp) - phase58TimeMs(a.timestamp);
      if (timeDelta !== 0) return timeDelta;
      return phase58SeverityRank(b.severity) - phase58SeverityRank(a.severity);
    });
    return unique.slice(0, retention);
  }

  function phase58FilteredTimeline() {
    const filters = phase58TimelineFilters();
    const entries = phase58UnifiedTimeline(state.phase58Retention);
    const query = toLowerSafe(filters.query);
    return entries.filter(function (entry) {
      if (filters.severity !== "all" && toLowerSafe(entry.severity) !== filters.severity) return false;
      if (filters.role !== "all" && toLowerSafe(entry.role) !== filters.role) return false;
      if (filters.category !== "all" && toLowerSafe(entry.category) !== filters.category) return false;
      if (!query) return true;
      const haystack = [entry.title, entry.summary, entry.category, entry.role].join(" ").toLowerCase();
      return haystack.indexOf(query) !== -1;
    });
  }

  function phase58TimelineWindow(entries) {
    const safeEntries = Array.isArray(entries) ? entries : [];
    const windowSize = Math.max(12, Math.min(64, Number(state.phase58TimelineWindowSize || 28)));
    const maxOffset = Math.max(0, safeEntries.length - windowSize);
    const offset = Math.max(0, Math.min(Number(state.phase58TimelineOffset || 0), maxOffset));
    state.phase58TimelineOffset = offset;
    return {
      windowSize: windowSize,
      offset: offset,
      total: safeEntries.length,
      rows: safeEntries.slice(offset, offset + windowSize),
      hasOlder: offset + windowSize < safeEntries.length,
      hasNewer: offset > 0,
    };
  }

  function phase58IncidentManagementPanel() {
    const incidents = phase58IncidentSignals();
    const counts = {
      critical: incidents.filter(function (item) { return toLowerSafe(item.severity) === "critical"; }).length,
      warning: incidents.filter(function (item) { return toLowerSafe(item.severity) === "warning"; }).length,
      info: incidents.filter(function (item) { return toLowerSafe(item.severity) === "info"; }).length,
    };
    const cards = incidents.map(function (signal) {
      const tone = phase58SeverityTone(signal.severity);
      return '<article class="phase58-incident-card ' + escapeHtml(tone) + '">'
        + '<div class="phase58-incident-head"><strong>' + escapeHtml(signal.title || signal.code || 'incident') + '</strong><span class="health-op-badge ' + escapeHtml(tone) + '">' + escapeHtml(signal.severity || 'info') + '</span></div>'
        + '<p>' + escapeHtml(signal.summary || 'Operational incident signal') + '</p>'
        + '<small>' + escapeHtml(signal.category || 'incident') + ' · ' + escapeHtml(signal.role || 'system') + ' · ' + escapeHtml(formatDateShort(signal.timestamp)) + '</small>'
        + '</article>';
    }).join('');

    return '<div class="phase58-incident-shell">'
      + '<div class="phase58-incident-metrics">'
      + '<span class="health-op-badge danger">critical ' + escapeHtml(formatNumber(counts.critical)) + '</span>'
      + '<span class="health-op-badge warn">warning ' + escapeHtml(formatNumber(counts.warning)) + '</span>'
      + '<span class="health-op-badge live">info ' + escapeHtml(formatNumber(counts.info)) + '</span>'
      + '<span class="health-op-badge ' + (state.websocketStatus === 'connected' ? 'live' : 'warn') + '">ws ' + escapeHtml(state.websocketStatus) + '</span>'
      + '</div>'
      + '<div class="phase58-incident-grid">' + cards + '</div>'
      + '</div>';
  }

  function phase58TimelinePanel() {
    const filters = phase58TimelineFilters();
    const filtered = phase58FilteredTimeline();
    const view = phase58TimelineWindow(filtered);
    const rows = view.rows.map(function (entry) {
      const tone = phase58SeverityTone(entry.severity);
      return '<article class="phase58-timeline-row ' + escapeHtml(tone) + '">'
        + '<div class="phase58-timeline-main">'
        + '<strong>' + escapeHtml(entry.title || 'timeline_event') + '</strong>'
        + '<p>' + escapeHtml(entry.summary || 'Operational timeline event') + '</p>'
        + '</div>'
        + '<div class="phase58-timeline-meta">'
        + '<span class="health-op-badge ' + escapeHtml(tone) + '">' + escapeHtml(entry.severity || 'info') + '</span>'
        + '<span class="health-op-badge live">' + escapeHtml(entry.category || 'runtime') + '</span>'
        + '<span class="health-op-badge">' + escapeHtml(entry.role || 'system') + '</span>'
        + '<small>' + escapeHtml(formatDateShort(entry.timestamp)) + '</small>'
        + '</div>'
        + '</article>';
    }).join('');

    return '<div class="phase58-timeline-shell">'
      + '<div class="phase58-timeline-controls">'
      + '<label>Severity <select data-phase58-filter="severity">'
      + '<option value="all"' + (filters.severity === 'all' ? ' selected' : '') + '>all</option>'
      + '<option value="critical"' + (filters.severity === 'critical' ? ' selected' : '') + '>critical</option>'
      + '<option value="warning"' + (filters.severity === 'warning' ? ' selected' : '') + '>warning</option>'
      + '<option value="info"' + (filters.severity === 'info' ? ' selected' : '') + '>info</option>'
      + '</select></label>'
      + '<label>Role <select data-phase58-filter="role">'
      + '<option value="all"' + (filters.role === 'all' ? ' selected' : '') + '>all</option>'
      + '<option value="dispatcher"' + (filters.role === 'dispatcher' ? ' selected' : '') + '>dispatcher</option>'
      + '<option value="driver"' + (filters.role === 'driver' ? ' selected' : '') + '>driver</option>'
      + '<option value="supervisor"' + (filters.role === 'supervisor' ? ' selected' : '') + '>supervisor</option>'
      + '<option value="system"' + (filters.role === 'system' ? ' selected' : '') + '>system</option>'
      + '</select></label>'
      + '<label>Category <select data-phase58-filter="category">'
      + '<option value="all"' + (filters.category === 'all' ? ' selected' : '') + '>all</option>'
      + '<option value="incident"' + (filters.category === 'incident' ? ' selected' : '') + '>incident</option>'
      + '<option value="runtime"' + (filters.category === 'runtime' ? ' selected' : '') + '>runtime</option>'
      + '<option value="dispatch"' + (filters.category === 'dispatch' ? ' selected' : '') + '>dispatch</option>'
      + '<option value="ride"' + (filters.category === 'ride' ? ' selected' : '') + '>ride</option>'
      + '<option value="recovery"' + (filters.category === 'recovery' ? ' selected' : '') + '>recovery</option>'
      + '</select></label>'
      + '<label>Search <input type="search" data-phase58-filter="query" value="' + escapeHtml(filters.query) + '" placeholder="timeline search" /></label>'
      + '</div>'
      + '<div class="phase58-timeline-windowing">'
      + '<button type="button" class="health-row-btn secondary" data-phase58-nav="newer"' + (view.hasNewer ? '' : ' disabled') + '>Newer</button>'
      + '<span class="health-summary">Showing ' + escapeHtml(formatNumber(view.offset + 1)) + '-' + escapeHtml(formatNumber(Math.min(view.offset + view.windowSize, view.total))) + ' of ' + escapeHtml(formatNumber(view.total)) + '</span>'
      + '<button type="button" class="health-row-btn secondary" data-phase58-nav="older"' + (view.hasOlder ? '' : ' disabled') + '>Older</button>'
      + '</div>'
      + '<div class="phase58-timeline-stream">'
      + (rows || '<p class="health-summary">No timeline events matched current filters.</p>')
      + '</div>'
      + '</div>';
  }

  function phase58DispatchLoadPanel() {
    const assignments = Array.isArray(state.dispatchActiveAssignments) ? state.dispatchActiveAssignments : [];
    const rides = Array.isArray(state.rides) ? state.rides : [];
    const replayQueue = state.runtimeReplay && Array.isArray(state.runtimeReplay.events) ? state.runtimeReplay.events.length : 0;
    const reconnectEvents = getPhase57RealtimeEvents(80).filter(function (item) { return item.eventType === 'websocket_reconnected'; }).length;
    const escalations = getPhase57RealtimeEvents(80).filter(function (item) { return item.eventType === 'escalation_triggered'; }).length;
    const activeRides = rides.filter(function (ride) {
      const status = toLowerSafe(ride && ride.status);
      return status === 'accepted' || status === 'in_transit';
    }).length;
    const pendingAssignments = assignments.filter(function (item) {
      const assignmentState = toLowerSafe(item && item.assignment_state);
      return assignmentState === 'offered' || assignmentState === 'pending' || assignmentState === 'queued';
    }).length;

    const ownerMap = {};
    assignments.forEach(function (item) {
      const owner = String(firstDefined(item && item.ownership_locked_by_user_id, item && item.dispatcher_id, 'unclaimed')).slice(0, 8) || 'unclaimed';
      if (!ownerMap[owner]) {
        ownerMap[owner] = { owner: owner, active: 0, pending: 0, escalations: 0 };
      }
      ownerMap[owner].active += 1;
      const assignmentState = toLowerSafe(item && item.assignment_state);
      if (assignmentState === 'offered' || assignmentState === 'pending' || assignmentState === 'queued') {
        ownerMap[owner].pending += 1;
      }
    });

    const ownerCards = Object.keys(ownerMap).slice(0, 8).map(function (ownerKey) {
      const row = ownerMap[ownerKey];
      const load = row.active + row.pending;
      const tone = load > 6 ? 'danger' : load > 3 ? 'warn' : 'live';
      return '<article class="phase58-load-card">'
        + '<div class="phase58-load-head"><strong>' + escapeHtml(row.owner) + '</strong><span class="health-op-badge ' + tone + '">load ' + escapeHtml(formatNumber(load)) + '</span></div>'
        + '<p>active ' + escapeHtml(formatNumber(row.active)) + ' · pending ' + escapeHtml(formatNumber(row.pending)) + '</p>'
        + '</article>';
    }).join('');

    return '<div class="phase58-load-shell">'
      + '<div class="enterprise-inline-grid">'
      + MetricCard('Active rides', formatNumber(activeRides), 'Rides currently executing', activeRides ? 'ok' : 'warn')
      + MetricCard('Unresolved escalations', formatNumber(escalations), 'Supervisor escalation pressure', escalations ? 'danger' : 'ok')
      + MetricCard('Pending assignments', formatNumber(pendingAssignments), 'Offers awaiting resolution', pendingAssignments ? 'warn' : 'ok')
      + MetricCard('WebSocket health', state.websocketStatus === 'connected' ? 'healthy' : state.websocketStatus, 'Realtime dispatch connectivity', state.websocketStatus === 'connected' ? 'ok' : 'warn')
      + MetricCard('Reconnect frequency', formatNumber(reconnectEvents + (state.reconnectAttempt || 0)), 'Recent reconnect pressure in retained window', reconnectEvents + (state.reconnectAttempt || 0) > 4 ? 'warn' : 'ok')
      + MetricCard('Replay queue depth', formatNumber(replayQueue), 'Replay backlog retained in runtime window', replayQueue > 120 ? 'danger' : replayQueue > 60 ? 'warn' : 'ok')
      + '</div>'
      + '<div class="phase58-load-grid">' + (ownerCards || '<p class="health-summary">Dispatcher load cards will appear with active assignments.</p>') + '</div>'
      + '</div>';
  }

  function phase58ResilienceRecoveryPanel() {
    const replayActive = Boolean(state.runtimeReplay && state.runtimeReplay.replay_safe === false);
    const reconnectActive = state.websocketStatus === 'reconnecting' || state.websocketStatus === 'auth_recovering' || Number(state.reconnectAttempt || 0) > 0;
    const websocketDegraded = state.websocketStatus !== 'connected';
    const hydrationRecovering = Boolean(state.hydration && state.hydration.lastRefreshError);
    const staleProtection = phase58EventAgeSeconds(firstDefined(state.lastRealtimeMessageAt, state.hydration && state.hydration.lastRefreshAt)) > 240;
    const banners = [];

    if (reconnectActive) {
      banners.push('<div class="phase58-recovery-banner warn">Reconnect recovery active. Runtime is stabilizing websocket continuity.</div>');
    }
    if (replayActive) {
      banners.push('<div class="phase58-recovery-banner warn">Replay synchronization active. Event ordering is being reconciled.</div>');
    }
    if (websocketDegraded) {
      banners.push('<div class="phase58-recovery-banner danger">WebSocket degraded mode detected. Live dispatch updates may lag.</div>');
    }
    if (hydrationRecovering) {
      banners.push('<div class="phase58-recovery-banner danger">Hydration recovery in progress after refresh instability.</div>');
    }
    if (staleProtection) {
      banners.push('<div class="phase58-recovery-banner warn">Stale event protection enabled. Recent runtime signal freshness is degraded.</div>');
    }
    if (!banners.length) {
      banners.push('<div class="phase58-recovery-banner live">Recovery systems nominal. Realtime and hydration guards are stable.</div>');
    }

    return '<div class="phase58-recovery-shell">'
      + '<div class="phase58-recovery-indicators">'
      + '<span class="health-op-badge ' + (reconnectActive ? 'warn' : 'live') + '">reconnect ' + (reconnectActive ? 'active' : 'clear') + '</span>'
      + '<span class="health-op-badge ' + (replayActive ? 'warn' : 'live') + '">replay sync ' + (replayActive ? 'active' : 'stable') + '</span>'
      + '<span class="health-op-badge ' + (websocketDegraded ? 'danger' : 'live') + '">websocket ' + escapeHtml(state.websocketStatus) + '</span>'
      + '<span class="health-op-badge ' + (hydrationRecovering ? 'danger' : 'live') + '">hydration ' + (hydrationRecovering ? 'recovering' : 'stable') + '</span>'
      + '<span class="health-op-badge ' + (staleProtection ? 'warn' : 'live') + '">stale protection ' + (staleProtection ? 'on' : 'clear') + '</span>'
      + '</div>'
      + '<div class="phase58-recovery-banners">' + banners.join('') + '</div>'
      + '</div>';
  }

  function phase59OperatorContext() {
    const profile = state.shellProfile && typeof state.shellProfile === "object" ? state.shellProfile : getSessionProfile();
    const role = getEffectiveShellRole(profile && profile.role);
    const isSupervisorRole = role === "admin" || role === "supervisor";
    const selectedRideId = state.selectedRideId
      || firstDefined(
        state.dispatchActiveAssignments && state.dispatchActiveAssignments[0] && state.dispatchActiveAssignments[0].ride_id,
        state.rides && state.rides[0] && state.rides[0].id,
        ""
      );
    return {
      role: role,
      isSupervisorRole: isSupervisorRole,
      selectedRideId: String(selectedRideId || ""),
      profile: profile,
    };
  }

  function phase59LifecycleStage(ride) {
    const status = toLowerSafe(ride && ride.status);
    if (status === "pending" || status === "requested") return "requested";
    if (status === "scheduled") return "scheduled";
    if (status === "assigned" || status === "offered") return "assigned";
    if (status === "accepted" || status === "driver_en_route" || status === "en_route" || status === "enroute" || status === "in_transit") return "driver_en_route";
    if (status === "arrived") return "arrived";
    if (status === "onboard" || status === "picked_up" || status === "rider_picked_up") return "rider_picked_up";
    if (status === "completed") return "completed";
    if (status === "cancelled" || status === "canceled") return "canceled";
    if (status === "delayed" || status === "stalled" || isOverdueRide(ride)) return "delayed_stalled";
    return "unknown";
  }

  function phase59LifecycleRows() {
    const rides = Array.isArray(state.rides) ? state.rides : [];
    const stages = {
      requested: [],
      scheduled: [],
      assigned: [],
      driver_en_route: [],
      arrived: [],
      rider_picked_up: [],
      completed: [],
      canceled: [],
      delayed_stalled: [],
      unknown: [],
    };
    rides.forEach(function (ride) {
      const stage = phase59LifecycleStage(ride);
      if (!stages[stage]) stages[stage] = [];
      stages[stage].push(ride);
    });
    return stages;
  }

  function phase59LifecyclePanel() {
    const stages = phase59LifecycleRows();
    const stageOrder = [
      { key: "requested", label: "requested" },
      { key: "scheduled", label: "scheduled" },
      { key: "assigned", label: "assigned" },
      { key: "driver_en_route", label: "driver en route" },
      { key: "arrived", label: "arrived" },
      { key: "rider_picked_up", label: "rider picked up" },
      { key: "completed", label: "completed" },
      { key: "canceled", label: "canceled" },
      { key: "delayed_stalled", label: "delayed/stalled" },
    ];

    const stageCards = stageOrder.map(function (stage) {
      const list = stages[stage.key] || [];
      const tone = stage.key === "delayed_stalled" ? (list.length ? "danger" : "ok") : (list.length ? "warn" : "ok");
      const links = list.slice(0, 4).map(function (ride) {
        const rideId = String(firstDefined(ride && ride.id, ""));
        return '<button type="button" class="health-row-btn secondary" data-phase59-focus-ride="' + escapeHtml(rideId) + '">Ride ' + escapeHtml(rideId.slice(0, 8)) + '</button>';
      }).join('');
      return '<article class="phase59-lifecycle-card">'
        + '<div class="phase59-lifecycle-head"><strong>' + escapeHtml(stage.label) + '</strong><span class="health-op-badge ' + tone + '">' + escapeHtml(formatNumber(list.length)) + '</span></div>'
        + '<p>' + escapeHtml(list.length ? (list.length + ' rides in this lifecycle stage.') : 'No rides in this stage.') + '</p>'
        + '<div class="phase59-lifecycle-links">' + (links || '<span class="health-summary">No rides</span>') + '</div>'
        + '</article>';
    }).join('');

    const unknownCount = (stages.unknown || []).length;
    return '<div class="phase59-lifecycle-shell">'
      + '<div class="phase59-lifecycle-grid">' + stageCards + '</div>'
      + (unknownCount ? '<p class="health-summary">Unknown lifecycle states detected for ' + escapeHtml(formatNumber(unknownCount)) + ' rides. Safe rendering fallback applied.</p>' : '')
      + '</div>';
  }

  function phase59CoordinationSnapshot() {
    const assignments = Array.isArray(state.dispatchActiveAssignments) ? state.dispatchActiveAssignments : [];
    const dispatchTimeline = Array.isArray(state.dispatchTimeline) ? state.dispatchTimeline : [];
    const operatorMap = {};

    assignments.forEach(function (item) {
      const owner = String(firstDefined(item && item.ownership_locked_by_user_id, item && item.dispatcher_id, "unclaimed")).slice(0, 8) || "unclaimed";
      if (!operatorMap[owner]) {
        operatorMap[owner] = {
          id: owner,
          active: 0,
          heartbeatAt: null,
        };
      }
      operatorMap[owner].active += 1;
      operatorMap[owner].heartbeatAt = firstDefined(item && item.updated_at, item && item.requested_at, operatorMap[owner].heartbeatAt, stampNow());
    });

    const sessionRows = Array.isArray(state.adminRoleSessions) ? state.adminRoleSessions : [];
    sessionRows.forEach(function (session) {
      const role = toLowerSafe(session && session.role);
      if (role !== "dispatcher" && role !== "supervisor" && role !== "admin") return;
      const key = String(firstDefined(session && session.user_id, session && session.id, role)).slice(0, 8) || role;
      if (!operatorMap[key]) {
        operatorMap[key] = {
          id: key,
          active: 0,
          heartbeatAt: firstDefined(session && session.updated_at, session && session.created_at, stampNow()),
        };
      }
    });

    const rideOwnerMap = {};
    assignments.forEach(function (item) {
      const rideId = String(firstDefined(item && item.ride_id, "")).slice(0, 12);
      if (!rideId) return;
      if (!rideOwnerMap[rideId]) rideOwnerMap[rideId] = {};
      const owner = String(firstDefined(item && item.ownership_locked_by_user_id, item && item.dispatcher_id, "unclaimed")).slice(0, 8) || "unclaimed";
      rideOwnerMap[rideId][owner] = true;
    });

    const ownershipConflicts = Object.keys(rideOwnerMap).filter(function (rideId) {
      return Object.keys(rideOwnerMap[rideId] || {}).length > 1;
    });

    const handoffRows = dispatchTimeline.filter(function (item) {
      return toLowerSafe(item && (item.kind || item.type || item.event_type)).indexOf("handoff") !== -1;
    });
    const handoffPending = handoffRows.filter(function (item) {
      const text = [item && item.kind, item && item.summary, item && item.message].join(" ").toLowerCase();
      return text.indexOf("pending") !== -1;
    }).length;
    const handoffAccepted = handoffRows.filter(function (item) {
      const text = [item && item.kind, item && item.summary, item && item.message].join(" ").toLowerCase();
      return text.indexOf("accepted") !== -1 || text.indexOf("approved") !== -1;
    }).length;
    const handoffRejected = handoffRows.filter(function (item) {
      const text = [item && item.kind, item && item.summary, item && item.message].join(" ").toLowerCase();
      return text.indexOf("rejected") !== -1 || text.indexOf("denied") !== -1;
    }).length;

    const broadcasts = dispatchTimeline.filter(function (item) {
      const text = [item && item.kind, item && item.summary, item && item.message].join(" ").toLowerCase();
      return text.indexOf("broadcast") !== -1;
    }).length;

    const offeredDriverMap = {};
    assignments.forEach(function (item) {
      const driverId = String(firstDefined(item && item.offered_driver_id, item && item.driver_id, "")).slice(0, 12);
      if (!driverId) return;
      if (!offeredDriverMap[driverId]) offeredDriverMap[driverId] = 0;
      offeredDriverMap[driverId] += 1;
    });
    const assignmentCollisions = Object.keys(offeredDriverMap).filter(function (driverId) {
      return Number(offeredDriverMap[driverId] || 0) > 1;
    });

    return {
      operators: Object.keys(operatorMap).map(function (key) { return operatorMap[key]; }).slice(0, 16),
      ownershipConflicts: ownershipConflicts,
      handoffPending: handoffPending,
      handoffAccepted: handoffAccepted,
      handoffRejected: handoffRejected,
      broadcasts: broadcasts,
      assignmentCollisions: assignmentCollisions,
    };
  }

  function phase59CoordinationFabricPanel() {
    const snapshot = phase59CoordinationSnapshot();
    const operatorRows = (snapshot.operators || []).map(function (row) {
      const ageSec = phase58EventAgeSeconds(row.heartbeatAt);
      const tone = ageSec > 180 ? "warn" : "live";
      return '<article class="phase59-operator-row">'
        + '<strong>' + escapeHtml(row.id || "operator") + '</strong>'
        + '<p>active rides ' + escapeHtml(formatNumber(row.active || 0)) + ' · heartbeat ' + escapeHtml(formatRelativeTime(row.heartbeatAt)) + '</p>'
        + '<span class="health-op-badge ' + tone + '">' + escapeHtml(ageSec > 180 ? 'stale heartbeat' : 'active heartbeat') + '</span>'
        + '</article>';
    }).join('');

    return '<div class="phase59-coordination-shell">'
      + '<div class="enterprise-inline-grid">'
      + MetricCard('Active operators', formatNumber((snapshot.operators || []).length), 'Dispatcher/supervisor presence in coordination fabric', (snapshot.operators || []).length ? 'ok' : 'warn')
      + MetricCard('Ownership conflicts', formatNumber((snapshot.ownershipConflicts || []).length), 'Rides with multi-operator ownership contention', (snapshot.ownershipConflicts || []).length ? 'danger' : 'ok')
      + MetricCard('Handoff pending', formatNumber(snapshot.handoffPending || 0), 'Handoffs awaiting supervisor visibility', (snapshot.handoffPending || 0) ? 'warn' : 'ok')
      + MetricCard('Handoff accepted', formatNumber(snapshot.handoffAccepted || 0), 'Accepted/approved handoff transitions', (snapshot.handoffAccepted || 0) ? 'ok' : 'warn')
      + MetricCard('Handoff rejected', formatNumber(snapshot.handoffRejected || 0), 'Rejected/denied handoff transitions', (snapshot.handoffRejected || 0) ? 'warn' : 'ok')
      + MetricCard('Supervisor broadcasts', formatNumber(snapshot.broadcasts || 0), 'Operational broadcast visibility in timeline', (snapshot.broadcasts || 0) ? 'warn' : 'ok')
      + MetricCard('Assignment collisions', formatNumber((snapshot.assignmentCollisions || []).length), 'Drivers concurrently targeted by multiple assignments', (snapshot.assignmentCollisions || []).length ? 'danger' : 'ok')
      + '</div>'
      + '<section class="phase59-operator-list">'
      + '<h5>Multi-operator heartbeat</h5>'
      + (operatorRows || '<p class="health-summary">Operator presence unavailable; coordination fabric is fail-closed.</p>')
      + '</section>'
      + '</div>';
  }

  function phase59SupervisorControlModel() {
    const context = phase59OperatorContext();
    const incidents = phase58IncidentSignals();
    const assignments = Array.isArray(state.dispatchActiveAssignments) ? state.dispatchActiveAssignments : [];
    const escalationEvents = getPhase57RealtimeEvents(80).filter(function (item) {
      return item.eventType === "escalation_triggered";
    });
    const recommendations = typeof getUnifiedOperationalRecommendations === "function"
      ? getUnifiedOperationalRecommendations("dispatch_actions", 6)
      : [];
    const handoffVisibility = phase59CoordinationSnapshot();
    const lockCount = assignments.filter(function (item) { return Boolean(item && item.ownership_locked); }).length;
    const reviewState = (escalationEvents.length > 0 || incidents.some(function (item) { return toLowerSafe(item.severity) !== "info"; }))
      ? "review_required"
      : "nominal";

    return {
      context: context,
      incidents: incidents,
      escalationEvents: escalationEvents,
      recommendations: Array.isArray(recommendations) ? recommendations : [],
      handoffVisibility: handoffVisibility,
      lockCount: lockCount,
      reviewState: reviewState,
      controls: [
        {
          key: "ack_escalation",
          label: "Escalation acknowledgement",
          mode: "read-only",
          detail: "Visibility only. Endpoint support not detected in current operations contract.",
        },
        {
          key: "supervisor_review",
          label: "Supervisor review state",
          mode: "read-only",
          detail: "Computed from escalation and incident signals.",
        },
        {
          key: "reassignment_visibility",
          label: "Reassignment recommendation visibility",
          mode: "read-only",
          detail: "Derived from dispatch recommendation stream.",
        },
        {
          key: "handoff_approval_visibility",
          label: "Dispatch handoff approval visibility",
          mode: "read-only",
          detail: "Derived from dispatch timeline handoff states.",
        },
        {
          key: "override_intent_log",
          label: "Override intent logging",
          mode: "active",
          detail: "Logs supervisor intent to runtime execution events without unsafe mutation.",
        },
        {
          key: "supervisor_lock_indicators",
          label: "Supervisor lock indicators",
          mode: "read-only",
          detail: "Uses ownership lock metadata from active assignments.",
        },
      ],
    };
  }

  function phase59SupervisorControlPanel() {
    const model = phase59SupervisorControlModel();
    const context = model.context || {};
    const controlRows = (model.controls || []).map(function (control) {
      const mode = toLowerSafe(control.mode);
      const tone = mode === "active" ? "live" : "warn";
      const disabled = mode === "active" ? "" : " disabled";
      return '<article class="phase59-control-row">'
        + '<div class="phase59-control-head"><strong>' + escapeHtml(control.label || control.key) + '</strong><span class="health-op-badge ' + tone + '">' + escapeHtml(mode) + '</span></div>'
        + '<p>' + escapeHtml(control.detail || '') + '</p>'
        + '<button type="button" class="health-row-btn secondary" data-phase59-supervisor-action="' + escapeHtml(control.key || '') + '"' + disabled + '>Log</button>'
        + '</article>';
    }).join('');

    const recRows = (model.recommendations || []).slice(0, 4).map(function (item) {
      const title = firstDefined(item && item.title, item && item.summary, item && item.kind, "recommendation");
      const summary = firstDefined(item && item.summary, item && item.message, "Dispatch recommendation");
      return '<li><strong>' + escapeHtml(String(title)) + '</strong><p>' + escapeHtml(String(summary)) + '</p></li>';
    }).join('');

    return '<div class="phase59-supervisor-shell">'
      + '<div class="enterprise-inline-grid">'
      + MetricCard('Supervisor role', context.isSupervisorRole ? 'active' : context.role, 'Current shell role for intervention controls', context.isSupervisorRole ? 'ok' : 'warn')
      + MetricCard('Review state', model.reviewState || 'nominal', 'Supervisor review gate from incident/escalation context', model.reviewState === 'review_required' ? 'warn' : 'ok')
      + MetricCard('Escalations', formatNumber((model.escalationEvents || []).length), 'Current escalation events in retained runtime window', (model.escalationEvents || []).length ? 'danger' : 'ok')
      + MetricCard('Handoff pending', formatNumber(model.handoffVisibility && model.handoffVisibility.handoffPending || 0), 'Pending handoff approvals visible to supervisor', model.handoffVisibility && model.handoffVisibility.handoffPending ? 'warn' : 'ok')
      + MetricCard('Lock indicators', formatNumber(model.lockCount || 0), 'Active ownership locks requiring supervisor visibility', model.lockCount ? 'warn' : 'ok')
      + MetricCard('Selected ride', context.selectedRideId ? String(context.selectedRideId).slice(0, 8) : 'none', 'Supervisor context target for visibility overlays', context.selectedRideId ? 'ok' : 'warn')
      + '</div>'
      + '<div class="phase59-supervisor-grid">'
      + '<section><h5>Supervisor intervention controls</h5>' + (controlRows || '<p class="health-summary">No supervisor controls available.</p>') + '</section>'
      + '<section><h5>Reassignment recommendations</h5>' + (recRows ? '<ul class="phase59-supervisor-list">' + recRows + '</ul>' : '<p class="health-summary">No reassignment recommendations available.</p>') + '</section>'
      + '</div>'
      + '</div>';
  }

  function phase59ResilienceEscalationVisibilityPanel() {
    const incidentSignals = phase58IncidentSignals().filter(function (item) {
      return toLowerSafe(item.severity) === "warning" || toLowerSafe(item.severity) === "critical";
    });
    const escalationEvents = getPhase57RealtimeEvents(120).filter(function (item) {
      return item.eventType === "escalation_triggered";
    });
    const reconnectEvents = getPhase57RealtimeEvents(120).filter(function (item) {
      return item.eventType === "websocket_reconnected";
    });
    const replayQueue = state.runtimeReplay && Array.isArray(state.runtimeReplay.events) ? state.runtimeReplay.events.length : 0;
    const hydrationAge = phase58EventAgeSeconds(state.hydration && state.hydration.lastRefreshAt);
    const oldestEscalationAge = escalationEvents.length ? Math.round(phase58EventAgeSeconds(escalationEvents[0] && escalationEvents[0].timestamp)) : 0;
    const oldestIncidentAge = incidentSignals.length ? Math.round(phase58EventAgeSeconds(incidentSignals[incidentSignals.length - 1] && incidentSignals[incidentSignals.length - 1].timestamp)) : 0;
    const staleSuppression = phase58EventAgeSeconds(firstDefined(state.lastRealtimeMessageAt, state.hydration && state.hydration.lastRefreshAt)) > 240;
    const hydrationRecovering = Boolean(state.hydration && state.hydration.lastRefreshError);
    const repeatedReconnect = reconnectEvents.length + Number(state.reconnectAttempt || 0);
    const replayPersistent = replayQueue > 60;
    const recoveryConfirmed = state.websocketStatus === "connected"
      && !hydrationRecovering
      && !staleSuppression
      && !replayPersistent
      && repeatedReconnect < 3;

    return '<div class="phase59-resilience-shell">'
      + '<div class="enterprise-inline-grid">'
      + MetricCard('Escalation age', oldestEscalationAge ? (formatNumber(oldestEscalationAge) + 's') : 'none', 'Age of oldest escalation signal', oldestEscalationAge > 900 ? 'danger' : oldestEscalationAge > 300 ? 'warn' : 'ok')
      + MetricCard('Unresolved incident age', oldestIncidentAge ? (formatNumber(oldestIncidentAge) + 's') : 'none', 'Age of oldest unresolved incident signal', oldestIncidentAge > 900 ? 'danger' : oldestIncidentAge > 300 ? 'warn' : 'ok')
      + MetricCard('Repeated reconnect', formatNumber(repeatedReconnect), 'Reconnect incidents in current retained runtime window', repeatedReconnect >= 6 ? 'danger' : repeatedReconnect >= 3 ? 'warn' : 'ok')
      + MetricCard('Replay backlog persistence', replayPersistent ? 'persistent' : 'clear', 'Replay queue persistence under resilience watch', replayPersistent ? 'warn' : 'ok')
      + MetricCard('Hydration recovery', hydrationRecovering ? 'recovering' : 'stable', 'Hydration error and freshness recovery state', hydrationRecovering ? 'danger' : hydrationAge > 180 ? 'warn' : 'ok')
      + MetricCard('Stale suppression', staleSuppression ? 'active' : 'clear', 'Stale event suppression status', staleSuppression ? 'warn' : 'ok')
      + MetricCard('Recovery confirmation', recoveryConfirmed ? 'confirmed' : 'pending', 'Runtime resilience confirmation state', recoveryConfirmed ? 'ok' : 'warn')
      + '</div>'
      + '</div>';
  }

  function phase59OperationalAnalyticsPanel() {
    const rides = Array.isArray(state.rides) ? state.rides : [];
    const assignments = Array.isArray(state.dispatchActiveAssignments) ? state.dispatchActiveAssignments : [];
    const escalations = getPhase57RealtimeEvents(120).filter(function (item) { return item.eventType === 'escalation_triggered'; }).length;
    const reconnects = getPhase57RealtimeEvents(120).filter(function (item) { return item.eventType === 'websocket_reconnected'; }).length + Number(state.reconnectAttempt || 0);
    const replayRecoveries = getPhase57RealtimeEvents(120).filter(function (item) { return item.eventType === 'replay_synchronized'; }).length;
    const hydrationWarnings = (state.hydration && state.hydration.lastRefreshError ? 1 : 0) + (phase58EventAgeSeconds(state.hydration && state.hydration.lastRefreshAt) > 180 ? 1 : 0);

    const completedRides = rides.filter(function (ride) { return toLowerSafe(ride && ride.status) === 'completed'; });
    const pendingRides = rides.filter(function (ride) {
      const status = toLowerSafe(ride && ride.status);
      return status === 'pending' || status === 'scheduled' || status === 'offered' || status === 'assigned';
    });

    const assignmentDelays = assignments.map(function (item) {
      const start = phase58TimeMs(firstDefined(item && item.requested_at, item && item.created_at));
      const stop = phase58TimeMs(firstDefined(item && item.updated_at, item && item.accepted_at, item && item.assigned_at));
      if (!start || !stop || stop <= start) return null;
      return (stop - start) / 1000;
    }).filter(function (value) { return value != null; });
    const avgAssignmentDelay = assignmentDelays.length
      ? (assignmentDelays.reduce(function (sum, value) { return sum + value; }, 0) / assignmentDelays.length)
      : 0;

    const pendingAges = pendingRides.map(function (ride) {
      return phase58EventAgeSeconds(firstDefined(ride && ride.requested_at, ride && ride.created_at));
    }).filter(function (value) { return Number.isFinite(value); });
    const avgPendingAge = pendingAges.length
      ? (pendingAges.reduce(function (sum, value) { return sum + value; }, 0) / pendingAges.length)
      : 0;

    const ownerLoad = {};
    assignments.forEach(function (item) {
      const owner = String(firstDefined(item && item.ownership_locked_by_user_id, item && item.dispatcher_id, 'unclaimed')).slice(0, 8) || 'unclaimed';
      if (!ownerLoad[owner]) ownerLoad[owner] = 0;
      ownerLoad[owner] += 1;
    });
    const loads = Object.keys(ownerLoad).map(function (key) { return ownerLoad[key]; });
    const maxLoad = loads.length ? Math.max.apply(Math, loads) : 0;
    const minLoad = loads.length ? Math.min.apply(Math, loads) : 0;
    const loadBalance = loads.length ? (maxLoad - minLoad) : 0;

    return '<div class="phase59-analytics-shell">'
      + '<div class="enterprise-inline-grid">'
      + MetricCard('Dispatch throughput', formatNumber(completedRides.length), 'Completed rides in active runtime snapshot', completedRides.length ? 'ok' : 'warn')
      + MetricCard('Avg assignment delay', avgAssignmentDelay ? (formatNumber(Math.round(avgAssignmentDelay)) + 's') : 'n/a', 'Average assignment resolution delay', avgAssignmentDelay > 600 ? 'danger' : avgAssignmentDelay > 240 ? 'warn' : 'ok')
      + MetricCard('Pending ride age', avgPendingAge ? (formatNumber(Math.round(avgPendingAge)) + 's') : 'n/a', 'Average pending ride age', avgPendingAge > 900 ? 'danger' : avgPendingAge > 300 ? 'warn' : 'ok')
      + MetricCard('Unresolved escalations', formatNumber(escalations), 'Escalation count in retained runtime window', escalations ? 'danger' : 'ok')
      + MetricCard('Load balance delta', formatNumber(loadBalance), 'Difference between max and min dispatcher load', loadBalance > 4 ? 'danger' : loadBalance > 2 ? 'warn' : 'ok')
      + MetricCard('Reconnect frequency', formatNumber(reconnects), 'Reconnect incidents in retained window', reconnects >= 6 ? 'danger' : reconnects >= 3 ? 'warn' : 'ok')
      + MetricCard('Replay recovery count', formatNumber(replayRecoveries), 'Replay synchronization events in retained window', replayRecoveries ? 'ok' : 'warn')
      + MetricCard('Hydration warning count', formatNumber(hydrationWarnings), 'Hydration error/freshness warning indicators', hydrationWarnings ? 'warn' : 'ok')
      + '</div>'
      + '</div>';
  }

  function filteredRides() {
    const q = String(state.filters.query || "").toLowerCase();
    return state.rides.filter((ride) => {
      const rideStatus = String(ride.status || "").toLowerCase();
      const priority = getPriorityTag(ride);
      const providerMatch = state.filters.provider === "all" || String(ride.provider_id || "") === state.filters.provider;
      const driverMatch = state.filters.driver === "all" || String(ride.driver_id || "") === state.filters.driver;
      const statusMatch = state.filters.status === "all" || rideStatus === state.filters.status;
      const priorityMatch = state.filters.priority === "all" || priority === state.filters.priority;
      const queryMatch = !q
        || String(ride.passenger_name || "").toLowerCase().includes(q)
        || String((ride.id || "").slice(0, 8)).toLowerCase().includes(q)
        || String(ride.id || "").toLowerCase().includes(q);
      return providerMatch && driverMatch && statusMatch && priorityMatch && queryMatch;
    }).sort((a, b) => {
      const scoreA = Number(a.priority_score || 0);
      const scoreB = Number(b.priority_score || 0);
      if (scoreA !== scoreB) return scoreB - scoreA;
      const ta = new Date(a.requested_at || 0).getTime();
      const tb = new Date(b.requested_at || 0).getTime();
      return tb - ta;
    });
  }

  function queueSplit(rides) {
    const pending = [];
    const active = [];
    const completed = [];
    const problem = [];
    rides.forEach((ride) => {
      const status = String(ride.status || "").toLowerCase();
      if (status === "pending") pending.push(ride);
      else if (status === "accepted" || status === "in_transit") active.push(ride);
      else if (status === "completed") completed.push(ride);
      if (status === "cancelled" || hasOperationalWarning(ride)) {
        problem.push(ride);
      }
    });
    return { pending, active, completed, problem };
  }

  function formatDateShort(value) {
    if (!value) return "-";
    const dt = new Date(value);
    if (Number.isNaN(dt.getTime())) return "-";
    return dt.toLocaleString();
  }

  function renderRideCard(ride) {
    const priorityTag = getPriorityTag(ride);
    const realtime = state.rideRealtimeEvents[ride.id];
    const liveState = realtime ? "Synced " + formatDateShort(realtime.updatedAt) : "Awaiting sync";
    const recommendationRows = (state.aiSnapshot
      && state.aiSnapshot.recommendations
      && Array.isArray(state.aiSnapshot.recommendations.dispatcher_recommendation_payloads)
      ? state.aiSnapshot.recommendations.dispatcher_recommendation_payloads
      : []).filter(function (item) {
        return String(item.ride_id || "") === String(ride.id || "");
      }).slice(0, 1);
    const recommendationText = recommendationRows.length
      ? String(recommendationRows[0].summary || recommendationRows[0].explanation || "AI recommendation available")
      : "Monitoring for AI dispatch recommendations";
    const warningBadges = [];
    if (isOverdueRide(ride)) warningBadges.push('<span class="health-op-badge warn">Overdue</span>');
    if (!ride.driver_id && String(ride.status || "").toLowerCase() !== "completed") warningBadges.push('<span class="health-op-badge warn">Driver Needed</span>');
    if (String(ride.status || "").toLowerCase() === "cancelled") warningBadges.push('<span class="health-op-badge danger">Cancelled</span>');
    if (Boolean(ride.is_emergency) || ["emergency", "urgent", "high"].includes(priorityTag)) warningBadges.push('<span class="health-op-badge danger">High Priority</span>');

    return [
      '<article class="health-ride-card ' + ((Boolean(ride.is_emergency) || priorityTag === "emergency") ? "emergency" : "") + '" data-ride-card-id="' + ride.id + '">',
      '<div class="health-ride-card-header">',
      '<div class="health-ride-card-title">' + escapeHtml(ride.passenger_name || "Unknown Passenger") + '</div>',
      '<span class="health-priority-badge ' + priorityTag + '">' + escapeHtml(priorityTag) + '</span>',
      '</div>',
      '<div class="health-ride-meta">',
      '<div><strong>ID:</strong> ' + escapeHtml((ride.id || "").slice(0, 8)) + '</div>',
      '<div><strong>Pickup:</strong> ' + escapeHtml(ride.pickup_address || "-") + '</div>',
      '<div><strong>Dropoff:</strong> ' + escapeHtml(ride.dropoff_address || "-") + '</div>',
      '<div><strong>Provider:</strong> ' + escapeHtml(lookupProviderName(ride.provider_id)) + '</div>',
      '<div><strong>Driver:</strong> ' + escapeHtml(lookupDriverName(ride.driver_id)) + '</div>',
      '<div><strong>Status:</strong> <span class="health-pill ' + pillClass(ride.status) + '">' + escapeHtml(ride.status || "unknown") + '</span></div>',
      '<div><strong>Scheduled:</strong> ' + escapeHtml(formatDateShort(ride.appointment_time)) + '</div>',
      '<div><strong>Duration:</strong> ' + escapeHtml(String(ride.estimated_duration_minutes || "-")) + ' min</div>',
      '<div><strong>Dispatch Score:</strong> ' + escapeHtml(String(ride.priority_score || "-")) + '</div>',
      '</div>',
      '<div class="health-ride-operational">',
      '<span class="health-op-badge live">' + escapeHtml(liveState) + '</span>',
      warningBadges.join(""),
      '</div>',
      '<p class="health-summary">AI: ' + escapeHtml(recommendationText) + '</p>',
      '<div class="health-assign-wrap">' + driverAssignControl(ride) + '</div>',
      '<div class="health-ride-actions">',
      '<button class="health-row-btn" data-card-action="assign" data-ride-id="' + ride.id + '">Assign or Reassign</button>',
      '<button class="health-row-btn danger" data-card-action="cancel" data-ride-id="' + ride.id + '">Cancel Ride</button>',
      '<button class="health-row-btn warn" data-card-action="arrived" data-ride-id="' + ride.id + '" data-driver-id="' + (ride.driver_id || "") + '">Mark Arrived</button>',
      '<button class="health-row-btn" data-card-action="onboard" data-ride-id="' + ride.id + '" data-driver-id="' + (ride.driver_id || "") + '">Mark Onboard</button>',
      '<button class="health-row-btn ok" data-card-action="complete" data-ride-id="' + ride.id + '" data-driver-id="' + (ride.driver_id || "") + '">Complete Trip</button>',
      '<button class="health-row-btn secondary" data-card-action="escalate" data-ride-id="' + ride.id + '">Escalate Issue</button>',
      '<button class="health-row-btn secondary" data-card-action="retry-workflow" data-ride-id="' + ride.id + '">Retry Failed Workflow</button>',
      '<button class="health-row-btn" data-card-action="details" data-ride-id="' + ride.id + '">Open Details</button>',
      '</div>',
      '</article>',
    ].join("");
  }

  function renderQueue(targetEl, rides, emptyText) {
    if (!targetEl) return;
    targetEl.innerHTML = rides.length ? rides.map(renderRideCard).join("") : '<p class="health-summary">' + escapeHtml(emptyText) + '</p>';
  }

  function disconnectRealtimeSocket() {
    if (state.socket) {
      try {
        state.socket.close();
      } catch (_err) {}
      state.socket = null;
    }
    if (state.reconnectTimer) {
      clearTimeout(state.reconnectTimer);
      state.reconnectTimer = null;
    }
  }

  function getRealtimeSubscriptionsForRole(role) {
    const normalizedRole = String(role || "guest").toLowerCase();
    if (normalizedRole === "driver") {
      return ["driver_dashboard", "ride_updates"];
    }
    if (normalizedRole === "provider") {
      return ["ride_updates", "workflow_events"];
    }
    if (normalizedRole === "customer") {
      return ["ride_updates", "workflow_events"];
    }
    if (normalizedRole === "analytics") {
      return ["ride_updates", "driver_availability"];
    }
    return ["dispatcher_board", "ride_updates", "workflow_events", "driver_availability"];
  }

  async function connectRealtimeSocket() {
    if (!state.active || state.socket) return;
    
    // Ensure session is restored from localStorage before attempting connection
    if (window.AmiCorSession && typeof window.AmiCorSession.restore === "function") {
      const currentSession = window.AmiCorSession.getCurrent();
      if (!currentSession) {
        const restored = window.AmiCorSession.restore();
        logDiag("Session restored from storage", { restored: !!restored });
      }
    }
    
    if (window.AmiCorSession && typeof window.AmiCorSession.refreshAccessToken === "function") {
      try {
        await window.AmiCorSession.refreshAccessToken(false);
      } catch (_err) {}
    }

    const ctx = getWsContext();
    if (!ctx) {
      console.warn("[Health ISF] Unable to get WebSocket context - will retry");
      state.websocketStatus = "auth_required";
      renderAIOperations();
      return;
    }
    
    const protocol = window.location.protocol === "https:" ? "wss" : "ws";
    const url = protocol + "://" + window.location.host + "/api/health-isf/ws/live/"
      + encodeURIComponent(ctx.organizationId) + "/" + encodeURIComponent(ctx.userId)
      + "?role=" + encodeURIComponent(ctx.role)
      + "&token=" + encodeURIComponent(ctx.token);
    const socket = new WebSocket(url);
    state.socket = socket;
    state.websocketStatus = "connecting";
    renderAIOperations();

    socket.addEventListener("open", () => {
      resetRealtimeBackoff();
      state.websocketStatus = "connected";
      state.lastRealtimeConnectAtMs = nowMs();
      state.lastRealtimeActivityAtMs = state.lastRealtimeConnectAtMs;
      const activeRole = getEffectiveShellRole((state.shellProfile && state.shellProfile.role) || ctx.role);
      const subs = getRealtimeSubscriptionsForRole(activeRole);
      subs.forEach((subscriptionType) => {
        socket.send(JSON.stringify({ type: "subscribe", subscription_type: subscriptionType }));
      });
      logDiag("WebSocket open", { role: activeRole, subscriptions: subs });
      renderAIOperations();
    });

    socket.addEventListener("message", (event) => {
      const message = parseRealtimeMessage(event.data);
      if (!message) return;
      if (message.type === "batch") {
        (message.events || []).forEach((item) => {
          applyRealtimeUpdate(item);
        });
        return;
      }
      logDiag("WebSocket message", {
        eventType: message.eventType,
        rideId: getRealtimeRideId(message.payload) || null,
        timestamp: message.timestamp,
      });
      const dedupKey = [message.eventType, getRealtimeRideId(message.payload), getRealtimeDriverId(message.payload), message.timestamp].join(":");
      if (state.realtimeDedup.indexOf(dedupKey) !== -1) return;
      state.realtimeDedup.unshift(dedupKey);
      state.realtimeDedup = state.realtimeDedup.slice(0, 100);
      state.lastRealtimeMessageAt = message.timestamp;
      state.lastRealtimeActivityAtMs = nowMs();
      applyRealtimeUpdate(message);
      const normalizedType = String(message.eventType || "").toLowerCase().replace(/-/g, "_");
      const normalizedDispatchEvent = String(message.payload && message.payload.event_name ? message.payload.event_name : "").toLowerCase().replace(/-/g, "_");
      if (["ride_created", "ride_status_changed", "ride_assigned", "ride_reassigned", "ride_escalated", "ride_retry", "ride_completed", "pickup_completed", "driver_status_changed", "driver_active_ride_state", "ride_lifecycle_sync", "workflow_recovery_completed", "workflow_reassignment_executed", "workflow_escalated", "intelligence_recommendations", "intelligence_summary", "intelligence_risk", "orchestration_update", "autonomous_operations_snapshot", "dispatch_changed", "ride_approved", "ride_dispatchable", "driver_offer_issued", "driver_offer_accepted", "ride_in_progress", "provider_request_created"].includes(normalizedType)
        || ["ride_approved", "ride_dispatchable", "driver_offer_issued", "driver_offer_accepted", "driver_location_updated", "ride_in_progress", "ride_completed", "provider_request_created"].includes(normalizedDispatchEvent)) {
        scheduleRealtimeRefresh();
      }
    });

    socket.addEventListener("close", async (event) => {
      if (state.socket === socket) {
        state.socket = null;
      }
      const code = Number(event && event.code ? event.code : 0);
      const reason = String(event && event.reason ? event.reason : "");
      const authFailure = code === 1008 || code === 4401 || code === 4403 || /auth|token|401|403/i.test(reason);
      state.websocketStatus = authFailure ? "auth_required" : "reconnecting";
      logDiag("WebSocket closed", { active: state.active, code: code || null, reason, authFailure });
      renderAIOperations();

      if (authFailure && window.AmiCorSession && typeof window.AmiCorSession.refreshAccessToken === "function") {
        try {
          const recovered = await window.AmiCorSession.refreshAccessToken(true);
          if (recovered) {
            scheduleRealtimeReconnect("auth_refresh_success", true);
            return;
          }
        } catch (_err) {}
      }
      if (state.active) {
        scheduleRealtimeReconnect(authFailure ? "auth_failure" : "socket_closed", authFailure);
      }
    });

    socket.addEventListener("error", () => {
      state.websocketStatus = "error";
      logDiag("WebSocket error", {});
      renderAIOperations();
      try {
        socket.close();
      } catch (_err) {}
      scheduleRealtimeReconnect("socket_error", false);
    });
  }

  function mergeRideState(rideId, patch) {
    const idx = state.rides.findIndex((item) => item.id === rideId);
    if (idx < 0) return;
    state.rides[idx] = Object.assign({}, state.rides[idx], patch || {});
  }

  function applyRealtimeUpdate(message) {
    const normalizedType = String(message && message.eventType ? message.eventType : "").toLowerCase().replace(/-/g, "_");
    const dispatchEventName = String(message && message.payload && message.payload.event_name ? message.payload.event_name : "").toLowerCase();
    const normalizedDispatchEvent = dispatchEventName.replace(/-/g, "_");
    const payload = message && message.payload && typeof message.payload === "object" ? message.payload : {};
    const payloadDetails = getRealtimePayloadDetails(payload);
    const rideId = getRealtimeRideId(payload);
    const driverId = getRealtimeDriverId(payload);
    state.lastRealtimeMessageAt = message.timestamp || stampNow();
    state.websocketDiagnostics = Object.assign({}, state.websocketDiagnostics || {}, {
      lastMessageAt: state.lastRealtimeMessageAt,
      lastEventType: message.eventType,
      lastSource: message.source || "websocket",
    });
    recordOperationalEvent(message, "websocket");
    
    // Track event for UI feedback
    if (rideId) {
      state.rideRealtimeEvents[rideId] = {
        eventType: message.eventType,
        updatedAt: message.timestamp,
      };
    }

    // Handle ride_created event
    if ((normalizedType === "ride_created" || normalizedType === "ride_created") && rideId) {
      const newRide = {
        id: rideId,
        passenger_name: String(firstDefined(payload.passenger_name, payloadDetails.passenger_name, payloadDetails.passengerName, "Unknown") || "Unknown"),
        status: String(firstDefined(payload.status, payloadDetails.status, "pending") || "pending"),
        priority_score: Number(firstDefined(payload.priority_score, payloadDetails.priority_score, 0) || 0),
        priority_tag: String(firstDefined(payload.priority_tag, payloadDetails.priority_tag, "normal") || "normal"),
        driver_id: null,
        provider_id: String(firstDefined(payload.provider_id, payloadDetails.provider_id, "") || ""),
        requested_at: String(firstDefined(payload.requested_at, payloadDetails.requested_at, message.timestamp) || message.timestamp),
      };
      if (!state.rides.find(r => r.id === rideId)) {
        state.rides.unshift(newRide);
      }
      logDiag("Ride created via WebSocket", { rideId: rideId });
    }

    // Handle ride_status_changed event
    if (normalizedType === "ride_status_changed" && rideId) {
      const toStatus = String(firstDefined(payload.to_status, payload.status, payloadDetails.to_status, payloadDetails.status, "") || "");
      mergeRideState(rideId, { status: toStatus });
      logDiag("Ride status changed", { rideId: rideId, toStatus: toStatus });
    }

    if (normalizedType === "dispatch_changed" && normalizedDispatchEvent) {
      if (normalizedDispatchEvent === "ride_approved" || normalizedDispatchEvent === "ride_dispatchable") {
        mergeRideState(rideId, { status: normalizedDispatchEvent === "ride_approved" ? "accepted" : "pending" });
      }
      if (normalizedDispatchEvent === "driver_offer_issued" && rideId) {
        mergeRideState(rideId, { status: "accepted", driver_id: driverId || null });
      }
      if (normalizedDispatchEvent === "driver_offer_accepted" && rideId) {
        mergeRideState(rideId, { status: "accepted", driver_id: driverId || null });
      }
      if (normalizedDispatchEvent === "ride_in_progress" && rideId) {
        mergeRideState(rideId, { status: "in_transit", driver_id: driverId || null });
      }
      if (normalizedDispatchEvent === "ride_completed" && rideId) {
        mergeRideState(rideId, { status: "completed", driver_id: driverId || null });
      }
    }

    // Handle ride_assigned event
    if (normalizedType === "ride_assigned" && rideId) {
      const assignedDriverId = driverId;
      mergeRideState(rideId, { driver_id: assignedDriverId || null, status: "accepted" });
      logDiag("Ride assigned", { rideId: rideId, driverId: assignedDriverId });
    }

    // Handle ride_reassigned event
    if (normalizedType === "ride_reassigned" && rideId) {
      const toDriverId = String(firstDefined(payload.to_driver_id, payloadDetails.to_driver_id, payloadDetails.toDriverId, driverId, "") || "");
      mergeRideState(rideId, { driver_id: toDriverId || null, status: "accepted" });
      logDiag("Ride reassigned", { rideId: rideId, driverId: toDriverId });
    }

    // Handle ride_escalated event
    if (normalizedType === "ride_escalated" && rideId) {
      const reason = String(firstDefined(payload.reason, payload.issue_type, payload.description, payloadDetails.reason, payloadDetails.issue_type, "escalated") || "escalated");
      mergeRideState(rideId, { escalation_reason: reason });
      logDiag("Ride escalated", { rideId: rideId, reason: reason });
    }

    // Handle ride_retry event
    if (normalizedType === "ride_retry" && rideId) {
      const retryCount = Number(message.payload.retry_count || 1);
      mergeRideState(rideId, { retry_count: retryCount, status: "pending" });
      logDiag("Ride retry", { rideId: rideId, retryCount: retryCount });
    }

    // Handle driver_status_changed event
    if (normalizedType === "driver_status_changed" && driverId) {
      const toStatus = String(firstDefined(payload.to_status, payload.status, payload.state, payloadDetails.to_status, payloadDetails.status, payloadDetails.state, "") || "");
      const driverIdx = state.drivers.findIndex(d => d.id === driverId);
      if (driverIdx >= 0) {
        state.drivers[driverIdx] = Object.assign({}, state.drivers[driverIdx], { status: toStatus });
      }
      logDiag("Driver status changed", { driverId: driverId, toStatus: toStatus });
    }

    if (normalizedType === "driver_active_ride_state" && driverId) {
      const activeRideId = String(firstDefined(payload.active_ride_id, payloadDetails.active_ride_id, payloadDetails.activeRideId, "") || "");
      const activeState = String(firstDefined(payload.state, payloadDetails.state, "") || "");
      const driverIdx = state.drivers.findIndex(d => d.id === driverId);
      if (driverIdx >= 0) {
        state.drivers[driverIdx] = Object.assign({}, state.drivers[driverIdx], {
          active_ride_id: activeRideId || null,
          active_ride_state: activeState || null,
          status: activeState === "available" ? "available" : state.drivers[driverIdx].status,
        });
      }
      if (activeRideId) {
        mergeRideState(activeRideId, { driver_id: driverId || null });
      }
    }

    if ((normalizedType === "pickup_completed" || normalizedType === "ride_completed") && rideId) {
      const terminalStatus = normalizedType === "ride_completed" ? "completed" : "in_transit";
      mergeRideState(rideId, { status: terminalStatus, driver_id: driverId || null });
    }

    if (normalizedType === "ride_lifecycle_sync" && rideId) {
      const legacyStatus = String(firstDefined(payload.legacy_status, payload.status, payloadDetails.legacy_status, payloadDetails.status, "") || "");
      const lifecycleState = String(firstDefined(payload.lifecycle_state, payloadDetails.lifecycle_state, "") || "");
      mergeRideState(rideId, {
        status: legacyStatus || undefined,
        lifecycle_state: lifecycleState || undefined,
      });
    }

    // Handle workflow_recovery_completed event
    if (normalizedType === "workflow_recovery_completed" && rideId) {
      const recoveryType = String(message.payload.recovery_type || "unknown");
      logDiag("Workflow recovery completed", { rideId: rideId, recoveryType: recoveryType });
    }

    // Handle workflow_reassignment_executed event
    if (normalizedType === "workflow_reassignment_executed" && rideId) {
      const toDriver = String(message.payload.to_driver_id || "");
      mergeRideState(rideId, { driver_id: toDriver || null });
      logDiag("Workflow reassignment executed", { rideId: rideId, driverId: toDriver });
    }

    // Handle workflow_escalated event
    if (normalizedType === "workflow_escalated" && rideId) {
      const escalationType = String(message.payload.escalation_type || "unknown");
      logDiag("Workflow escalated", { rideId: rideId, escalationType: escalationType });
    }

    // Handle workflow_replay_completed event
    if (normalizedType === "workflow_replay_completed" && rideId) {
      logDiag("Workflow replay completed", { rideId: rideId });
    }

    // Handle intelligence_recommendations event
    if (normalizedType === "intelligence_recommendations" && rideId) {
      const recommendations = message.payload.recommendations || [];
      state.aiRecommendations[rideId] = {
        recommendations: recommendations,
        timestamp: message.timestamp,
      };
      logDiag("Intelligence recommendations received", { rideId: rideId, recommendationCount: recommendations.length });
    }

    if (normalizedType === "intelligence_summary") {
      state.aiSnapshot = state.aiSnapshot || {};
      state.aiSnapshot.summary = Object.assign({}, state.aiSnapshot.summary || {}, message.payload || {});
    }

    if (normalizedType === "intelligence_risk") {
      state.aiSnapshot = state.aiSnapshot || {};
      state.aiSnapshot.orchestration = state.aiSnapshot.orchestration || {};
      state.aiSnapshot.orchestration.system_health = Object.assign(
        {},
        state.aiSnapshot.orchestration.system_health || {},
        (message.payload && message.payload.orchestration) || {}
      );
    }

    if (normalizedType === "orchestration_update") {
      state.aiSnapshot = state.aiSnapshot || {};
      state.aiSnapshot.orchestration = Object.assign({}, state.aiSnapshot.orchestration || {}, message.payload || {});
    }

    if (normalizedType === "autonomous_operations_snapshot") {
      state.aiSnapshot = state.aiSnapshot || {};
      state.aiSnapshot.summary = Object.assign({}, state.aiSnapshot.summary || {}, (message.payload && message.payload.summary) || {});
      state.aiSnapshot.orchestration = Object.assign({}, state.aiSnapshot.orchestration || {}, (message.payload && message.payload.orchestration) || {});
      state.aiSnapshot.assistant = Object.assign({}, state.aiSnapshot.assistant || {}, (message.payload && message.payload.assistant) || {});
      state.aiSnapshot.event_stream = Object.assign({}, state.aiSnapshot.event_stream || {}, (message.payload && message.payload.event_stream) || {});
      state.aiSnapshot.memory_snapshot = Object.assign({}, state.aiSnapshot.memory_snapshot || {}, (message.payload && message.payload.memory_snapshot) || {});
    }

    // Re-render UI components
    renderRides();
    renderDashboard();
    renderDrivers();
    renderProviders();
    renderAnalytics();
    renderAIOperations();
  }

  function lookupProviderName(providerId) {
    if (!providerId) return "-";
    const provider = state.providers.find((item) => item.id === providerId);
    return provider ? provider.name : "-";
  }

  function lookupDriverName(driverId) {
    if (!driverId) return "Unassigned";
    const driver = state.drivers.find((item) => item.id === driverId);
    return driver ? driver.name : "Unknown";
  }

  function getCurrentRole() {
    if (!window.AmiCorSession || typeof window.AmiCorSession.getRole !== "function") {
      return "staff";
    }
    return String(window.AmiCorSession.getRole() || "staff").toLowerCase();
  }

  function canMutateRides() {
    return ["admin", "dispatcher", "staff"].includes(getCurrentRole());
  }

  function driverWorkflowButtons(ride) {
    if (!ride || !ride.driver_id) return "";
    const statusValue = String(ride.status || "").toLowerCase();
    const terminal = statusValue === "completed" || statusValue === "cancelled";
    if (terminal || !canMutateRides()) return "";

    const buttons = [];
    if (statusValue === "accepted") {
      buttons.push(
        '<button class="health-row-btn warn" data-driver-action="arrived" data-ride-id="' + ride.id + '" data-driver-id="' + ride.driver_id + '">Arrived</button>'
      );
    }
    if (statusValue === "accepted") {
      buttons.push(
        '<button class="health-row-btn" data-driver-action="pickup" data-ride-id="' + ride.id + '" data-driver-id="' + ride.driver_id + '">Pickup Done</button>'
      );
    }
    if (statusValue === "in_transit") {
      buttons.push(
        '<button class="health-row-btn ok" data-driver-action="dropoff" data-ride-id="' + ride.id + '" data-driver-id="' + ride.driver_id + '">Dropoff Done</button>'
      );
    }
    return buttons.join("");
  }

  function statusActionButton(ride, status, label) {
    const statusValue = String(ride.status || "").toLowerCase();
    const terminal = statusValue === "completed" || statusValue === "cancelled";
    const disabled = !canMutateRides() || terminal || statusValue === status;
    return (
      '<button class="health-row-btn" data-ride-status="' + status + '" data-ride-id="' + ride.id + '"' +
      (disabled ? " disabled" : "") + ">" + label + "</button>"
    );
  }

  function driverAssignControl(ride) {
    const statusValue = String(ride.status || "").toLowerCase();
    const terminal = statusValue === "completed" || statusValue === "cancelled";
    const options = ['<option value="">Select driver</option>']
      .concat(
        state.drivers.map((driver) => {
          const selected = ride.driver_id === driver.id ? " selected" : "";
          const disabled = String(driver.status || "") !== "available" ? " disabled" : "";
          return '<option value="' + driver.id + '"' + selected + disabled + '>' +
            escapeHtml(driver.name + " (" + driver.status + ")") +
            "</option>";
        })
      )
      .join("");

    if (!canMutateRides()) {
      return '<span class="health-summary">Restricted</span>';
    }

    return [
      '<div class="health-assign-wrap">',
      '<select class="health-driver-select" data-ride-driver-select="' + ride.id + '"' + (terminal ? " disabled" : "") + '">',
      options,
      "</select>",
      '<button class="health-row-btn" data-ride-assign="' + ride.id + '"' + (terminal ? " disabled" : "") + '">Assign Driver</button>',
      "</div>",
    ].join("");
  }

  function renderDashboard() {
    const els = getEls();
    const d = state.dashboard;
    const enterprise = state.enterpriseDashboard || {};
    const enterpriseReady = !!state.enterpriseDashboard && !state.hydration.enterpriseDashboardError && !enterprise.stale;
    if (!els.dashboardCards || !els.dispatchSummary) return;
    if (!d) {
      els.dashboardCards.innerHTML = "<p class=\"health-summary\">Dashboard unavailable.</p>";
      els.dispatchSummary.innerHTML = "No dashboard data available.";
      return;
    }

    const utilization = enterpriseReady ? (enterprise.utilization_metrics || {}) : {};
    const slaStatus = enterpriseReady ? (enterprise.sla_status || {}) : {};
    const freshnessStamp = state.hydration.lastRefreshAt || d.timestamp || null;
    const freshnessAgeMs = freshnessStamp ? Math.max(0, Date.now() - new Date(freshnessStamp).getTime()) : null;
    const freshnessLabel = freshnessStamp ? formatDateShort(freshnessStamp) : "pending";
    const freshnessBadgeClass = freshnessAgeMs !== null && freshnessAgeMs > 90000 ? "warn" : "live";

    const rides = Array.isArray(state.rides) ? state.rides : [];
    const drivers = Array.isArray(state.drivers) ? state.drivers : [];
    const providers = Array.isArray(state.providers) ? state.providers : [];
    const pendingCount = rides.filter(function (ride) { return String(ride.status || '').toLowerCase() === 'pending'; }).length;
    const activeCount = rides.filter(function (ride) { return ['accepted', 'in_transit'].includes(String(ride.status || '').toLowerCase()); }).length;
    const completedToday = rides.filter(function (ride) {
      return String(ride.status || '').toLowerCase() === 'completed';
    }).length;
    const availableDriversCount = drivers.filter(function (driver) {
      return String(driver.status || '').toLowerCase() === 'available';
    }).length;
    const busyDriversCount = drivers.filter(function (driver) {
      return ['assigned', 'busy', 'en_route_pickup', 'waiting_at_pickup', 'in_transit'].includes(String(driver.status || '').toLowerCase());
    }).length;
    const onTimeCount = rides.filter(function (ride) {
      return !isOverdueRide(ride) && ['accepted', 'in_transit', 'completed'].includes(String(ride.status || '').toLowerCase());
    }).length;
    const serviceLevel = rides.length ? Math.round((onTimeCount / rides.length) * 100) : Number(slaStatus.score || 0);
    const providersOnlineCount = providers.filter(function (provider) {
      return String(firstDefined(provider.status, provider.operational_status, 'active') || 'active').toLowerCase() !== 'offline';
    }).length;
    const fleetUtilization = drivers.length ? Math.round((busyDriversCount / drivers.length) * 100) : Number(d.busy_drivers || 0);
    const dispatchPosture = enterpriseReady ? String(enterprise.dispatch_health || 'stable') : 'degraded';
    const workflowHealth = enterpriseReady ? String(enterprise.workflow_health || 'stable') : 'degraded';

    const kpiRows = [
      ['Trips booked today', formatNumber(d.total_rides_today), 'Total ride requests received for today'],
      ['Trips in motion', formatNumber(activeCount || d.active_rides), 'Rides currently in pickup or transport flow'],
      ['Awaiting dispatch', formatNumber(pendingCount || d.pending_rides), 'Requests waiting for assignment'],
      ['Drivers ready', formatNumber(availableDriversCount || d.available_drivers), 'Dispatch-ready drivers in roster'],
      ['Providers online', formatNumber(providersOnlineCount || providers.length || d.total_providers), 'Partner facilities currently active'],
      ['Trips completed', formatNumber(completedToday || d.completed_rides), 'Trips completed in this operating window'],
      ['Service level', formatNumber(serviceLevel) + '%', 'On-time execution performance'],
      ['Dispatch posture', escapeHtml(dispatchPosture), enterpriseReady ? 'Current workload pressure state' : 'Supporting enterprise snapshot unavailable in this refresh'],
      ['Avg trip time', Number(d.average_ride_duration_minutes || 0).toFixed(1) + ' min', 'Average end-to-end trip duration'],
      ['Pending payouts', '$' + Number(d.pending_payouts_usd || 0).toFixed(2), 'Outstanding financial settlements'],
      ['Workflow health', escapeHtml(workflowHealth), enterpriseReady ? 'Operational process health' : 'Supporting enterprise snapshot unavailable in this refresh'],
      ['Fleet utilization', Number(fleetUtilization || utilization.driver_utilization_percent || 0).toFixed(1) + '%', 'Driver capacity currently utilized'],
    ];
    els.dashboardCards.innerHTML = '<div class="enterprise-table-wrap"><table class="health-table"><thead><tr><th>KPI</th><th>Value</th><th>Operational meaning</th></tr></thead><tbody>'
      + kpiRows.map(function (row) {
        return '<tr><td><strong>' + escapeHtml(row[0]) + '</strong></td><td>' + escapeHtml(String(row[1])) + '</td><td>' + escapeHtml(row[2]) + '</td></tr>';
      }).join('')
      + '</tbody></table></div>';

    const sections = [
      ["Pending Rides", state.rides.filter((ride) => String(ride.status || "").toLowerCase() === "pending")],
      ["Assigned Rides", state.rides.filter((ride) => String(ride.status || "").toLowerCase() === "accepted" && ride.driver_id)],
      ["Active Rides", state.rides.filter((ride) => ["accepted", "in_transit"].includes(String(ride.status || "").toLowerCase()))],
      ["Completed Rides", state.rides.filter((ride) => String(ride.status || "").toLowerCase() === "completed")],
      ["Cancelled Rides", state.rides.filter((ride) => String(ride.status || "").toLowerCase() === "cancelled")],
      ["Available Drivers", state.drivers.filter((driver) => String(driver.status || "").toLowerCase() === "available")],
      ["Busy Drivers", state.drivers.filter((driver) => ["assigned", "busy", "en_route_pickup", "waiting_at_pickup", "in_transit"].includes(String(driver.status || "").toLowerCase()))],
      ["Offline Drivers", state.drivers.filter((driver) => ["offline", "unavailable"].includes(String(driver.status || "").toLowerCase()))],
    ];

    const sectionHtml = sections.map(([title, items]) => {
      const cards = (items || []).slice(0, 4).map((item) => {
        if (title.includes("Drivers")) {
          return '<div class="health-flow-item"><strong>' + escapeHtml(item.name || "Unnamed") + '</strong><span class="health-pill ' + pillClass(item.status) + '">' + escapeHtml(item.status || "unknown") + '</span><small>' + escapeHtml((item.vehicle_type || "") + " " + (item.vehicle_plate || "")) + '</small></div>';
        }
        return '<div class="health-flow-item"><strong>' + escapeHtml(item.passenger_name || "Unnamed") + '</strong><span class="health-pill ' + pillClass(item.status) + '">' + escapeHtml(item.status || "unknown") + '</span><small>' + escapeHtml(lookupDriverName(item.driver_id)) + '</small></div>';
      }).join("");
      return '<section class="health-flow-column"><h4>' + escapeHtml(title) + '</h4>' + (cards || '<p class="health-summary">No items.</p>') + '</section>';
    }).join("");

    const loadBadge = getDispatchLoadBadge();
    const liveUpdated = state.lastRealtimeMessageAt ? formatDateShort(state.lastRealtimeMessageAt) : "No realtime feed yet";
    const alertCount = enterpriseReady && Array.isArray(enterprise.operational_alerts) ? enterprise.operational_alerts.length : 0;
    const recommendationCount = enterpriseReady && Array.isArray(enterprise.ai_recommendations) ? enterprise.ai_recommendations.length : 0;
    const operationalSummary = summarySummaryText();

    const riskRides = getRideRows(rides).filter(function (row) {
      return row.delayed || row.emergency || String(row.slaRisk || '').toLowerCase() === 'high';
    }).slice(0, 6);
    const openAlerts = enterpriseReady ? getEnterpriseAlerts().slice(0, 5) : [];
    const openRecommendations = enterpriseReady ? getEnterpriseRecommendations().slice(0, 5) : [];
    const idleDrivers = drivers.filter(function (driver) {
      return String(driver.status || '').toLowerCase() === 'available';
    }).slice(0, 5);
    const completedCount = rides.filter(function (ride) { return String(ride.status || '').toLowerCase() === 'completed'; }).length;
    const cancelledCount = rides.filter(function (ride) { return String(ride.status || '').toLowerCase() === 'cancelled'; }).length;
    const coveragePct = drivers.length ? Math.round((idleDrivers.length / drivers.length) * 100) : 0;
    const providerBottlenecks = providers.map(function (provider) {
      const providerId = String(provider.id || '');
      const queueSize = rides.filter(function (ride) {
        const status = String(ride.status || '').toLowerCase();
        return String(ride.provider_id || '') === providerId && (status === 'pending' || status === 'accepted');
      }).length;
      return {
        id: providerId,
        name: provider.name || 'Provider',
        queueSize: queueSize,
      };
    }).filter(function (item) {
      return item.queueSize > 0;
    }).sort(function (a, b) {
      return b.queueSize - a.queueSize;
    }).slice(0, 4);
    const upcomingCommitments = rides.filter(function (ride) {
      if (!ride || !ride.scheduled_time) return false;
      const status = String(ride.status || '').toLowerCase();
      if (!['pending', 'accepted'].includes(status)) return false;
      const eta = new Date(ride.scheduled_time).getTime();
      if (!Number.isFinite(eta)) return false;
      const deltaMin = Math.round((eta - Date.now()) / 60000);
      return deltaMin >= 0 && deltaMin <= 120;
    }).sort(function (a, b) {
      return new Date(a.scheduled_time).getTime() - new Date(b.scheduled_time).getTime();
    }).slice(0, 6);

    els.dispatchSummary.innerHTML = [
      '<div class="enterprise-panel-grid">',
      '<section class="enterprise-panel-block">',
      '<h4>Urgent ride watch</h4>',
      (riskRides.length ? RideQueue(riskRides) : '<p class="health-summary">No high-risk rides. The active board is on plan.</p>'),
      '</section>',
      '<section class="enterprise-panel-block">',
      '<h4>Dispatcher staffing posture</h4>',
      (idleDrivers.length
        ? '<div class="health-stack-list">' + idleDrivers.map(function (driver) {
            return '<article class="health-stack-item"><div class="health-stack-title-row"><strong>' + escapeHtml(driver.name || 'Driver') + '</strong><span class="health-op-badge ok">ready</span></div><p>' + escapeHtml(driver.vehicle_type || 'Vehicle not listed') + '</p><small>' + escapeHtml(String(driver.status || 'available')) + '</small></article>';
          }).join('') + '</div>'
        : '<p class="health-summary">No immediately available drivers. Consider rebalancing live trips.</p>'),
      '<p class="health-summary"><span class="health-op-badge ' + loadBadge.className + '">' + escapeHtml(loadBadge.text) + '</span> <span class="health-op-badge live">Realtime ' + escapeHtml(liveUpdated) + '</span> <span class="health-op-badge ' + freshnessBadgeClass + '">Sync ' + escapeHtml(freshnessLabel) + '</span></p>',
      '</section>',
      '<section class="enterprise-panel-block">',
      '<h4>Executive service brief</h4>',
      '<div class="enterprise-inline-grid">'
        + MetricCard('Alerts', formatNumber(alertCount), 'Open issues requiring attention', alertCount ? 'warn' : 'ok')
        + MetricCard('AI actions', formatNumber(recommendationCount), 'Recommended interventions prepared', recommendationCount ? 'ok' : 'warn')
        + MetricCard('Completed', formatNumber(d.total_trips_completed), 'Trips closed successfully today', 'ok')
        + MetricCard('Payouts due', '$' + Number(d.pending_payouts_usd || 0).toFixed(2), 'Outstanding provider or driver payouts', Number(d.pending_payouts_usd || 0) > 0 ? 'warn' : 'ok')
      + '</div>',
      (!enterpriseReady ? '<p class="health-summary">Enterprise dashboard adjunct metrics are unavailable for this refresh window. Core dispatch KPIs are rendered from the local operations snapshot only.</p>' : ''),
      '<p class="health-summary">' + escapeHtml(operationalSummary) + '</p>',
      '</section>',
      '</div>',
      '<div class="health-flow-board">',
      sectionHtml,
      '</div>',
      '<div class="enterprise-panel-grid">',
      '<section class="enterprise-panel-block">',
      '<h4>Operational pulse</h4>',
      '<div class="enterprise-inline-grid">'
        + MetricCard('Queue pressure', formatNumber(pendingCount), 'Pending rides currently waiting for dispatch', pendingCount > Math.max(3, idleDrivers.length) ? 'warn' : 'ok')
        + MetricCard('Trips in service', formatNumber(activeCount), 'Rides actively being serviced right now', activeCount ? 'ok' : 'warn')
        + MetricCard('Completed', formatNumber(completedCount), 'Completed rides in current operational window', 'ok')
        + MetricCard('Cancelled', formatNumber(cancelledCount), 'Cancelled rides requiring reason review', cancelledCount ? 'warn' : 'ok')
        + MetricCard('Driver coverage', formatNumber(coveragePct) + '%', 'Share of roster currently available for new work', coveragePct < 25 ? 'warn' : 'ok')
      + '</div>',
      '</section>',
      '<section class="enterprise-panel-block">',
      '<h4>Provider bottlenecks</h4>',
      (providerBottlenecks.length
        ? '<div class="health-stack-list">' + providerBottlenecks.map(function (item) {
            return '<article class="health-stack-item"><div class="health-stack-title-row"><strong>' + escapeHtml(item.name) + '</strong><span class="health-op-badge ' + (item.queueSize >= 4 ? 'warn' : 'ok') + '">queue ' + escapeHtml(String(item.queueSize)) + '</span></div><p>Pending or accepted rides currently tied to this provider.</p></article>';
          }).join('') + '</div>'
        : '<p class="health-summary">No provider-side queue build-up.</p>'),
      '</section>',
      '<section class="enterprise-panel-block">',
      '<h4>Next 2 hours commitments</h4>',
      (upcomingCommitments.length
        ? '<div class="health-stack-list">' + upcomingCommitments.map(function (ride) {
            return '<article class="health-stack-item"><div class="health-stack-title-row"><strong>' + escapeHtml(ride.passenger_name || 'Passenger') + '</strong><span class="health-pill ' + pillClass(ride.status || 'pending') + '">' + escapeHtml(ride.status || 'pending') + '</span></div><p>' + escapeHtml(ride.pickup_address || '-') + ' -> ' + escapeHtml(ride.dropoff_address || '-') + '</p><small>Scheduled ' + escapeHtml(formatDateShort(ride.scheduled_time)) + '</small></article>';
          }).join('') + '</div>'
        : '<p class="health-summary">No near-term scheduled commitments waiting for dispatch.</p>'),
      '</section>',
      '</div>',
      (openAlerts.length ? '<h4>Urgent alerts</h4>' + renderNotificationList(openAlerts, 'No service interruptions.') : ''),
      (openRecommendations.length ? '<h4>Recommended moves</h4>' + renderRecommendationList(openRecommendations, 'No recommended moves.') : ''),
    ].join('');

    const dashboardEls = getEls();
    if (dashboardEls.dashboardOperationalFeed) {
      dashboardEls.dashboardOperationalFeed.innerHTML = renderTimelineList((state.operationalEventFeed || []).slice(0, 10).map(function (item) {
        return {
          kind: item.kind || item.type || item.eventType || 'event',
          summary: item.summary || item.message || 'Operational update',
          timestamp: item.timestamp || item.created_at || stampNow(),
          severity: item.severity || 'info',
        };
      }), 'No active escalations.');
    }
    if (dashboardEls.dashboardRecommendations) {
      dashboardEls.dashboardRecommendations.innerHTML = renderRecommendationList(getUnifiedOperationalRecommendations('dashboard', 8), 'No recommended moves right now.');
    }
    if (dashboardEls.dashboardMemory) {
      dashboardEls.dashboardMemory.innerHTML = recurringTransportPanel();
    }
    if (dashboardEls.dashboardGovernance) {
      dashboardEls.dashboardGovernance.innerHTML = renderNotificationList(openAlerts.slice(0, 8), 'No urgent service alerts.');
    }
    if (dashboardEls.dashboardWebsocket) {
      dashboardEls.dashboardWebsocket.innerHTML = '<div class="enterprise-inline-grid">'
        + MetricCard('Available drivers', formatNumber(drivers.filter(function (driver) { return String(driver.status || '').toLowerCase() === 'available'; }).length), 'Drivers ready for immediate dispatch', 'ok')
        + MetricCard('Busy drivers', formatNumber(drivers.filter(function (driver) { return ['assigned', 'busy', 'en_route_pickup', 'waiting_at_pickup', 'in_transit'].includes(String(driver.status || '').toLowerCase()); }).length), 'Drivers actively servicing riders', 'warn')
        + MetricCard('Online providers', formatNumber(providers.filter(function (provider) { return provider && provider.is_active !== false; }).length), 'Facilities and provider partners online', 'ok')
        + MetricCard('Provider pressure', formatNumber(providerBottlenecks.length), 'Providers with queue pressure above normal', providerBottlenecks.length ? 'warn' : 'ok')
      + '</div>';
    }
    if (dashboardEls.dashboardSync) {
      dashboardEls.dashboardSync.innerHTML = '<div class="enterprise-inline-grid">'
        + MetricCard('Last update', escapeHtml(freshnessLabel), 'Latest full operations refresh across rides, drivers, and providers', freshnessBadgeClass === 'warn' ? 'warn' : 'ok')
        + MetricCard('Dispatch board', escapeHtml(loadBadge.text), 'Current dispatch posture from queue and staffing state', loadBadge.className === 'warn' ? 'warn' : 'ok')
        + MetricCard('Active trips', formatNumber(activeCount), 'Trips currently moving through service', activeCount ? 'ok' : 'warn')
      + '</div>';
    }
  }

  function summarySummaryText() {
    const count = Array.isArray(state.operationalEventFeed) ? state.operationalEventFeed.length : 0;
    if (!count) {
      return 'Dispatch operations are live. Queue, staffing, and provider network are ready.';
    }
    return 'Live operations stream has ' + formatNumber(count) + ' recent events across dispatch, drivers, and providers.';
  }

  function renderNotificationList(items, emptyText) {
    if (!Array.isArray(items) || !items.length) {
      return '<p class="health-summary">' + escapeHtml(emptyText) + '</p>';
    }
    return '<div class="health-stack-list">' + items.map((item) => {
      return [
        '<article class="health-stack-item ' + escapeHtml(item.severity || 'info') + '">',
        '<div class="health-stack-title-row"><strong>' + escapeHtml(item.title || item.type || 'Update') + '</strong><span class="health-op-badge ' + (item.severity === 'high' || item.severity === 'critical' ? 'danger' : item.severity === 'medium' ? 'warn' : 'live') + '">' + escapeHtml(item.severity || 'info') + '</span></div>',
        '<p>' + escapeHtml(item.message || item.summary || '') + '</p>',
        '<small>' + escapeHtml(formatDateShort(item.created_at || item.timestamp)) + '</small>',
        '</article>',
      ].join('');
    }).join('') + '</div>';
  }

  function renderRecommendationList(items, emptyText) {
    if (!Array.isArray(items) || !items.length) {
      return '<p class="health-summary">' + escapeHtml(emptyText) + '</p>';
    }
    return '<div class="health-stack-list">' + items.map((item) => {
      const message = item.summary || item.explanation_summary || item.message || item.action_type || 'Recommendation available';
      return [
        '<article class="health-stack-item accent">',
        '<div class="health-stack-title-row"><strong>' + escapeHtml(item.action_type || item.entity_type || 'AI recommendation') + '</strong><span class="health-op-badge live">AI</span></div>',
        '<p>' + escapeHtml(message) + '</p>',
        (item.ride_id ? '<small>Ride ' + escapeHtml(String(item.ride_id).slice(0, 8)) + '</small>' : '<small>Generated from live operations</small>'),
        '</article>',
      ].join('');
    }).join('') + '</div>';
  }

  function renderTimelineList(items, emptyText) {
    if (!Array.isArray(items) || !items.length) {
      return '<p class="health-summary">' + escapeHtml(emptyText) + '</p>';
    }
    return '<ul class="health-timeline-feed">' + items.map((item) => {
      return '<li><span class="health-pill ' + (item.severity === 'high' ? 'danger' : item.severity === 'medium' ? 'warn' : 'ok') + '">' + escapeHtml(item.kind || 'timeline') + '</span><strong>' + escapeHtml(item.summary || item.title || 'Update') + '</strong><small>' + escapeHtml(formatDateShort(item.timestamp || item.created_at)) + '</small></li>';
    }).join('') + '</ul>';
  }

  function renderAIOperations() {
    const els = getEls();
    const snapshot = state.aiSnapshot;
    if (els.aiTranscript) {
      const transcriptText = state.voice.listening
        ? (state.voice.transcript || '') + (state.voice.interim ? ' ' + state.voice.interim : '')
        : (state.voice.transcript || 'Voice dispatcher ready. Use push-to-talk for commands or ride intake dictation.');
      els.aiTranscript.textContent = transcriptText.trim() || 'Voice dispatcher ready. Use push-to-talk for commands or ride intake dictation.';
    }
    if (els.voicePtt) {
      els.voicePtt.disabled = !state.voice.supported || state.voice.listening;
      els.voicePtt.textContent = state.voice.listening ? 'Listening...' : 'Push to Talk';
    }
    if (els.voiceStop) {
      els.voiceStop.disabled = !state.voice.listening;
    }
    if (!snapshot) {
      if (els.aiOpsCenter) {
        els.aiOpsCenter.innerHTML = op_empty_state('Dispatch intelligence is loading from live transportation activity.', '🧭');
      }
      return;
    }

    if (els.aiOpsCenter) {
      const summary = snapshot.summary || {};
      const assistant = snapshot.assistant || {};
      const recommendations = getUnifiedOperationalRecommendations('operational_summaries', 8);
      const alerts = getEnterpriseAlerts();
      const activeDispatchRows = (state.dispatchQueue || []).slice(0, 8);
      els.aiOpsCenter.innerHTML = [
        '<div class="enterprise-panel-grid">',
        '<section class="enterprise-panel-block">',
        '<h4>Dispatch insight brief</h4>',
        '<div class="enterprise-inline-grid">'
          + MetricCard('Priority focus', escapeHtml(assistant.priority_focus || 'stable flow'), 'Current dispatch focus area', 'ok')
          + MetricCard('Open anomalies', formatNumber(summary.anomaly_count || 0), 'Exceptions detected in active operations', Number(summary.anomaly_count || 0) ? 'warn' : 'ok')
          + MetricCard('Recommended actions', formatNumber(recommendations.length), 'Actionable operations recommendations', recommendations.length ? 'ok' : 'warn')
          + MetricCard('Urgent alerts', formatNumber(alerts.filter(function (a) { return String(a.severity || '').toLowerCase() === 'high' || String(a.severity || '').toLowerCase() === 'critical'; }).length), 'Immediate intervention signals', alerts.length ? 'warn' : 'ok')
        + '</div>',
        '<p class="health-summary">' + escapeHtml(summary.summary || assistant.operational_status || 'Monitoring live transportation operations and preparing interventions.') + '</p>',
        '</section>',
        '<section class="enterprise-panel-block">',
        '<h4>Active dispatch queue</h4>',
        (activeDispatchRows.length
          ? '<div class="enterprise-table-wrap"><table class="health-table"><thead><tr><th>Passenger</th><th>Ride</th><th>State</th><th>Attempt</th><th>Suggested action</th></tr></thead><tbody>'
            + activeDispatchRows.map(function (item) {
              const suggestion = firstDefined(item.recommendation, item.assignment_state, 'review assignment');
              return '<tr><td><strong>' + escapeHtml(item.passenger_name || 'Passenger') + '</strong></td><td>' + escapeHtml(String(item.ride_id || '').slice(0, 8)) + '</td><td>' + StatusPill(item.assignment_state || 'queued') + '</td><td>' + escapeHtml(String(item.attempt_index || 0)) + '</td><td>' + escapeHtml(suggestion) + '</td></tr>';
            }).join('')
            + '</tbody></table></div>'
          : '<p class="health-summary">No queue items waiting for dispatch intelligence.</p>'),
        '</section>',
        '</div>',
      ].join('');
    }

    if (els.aiRecommendations) {
      els.aiRecommendations.innerHTML = renderRecommendationList(getUnifiedOperationalRecommendations('operational_summaries', 8), 'No dispatcher recommendations right now.');
    }
    if (els.aiAlerts) {
      els.aiAlerts.innerHTML = renderNotificationList(snapshot.alerts || [], 'No operational alerts at the moment.');
    }
    if (els.aiNotifications) {
      els.aiNotifications.innerHTML = renderNotificationList(snapshot.notifications || [], 'No new operations notifications.');
    }
    if (els.aiTimeline) {
      const timelineItems = state.selectedOperationalTimeline.length ? state.selectedOperationalTimeline : (snapshot.timeline || []);
      els.aiTimeline.innerHTML = renderTimelineList(timelineItems.slice(0, 12), 'Waiting for transportation event timeline updates.');
    }
  }

  function renderRides() {
    const els = getEls();
    if (!els.queuePending || !els.queueActive || !els.queueCompleted || !els.queueProblem) return;

    const rides = filteredRides();
    const queues = queueSplit(rides);
    const rideRows = getRideRows(rides);
    const enterprise = state.enterpriseDashboard || {};
    const delayedCount = rides.filter(isOverdueRide).length;
    const emergencyCount = rides.filter(function (ride) { return Boolean(ride.is_emergency); }).length;
    const highRiskCount = rideRows.filter(function (ride) { return String(ride.slaRisk || "").toLowerCase() === "high"; }).length;
    const lifecycleRows = buildLifecycleRows();
    renderQueue(els.queuePending, queues.pending, "No pending rides.");
    renderQueue(els.queueActive, queues.active, "No active rides.");
    renderQueue(els.queueCompleted, queues.completed, "No completed rides.");
    renderQueue(els.queueProblem, queues.problem, "No delayed or problem rides.");

    if (els.queuePendingCount) els.queuePendingCount.textContent = String(queues.pending.length);
    if (els.queueActiveCount) els.queueActiveCount.textContent = String(queues.active.length);
    if (els.queueCompletedCount) els.queueCompletedCount.textContent = String(queues.completed.length);
    if (els.queueProblemCount) els.queueProblemCount.textContent = String(queues.problem.length);
    if (els.customerQueueMetrics) {
      const queue = state.customerQueueMetrics || {};
      els.customerQueueMetrics.innerHTML = '<div class="enterprise-inline-grid">'
        + MetricCard('Pending', formatNumber(queue.pending || 0), 'Customer requests waiting for dispatch broadcast', (queue.pending || 0) ? 'warn' : 'ok')
        + MetricCard('Approved', formatNumber(queue.approved || 0), 'Dispatcher-approved requests ready for controlled dispatch', (queue.approved || 0) ? 'warn' : 'ok')
        + MetricCard('Dispatchable', formatNumber(queue.dispatchable || 0), 'Requests staged for assignment offer generation', (queue.dispatchable || 0) ? 'warn' : 'ok')
        + MetricCard('Broadcasted', formatNumber(queue.broadcasted || 0), 'Requests currently pushed to available drivers', (queue.broadcasted || 0) ? 'warn' : 'ok')
        + MetricCard('Accepted', formatNumber(queue.accepted || 0), 'Driver accepted notification', (queue.accepted || 0) ? 'ok' : 'warn')
        + MetricCard('Assigned', formatNumber(queue.assigned || 0), 'Dispatch-assigned transportation requests', (queue.assigned || 0) ? 'ok' : 'warn')
        + MetricCard('In Progress', formatNumber(queue.in_progress || 0), 'Active customer transportation rides', (queue.in_progress || 0) ? 'warn' : 'ok')
        + MetricCard('Completed', formatNumber(queue.completed || 0), 'Completed customer rides', (queue.completed || 0) ? 'ok' : 'warn')
        + '</div>';
    }

    if (els.dispatchIntelQueue) {
      const queueRows = Array.isArray(state.dispatchQueue) ? state.dispatchQueue : [];
      const searching = queueRows.filter(function (item) { return String(item.assignment_state || '').toLowerCase() === 'searching'; }).length;
      const offered = queueRows.filter(function (item) { return String(item.assignment_state || '').toLowerCase() === 'offered'; }).length;
      const reassignment = queueRows.filter(function (item) { return String(item.assignment_state || '').toLowerCase() === 'reassignment_pending'; }).length;
      const listHtml = queueRows.length
        ? '<div class="health-stack-list">' + queueRows.slice(0, 8).map(function (item) {
            const aging = item.requested_at ? formatRelativeTime(item.requested_at) : 'n/a';
            return '<article class="health-stack-item">'
              + '<div class="health-stack-title-row"><strong>' + escapeHtml(item.passenger_name || 'Passenger') + '</strong><span class="health-pill ' + pillClass(item.assignment_state || 'queued') + '">' + escapeHtml(item.assignment_state || 'queued') + '</span></div>'
              + '<p>Ride ' + escapeHtml(String(item.ride_id || '').slice(0, 8)) + ' · attempt ' + escapeHtml(String(item.attempt_index || 0)) + ' · age ' + escapeHtml(aging) + '</p>'
              + '<small>Offered driver: ' + escapeHtml(item.offered_driver_id ? String(item.offered_driver_id).slice(0, 8) : 'none') + '</small>'
              + '</article>';
          }).join('') + '</div>'
        : '<p class="health-summary">Dispatch queue is clear.</p>';
      els.dispatchIntelQueue.innerHTML = '<div class="enterprise-inline-grid">'
        + MetricCard('Queue Depth', formatNumber(queueRows.length), 'Total rides in dispatch intelligence queue', queueRows.length ? 'warn' : 'ok')
        + MetricCard('Searching', formatNumber(searching), 'Rides currently in driver search stage', searching ? 'warn' : 'ok')
        + MetricCard('Offered', formatNumber(offered), 'Offers awaiting driver response', offered ? 'warn' : 'ok')
        + MetricCard('Reassignment', formatNumber(reassignment), 'Rides waiting reassignment', reassignment ? 'danger' : 'ok')
        + '</div>' + listHtml;
    }

    if (els.dispatchActiveAssignments) {
      const activeRows = Array.isArray(state.dispatchActiveAssignments) ? state.dispatchActiveAssignments : [];
      els.dispatchActiveAssignments.innerHTML = activeRows.length
        ? '<div class="health-stack-list">' + activeRows.slice(0, 10).map(function (item) {
            const expires = item.offer_expires_at ? formatRelativeTime(item.offer_expires_at) : 'n/a';
            const owner = item.ownership_locked_by_user_id ? String(item.ownership_locked_by_user_id).slice(0, 8) : 'unlocked';
            const ownerTone = item.ownership_locked ? (item.ownership_is_current_user ? 'live' : 'warn') : 'ok';
            const ownerText = item.ownership_locked
              ? (item.ownership_is_current_user ? 'my lock ' + owner : 'locked ' + owner)
              : 'unlocked';
            return '<article class="health-stack-item">'
              + '<div class="health-stack-title-row"><strong>' + escapeHtml(item.driver_name || 'Driver') + '</strong><span class="health-pill ' + pillClass(item.assignment_state || 'offered') + '">' + escapeHtml(item.assignment_state || 'offered') + '</span></div>'
              + '<p>Ride ' + escapeHtml(String(item.ride_id || '').slice(0, 8)) + ' · passenger ' + escapeHtml(item.passenger_name || 'Passenger') + '</p>'
              + '<small>Attempt ' + escapeHtml(String(item.attempt_index || 0)) + ' · score ' + escapeHtml(String(item.score != null ? Number(item.score).toFixed(3) : '-')) + ' · expiry ' + escapeHtml(expires) + '</small>'
              + '<div class="health-shell-chip" data-tone="' + ownerTone + '">Owner ' + escapeHtml(ownerText) + '</div>'
              + '<div style="margin-top:6px;display:flex;gap:6px;flex-wrap:wrap;">'
              + '<button class="health-row-btn" data-dispatch-claim-ride="' + escapeHtml(item.ride_id || '') + '">Claim</button>'
              + '<button class="health-row-btn secondary" data-dispatch-handoff-ride="' + escapeHtml(item.ride_id || '') + '">Handoff</button>'
              + '<button class="health-row-btn warn" data-dispatch-supervisor-escalate="' + escapeHtml(item.ride_id || '') + '">Supervisor</button>'
              + '</div>'
              + '</article>';
          }).join('') + '</div>'
        : '<p class="health-summary">No active assignment offers.</p>';
    }

    if (els.dispatchTimeline) {
      const timelineRows = Array.isArray(state.dispatchTimeline) ? state.dispatchTimeline : [];
      els.dispatchTimeline.innerHTML = timelineRows.length
        ? renderTimelineList(timelineRows.map(function (item) {
            return {
              kind: item.kind || item.type || item.event_type || 'dispatch',
              summary: item.summary || item.message || 'Dispatch intelligence event',
              timestamp: item.timestamp || item.created_at || stampNow(),
              severity: item.severity || 'info',
            };
          }), 'Dispatch timeline awaiting events...')
        : '<p class="health-summary">Dispatch timeline awaiting events...</p>';
    }

    if (els.rideWorkflowProof) {
      const proofPayload = state.selectedRideWorkflowProof && typeof state.selectedRideWorkflowProof === 'object'
        ? state.selectedRideWorkflowProof
        : null;
      if (!proofPayload) {
        els.rideWorkflowProof.innerHTML = '<p class="health-summary">Select a ride to load workflow proof.</p>';
      } else {
        const proof = proofPayload.proof && typeof proofPayload.proof === 'object' ? proofPayload.proof : {};
        const proofItems = Object.keys(proof).map(function (key) {
          const ok = Boolean(proof[key]);
          return '<li><span class="health-pill ' + (ok ? 'ok' : 'warn') + '">' + (ok ? 'ok' : 'pending') + '</span><strong>' + escapeHtml(key.replace(/_/g, ' ')) + '</strong></li>';
        }).join('');
        els.rideWorkflowProof.innerHTML = '<h4>End-to-End Workflow Proof</h4>'
          + '<p class="health-summary">Ride ' + escapeHtml(String(proofPayload.ride_id || '').slice(0, 12)) + ' · Request status ' + escapeHtml(String(proofPayload.customer_request_status || 'n/a')) + '</p>'
          + '<ul class="health-timeline-feed">' + (proofItems || '<li><strong>No proof markers yet.</strong></li>') + '</ul>';
      }
    }

    if (els.ridesTable) {
      els.ridesTable.hidden = false;
      els.ridesTable.innerHTML = [
        '<div class="enterprise-section">',
        '<div class="enterprise-metric-grid">',
        MetricCard('Active rides', enterprise.active_rides != null ? enterprise.active_rides : queues.active.length, 'Trips actively being serviced right now', 'ok'),
        MetricCard('Pending requests', enterprise.pending_rides != null ? enterprise.pending_rides : queues.pending.length, 'Requests still waiting for assignment', 'warn'),
        MetricCard('Emergency rides', emergencyCount, 'High-priority trips needing immediate eyes', emergencyCount ? 'danger' : 'ok'),
        MetricCard('Delayed rides', delayedCount, 'Trips currently outside expected timing', delayedCount ? 'danger' : 'ok'),
        MetricCard('High SLA risk', highRiskCount, 'Trips likely to miss expectations if untouched', highRiskCount ? 'danger' : 'warn'),
        MetricCard('Realtime update', state.lastRealtimeMessageAt ? formatRelativeTime(state.lastRealtimeMessageAt) : 'pending', 'Most recent live dispatch refresh', state.websocketStatus === 'connected' ? 'ok' : 'warn'),
        '</div>',
        '<div class="enterprise-panel-grid">',
        '<section class="enterprise-panel-block">',
        '<h4>Priority dispatch queue</h4>',
        RideQueue(rideRows.slice(0, 10)),
        '</section>',
        '<section class="enterprise-panel-block">',
        '<h4>Risk desk</h4>',
        AlertPanel(getEnterpriseAlerts().slice(0, 6), 'No ride-side operational alerts.'),
        '<h4>Recommended interventions</h4>',
        renderRecommendationList(getUnifiedOperationalRecommendations('operational_summaries', 6), 'No dispatch interventions recommended right now.'),
        '</section>',
        '</div>',
        '<div class="enterprise-panel-grid">',
        '<section class="enterprise-panel-block">',
        '<h4>Trip progression</h4>',
        lifecycleProgressionPanel(lifecycleRows),
        '</section>',
        '<section class="enterprise-panel-block">',
        '<h4>Dispatcher ownership and handoffs</h4>',
        dispatchOwnershipPanel(),
        '</section>',
        '</div>',
        '<div class="enterprise-panel-grid">',
        '<section class="enterprise-panel-block">',
        '<h4>Recurring and scheduled transportation</h4>',
        recurringTransportPanel(),
        '</section>',
        '<section class="enterprise-panel-block">',
        '<h4>Incident intervention queue</h4>',
        phase58IncidentManagementPanel(),
        '</section>',
        '</div>',
        '<div class="enterprise-panel-grid">',
        '<section class="enterprise-panel-block">',
        '<h4>Supervisor assist lane</h4>',
        phase59SupervisorControlPanel(),
        '</section>',
        '<section class="enterprise-panel-block">',
        '<h4>Live coordination timeline</h4>',
        renderTimelineList((state.dispatchTimeline || []).map(function (item) {
          return {
            kind: item.kind || item.type || item.event_type || 'dispatch',
            summary: item.summary || item.message || 'Dispatch event',
            timestamp: item.timestamp || item.created_at || stampNow(),
            severity: item.severity || 'info',
          };
        }).slice(0, 12), 'No live coordination events yet.'),
        '</section>',
        '</div>',
        '</div>',
      ].join('');
    }

  }

  function renderDispatchWorkspace() {
    const els = getEls();
    if (!els.dispatchWorklist || !els.dispatchWorkflow || !els.dispatchAssignments) return;

    const rides = getRideRows(filteredRides()).filter(function (row) {
      const status = String(row.status || '').toLowerCase();
      return ['pending', 'accepted', 'in_transit', 'assigned'].indexOf(status) !== -1;
    });
    const drivers = getDriverRows();
    const assignableDrivers = drivers.filter(function (driver) {
      const availability = String(driver.availability || '').toLowerCase();
      return availability === 'available' || availability === 'assigned';
    });
    const driverOptions = assignableDrivers.map(function (driver) {
      return '<option value="' + escapeHtml(driver.id) + '">' + escapeHtml(driver.name) + ' (' + escapeHtml(driver.availability || driver.status) + ')</option>';
    }).join('');

    els.dispatchWorklist.innerHTML = rides.length
      ? '<div class="enterprise-table-wrap"><table class="health-table"><thead><tr><th>Ride</th><th>Passenger</th><th>Status</th><th>Priority</th><th>Driver assignment</th><th>Actions</th></tr></thead><tbody>'
        + rides.slice(0, 30).map(function (ride) {
          return '<tr>'
            + '<td><strong>' + escapeHtml(String(ride.id || '').slice(0, 10)) + '</strong></td>'
            + '<td>' + escapeHtml(ride.passengerName || 'Passenger') + '</td>'
            + '<td><span class="health-pill ' + pillClass(ride.status || 'pending') + '">' + escapeHtml(ride.status || 'pending') + '</span></td>'
            + '<td>' + escapeHtml(getPriorityTag(ride.raw || {}) || 'normal') + '</td>'
            + '<td><select data-dispatch-driver-select="' + escapeHtml(ride.id) + '"><option value="">Select driver</option>' + driverOptions + '</select></td>'
            + '<td><div class="health-row-actions health-row-actions-inline">'
            + '<button class="health-row-btn" data-dispatch-assign="' + escapeHtml(ride.id) + '">Assign</button>'
            + '<button class="health-row-btn secondary" data-dispatch-select-ride="' + escapeHtml(ride.id) + '">Focus</button>'
            + '<button class="health-row-btn warn" data-dispatch-status="cancelled" data-dispatch-ride="' + escapeHtml(ride.id) + '">Cancel</button>'
            + '</div></td>'
            + '</tr>';
        }).join('')
        + '</tbody></table></div>'
      : '<p class="health-summary">No rides currently waiting in dispatch worklist.</p>';

    els.dispatchWorkflow.innerHTML = renderTimelineList((state.dispatchTimeline || []).slice(0, 20).map(function (item) {
      return {
        kind: item.kind || item.type || item.event_type || 'dispatch',
        summary: item.summary || item.message || 'Dispatch workflow event',
        timestamp: item.timestamp || item.created_at || stampNow(),
        severity: item.severity || 'info',
      };
    }), 'Dispatch workflow timeline is waiting for live events.');

    const assignments = Array.isArray(state.dispatchActiveAssignments) ? state.dispatchActiveAssignments : [];
    els.dispatchAssignments.innerHTML = assignments.length
      ? '<div class="enterprise-table-wrap"><table class="health-table"><thead><tr><th>Ride</th><th>Passenger</th><th>Driver</th><th>State</th><th>Offer expiry</th><th>Score</th></tr></thead><tbody>'
        + assignments.slice(0, 30).map(function (item) {
          return '<tr>'
            + '<td>' + escapeHtml(String(item.ride_id || '').slice(0, 10)) + '</td>'
            + '<td>' + escapeHtml(item.passenger_name || 'Passenger') + '</td>'
            + '<td>' + escapeHtml(item.driver_name || item.driver_id || 'Unassigned') + '</td>'
            + '<td><span class="health-pill ' + pillClass(item.assignment_state || 'offered') + '">' + escapeHtml(item.assignment_state || 'offered') + '</span></td>'
            + '<td>' + escapeHtml(item.offer_expires_at ? formatRelativeTime(item.offer_expires_at) : 'n/a') + '</td>'
            + '<td>' + escapeHtml(String(item.score != null ? Number(item.score).toFixed(3) : '-')) + '</td>'
            + '</tr>';
        }).join('')
        + '</tbody></table></div>'
      : '<p class="health-summary">No active dispatch assignments.</p>';
  }

  function renderBillingWorkspace() {
    const els = getEls();
    if (!els.billingKpis || !els.billingClaims || !els.billingAging) return;

    const rides = Array.isArray(state.rides) ? state.rides : [];
    const completed = rides.filter(function (ride) {
      return String(ride.status || '').toLowerCase() === 'completed';
    });
    const inProgress = rides.filter(function (ride) {
      const status = String(ride.status || '').toLowerCase();
      return status === 'accepted' || status === 'in_transit';
    });
    const cancelled = rides.filter(function (ride) {
      return String(ride.status || '').toLowerCase() === 'cancelled';
    });

    const totalBilled = completed.reduce(function (sum, ride) {
      const fare = Number(firstDefined(ride.fare_amount, ride.total_amount, ride.total_fare, ride.payout_amount, ride.estimated_distance_miles ? Number(ride.estimated_distance_miles) * 2.4 : 0) || 0);
      return sum + (Number.isFinite(fare) ? fare : 0);
    }, 0);
    const pendingPayout = Number((state.dashboard && state.dashboard.pending_payouts_usd) || 0);

    els.billingKpis.innerHTML = '<div class="enterprise-table-wrap"><table class="health-table"><thead><tr><th>Metric</th><th>Value</th><th>Operational meaning</th></tr></thead><tbody>'
      + '<tr><td><strong>Total billed today</strong></td><td>$' + totalBilled.toFixed(2) + '</td><td>Completed ride revenue captured in current operating window</td></tr>'
      + '<tr><td><strong>Pending payout</strong></td><td>$' + pendingPayout.toFixed(2) + '</td><td>Outstanding settlement value waiting reconciliation</td></tr>'
      + '<tr><td><strong>Completed trips</strong></td><td>' + formatNumber(completed.length) + '</td><td>Trips eligible for final claim processing</td></tr>'
      + '<tr><td><strong>Trips in progress</strong></td><td>' + formatNumber(inProgress.length) + '</td><td>Trips likely to enter billing queue soon</td></tr>'
      + '<tr><td><strong>Cancelled trips</strong></td><td>' + formatNumber(cancelled.length) + '</td><td>Trips requiring adjustment or no-charge handling</td></tr>'
      + '</tbody></table></div>';

    els.billingClaims.innerHTML = completed.length
      ? '<div class="enterprise-table-wrap"><table class="health-table"><thead><tr><th>Ride</th><th>Passenger</th><th>Service type</th><th>Status</th><th>Estimated charge</th></tr></thead><tbody>'
        + completed.slice(0, 30).map(function (ride) {
          const charge = Number(firstDefined(ride.fare_amount, ride.total_amount, ride.total_fare, ride.payout_amount, ride.estimated_distance_miles ? Number(ride.estimated_distance_miles) * 2.4 : 0) || 0);
          return '<tr>'
            + '<td>' + escapeHtml(String(ride.id || '').slice(0, 10)) + '</td>'
            + '<td>' + escapeHtml(ride.passenger_name || ride.rider_name || 'Passenger') + '</td>'
            + '<td>' + escapeHtml(formatServiceCategoryLabel(ride.service_type || 'medical_transport')) + '</td>'
            + '<td><span class="health-pill ok">ready</span></td>'
            + '<td>$' + (Number.isFinite(charge) ? charge.toFixed(2) : '0.00') + '</td>'
            + '</tr>';
        }).join('')
        + '</tbody></table></div>'
      : '<p class="health-summary">No completed rides available for claim generation yet.</p>';

    const agingRows = rides.slice(0, 30).map(function (ride) {
      const requestedAt = ride.requested_at || ride.created_at || null;
      const ageHours = requestedAt ? Math.max(0, (Date.now() - new Date(requestedAt).getTime()) / 3600000) : 0;
      const status = String(ride.status || '').toLowerCase();
      const bucket = status === 'completed' ? 'closed' : (ageHours > 24 ? 'aging' : 'active');
      return {
        id: ride.id,
        passenger: ride.passenger_name || ride.rider_name || 'Passenger',
        status: status || 'pending',
        ageHours: ageHours,
        bucket: bucket,
      };
    });

    els.billingAging.innerHTML = agingRows.length
      ? '<div class="enterprise-table-wrap"><table class="health-table"><thead><tr><th>Ride</th><th>Passenger</th><th>Lifecycle status</th><th>Age</th><th>Billing bucket</th></tr></thead><tbody>'
        + agingRows.map(function (row) {
          return '<tr>'
            + '<td>' + escapeHtml(String(row.id || '').slice(0, 10)) + '</td>'
            + '<td>' + escapeHtml(row.passenger) + '</td>'
            + '<td><span class="health-pill ' + pillClass(row.status) + '">' + escapeHtml(row.status) + '</span></td>'
            + '<td>' + escapeHtml(formatNumber(Math.round(row.ageHours))) + 'h</td>'
            + '<td>' + escapeHtml(row.bucket) + '</td>'
            + '</tr>';
        }).join('')
        + '</tbody></table></div>'
      : '<p class="health-summary">No ride records available for billing aging.</p>';
  }

  function applyRoleUiAccess() {
    const els = getEls();
    const allowWrite = canMutateRides();
    els.actions.forEach((button) => {
      if (button.getAttribute("data-health-action") === "create-ride") {
        button.hidden = !allowWrite;
      }
    });
  }

  async function updateRideStatus(rideId, status) {
    await fetchJson("/api/health-isf/rides/" + encodeURIComponent(rideId) + "/status", {
      method: "PATCH",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ status }),
    });
    await refreshData();
  }

  async function assignDriver(rideId, driverId) {
    await fetchJson("/api/health-isf/rides/" + encodeURIComponent(rideId) + "/assign-driver", {
      method: "PATCH",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ driver_id: driverId }),
    });
    state.selectedRideId = rideId;
    await refreshData();
  }

  async function fetchRideHistory(rideId) {
    if (!rideId) {
      return [];
    }
    return fetchJson("/api/health-isf/rides/" + encodeURIComponent(rideId) + "/history", { actionName: "ride_history" });
  }

  async function runDriverWorkflow(rideId, driverId, action) {
    const pathMap = {
      accept: "/accept-ride",
      decline: "/decline-ride",
      arrived: "/arrived-pickup",
      pickup: "/pickup-complete",
      onboard: "/pickup-complete",
      dropoff: "/dropoff-complete",
      complete: "/dropoff-complete",
    };
    const endpoint = pathMap[action];
    if (!endpoint) return;
    await fetchJson("/api/health-isf/drivers/" + encodeURIComponent(driverId) + endpoint, {
      method: "POST",
      actionName: "driver_workflow_" + String(action || "unknown"),
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ ride_id: rideId }),
    });
    state.selectedRideId = rideId;
    await refreshData();
  }

  async function escalateRideIssue(rideId) {
    const organizationId = getOrganizationId() || null;
    await fetchJson("/api/health-isf/workflows/escalate", {
      method: "POST",
      actionName: "workflow_escalate",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        organization_id: organizationId,
        ride_id: rideId,
        summary: "Manual escalation from dispatcher command center",
        severity: "high",
        target_role: "operations_manager",
        escalation_level: 1,
        details: { source: "dispatcher_command_center" },
      }),
    });
    await refreshData();
  }

  async function retryFailedWorkflow() {
    const organizationId = getOrganizationId() || null;
    await fetchJson("/api/health-isf/ai-dispatch/resilience/replay", {
      method: "POST",
      actionName: "workflow_retry_replay",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ organization_id: organizationId, limit: 25 }),
    });
    await refreshData();
  }

  async function setDriverStatus(driverId, status) {
    await fetchJson("/api/health-isf/drivers/" + encodeURIComponent(driverId) + "/set-status", {
      method: "POST",
      actionName: "driver_set_status",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ status }),
    });
    await refreshData();
  }

  async function submitCustomerRideRequest(formData) {
    const scheduledRaw = String(formData.get('scheduled_time') || '').trim();
    const payload = {
      rider_name: String(formData.get('rider_name') || '').trim(),
      rider_phone: String(formData.get('rider_phone') || '').trim(),
      pickup_address: String(formData.get('pickup_address') || '').trim(),
      dropoff_address: String(formData.get('dropoff_address') || '').trim(),
      scheduled_time: scheduledRaw ? new Date(scheduledRaw).toISOString() : null,
      ride_type: String(formData.get('ride_type') || 'healthcare').trim().toLowerCase(),
      recurring: Boolean(formData.get('recurring')),
      notes: String(formData.get('notes') || '').trim() || null,
    };

    await fetchJson('/api/health-isf/customer-requests', {
      method: 'POST',
      actionName: 'customer_request_submit',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(payload),
    });
    await refreshData();
  }

  async function fetchDriverAssignedRides(driverId) {
    if (!driverId) {
      state.selectedDriverAssignedRides = [];
      return;
    }
    const rows = await fetchJson('/api/health-isf/drivers/' + encodeURIComponent(driverId) + '/assigned-rides', {
      actionName: 'driver_assigned_rides',
    }).catch(function () { return []; });
    state.selectedDriverAssignedRides = Array.isArray(rows) ? rows : [];
  }

  function getDriverRuntimeInputs() {
    const els = getEls();
    return {
      driverId: String((els.driverRuntimeId && els.driverRuntimeId.value) || state.selectedDriverId || '').trim(),
      phone: String((els.driverRuntimePhone && els.driverRuntimePhone.value) || '').trim(),
      token: String((els.driverRuntimeToken && els.driverRuntimeToken.value) || state.driverRuntimeToken || '').trim(),
      availability: String((els.driverRuntimeAvailability && els.driverRuntimeAvailability.value) || 'available').trim().toLowerCase(),
    };
  }

  async function loginDriverRuntime() {
    const inputs = getDriverRuntimeInputs();
    if (!inputs.driverId || !inputs.phone) {
      throw new Error('Driver and phone are required');
    }
    const response = await fetchJson('/api/health-isf/drivers/login', {
      method: 'POST',
      actionName: 'driver_login',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ driver_id: inputs.driverId, phone: inputs.phone }),
    });
    state.driverRuntimeToken = String((response && response.session_token) || '');
    const els = getEls();
    if (els.driverRuntimeToken) {
      els.driverRuntimeToken.value = state.driverRuntimeToken;
    }
    return response;
  }

  async function logoutDriverRuntime() {
    const inputs = getDriverRuntimeInputs();
    if (!inputs.driverId || !inputs.token) {
      throw new Error('Driver and session token are required');
    }
    await fetchJson('/api/health-isf/drivers/logout', {
      method: 'POST',
      actionName: 'driver_logout',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ driver_id: inputs.driverId, session_token: inputs.token }),
    });
    state.driverRuntimeToken = null;
    const els = getEls();
    if (els.driverRuntimeToken) {
      els.driverRuntimeToken.value = '';
    }
  }

  async function setDriverRuntimeAvailability() {
    const inputs = getDriverRuntimeInputs();
    if (!inputs.driverId) {
      throw new Error('Driver is required');
    }
    await fetchJson('/api/health-isf/drivers/availability', {
      method: 'POST',
      actionName: 'driver_set_availability',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        driver_id: inputs.driverId,
        availability_state: inputs.availability,
        session_token: inputs.token || null,
      }),
    });
  }

  async function heartbeatDriverRuntime() {
    const inputs = getDriverRuntimeInputs();
    if (!inputs.driverId || !inputs.token) {
      throw new Error('Driver and session token are required');
    }
    await fetchJson('/api/health-isf/drivers/heartbeat', {
      method: 'POST',
      actionName: 'driver_heartbeat',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ driver_id: inputs.driverId, session_token: inputs.token }),
    });
  }

  async function refreshDriverRuntimeStatus() {
    const inputs = getDriverRuntimeInputs();
    if (!inputs.driverId) {
      throw new Error('Driver is required');
    }
    const query = inputs.token ? ('?session_token=' + encodeURIComponent(inputs.token)) : '';
    const runtime = await fetchJson('/api/health-isf/drivers/' + encodeURIComponent(inputs.driverId) + '/status' + query, {
      actionName: 'driver_runtime_status',
    });
    state.driverRuntimeStatus = runtime;
    return runtime;
  }

  async function refreshDriverLiveWorkspace() {
    const inputs = getDriverRuntimeInputs();
    if (!inputs.driverId) {
      state.driverLiveWorkspace = null;
      return null;
    }
    const workspace = await fetchJson('/api/health-isf/drivers/' + encodeURIComponent(inputs.driverId) + '/live-workspace', {
      actionName: 'driver_live_workspace',
    }).catch(function () { return null; });
    state.driverLiveWorkspace = workspace && typeof workspace === 'object' ? workspace : null;
    return state.driverLiveWorkspace;
  }

  async function progressDriverRoute(targetState, rideId) {
    const inputs = getDriverRuntimeInputs();
    if (!inputs.driverId) {
      throw new Error('Select a driver first');
    }
    await fetchJson('/api/health-isf/drivers/' + encodeURIComponent(inputs.driverId) + '/route-progress', {
      method: 'POST',
      actionName: 'driver_route_progress',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        target_state: targetState,
        ride_id: rideId || null,
      }),
    });
    await Promise.all([
      refreshDriverRuntimeStatus().catch(function () { return null; }),
      refreshDriverLiveWorkspace().catch(function () { return null; }),
      refreshData(),
    ]);
  }

  async function markProviderRequest(providerId, requestId, mode) {
    if (!providerId || !requestId) {
      throw new Error('Provider and request IDs are required');
    }
    let path = '/api/health-isf/providers/' + encodeURIComponent(providerId) + '/requests/' + encodeURIComponent(requestId);
    if (mode === 'ready') {
      path += '/ready';
    } else {
      const reason = window.prompt('Delay note for provider coordination', 'patient not ready') || '';
      if (!reason.trim()) {
        throw new Error('Delay note is required');
      }
      path += '/delay?note=' + encodeURIComponent(reason.trim());
    }
    await fetchJson(path, {
      method: 'POST',
      actionName: mode === 'ready' ? 'provider_ready' : 'provider_delay',
    });
    await refreshData();
  }

  async function adminReassignDriver(rideId, driverId) {
    if (!rideId || !driverId) {
      throw new Error('Ride and driver IDs are required');
    }
    await fetchJson('/api/health-isf/admin/reassign-driver', {
      method: 'POST',
      actionName: 'admin_reassign_driver',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        ride_id: rideId,
        driver_id: driverId,
        reason: 'manual_admin_reassign',
      }),
    });
    await refreshData();
  }

  async function adminForceExpireAssignment(offerId) {
    if (!offerId) {
      throw new Error('Offer ID is required');
    }
    await fetchJson('/api/health-isf/admin/force-expire-assignment', {
      method: 'POST',
      actionName: 'admin_force_expire',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        offer_id: offerId,
        reason: 'manual_admin_expire',
      }),
    });
    await refreshData();
  }

  async function dispatchClaimOwnership(rideId) {
    if (!rideId) {
      throw new Error('Ride ID is required');
    }
    await fetchJson('/api/health-isf/dispatcher/rides/' + encodeURIComponent(rideId) + '/claim-ownership?lease_seconds=180', {
      method: 'POST',
      actionName: 'dispatcher_claim_ownership',
    });
    await refreshData();
  }

  async function dispatchHandoffOwnership(rideId, toUserId) {
    if (!rideId || !toUserId) {
      throw new Error('Ride ID and target user ID are required');
    }
    const qs = '?to_user_id=' + encodeURIComponent(String(toUserId || '').trim()) + '&reason=' + encodeURIComponent('manual_handoff_ui') + '&lease_seconds=240';
    await fetchJson('/api/health-isf/dispatcher/rides/' + encodeURIComponent(rideId) + '/handoff-ownership' + qs, {
      method: 'POST',
      actionName: 'dispatcher_handoff_ownership',
    });
    await refreshData();
  }

  async function dispatchSupervisorEscalation(rideId, summary) {
    if (!rideId) {
      throw new Error('Ride ID is required');
    }
    const message = String(summary || 'Dispatcher requested supervisor assist').trim();
    const qs = '?summary=' + encodeURIComponent(message) + '&severity=high';
    await fetchJson('/api/health-isf/dispatcher/rides/' + encodeURIComponent(rideId) + '/supervisor-escalation-hook' + qs, {
      method: 'POST',
      actionName: 'dispatcher_supervisor_escalation',
    });
    await refreshData();
  }

  async function refreshPhase52RuntimeData() {
    const [runtimeState, runtimeReplay] = await Promise.all([
      fetchJson('/api/health-isf/operations/runtime-state?include_timeline=true&limit=120', {
        actionName: 'phase52_runtime_state',
      }).catch(function () { return null; }),
      fetchJson('/api/health-isf/operations/runtime-replay?after_sequence=0&limit=120', {
        actionName: 'phase52_runtime_replay',
      }).catch(function () { return null; }),
    ]);
    state.runtimeState = runtimeState && typeof runtimeState === 'object' ? runtimeState : null;
    state.runtimeReplay = runtimeReplay && typeof runtimeReplay === 'object' ? runtimeReplay : null;
  }

  async function runPhase52LifecycleAction(actionName, options) {
    const opts = options && typeof options === 'object' ? options : {};
    const query = new URLSearchParams();
    query.set('action', String(actionName || '').trim());
    if (opts.rideId) query.set('ride_id', String(opts.rideId));
    if (opts.driverId) query.set('driver_id', String(opts.driverId));
    if (opts.providerId) query.set('provider_id', String(opts.providerId));

    await fetchJson('/api/health-isf/operations/lifecycle-action?' + query.toString(), {
      method: 'POST',
      actionName: 'phase52_lifecycle_action',
    });
    await Promise.all([
      refreshPhase52RuntimeData().catch(function () { return null; }),
      refreshData(),
    ]);
  }

  async function runPhase52DispatchRecovery(rideId, strategy) {
    if (!rideId) {
      throw new Error('ride_id is required for dispatch recovery');
    }
    await fetchJson('/api/health-isf/operations/dispatch-recovery?ride_id=' + encodeURIComponent(rideId) + '&strategy=' + encodeURIComponent(strategy || 'auto_assign'), {
      method: 'POST',
      actionName: 'phase52_dispatch_recovery',
    });
    await Promise.all([
      refreshPhase52RuntimeData().catch(function () { return null; }),
      refreshData(),
    ]);
  }

  function selectedRideForDispatchAction() {
    if (state.selectedRideId) {
      return String(state.selectedRideId);
    }
    const pending = (state.rides || []).find(function (ride) {
      const status = String((ride && ride.status) || '').toLowerCase();
      return status === 'pending' || status === 'accepted';
    });
    return pending ? String(pending.id) : '';
  }

  function computeDispatchTimeline() {
    const events = Array.isArray(state.operationalEventFeed) ? state.operationalEventFeed : [];
    const keys = {
      'dispatch-search-started': true,
      'driver-offer-issued': true,
      'driver-offer-expired': true,
      'auto-assignment-completed': true,
      'reassignment-started': true,
      'reassignment-completed': true,
      'assignment-accepted': true,
    };
    return events.filter(function (item) {
      const kind = String((item && (item.kind || item.type || item.event_type)) || '').toLowerCase();
      return keys[kind] === true;
    }).slice(0, 20);
  }

  function hydrateDriverIncomingOffer() {
    const selectedDriverId = String(state.selectedDriverId || '');
    if (!selectedDriverId) {
      state.driverIncomingOffer = null;
      return;
    }
    const rows = Array.isArray(state.dispatchActiveAssignments) ? state.dispatchActiveAssignments : [];
    state.driverIncomingOffer = rows.find(function (item) {
      return String(item.driver_id || '') === selectedDriverId && String(item.assignment_state || '').toLowerCase() === 'offered';
    }) || null;
  }

  async function refreshDispatchIntelligence() {
    const queue = await fetchJson('/api/health-isf/dispatch/queue', { actionName: 'dispatch_queue' }).catch(function () { return []; });
    const active = await fetchJson('/api/health-isf/dispatch/active-assignments', { actionName: 'dispatch_active_assignments' }).catch(function () { return []; });
    state.dispatchQueue = Array.isArray(queue) ? queue : [];
    state.dispatchActiveAssignments = Array.isArray(active) ? active : [];
    state.dispatchTimeline = computeDispatchTimeline();
    hydrateDriverIncomingOffer();
  }

  async function runDispatchAutoAssign() {
    const rideId = selectedRideForDispatchAction();
    if (!rideId) {
      throw new Error('Select a ride before auto-assign');
    }
    await fetchJson('/api/health-isf/dispatch/auto-assign', {
      method: 'POST',
      actionName: 'dispatch_auto_assign',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ ride_id: rideId, offer_timeout_seconds: 90 }),
    });
  }

  async function runDispatchReassign() {
    const rideId = selectedRideForDispatchAction();
    if (!rideId) {
      throw new Error('Select a ride before reassignment');
    }
    await fetchJson('/api/health-isf/dispatch/reassign', {
      method: 'POST',
      actionName: 'dispatch_reassign',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ ride_id: rideId, offer_timeout_seconds: 90 }),
    });
  }

  function getSelectedCustomerRequestId() {
    const els = getEls();
    const explicit = String((els.requestActionId && els.requestActionId.value) || '').trim();
    if (explicit) {
      return explicit;
    }
    const firstPending = (state.customerRequests || []).find(function (item) {
      const status = String((item && item.dispatch_status) || '').toLowerCase();
      return status === 'pending' || status === 'approved' || status === 'dispatchable';
    });
    return firstPending ? String(firstPending.id || '') : '';
  }

  function setRequestActionStatus(message, tone) {
    const els = getEls();
    if (!els.requestActionStatus) return;
    const cls = tone === 'error' ? 'health-pill danger' : tone === 'warn' ? 'health-pill warn' : 'health-pill ok';
    els.requestActionStatus.innerHTML = '<span class="' + cls + '">' + escapeHtml(tone || 'info') + '</span> ' + escapeHtml(message || 'Ready.');
  }

  async function runCustomerRequestAction(pathSuffix, method, body) {
    const requestId = getSelectedCustomerRequestId();
    if (!requestId) {
      throw new Error('Enter or select a customer request ID first');
    }
    await fetchJson('/api/health-isf/dispatcher/customer-requests/' + encodeURIComponent(requestId) + pathSuffix, {
      method: method,
      actionName: 'dispatcher_request_action',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(body || {}),
    });
    if (state.selectedRideId) {
      await refreshRideTimeline().catch(function () { return null; });
    }
  }

  async function acceptDriverIncomingOffer() {
    hydrateDriverIncomingOffer();
    if (!state.driverIncomingOffer || !state.driverIncomingOffer.offer_id) {
      throw new Error('No incoming offer for selected driver');
    }
    await fetchJson('/api/health-isf/dispatch/offers/' + encodeURIComponent(state.driverIncomingOffer.offer_id) + '/accept', {
      method: 'POST',
      actionName: 'driver_offer_accept',
    });
  }

  async function rejectDriverIncomingOffer() {
    hydrateDriverIncomingOffer();
    if (!state.driverIncomingOffer || !state.driverIncomingOffer.offer_id) {
      throw new Error('No incoming offer for selected driver');
    }
    await fetchJson('/api/health-isf/dispatch/offers/' + encodeURIComponent(state.driverIncomingOffer.offer_id) + '/reject?reason=' + encodeURIComponent('driver_rejected'), {
      method: 'POST',
      actionName: 'driver_offer_reject',
    });
  }

  async function submitDriverApplication(formData) {
    const categoriesRaw = String(formData.get('preferred_service_categories') || '').trim();
    const payload = {
      applicant_name: String(formData.get('applicant_name') || '').trim(),
      applicant_phone: String(formData.get('applicant_phone') || '').trim(),
      applicant_email: String(formData.get('applicant_email') || '').trim() || null,
      license_number: String(formData.get('license_number') || '').trim() || null,
      vehicle_make: String(formData.get('vehicle_make') || '').trim() || null,
      vehicle_model: String(formData.get('vehicle_model') || '').trim() || null,
      vehicle_year: formData.get('vehicle_year') ? Number(formData.get('vehicle_year')) : null,
      vehicle_plate: String(formData.get('vehicle_plate') || '').trim() || null,
      availability_summary: String(formData.get('availability_summary') || '').trim() || null,
      preferred_service_categories: categoriesRaw
        ? categoriesRaw.split(',').map(function (item) { return String(item || '').trim().toLowerCase(); }).filter(Boolean)
        : [],
      background_check_authorized: Boolean(formData.get('background_check_authorized')),
      license_document_ref: String(formData.get('license_document_ref') || '').trim() || null,
      insurance_document_ref: String(formData.get('insurance_document_ref') || '').trim() || null,
      notes: String(formData.get('notes') || '').trim() || null,
    };

    await fetchJson('/api/health-isf/driver-applications', {
      method: 'POST',
      actionName: 'driver_application_submit',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(payload),
    });
    await refreshData();
  }

  async function setDriverApplicationStatus(applicationId, onboardingStatus) {
    await fetchJson('/api/health-isf/driver-applications/' + encodeURIComponent(applicationId) + '/status', {
      method: 'PATCH',
      actionName: 'driver_application_review',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        onboarding_status: onboardingStatus,
        review_notes: 'Updated from Phase 43 onboarding command center',
      }),
    });
    await refreshData();
  }

  async function seedPhase43Data() {
    await fetchJson('/api/health-isf/ops/seed-phase43', {
      method: 'POST',
      actionName: 'seed_phase43',
    });
    await refreshData();
  }

  function selectRide(rideId) {
    state.selectedRideId = rideId || null;
    persistRuntimeState("select_ride");
    refreshRideTimeline().catch(() => {});
  }

  async function refreshRideTimeline() {
    const ride = state.rides.find((item) => item.id === state.selectedRideId) || state.rides[0] || null;
    state.selectedRideId = ride ? ride.id : null;
    if (ride) {
      const [history, dispatchHistory, operationalTimeline, workflowProof] = await Promise.all([
        fetchRideHistory(ride.id),
        fetchJson("/api/health-isf/rides/" + encodeURIComponent(ride.id) + "/dispatch-history").catch(() => []),
        fetchJson("/api/health-isf/ai-dispatch/timeline?ride_id=" + encodeURIComponent(ride.id)).catch(() => []),
        fetchJson("/api/health-isf/rides/" + encodeURIComponent(ride.id) + "/workflow-path").catch(() => null),
      ]);
      state.selectedRideHistory = history;
      state.selectedRideDispatchHistory = dispatchHistory;
      state.selectedOperationalTimeline = Array.isArray(operationalTimeline) ? operationalTimeline : [];
      state.selectedRideWorkflowProof = workflowProof && typeof workflowProof === 'object' ? workflowProof : null;
    } else {
      state.selectedRideHistory = [];
      state.selectedRideDispatchHistory = [];
      state.selectedOperationalTimeline = [];
      state.selectedRideWorkflowProof = null;
    }
    renderRideTimeline();
    renderAIOperations();
  }

  function renderDrivers() {
    const els = getEls();
    if (!els.driverCards) return;
    const rows = getDriverRows();
    const availableCount = rows.filter(function (row) { return String(row.availability || '').toLowerCase() === 'available'; }).length;
    const activeCount = rows.filter(function (row) { return row.assignedRides > 0; }).length;
    const avgUtilization = rows.length ? rows.reduce(function (sum, row) { return sum + Number(row.utilization || 0); }, 0) / rows.length : 0;
    const capacityChartItems = rows.slice(0, 6).map(function (row) {
      return { label: row.name.split(' ')[0], value: Number(row.utilization || 0), displayValue: formatPercent(row.utilization) };
    });
    const driverAlerts = rows.filter(function (row) {
      return String(row.availability || '').toLowerCase() !== 'available' || row.assignedRides >= 2;
    }).map(function (row) {
      return {
        title: row.name,
        message: 'Shift ' + row.shiftState + ' · assigned rides ' + row.assignedRides + ' · ETA ' + formatMinutesCompact(row.etaMinutes),
        created_at: row.updatedAt || new Date().toISOString(),
        severity: row.assignedRides >= 2 ? 'medium' : 'info',
      };
    });

    els.driverCards.innerHTML = [
      '<div class="enterprise-section">',
      '<div class="enterprise-metric-grid">',
      MetricCard('Live roster', rows.length, 'Drivers currently visible to dispatch', 'ok'),
      MetricCard('Ready now', availableCount, 'Available for immediate assignment', availableCount ? 'ok' : 'warn'),
      MetricCard('On trip', activeCount, 'Drivers with at least one active rider', activeCount ? 'warn' : 'ok'),
      MetricCard('Avg utilization', formatPercent(avgUtilization), 'How saturated the current fleet is', avgUtilization >= 75 ? 'danger' : 'ok'),
      '</div>',
      '<div class="enterprise-panel-grid">',
      '<section class="enterprise-panel-block">',
      '<h4>Shift roster</h4>',
      DriverTable(rows),
      '</section>',
      '<section class="enterprise-panel-block">',
      '<h4>Capacity and workload</h4>',
      AnalyticsChart({
        type: 'bar',
        items: capacityChartItems,
        emptyText: 'Awaiting refreshed operations data...',
        timestamp: state.hydration.lastRefreshAt,
        footer: 'Utilization by driver across current assignments',
      }),
      '<h4>Shift watchlist</h4>',
      AlertPanel(driverAlerts.slice(0, 6), 'Driver availability is stable.'),
      '</section>',
      '<section class="enterprise-panel-block">',
      '<h4>Dispatch commitments</h4>',
      ((state.selectedDriverAssignedRides || []).length
        ? (state.selectedDriverAssignedRides || []).slice(0, 4).map(function (ride) {
            return '<article class="health-item-card"><div class="health-row"><strong>' + escapeHtml(ride.passenger_name || 'Passenger') + '</strong><span class="health-pill ' + pillClass(ride.status || 'pending') + '">' + escapeHtml(ride.status || 'pending') + '</span></div><div class="health-summary">Pickup ' + escapeHtml(ride.pickup_address || '-') + '</div><div class="health-summary">Dropoff ' + escapeHtml(ride.dropoff_address || '-') + '</div></article>';
          }).join('')
        : '<p class="health-summary">Select a driver to inspect today\'s assigned riders and commitments.</p>'),
      '</section>',
      '</div>',
      '</div>',
    ].join('');

    if (els.driverRuntimeId) {
      const selected = String(els.driverRuntimeId.value || state.selectedDriverId || '');
      els.driverRuntimeId.innerHTML = '<option value="">Select driver</option>' + rows.map(function (row) {
        return '<option value="' + escapeHtml(row.id) + '">' + escapeHtml(row.name) + ' (' + escapeHtml(row.status) + ')</option>';
      }).join('');
      if (selected) {
        els.driverRuntimeId.value = selected;
      }
    }

    if (els.driverPoolMetrics) {
      const pool = state.driverPoolMetrics || {};
      els.driverPoolMetrics.innerHTML = '<div class="enterprise-inline-grid">'
        + MetricCard('Active Drivers', formatNumber(pool.total_active || rows.length), 'Active contractor drivers in organization', 'ok')
        + MetricCard('Online', formatNumber(pool.online || 0), 'Drivers currently online', (pool.online || 0) ? 'ok' : 'warn')
        + MetricCard('Available', formatNumber(pool.available || 0), 'Dispatch-ready pool', (pool.available || 0) ? 'ok' : 'warn')
        + MetricCard('Assigned', formatNumber(pool.assigned || 0), 'Drivers currently assigned/on_trip', (pool.assigned || 0) ? 'warn' : 'ok')
        + MetricCard('Unavailable', formatNumber(pool.unavailable || 0), 'Temporarily not dispatchable', (pool.unavailable || 0) ? 'warn' : 'ok')
        + MetricCard('Offline', formatNumber(pool.offline || 0), 'Offline/inactive runtime state', (pool.offline || 0) ? 'danger' : 'ok')
        + '</div>';
    }

    const runtime = state.driverRuntimeStatus;
    if (els.driverRuntimeStatus) {
      if (!runtime) {
        els.driverRuntimeStatus.innerHTML = '<p class="health-summary">Driver status not loaded.</p>';
      } else {
        els.driverRuntimeStatus.innerHTML = '<div class="enterprise-inline-grid">'
          + MetricCard('Auth State', escapeHtml(runtime.auth_state || 'inactive'), 'Driver auth session state', runtime.auth_state === 'active' ? 'ok' : 'warn')
          + MetricCard('Availability', escapeHtml(runtime.availability_state || 'offline'), 'Driver dispatch availability', runtime.availability_state === 'available' ? 'ok' : 'warn')
          + MetricCard('Online', runtime.is_online ? 'Yes' : 'No', 'Driver websocket/runtime presence', runtime.is_online ? 'ok' : 'warn')
          + MetricCard('Heartbeat', runtime.last_seen_at ? formatRelativeTime(runtime.last_seen_at) : 'never', 'Most recent driver heartbeat', runtime.last_seen_at ? 'ok' : 'warn')
          + MetricCard('Session Valid', runtime.active_session ? 'Yes' : 'No', 'Driver session validation status', runtime.active_session ? 'ok' : 'danger')
          + MetricCard('Active Ride', runtime.active_ride_id ? String(runtime.active_ride_id).slice(0, 8) : 'none', 'Current active assignment', runtime.active_ride_id ? 'warn' : 'ok')
          + '</div>';
      }
    }

    hydrateDriverIncomingOffer();
    if (els.driverIncomingOffer) {
      const offer = state.driverIncomingOffer;
      if (!offer) {
        els.driverIncomingOffer.innerHTML = '<p class="health-summary">No incoming assignment offer for selected driver.</p>';
      } else {
        const expires = offer.offer_expires_at ? formatRelativeTime(offer.offer_expires_at) : 'n/a';
        els.driverIncomingOffer.innerHTML = '<div class="enterprise-inline-grid">'
          + MetricCard('Offer State', escapeHtml(offer.assignment_state || 'offered'), 'Current driver offer lifecycle state', 'warn')
          + MetricCard('Ride', escapeHtml(String(offer.ride_id || '').slice(0, 8)), 'Incoming ride identifier', 'ok')
          + MetricCard('Attempt', formatNumber(offer.attempt_index || 0), 'Deterministic offer attempt index', 'ok')
          + MetricCard('Score', escapeHtml(String(offer.score != null ? Number(offer.score).toFixed(3) : '-')), 'Dispatch scoring model output', 'ok')
          + MetricCard('Countdown', escapeHtml(expires), 'Offer expiry countdown', 'warn')
          + '</div>';
      }
    }

    if (els.driverOfferStream) {
      const streamRows = (state.dispatchTimeline || []).filter(function (item) {
        const payload = item.payload || {};
        const driverId = String(payload.driver_id || item.driver_id || '');
        return !state.selectedDriverId || driverId === String(state.selectedDriverId);
      }).slice(0, 10);
      els.driverOfferStream.innerHTML = streamRows.length
        ? renderTimelineList(streamRows.map(function (item) {
            return {
              kind: item.kind || item.type || item.event_type || 'dispatch',
              summary: item.summary || item.message || 'Dispatch event',
              timestamp: item.timestamp || item.created_at || stampNow(),
              severity: item.severity || 'info',
            };
          }), 'Driver dispatch event stream waiting for events.')
        : '<p class="health-summary">Driver dispatch event stream waiting for events.</p>';
    }

    if (els.driverAuthAssignment) {
      const activeAssignments = state.selectedDriverAssignedRides || [];
      const liveWorkspace = state.driverLiveWorkspace && typeof state.driverLiveWorkspace === 'object' ? state.driverLiveWorkspace : null;
      const activeRide = liveWorkspace && liveWorkspace.active_ride ? liveWorkspace.active_ride : null;
      const liveAssignmentCountdown = (liveWorkspace && Number.isFinite(Number(liveWorkspace.assignment_countdown_seconds)))
        ? formatNumber(liveWorkspace.assignment_countdown_seconds) + 's'
        : '-';
      const routeRideId = String((activeRide && activeRide.id) || (liveWorkspace && liveWorkspace.active_assignment && liveWorkspace.active_assignment.ride_id) || '');
      const routeButtons = ['en_route_pickup', 'arrived_pickup', 'rider_loaded', 'trip_in_progress', 'arrived_destination', 'completed'].map(function (stateName) {
        return '<button class="health-row-btn" data-driver-route-progress="' + escapeHtml(stateName) + '" data-driver-route-ride="' + escapeHtml(routeRideId) + '">' + escapeHtml(stateName.replace(/_/g, ' ')) + '</button>';
      }).join('');

      els.driverAuthAssignment.innerHTML = '<div class="enterprise-inline-grid">'
        + MetricCard('Safety', escapeHtml((liveWorkspace && liveWorkspace.safety_status) || 'ok'), 'Driver safety and heartbeat health', statusTone((liveWorkspace && liveWorkspace.safety_status) || 'ok'))
        + MetricCard('Reconnect', (liveWorkspace && liveWorkspace.reconnect_safe) ? 'safe' : 'required', 'Realtime reconnect continuity status', (liveWorkspace && liveWorkspace.reconnect_safe) ? 'ok' : 'warn')
        + MetricCard('Offer countdown', liveAssignmentCountdown, 'Seconds until current offer expires', 'warn')
        + MetricCard('ETA', liveWorkspace && Number.isFinite(Number(liveWorkspace.eta_minutes)) ? formatMinutesCompact(liveWorkspace.eta_minutes) : '-', 'Live ETA estimate to destination', 'ok')
        + '</div>'
        + (activeAssignments.length
          ? activeAssignments.slice(0, 3).map(function (ride) {
              return '<div class="health-row"><strong>' + escapeHtml(ride.passenger_name || 'Passenger') + '</strong><span class="health-pill ' + pillClass(ride.status) + '">' + escapeHtml(ride.status || 'pending') + '</span></div>';
            }).join('')
          : '<p class="health-summary">No active assignments for selected driver.</p>')
        + '<div class="health-row-actions">' + routeButtons + '</div>';
    }

    if (els.driverAuthHistory) {
      const driverIdForHistory = state.selectedDriverId || (runtime && runtime.driver_id) || '';
      const historyRows = state.rides.filter(function (ride) {
        return driverIdForHistory && String(ride.driver_id || '') === String(driverIdForHistory);
      }).slice(0, 8);
      els.driverAuthHistory.innerHTML = historyRows.length
        ? historyRows.map(function (ride) {
            return '<div class="health-row"><strong>' + escapeHtml(ride.passenger_name || 'Passenger') + '</strong><span class="health-pill ' + pillClass(ride.status) + '">' + escapeHtml(ride.status || 'unknown') + '</span></div>';
          }).join('')
        : '<p class="health-summary">Ride history unavailable for selected driver.</p>';
    }

    const driverEls = getEls();
    const driverWs = getWebsocketMetrics();
    if (driverEls.driverOperationalFeed) {
      driverEls.driverOperationalFeed.innerHTML = renderNotificationList(driverAlerts.slice(0, 8), 'No shift exceptions.');
    }
    if (driverEls.driverRecommendations) {
      driverEls.driverRecommendations.innerHTML = renderRecommendationList(getOperationalDecisionRecommendations().slice(0, 6), 'No coaching prompts for drivers right now.');
    }
    if (driverEls.driverMemory) {
      driverEls.driverMemory.innerHTML = (state.selectedDriverAssignedRides || []).length
        ? '<div class="health-stack-list">' + (state.selectedDriverAssignedRides || []).slice(0, 6).map(function (ride) {
            return '<article class="health-stack-item"><div class="health-stack-title-row"><strong>' + escapeHtml(ride.passenger_name || 'Passenger') + '</strong><span class="health-op-badge live">assigned</span></div><p>' + escapeHtml(ride.pickup_address || '-') + ' -> ' + escapeHtml(ride.dropoff_address || '-') + '</p><small>' + escapeHtml(formatServiceCategoryLabel(ride.service_type || 'medical_transport')) + '</small></article>';
          }).join('') + '</div>'
        : '<p class="health-summary">Assigned rides will appear here for the selected driver.</p>';
    }
    if (driverEls.driverGovernance) {
      driverEls.driverGovernance.innerHTML = '<div class="enterprise-inline-grid">'
        + MetricCard('Auth state', escapeHtml((runtime && runtime.auth_state) || 'inactive'), 'Driver sign-in validation state', runtime && runtime.auth_state === 'active' ? 'ok' : 'warn')
        + MetricCard('Safety', escapeHtml((state.driverLiveWorkspace && state.driverLiveWorkspace.safety_status) || 'ok'), 'Heartbeat and safety checks for selected driver', statusTone((state.driverLiveWorkspace && state.driverLiveWorkspace.safety_status) || 'ok'))
        + MetricCard('Reconnect', state.driverLiveWorkspace && state.driverLiveWorkspace.reconnect_safe ? 'safe' : 'watch', 'Ability to recover the live trip session', state.driverLiveWorkspace && state.driverLiveWorkspace.reconnect_safe ? 'ok' : 'warn')
      + '</div>';
    }
    if (driverEls.driverWebsocket) {
      const streamRows = (state.dispatchTimeline || []).filter(function (item) {
        const payload = item.payload || {};
        const driverId = String(payload.driver_id || item.driver_id || '');
        return !state.selectedDriverId || driverId === String(state.selectedDriverId);
      }).slice(0, 10);
      driverEls.driverWebsocket.innerHTML = renderTimelineList(streamRows.map(function (item) {
        return {
          kind: item.kind || item.type || item.event_type || 'dispatch',
          summary: item.summary || item.message || 'Dispatch handoff event',
          timestamp: item.timestamp || item.created_at || stampNow(),
          severity: item.severity || 'info',
        };
      }), 'No offer or handoff history yet.');
    }
    if (driverEls.driverSync) {
      driverEls.driverSync.innerHTML = '<div class="enterprise-inline-grid">'
        + MetricCard('Heartbeat', runtime && runtime.last_seen_at ? formatRelativeTime(runtime.last_seen_at) : 'never', 'Latest driver heartbeat', runtime && runtime.last_seen_at ? 'ok' : 'warn')
        + MetricCard('Offer countdown', (state.driverLiveWorkspace && Number.isFinite(Number(state.driverLiveWorkspace.assignment_countdown_seconds))) ? formatNumber(state.driverLiveWorkspace.assignment_countdown_seconds) + 's' : '-', 'Time left on current assignment offer', 'warn')
        + MetricCard('ETA', (state.driverLiveWorkspace && Number.isFinite(Number(state.driverLiveWorkspace.eta_minutes))) ? formatMinutesCompact(state.driverLiveWorkspace.eta_minutes) : '-', 'Live route ETA for selected driver', 'ok')
      + '</div>';
    }

    if (driverEls.driverAssignedRides) {
      const items = Array.isArray(state.selectedDriverAssignedRides) ? state.selectedDriverAssignedRides : [];
      const selectedDriverName = lookupDriverName(state.selectedDriverId);
      if (!state.selectedDriverId) {
        driverEls.driverAssignedRides.innerHTML = '<p class="health-summary">Select a driver to inspect active assigned rides.</p>';
      } else if (!items.length) {
        driverEls.driverAssignedRides.innerHTML = '<p class="health-summary">No active assigned rides for ' + escapeHtml(selectedDriverName) + '.</p>';
      } else {
        driverEls.driverAssignedRides.innerHTML = items.map(function (ride) {
          return '<article class="health-item-card">'
            + '<div class="health-row"><strong>' + escapeHtml(ride.passenger_name || 'Passenger') + '</strong><span class="health-pill ' + pillClass(ride.status) + '">' + escapeHtml(ride.status || 'pending') + '</span></div>'
            + '<div class="health-summary">Ride ID: ' + escapeHtml(String(ride.id || '').slice(0, 8)) + ' · Category: ' + escapeHtml(formatServiceCategoryLabel(ride.service_type || 'medical_transport')) + '</div>'
            + '<div class="health-summary">Pickup: ' + escapeHtml(ride.pickup_address || '-') + '</div>'
            + '<div class="health-summary">Dropoff: ' + escapeHtml(ride.dropoff_address || '-') + '</div>'
            + '</article>';
        }).join('');
      }
    }
  }

  function renderProviders() {
    const els = getEls();
    if (!els.providerCards) return;
    const rows = getProviderRows();
    const onlineCount = rows.filter(function (row) { return String(row.status || '').toLowerCase() !== 'offline'; }).length;
    const queueTotal = rows.reduce(function (sum, row) { return sum + Number(row.queueSize || 0); }, 0);
    const avgSla = rows.length ? rows.reduce(function (sum, row) { return sum + Number(row.sla || 0); }, 0) / rows.length : 0;
    const avgResponse = rows.length ? rows.reduce(function (sum, row) { return sum + Number(row.responseTimeMinutes || 0); }, 0) / Math.max(rows.filter(function (row) { return Number.isFinite(row.responseTimeMinutes); }).length, 1) : 0;
    const providerAlertItems = rows.filter(function (row) {
      return row.alerts > 0 || row.queueSize >= 3;
    }).map(function (row) {
      return {
        title: row.name,
        message: 'Queue ' + row.queueSize + ' · SLA ' + formatPercent(row.sla) + ' · response ' + formatMinutesCompact(row.responseTimeMinutes),
        created_at: row.updatedAt || new Date().toISOString(),
        severity: row.alerts > 1 || row.queueSize >= 4 ? 'high' : 'medium',
      };
    });
    const performanceChartItems = rows.slice(0, 6).map(function (row) {
      return { label: row.name.split(' ')[0], value: Number(row.sla || 0), displayValue: formatPercent(row.sla) };
    });

    els.providerCards.innerHTML = [
      '<div class="enterprise-section">',
      '<div class="enterprise-metric-grid">',
      MetricCard('Provider table', rows.length, 'Network partners in the live enterprise roster', 'ok'),
      MetricCard('Online providers', onlineCount, 'Ready to receive new ride volume', onlineCount ? 'ok' : 'warn'),
      MetricCard('Queue size', queueTotal, 'Combined provider-side unresolved queue', queueTotal >= 6 ? 'danger' : 'warn'),
      MetricCard('Avg response', formatMinutesCompact(avgResponse), 'Mean request-to-accept time across provider rides', avgResponse >= 20 ? 'danger' : 'ok'),
      MetricCard('Avg SLA', formatPercent(avgSla), 'Provider delivery health across current network', avgSla >= 85 ? 'ok' : 'warn'),
      MetricCard('Live alerts', providerAlertItems.length, 'Provider-side watch items requiring intervention', providerAlertItems.length ? 'warn' : 'ok'),
      '</div>',
      '<div class="enterprise-panel-grid">',
      '<section class="enterprise-panel-block">',
      '<h4>Partner roster</h4>',
      ProviderTable(rows),
      '</section>',
      '<section class="enterprise-panel-block">',
      '<h4>Partner performance</h4>',
      AnalyticsChart({
        type: 'bar',
        items: performanceChartItems,
        emptyText: 'Provider performance will render when live providers are available.',
        timestamp: state.hydration.lastRefreshAt,
        footer: 'SLA performance by provider',
      }),
      '<h4>Partner watchlist</h4>',
      AlertPanel(providerAlertItems.slice(0, 6), 'Provider network is stable.'),
      '</section>',
      '<section class="enterprise-panel-block">',
      '<h4>Facility transport queue</h4>',
      ((state.providerTransportQueue || []).slice(0, 10).map(function (item) {
        return '<article class="health-item-card">'
          + '<div class="health-row"><strong>' + escapeHtml(item.rider_name || 'Rider') + '</strong><span class="health-pill ' + pillClass(item.dispatch_status || item.ride_status || 'queued') + '">' + escapeHtml(item.dispatch_status || item.ride_status || 'queued') + '</span></div>'
          + '<div class="health-summary">' + escapeHtml(item.pickup_address || '-') + ' -> ' + escapeHtml(item.dropoff_address || '-') + '</div>'
          + '<div class="health-summary">Updated ' + escapeHtml(formatRelativeTime(item.updated_at || stampNow())) + '</div>'
          + '<div class="health-row-actions">'
          + '<button class="health-row-btn ok" data-provider-id="' + escapeHtml(item.provider_id || '') + '" data-provider-request-ready="' + escapeHtml(item.id || '') + '">Provider Ready</button>'
          + '<button class="health-row-btn warn" data-provider-id="' + escapeHtml(item.provider_id || '') + '" data-provider-request-delay="' + escapeHtml(item.id || '') + '">Provider Delay</button>'
            + '<button class="health-row-btn" data-provider-request-escalate="' + escapeHtml(item.ride_id || '') + '">Escalate</button>'
          + '</div>'
          + '</article>';
      }).join('') || '<p class="health-summary">Provider queue is empty for current facility.</p>'),
      '</section>',
      '<section class="enterprise-panel-block">',
      '<h4>Recurring demand by facility</h4>',
      recurringTransportPanel(),
      '</section>',
      '</div>',
      '</div>',
    ].join('');

    const providerEls = getEls();
    const providerWs = getWebsocketMetrics();
    if (providerEls.providerOperationalFeed) {
      providerEls.providerOperationalFeed.innerHTML = ((state.providerTransportQueue || []).length
        ? '<div class="health-stack-list">' + (state.providerTransportQueue || []).slice(0, 8).map(function (item) {
            return '<article class="health-stack-item"><div class="health-stack-title-row"><strong>' + escapeHtml(item.rider_name || 'Rider') + '</strong><span class="health-op-badge ' + (String(item.dispatch_status || item.ride_status || '').toLowerCase() === 'delayed' ? 'warn' : 'ok') + '">' + escapeHtml(item.dispatch_status || item.ride_status || 'queued') + '</span></div><p>' + escapeHtml(item.pickup_address || '-') + ' -> ' + escapeHtml(item.dropoff_address || '-') + '</p><small>' + escapeHtml(lookupProviderName(item.provider_id)) + '</small></article>';
          }).join('') + '</div>'
        : '<p class="health-summary">No provider-side pickup exceptions.</p>');
    }
    if (providerEls.providerRecommendations) {
      providerEls.providerRecommendations.innerHTML = renderRecommendationList(getUnifiedOperationalRecommendations('provider_analytics', 6), 'No partner network recommendations.');
    }
    if (providerEls.providerMemory) {
      providerEls.providerMemory.innerHTML = recurringTransportPanel();
    }
    if (providerEls.providerGovernance) {
      providerEls.providerGovernance.innerHTML = renderNotificationList(providerAlertItems.slice(0, 6), 'No escalations or approvals are pending.');
    }
    if (providerEls.providerWebsocket) {
      providerEls.providerWebsocket.innerHTML = '<div class="enterprise-inline-grid">'
        + MetricCard('Online providers', formatNumber(onlineCount), 'Partners currently available to accept ride flow', onlineCount ? 'ok' : 'warn')
        + MetricCard('Queue volume', formatNumber(queueTotal), 'Combined unresolved queue at facilities', queueTotal >= 6 ? 'warn' : 'ok')
        + MetricCard('Avg response', formatMinutesCompact(avgResponse), 'Time from request to partner response', avgResponse >= 20 ? 'danger' : 'ok')
        + MetricCard('Reconnect watch', formatNumber(providerWs.websocket.reconnects_last_5m || 0), 'Continuity pressure across partner surfaces', (providerWs.websocket.reconnects_last_5m || 0) > 0 ? 'warn' : 'ok')
      + '</div>';
    }
    if (providerEls.providerSync) {
      providerEls.providerSync.innerHTML = renderTimelineList((state.providerTransportQueue || []).slice(0, 10).map(function (item) {
        return {
          kind: item.dispatch_status || item.ride_status || 'queued',
          summary: (item.rider_name || 'Rider') + ' · ' + (item.pickup_address || '-') + ' -> ' + (item.dropoff_address || '-'),
          timestamp: item.updated_at || item.created_at || stampNow(),
          severity: String(item.dispatch_status || item.ride_status || '').toLowerCase() === 'delayed' ? 'high' : 'info',
        };
      }), 'No facility timeline events yet.');
    }
  }

  function renderCustomerWorkspace() {
    const els = getEls();
    if (!els.customerActiveRide || !els.customerRequestHistory || !els.customerAssignment || !els.customerTimeline || !els.customerBookingManagement || !els.customerSupport) return;

    const activeRide = state.customerWorkspace && state.customerWorkspace.activeRide ? state.customerWorkspace.activeRide : null;
    const history = state.customerWorkspace && Array.isArray(state.customerWorkspace.history) ? state.customerWorkspace.history : [];
    const liveTimeline = state.customerWorkspace && Array.isArray(state.customerWorkspace.timeline) ? state.customerWorkspace.timeline : [];
    const liveEta = state.customerWorkspace ? state.customerWorkspace.etaMinutes : null;
    const supportQueue = state.customerWorkspace && Array.isArray(state.customerWorkspace.supportQueue) ? state.customerWorkspace.supportQueue : [];
    const actions = state.customerWorkspace && Array.isArray(state.customerWorkspace.actions) ? state.customerWorkspace.actions : [];

    const runtimeTimeline = state.runtimeReplay && Array.isArray(state.runtimeReplay.events) ? state.runtimeReplay.events : [];
    const customerRequestRow = history.find(function (item) {
      const status = String(item && item.dispatch_status || '').toLowerCase();
      return status !== 'completed' && status !== 'cancelled';
    }) || history[0] || null;
    const bookingManagementItems = actions.length
      ? actions
      : [
          { label: 'Reschedule requests pending review', value: Math.max(0, history.filter(function (ride) { return String(ride && ride.dispatch_status || '').toLowerCase() === 'pending'; }).length) },
          { label: 'No-show follow-up cases', value: Math.max(0, history.filter(function (ride) { return String(ride && ride.dispatch_status || '').toLowerCase() === 'no_show'; }).length) },
          { label: 'Authorization updates needed', value: Math.max(0, history.filter(function (ride) { return !ride || !ride.authorization_id; }).length) },
        ];
    const supportWorkflowItems = supportQueue.length
      ? supportQueue
      : [
          { label: 'Open rider support tickets', value: Math.max(0, history.filter(function (ride) { return String(ride && ride.dispatch_status || '').toLowerCase() === 'cancelled'; }).length) },
          { label: 'Escalated dispatch callbacks', value: Math.max(0, history.filter(function (ride) { return String(ride && ride.dispatch_status || '').toLowerCase() === 'delayed'; }).length) },
          { label: 'Billing clarification requests', value: Math.max(0, history.filter(function (ride) { return String(ride && ride.dispatch_status || '').toLowerCase() === 'completed'; }).length) },
        ];

    if (!activeRide) {
      els.customerActiveRide.innerHTML = '<div class="enterprise-inline-grid">'
        + MetricCard('Booking status', customerRequestRow ? escapeHtml(customerRequestRow.dispatch_status || 'pending') : 'idle', 'Latest request state for this rider', customerRequestRow ? statusTone(customerRequestRow.dispatch_status) : 'warn')
        + MetricCard('Next trip', customerRequestRow && customerRequestRow.scheduled_time ? formatDateShort(customerRequestRow.scheduled_time) : 'not scheduled', 'Upcoming scheduled transportation time', customerRequestRow && customerRequestRow.scheduled_time ? 'ok' : 'warn')
      + '</div><p class="health-summary">No active ride yet. Submit a request or wait for dispatch assignment.</p>';
      els.customerAssignment.innerHTML = '<p class="health-summary">Driver details, pickup countdown, and support controls will appear when dispatch confirms the trip.</p>';
    } else {
      const driverName = lookupDriverName(activeRide.driver_id);
      const etaMinutes = Number.isFinite(Number(liveEta)) ? Number(liveEta) : Number(activeRide.estimated_duration_minutes || 0);
      els.customerActiveRide.innerHTML = '<div class="enterprise-inline-grid">'
        + MetricCard('Trip ID', escapeHtml(String(activeRide.id || '').slice(0, 8)), 'Current trip reference for support and tracking', 'ok')
        + MetricCard('Status', escapeHtml(activeRide.status || 'pending'), 'Current trip lifecycle state', statusTone(activeRide.status))
        + MetricCard('Pickup', escapeHtml(activeRide.pickup_address || '-'), 'Pickup location for this booking', 'ok')
        + MetricCard('Dropoff', escapeHtml(activeRide.dropoff_address || '-'), 'Destination for this trip', 'ok')
        + '</div>';
      els.customerAssignment.innerHTML = '<div class="enterprise-inline-grid">'
        + MetricCard('Assigned driver', escapeHtml(driverName), 'Driver assigned by dispatch', activeRide.driver_id ? 'ok' : 'warn')
        + MetricCard('Pickup ETA', Number.isFinite(etaMinutes) ? formatMinutesCompact(etaMinutes) : 'awaiting route plan', 'Estimated arrival from live routing', Number.isFinite(etaMinutes) ? 'ok' : 'warn')
        + MetricCard('Provider', escapeHtml(lookupProviderName(activeRide.provider_id)), 'Facility or network partner on this trip', 'ok')
        + '</div>'
        + '<div class="health-row-actions">'
        + '<button class="health-row-btn warn" data-phase52-customer-action="ride_cancelled" data-phase52-ride-id="' + escapeHtml(String(activeRide.id || '')) + '">Cancel Ride</button>'
        + '<button class="health-row-btn" data-phase52-customer-action="escalation_requested" data-phase52-ride-id="' + escapeHtml(String(activeRide.id || '')) + '">Request Help</button>'
        + '<button class="health-row-btn ok" data-phase52-customer-action="ride_completed" data-phase52-ride-id="' + escapeHtml(String(activeRide.id || '')) + '">Confirm Dropoff</button>'
        + '</div>';
    }

    const bookingRows = bookingManagementItems.map(function (item) {
      const label = item && (item.label || item.title || item.name);
      const value = item && (item.value != null ? item.value : item.count);
      return '<div class="health-summary-card"><span>' + escapeHtml(String(label || 'Queue')) + '</span><strong>' + escapeHtml(String(value == null ? 0 : value)) + '</strong></div>';
    }).join('');
    els.customerBookingManagement.innerHTML = bookingRows
      ? '<div class="health-summary-grid">' + bookingRows + '</div>'
      : '<p class="health-summary">No booking management actions in queue.</p>';

    const supportRows = supportWorkflowItems.map(function (item) {
      const label = item && (item.label || item.title || item.name);
      const value = item && (item.value != null ? item.value : item.count);
      return '<div class="health-summary-card"><span>' + escapeHtml(String(label || 'Support')) + '</span><strong>' + escapeHtml(String(value == null ? 0 : value)) + '</strong></div>';
    }).join('');
    els.customerSupport.innerHTML = supportRows
      ? '<div class="health-summary-grid">' + supportRows + '</div>'
      : '<p class="health-summary">No support workflow actions in queue.</p>';

    els.customerRequestHistory.innerHTML = history.length
      ? renderTimelineList(history.slice(0, 12).map(function (item) {
          return {
            kind: item.dispatch_status || 'pending',
            summary: (item.rider_name || 'Rider') + ' · ' + (item.pickup_address || '-') + ' -> ' + (item.dropoff_address || '-'),
            timestamp: item.updated_at || item.created_at || stampNow(),
            severity: item.dispatch_status === 'cancelled' ? 'high' : 'info',
          };
        }), 'No customer request history yet.')
      : '<p class="health-summary">No previous bookings yet. New and recurring trips will appear here.</p>';

    if (liveTimeline.length) {
      els.customerTimeline.innerHTML = renderTimelineList(liveTimeline.slice(0, 16).map(function (item) {
        return {
          kind: item.event_name || 'dispatch',
          summary: item.message || item.event_name || 'Ride event',
          timestamp: item.timestamp || stampNow(),
          severity: String(item.event_name || '').indexOf('completed') !== -1 ? 'info' : 'medium',
        };
      }), 'Customer timeline is waiting for realtime ride lifecycle updates.');
    } else {
      const customerTimeline = Array.isArray(state.operationalEventFeed)
        ? state.operationalEventFeed.filter(function (item) {
            const type = String(item.eventType || item.kind || '').toLowerCase();
            return type.indexOf('ride') !== -1 || type.indexOf('driver') !== -1 || type.indexOf('dispatch') !== -1;
          }).slice(0, 10)
        : [];
      const mergedTimeline = customerTimeline.concat(runtimeTimeline.slice(0, 8).map(function (evt) {
        return {
          eventType: evt.event_alias || evt.event_name || 'runtime',
          timestamp: evt.timestamp || stampNow(),
          payload: { summary: (evt.event_alias || evt.event_name || 'runtime') + ' · ' + String((evt.details && evt.details.ride_id) || '').slice(0, 8) },
        };
      }));
      els.customerTimeline.innerHTML = operational_event_feed(mergedTimeline, 'Customer timeline is waiting for realtime ride lifecycle updates.');
    }
  }

  function renderAdminWorkspace() {
    const els = getEls();
    if (!els.adminSummary || !els.adminRoleSessions || !els.adminWebsocket || !els.adminRuntimeValidation || !els.adminLifecycleAudit) return;

    const summary = state.adminSummary && typeof state.adminSummary === 'object' ? state.adminSummary : null;
    if (!summary) {
      els.adminSummary.innerHTML = '<p class="health-summary">Admin operations data is loading.</p>';
      els.adminRoleSessions.innerHTML = '<p class="health-summary">Escalation queue is not available yet.</p>';
      els.adminWebsocket.innerHTML = '<p class="health-summary">Approvals queue is not available yet.</p>';
      els.adminRuntimeValidation.innerHTML = '<p class="health-summary">Compliance events are not available yet.</p>';
      els.adminLifecycleAudit.innerHTML = '<p class="health-summary">Audit queue is not available yet.</p>';
      return;
    }

    const websocket = summary.websocket && typeof summary.websocket === 'object' ? summary.websocket : {};
    const liveOps = state.adminLiveOperations && typeof state.adminLiveOperations === 'object' ? state.adminLiveOperations : null;
    const liveAlerts = state.adminDispatchAlerts && typeof state.adminDispatchAlerts === 'object' ? state.adminDispatchAlerts : null;
    const runtimeValidation = summary.runtime_validation && typeof summary.runtime_validation === 'object' ? summary.runtime_validation : {};
    const queueMetrics = summary.queue_metrics && typeof summary.queue_metrics === 'object' ? summary.queue_metrics : {};
    const assignmentBreakdown = summary.assignment_state_breakdown && typeof summary.assignment_state_breakdown === 'object' ? summary.assignment_state_breakdown : {};

    els.adminSummary.innerHTML = '<div class="enterprise-inline-grid">'
      + MetricCard('Dispatch queue', formatNumber(summary.dispatch_queue_count || 0), 'Current queue depth across transport operations', (summary.dispatch_queue_count || 0) > 20 ? 'warn' : 'ok')
      + MetricCard('Active assignments', formatNumber(summary.active_assignment_count || 0), 'Live assignment workload', (summary.active_assignment_count || 0) > 15 ? 'warn' : 'ok')
      + MetricCard('Rejected offers', formatNumber(summary.rejected_offer_count || 0), 'Offer-level rejections observed', (summary.rejected_offer_count || 0) > 0 ? 'warn' : 'ok')
      + MetricCard('Reassignments', formatNumber(summary.reassignment_event_count || 0), 'Dispatch reassignment pressure indicator', (summary.reassignment_event_count || 0) > 0 ? 'warn' : 'ok')
      + MetricCard('Queue pending', formatNumber(queueMetrics.pending || 0), 'Pending customer requests', (queueMetrics.pending || 0) > 0 ? 'warn' : 'ok')
      + MetricCard('Queue dispatchable', formatNumber(queueMetrics.dispatchable || 0), 'Requests ready for dispatch', (queueMetrics.dispatchable || 0) > 0 ? 'warn' : 'ok')
      + MetricCard('Stale assignments', formatNumber(liveOps && Array.isArray(liveOps.stale_assignments) ? liveOps.stale_assignments.length : 0), 'Assignments near expiry requiring intervention', liveOps && Array.isArray(liveOps.stale_assignments) && liveOps.stale_assignments.length ? 'danger' : 'ok')
      + MetricCard('Dispatch alerts', formatNumber(liveAlerts && Array.isArray(liveAlerts.alerts) ? liveAlerts.alerts.length : 0), 'Live dispatch alerts raised by simulation layer', liveAlerts && Array.isArray(liveAlerts.alerts) && liveAlerts.alerts.length ? 'warn' : 'ok')
      + '</div>';

    const staleRows = liveOps && Array.isArray(liveOps.stale_assignments) ? liveOps.stale_assignments : [];
    const activeRows = liveOps && Array.isArray(liveOps.active_rides) ? liveOps.active_rides : [];
    const alertsRows = liveAlerts && Array.isArray(liveAlerts.alerts) ? liveAlerts.alerts : [];
    const runtimeState = state.runtimeState && typeof state.runtimeState === 'object' ? state.runtimeState : null;
    const interventionRows = staleRows.slice(0, 4).map(function (item) {
      const matchingOffer = (state.dispatchActiveAssignments || []).find(function (row) {
        return String(row.ride_id || '') === String(item.ride_id || '') && String(row.assignment_state || '').toLowerCase() === 'offered';
      });
      return '<article class="health-item-card">'
        + '<div class="health-row"><strong>Ride ' + escapeHtml(String(item.ride_id || '').slice(0, 8)) + '</strong><span class="health-pill warn">intervene</span></div>'
        + '<div class="health-summary">Offer is aging and may need manual reassignment.</div>'
        + '<div class="health-row-actions">'
        + '<button class="health-row-btn warn" data-admin-expire-offer="' + escapeHtml((matchingOffer && matchingOffer.offer_id) || '') + '">Force Expire</button>'
        + '<button class="health-row-btn" data-admin-reassign-ride="' + escapeHtml(item.ride_id || '') + '">Reassign Driver</button>'
        + '<button class="health-row-btn secondary" data-admin-recover-ride="' + escapeHtml(item.ride_id || '') + '">Recover Dispatch</button>'
        + '</div>'
        + '</article>';
    }).join('');

    const replayRows = state.runtimeReplay && Array.isArray(state.runtimeReplay.events) ? state.runtimeReplay.events.slice(0, 10) : [];
    const futureCategories = (state.serviceCategories || []).filter(function (item) { return !item.active; });

    els.adminRoleSessions.innerHTML = '<h4>Escalations</h4>' + (interventionRows || '<p class="health-summary">No escalations waiting for supervisor intervention.</p>');

    els.adminWebsocket.innerHTML = '<h4>Approvals</h4>'
      + '<div class="enterprise-inline-grid">'
      + MetricCard('Open approvals', formatNumber(state.governanceApprovals.length), 'Requests waiting for operations leadership approval', state.governanceApprovals.length ? 'warn' : 'ok')
      + MetricCard('Dispatch alerts', formatNumber(alertsRows.length), 'Alerts requiring explicit operator acknowledgment', alertsRows.length ? 'warn' : 'ok')
      + MetricCard('Queue pending', formatNumber(queueMetrics.pending || 0), 'Pending requests awaiting action', (queueMetrics.pending || 0) ? 'warn' : 'ok')
      + MetricCard('Assignment offers', formatNumber(summary.active_assignment_count || 0), 'Offers currently in active lifecycle', (summary.active_assignment_count || 0) ? 'ok' : 'warn')
      + '</div>';
    els.adminRuntimeValidation.innerHTML = '<h4>Compliance Events</h4>'
      + '<div class="enterprise-inline-grid">'
      + MetricCard('Compliance health', escapeHtml(runtimeValidation.lifecycle_guardrails || 'enabled'), 'Policy checks on ride lifecycle and assignment actions', 'ok')
      + MetricCard('Data integrity', escapeHtml(runtimeValidation.idempotency_integrity || 'stable'), 'Duplicate prevention and event consistency', 'ok')
      + MetricCard('Retry queue', formatNumber((runtimeValidation.queue_depth && runtimeValidation.queue_depth.pending_count) || 0), 'Events awaiting retry processing', ((runtimeValidation.queue_depth && runtimeValidation.queue_depth.pending_count) || 0) > 0 ? 'warn' : 'ok')
      + MetricCard('Future policy set', formatNumber(futureCategories.length), 'Reserved categories held by policy controls', futureCategories.length ? 'warn' : 'ok')
      + '</div>';
    els.adminLifecycleAudit.innerHTML = '<h4>Audit Queue</h4>'
      + '<div class="enterprise-inline-grid">'
      + MetricCard('Audit sequence', formatNumber((runtimeState && runtimeState.sequence) || 0), 'Ordered event index for compliance review', 'ok')
      + MetricCard('Audit subscribers', formatNumber(runtimeState && Array.isArray(runtimeState.websocket_subscriber_registry) ? runtimeState.websocket_subscriber_registry.length : 0), 'Active audit and supervisor subscribers', 'ok')
      + MetricCard('Reconnect events', formatNumber((runtimeState && runtimeState.runtime_reconnect_count) || 0), 'Reconnect actions captured in audit queue', ((runtimeState && runtimeState.runtime_reconnect_count) || 0) > 0 ? 'warn' : 'ok')
      + '</div>'
      + (futureCategories.length ? '<div class="health-summary">Policy-held categories: ' + escapeHtml(futureCategories.map(function (item) { return item.label || item.key || 'future'; }).join(', ')) + '</div>' : '')
      + renderTimelineList((summary.recent_dispatch_actions || []).concat(alertsRows.map(function (item) {
        return {
          action: item.alert_type || 'dispatch-alert',
          note: item.message || item.alert_type || 'Dispatch alert',
          ride_id: item.ride_id,
          created_at: item.created_at,
        };
      })).map(function (item) {
      return {
        kind: item.action || 'dispatch',
        summary: (item.note || item.action || 'Dispatch action') + ' · ride ' + String(item.ride_id || '').slice(0, 8),
        timestamp: item.created_at || stampNow(),
        severity: String(item.action || '').toLowerCase().indexOf('cancel') !== -1 ? 'high' : 'info',
      };
    }), 'No lifecycle audit actions recorded.')
      + (replayRows.length ? renderTimelineList(replayRows.map(function (item) {
        return {
          kind: item.event_alias || item.event_name || 'operations',
          summary: (item.event_alias || item.event_name || 'operations') + ' · ride ' + String(item.details && item.details.ride_id || '').slice(0, 8),
          timestamp: item.timestamp || stampNow(),
          severity: (item.event_alias === 'ride_cancelled' || item.event_alias === 'escalation_created') ? 'high' : 'info',
        };
      }), 'Lifecycle replay viewer has no operational rows yet.') : '')
      + (activeRows.length ? '<div class="health-summary">Live rides under command center watch: ' + formatNumber(activeRows.length) + '</div>' : '');

    state.adminRoleSessions = assignmentBreakdown;
  }

  function renderOnboarding() {
    const els = getEls();
    if (!els.onboardingSummary || !els.onboardingList) return;
    const apps = Array.isArray(state.driverApplications) ? state.driverApplications : [];
    const counts = apps.reduce(function (acc, item) {
      const key = String(item.onboarding_status || "applied").toLowerCase();
      acc[key] = (acc[key] || 0) + 1;
      return acc;
    }, {});
    els.onboardingSummary.innerHTML = '<div class="enterprise-inline-grid">'
      + MetricCard('Applications', apps.length, 'Independent driver applications in lifecycle', 'ok')
      + MetricCard('Pending review', counts.pending_review || 0, 'Review queue awaiting admin action', (counts.pending_review || 0) ? 'warn' : 'ok')
      + MetricCard('Approved/Active', (counts.approved || 0) + (counts.active || 0), 'Approved drivers ready for operations', ((counts.approved || 0) + (counts.active || 0)) ? 'ok' : 'warn')
      + MetricCard('Suspended', counts.suspended || 0, 'Applications blocked from activation', (counts.suspended || 0) ? 'danger' : 'ok')
      + '</div>';

    if (!apps.length) {
      els.onboardingList.innerHTML = '<p class="health-summary">No applications yet. Submit a candidate above or run Phase 43 seed data.</p>';
      return;
    }

    const rows = apps.map(function (item) {
      const categories = Array.isArray(item.preferred_service_categories) ? item.preferred_service_categories.join(', ') : '';
      return '<article class="health-item-card">'
        + '<div class="health-row"><strong>' + escapeHtml(item.applicant_name || '-') + '</strong><span class="health-pill ' + pillClass(item.onboarding_status) + '">' + escapeHtml(item.onboarding_status || 'applied') + '</span></div>'
        + '<div class="health-summary">Phone: ' + escapeHtml(item.applicant_phone || '-') + ' · Vehicle: ' + escapeHtml((item.vehicle_make || '') + ' ' + (item.vehicle_model || '')) + '</div>'
        + '<div class="health-summary">Categories: ' + escapeHtml(categories || 'n/a') + ' · Availability: ' + escapeHtml(item.availability_summary || 'n/a') + '</div>'
        + '<div class="health-row-actions">'
        + '<button class="health-row-btn" data-driver-app-status="pending_review" data-driver-app-id="' + escapeHtml(item.id) + '">Queue Review</button>'
        + '<button class="health-row-btn ok" data-driver-app-status="approved" data-driver-app-id="' + escapeHtml(item.id) + '">Approve</button>'
        + '<button class="health-row-btn secondary" data-driver-app-status="active" data-driver-app-id="' + escapeHtml(item.id) + '">Activate</button>'
        + '<button class="health-row-btn warn" data-driver-app-status="suspended" data-driver-app-id="' + escapeHtml(item.id) + '">Suspend</button>'
        + '</div>'
        + '</article>';
    }).join('');

    els.onboardingList.innerHTML = rows;
  }

  function renderGrantProof() {
    const els = getEls();
    if (!els.grantMetrics || !els.grantScreenshots || !els.recurringTemplates) return;
    const snapshot = state.grantSnapshot || {};
    const metrics = snapshot.metrics && typeof snapshot.metrics === 'object' ? snapshot.metrics : {};
    const screenshots = Array.isArray(snapshot.screenshot_inventory) ? snapshot.screenshot_inventory : [];
    const templates = Array.isArray(state.recurringTemplates) ? state.recurringTemplates : [];

    els.grantMetrics.innerHTML = '<div class="enterprise-inline-grid">'
      + MetricCard('Grant target', escapeHtml(metrics.target_date || '2025-06-15'), 'Rural transportation readiness deadline', 'ok')
      + MetricCard('Total rides', formatNumber(metrics.total_rides || state.rides.length), 'Operational transportation evidence', 'ok')
      + MetricCard('Recurring templates', formatNumber(metrics.recurring_templates || templates.length), 'Scheduled recurring route coverage', (metrics.recurring_templates || templates.length) ? 'ok' : 'warn')
      + MetricCard('Onboarding pipeline', formatNumber(metrics.driver_applications_total || state.driverApplications.length), 'Driver onboarding pipeline evidence', (metrics.driver_applications_total || state.driverApplications.length) ? 'ok' : 'warn')
      + MetricCard('Pending applications', formatNumber(metrics.driver_applications_pending || 0), 'Review workload for launch readiness', (metrics.driver_applications_pending || 0) ? 'warn' : 'ok')
      + MetricCard('Approved applications', formatNumber(metrics.driver_applications_approved || 0), 'Activated contractor capacity', (metrics.driver_applications_approved || 0) ? 'ok' : 'warn')
      + '</div>';

    els.grantScreenshots.innerHTML = screenshots.length
      ? screenshots.map(function (item) {
          return '<div class="health-row"><strong>' + escapeHtml(item.label || item.id || 'Capture') + '</strong><span class="health-pill ' + pillClass(item.status) + '">' + escapeHtml(item.status || 'pending') + '</span></div>';
        }).join('')
      : '<p class="health-summary">No screenshot checklist generated yet.</p>';

    els.recurringTemplates.innerHTML = templates.length
      ? templates.slice(0, 10).map(function (item) {
          const recur = item.recurrence && typeof item.recurrence === 'object' ? item.recurrence : {};
          const days = Array.isArray(recur.days) ? recur.days.join(', ') : 'schedule pending';
          return '<article class="health-item-card">'
            + '<div class="health-row"><strong>' + escapeHtml(item.rider_name || '-') + '</strong><span class="health-pill ' + pillClass(item.last_status) + '">' + escapeHtml(item.last_status || 'pending') + '</span></div>'
            + '<div class="health-summary">Category: ' + escapeHtml(item.category || item.service_type || 'general') + ' · Pickup: ' + escapeHtml(item.preferred_pickup_time || 'n/a') + '</div>'
            + '<div class="health-summary">Days: ' + escapeHtml(days) + '</div>'
            + '<div class="health-summary">Route: ' + escapeHtml(item.pickup_address || '-') + ' → ' + escapeHtml(item.dropoff_address || '-') + '</div>'
            + '</article>';
        }).join('')
      : '<p class="health-summary">No recurring templates yet. Seed Phase 43 data to generate examples.</p>';
  }

  function renderRideTimeline() {
    const els = getEls();
    if (!els.workflow) return;
    const ride = state.rides.find((item) => item.id === state.selectedRideId) || state.rides[0] || null;
    if (!ride) {
      els.workflow.innerHTML = '<div class="workflow-card"><h3>Ride Timeline</h3><p class="health-summary">No ride selected.</p></div>';
      return;
    }
    const history = Array.isArray(state.selectedRideHistory) ? state.selectedRideHistory : [];
    const dispatchHistory = Array.isArray(state.selectedRideDispatchHistory) ? state.selectedRideDispatchHistory : [];
    const driverName = lookupDriverName(ride.driver_id);
    const timeline = history.map((event) => {
      return '<li><span class="health-pill ' + pillClass(event.to_status) + '">' + escapeHtml(event.to_status || "unknown") + '</span><strong>' + escapeHtml(event.note || event.from_status || "status updated") + '</strong><small>' + escapeHtml(new Date(event.created_at).toLocaleString()) + '</small></li>';
    }).join("");
    const dispatchFeed = dispatchHistory.map((log) => {
      return '<li class="dispatch-log-item"><span class="health-pill dispatch-action">' + escapeHtml(log.action || "action") + '</span>' + escapeHtml(log.note || "") + '<small>' + escapeHtml(new Date(log.created_at).toLocaleString()) + '</small></li>';
    }).join("");
    els.workflow.innerHTML = [
      '<div class="workflow-card">',
      '<div class="health-panel">',
      '<h3>Ride Timeline</h3>',
      '<p class="health-summary">Current state: <strong>' + escapeHtml(ride.status || "unknown") + '</strong></p>',
      '<p class="health-summary">Assigned driver: <strong>' + escapeHtml(driverName) + '</strong></p>',
      '<p class="health-summary">Requested: ' + escapeHtml(new Date(ride.requested_at || Date.now()).toLocaleString()) + '</p>',
      '<p class="health-summary">Accepted: ' + escapeHtml(ride.accepted_at ? new Date(ride.accepted_at).toLocaleString() : "-") + '</p>',
      '<p class="health-summary">Completed: ' + escapeHtml(ride.completed_at ? new Date(ride.completed_at).toLocaleString() : "-") + '</p>',
      '<h4 style="margin-top:10px;font-size:0.82rem;color:var(--text-dim)">Status History</h4>',
      '<ul class="health-timeline-feed">' + (timeline || '<li><span class="health-pill ok">live</span><strong>No history yet</strong></li>') + '</ul>',
      '<h4 style="margin-top:10px;font-size:0.82rem;color:var(--text-dim)">Dispatch Log</h4>',
      '<ul class="health-timeline-feed">' + (dispatchFeed || '<li><strong>No dispatch log entries.</strong></li>') + '</ul>',
      '</div>',
      '</div>',
    ].join("");
  }

  function renderAnalytics() {
    const els = getEls();
    if (!els.rideMix || !els.driverCapacity) return;
    const enterprise = state.enterpriseDashboard || {};
    const analytics = enterprise.analytics && typeof enterprise.analytics === "object"
      ? enterprise.analytics
      : (state.aiSnapshot && state.aiSnapshot.analytics ? state.aiSnapshot.analytics : null);
    const hasCoreData = state.rides.length > 0 || state.drivers.length > 0;

    const statusCounts = state.rides.reduce((acc, ride) => {
      const key = String(ride.status || "unknown").toLowerCase();
      acc[key] = (acc[key] || 0) + 1;
      return acc;
    }, {});

    const maxRideMix = Math.max(1, ...Object.values(statusCounts));
    const rideChartItems = Object.entries(statusCounts).map(function (entry) {
      return {
        label: entry[0],
        value: entry[1],
        displayValue: entry[1],
      };
    });

    const driverStatus = state.drivers.reduce((acc, driver) => {
      const key = String(driver.status || "unknown").toLowerCase();
      acc[key] = (acc[key] || 0) + 1;
      return acc;
    }, {});

    const driverRows = Object.entries(driverStatus).map(function (entry) {
      return {
        label: entry[0],
        value: entry[1],
        displayValue: entry[1],
      };
    });

    const dashboardTrend = enterprise.dashboard && Array.isArray(enterprise.dashboard.ride_throughput_chart)
      ? enterprise.dashboard.ride_throughput_chart
      : [];
    const throughputPoints = dashboardTrend.length
      ? dashboardTrend.slice(-8).map(function (item) {
          const minute = String(item.minute || '').split('T')[1] || String(item.minute || 'now');
          return {
            label: minute.slice(0, 5) || 'now',
            value: Number(item.value || 0),
          };
        })
      : [
          { label: 'T-5', value: Math.max(1, state.rides.length - 2) },
          { label: 'T-4', value: Math.max(1, state.rides.length - 1) },
          { label: 'T-3', value: Math.max(1, state.rides.length) },
          { label: 'T-2', value: Math.max(1, state.rides.length + 1) },
          { label: 'T-1', value: Math.max(1, state.rides.length) },
          { label: 'Now', value: Math.max(1, state.rides.length + (state.pendingRequests > 0 ? 1 : 0)) },
        ];

    els.rideMix.innerHTML = AnalyticsChart({
      type: 'bar',
      items: rideChartItems,
      emptyText: 'No ride analytics yet.',
      timestamp: enterprise.last_synced_at || state.hydration.lastRefreshAt,
      footer: 'Ride mix across the live dispatch queue',
    });
    els.driverCapacity.innerHTML = AnalyticsChart({
      type: 'bar',
      items: driverRows,
      emptyText: 'No driver analytics yet.',
      timestamp: enterprise.last_synced_at || state.hydration.lastRefreshAt,
      footer: 'Driver capacity by live status bucket',
    });

    if (els.providerPerformance) {
      const leaders = analytics && analytics.provider_performance ? analytics.provider_performance.leaders : [];
      if (!analytics) {
        const fallback = hasCoreData
          ? 'Provider analytics temporarily degraded (AI snapshot unavailable). Core ride and driver data is live.'
          : 'Provider analytics loading from live operations feed.';
        els.providerPerformance.innerHTML = '<p class="health-summary">' + escapeHtml(fallback) + '</p>';
      } else {
        els.providerPerformance.innerHTML = AnalyticsChart({
          type: 'bar',
          items: (leaders || []).map(function (item) {
            const completed = Number(item.completed || 0);
            const active = Number(item.active || 0);
            const cancelled = Number(item.cancelled || 0);
            const score = clampPercent(((completed + Math.max(0, active - cancelled)) / Math.max(completed + active + cancelled, 1)) * 100);
            return {
              label: item.provider_name || item.provider_id || 'Provider',
              value: score,
              displayValue: formatPercent(score),
            };
          }),
          emptyText: 'Provider analytics pending.',
          timestamp: enterprise.last_synced_at || state.hydration.lastRefreshAt,
          footer: 'Top provider SLA performance',
        });
      }
    }
    if (els.operationalLoad) {
      const load = analytics && analytics.realtime_operational_load ? analytics.realtime_operational_load : {};
      if (!analytics) {
        const wsState = state.websocketStatus === 'connected' ? 'connected' : state.websocketStatus;
        els.operationalLoad.innerHTML = '<div class="health-chart-list">'
          + card('Operational Feed', hasCoreData ? 'Degraded' : 'Loading')
          + card('Realtime Socket', wsState)
          + card('Last Hydration', state.hydration.lastRefreshAt ? formatDateShort(state.hydration.lastRefreshAt) : 'pending')
          + card('Last Enterprise Sync', enterprise.last_synced_at ? formatDateShort(enterprise.last_synced_at) : 'pending')
          + '</div>';
      } else {
        els.operationalLoad.innerHTML = AnalyticsChart({
          type: 'line',
          points: throughputPoints,
          timestamp: enterprise.last_synced_at || state.hydration.lastRefreshAt,
          footer: 'Dispatch throughput trend · Utilization ' + Number(load.driver_utilization_percent || 0).toFixed(1) + '% · Failed events ' + formatNumber(load.failed_event_count),
        }) + '<div class="enterprise-inline-grid">'
          + MetricCard('Driver utilization', Number(load.driver_utilization_percent || 0).toFixed(1) + '%', 'Live capacity saturation', Number(load.driver_utilization_percent || 0) >= 75 ? 'danger' : 'ok')
          + MetricCard('Websocket connections', formatNumber(load.websocket_connection_count), 'Realtime operator sessions connected', 'ok')
          + MetricCard('Failed events', formatNumber(load.failed_event_count), 'Operational event replay watchlist', Number(load.failed_event_count || 0) ? 'warn' : 'ok')
          + MetricCard('Dispatch throughput', formatNumber(load.dispatch_throughput_per_minute), 'Events processed per minute', 'ok')
          + '</div>';
      }
    }
    if (els.aiAnalyticsRecommendations) {
      const slaStatus = enterprise.sla_status || {};
      const workflow = analytics && analytics.workflow_success_failure_metrics ? analytics.workflow_success_failure_metrics : {};
      if (!analytics) {
        const reason = state.hydration.aiSnapshotError || 'snapshot unavailable';
        els.aiAnalyticsRecommendations.innerHTML = '<p class="health-summary">SLA compliance analytics degraded: ' + escapeHtml(reason) + '.</p>';
      } else {
        els.aiAnalyticsRecommendations.innerHTML = '<div class="enterprise-inline-grid">'
          + MetricCard('SLA score', Number(slaStatus.score || 0).toFixed(1) + '%', 'Composite provider, workflow, and emergency compliance score', Number(slaStatus.score || 0) >= 85 ? 'ok' : 'warn')
          + MetricCard('Workflow success', Number(workflow.success_rate || 0).toFixed(1) + '%', 'Success rate across workflow executions', Number(workflow.success_rate || 0) >= 85 ? 'ok' : 'warn')
          + MetricCard('Provider completion', Number(slaStatus.provider_completion_rate || 0).toFixed(1) + '%', 'Completed provider work over total tracked load', Number(slaStatus.provider_completion_rate || 0) >= 80 ? 'ok' : 'warn')
          + MetricCard('Emergency pressure', Number(slaStatus.emergency_percentage || 0).toFixed(1) + '%', 'Share of active high-acuity rides', Number(slaStatus.emergency_percentage || 0) >= 25 ? 'danger' : 'ok')
          + '</div>'
          + AnalyticsChart({
            type: 'bar',
            items: [
              { label: 'Composite SLA', value: Number(slaStatus.score || 0), displayValue: formatPercent(slaStatus.score || 0) },
              { label: 'Workflow success', value: Number(workflow.success_rate || 0), displayValue: formatPercent(workflow.success_rate || 0) },
              { label: 'Provider completion', value: Number(slaStatus.provider_completion_rate || 0), displayValue: formatPercent(slaStatus.provider_completion_rate || 0) },
              { label: 'Emergency pressure', value: 100 - clampPercent(Number(slaStatus.emergency_percentage || 0)), displayValue: formatPercent(100 - clampPercent(Number(slaStatus.emergency_percentage || 0))) },
            ],
            timestamp: enterprise.last_synced_at || state.hydration.lastRefreshAt,
            footer: 'SLA compliance metrics',
          });
      }
    }
    if (els.emergencyStats) {
      const emergency = analytics && analytics.emergency_ride_statistics ? analytics.emergency_ride_statistics : {};
      const workflow = analytics && analytics.workflow_success_failure_metrics ? analytics.workflow_success_failure_metrics : {};
      if (!analytics) {
        els.emergencyStats.innerHTML = '<div class="health-chart-list">'
          + card('Active Emergency Rides', formatNumber(state.rides.filter((ride) => Boolean(ride.is_emergency)).length))
          + card('Emergency %', state.rides.length ? Number((state.rides.filter((ride) => Boolean(ride.is_emergency)).length / state.rides.length) * 100).toFixed(1) + '%' : '0.0%')
          + card('Workflow Success Rate', 'degraded')
          + '</div>';
      } else {
        els.emergencyStats.innerHTML = '<div class="enterprise-inline-grid">'
          + MetricCard('Active emergency rides', formatNumber(emergency.active_emergency_rides), 'Current emergency transport volume', Number(emergency.active_emergency_rides || 0) ? 'danger' : 'ok')
          + MetricCard('Emergency %', Number(emergency.emergency_percentage || 0).toFixed(1) + '%', 'Share of rides marked emergency', Number(emergency.emergency_percentage || 0) >= 20 ? 'danger' : 'warn')
          + MetricCard('Workflow success', Number(workflow.success_rate || 0).toFixed(1) + '%', 'Emergency orchestration success rate', Number(workflow.success_rate || 0) >= 85 ? 'ok' : 'warn')
          + MetricCard('SLA state', (enterprise.sla_status && enterprise.sla_status.status) || 'watch', 'Composite compliance signal', statusTone((enterprise.sla_status && enterprise.sla_status.status) || 'watch'))
          + '</div>'
          + AnalyticsChart({
            type: 'bar',
            items: [
              { label: 'Emergency rides', value: Number(emergency.active_emergency_rides || 0), displayValue: formatNumber(emergency.active_emergency_rides || 0) },
              { label: 'Emergency %', value: Number(emergency.emergency_percentage || 0), displayValue: Number(emergency.emergency_percentage || 0).toFixed(1) + '%' },
              { label: 'Workflow success', value: Number(workflow.success_rate || 0), displayValue: Number(workflow.success_rate || 0).toFixed(1) + '%' },
            ],
            timestamp: enterprise.last_synced_at || state.hydration.lastRefreshAt,
            footer: 'Emergency ride analytics',
          });
      }
    }

    const analyticsWs = getWebsocketMetrics();
    if (els.analyticsOperationalFeed) {
      els.analyticsOperationalFeed.innerHTML = operational_event_feed(state.operationalEventFeed.slice(0, 8), 'Operational feed initializing - realtime events will appear here');
    }
    if (els.analyticsRecommendations) {
      els.analyticsRecommendations.innerHTML = operational_recommendation_panel(getUnifiedOperationalRecommendations('operational_summaries', 8), 'AI operational analysis preparing...');
    }
    if (els.analyticsGovernance) {
      els.analyticsGovernance.innerHTML = hc_section('Governance', governance_status_panel(getGovernanceSnapshot() || {}, state.governanceApprovals || [], (state.operationalStatus && state.operationalStatus.governance_audits) || []), { collapsed: false, pulse: true });
    }
    if (els.analyticsAudit) {
      els.analyticsAudit.innerHTML = hc_section('Audit Visibility', audit_visibility_feed((state.operationalStatus && state.operationalStatus.governance_audits) || [], 'Awaiting refreshed operations data...'), { collapsed: true, pulse: false });
    }
    if (els.analyticsMemory) {
      els.analyticsMemory.innerHTML = hc_section('Memory Fabric', operational_memory_panel(getOperationalMemorySnapshot(), state.operationalMemoryReferences || [], 'Awaiting memory fabric synchronization'), { collapsed: true, pulse: true, pulseTone: 'idle' });
    }
    if (els.analyticsWebsocket) {
      els.analyticsWebsocket.innerHTML = hc_section('WebSocket Diagnostics', websocket_runtime_monitor(analyticsWs.metrics, analyticsWs.websocket, analyticsWs.sync, analyticsWs.replay), { collapsed: true, pulse: state.websocketStatus === 'connected', pulseTone: state.websocketStatus === 'connected' ? '' : 'idle' });
    }
    if (els.analyticsSync) {
      els.analyticsSync.innerHTML = hc_section('Sync Continuity', synchronization_health_panel(analyticsWs.sync, analyticsWs.replay), { collapsed: true, pulse: false });
    }

    logDiag('Analytics hydrated', {
      hasAnalytics: !!analytics,
      rideCount: state.rides.length,
      driverCount: state.drivers.length,
      providerCount: state.providers.length,
      snapshotDegraded: state.hydration.aiSnapshotDegraded,
      snapshotError: state.hydration.aiSnapshotError,
    });
  }

  function renderAll() {
    applyRoleUiAccess();
    // Hydrate the create-ride provider select early so unrelated view errors do not block options.
    hydrateProviderSelect();
    hydrateDispatchFilters();
    renderDashboard();
    renderRides();
    renderDispatchWorkspace();
    renderDrivers();
    renderProviders();
    renderCustomerWorkspace();
    renderAdminWorkspace();
    renderOnboarding();
    renderGrantProof();
    renderAIOperations();
    renderAnalytics();
    renderBillingWorkspace();
    renderOperationsRail();
  }

  function renderOperationsRail() {
    const activityEl = document.getElementById("ops-rail-activity");
    const alertsEl = document.getElementById("ops-rail-alerts");
    const selectionEl = document.getElementById("ops-rail-selection");

    if (activityEl) {
      const items = (state.operationalEventFeed || []).slice(0, 6);
      activityEl.innerHTML = items.length ? items.map(function (event) {
        const title = firstDefined(event && event.title, event && event.event_type, event && event.message, "Operational event");
        const details = firstDefined(event && event.summary, event && event.reasoning, event && event.detail, "No additional details");
        const when = formatDateShort(event && (event.created_at || event.timestamp || event.generated_at));
        return '<article class="health-stack-item">'
          + '<div class="health-stack-title-row"><strong>' + escapeHtml(title) + '</strong></div>'
          + '<p>' + escapeHtml(details) + '</p>'
          + '<small>' + escapeHtml(when) + '</small>'
          + '</article>';
      }).join("") : '<p class="health-summary">Live activity feed will appear as dispatch and workforce events are received.</p>';
    }

    if (alertsEl) {
      const delayed = (state.rides || []).filter(function (ride) {
        const status = String((ride && ride.status) || "").toLowerCase();
        return status === "delayed" || status === "cancelled" || status === "problem";
      }).length;
      const urgent = (state.rides || []).filter(function (ride) {
        const priority = String(getPriorityTag(ride) || "").toLowerCase();
        return priority === "emergency" || priority === "urgent";
      }).length;
      const offlineDrivers = (state.drivers || []).filter(function (driver) {
        const availability = String((driver && driver.availability) || (driver && driver.status) || "").toLowerCase();
        return availability === "offline" || availability === "unavailable";
      }).length;
      alertsEl.innerHTML = '<div class="health-chart-list">'
        + card('Urgent rides', formatNumber(urgent))
        + card('Delayed/problem rides', formatNumber(delayed))
        + card('Offline/unavailable drivers', formatNumber(offlineDrivers))
        + '</div>';
    }

    if (selectionEl) {
      if ((state.route === "rides" || state.route === "dispatch") && state.selectedRideId) {
        const ride = (state.rides || []).find(function (item) {
          return String(item && item.id) === String(state.selectedRideId);
        });
        selectionEl.innerHTML = ride
          ? '<strong>Ride ' + escapeHtml(ride.id) + '</strong><p>' + escapeHtml(ride.passenger_name || 'Passenger') + ' · ' + escapeHtml(ride.status || 'pending') + '</p><p>' + escapeHtml(firstDefined(ride.pickup_address, 'Pickup not provided')) + ' -> ' + escapeHtml(firstDefined(ride.dropoff_address, 'Dropoff not provided')) + '</p>'
          : '<p class="health-summary">Selected ride is no longer available in the active queue.</p>';
      } else if (state.route === "drivers" && state.selectedDriverId) {
        const driver = (state.drivers || []).find(function (item) {
          return String(item && item.id) === String(state.selectedDriverId);
        });
        selectionEl.innerHTML = driver
          ? '<strong>Driver ' + escapeHtml(driver.name || driver.id) + '</strong><p>Status: ' + escapeHtml(driver.status || driver.availability || 'unknown') + '</p><p>Phone: ' + escapeHtml(driver.phone || 'not provided') + '</p>'
          : '<p class="health-summary">Selected driver details are unavailable.</p>';
      } else if (state.route === "providers") {
        const provider = (state.providers || [])[0] || null;
        selectionEl.innerHTML = provider
          ? '<strong>Provider ' + escapeHtml(provider.name || provider.id) + '</strong><p>Coverage: ' + escapeHtml(provider.coverage_area || provider.region || 'regional') + '</p><p>Capacity: ' + escapeHtml(String(provider.capacity || provider.available_capacity || 'n/a')) + '</p>'
          : '<p class="health-summary">Provider context will appear once network data is loaded.</p>';
      } else if (state.route === "customer") {
        const activeRide = state.customerWorkspace && state.customerWorkspace.activeRide ? state.customerWorkspace.activeRide : null;
        selectionEl.innerHTML = activeRide
          ? '<strong>Active customer trip</strong><p>Ride: ' + escapeHtml(activeRide.id || 'unknown') + '</p><p>Status: ' + escapeHtml(activeRide.status || 'pending') + '</p>'
          : '<p class="health-summary">No active customer trip selected. Use customer workspace to load rider context.</p>';
      } else {
        selectionEl.innerHTML = '<p class="health-summary">Route focus: ' + escapeHtml(state.route || PRIMARY_ROUTE) + '. Select an entity to inspect live operational details.</p>';
      }
    }
  }

  function renderFilterOptions(selectEl, items, currentValue, labelBuilder) {
    if (!selectEl) return;
    const options = items.map((item) => {
      const value = String(item.value || "");
      const label = String(labelBuilder(item) || value);
      return '<option value="' + escapeHtml(value) + '">' + escapeHtml(label) + '</option>';
    }).join("");
    selectEl.innerHTML = '<option value="all">All</option>' + options;
    selectEl.value = currentValue || "all";
  }

  function normalizeProvidersList(payload) {
    let list = [];
    if (Array.isArray(payload)) {
      list = payload;
    } else if (payload && Array.isArray(payload.providers)) {
      list = payload.providers;
    } else if (payload && Array.isArray(payload.items)) {
      list = payload.items;
    } else if (payload && payload.data && Array.isArray(payload.data.providers)) {
      list = payload.data.providers;
    }

    return list
      .filter(function (item) { return !!item; })
      .map(function (item) {
        const providerId = String(firstDefined(item.id, item.provider_id, item.providerId, "")).trim();
        const providerName = String(firstDefined(item.name, item.provider_name, item.display_name, providerId)).trim();
        if (!providerId) return null;
        return Object.assign({}, item, { id: providerId, name: providerName || providerId });
      })
      .filter(function (item) { return !!item; });
  }

  function hydrateDispatchFilters() {
    const els = getEls();
    if (!els.filterStatus || !els.filterProvider || !els.filterDriver || !els.filterPriority || !els.filterQuery) return;

    const statuses = Array.from(new Set(state.rides.map((ride) => String(ride.status || "").toLowerCase()).filter(Boolean)))
      .sort()
      .map((status) => ({ value: status }));
    const providers = state.providers.map((provider) => ({ value: provider.id, name: provider.name || provider.id }));
    const drivers = state.drivers.map((driver) => ({ value: driver.id, name: driver.name || driver.id, status: driver.status || "unknown" }));
    const priorities = Array.from(new Set(state.rides.map((ride) => getPriorityTag(ride)).filter(Boolean)))
      .sort()
      .map((priority) => ({ value: priority }));

    renderFilterOptions(els.filterStatus, statuses, state.filters.status, (item) => item.value);
    renderFilterOptions(els.filterProvider, providers, state.filters.provider, (item) => item.name);
    renderFilterOptions(els.filterDriver, drivers, state.filters.driver, (item) => item.name + " (" + item.status + ")");
    renderFilterOptions(els.filterPriority, priorities, state.filters.priority, (item) => item.value);
    els.filterQuery.value = state.filters.query || "";
  }

  function hydrateProviderSelect(providersOverride) {
    const els = getEls();
    const modal = document.getElementById("health-create-ride-modal");
    const selectCandidates = Array.from(document.querySelectorAll("#health-provider-select"));
    const targetSelect = selectCandidates.find(function (node) {
      return !!(modal && modal.contains(node));
    }) || els.providerSelect || selectCandidates[0] || null;
    if (!targetSelect) return;

    const providerList = normalizeProvidersList(providersOverride || state.providers);
    const existingOptionCount = targetSelect.options ? targetSelect.options.length : 0;
    if (providerList.length <= 0 && existingOptionCount > 1) {
      clearCreateRideErrors();
      return;
    }
    const current = targetSelect.value;
    const options = providerList.map((provider) => {
      return '<option value="' + provider.id + '">' + provider.name + "</option>";
    }).join("");
    targetSelect.innerHTML = '<option value="">Select provider</option>' + options;
    if (current) {
      targetSelect.value = current;
    }
    if (providerList.length > 0) {
      clearCreateRideErrors();
    }
  }

  function showView(route) {
    const els = getEls();
    const previousRoute = state.route;
    state.route = route;
    els.views.forEach((view) => {
      view.hidden = view.getAttribute("data-health-view") !== route;
    });
    els.tabs.forEach((tab) => {
      tab.classList.toggle("active", tab.getAttribute("data-health-route") === route);
    });
    persistRuntimeState("show_view");
    if (previousRoute !== route) {
      incrementStabilityCounter("routeTransitions", 1);
    }
  }

  function setModuleVisibility(active, options) {
    const els = getEls();
    const prevActive = !!state.active;
    const prevAuthGateVisible = !!state.authGateVisible;
    state.active = !!active;
    state.authGateVisible = !!(options && options.authGate);
    if (!els.shell || !els.frame || !els.inputWrap || !els.statusBar) return;

    const shellVisible = state.active || state.authGateVisible;
    els.shell.hidden = !shellVisible;
    els.shell.style.display = shellVisible ? "grid" : "none";
    els.shell.dataset.shellMode = state.active ? "operational" : (state.authGateVisible ? "auth-gate" : "hidden");

    els.frame.hidden = shellVisible;
    els.frame.style.display = shellVisible ? "none" : "flex";

    els.inputWrap.hidden = shellVisible;
    els.inputWrap.style.display = shellVisible ? "none" : "block";

    els.statusBar.hidden = shellVisible;
    els.statusBar.style.display = shellVisible ? "none" : "flex";

    if (els.searchResults) {
      els.searchResults.hidden = shellVisible;
      els.searchResults.style.display = shellVisible ? "none" : "block";
    }

    const productToolbar = document.getElementById("product-toolbar");
    if (productToolbar) {
      productToolbar.hidden = shellVisible;
      productToolbar.style.display = shellVisible ? "none" : "flex";
    }

    const assistantState = document.getElementById("assistant-state-text");
    if (assistantState) {
      assistantState.textContent = shellVisible ? "Operations center" : "Ready";
    }

    if (els.shell) {
      els.shell.querySelectorAll('[data-health-action="close"]').forEach(function (button) {
        const debugVisible = isDevelopmentPreviewMode();
        button.hidden = !debugVisible;
        button.setAttribute("aria-hidden", debugVisible ? "false" : "true");
      });
    }

    if (els.workflow) {
      els.workflow.hidden = true;
      els.workflow.style.display = "none";
    }

    const activeTransitionChanged = prevActive !== state.active || prevAuthGateVisible !== state.authGateVisible;

    if (state.active && (!prevActive || activeTransitionChanged)) {
      startAutoRefresh();
      const initialRefresh = triggerRefresh("module-activate", { bypassCooldown: true });
      if (initialRefresh && typeof initialRefresh.catch === "function") {
        initialRefresh.catch((error) => {
        logDiag("Hydration on module activate failed", { message: error.message });
        });
      }
    } else if (!state.active && (prevActive || activeTransitionChanged)) {
      stopAutoRefresh();
    }

    renderRuntimeShell(state.active ? "module_open" : (state.authGateVisible ? "auth_gate" : "module_closed"));
    persistRuntimeState(state.active ? "module_open" : "module_closed");
  }

  function reconnectRealtime(reason, options) {
    const reconnectReason = String(reason || "unknown");
    const opts = options && typeof options === "object" ? options : {};
    const onlyIfStale = opts.onlyIfStale !== false;
    const bypassCooldown = !!opts.bypassCooldown;
    if (!bypassCooldown && shouldThrottleBySource("lastReconnectBySource", reconnectReason, REALTIME_RECONNECT_COOLDOWN_MS)) {
      incrementStabilityCounter("reconnectSuppressed", 1);
      logDiag("Realtime reconnect suppressed", { reason: reconnectReason, cause: "source_cooldown" });
      return;
    }
    if (!canReconnectRealtime(reconnectReason, { onlyIfStale: onlyIfStale, force: !!opts.force })) {
      return;
    }
    incrementStabilityCounter("reconnectAttempts", 1);
    state.lastRealtimeReconnectAtMs = nowMs();
    logDiag("Realtime reconnect", { reason: reconnectReason });
    disconnectRealtimeSocket();
    connectRealtimeSocket();
  }

  async function refreshData() {
    if (state.refreshPromise) {
      state.refreshQueued = true;
      return state.refreshPromise;
    }

    state.refreshQueued = false;
    state.refreshPromise = (async function runRefreshData() {
      const profile = getSessionProfile();
      if (!profile.active) {
        state.hydration.lastRefreshError = "authentication required";
        state.websocketStatus = "auth_required";
        renderRuntimeShell("refresh_blocked");
        return;
      }

      state.lastActionAt = stampNow();
      const activeRoute = VIEW_ROUTES.includes(state.route) ? state.route : PRIMARY_ROUTE;
      const wantsCustomer = activeRoute === "customer";
      const wantsAdmin = activeRoute === "admin";
      const wantsDashboardIntelligence = activeRoute === "dashboard" || activeRoute === "analytics";
      const wantsOnboarding = activeRoute === "onboarding";
      const wantsGrant = activeRoute === "grant";
      const wantsProviderQueue = activeRoute === "providers";
      let aiSnapshot = null;
      let aiSnapshotError = null;
      const [dashboard, rides, drivers, providers, customerRequests, customerQueueMetrics, dispatchQueue, dispatchActiveAssignments, driverPoolMetrics, driverApplications, recurringTemplates, grantSnapshot, operationalStatus, governanceStatus, governanceApprovals, novaContinuityBrief, novaAssistanceRecommendations, novaLiveEvents, novaMemoryFabric, runtimeDiagnostics, adminSummary, adminLiveOperations, adminDispatchAlerts, runtimeState, runtimeReplay, serviceCategories, previewRuntimeStatus] = await Promise.all([
      fetchJson("/api/health-isf/dashboard", { actionName: "refresh_dashboard" }),
      fetchJson("/api/health-isf/rides", { actionName: "refresh_rides" }),
      fetchJson("/api/health-isf/drivers", { actionName: "refresh_drivers" }),
      fetchJson("/api/health-isf/providers", { actionName: "refresh_providers" }),
      wantsCustomer ? fetchJson("/api/health-isf/customer-requests", { actionName: "refresh_customer_requests" }).catch(() => []) : Promise.resolve([]),
      wantsCustomer ? fetchJson("/api/health-isf/customer-requests/metrics", { actionName: "refresh_customer_queue_metrics" }).catch(() => null) : Promise.resolve(null),
      fetchJson("/api/health-isf/dispatch/queue", { actionName: "refresh_dispatch_queue" }).catch(() => []),
      fetchJson("/api/health-isf/dispatch/active-assignments", { actionName: "refresh_dispatch_active_assignments" }).catch(() => []),
      fetchJson("/api/health-isf/drivers/active/metrics", { actionName: "refresh_driver_pool_metrics" }).catch(() => null),
      wantsOnboarding ? fetchJson("/api/health-isf/driver-applications", { actionName: "refresh_driver_applications" }).catch(() => []) : Promise.resolve([]),
      wantsOnboarding ? fetchJson("/api/health-isf/recurring/templates", { actionName: "refresh_recurring_templates" }).catch(() => []) : Promise.resolve([]),
      wantsGrant ? fetchJson("/api/health-isf/grant-proof/snapshot", { actionName: "refresh_grant_snapshot" }).catch(() => null) : Promise.resolve(null),
      wantsDashboardIntelligence ? fetchJson("/api/ai/operations/status", { actionName: "refresh_ai_ops" }).catch(() => null) : Promise.resolve(null),
      wantsDashboardIntelligence ? fetchJson("/api/ai/governance/status", { actionName: "refresh_governance_status" }).catch(() => null) : Promise.resolve(null),
      wantsDashboardIntelligence ? fetchJson("/api/ai/governance/approvals", { actionName: "refresh_governance_approvals" }).catch(() => []) : Promise.resolve([]),
      wantsDashboardIntelligence ? fetchJson("/api/nova/continuity/brief", { actionName: "refresh_nova_continuity" }).catch(() => null) : Promise.resolve(null),
      wantsDashboardIntelligence ? fetchJson("/api/nova/assist/recommendations", { actionName: "refresh_nova_recommendations" }).catch(() => null) : Promise.resolve(null),
      wantsDashboardIntelligence ? fetchJson("/api/nova/events/live?limit=60", { actionName: "refresh_nova_live_events" }).catch(() => null) : Promise.resolve(null),
      wantsDashboardIntelligence ? fetchJson("/api/nova/memory/fabric", { actionName: "refresh_nova_memory" }).catch(() => null) : Promise.resolve(null),
      wantsDashboardIntelligence ? fetchJson("/api/nova/health/runtime/diagnostics", { actionName: "refresh_runtime_diagnostics" }).catch(() => null) : Promise.resolve(null),
      wantsAdmin ? fetchJson("/api/health-isf/admin/command-center/summary", { actionName: "refresh_admin_summary" }).catch(() => null) : Promise.resolve(null),
      wantsAdmin ? fetchJson("/api/health-isf/admin/live-operations", { actionName: "refresh_admin_live_ops" }).catch(() => null) : Promise.resolve(null),
      wantsAdmin ? fetchJson("/api/health-isf/admin/dispatch-alerts", { actionName: "refresh_admin_dispatch_alerts" }).catch(() => null) : Promise.resolve(null),
      wantsDashboardIntelligence ? fetchJson("/api/health-isf/operations/runtime-state?include_timeline=true&limit=120", { actionName: "refresh_runtime_state" }).catch(() => null) : Promise.resolve(null),
      wantsDashboardIntelligence ? fetchJson("/api/health-isf/operations/runtime-replay?after_sequence=0&limit=120", { actionName: "refresh_runtime_replay" }).catch(() => null) : Promise.resolve(null),
      fetchJson("/api/health-isf/operations/service-categories", { actionName: "refresh_service_categories" }).catch(() => null),
      wantsDashboardIntelligence ? fetchJson("/api/health-isf/operations/preview-runtime-status", { actionName: "refresh_preview_runtime_status" }).catch(() => null) : Promise.resolve(null),
    ]);

      let enterpriseDashboard = null;
      let enterpriseDashboardError = null;
      if (wantsDashboardIntelligence) {
        try {
          enterpriseDashboard = await fetchJson("/api/enterprise/dashboard", { actionName: "refresh_enterprise_dashboard" });
        } catch (error) {
          enterpriseDashboardError = error && error.message ? error.message : "enterprise dashboard fetch failed";
          logDiag("Enterprise dashboard degraded", { error: enterpriseDashboardError });
        }
      }

      if (wantsDashboardIntelligence) {
        try {
          aiSnapshot = await fetchJson("/api/health-isf/ai-dispatch/snapshot?publish=false", { actionName: "refresh_ai_snapshot" });
        } catch (error) {
          aiSnapshot = null;
          aiSnapshotError = error && error.message ? error.message : "snapshot fetch failed";
          logDiag("AI snapshot degraded", { error: aiSnapshotError });
        }
      }

      state.dashboard = dashboard;
      state.enterpriseDashboard = enterpriseDashboard;
      state.rides = Array.isArray(rides) ? rides : [];
      state.drivers = Array.isArray(drivers) ? drivers : [];
      const normalizedProviders = normalizeProvidersList(providers);
      state.providers = normalizedProviders.length > 0 ? normalizedProviders : state.providers;
      state.customerRequests = Array.isArray(customerRequests) ? customerRequests : [];
      state.customerQueueMetrics = customerQueueMetrics && typeof customerQueueMetrics === "object" ? customerQueueMetrics : null;
      state.dispatchQueue = Array.isArray(dispatchQueue) ? dispatchQueue : [];
      state.dispatchActiveAssignments = Array.isArray(dispatchActiveAssignments) ? dispatchActiveAssignments : [];
      state.dispatchTimeline = computeDispatchTimeline();
      state.driverPoolMetrics = driverPoolMetrics && typeof driverPoolMetrics === "object" ? driverPoolMetrics : null;
      state.driverApplications = Array.isArray(driverApplications) ? driverApplications : [];
      state.recurringTemplates = Array.isArray(recurringTemplates) ? recurringTemplates : [];
      state.grantSnapshot = grantSnapshot && typeof grantSnapshot === "object" ? grantSnapshot : null;
      state.aiSnapshot = aiSnapshot;
      state.operationalStatus = operationalStatus || null;
      state.operationalExpansion = operationalStatus && operationalStatus.operational_intelligence_expansion
        ? operationalStatus.operational_intelligence_expansion
        : null;
      state.governanceStatus = governanceStatus || null;
      state.governanceApprovals = Array.isArray(governanceApprovals) ? governanceApprovals : [];
      state.novaContinuityBrief = novaContinuityBrief || null;
      state.novaAssistanceRecommendations = novaAssistanceRecommendations && Array.isArray(novaAssistanceRecommendations.recommendations)
        ? novaAssistanceRecommendations.recommendations.slice(0, 30)
        : [];
      state.novaLiveEvents = novaLiveEvents && Array.isArray(novaLiveEvents.events)
        ? novaLiveEvents.events.slice(0, 60)
        : [];
      state.novaMemoryFabric = novaMemoryFabric && novaMemoryFabric.memory_fabric && typeof novaMemoryFabric.memory_fabric === "object"
        ? novaMemoryFabric.memory_fabric
        : null;
      state.runtimeDiagnostics = runtimeDiagnostics && typeof runtimeDiagnostics === "object" ? runtimeDiagnostics : null;
      state.adminSummary = adminSummary && typeof adminSummary === "object" ? adminSummary : null;
      state.adminLiveOperations = adminLiveOperations && typeof adminLiveOperations === "object" ? adminLiveOperations : null;
      state.adminDispatchAlerts = adminDispatchAlerts && typeof adminDispatchAlerts === "object" ? adminDispatchAlerts : null;
      state.runtimeState = runtimeState && typeof runtimeState === "object" ? runtimeState : null;
      state.runtimeReplay = runtimeReplay && typeof runtimeReplay === "object" ? runtimeReplay : null;
      state.serviceCategories = serviceCategories && Array.isArray(serviceCategories.categories) ? serviceCategories.categories : [];
      state.previewRuntimeStatus = previewRuntimeStatus && typeof previewRuntimeStatus === 'object' ? previewRuntimeStatus : null;
      state.previewRuntimeLastCheck = state.previewRuntimeStatus ? stampNow() : null;
      state.adminRoleSessions = state.adminSummary && state.adminSummary.websocket && typeof state.adminSummary.websocket === "object"
        ? state.adminSummary.websocket
        : null;

      const firstProvider = state.providers.length ? state.providers[0] : null;
      if (wantsProviderQueue && firstProvider && firstProvider.id) {
        const providerQueue = await fetchJson(
          "/api/health-isf/providers/" + encodeURIComponent(firstProvider.id) + "/transport-queue?include_completed=false&limit=120",
          { actionName: "refresh_provider_transport_queue" }
        ).catch(function () { return null; });
        state.providerTransportQueue = providerQueue && Array.isArray(providerQueue.items) ? providerQueue.items : [];
      } else {
        state.providerTransportQueue = [];
      }

      const riderPhone = state.customerWorkspace.riderPhone
        || (state.customerRequests[0] && state.customerRequests[0].rider_phone)
        || "";
      state.customerWorkspace.riderPhone = riderPhone;
      if (wantsCustomer && riderPhone) {
        const customerHistory = await fetchJson(
          "/api/health-isf/customers/workspace/history?rider_phone=" + encodeURIComponent(riderPhone) + "&limit=40",
          { actionName: "refresh_customer_workspace_history" }
        ).catch(function () { return null; });
        const customerActiveRide = await fetchJson(
          "/api/health-isf/customers/workspace/active?rider_phone=" + encodeURIComponent(riderPhone),
          { actionName: "refresh_customer_workspace_active" }
        ).catch(function () { return null; });
        const customerTracking = await fetchJson(
          "/api/health-isf/customers/workspace/live-tracking?rider_phone=" + encodeURIComponent(riderPhone) + "&limit=60",
          { actionName: "refresh_customer_workspace_tracking" }
        ).catch(function () { return null; });
        state.customerWorkspace.history = customerHistory && Array.isArray(customerHistory.history) ? customerHistory.history : [];
        state.customerWorkspace.activeRide = customerActiveRide && customerActiveRide.active_ride ? customerActiveRide.active_ride : null;
        state.customerWorkspace.timeline = customerTracking && Array.isArray(customerTracking.timeline) ? customerTracking.timeline : [];
        state.customerWorkspace.etaMinutes = customerTracking && Number.isFinite(Number(customerTracking.eta_minutes)) ? Number(customerTracking.eta_minutes) : null;
      } else {
        state.customerWorkspace.history = [];
        state.customerWorkspace.activeRide = null;
        state.customerWorkspace.timeline = [];
        state.customerWorkspace.etaMinutes = null;
      }

      if (state.selectedDriverId) {
        await refreshDriverLiveWorkspace().catch(function () { return null; });
      } else {
        state.driverLiveWorkspace = null;
      }
      state.operationalMemorySnapshot = getOperationalMemorySnapshot();
      state.operationalMemoryReferences = state.operationalMemorySnapshot ? [
      ...(Array.isArray(state.operationalMemorySnapshot.incident_history_memory) ? state.operationalMemorySnapshot.incident_history_memory : []),
      ...(Array.isArray(state.operationalMemorySnapshot.escalation_pattern_memory) ? state.operationalMemorySnapshot.escalation_pattern_memory : []),
      ...(Array.isArray(state.operationalMemorySnapshot.provider_continuity_history) ? state.operationalMemorySnapshot.provider_continuity_history : []),
      ...(Array.isArray(state.operationalMemorySnapshot.driver_operational_trend_memory) ? state.operationalMemorySnapshot.driver_operational_trend_memory : []),
      ...(Array.isArray(state.operationalMemorySnapshot.operational_congestion_history) ? state.operationalMemorySnapshot.operational_congestion_history : []),
      ...(Array.isArray(state.operationalMemorySnapshot.regional_operational_learning) ? state.operationalMemorySnapshot.regional_operational_learning : []),
      ] : [];
      if (state.novaMemoryFabric) {
        state.operationalMemoryReferences = state.operationalMemoryReferences.concat(buildNovaMemoryReferences(state.novaMemoryFabric));
        const timeline = Array.isArray(state.novaMemoryFabric.execution_timeline) ? state.novaMemoryFabric.execution_timeline : [];
        timeline.slice(0, 16).forEach(function (item) {
          recordOperationalEvent({
            event_type: firstDefined(item.event_type, item.stage, "execution_timeline"),
            timestamp: firstDefined(item.timestamp, item.at, stampNow()),
            severity: firstDefined(item.failure_reason ? "high" : "info"),
            payload: {
              summary: firstDefined(item.summary, item.recommendation, "Execution timeline event"),
              synchronization_impact: "replay-safe",
              impacted_surface: "Operational shell",
              recommendation_only: true,
            },
          }, "nova_memory");
        });
      }
      getNovaAssistanceRecommendations().slice(0, 10).forEach(function (rec) {
        const mapped = mapNovaRecommendation(rec);
        if (!mapped) return;
        recordOperationalEvent({
          event_type: firstDefined(mapped.action_type, mapped.recommendation_type, "nova_recommendation"),
          timestamp: firstDefined(mapped.timestamp, stampNow()),
          severity: firstDefined(mapped.operational_risk, mapped.priority, "info"),
          payload: {
            summary: firstDefined(mapped.summary, mapped.reasoning, "Nova recommendation"),
            impacted_surface: mapped.impacted_surface,
            recommendation_only: true,
            synchronization_impact: mapped.synchronization_impact,
          },
        }, "nova_recommendation");
      });
      getNovaLiveEvents().slice(0, 20).forEach(function (evt) {
      recordOperationalEvent({
        event_type: firstDefined(evt && evt.event_type, "nova_live_event"),
        timestamp: firstDefined(evt && evt.detected_at, stampNow()),
        severity: firstDefined(evt && evt.severity, "info"),
        payload: {
          summary: firstDefined(evt && evt.summary, "Live operational event"),
          impacted_surface: firstDefined(evt && evt.impacted_surface, "Operational shell"),
          recommendation_only: true,
          synchronization_impact: "replay-safe",
        },
      }, "nova_live");
    });
    state.websocketDiagnostics = Object.assign({}, state.websocketDiagnostics || {}, getWebsocketMetrics());
    hydrateDriverIncomingOffer();
    seedOperationalEventFeed(operationalStatus || {});
    state.hydration.lastRefreshAt = new Date().toISOString();
    state.hydration.lastRefreshError = null;
    state.hydration.enterpriseDashboardError = enterpriseDashboardError;
    state.hydration.aiSnapshotDegraded = !aiSnapshot;
    state.hydration.aiSnapshotError = aiSnapshotError;
    state.lastCompletedAction = "refresh_data";
    state.lastFailedAction = null;
    logDiag("Dashboard state hydrated", {
      route: state.route,
      active: state.active,
      dashboardReady: !!state.dashboard,
      rides: state.rides.length,
      drivers: state.drivers.length,
      providers: state.providers.length,
      hasAiSnapshot: !!state.aiSnapshot,
      aiSnapshotError,
      websocketStatus: state.websocketStatus,
      memoryManagerLoaded: !!window.AmiCorMemoryManager,
    });
    if (!state.selectedRideId && state.rides.length > 0) {
      state.selectedRideId = state.rides[0].id;
    }
    // Keep provider options current even if a later renderer throws.
    hydrateProviderSelect();
    persistRuntimeState("refresh_data");
    renderAll();
    await refreshRideTimeline().catch(() => {});
    })();

    try {
      return await state.refreshPromise;
    } finally {
      state.refreshPromise = null;
      if (state.refreshQueued && state.active) {
        incrementStabilityCounter("refreshQueuedBursts", 1);
        state.refreshQueued = false;
        window.setTimeout(function () {
          refreshData().catch(function () {});
        }, 0);
      }
    }
  }

  async function openModal() {
    const els = getEls();
    if (!els.modal) return;
    clearCreateRideErrors();
    els.modal.hidden = false;
    els.modal.style.display = "grid";
    attachAutoDistanceListeners();
    // Always reset stale hydration promise so a fresh load is attempted each open.
    state.providerHydrationPromise = null;
    // Immediately populate from cached state if available.
    if (Array.isArray(state.providers) && state.providers.length > 0) {
      hydrateProviderSelect();
      return;
    }
    // Direct fetch – no AbortController, no deduplication wrapper that can fail closed.
    try {
      const scopedPath = withOrganizationScope("/api/health-isf/providers");
      let response;
      if (window.AmiCorSession && typeof window.AmiCorSession.authFetch === "function") {
        response = await window.AmiCorSession.authFetch(scopedPath, { method: "GET" });
      } else {
        response = await fetch(scopedPath, { method: "GET" });
      }
      if (!response || !response.ok) {
        const statusText = response ? " (HTTP " + response.status + ")" : " (no response)";
        throw new Error("Providers failed to load — cannot create ride." + statusText);
      }
      const data = await response.json().catch(function () { return []; });
      const providers = normalizeProvidersList(data);
      if (providers.length > 0) {
        state.providers = providers;
        hydrateProviderSelect();
      } else {
        renderCreateRideErrors({}, "Providers failed to load — cannot create ride.");
      }
    } catch (error) {
      renderCreateRideErrors({}, "Providers failed to load — cannot create ride.");
    }
  }

  async function fetchProvidersForCreateRideFallback() {
    const scopedPath = withOrganizationScope("/api/health-isf/providers");
    let response;
    if (window.AmiCorSession && typeof window.AmiCorSession.authFetch === "function") {
      response = await window.AmiCorSession.authFetch(scopedPath, { method: "GET" });
    } else {
      response = await fetch(scopedPath, { method: "GET" });
    }
    const data = await safeJson(response);
    if (!response || !response.ok) {
      const message = data && data.detail ? data.detail : "Unable to load providers";
      throw new Error(normalizeApiError(message));
    }
    return normalizeProvidersList(data);
  }

  async function ensureProviderOptionsForCreateRide() {
    const els = getEls();
    if (!els.providerSelect) return;

    if (Array.isArray(state.providers) && state.providers.length > 0) {
      hydrateProviderSelect();
      return;
    }

    if (state.refreshPromise) {
      try {
        await state.refreshPromise;
      } catch (_error) {}
      if (Array.isArray(state.providers) && state.providers.length > 0) {
        hydrateProviderSelect();
        return;
      }
    }

    if (state.providerHydrationPromise) {
      await state.providerHydrationPromise;
      return;
    }

    const currentOptionCount = els.providerSelect.options ? els.providerSelect.options.length : 0;
    if (Array.isArray(state.providers) && state.providers.length > 0 && currentOptionCount > 1) {
      return;
    }

    state.providerHydrationPromise = (async function hydrateProvidersForModal() {
      let providers = [];
      let lastError = null;
      for (let attempt = 0; attempt < 3; attempt += 1) {
        try {
          const response = await fetchJson("/api/health-isf/providers", { actionName: "refresh_providers_modal" });
          providers = normalizeProvidersList(response);
        } catch (error) {
          lastError = error;
          try {
            providers = await fetchProvidersForCreateRideFallback();
          } catch (fallbackError) {
            lastError = fallbackError;
            providers = [];
          }
        }

        if (providers.length > 0) {
          break;
        }

        await new Promise(function (resolve) {
          window.setTimeout(resolve, 250);
        });
      }

      state.providers = providers.length > 0 ? providers : state.providers;
      hydrateProviderSelect(providers.length > 0 ? providers : state.providers);
      if (!providers.length && (!Array.isArray(state.providers) || state.providers.length <= 0) && lastError) {
        throw lastError;
      }
    })();

    try {
      await state.providerHydrationPromise;
    } catch (error) {
      logDiag("Provider modal hydration degraded", {
        error: error && error.message ? error.message : String(error || "unknown"),
      });
      throw error;
    } finally {
      state.providerHydrationPromise = null;
    }
  }

  function closeModal() {
    const els = getEls();
    if (!els.modal) return;
    els.modal.hidden = true;
    els.modal.style.display = "none";
  }

  function openRideDetailsModal(rideId) {
    const els = getEls();
    if (!els.rideDetailsModal || !els.rideDetailsContent) return;
    state.selectedRideId = rideId;
    els.rideDetailsModal.hidden = false;
    els.rideDetailsModal.style.display = "grid";
    els.rideDetailsContent.innerHTML = '<p class="health-summary">Loading operational timeline...</p>';
    refreshRideTimeline().then(() => {
      const ride = state.rides.find((item) => item.id === rideId);
      if (!ride) {
        els.rideDetailsContent.innerHTML = '<p class="health-summary">Ride details unavailable.</p>';
        return;
      }
      const history = Array.isArray(state.selectedRideHistory) ? state.selectedRideHistory : [];
      const dispatchHistory = Array.isArray(state.selectedRideDispatchHistory) ? state.selectedRideDispatchHistory : [];
      const statusItems = history.map((event) => {
        return '<li><span class="health-pill ' + pillClass(event.to_status) + '">' + escapeHtml(event.to_status || "unknown") + '</span><strong>' + escapeHtml(event.note || event.from_status || "status updated") + '</strong><small>' + escapeHtml(formatDateShort(event.created_at)) + '</small></li>';
      }).join("");
      const dispatchItems = dispatchHistory.map((item) => {
        return '<li><span class="health-pill warn">' + escapeHtml(item.action || "action") + '</span><strong>' + escapeHtml(item.note || "No details") + '</strong><small>' + escapeHtml(formatDateShort(item.created_at)) + '</small></li>';
      }).join("");
      els.rideDetailsContent.innerHTML = [
        '<div class="health-panel">',
        '<p><strong>Passenger:</strong> ' + escapeHtml(ride.passenger_name || "-") + '</p>',
        '<p><strong>Status:</strong> <span class="health-pill ' + pillClass(ride.status) + '">' + escapeHtml(ride.status || "unknown") + '</span></p>',
        '<p><strong>Provider:</strong> ' + escapeHtml(lookupProviderName(ride.provider_id)) + '</p>',
        '<p><strong>Driver:</strong> ' + escapeHtml(lookupDriverName(ride.driver_id)) + '</p>',
        '<h4 style="margin-top:10px;font-size:0.82rem;color:var(--text-dim)">Status History</h4>',
        '<ul class="health-timeline-feed">' + (statusItems || '<li><strong>No status history yet.</strong></li>') + '</ul>',
        '<h4 style="margin-top:10px;font-size:0.82rem;color:var(--text-dim)">Dispatch Log</h4>',
        '<ul class="health-timeline-feed">' + (dispatchItems || '<li><strong>No dispatch events yet.</strong></li>') + '</ul>',
        '</div>',
      ].join("");
    }).catch((error) => {
      els.rideDetailsContent.innerHTML = '<p class="health-summary">Unable to load details: ' + escapeHtml(error.message || "Unknown error") + '</p>';
    });
  }

  function closeRideDetailsModal() {
    const els = getEls();
    if (!els.rideDetailsModal) return;
    els.rideDetailsModal.hidden = true;
    els.rideDetailsModal.style.display = "none";
  }

  // ── Auto-Distance Calculation ──────────────────────────────────────────────────
  // ROUTING INTEGRATION POINT:
  // When distance auto-calc is enabled, this function should:
  // 1. Extract lat/lon from pickup/dropoff addresses via geocoding API
  // 2. Call routing provider (Google Maps / Mapbox) for driving distance
  // 3. Update estimated_distance_miles and estimated_duration_minutes
  // Current implementation: Conservative heuristic based on address keywords
  function estimateDistanceFromAddresses(pickup, dropoff) {
    // Heuristic distance estimation:
    // - Count of address components (longer addresses = likely farther)
    // - Common borough/neighborhood patterns in NYC area
    pickup = String(pickup || "").toLowerCase().trim();
    dropoff = String(dropoff || "").toLowerCase().trim();
    if (!pickup || !dropoff || pickup === dropoff) return 1.0;

    const pickupScore = pickup.split(/[\s,]+/).length;
    const dropoffScore = dropoff.split(/[\s,]+/).length;
    const addressComplexity = pickupScore + dropoffScore;

    // Simple rule: use complexity as rough distance estimate (1-20 miles)
    let estimate = Math.max(1.0, Math.min(20.0, addressComplexity * 0.8));

    // NYC area borough distance adjustments
    const neighborhoods = {
      manhattan: 0,
      brooklyn: 1,
      queens: 2,
      bronx: 3,
      "staten island": 4,
    };
    for (const [borough, idx] of Object.entries(neighborhoods)) {
      const pickupHasBorough = pickup.includes(borough);
      const dropoffHasBorough = dropoff.includes(borough);
      if (pickupHasBorough && !dropoffHasBorough) {
        estimate = Math.max(estimate, 5.0);
      }
    }

    // Cross-borough detection (rough)
    const boroCount = (String(pickup + " " + dropoff).match(/manhattan|brooklyn|queens|bronx|staten/gi) || []).length;
    if (boroCount >= 2) {
      estimate = Math.max(estimate, 6.0);
    }

    return Math.round(estimate * 10) / 10; // Round to nearest 0.1
  }

  function updateAutoDistance() {
    const els = getEls();
    if (!els.form) return;
    const distanceField = els.form.querySelector('[name="estimated_distance_miles"]');
    if (!distanceField || distanceField.getAttribute("data-auto-calc") !== "true") return;

    // If user manually edited the field, don't auto-update
    if (distanceField.classList.contains("health-user-edited")) return;

    const pickup = sanitizeInput(els.form.querySelector('[name="pickup_address"]')?.value || "");
    const dropoff = sanitizeInput(els.form.querySelector('[name="dropoff_address"]')?.value || "");

    if (pickup && dropoff && pickup !== dropoff) {
      const estimated = estimateDistanceFromAddresses(pickup, dropoff);
      distanceField.value = estimated;

      // Auto-update duration based on distance
      const durationField = els.form.querySelector('[name="estimated_duration_minutes"]');
      if (durationField && !durationField.value) {
        const durationMinutes = Math.max(1, Math.round((estimated / 25.0) * 60.0));
        durationField.value = durationMinutes;
      }
    }
  }

  function attachAutoDistanceListeners() {
    const els = getEls();
    if (!els.form) return;
    const pickupField = els.form.querySelector('[name="pickup_address"]');
    const dropoffField = els.form.querySelector('[name="dropoff_address"]');
    const distanceField = els.form.querySelector('[name="estimated_distance_miles"]');

    if (pickupField) {
      pickupField.addEventListener("change", updateAutoDistance);
      pickupField.addEventListener("blur", updateAutoDistance);
    }
    if (dropoffField) {
      dropoffField.addEventListener("change", updateAutoDistance);
      dropoffField.addEventListener("blur", updateAutoDistance);
    }

    // Allow user to opt-out of auto-calculation by manually editing distance
    if (distanceField) {
      distanceField.addEventListener("input", function () {
        distanceField.classList.add("health-user-edited");
      });
    }

    // Show/hide recurrence days based on frequency selection
    const frequencySelect = els.form.querySelector('[name="recurring_frequency"]');
    const daysGroup = els.form.querySelector('#health-recurring-days-group');
    if (frequencySelect && daysGroup) {
      function updateRecurrenceVisibility() {
        const freq = frequencySelect.value;
        if (freq === 'daily' || freq === 'weekly' || freq === 'monthly') {
          daysGroup.hidden = false;
        } else {
          daysGroup.hidden = true;
        }
      }
      frequencySelect.addEventListener("change", updateRecurrenceVisibility);
    }
  }

  async function handleCreateRideSubmit(event) {
    event.preventDefault();
    if (state.createRideSubmitting) return;
    const form = event.target;
    const formData = new FormData(form);
    const errors = {};

    // Build recurring_trip_pattern from user-friendly form controls
    let recurringPattern = null;
    const recurringFrequency = sanitizeInput(formData.get("recurring_frequency"));
    if (recurringFrequency && recurringFrequency !== "custom") {
      const selectedDays = Array.from(els.form.querySelectorAll('input[name="recurring_days"]:checked')).map((el) => el.value);
      recurringPattern = {
        frequency: recurringFrequency,
        days: selectedDays.length > 0 ? selectedDays : undefined,
      };
    }

    // ai_dispatch_context is hidden/auto-populated by backend, not exposed to user
    const aiDispatchContext = null;

    const appointmentRaw = sanitizeInput(formData.get("appointment_time"));
    const appointmentIso = appointmentRaw ? new Date(appointmentRaw).toISOString() : null;

    const payload = {
      passenger_name: sanitizeInput(formData.get("passenger_name")),
      passenger_phone: sanitizeInput(formData.get("passenger_phone")),
      pickup_address: sanitizeInput(formData.get("pickup_address")),
      dropoff_address: sanitizeInput(formData.get("dropoff_address")),
      service_type: sanitizeInput(formData.get("service_type")),
      provider_id: sanitizeInput(formData.get("provider_id")),
      estimated_distance_miles: Number(formData.get("estimated_distance_miles") || 0),
      estimated_duration_minutes: formData.get("estimated_duration_minutes") ? Number(formData.get("estimated_duration_minutes")) : null,
      priority_tag: sanitizeInput(formData.get("priority_tag")) || "normal",
      is_emergency: Boolean(formData.get("is_emergency")),
      appointment_time: appointmentIso,
      recurring_trip_pattern: recurringPattern,
      ai_dispatch_context: aiDispatchContext,
      notes: sanitizeInput(formData.get("notes")) || null,
    };

    const validationErrors = Object.assign(errors, validateCreateRidePayload(payload));
    if (Object.keys(validationErrors).length > 0) {
      renderCreateRideErrors(validationErrors, "Please fix the highlighted fields.");
      showToastSafe("Ride intake validation failed.", "error");
      return;
    }

    const idempotencyKey = ["ride", Date.now(), Math.random().toString(36).slice(2, 10)].join(":");
    setCreateRideSubmitting(true);
    clearCreateRideErrors();
    try {
      state.lastActionAt = stampNow();
      await fetchJson("/api/health-isf/rides", {
        method: "POST",
        actionName: "create_ride",
        headers: {
          "Content-Type": "application/json",
          "X-Idempotency-Key": idempotencyKey,
        },
        body: JSON.stringify(payload),
      });

      form.reset();
      closeModal();
      showToastSafe("Ride created and dispatched to operations.", "success");
      state.lastCompletedAction = "create_ride";
      state.lastFailedAction = null;
      await refreshData();
      navigate("rides", true);
    } catch (error) {
      state.lastFailedAction = "create_ride";
      state.lastApiError = String(error && error.message ? error.message : error);
      renderCreateRideErrors({}, error.message || "Unable to create ride");
      showToastSafe("Ride creation failed: " + error.message, "error");
      throw error;
    } finally {
      setCreateRideSubmitting(false);
    }
  }

  function stopAutoRefresh() {
    if (state.refreshTimer) {
      clearInterval(state.refreshTimer);
      state.refreshTimer = null;
    }
    if (state.realtimeRefreshTimer) {
      clearTimeout(state.realtimeRefreshTimer);
      state.realtimeRefreshTimer = null;
    }
    if (state.reconnectTimer) {
      clearTimeout(state.reconnectTimer);
      state.reconnectTimer = null;
    }
    disconnectRealtimeSocket();
  }

  function startAutoRefresh() {
    stopAutoRefresh();
    connectRealtimeSocket();
    state.refreshTimer = setInterval(() => {
      if (!state.active) return;
      monitorRealtimeHealth("refresh-interval");
      refreshData().catch(() => {});
    }, 20000);
  }

  function readDriverForRide(rideId) {
    const els = getEls();
    const queues = [els.queuePending, els.queueActive, els.queueCompleted, els.queueProblem].filter(Boolean);
    for (let i = 0; i < queues.length; i += 1) {
      const select = queues[i].querySelector('[data-ride-driver-select="' + rideId + '"]');
      if (select) return String(select.value || "");
    }
    return "";
  }

  function bindFilterEvents() {
    const els = getEls();
    const handlers = [
      [els.filterStatus, "status"],
      [els.filterProvider, "provider"],
      [els.filterDriver, "driver"],
      [els.filterPriority, "priority"],
    ];
    handlers.forEach(([node, key]) => {
      if (!node) return;
      node.addEventListener("change", () => {
        state.filters[key] = String(node.value || "all");
        persistRuntimeState("filter_change");
        renderRides();
      });
    });
    if (els.filterQuery) {
      els.filterQuery.addEventListener("input", () => {
        state.filters.query = String(els.filterQuery.value || "").trim();
        persistRuntimeState("filter_query");
        renderRides();
      });
    }
  }

  function recognitionCtor() {
    return window.SpeechRecognition || window.webkitSpeechRecognition || null;
  }

  function updateTranscriptUi(text, targetId) {
    const els = getEls();
    const node = targetId === 'intake' ? els.intakeTranscript : els.aiTranscript;
    if (node) node.textContent = text;
  }

  function stopVoiceCapture(submitToAssistant) {
    state.voice.submitOnEnd = !!submitToAssistant;
    if (state.voice.recognition) {
      try {
        state.voice.recognition.stop();
      } catch (_err) {}
    }
  }

  async function submitVoiceCommand(transcript) {
    if (!transcript) return;
    const result = await fetchJson('/api/health-isf/ai-dispatch/voice/command', {
      method: 'POST',
      actionName: 'voice_command',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        organization_id: getOrganizationId() || null,
        transcript: transcript,
        ride_id: state.selectedRideId || null,
      }),
    });
    state.voice.transcript = transcript;
    updateTranscriptUi((result.action_label || 'Voice command parsed') + ': ' + (result.recommendation_summary || transcript), 'dispatch');
    if (result.intent === 'prepare_intake') {
      openModal().catch(() => {});
      applyExtractedEntitiesToIntake(result.extracted_entities || {});
      applyTranscriptToIntake(transcript);
    }
    await refreshData();
  }

  function applyExtractedEntitiesToIntake(entities) {
    const els = getEls();
    if (!els.form || !entities || typeof entities !== 'object') return;

    const setIfBlank = function (fieldName, value) {
      const field = els.form.elements[fieldName];
      if (!field) return;
      const nextValue = String(value || '').trim();
      if (!nextValue) return;
      if (!String(field.value || '').trim()) {
        field.value = nextValue;
      }
    };

    setIfBlank('passenger_name', entities.passenger_name);
    setIfBlank('passenger_phone', entities.passenger_phone);
    setIfBlank('pickup_address', entities.pickup_address);
    setIfBlank('dropoff_address', entities.dropoff_address);
    setIfBlank('service_type', entities.service_type);
    setIfBlank('priority_tag', entities.priority_tag);

    if (els.form.elements.is_emergency && String(entities.is_emergency || '').toLowerCase() === 'true') {
      els.form.elements.is_emergency.checked = true;
    }
  }

  function applyTranscriptToIntake(transcript) {
    const els = getEls();
    if (!els.form) return;
    const text = String(transcript || '');
    const fromMatch = text.match(/\bfrom\s+(.+?)\s+to\s+(.+?)(?:\bfor\b|\bpassenger\b|\bphone\b|\bservice\b|\bpriority\b|$)/i);
    const passengerMatch = text.match(/\bpassenger\s+([a-z][a-z\s.'-]{1,80}?)(?:\s+\b(?:phone|from|to|pickup|dropoff|service|priority|emergency|urgent)\b|$)/i);
    const phoneMatch = text.match(/(\+?[0-9][0-9()\-\s]{6,20})/);
    const serviceMatch = text.match(/dialysis|discharge|oncology|medical transport|specialist|appointment/i);
    if (passengerMatch && els.form.elements.passenger_name && !els.form.elements.passenger_name.value) {
      els.form.elements.passenger_name.value = passengerMatch[1].trim();
    }
    if (phoneMatch && els.form.elements.passenger_phone && !els.form.elements.passenger_phone.value) {
      els.form.elements.passenger_phone.value = phoneMatch[1].trim();
    }
    if (fromMatch) {
      if (els.form.elements.pickup_address && !els.form.elements.pickup_address.value) {
        els.form.elements.pickup_address.value = fromMatch[1].trim();
      }
      if (els.form.elements.dropoff_address && !els.form.elements.dropoff_address.value) {
        els.form.elements.dropoff_address.value = fromMatch[2].trim();
      }
    }
    if (serviceMatch && els.form.elements.service_type && !els.form.elements.service_type.value) {
      els.form.elements.service_type.value = serviceMatch[0].trim();
    }
    if (/emergency|urgent|stat/i.test(text)) {
      if (els.form.elements.priority_tag) els.form.elements.priority_tag.value = /emergency/i.test(text) ? 'emergency' : 'urgent';
      if (els.form.elements.is_emergency) els.form.elements.is_emergency.checked = true;
    }
    if (els.form.elements.notes) {
      const current = String(els.form.elements.notes.value || '').trim();
      els.form.elements.notes.value = current ? current + '\n' + text : text;
    }
    updateTranscriptUi(text, 'intake');
  }

  async function runIntakeAssist() {
    const els = getEls();
    if (!els.form) return;
    const formData = new FormData(els.form);
    const payload = {
      organization_id: getOrganizationId() || null,
      passenger_name: sanitizeInput(formData.get('passenger_name')) || 'Unknown Passenger',
      passenger_phone: sanitizeInput(formData.get('passenger_phone')) || null,
      pickup_address: sanitizeInput(formData.get('pickup_address')) || 'Unknown pickup',
      dropoff_address: sanitizeInput(formData.get('dropoff_address')) || 'Unknown dropoff',
      service_type: sanitizeInput(formData.get('service_type')) || 'medical_transport',
      provider_id: sanitizeInput(formData.get('provider_id')) || null,
      estimated_distance_miles: Number(formData.get('estimated_distance_miles') || 0),
      estimated_duration_minutes: formData.get('estimated_duration_minutes') ? Number(formData.get('estimated_duration_minutes')) : null,
      priority_tag: sanitizeInput(formData.get('priority_tag')) || 'normal',
      is_emergency: Boolean(formData.get('is_emergency')),
      notes: sanitizeInput(formData.get('notes')) || null,
    };
    const result = await fetchJson('/api/health-isf/ai-dispatch/intake/assist', {
      method: 'POST',
      actionName: 'intake_assist',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(payload),
    });
    if (els.intakeAssistOutput) {
      els.intakeAssistOutput.innerHTML = renderNotificationList([
        {
          title: 'Urgency ' + String(result.urgency || 'normal').toUpperCase(),
          message: 'Priority ' + String(result.priority_score || 0) + ' · Duration ' + String(result.estimated_duration_minutes || 0) + ' min · Providers ' + (result.suggested_provider_ids || []).slice(0, 3).join(', '),
          created_at: result.generated_at,
          severity: result.urgency === 'emergency' ? 'high' : result.urgency === 'high' ? 'medium' : 'info',
        },
      ].concat((result.dispatcher_notes || []).map(function (note) {
        return { title: 'Dispatcher note', message: note, created_at: result.generated_at, severity: 'info' };
      })), 'No AI intake guidance yet.');
    }
    if (Array.isArray(result.suggested_provider_ids) && result.suggested_provider_ids.length && els.providerSelect && !els.providerSelect.value) {
      els.providerSelect.value = result.suggested_provider_ids[0];
    }
  }

  function startVoiceCapture(mode) {
    const SR = recognitionCtor();
    if (!SR) {
      showToastSafe('Speech recognition requires Chrome or Edge.', 'error');
      return;
    }
    if (state.voice.listening) {
      stopVoiceCapture(mode === 'dispatch');
      return;
    }
    const recognition = new SR();
    state.voice.mode = mode;
    state.voice.transcript = '';
    state.voice.interim = '';
    state.voice.submitOnEnd = mode === 'dispatch';
    recognition.continuous = true;
    recognition.interimResults = true;
    recognition.lang = 'en-US';
    recognition.onstart = function () {
      state.voice.listening = true;
      updateTranscriptUi(mode === 'intake' ? 'Listening for ride intake...' : 'Listening for dispatcher command...', mode === 'intake' ? 'intake' : 'dispatch');
      renderAIOperations();
    };
    recognition.onresult = function (event) {
      var finalText = '';
      var interimText = '';
      for (var i = event.resultIndex; i < event.results.length; i += 1) {
        var transcript = event.results[i][0] && event.results[i][0].transcript ? event.results[i][0].transcript : '';
        if (event.results[i].isFinal) finalText += transcript + ' ';
        else interimText += transcript + ' ';
      }
      state.voice.transcript = (state.voice.transcript + ' ' + finalText).trim();
      state.voice.interim = interimText.trim();
      updateTranscriptUi((state.voice.transcript + ' ' + state.voice.interim).trim(), mode === 'intake' ? 'intake' : 'dispatch');
    };
    recognition.onerror = function (event) {
      state.voice.listening = false;
      state.voice.interim = '';
      updateTranscriptUi('Voice recognition error: ' + String(event && event.error || 'unknown'), mode === 'intake' ? 'intake' : 'dispatch');
      renderAIOperations();
    };
    recognition.onend = function () {
      var transcript = String(state.voice.transcript || '').trim();
      state.voice.listening = false;
      state.voice.interim = '';
      state.voice.recognition = null;
      renderAIOperations();
      if (!transcript) return;
      if (mode === 'intake') {
        applyTranscriptToIntake(transcript);
        runIntakeAssist().catch(function (error) {
          showToastSafe('AI intake assist failed: ' + error.message, 'error');
        });
        return;
      }
      if (state.voice.submitOnEnd) {
        submitVoiceCommand(transcript).catch(function (error) {
          showToastSafe('Voice command failed: ' + error.message, 'error');
        });
      }
    };
    state.voice.recognition = recognition;
    recognition.start();
  }

  function handleBoardClick(event) {
    const target = event.target;
    if (!target) return;

    const assignButton = target.closest("[data-ride-assign]");
    if (assignButton) {
      if (!canMutateRides()) {
        showToastSafe("Your role cannot assign drivers.", "error");
        return;
      }
      const rideId = assignButton.getAttribute("data-ride-assign");
      if (!rideId) return;
      const driverId = readDriverForRide(rideId);
      if (!driverId) {
        showToastSafe("Select a driver before assigning.", "error");
        return;
      }
      assignDriver(rideId, driverId).catch((error) => {
        showToastSafe("Driver assignment failed: " + error.message, "error");
      });
      return;
    }

    const actionButton = target.closest("[data-card-action]");
    if (!actionButton) return;

    const action = String(actionButton.getAttribute("data-card-action") || "");
    const rideId = String(actionButton.getAttribute("data-ride-id") || "");
    const driverId = String(actionButton.getAttribute("data-driver-id") || "");
    if (!rideId) return;

    if (action === "details") {
      openRideDetailsModal(rideId);
      return;
    }

    if (!canMutateRides()) {
      showToastSafe("Your role cannot modify ride operations.", "error");
      return;
    }

    if (action === "assign") {
      const selected = readDriverForRide(rideId);
      if (!selected) {
        showToastSafe("Select a driver from the ride card assignment dropdown.", "error");
        return;
      }
      assignDriver(rideId, selected).catch((error) => {
        showToastSafe("Driver assignment failed: " + error.message, "error");
      });
      return;
    }
    if (action === "cancel") {
      updateRideStatus(rideId, "cancelled").catch((error) => showToastSafe("Status update failed: " + error.message, "error"));
      return;
    }
    if (action === "arrived") {
      if (!driverId) {
        showToastSafe("Driver assignment required before marking arrived.", "error");
        return;
      }
      runDriverWorkflow(rideId, driverId, "arrived").catch((error) => showToastSafe("Driver action failed: " + error.message, "error"));
      return;
    }
    if (action === "onboard") {
      if (!driverId) {
        showToastSafe("Driver assignment required before marking onboard.", "error");
        return;
      }
      runDriverWorkflow(rideId, driverId, "onboard").catch((error) => showToastSafe("Driver action failed: " + error.message, "error"));
      return;
    }
    if (action === "complete") {
      if (!driverId) {
        showToastSafe("Driver assignment required before completing trip.", "error");
        return;
      }
      runDriverWorkflow(rideId, driverId, "complete").catch((error) => showToastSafe("Driver action failed: " + error.message, "error"));
      return;
    }
    if (action === "escalate") {
      escalateRideIssue(rideId).then(() => {
        showToastSafe("Escalation submitted to operations.", "success");
      }).catch((error) => showToastSafe("Escalation failed: " + error.message, "error"));
      return;
    }
    if (action === "retry-workflow") {
      retryFailedWorkflow().then(() => {
        showToastSafe("Workflow replay submitted.", "success");
      }).catch((error) => showToastSafe("Replay failed: " + error.message, "error"));
      return;
    }
  }

  function navigate(route, skipHash, options) {
    const opts = options && typeof options === "object" ? options : {};
    const source = String(opts.source || "manual");
    const force = !!opts.force;
    const profile = getSessionProfile();
    const requestedRoute = VIEW_ROUTES.includes(route) ? route : PRIMARY_ROUTE;
    const target = clampRouteForRole(requestedRoute, getEffectiveShellRole(profile.role));
    const now = nowMs();

    if (force) {
      incrementStabilityCounter("forcedNavigationCalls", 1);
      state.navSync.lastForcedNavigateAtMs = now;
    }

    const moduleVisible = !!(state.active || state.authGateVisible);
    const sameRoute = state.route === target;
    const sinceLastNavigate = now - Number(state.navSync.lastNavigateAtMs || 0);
    const sameRouteRepeat = sameRoute && state.navSync.lastNavigateRoute === target && sinceLastNavigate >= 0 && sinceLastNavigate < NAVIGATION_COOLDOWN_MS;
    if (!force && profile.active && moduleVisible && sameRouteRepeat) {
      incrementStabilityCounter("suppressedNavigations", 1);
      logDiag("Navigation suppressed", { source: source, route: target, sinceLastNavigate });
      return;
    }

    if (!profile.active) {
      state.pendingRoute = requestedRoute;
      setModuleVisibility(false, { authGate: true });
      renderRuntimeShell("route_guarded");
      return;
    }

    state.routeMutationInProgress = true;
    state.navSync.lastNavigateAtMs = now;
    state.navSync.lastNavigateRoute = target;
    state.navSync.lastNavigateSource = source;
    setModuleVisibility(true);
    showView(target);
    if (!skipHash) {
      state.navSync.suppressHashRoute = target;
      state.navSync.suppressHashRouteUntilMs = now + HASH_ROUTE_SUPPRESSION_MS;
      setHash(target);
    }
    const refreshRun = triggerRefresh("navigate:" + source, { bypassCooldown: !!opts.bypassRefreshCooldown });
    if (refreshRun && typeof refreshRun.catch === "function") {
      refreshRun.catch((error) => {
      const els = getEls();
      if (els.dispatchSummary) {
        els.dispatchSummary.textContent = "Health ISF API error: " + error.message;
      }
      }).finally(function () {
        state.routeMutationInProgress = false;
      });
      return;
    }
    state.routeMutationInProgress = false;
  }

  function closeModule() {
    setModuleVisibility(false);
    state.pendingRoute = null;
    closeModal();
    if (window.location.hash.startsWith(HEALTH_HASH_PREFIX)) {
      history.replaceState(null, "", window.location.pathname + window.location.search);
    }
    persistRuntimeState("close_module");
  }

  function onHashRoute() {
    const route = routeFromHash(window.location.hash);
    const now = nowMs();
    if (route && state.navSync.suppressHashRoute === route && now <= Number(state.navSync.suppressHashRouteUntilMs || 0)) {
      incrementStabilityCounter("suppressedNavigations", 1);
      logDiag("Hash route suppressed", { route: route, source: "hashchange", reason: "self_sync" });
      return;
    }
    if (!route) {
      const profile = getSessionProfile();
      if (!profile.active) {
        state.pendingRoute = PRIMARY_ROUTE;
        setModuleVisibility(false, { authGate: true });
        renderRuntimeShell("default_auth_gate");
        return;
      }
      navigate(PRIMARY_ROUTE, true, { source: "hash-default" });
      return;
    }

    const profile = getSessionProfile();
    if (!profile.active) {
      state.pendingRoute = route;
      setModuleVisibility(false, { authGate: true });
      renderRuntimeShell("route_guarded");
      return;
    }

    navigate(route, true, { source: "hashchange" });
  }

  function bindEvents() {
    const els = getEls();

    els.tabs.forEach((tab) => {
      tab.addEventListener("click", (event) => {
        if (shouldSuppressSyntheticEvent(event, "tab_navigation")) return;
        navigate(tab.getAttribute("data-health-route") || "dashboard", false, { source: "tab-click" });
      });
    });

    els.navOpeners.forEach((button) => {
      button.addEventListener("click", (event) => {
        if (shouldSuppressSyntheticEvent(event, "nav_opener")) return;
        navigate(button.getAttribute("data-health-nav-open") || "dashboard", false, { source: "nav-open" });
      });
    });

    els.actions.forEach((button) => {
      button.addEventListener("click", () => {
        const action = button.getAttribute("data-health-action");
        if (action === "create-ride") openModal().catch(() => {});
        if (action === "refresh") refreshData().catch(() => {});
        if (action === "close") closeModule();
        if (action === "shell-login") openAuthFlow("login");
        if (action === "shell-signup") openAuthFlow("signup");
        if (action === "logout") {
          if (window.AmiCorSession && typeof window.AmiCorSession.logout === "function") {
            window.AmiCorSession.logout().finally(() => {
              state.pendingRoute = null;
              setModuleVisibility(false, { authGate: true });
              renderRuntimeShell("logout");
            });
          }
        }
        if (action === "clear-role-override") {
          state.shellRoleOverride = null;
          persistRuntimeState("clear_role_override");
          const currentProfile = getSessionProfile();
          const next = clampRouteForRole(state.route, getEffectiveShellRole(currentProfile.role));
          renderRuntimeShell("clear_role_override");
          if (next !== state.route) {
            navigate(next, true, { source: "clear-role-override" });
          }
        }
        if (action === "dismiss-modal") closeModal();
      });
    });

    document.addEventListener("change", (event) => {
      const target = event && event.target ? event.target : null;
      if (!target || target.id !== "health-shell-role-switch") return;
      const value = String(target.value || "").toLowerCase();
      if (!ROLE_ROUTE_ACCESS[value]) return;
      state.shellRoleOverride = value;
      persistRuntimeState("switch_role_override");
      const nextRoute = clampRouteForRole(state.route, value);
      renderRuntimeShell("switch_role_override");
      if (nextRoute !== state.route) {
        navigate(nextRoute, true, { source: "role-switch" });
      } else {
        renderAll();
      }
    });

    if (els.voicePtt) {
      els.voicePtt.addEventListener('click', function () {
        startVoiceCapture('dispatch');
      });
    }
    if (els.voiceStop) {
      els.voiceStop.addEventListener('click', function () {
        stopVoiceCapture(true);
      });
    }
    if (els.aiRefresh) {
      els.aiRefresh.addEventListener('click', function () {
        refreshData().catch(function (error) {
          showToastSafe('AI refresh failed: ' + error.message, 'error');
        });
      });
    }
    if (els.aiReplay) {
      els.aiReplay.addEventListener('click', function () {
        retryFailedWorkflow().then(function () {
          showToastSafe('Replay submitted to resilient event queue.', 'success');
        }).catch(function (error) {
          showToastSafe('Replay failed: ' + error.message, 'error');
        });
      });
    }
    if (els.intakeVoice) {
      els.intakeVoice.addEventListener('click', function () {
        startVoiceCapture('intake');
      });
    }
    if (els.intakeAssist) {
      els.intakeAssist.addEventListener('click', function () {
        runIntakeAssist().catch(function (error) {
          showToastSafe('AI intake assist failed: ' + error.message, 'error');
        });
      });
    }

    if (els.modal) {
      els.modal.addEventListener("click", (event) => {
        if (event.target === els.modal) closeModal();
      });
    }

    if (els.rideDetailsModal) {
      els.rideDetailsModal.addEventListener("click", (event) => {
        const dismiss = event.target.closest('[data-health-action="dismiss-ride-details"]');
        if (dismiss || event.target === els.rideDetailsModal) {
          closeRideDetailsModal();
        }
      });
    }

    bindFilterEvents();

    document.addEventListener("click", (event) => {
      const toggle = event.target && event.target.closest ? event.target.closest("[data-hc-id]") : null;
      if (!toggle) return;
      const id = toggle.getAttribute("data-hc-id");
      if (!id) return;
      const section = document.getElementById(id);
      if (!section) return;
      section.classList.toggle("open");
    });

    document.addEventListener('click', function (event) {
      const routeProgressButton = event.target.closest('[data-driver-route-progress]');
      if (routeProgressButton) {
        const targetState = routeProgressButton.getAttribute('data-driver-route-progress');
        const rideId = routeProgressButton.getAttribute('data-driver-route-ride') || '';
        progressDriverRoute(targetState, rideId).then(function () {
          showToastSafe('Driver route progressed to ' + String(targetState || '').replace(/_/g, ' ') + '.', 'success');
        }).catch(function (error) {
          showToastSafe('Route progress failed: ' + error.message, 'error');
        });
        return;
      }

      const providerReadyButton = event.target.closest('[data-provider-request-ready]');
      if (providerReadyButton) {
        const providerId = providerReadyButton.getAttribute('data-provider-id');
        const requestId = providerReadyButton.getAttribute('data-provider-request-ready');
        markProviderRequest(providerId, requestId, 'ready').then(function () {
          showToastSafe('Provider marked request ready.', 'success');
        }).catch(function (error) {
          showToastSafe('Provider ready update failed: ' + error.message, 'error');
        });
        return;
      }

      const providerDelayButton = event.target.closest('[data-provider-request-delay]');
      if (providerDelayButton) {
        const providerId = providerDelayButton.getAttribute('data-provider-id');
        const requestId = providerDelayButton.getAttribute('data-provider-request-delay');
        markProviderRequest(providerId, requestId, 'delay').then(function () {
          showToastSafe('Provider delay captured.', 'warn');
        }).catch(function (error) {
          showToastSafe('Provider delay update failed: ' + error.message, 'error');
        });
        return;
      }

      const providerEscalateButton = event.target.closest('[data-provider-request-escalate]');
      if (providerEscalateButton) {
        const rideId = providerEscalateButton.getAttribute('data-provider-request-escalate');
        runPhase52LifecycleAction('escalation_requested', { rideId: rideId }).then(function () {
          showToastSafe('Escalation signal emitted for ride ' + String(rideId || '').slice(0, 8) + '.', 'warn');
        }).catch(function (error) {
          showToastSafe('Escalation failed: ' + error.message, 'error');
        });
        return;
      }

      const adminReassignButton = event.target.closest('[data-admin-reassign-ride]');
      if (adminReassignButton) {
        const rideId = adminReassignButton.getAttribute('data-admin-reassign-ride');
        const driverId = window.prompt('Driver ID to reassign ride ' + rideId, '') || '';
        if (!driverId.trim()) return;
        adminReassignDriver(rideId, driverId.trim()).then(function () {
          showToastSafe('Admin reassignment completed.', 'success');
        }).catch(function (error) {
          showToastSafe('Admin reassignment failed: ' + error.message, 'error');
        });
        return;
      }

      const adminExpireButton = event.target.closest('[data-admin-expire-offer]');
      if (adminExpireButton) {
        const offerId = adminExpireButton.getAttribute('data-admin-expire-offer');
        if (!offerId) {
          showToastSafe('No active offer available to expire for this ride.', 'warn');
          return;
        }
        adminForceExpireAssignment(offerId).then(function () {
          showToastSafe('Assignment offer force-expired.', 'warn');
        }).catch(function (error) {
          showToastSafe('Force-expire failed: ' + error.message, 'error');
        });
        return;
      }

      const adminRecoverButton = event.target.closest('[data-admin-recover-ride]');
      if (adminRecoverButton) {
        const rideId = adminRecoverButton.getAttribute('data-admin-recover-ride');
        runPhase52DispatchRecovery(rideId, 'auto_assign').then(function () {
          showToastSafe('Dispatch recovery executed for ride ' + String(rideId || '').slice(0, 8) + '.', 'success');
        }).catch(function (error) {
          showToastSafe('Dispatch recovery failed: ' + error.message, 'error');
        });
        return;
      }

      const claimOwnershipButton = event.target.closest('[data-dispatch-claim-ride]');
      if (claimOwnershipButton) {
        const rideId = claimOwnershipButton.getAttribute('data-dispatch-claim-ride');
        dispatchClaimOwnership(rideId).then(function () {
          showToastSafe('Ownership lock claimed for ride ' + String(rideId || '').slice(0, 8) + '.', 'success');
        }).catch(function (error) {
          showToastSafe('Ownership claim failed: ' + error.message, 'error');
        });
        return;
      }

      const handoffOwnershipButton = event.target.closest('[data-dispatch-handoff-ride]');
      if (handoffOwnershipButton) {
        const rideId = handoffOwnershipButton.getAttribute('data-dispatch-handoff-ride');
        const toUserId = window.prompt('Handoff to dispatcher user ID', '') || '';
        if (!toUserId.trim()) return;
        dispatchHandoffOwnership(rideId, toUserId.trim()).then(function () {
          showToastSafe('Ownership handoff completed for ride ' + String(rideId || '').slice(0, 8) + '.', 'success');
        }).catch(function (error) {
          showToastSafe('Ownership handoff failed: ' + error.message, 'error');
        });
        return;
      }

      const supervisorEscalationButton = event.target.closest('[data-dispatch-supervisor-escalate]');
      if (supervisorEscalationButton) {
        const rideId = supervisorEscalationButton.getAttribute('data-dispatch-supervisor-escalate');
        const summary = window.prompt('Supervisor escalation summary', 'High-risk ride requires supervisor review') || '';
        dispatchSupervisorEscalation(rideId, summary).then(function () {
          showToastSafe('Supervisor escalation emitted for ride ' + String(rideId || '').slice(0, 8) + '.', 'warn');
        }).catch(function (error) {
          showToastSafe('Supervisor escalation failed: ' + error.message, 'error');
        });
        return;
      }

      const customerLifecycleButton = event.target.closest('[data-phase52-customer-action]');
      if (customerLifecycleButton) {
        const actionName = customerLifecycleButton.getAttribute('data-phase52-customer-action');
        const rideId = customerLifecycleButton.getAttribute('data-phase52-ride-id');
        runPhase52LifecycleAction(actionName, { rideId: rideId }).then(function () {
          showToastSafe('Lifecycle action applied: ' + actionName, 'success');
        }).catch(function (error) {
          showToastSafe('Lifecycle action failed: ' + error.message, 'error');
        });
      }
    });

    if (els.form) {
      els.form.addEventListener("submit", (event) => {
        handleCreateRideSubmit(event)
          .then((createdRide) => {
            // Success: Show confirmation with ride details
            const rideId = createdRide && createdRide.id ? String(createdRide.id).slice(0, 12) : "Unknown";
            const passengerName = createdRide && createdRide.passenger_name ? String(createdRide.passenger_name) : "Passenger";
            const pickup = createdRide && createdRide.pickup_address ? String(createdRide.pickup_address) : "Pickup address";
            const dropoff = createdRide && createdRide.dropoff_address ? String(createdRide.dropoff_address) : "Dropoff address";
            const providerName = createdRide && createdRide.provider_id ? lookupProviderName(createdRide.provider_id) : "Provider";
            const scheduledTime = createdRide && createdRide.appointment_time ? formatDateShort(createdRide.appointment_time) : "immediately";
            
            // Show success toast with ID
            showToastSafe("✓ Ride created successfully. ID: " + rideId, "success");
            
            // Show detailed confirmation
            const detailsMsg = "Passenger: " + passengerName + " | Provider: " + providerName + " | From: " + pickup + " | To: " + dropoff + " | When: " + scheduledTime;
            console.log("[Health ISF] Ride created:", { rideId: rideId, passenger: passengerName, provider: providerName, pickup: pickup, dropoff: dropoff, scheduledTime: scheduledTime });
            
            // Refresh ride list immediately to show new ride
            refreshData().then(() => {
              // After refresh, display modal with confirmation before closing
              const messageDiv = document.createElement('div');
              messageDiv.className = 'health-create-ride-success';
              messageDiv.style.cssText = 'padding:12px;margin-bottom:12px;border-radius:8px;background:rgba(100,220,180,0.15);border-left:4px solid #61DCAD;color:#97ffd9;font-size:0.9rem;line-height:1.5;';
              messageDiv.innerHTML = '<strong>✓ Ride Created</strong><br>'
                + 'ID: <code style="background:rgba(0,0,0,0.3);padding:2px 6px;border-radius:3px;">' + escapeHtml(rideId) + '</code><br>'
                + '' + escapeHtml(passengerName) + ' → ' + escapeHtml(providerName) + '<br>'
                + 'From: ' + escapeHtml(pickup) + '<br>'
                + 'To: ' + escapeHtml(dropoff);
              
              const modal = els.modal;
              if (modal && modal.querySelector('.health-modal-body')) {
                const body = modal.querySelector('.health-modal-body');
                body.insertBefore(messageDiv, body.firstChild);
              }
              
              // Keep modal open for 2 seconds so user sees confirmation
              setTimeout(() => {
                closeModal();
              }, 2000);
            }).catch(() => {
              // If refresh fails, still show success and close modal
              setTimeout(() => {
                closeModal();
              }, 2500);
            });
          })
          .catch((error) => {
            // Error: Keep modal open and show error message
            showToastSafe("Ride creation failed: " + (error && error.message ? error.message : "Unknown error"), "error");
            renderCreateRideErrors({}, (error && error.message ? error.message : "Failed to create ride. Please try again."));
          });
      });
    }

    if (els.customerRequestForm) {
      els.customerRequestForm.addEventListener('submit', function (event) {
        event.preventDefault();
        const formData = new FormData(els.customerRequestForm);
        submitCustomerRideRequest(formData).then(function () {
          showToastSafe('Customer ride request submitted.', 'success');
          els.customerRequestForm.reset();
        }).catch(function (error) {
          showToastSafe('Customer request failed: ' + error.message, 'error');
        });
      });
    }

    if (els.onboardingForm) {
      els.onboardingForm.addEventListener('submit', function (event) {
        event.preventDefault();
        const formData = new FormData(els.onboardingForm);
        submitDriverApplication(formData).then(function () {
          showToastSafe('Driver application submitted.', 'success');
          els.onboardingForm.reset();
        }).catch(function (error) {
          showToastSafe('Onboarding submit failed: ' + error.message, 'error');
        });
      });
    }

    if (els.onboardingSeed) {
      els.onboardingSeed.addEventListener('click', function () {
        seedPhase43Data().then(function () {
          showToastSafe('Phase 43 seed data applied.', 'success');
          const refreshed = getEls();
          if (refreshed.onboardingStatus) {
            refreshed.onboardingStatus.textContent = 'Phase 43 data seeded and synchronized.';
          }
        }).catch(function (error) {
          showToastSafe('Phase 43 seed failed: ' + error.message, 'error');
        });
      });
    }

    if (els.onboardingList) {
      els.onboardingList.addEventListener('click', function (event) {
        const statusButton = event.target.closest('[data-driver-app-status]');
        if (!statusButton) return;
        const appId = statusButton.getAttribute('data-driver-app-id');
        const status = statusButton.getAttribute('data-driver-app-status');
        if (!appId || !status) return;
        setDriverApplicationStatus(appId, status).then(function () {
          showToastSafe('Application moved to ' + status + '.', 'success');
        }).catch(function (error) {
          showToastSafe('Review update failed: ' + error.message, 'error');
        });
      });
    }

    if (els.ridesTable) {
      els.ridesTable.addEventListener("click", (event) => {
        const supervisorAction = event.target.closest('[data-phase59-supervisor-action]');
        if (supervisorAction) {
          const action = String(supervisorAction.getAttribute('data-phase59-supervisor-action') || '').toLowerCase();
          if (!action) return;
          const context = phase59OperatorContext();
          const intent = {
            topic: 'phase59.supervisor_control',
            action: action,
            selectedRideId: context.selectedRideId || null,
            mode: action === 'override_intent_log' ? 'active' : 'read-only',
          };
          state.phase59OverrideIntents.unshift(Object.assign({ at: stampNow(), role: context.role }, intent));
          state.phase59OverrideIntents = state.phase59OverrideIntents.slice(0, 40);
          recordExecutionEvent(intent);
          if (action === 'override_intent_log') {
            showToastSafe('Supervisor override intent logged for audit visibility.', 'info');
          } else {
            showToastSafe('Supervisor control is read-only in the current operations contract.', 'warn');
          }
          return;
        }

        const focusRide = event.target.closest('[data-phase59-focus-ride]');
        if (focusRide) {
          const rideId = String(focusRide.getAttribute('data-phase59-focus-ride') || '');
          if (!rideId) return;
          selectRide(rideId);
          showToastSafe('Focused ride ' + rideId.slice(0, 8) + ' from lifecycle panel.', 'info');
          return;
        }

        const phase58Nav = event.target.closest('[data-phase58-nav]');
        if (phase58Nav) {
          const direction = String(phase58Nav.getAttribute('data-phase58-nav') || '').toLowerCase();
          const step = Math.max(12, Math.min(64, Number(state.phase58TimelineWindowSize || 28)));
          if (direction === 'older') {
            state.phase58TimelineOffset = Number(state.phase58TimelineOffset || 0) + step;
          }
          if (direction === 'newer') {
            state.phase58TimelineOffset = Math.max(0, Number(state.phase58TimelineOffset || 0) - step);
          }
          renderRides();
          return;
        }

        const selectedRide = event.target.closest("[data-ride-select]");
        if (selectedRide) {
          selectRide(selectedRide.getAttribute("data-ride-select"));
          return;
        }

        const statusButton = event.target.closest("[data-ride-status]");
        if (statusButton) {
          if (!canMutateRides()) {
            window.alert("Your role cannot modify ride statuses.");
            return;
          }
          const rideId = statusButton.getAttribute("data-ride-id");
          const status = statusButton.getAttribute("data-ride-status");
          if (!rideId || !status) return;
          updateRideStatus(rideId, status).catch((error) => {
            window.alert("Status update failed: " + error.message);
          });
          return;
        }

        const driverAction = event.target.closest("[data-driver-action]");
        if (driverAction) {
          if (!canMutateRides()) {
            window.alert("Your role cannot modify driver workflow.");
            return;
          }
          const rideId = driverAction.getAttribute("data-ride-id");
          const driverId = driverAction.getAttribute("data-driver-id");
          const action = driverAction.getAttribute("data-driver-action");
          if (!rideId || !driverId || !action) return;
          runDriverWorkflow(rideId, driverId, action).catch((error) => {
            window.alert("Driver action failed: " + error.message);
          });
          return;
        }

        const assignButton = event.target.closest("[data-ride-assign]");
        if (assignButton) {
          if (!canMutateRides()) {
            window.alert("Your role cannot assign drivers.");
            return;
          }
          const rideId = assignButton.getAttribute("data-ride-assign");
          if (!rideId) return;
          const select = els.ridesTable.querySelector('[data-ride-driver-select="' + rideId + '"]');
          const driverId = select ? String(select.value || "") : "";
          if (!driverId) {
            window.alert("Select a driver before assigning.");
            return;
          }
          assignDriver(rideId, driverId).catch((error) => {
            window.alert("Driver assignment failed: " + error.message);
          });
        }
      });

      els.ridesTable.addEventListener("change", (event) => {
        const filterNode = event.target && event.target.closest ? event.target.closest('[data-phase58-filter]') : null;
        if (!filterNode) return;
        const key = String(filterNode.getAttribute('data-phase58-filter') || '').toLowerCase();
        if (!key) return;
        const current = phase58TimelineFilters();
        const fallback = key === 'query' ? '' : 'all';
        current[key] = String(filterNode.value || fallback);
        state.phase58TimelineFilters = current;
        state.phase58TimelineOffset = 0;
        renderRides();
      });

      els.ridesTable.addEventListener("input", (event) => {
        const filterNode = event.target && event.target.closest ? event.target.closest('[data-phase58-filter="query"]') : null;
        if (!filterNode) return;
        const current = phase58TimelineFilters();
        current.query = String(filterNode.value || '');
        state.phase58TimelineFilters = current;
        state.phase58TimelineOffset = 0;
        renderRides();
      });

    }

    if (els.dispatchWorklist) {
      els.dispatchWorklist.addEventListener("click", (event) => {
        const focus = event.target.closest("[data-dispatch-select-ride]");
        if (focus) {
          selectRide(focus.getAttribute("data-dispatch-select-ride"));
          showToastSafe("Focused ride in dispatch workspace.", "info");
          return;
        }

        const assignButton = event.target.closest("[data-dispatch-assign]");
        if (assignButton) {
          if (!canMutateRides()) {
            window.alert("Your role cannot assign drivers.");
            return;
          }
          const rideId = assignButton.getAttribute("data-dispatch-assign");
          if (!rideId) return;
          const select = els.dispatchWorklist.querySelector('[data-dispatch-driver-select="' + rideId + '"]');
          const driverId = select ? String(select.value || "") : "";
          if (!driverId) {
            window.alert("Select a driver before assigning.");
            return;
          }
          assignDriver(rideId, driverId).catch((error) => {
            window.alert("Driver assignment failed: " + error.message);
          });
          return;
        }

        const statusButton = event.target.closest("[data-dispatch-status]");
        if (statusButton) {
          if (!canMutateRides()) {
            window.alert("Your role cannot update ride statuses.");
            return;
          }
          const rideId = statusButton.getAttribute("data-dispatch-ride");
          const status = statusButton.getAttribute("data-dispatch-status");
          if (!rideId || !status) return;
          updateRideStatus(rideId, status).catch((error) => {
            window.alert("Status update failed: " + error.message);
          });
        }
      });
    }

    [els.queuePending, els.queueActive, els.queueCompleted, els.queueProblem].forEach((column) => {
      if (!column) return;
      column.addEventListener("click", handleBoardClick);
    });

    if (els.driverCards) {
      els.driverCards.addEventListener("click", (event) => {
        const inspectButton = event.target.closest("[data-driver-inspect]");
        if (inspectButton) {
          const driverId = inspectButton.getAttribute("data-driver-inspect");
          if (!driverId) return;
          state.selectedDriverId = driverId;
          const runtimeEls = getEls();
          if (runtimeEls.driverRuntimeId) {
            runtimeEls.driverRuntimeId.value = driverId;
          }
          Promise.all([
            fetchDriverAssignedRides(driverId),
            refreshDriverRuntimeStatus().catch(function () { return null; }),
            refreshDriverLiveWorkspace().catch(function () { return null; }),
          ]).then(function () {
            renderDrivers();
          }).catch(function (error) {
            showToastSafe('Driver worklist failed: ' + error.message, 'error');
          });
          return;
        }

        const setStatusButton = event.target.closest("[data-driver-set-status]");
        if (!setStatusButton) return;
        const driverId = setStatusButton.getAttribute("data-driver-id");
        const status = setStatusButton.getAttribute("data-driver-set-status");
        if (!driverId || !status) return;
        setDriverStatus(driverId, status).catch((error) => {
          window.alert("Driver status update failed: " + error.message);
        });
      });
    }

    if (els.driverRuntimeId) {
      els.driverRuntimeId.addEventListener('change', function () {
        const selected = String(els.driverRuntimeId.value || '').trim();
        state.selectedDriverId = selected || null;
        if (!selected) {
          state.selectedDriverAssignedRides = [];
          state.driverRuntimeStatus = null;
          state.driverLiveWorkspace = null;
          renderDrivers();
          return;
        }
        Promise.all([
          fetchDriverAssignedRides(selected).catch(function () { return []; }),
          refreshDriverRuntimeStatus().catch(function () { return null; }),
          refreshDriverLiveWorkspace().catch(function () { return null; }),
        ]).then(function () {
          renderDrivers();
        });
      });
    }

    if (els.driverLogin) {
      els.driverLogin.addEventListener('click', function () {
        loginDriverRuntime().then(function () {
          return Promise.all([
            refreshDriverRuntimeStatus().catch(function () { return null; }),
            refreshDriverLiveWorkspace().catch(function () { return null; }),
            refreshData(),
          ]);
        }).then(function () {
          showToastSafe('Driver session activated.', 'success');
        }).catch(function (error) {
          showToastSafe('Driver login failed: ' + error.message, 'error');
        });
      });
    }

    if (els.driverLogout) {
      els.driverLogout.addEventListener('click', function () {
        logoutDriverRuntime().then(function () {
          state.driverRuntimeStatus = null;
          return refreshData();
        }).then(function () {
          showToastSafe('Driver session closed.', 'success');
        }).catch(function (error) {
          showToastSafe('Driver logout failed: ' + error.message, 'error');
        });
      });
    }

    if (els.driverSetAvailability) {
      els.driverSetAvailability.addEventListener('click', function () {
        setDriverRuntimeAvailability().then(function () {
          return Promise.all([
            refreshDriverRuntimeStatus().catch(function () { return null; }),
            refreshDriverLiveWorkspace().catch(function () { return null; }),
            refreshData(),
          ]);
        }).then(function () {
          showToastSafe('Driver availability updated.', 'success');
        }).catch(function (error) {
          showToastSafe('Availability update failed: ' + error.message, 'error');
        });
      });
    }

    if (els.driverHeartbeat) {
      els.driverHeartbeat.addEventListener('click', function () {
        heartbeatDriverRuntime().then(function () {
          return Promise.all([
            refreshDriverRuntimeStatus().catch(function () { return null; }),
            refreshDriverLiveWorkspace().catch(function () { return null; }),
          ]);
        }).then(function () {
          showToastSafe('Driver heartbeat recorded.', 'success');
          renderDrivers();
        }).catch(function (error) {
          showToastSafe('Heartbeat failed: ' + error.message, 'error');
        });
      });
    }

    if (els.driverRefreshStatus) {
      els.driverRefreshStatus.addEventListener('click', function () {
        refreshDriverRuntimeStatus().then(function () {
          return refreshDriverLiveWorkspace().catch(function () { return null; });
        }).then(function () {
          renderDrivers();
          showToastSafe('Driver status refreshed.', 'info');
        }).catch(function (error) {
          showToastSafe('Status refresh failed: ' + error.message, 'error');
        });
      });
    }

    if (els.dispatchAutoAssign) {
      els.dispatchAutoAssign.addEventListener('click', function () {
        runDispatchAutoAssign().then(function () {
          return refreshData();
        }).then(function () {
          showToastSafe('Auto-assignment workflow completed.', 'success');
        }).catch(function (error) {
          showToastSafe('Auto-assignment failed: ' + error.message, 'error');
        });
      });
    }

    if (els.dispatchReassign) {
      els.dispatchReassign.addEventListener('click', function () {
        runDispatchReassign().then(function () {
          return refreshData();
        }).then(function () {
          showToastSafe('Reassignment workflow completed.', 'success');
        }).catch(function (error) {
          showToastSafe('Reassignment failed: ' + error.message, 'error');
        });
      });
    }

    if (els.dispatchRefreshIntel) {
      els.dispatchRefreshIntel.addEventListener('click', function () {
        refreshDispatchIntelligence().then(function () {
          renderRides();
          renderDrivers();
          showToastSafe('Dispatch intelligence refreshed.', 'info');
        }).catch(function (error) {
          showToastSafe('Dispatch intelligence refresh failed: ' + error.message, 'error');
        });
      });
    }

    if (els.requestApprove) {
      els.requestApprove.addEventListener('click', function () {
        runCustomerRequestAction('/approve', 'POST', {}).then(function () {
          setRequestActionStatus('Request approved for dispatch.', 'ok');
          return refreshData();
        }).catch(function (error) {
          setRequestActionStatus('Approve failed: ' + error.message, 'error');
          showToastSafe('Request approve failed: ' + error.message, 'error');
        });
      });
    }

    if (els.requestAutoDispatch) {
      els.requestAutoDispatch.addEventListener('click', function () {
        runCustomerRequestAction('/auto-dispatch', 'POST', { offer_timeout_seconds: 90 }).then(function () {
          setRequestActionStatus('Auto-dispatch executed.', 'ok');
          return refreshData();
        }).catch(function (error) {
          setRequestActionStatus('Auto-dispatch failed: ' + error.message, 'error');
          showToastSafe('Auto-dispatch failed: ' + error.message, 'error');
        });
      });
    }

    if (els.requestAssignDriver) {
      els.requestAssignDriver.addEventListener('click', function () {
        const driverId = String((els.requestDriverId && els.requestDriverId.value) || '').trim();
        if (!driverId) {
          setRequestActionStatus('Driver ID is required for assign.', 'warn');
          return;
        }
        runCustomerRequestAction('/assign-driver', 'POST', { driver_id: driverId }).then(function () {
          setRequestActionStatus('Driver assigned to customer request.', 'ok');
          return refreshData();
        }).catch(function (error) {
          setRequestActionStatus('Assign failed: ' + error.message, 'error');
          showToastSafe('Assign driver failed: ' + error.message, 'error');
        });
      });
    }

    if (els.requestReassign) {
      els.requestReassign.addEventListener('click', function () {
        runCustomerRequestAction('/reassign', 'POST', { offer_timeout_seconds: 90, reason: 'dispatcher_reassign' }).then(function () {
          setRequestActionStatus('Reassignment submitted.', 'ok');
          return refreshData();
        }).catch(function (error) {
          setRequestActionStatus('Reassign failed: ' + error.message, 'error');
          showToastSafe('Reassign failed: ' + error.message, 'error');
        });
      });
    }

    if (els.requestCancel) {
      els.requestCancel.addEventListener('click', function () {
        runCustomerRequestAction('/cancel', 'PATCH', { reason: 'dispatcher_cancelled_request' }).then(function () {
          setRequestActionStatus('Request cancelled.', 'ok');
          return refreshData();
        }).catch(function (error) {
          setRequestActionStatus('Cancel failed: ' + error.message, 'error');
          showToastSafe('Cancel failed: ' + error.message, 'error');
        });
      });
    }

    if (els.requestComplete) {
      els.requestComplete.addEventListener('click', function () {
        runCustomerRequestAction('/complete', 'PATCH', { reason: 'dispatcher_manual_complete' }).then(function () {
          setRequestActionStatus('Request marked complete.', 'ok');
          return refreshData();
        }).catch(function (error) {
          setRequestActionStatus('Complete failed: ' + error.message, 'error');
          showToastSafe('Complete failed: ' + error.message, 'error');
        });
      });
    }

    if (els.driverOfferAccept) {
      els.driverOfferAccept.addEventListener('click', function () {
        acceptDriverIncomingOffer().then(function () {
          return refreshData();
        }).then(function () {
          showToastSafe('Driver offer accepted.', 'success');
        }).catch(function (error) {
          showToastSafe('Offer accept failed: ' + error.message, 'error');
        });
      });
    }

    if (els.driverOfferReject) {
      els.driverOfferReject.addEventListener('click', function () {
        rejectDriverIncomingOffer().then(function () {
          return refreshData();
        }).then(function () {
          showToastSafe('Driver offer rejected and returned to pool.', 'warn');
        }).catch(function (error) {
          showToastSafe('Offer reject failed: ' + error.message, 'error');
        });
      });
    }

    if (els.driverOfferRefresh) {
      els.driverOfferRefresh.addEventListener('click', function () {
        refreshDispatchIntelligence().then(function () {
          renderDrivers();
          showToastSafe('Driver offer state refreshed.', 'info');
        }).catch(function (error) {
          showToastSafe('Offer refresh failed: ' + error.message, 'error');
        });
      });
    }

    window.addEventListener("focus", () => {
      if (!state.active) return;
      triggerHydrationRefresh("window-focus");
      monitorRealtimeHealth("window-focus");
    });

    document.addEventListener("visibilitychange", () => {
      if (!state.active || document.visibilityState !== "visible") return;
      logDiag("Visibility hydration", { visibilityState: document.visibilityState });
      triggerHydrationRefresh("visibility-visible");
      monitorRealtimeHealth("visibility-visible");
    });

    window.addEventListener("storage", (event) => {
      const key = String((event && event.key) || "");
      if (key !== "amicor_identity" && key !== "amicor_session") return;
      if (!state.active) return;
      triggerHydrationRefresh("session-storage-change");
    });

    window.addEventListener("amicor:session-recovered", () => {
      renderRuntimeShell("session_recovered");
      if (state.pendingRoute) {
        const pendingRoute = state.pendingRoute;
        state.pendingRoute = null;
        navigate(pendingRoute, true, { source: "session-recovered", force: true, bypassRefreshCooldown: true });
        return;
      }
      if (state.active) {
        reconnectRealtime("session-recovered", { force: true, onlyIfStale: false, bypassCooldown: true });
      }
    });

    window.addEventListener("amicor:session-invalid", () => {
      disconnectRealtimeSocket();
      state.websocketStatus = "auth_required";
      state.active = false;
      state.authGateVisible = true;
      setModuleVisibility(false, { authGate: true });
      renderRuntimeShell("session_invalid");
    });

    window.addEventListener("hashchange", onHashRoute);
  }

  function init() {
    const els = getEls();
    if (!els.shell) return;
    restoreRuntimeState();
    ensureShellChrome();
    renderRuntimeShell("init");
    bindEvents();
    closeModal();
    setModuleVisibility(false);
    onHashRoute();
  }

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", init);
  } else {
    init();
  }

  window.AmiCorHealthISF = {
    navigate,
    refreshData,
    close: closeModule,
    runIntakeAssist,
    startVoiceCapture,
    getRuntimeStatus: function () {
      const tokenPresent = !!(window.AmiCorSession
        && typeof window.AmiCorSession.getAccessToken === "function"
        && window.AmiCorSession.getAccessToken());
      const sessionActive = !!(window.AmiCorSession
        && typeof window.AmiCorSession.isActive === "function"
        && window.AmiCorSession.isActive());
      return {
        route: state.route,
        active: state.active,
        websocketStatus: state.websocketStatus,
        lastRefreshAt: state.hydration.lastRefreshAt,
        hasDashboard: !!state.dashboard,
        hasAiSnapshot: !!state.aiSnapshot,
        aiSnapshotDegraded: !!state.hydration.aiSnapshotDegraded,
        hydrationError: state.hydration.lastRefreshError || state.hydration.aiSnapshotError || null,
        lastApiError: state.lastApiError,
        lastCompletedAction: state.lastCompletedAction,
        lastFailedAction: state.lastFailedAction,
        lastActionAt: state.lastActionAt,
        pendingRequests: state.pendingRequests,
        executionEvents: Array.isArray(state.executionEvents) ? state.executionEvents.slice(0, 30) : [],
        continuityBrief: state.novaContinuityBrief,
        assistanceRecommendations: Array.isArray(state.novaAssistanceRecommendations) ? state.novaAssistanceRecommendations.slice(0, 20) : [],
        memoryFabric: state.novaMemoryFabric,
        executionTimeline: state.novaMemoryFabric && Array.isArray(state.novaMemoryFabric.execution_timeline)
          ? state.novaMemoryFabric.execution_timeline.slice(0, 40)
          : [],
        activeOrganizationId: state.activeOrganizationId || getOrganizationId() || null,
        shellVisible: !!(state.active || state.authGateVisible),
        authGateVisible: !!state.authGateVisible,
        pendingRoute: state.pendingRoute || null,
        isolationActive: operatorIsolationEnabled(),
        stability: Object.assign({}, state.stability),
        navigation: {
          lastNavigateAtMs: state.navSync.lastNavigateAtMs,
          lastNavigateRoute: state.navSync.lastNavigateRoute,
          lastNavigateSource: state.navSync.lastNavigateSource,
          suppressHashRoute: state.navSync.suppressHashRoute,
          suppressHashRouteUntilMs: state.navSync.suppressHashRouteUntilMs,
        },
        shellProfile: state.shellProfile || null,
        tokenPresent: tokenPresent,
        sessionActive: sessionActive,
        memoryHooksActive: !!window.AmiCorMemoryManager,
        aiOrchestrationActive: !!window.AmiCorOrchestrator,
      };
    },
  };
})();
