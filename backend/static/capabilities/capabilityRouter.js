"use strict";

const { createTaskPlanner, createWorkflowEngine } = require("../planning");
const {
  CAPABILITY_TYPES,
  CAPABILITY_STATUS,
  createCapabilityRequest,
  createCapabilityWorkflow,
  createCapabilityResult,
  isCapabilityType,
} = require("./capabilitySchemas");
const { listWorkflowTemplates, instantiateTemplate } = require("./workflowTemplates");
const { buildDocumentWorkflow } = require("./documentWorkflow");
const { buildTaskManagerWorkflow } = require("./taskManager");
const { buildSchedulingWorkflow } = require("./schedulingAssistant");
const { buildEmailWorkflow } = require("./emailAssistant");
const { buildReportWorkflow } = require("./reportGenerator");
const { buildBusinessSummaryWorkflow } = require("./businessSummarizer");
const { buildResearchWorkflow } = require("./researchAssistant");

function inferCapability(request) {
  if (isCapabilityType(request.capability)) {
    return request.capability;
  }
  var text = (request.goal || "").toLowerCase();
  if (/email|message|reply/.test(text)) return CAPABILITY_TYPES.emailAssistant;
  if (/schedule|meeting|calendar/.test(text)) return CAPABILITY_TYPES.schedulingAssistant;
  if (/report|dashboard|kpi/.test(text)) return CAPABILITY_TYPES.reportGenerator;
  if (/summary|summarize|business/.test(text)) return CAPABILITY_TYPES.businessSummarizer;
  if (/research|analyze|investigate/.test(text)) return CAPABILITY_TYPES.researchAssistant;
  if (/task|todo|action item/.test(text)) return CAPABILITY_TYPES.taskManager;
  if (/document|file|notes/.test(text)) return CAPABILITY_TYPES.documentWorkflow;
  if (request.templateId) return CAPABILITY_TYPES.workflowTemplates;
  return CAPABILITY_TYPES.researchAssistant;
}

function toStreamChunks(text) {
  var chunks = [];
  var value = String(text || "");
  var size = 120;
  for (var i = 0; i < value.length; i += size) {
    chunks.push(value.slice(i, i + size));
  }
  return chunks;
}

