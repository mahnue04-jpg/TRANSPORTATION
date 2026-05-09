"use strict";

const { createAuthError, createAuthSuccess, AUTH_ERRORS, clone, uid } = require("./authSchemas");

var MAX_WORKFLOWS_PER_USER = 200;
var MAX_CONVERSATIONS_PER_USER = 500;

function createWorkflowRecord(input) {
  var source = input || {};
  return {
    id: String(source.id || uid("wf")),
    userId: String(source.userId || ""),
    name: String(source.name || "Untitled Workflow"),
    description: String(source.description || ""),
    templateId: source.templateId ? String(source.templateId) : null,
    capability: source.capability ? String(source.capability) : null,
    status: String(source.status || "saved"),
    plan: clone(source.plan || null),
    result: clone(source.result || null),
    tags: Array.isArray(source.tags) ? source.tags.slice() : [],
    createdAt: source.createdAt || Date.now(),
    updatedAt: source.updatedAt || Date.now(),
    metadata: clone(source.metadata || {}),
  };
}

function createConversationRecord(input) {
  var source = input || {};
  return {
    id: String(source.id || uid("conv")),
    userId: String(source.userId || ""),
    title: String(source.title || "New Conversation"),
    messages: Array.isArray(source.messages) ? clone(source.messages) : [],
    workflowId: source.workflowId ? String(source.workflowId) : null,
    tags: Array.isArray(source.tags) ? source.tags.slice() : [],
    createdAt: source.createdAt || Date.now(),
    updatedAt: source.updatedAt || Date.now(),
    metadata: clone(source.metadata || {}),
  };
}

