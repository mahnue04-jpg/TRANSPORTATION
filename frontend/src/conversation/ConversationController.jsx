"use strict";

const { createConversationStore } = require("./ConversationStore");
const { createStreamingRenderer } = require("./StreamingRenderer");
const { buildWorkflowTimelineModel } = require("./WorkflowTimeline");
const { buildToolActivityModel } = require("./ToolActivityPanel");
const { buildMemoryContextModel } = require("./MemoryContextPanel");
const { buildExecutionFeedModel } = require("./ExecutionFeed");

function createDefaultAssistantAdapter(deps) {
  var input = deps || {};
  var assistantController = input.assistantController || null;

  if (!assistantController) {
    if (typeof window !== "undefined" && window.AmiCorAssistantController) {
      assistantController = window.AmiCorAssistantController;
    } else if (input.assistantFactory && typeof input.assistantFactory.createAssistantController === "function") {
      assistantController = input.assistantFactory.createAssistantController({
        runtime: input.runtime,
        memoryManager: input.memoryManager,
        orchestrator: input.orchestrator,
        streamingEngine: input.streamingEngine,
        permissions: input.permissions || [],
      });
    }
  }

  if (!assistantController) {
    throw new Error("Assistant controller adapter is unavailable");
  }

  return {
    run: function (request) {
      return assistantController.run(request);
    },
    interrupt: function (requestId, conversationId, reason) {
      return assistantController.interrupt(requestId, conversationId, reason);
    },
    snapshot: function (conversationId) {
      if (typeof assistantController.snapshot === "function") {
        return assistantController.snapshot(conversationId);
      }
      return null;
    },
  };
}

