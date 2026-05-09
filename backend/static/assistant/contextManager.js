"use strict";

const { cloneAssistantValue } = require("./assistantSchemas");

function estimateTokens(text) {
  return Math.ceil(String(text || "").length / 4);
}

function createContextManager(options) {
  var config = Object.assign(
    {
      memoryManager: null,
      maxContextTokens: 500,
      maxMessages: 12,
    },
    options || {}
  );

  async function buildContext(input) {
    var source = input || {};
    var conversation = source.conversationState ? source.conversationState.snapshot() : { messages: [] };
    var userGoal = String(source.userGoal || "");
    var memoryContext = { context: "", overflow: false, consumedTokens: 0 };

    if (config.memoryManager && typeof config.memoryManager.assembleContext === "function") {
      try {
        var assembled = await config.memoryManager.assembleContext({ query: userGoal, maxTokens: Math.max(50, config.maxContextTokens - 120) });
        memoryContext = {
          context: assembled.context || "",
          overflow: !!(assembled.compressed && assembled.compressed.overflow),
          consumedTokens: assembled.compressed ? assembled.compressed.consumedTokens : estimateTokens(assembled.context || ""),
        };
      } catch (error) {
        memoryContext = {
          context: "memory-unavailable:" + error.message,
          overflow: false,
          consumedTokens: estimateTokens(error.message || ""),
        };
      }
    }

    var messages = Array.isArray(conversation.messages) ? conversation.messages.slice(-config.maxMessages) : [];
    var messageText = messages.map(function (msg) {
      return msg.role + ": " + msg.text;
    }).join("\n");

    var merged = [
      "Goal: " + userGoal,
      "Conversation:\n" + messageText,
      "Memory:\n" + memoryContext.context,
    ].join("\n\n");

    var tokenEstimate = estimateTokens(merged);
    var overflow = tokenEstimate > config.maxContextTokens || memoryContext.overflow;

    if (overflow) {
      var clipped = merged.slice(Math.max(0, merged.length - config.maxContextTokens * 4));
      return {
        raw: clipped,
        tokenEstimate: estimateTokens(clipped),
        overflow: true,
        memoryContext: memoryContext,
        messages: cloneAssistantValue(messages),
      };
    }

    return {
      raw: merged,
      tokenEstimate: tokenEstimate,
      overflow: false,
      memoryContext: memoryContext,
      messages: cloneAssistantValue(messages),
    };
  }

  return {
    config: config,
    buildContext: buildContext,
    estimateTokens: estimateTokens,
  };
}

module.exports = {
  createContextManager: createContextManager,
  estimateContextTokens: estimateTokens,
};