function createCapabilityRouter(options) {
  var config = Object.assign(
    {
      planner: null,
      workflowEngine: null,
      memoryManager: null,
      runtime: null,
      assistantAdapter: null,
      conversationAdapter: null,
      permissions: [],
      timeoutBudgetMs: 60000,
    },
    options || {}
  );

  var planner = config.planner || createTaskPlanner({
    runtime: config.runtime,
    memoryManager: config.memoryManager,
    permissions: config.permissions,
    timeoutBudgetMs: config.timeoutBudgetMs,
  });

  var workflowEngine = config.workflowEngine || createWorkflowEngine({
    runtime: config.runtime,
    memoryManager: config.memoryManager,
    permissions: config.permissions,
    timeoutBudgetMs: config.timeoutBudgetMs,
  });

  var history = [];
  var persistedWorkflows = Object.create(null);
  var active = Object.create(null);

  async function buildMemoryContext(request) {
    if (!config.memoryManager || typeof config.memoryManager.assembleContext !== "function") {
      return { memorySummary: "", retrievedMemories: [] };
    }
    try {
      var assembled = await config.memoryManager.assembleContext({ query: request.goal || "", maxTokens: 240 });
      var retrieval = await config.memoryManager.retrieve(request.goal || "", { limit: 8 });
      return {
        memorySummary: assembled.context || "",
        retrievedMemories: retrieval.items || [],
        overflow: !!(assembled.compressed && assembled.compressed.overflow),
      };
    } catch (error) {
      return { memorySummary: "memory-unavailable:" + error.message, retrievedMemories: [], overflow: false };
    }
  }

  function hasConflicts(request) {
    var goal = (request.goal || "").toLowerCase();
    return /cancel/.test(goal) && /(create|draft|build|generate|summarize|research)/.test(goal);
  }

  function builderFor(capability) {
    if (capability === CAPABILITY_TYPES.documentWorkflow) return buildDocumentWorkflow;
    if (capability === CAPABILITY_TYPES.taskManager) return buildTaskManagerWorkflow;
    if (capability === CAPABILITY_TYPES.schedulingAssistant) return buildSchedulingWorkflow;
    if (capability === CAPABILITY_TYPES.emailAssistant) return buildEmailWorkflow;
    if (capability === CAPABILITY_TYPES.reportGenerator) return buildReportWorkflow;
    if (capability === CAPABILITY_TYPES.businessSummarizer) return buildBusinessSummaryWorkflow;
    if (capability === CAPABILITY_TYPES.researchAssistant) return buildResearchWorkflow;
    return null;
  }

  function templateToPlan(template, memoryContext, request) {
    return {
      capability: CAPABILITY_TYPES.workflowTemplates,
      summary: "Instantiated workflow template: " + template.name,
      goal: request.goal || template.description,
      tasks: template.tasks,
      templateId: template.id,
      context: {
        memorySummary: memoryContext.memorySummary,
        retrievedMemories: memoryContext.retrievedMemories,
        templateContext: template.context || {},
      },
    };
  }

  async function persistRecord(record) {
    history.push(record);
    persistedWorkflows[record.workflow.id] = record;

    if (config.memoryManager && typeof config.memoryManager.addWorkflowMemory === "function") {
      await config.memoryManager.addWorkflowMemory("capability workflow persisted", {
        workflowId: record.workflow.id,
        capability: record.workflow.capability,
        status: record.status,
      });
    }

    if (config.conversationAdapter) {
      if (typeof config.conversationAdapter.addWorkflowEntry === "function") {
        config.conversationAdapter.addWorkflowEntry(record.workflow);
      }
      if (typeof config.conversationAdapter.addExecutionEvent === "function") {
        config.conversationAdapter.addExecutionEvent({
          at: Date.now(),
          type: "capability-workflow",
          details: { workflowId: record.workflow.id, capability: record.workflow.capability, status: record.status },
        });
      }
    }
  }

  async function runCapability(input) {
    var startedAt = Date.now();
    var request = createCapabilityRequest(input || {});

    if (!request.goal && !request.templateId) {
      return createCapabilityResult({
        requestId: request.id,
        capability: request.capability,
        status: CAPABILITY_STATUS.failed,
        summary: "Missing goal or template for capability execution",
        errors: [{ code: "malformed-input", message: "Goal or templateId is required" }],
        startedAt: startedAt,
      });
    }

    if (hasConflicts(request)) {
      return createCapabilityResult({
        requestId: request.id,
        capability: request.capability,
        status: CAPABILITY_STATUS.failed,
        summary: "Conflicting task directives detected",
        errors: [{ code: "conflicting-tasks", message: "Request contains both cancellation and execution directives" }],
        startedAt: startedAt,
      });
    }

    var capability = inferCapability(request);
    var memoryContext = await buildMemoryContext(request);
    var definition = null;

    if (capability === CAPABILITY_TYPES.workflowTemplates) {
      var template = instantiateTemplate(request.templateId, request.payload || {});
      if (!template) {
        return createCapabilityResult({
          requestId: request.id,
          capability: capability,
          status: CAPABILITY_STATUS.failed,
          summary: "Unknown workflow template",
          errors: [{ code: "template-not-found", message: "Template not found: " + request.templateId }],
          startedAt: startedAt,
        });
      }
      definition = templateToPlan(template, memoryContext, request);
    } else {
      var builder = builderFor(capability);
      definition = builder ? builder(request, memoryContext) : null;
    }

    if (!definition) {
      return createCapabilityResult({
        requestId: request.id,
        capability: capability,
        status: CAPABILITY_STATUS.failed,
        summary: "Unable to resolve capability workflow",
        errors: [{ code: "capability-not-implemented", message: "No builder for capability: " + capability }],
        startedAt: startedAt,
      });
    }

    var workflow = createCapabilityWorkflow({
      capability: capability,
      goal: definition.goal,
      tasks: definition.tasks,
      templateId: definition.templateId || request.templateId,
      context: Object.assign({}, definition.context || {}, {
        capabilitySummary: definition.summary,
        requestContext: request.context,
      }),
    });

    var planResult = await planner.plan({
      workflowId: workflow.id,
      goal: workflow.goal,
      tasks: workflow.tasks,
      context: workflow.context,
      timeoutBudgetMs: request.timeoutBudgetMs,
      maxDepth: 12,
    });

    if (!planResult.validation.valid) {
      return createCapabilityResult({
        requestId: request.id,
        workflowId: workflow.id,
        capability: capability,
        status: CAPABILITY_STATUS.failed,
        summary: "Planning validation failed for capability workflow",
        errors: planResult.validation.errors || [],
        memoryContext: memoryContext,
        startedAt: startedAt,
      });
    }

    active[workflow.id] = {
      requestId: request.id,
      interrupted: false,
      conversationId: request.conversationId || null,
    };

    var workflowResult = await workflowEngine.executeWorkflow(planResult.workflow, {
      timeoutBudgetMs: request.timeoutBudgetMs,
    });

    if (active[workflow.id] && active[workflow.id].interrupted) {
      workflowResult.status = CAPABILITY_STATUS.interrupted;
    }

    var status = workflowResult.status === "completed"
      ? CAPABILITY_STATUS.completed
      : workflowResult.status === "cancelled"
        ? CAPABILITY_STATUS.interrupted
        : CAPABILITY_STATUS.failed;

    var summary = definition.summary + " (status: " + status + ")";
    var chunks = toStreamChunks(summary + "\nWorkflow " + workflow.id + " processed " + (workflow.tasks || []).length + " tasks.");

    if (typeof input.onStreamChunk === "function") {
      for (var i = 0; i < chunks.length; i++) {
        input.onStreamChunk(chunks[i]);
      }
    }

    var result = createCapabilityResult({
      requestId: request.id,
      workflowId: workflow.id,
      capability: capability,
      status: status,
      workflowResult: workflowResult,
      summary: summary,
      streamedChunks: chunks,
      memoryContext: memoryContext,
      persisted: true,
      startedAt: startedAt,
      completedAt: Date.now(),
    });

    var record = {
      request: request,
      capability: capability,
      workflow: workflow,
      planning: planResult,
      status: status,
      result: result,
      persistedAt: Date.now(),
    };

    await persistRecord(record);
    delete active[workflow.id];
    return result;
  }

  function interruptWorkflow(workflowId, reason) {
    var entry = active[workflowId];
    if (!entry) {
      return { interrupted: false, reason: "workflow-not-active" };
    }
    entry.interrupted = true;
    workflowEngine.cancelWorkflow(workflowId, reason || "capability-interrupt");
    return { interrupted: true, workflowId: workflowId, reason: reason || "capability-interrupt" };
  }

  async function continueWorkflow(workflowId) {
    var record = persistedWorkflows[workflowId];
    if (!record) {
      return createCapabilityResult({
        workflowId: workflowId,
        status: CAPABILITY_STATUS.failed,
        summary: "Cannot continue unknown workflow",
        errors: [{ code: "workflow-not-found", message: "No persisted workflow found" }],
      });
    }

    var previous = record.result && record.result.workflowResult ? record.result.workflowResult : null;
    if (!previous || !previous.snapshot) {
      return createCapabilityResult({
        workflowId: workflowId,
        capability: record.capability,
        status: CAPABILITY_STATUS.failed,
        summary: "Workflow continuation requires prior snapshot",
        errors: [{ code: "workflow-no-snapshot", message: "Persisted workflow lacks execution snapshot" }],
      });
    }

    var continuedWorkflow = {
      id: workflowId + "-continue-" + Date.now(),
      goal: record.workflow.goal + " (continuation)",
      tasks: previous.snapshot.tasks,
      context: record.workflow.context,
      timeoutBudgetMs: record.request.timeoutBudgetMs,
    };

    var workflowResult = await workflowEngine.executeWorkflow(continuedWorkflow, {
      timeoutBudgetMs: record.request.timeoutBudgetMs,
    });

    var status = workflowResult.status === "completed" ? CAPABILITY_STATUS.completed : CAPABILITY_STATUS.failed;

    var result = createCapabilityResult({
      requestId: record.request.id,
      workflowId: continuedWorkflow.id,
      capability: record.capability,
      status: status,
      workflowResult: workflowResult,
      summary: "Workflow continuation result: " + status,
      memoryContext: record.result.memoryContext,
      persisted: true,
      startedAt: Date.now(),
      completedAt: Date.now(),
    });

    persistedWorkflows[continuedWorkflow.id] = {
      request: record.request,
      capability: record.capability,
      workflow: createCapabilityWorkflow({
        id: continuedWorkflow.id,
        capability: record.capability,
        goal: continuedWorkflow.goal,
        tasks: continuedWorkflow.tasks,
        context: continuedWorkflow.context,
      }),
      status: status,
      result: result,
      persistedAt: Date.now(),
    };

    return result;
  }

  function listPersistedWorkflows() {
    var ids = Object.keys(persistedWorkflows).sort();
    return ids.map(function (id) {
      var record = persistedWorkflows[id];
      return {
        workflowId: id,
        capability: record.capability,
        status: record.status,
        templateId: record.workflow.templateId || null,
        persistedAt: record.persistedAt,
      };
    });
  }

  return {
    runCapability: runCapability,
    interruptWorkflow: interruptWorkflow,
    continueWorkflow: continueWorkflow,
    listPersistedWorkflows: listPersistedWorkflows,
    listWorkflowTemplates: listWorkflowTemplates,
    history: history,
  };
}

module.exports = {
  createCapabilityRouter: createCapabilityRouter,
};