function createConversationController(options) {
  var config = Object.assign(
    {
      conversationStore: null,
      streamingRenderer: null,
      assistantAdapter: null,
      runtime: null,
      memoryManager: null,
      orchestrator: null,
      streamingEngine: null,
      permissions: [],
      assistantFactory: null,
    },
    options || {}
  );

  var store = config.conversationStore || createConversationStore({});
  var renderer = config.streamingRenderer || createStreamingRenderer({});
  var assistant = config.assistantAdapter || createDefaultAssistantAdapter(config);

  var activeRequest = null;
  var lastResult = null;

  function ensureSession(sessionId) {
    var snapshot = store.getSnapshot();
    if (sessionId) {
      store.activateSession(sessionId) || store.createSession({ id: sessionId, title: "Conversation" });
    } else if (!snapshot.activeSessionId) {
      store.createSession({ title: "Conversation" });
    }
  }

  async function submitGoal(input) {
    var request = input || {};
    ensureSession(request.conversationId);

    var requestRef = {
      id: request.id || ("req-" + Date.now()),
      conversationId: request.conversationId || store.getSnapshot().activeSessionId,
      startedAt: Date.now(),
    };

    store.appendMessage("user", request.userGoal || "", { requestId: requestRef.id });
    store.setAssistantState("interpreting", { requestId: requestRef.id });

    activeRequest = requestRef;

    renderer.reset();

    var result = await assistant.run({
      id: requestRef.id,
      conversationId: requestRef.conversationId,
      userGoal: request.userGoal || "",
      context: request.context || {},
      permissions: Array.isArray(request.permissions) && request.permissions.length > 0 ? request.permissions : config.permissions,
      timeoutBudgetMs: request.timeoutBudgetMs,
      maxDepth: request.maxDepth,
      onStreamChunk: function (chunk) {
        renderer.appendToken(chunk);
        store.upsertStreamingMessage("assistant", chunk, { requestId: requestRef.id });
      },
    });

    renderer.finalize();
    store.finalizeStreamingMessage({ requestId: requestRef.id, status: result.status });

    if (result && result.status) {
      store.setAssistantState(result.status, { requestId: requestRef.id });
    }

    if (result && result.workflowResult) {
      store.addWorkflowEntry(buildWorkflowTimelineModel(result.workflowResult));

      var toolRows = buildToolActivityModel(result.workflowResult.snapshot ? result.workflowResult.snapshot.tasks : []);
      for (var i = 0; i < toolRows.length; i++) {
        store.addToolActivity(toolRows[i]);
      }
    }

    if (result && result.planning && result.planning.planningContext) {
      store.setMemoryContext(buildMemoryContextModel({
        summary: result.planning.planningContext.memorySummary,
        indicators: ["retrieved memories: " + ((result.planning.planningContext.retrievedMemories || []).length)],
      }));
    }

    store.addExecutionEvent({
      at: Date.now(),
      type: "assistant-result",
      details: { status: result.status, requestId: requestRef.id },
    });

    lastResult = result;
    if (activeRequest && activeRequest.id === requestRef.id) {
      activeRequest = null;
    }

    return {
      result: result,
      snapshot: store.getSnapshot(),
      renderedText: renderer.snapshot().renderedText,
      executionFeed: buildExecutionFeedModel(store.getSnapshot().activeSession ? store.getSnapshot().activeSession.executionFeed : []),
    };
  }

  function cancelResponse(reason) {
    if (!activeRequest) {
      return { cancelled: false, reason: "no-active-request" };
    }
    renderer.interrupt();
    var interrupt = assistant.interrupt(activeRequest.id, activeRequest.conversationId, reason || "cancel-response");
    store.setAssistantState("interrupted", { requestId: activeRequest.id, reason: reason || "cancel-response" });
    store.addExecutionEvent({ at: Date.now(), type: "cancel-response", details: interrupt });
    return { cancelled: true, interrupt: interrupt };
  }

  function cancelWorkflow(reason) {
    if (!activeRequest) {
      return { cancelled: false, reason: "no-active-request" };
    }
    var interrupt = assistant.interrupt(activeRequest.id, activeRequest.conversationId, reason || "cancel-workflow");
    store.setAssistantState("interrupted", { requestId: activeRequest.id, reason: reason || "cancel-workflow" });
    store.addExecutionEvent({ at: Date.now(), type: "cancel-workflow", details: interrupt });
    return { cancelled: true, interrupt: interrupt };
  }

  async function retryWorkflow() {
    if (!lastResult || !lastResult.requestId) {
      return { retried: false, reason: "no-previous-result" };
    }

    var session = store.getSnapshot().activeSession;
    var userMessage = null;
    if (session && Array.isArray(session.messages)) {
      for (var i = session.messages.length - 1; i >= 0; i--) {
        if (session.messages[i].role === "user") {
          userMessage = session.messages[i];
          break;
        }
      }
    }

    if (!userMessage) {
      return { retried: false, reason: "no-user-goal" };
    }

    store.addExecutionEvent({ at: Date.now(), type: "retry-workflow", details: { previousRequestId: lastResult.requestId } });
    return submitGoal({
      id: "retry-" + Date.now(),
      conversationId: store.getSnapshot().activeSessionId,
      userGoal: userMessage.text,
      context: { retryOf: lastResult.requestId },
    });
  }

  function resumeConversation(sessionId) {
    var session = store.activateSession(sessionId);
    if (!session) {
      return { resumed: false, reason: "session-not-found" };
    }

    var recovered = store.recoverFromDesync({ forceTerminal: false, reason: "resume-conversation" });
    return {
      resumed: true,
      session: session,
      recovered: recovered,
      assistantSnapshot: assistant.snapshot ? assistant.snapshot(sessionId) : null,
    };
  }

  function listSavedSessions() {
    return store.listSessions();
  }

  function snapshot() {
    return {
      store: store.getSnapshot(),
      renderer: renderer.snapshot(),
      activeRequest: activeRequest,
      lastResult: lastResult,
    };
  }

  return {
    submitGoal: submitGoal,
    cancelResponse: cancelResponse,
    cancelWorkflow: cancelWorkflow,
    retryWorkflow: retryWorkflow,
    resumeConversation: resumeConversation,
    listSavedSessions: listSavedSessions,
    snapshot: snapshot,
    store: store,
    renderer: renderer,
  };
}

module.exports = {
  createConversationController: createConversationController,
};
