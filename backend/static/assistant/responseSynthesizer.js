"use strict";

const { createReasoningStep } = require("./assistantSchemas");

function chunkText(text, size) {
  var out = [];
  var source = String(text || "");
  var chunkSize = Math.max(10, size || 120);
  for (var i = 0; i < source.length; i += chunkSize) {
    out.push(source.slice(i, i + chunkSize));
  }
  return out;
}

function sanitizeText(text) {
  return String(text || "")
    .replace(/[\x00-\x08\x0B\x0C\x0E-\x1F]/g, "")
    .trim();
}

function summarizeWorkflow(workflowResult) {
  if (!workflowResult || !workflowResult.snapshot) {
    return {
      completed: 0,
      failed: 0,
      cancelled: 0,
      outputs: [],
    };
  }

  var tasks = Array.isArray(workflowResult.snapshot.tasks) ? workflowResult.snapshot.tasks : [];
  var outputs = [];
  var stats = { completed: 0, failed: 0, cancelled: 0 };

  for (var i = 0; i < tasks.length; i++) {
    if (tasks[i].status === "completed") {
      stats.completed += 1;
      outputs.push({ taskId: tasks[i].id, output: tasks[i].outputs || null });
    } else if (tasks[i].status === "failed") {
      stats.failed += 1;
    } else if (tasks[i].status === "cancelled") {
      stats.cancelled += 1;
    }
  }

  return {
    completed: stats.completed,
    failed: stats.failed,
    cancelled: stats.cancelled,
    outputs: outputs,
  };
}

function createResponseSynthesizer(options) {
  var config = Object.assign(
    {
      streamingEngine: null,
      safetyGuardrails: null,
      streamChunkSize: 100,
    },
    options || {}
  );

  function synthesize(input) {
    var source = input || {};
    var context = source.context || { raw: "" };
    var execution = source.execution || {};
    var summary = summarizeWorkflow(execution.workflowResult);

    var lines = [];
    lines.push("Execution status: " + (execution.workflowResult ? execution.workflowResult.status : "unknown"));
    lines.push("Completed tasks: " + summary.completed + ", Failed tasks: " + summary.failed + ", Cancelled tasks: " + summary.cancelled);

    if (summary.outputs.length > 0) {
      lines.push("Key outputs:");
      for (var i = 0; i < summary.outputs.length; i++) {
        var out = summary.outputs[i].output;
        var compact = sanitizeText(JSON.stringify(out));
        if (compact.length > 180) {
          compact = compact.slice(0, 180) + "...";
        }
        lines.push("- " + summary.outputs[i].taskId + ": " + compact);
      }
    }

    if (context.overflow) {
      lines.push("Note: context was truncated to remain within budget.");
    }

    if (context.memoryContext && context.memoryContext.context) {
      var memoryNote = sanitizeText(context.memoryContext.context);
      if (memoryNote) {
        lines.push("Memory context considered: " + memoryNote.slice(0, 140));
      }
    }

    var responseText = sanitizeText(lines.join("\n"));
    if (!responseText) {
      responseText = "Unable to synthesize response due to invalid execution output.";
    }

    var evidence = config.safetyGuardrails ? config.safetyGuardrails.validateEvidence(responseText, execution.workflowResult || {}) : { valid: true, issues: [] };
    if (!evidence.valid) {
      responseText = "Execution completed with limited confidence. Some response claims were removed due to insufficient evidence.";
    }

    return {
      text: responseText,
      reasoning: [createReasoningStep("responding", "Synthesized assistant response", { evidenceValid: evidence.valid })],
      evidence: evidence,
    };
  }

  function stream(response, streamOptions) {
    var options = streamOptions || {};
    var chunks = chunkText(response.text, config.streamChunkSize);

    for (var i = 0; i < chunks.length; i++) {
      if (typeof options.onChunk === "function") {
        options.onChunk(chunks[i]);
      }
      if (options.streamingSession && typeof options.streamingSession.appendChunk === "function") {
        options.streamingSession.appendChunk(chunks[i]);
      }
    }

    if (options.streamingSession && typeof options.streamingSession.flushFinalRender === "function") {
      options.streamingSession.flushFinalRender();
    }

    return chunks;
  }

  return {
    config: config,
    synthesize: synthesize,
    stream: stream,
  };
}

module.exports = {
  createResponseSynthesizer: createResponseSynthesizer,
};
