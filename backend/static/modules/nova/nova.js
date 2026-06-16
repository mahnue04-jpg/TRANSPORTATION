(function () {
  const NOVA_API = "/api/nova";
  const NOVA_REQUEST_TIMEOUT_MS = 70000;
  const NOVA_STATUS_TIMEOUT_MS = 35000;
  const NOVA_STREAM_IDLE_TIMEOUT_MS = 10000;
  const NOVA_BUSY_FAILSAFE_MS = 90000;
  const NOVA_HEARTBEAT_INTERVAL_MS = 60000;

  const runtime = {
    busy: false,
    pendingRequests: 0,
    activeOrganizationId: null,
    lastRequestPath: null,
    lastCompletedAction: null,
    lastFailedAction: null,
    lastApiError: null,
    lastActionAt: null,
    lastResponseAt: null,
    lastStreamPhase: "idle",
    lastActionId: null,
    actionEvents: [],
    actionEventKeys: [],
    busySinceAt: null,
    busyFailsafeTimer: null,
    continuityBrief: null,
    assistanceRecommendations: [],
    heartbeatTimer: null,
    memoryEventKeys: [],
  };

  function stampNow() {
    return new Date().toISOString();
  }

  function currentOrganizationId() {
    try {
      if (window.AmiCorSession && typeof window.AmiCorSession.getOrganizationId === "function") {
        const orgId = window.AmiCorSession.getOrganizationId();
        runtime.activeOrganizationId = orgId ? String(orgId) : null;
        return orgId;
      }
    } catch (_) {}
    return null;
  }

  function withOrgQuery(path) {
    if (/[?&]organization_id=/.test(String(path || ""))) return path;
    const orgId = currentOrganizationId();
    if (!orgId) return path;
    const joiner = path.indexOf("?") === -1 ? "?" : "&";
    return path + joiner + "organization_id=" + encodeURIComponent(String(orgId));
  }

  function scopedNovaPath(path) {
    const normalized = String(path || "");
    if (!normalized.startsWith(NOVA_API)) return normalized;
    return withOrgQuery(normalized);
  }

  function getWsDeliveryStatus() {
    try {
      if (window.AmiCorHealthISF && typeof window.AmiCorHealthISF.getRuntimeStatus === "function") {
        const status = window.AmiCorHealthISF.getRuntimeStatus() || {};
        return String(status.websocketStatus || "idle");
      }
    } catch (_) {}
    return "unknown";
  }

  function normalizeExecutionError(error) {
    const message = String(error && error.message ? error.message : error || "Request failed");
    const lower = message.toLowerCase();
    if (lower.indexOf("aborted") !== -1 || lower.indexOf("timeout") !== -1) {
      return "Operational request timed out";
    }
    if (lower.indexOf("401") !== -1 || lower.indexOf("403") !== -1 || lower.indexOf("auth") !== -1 || lower.indexOf("token") !== -1) {
      return "Authentication session expired";
    }
    if (lower.indexOf("network") !== -1 || lower.indexOf("failed to fetch") !== -1) {
      return "Realtime execution reconnecting";
    }
    return message;
  }

  function pushActionEvent(event) {
    const normalized = Object.assign({
      at: stampNow(),
      actionId: runtime.lastActionId,
      auth: !!(window.AmiCorSession && typeof window.AmiCorSession.getAccessToken === "function" && window.AmiCorSession.getAccessToken()),
      websocket: getWsDeliveryStatus(),
    }, event || {});
    const eventKey = [
      String(normalized.stage || "event"),
      String(normalized.actionId || runtime.lastActionId || "none"),
      String(normalized.path || ""),
      String(normalized.error || ""),
    ].join("|");
    if (runtime.actionEventKeys.indexOf(eventKey) !== -1) {
      return;
    }
    runtime.actionEventKeys.unshift(eventKey);
    runtime.actionEventKeys = runtime.actionEventKeys.slice(0, 120);
    runtime.actionEvents.unshift(normalized);
    runtime.actionEvents = runtime.actionEvents.slice(0, 60);
    persistExecutionEvent(normalized);
  }

  function persistExecutionEvent(event) {
    const stage = String(event && event.stage ? event.stage : "event");
    if (["started", "completed", "failed", "failsafe_release", "stream_started", "stream_completed", "stream_failed"].indexOf(stage) === -1) {
      return;
    }
    const correlationId = String(event && event.actionId ? event.actionId : runtime.lastActionId || "nova") + ":" + stage;
    if (runtime.memoryEventKeys.indexOf(correlationId) !== -1) {
      return;
    }
    runtime.memoryEventKeys.unshift(correlationId);
    runtime.memoryEventKeys = runtime.memoryEventKeys.slice(0, 240);

    const payload = {
      organization_id: currentOrganizationId() || null,
      channel: "workflow_history",
      event_type: stage,
      summary: String(event && event.error ? event.error : (event && event.path ? event.path : "Nova execution event")),
      source: "nova.runtime",
      tags: ["phase6d", "execution_timeline", "nova"],
      correlation_id: correlationId,
      metadata: {
        stage: stage,
        path: event && event.path ? String(event.path) : null,
        duration_ms: event && event.durationMs ? Number(event.durationMs) : null,
        failure_reason: event && event.error ? String(event.error) : null,
        recovery_attempt: stage === "failsafe_release" ? 1 : null,
        deployment_change: event && event.path && String(event.path).indexOf("review-report") !== -1 ? "deployment_review" : null,
        suggested_action: stage === "failed" ? "Retry action with current authenticated session context" : null,
      },
    };

    const req = {
      method: "POST",
      headers: { "Content-Type": "application/json", "X-Client-Action-Id": correlationId },
      body: JSON.stringify(payload),
    };
    try {
      const endpoint = scopedNovaPath(NOVA_API + "/memory/events");
      if (window.AmiCorSession && typeof window.AmiCorSession.authFetch === "function") {
        window.AmiCorSession.authFetch(endpoint, req).catch(function () {});
      } else {
        fetch(endpoint, req).catch(function () {});
      }
    } catch (_) {}
  }

  function nextActionId(actionName) {
    const id = "nova-" + String(actionName || "action") + "-" + Date.now() + "-" + Math.random().toString(36).slice(2, 8);
    runtime.lastActionId = id;
    return id;
  }

  function getEls() {
    return {
      panel: document.getElementById("nova-panel"),
      askInput: document.getElementById("nova-ask-input"),
      askButton: document.getElementById("nova-ask-submit"),
      actions: Array.from(document.querySelectorAll("[data-nova-action]")),
      output: document.getElementById("nova-output"),
      phasePill: document.getElementById("nova-phase-pill"),
      widgetPhase: document.getElementById("nova-widget-phase"),
      widgetCompletion: document.getElementById("nova-widget-completion"),
      widgetNext: document.getElementById("nova-widget-next"),
      widgetHealth: document.getElementById("nova-widget-health"),
      widgetBusiness: document.getElementById("nova-widget-business"),
    };
  }

  async function authJson(path, options) {
    const resolvedPath = scopedNovaPath(path);
    const opts = Object.assign({}, options || {});
    const timeoutMs = Number.isFinite(Number(opts.timeoutMs)) ? Number(opts.timeoutMs) : NOVA_REQUEST_TIMEOUT_MS;
    const shouldRecordError = !opts.silentErrors;
    const actionId = opts.actionId ? String(opts.actionId) : nextActionId("request");
    const startedAt = Date.now();
    delete opts.timeoutMs;
    delete opts.silentErrors;
    delete opts.actionId;

    const controller = new AbortController();
    const timeout = setTimeout(function () {
      controller.abort();
    }, timeoutMs);
    runtime.pendingRequests += 1;
    runtime.lastRequestPath = String(resolvedPath || "");
    if (shouldRecordError) {
      runtime.lastApiError = null;
      pushActionEvent({ stage: "started", path: String(resolvedPath || ""), actionId: actionId });
    }

    try {
      let response;
      const headers = Object.assign({}, opts.headers || {}, {
        "X-Client-Action-Id": actionId,
      });
      const mergedOptions = Object.assign({}, opts, { signal: controller.signal, headers: headers });
      if (window.AmiCorSession && typeof window.AmiCorSession.authFetch === "function") {
        response = await window.AmiCorSession.authFetch(resolvedPath, mergedOptions);
      } else {
        response = await fetch(resolvedPath, mergedOptions);
      }

      const text = await response.text();
      let data;
      try {
        data = text ? JSON.parse(text) : {};
      } catch (_) {
        data = { raw: text };
      }
      if (!response.ok) {
        const detail = data && data.detail ? data.detail : "Request failed";
        const message = String(detail);
        if (shouldRecordError) {
          runtime.lastApiError = message;
          runtime.lastFailedAction = runtime.lastRequestPath;
          runtime.lastActionAt = stampNow();
        }
        throw new Error(message);
      }
      runtime.lastResponseAt = stampNow();
      if (shouldRecordError) {
        pushActionEvent({
          stage: "completed",
          path: String(resolvedPath || ""),
          actionId: actionId,
          durationMs: Date.now() - startedAt,
          status: response.status,
        });
      }
      return data;
    } catch (error) {
      const message = normalizeExecutionError(error);
      if (shouldRecordError) {
        runtime.lastApiError = message;
        runtime.lastFailedAction = runtime.lastRequestPath;
        runtime.lastActionAt = stampNow();
        pushActionEvent({
          stage: "failed",
          path: String(resolvedPath || ""),
          actionId: actionId,
          durationMs: Date.now() - startedAt,
          error: message,
        });
      }
      throw new Error(message);
    } finally {
      clearTimeout(timeout);
      runtime.pendingRequests = Math.max(0, runtime.pendingRequests - 1);
    }
  }

  function setOutput(els, text) {
    if (!els.output) return;
    els.output.textContent = String(text || "");
  }

  function setBusy(els, busy) {
    runtime.busy = !!busy;
    if (runtime.busyFailsafeTimer) {
      clearTimeout(runtime.busyFailsafeTimer);
      runtime.busyFailsafeTimer = null;
    }
    runtime.busySinceAt = runtime.busy ? stampNow() : null;
    if (els.askButton) {
      els.askButton.disabled = !!busy;
      els.askButton.textContent = busy ? "Working..." : "Ask Mr. Nova";
    }
    if (Array.isArray(els.actions)) {
      els.actions.forEach(function (button) {
        button.disabled = !!busy;
      });
    }
    if (busy) {
      runtime.busyFailsafeTimer = setTimeout(function () {
        runtime.busy = false;
        runtime.lastApiError = "Operational request timed out";
        runtime.lastFailedAction = runtime.lastFailedAction || "busy_failsafe";
        runtime.lastActionAt = stampNow();
        pushActionEvent({ stage: "failsafe_release", error: "Operational request timed out" });
        setBusy(els, false);
        setOutput(els, "Operational request timed out");
      }, NOVA_BUSY_FAILSAFE_MS);
    }
  }

  function setWidget(els, status, context) {
    if (!status || !context) return;
    if (els.phasePill) els.phasePill.textContent = context.platform_phase || "unknown";
    if (els.widgetPhase) els.widgetPhase.textContent = context.platform_phase || "unknown";
    if (els.widgetCompletion) els.widgetCompletion.textContent = status.build_completion_estimate || "n/a";
    if (els.widgetNext) els.widgetNext.textContent = status.next_recommended_action || "n/a";
    if (els.widgetHealth) els.widgetHealth.textContent = status.system_health_summary || "n/a";
    if (els.widgetBusiness) els.widgetBusiness.textContent = status.business_legal_checklist_status || "n/a";
  }

  async function refreshStatus(els) {
    try {
      const results = await Promise.allSettled([
        authJson(withOrgQuery(NOVA_API + "/status"), { timeoutMs: NOVA_STATUS_TIMEOUT_MS, silentErrors: true }),
        authJson(withOrgQuery(NOVA_API + "/context"), { timeoutMs: NOVA_STATUS_TIMEOUT_MS, silentErrors: true }),
        authJson(withOrgQuery(NOVA_API + "/continuity/brief"), { timeoutMs: NOVA_STATUS_TIMEOUT_MS, silentErrors: true }),
        authJson(withOrgQuery(NOVA_API + "/assist/recommendations"), { timeoutMs: NOVA_STATUS_TIMEOUT_MS, silentErrors: true }),
      ]);
      const status = results[0].status === "fulfilled" ? results[0].value : null;
      const context = results[1].status === "fulfilled" ? results[1].value : null;
      const continuity = results[2].status === "fulfilled" ? results[2].value : null;
      const assistance = results[3].status === "fulfilled" ? results[3].value : null;
      if (status && context) {
        setWidget(els, status, context);
      }
      runtime.continuityBrief = continuity;
      runtime.assistanceRecommendations = assistance && Array.isArray(assistance.recommendations)
        ? assistance.recommendations.slice(0, 8)
        : [];
      if (els.output && /loading platform context|status unavailable/i.test(String(els.output.textContent || ""))) {
        const rec = runtime.assistanceRecommendations.length ? runtime.assistanceRecommendations[0] : null;
        const continuityHint = continuity && Array.isArray(continuity.next_actions) && continuity.next_actions.length
          ? " Next: " + String(continuity.next_actions[0] || "")
          : "";
        if (rec && rec.summary) {
          setOutput(els, "Nova context ready. " + String(rec.summary) + continuityHint);
        } else {
          setOutput(els, "Nova context ready. Ask a question or run an action." + continuityHint);
        }
      }
      if (!status || !context) {
        if (els.widgetPhase) els.widgetPhase.textContent = "unavailable";
        if (els.widgetHealth) els.widgetHealth.textContent = "degraded";
        const statusErr = results[0].status === "rejected" ? String(results[0].reason && results[0].reason.message ? results[0].reason.message : results[0].reason) : null;
        const contextErr = results[1].status === "rejected" ? String(results[1].reason && results[1].reason.message ? results[1].reason.message : results[1].reason) : null;
        const reason = contextErr || statusErr || "unavailable";
        setOutput(els, "Mr. Nova status unavailable: " + reason);
      }
    } catch (error) {
      if (els.widgetPhase) els.widgetPhase.textContent = "unavailable";
      if (els.widgetHealth) els.widgetHealth.textContent = "degraded";
      setOutput(els, "Mr. Nova status unavailable: " + String(error && error.message ? error.message : error));
    }
  }

  async function sendHeartbeat() {
    try {
      await authJson(NOVA_API + "/session/heartbeat", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        timeoutMs: Math.min(NOVA_STATUS_TIMEOUT_MS, 12000),
        silentErrors: true,
        body: JSON.stringify({
          status: runtime.busy ? "busy" : "active",
          session_id: window.AmiCorSession && typeof window.AmiCorSession.getCurrent === "function" && window.AmiCorSession.getCurrent()
            ? String((window.AmiCorSession.getCurrent() || {}).sessionId || "")
            : null,
          organization_id: currentOrganizationId() || null,
        }),
      });
    } catch (_) {}
  }

  function startHeartbeat() {
    if (runtime.heartbeatTimer) {
      clearInterval(runtime.heartbeatTimer);
      runtime.heartbeatTimer = null;
    }
    sendHeartbeat();
    runtime.heartbeatTimer = setInterval(function () {
      sendHeartbeat();
    }, NOVA_HEARTBEAT_INTERVAL_MS);
  }

  async function askNovaStreaming(els, payload) {
    const actionId = payload && payload.action_id ? String(payload.action_id) : nextActionId("ask_stream");
    const controller = new AbortController();
    let idleTimer = null;
    const startedAt = Date.now();
    const armIdleTimeout = function () {
      if (idleTimer) clearTimeout(idleTimer);
      idleTimer = setTimeout(function () {
        controller.abort();
      }, NOVA_STREAM_IDLE_TIMEOUT_MS);
    };
    armIdleTimeout();

    try {
      let response;
      if (window.AmiCorSession && typeof window.AmiCorSession.authFetch === "function") {
        response = await window.AmiCorSession.authFetch(withOrgQuery(NOVA_API + "/ask/stream"), {
          method: "POST",
          headers: {
            "Content-Type": "application/json",
            "X-Client-Action-Id": actionId,
          },
          body: JSON.stringify(payload),
          signal: controller.signal,
        });
      } else {
        response = await fetch(withOrgQuery(NOVA_API + "/ask/stream"), {
          method: "POST",
          headers: {
            "Content-Type": "application/json",
            "X-Client-Action-Id": actionId,
          },
          body: JSON.stringify(payload),
          signal: controller.signal,
        });
      }
      if (!response.ok || !response.body) {
        const text = await response.text();
        throw new Error(text || "Streaming request failed");
      }

      const reader = response.body.getReader();
      const decoder = new TextDecoder();
      let buffer = "";
      let fullText = "";
      let finalPayload = null;
      let streamDoneEventSeen = false;
      runtime.lastStreamPhase = "streaming";
      pushActionEvent({ stage: "stream_started", actionId: actionId, path: "/ask/stream" });

      while (true) {
        const packet = await reader.read();
        if (packet.done) break;
        armIdleTimeout();
        buffer += decoder.decode(packet.value, { stream: true });
        const events = buffer.split("\n\n");
        buffer = events.pop() || "";

        for (let i = 0; i < events.length; i += 1) {
          const line = String(events[i] || "").split("\n").find(function (item) {
            return String(item || "").startsWith("data: ");
          });
          if (!line) continue;
          let parsed;
          try {
            parsed = JSON.parse(line.slice(6));
          } catch (_err) {
            continue;
          }
          if (parsed.type === "chunk") {
            fullText += String(parsed.content || "");
            setOutput(els, fullText.trim());
          }
          if (parsed.type === "done") {
            finalPayload = parsed;
            streamDoneEventSeen = true;
            runtime.lastStreamPhase = "done";
            pushActionEvent({
              stage: "stream_completed",
              actionId: actionId,
              path: "/ask/stream",
              durationMs: Date.now() - startedAt,
            });
            break;
          }
        }
        if (streamDoneEventSeen) {
          try {
            await reader.cancel();
          } catch (_err) {}
          break;
        }
      }
      return finalPayload;
    } catch (error) {
      const message = normalizeExecutionError(error);
      runtime.lastStreamPhase = "failed";
      pushActionEvent({
        stage: "stream_failed",
        actionId: actionId,
        path: "/ask/stream",
        durationMs: Date.now() - startedAt,
        error: message,
      });
      throw new Error(message);
    } finally {
      if (idleTimer) clearTimeout(idleTimer);
    }
  }

  async function askNova(els, question) {
    const prompt = String(question || "").trim();
    if (!prompt) {
      setOutput(els, "Enter a prompt for Mr. Nova.");
      return;
    }
    try {
      setBusy(els, true);
      runtime.lastActionAt = stampNow();
      runtime.lastCompletedAction = null;
      runtime.lastFailedAction = null;
      setOutput(els, "Mr. Nova is analyzing live runtime context...");
      const actionId = nextActionId("ask");
      const payload = {
        question: prompt,
        mode: "founder_advisor",
        action_id: actionId,
      };
      const orgId = currentOrganizationId();
      if (orgId) {
        payload.organization_id = String(orgId);
      }

      const result = await askNovaStreaming(els, payload);
      if (!result) {
        throw new Error("Awaiting AI orchestration response");
      }
      const actions = Array.isArray(result.next_actions) ? result.next_actions : [];
      const actionLine = actions.length ? "\nNext actions: " + actions.join(" | ") : "";
      setOutput(els, String(result.answer || "No response") + actionLine);
      runtime.lastCompletedAction = "ask";
      runtime.lastApiError = null;
      runtime.lastActionAt = stampNow();
      if (els.askInput) els.askInput.value = "";
      refreshStatus(els);
    } catch (error) {
      runtime.lastFailedAction = "ask";
      runtime.lastApiError = String(error && error.message ? error.message : error);
      runtime.lastActionAt = stampNow();
      setOutput(els, normalizeExecutionError(error));
    } finally {
      setBusy(els, false);
    }
  }

  async function runAction(els, action) {
    const map = {
      what_built: {
        endpoint: "/summarize",
        body: { summary_type: "build_progress", mode: "engineering_director" },
        extract: function (r) { return r.summary; },
      },
      next_step: {
        endpoint: "/next-step",
        body: { mode: "founder_advisor" },
        extract: function (r) {
          const checklist = Array.isArray(r.checklist) ? r.checklist : [];
          return "Next step: " + String(r.next_recommended_step || "none") + (checklist.length ? "\nChecklist: " + checklist.join(" | ") : "");
        },
      },
      system_health: {
        endpoint: "/summarize",
        body: { summary_type: "operational_health", mode: "operations_commander" },
        extract: function (r) {
          return String(r.summary || "") + (Array.isArray(r.highlights) && r.highlights.length ? "\nHighlights: " + r.highlights.join(" | ") : "");
        },
      },
      founder_checklist: {
        endpoint: "/next-step",
        body: { mode: "founder_advisor", goal: "Generate founder checklist" },
        extract: function (r) {
          const checklist = Array.isArray(r.checklist) ? r.checklist : [];
          return checklist.length ? "Founder checklist: " + checklist.join(" | ") : "Founder checklist unavailable.";
        },
      },
      health_isf_status: {
        endpoint: "/summarize",
        body: { summary_type: "health_isf_dispatch", mode: "dispatch_supervisor" },
        extract: function (r) {
          return String(r.summary || "") + (Array.isArray(r.highlights) && r.highlights.length ? "\nHighlights: " + r.highlights.join(" | ") : "");
        },
      },
      deployment_readiness: {
        endpoint: "/review-report",
        body: {
          mode: "engineering_director",
          report_title: "Deployment Readiness Snapshot",
          report_text: "Review deployment readiness with focus on tenant isolation, endpoint stability, workflow resilience, and production safety controls.",
        },
        extract: function (r) {
          const risks = Array.isArray(r.risks) ? r.risks : [];
          const actions = Array.isArray(r.recommended_actions) ? r.recommended_actions : [];
          return String(r.executive_summary || "") + (risks.length ? "\nRisks: " + risks.join(" | ") : "") + (actions.length ? "\nActions: " + actions.join(" | ") : "");
        },
      },
    };

    const config = map[action];
    if (!config) return;

    try {
      setBusy(els, true);
      setOutput(els, "Awaiting AI orchestration response...");
      runtime.lastActionAt = stampNow();
      runtime.lastCompletedAction = null;
      runtime.lastFailedAction = null;
      const actionId = nextActionId(action);
      const result = await authJson(NOVA_API + config.endpoint, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        actionId: actionId,
        body: JSON.stringify(Object.assign({}, config.body, currentOrganizationId() ? { organization_id: currentOrganizationId() } : {})),
      });
      setOutput(els, config.extract(result));
      runtime.lastCompletedAction = action;
      runtime.lastApiError = null;
      runtime.lastActionAt = stampNow();
      refreshStatus(els);
    } catch (error) {
      runtime.lastFailedAction = action;
      runtime.lastApiError = String(error && error.message ? error.message : error);
      runtime.lastActionAt = stampNow();
      setOutput(els, normalizeExecutionError(error));
    } finally {
      setBusy(els, false);
    }
  }

  function bind(els) {
    if (els.askButton && els.askInput) {
      els.askButton.addEventListener("click", function () {
        askNova(els, els.askInput.value);
      });
      els.askInput.addEventListener("keydown", function (event) {
        if (event.key === "Enter") {
          event.preventDefault();
          askNova(els, els.askInput.value);
        }
      });
    }

    els.actions.forEach(function (button) {
      button.addEventListener("click", function () {
        const action = button.getAttribute("data-nova-action");
        runAction(els, String(action || ""));
      });
    });
  }

  function init() {
    const els = getEls();
    if (!els.panel) return;
    bind(els);
    refreshStatus(els);
    startHeartbeat();
  }

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", init);
  } else {
    init();
  }

  window.AmiCorNova = {
    init: init,
    refresh: function () {
      const els = getEls();
      refreshStatus(els);
    },
    getRuntimeStatus: function () {
      const hasSession = !!(window.AmiCorSession && typeof window.AmiCorSession.isActive === "function" && window.AmiCorSession.isActive());
      const tokenPresent = !!(window.AmiCorSession && typeof window.AmiCorSession.getAccessToken === "function" && window.AmiCorSession.getAccessToken());
      return {
        busy: !!runtime.busy,
        pendingRequests: runtime.pendingRequests,
        activeOrganizationId: runtime.activeOrganizationId || currentOrganizationId() || null,
        lastRequestPath: runtime.lastRequestPath,
        lastCompletedAction: runtime.lastCompletedAction,
        lastFailedAction: runtime.lastFailedAction,
        lastApiError: runtime.lastApiError,
        lastActionAt: runtime.lastActionAt,
        lastResponseAt: runtime.lastResponseAt,
        lastStreamPhase: runtime.lastStreamPhase,
        lastActionId: runtime.lastActionId,
        busySinceAt: runtime.busySinceAt,
        actionEvents: runtime.actionEvents.slice(),
        continuityBrief: runtime.continuityBrief,
        assistanceRecommendations: runtime.assistanceRecommendations.slice(),
        hasSession: hasSession,
        tokenPresent: tokenPresent,
      };
    },
  };
})();
