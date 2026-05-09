"use strict";

function createToolError(code, message, details) {
  const error = new Error(message);
  error.name = "ToolAdapterError";
  error.code = code;
  error.details = details || {};
  error.toJSON = function () {
    return { name: error.name, code: error.code, message: error.message, details: error.details };
  };
  return error;
}

function withLifecycle(lifecycle, executor) {
  const hooks = lifecycle || {};
  return async function wrappedExecutor(args, ctx) {
    if (typeof hooks.onBeforeExecute === "function") {
      await hooks.onBeforeExecute(args, ctx);
    }
    try {
      const result = await executor(args, ctx);
      if (typeof hooks.onAfterExecute === "function") {
        await hooks.onAfterExecute(result, args, ctx);
      }
      return result;
    } catch (error) {
      if (typeof hooks.onError === "function") {
        await hooks.onError(error, args, ctx);
      }
      throw error;
    } finally {
      if (typeof hooks.onFinally === "function") {
        await hooks.onFinally(args, ctx);
      }
    }
  };
}

function chunkText(text, chunkSize) {
  const source = String(text || "");
  const size = Math.max(1, Number(chunkSize) || 1024);
  const chunks = [];
  for (let index = 0; index < source.length; index += size) {
    chunks.push(source.slice(index, index + size));
  }
  return chunks;
}

function paginate(items, page, pageSize) {
  const currentPage = Math.max(1, Number(page) || 1);
  const size = Math.max(1, Number(pageSize) || 10);
  const start = (currentPage - 1) * size;
  const data = items.slice(start, start + size);
  return {
    items: data,
    page: currentPage,
    pageSize: size,
    total: items.length,
    totalPages: Math.max(1, Math.ceil(items.length / size)),
  };
}

module.exports = {
  createToolError: createToolError,
  withLifecycle: withLifecycle,
  chunkText: chunkText,
  paginate: paginate,
};