function createWorkflowPersistence(options) {
  var config = Object.assign(
    {
      maxWorkflowsPerUser: MAX_WORKFLOWS_PER_USER,
      maxConversationsPerUser: MAX_CONVERSATIONS_PER_USER,
    },
    options || {}
  );

  // userId -> Map(workflowId -> record)
  var workflowsByUser = new Map();
  // userId -> Map(conversationId -> record)
  var conversationsByUser = new Map();

  function getUserWorkflows(userId) {
    if (!workflowsByUser.has(userId)) workflowsByUser.set(userId, new Map());
    return workflowsByUser.get(userId);
  }

  function getUserConversations(userId) {
    if (!conversationsByUser.has(userId)) conversationsByUser.set(userId, new Map());
    return conversationsByUser.get(userId);
  }

  // --- Workflows ---

  function saveWorkflow(input) {
    var opts = input || {};
    var userId = String(opts.userId || "");
    if (!userId) return createAuthError("missing_user_id", "userId is required");

    var store = getUserWorkflows(userId);
    if (store.size >= config.maxWorkflowsPerUser) {
      return createAuthError("limit_exceeded", "Maximum saved workflows reached");
    }

    var record = createWorkflowRecord(Object.assign({}, opts, { userId: userId }));
    store.set(record.id, record);
    return createAuthSuccess({ workflow: clone(record) });
  }

  function getWorkflow(userId, workflowId) {
    var uid = String(userId || "");
    var wid = String(workflowId || "");
    var store = getUserWorkflows(uid);
    var record = store.get(wid);
    if (!record) return createAuthError("not_found", "Workflow not found");
    return createAuthSuccess({ workflow: clone(record) });
  }

  function updateWorkflow(userId, workflowId, patch) {
    var uid = String(userId || "");
    var wid = String(workflowId || "");
    var store = getUserWorkflows(uid);
    var record = store.get(wid);
    if (!record) return createAuthError("not_found", "Workflow not found");

    var p = patch || {};
    if (p.name !== undefined) record.name = String(p.name || "").trim() || record.name;
    if (p.description !== undefined) record.description = String(p.description || "");
    if (p.status !== undefined) record.status = String(p.status);
    if (p.plan !== undefined) record.plan = clone(p.plan);
    if (p.result !== undefined) record.result = clone(p.result);
    if (Array.isArray(p.tags)) record.tags = p.tags.slice();
    if (p.metadata && typeof p.metadata === "object") Object.assign(record.metadata, p.metadata);
    record.updatedAt = Date.now();

    return createAuthSuccess({ workflow: clone(record) });
  }

  function deleteWorkflow(userId, workflowId) {
    var store = getUserWorkflows(String(userId || ""));
    var existed = store.delete(String(workflowId || ""));
    return createAuthSuccess({ deleted: existed });
  }

  function listWorkflows(userId, filter) {
    var store = getUserWorkflows(String(userId || ""));
    var results = [];
    store.forEach(function (record) {
      if (filter && filter.templateId && record.templateId !== filter.templateId) return;
      if (filter && filter.capability && record.capability !== filter.capability) return;
      if (filter && filter.status && record.status !== filter.status) return;
      results.push(clone(record));
    });
    results.sort(function (a, b) { return b.updatedAt - a.updatedAt; });
    return results;
  }

  // --- Conversations ---

  function saveConversation(input) {
    var opts = input || {};
    var userId = String(opts.userId || "");
    if (!userId) return createAuthError("missing_user_id", "userId is required");

    var store = getUserConversations(userId);
    if (store.size >= config.maxConversationsPerUser) {
      return createAuthError("limit_exceeded", "Maximum saved conversations reached");
    }

    var record = createConversationRecord(Object.assign({}, opts, { userId: userId }));
    store.set(record.id, record);
    return createAuthSuccess({ conversation: clone(record) });
  }

  function getConversation(userId, conversationId) {
    var store = getUserConversations(String(userId || ""));
    var record = store.get(String(conversationId || ""));
    if (!record) return createAuthError("not_found", "Conversation not found");
    return createAuthSuccess({ conversation: clone(record) });
  }

  function updateConversation(userId, conversationId, patch) {
    var store = getUserConversations(String(userId || ""));
    var record = store.get(String(conversationId || ""));
    if (!record) return createAuthError("not_found", "Conversation not found");

    var p = patch || {};
    if (p.title !== undefined) record.title = String(p.title || "").trim() || record.title;
    if (Array.isArray(p.messages)) record.messages = clone(p.messages);
    if (Array.isArray(p.tags)) record.tags = p.tags.slice();
    if (p.workflowId !== undefined) record.workflowId = p.workflowId ? String(p.workflowId) : null;
    if (p.metadata && typeof p.metadata === "object") Object.assign(record.metadata, p.metadata);
    record.updatedAt = Date.now();

    return createAuthSuccess({ conversation: clone(record) });
  }

  function appendMessage(userId, conversationId, message) {
    var store = getUserConversations(String(userId || ""));
    var record = store.get(String(conversationId || ""));
    if (!record) return createAuthError("not_found", "Conversation not found");
    record.messages.push(clone(message || {}));
    record.updatedAt = Date.now();
    return createAuthSuccess({ messageCount: record.messages.length });
  }

  function deleteConversation(userId, conversationId) {
    var store = getUserConversations(String(userId || ""));
    var existed = store.delete(String(conversationId || ""));
    return createAuthSuccess({ deleted: existed });
  }

  function listConversations(userId, filter) {
    var store = getUserConversations(String(userId || ""));
    var results = [];
    store.forEach(function (record) {
      if (filter && filter.workflowId && record.workflowId !== filter.workflowId) return;
      results.push(clone(record));
    });
    results.sort(function (a, b) { return b.updatedAt - a.updatedAt; });
    return results;
  }

  function deleteAllUserData(userId) {
    var uid = String(userId || "");
    workflowsByUser.delete(uid);
    conversationsByUser.delete(uid);
    return createAuthSuccess({ deleted: true });
  }

  return {
    saveWorkflow: saveWorkflow,
    getWorkflow: getWorkflow,
    updateWorkflow: updateWorkflow,
    deleteWorkflow: deleteWorkflow,
    listWorkflows: listWorkflows,
    saveConversation: saveConversation,
    getConversation: getConversation,
    updateConversation: updateConversation,
    appendMessage: appendMessage,
    deleteConversation: deleteConversation,
    listConversations: listConversations,
    deleteAllUserData: deleteAllUserData,
  };
}

module.exports = { createWorkflowPersistence };
