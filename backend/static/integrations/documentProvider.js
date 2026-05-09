"use strict";

/**
 * documentProvider.js — Cloud document provider abstraction.
 * Plug in Google Drive, Dropbox, OneDrive, S3, etc.
 */

const {
  INTEGRATION_TYPES,
  INTEGRATION_ERRORS,
  uid,
  clone,
  createIntegrationError,
  createIntegrationSuccess,
} = require("./integrationSchemas");

const DOC_TYPES = {
  file:      "file",
  folder:    "folder",
  link:      "link",
  shortcut:  "shortcut",
};

function createDocumentRecord(options) {
  var opts = options || {};
  return {
    id:          opts.id || uid("doc"),
    name:        opts.name || "Untitled",
    type:        opts.type || DOC_TYPES.file,
    mimeType:    opts.mimeType || "application/octet-stream",
    size:        opts.size || 0,
    parentId:    opts.parentId || null,
    content:     opts.content !== undefined ? opts.content : null, // Buffer or string for mock
    tags:        clone(opts.tags || []),
    metadata:    clone(opts.metadata || {}),
    createdAt:   Date.now(),
    updatedAt:   Date.now(),
    deletedAt:   null,
  };
}

function createDocumentProvider(options) {
  var config = Object.assign(
    {
      provider: null,  // { upload, download, getMetadata, listFiles, deleteFile, moveFile, [healthCheck] }
      maxFileSizeBytes: 100 * 1024 * 1024, // 100 MB
    },
    options || {}
  );

  var documentStore = new Map();

  async function upload(options) {
    var opts = options || {};
    if (!opts.name) return createIntegrationError(INTEGRATION_ERRORS.invalidConfig, "File name is required");
    if (opts.size && opts.size > config.maxFileSizeBytes) {
      return createIntegrationError(INTEGRATION_ERRORS.invalidConfig, "File exceeds max size limit");
    }

    if (config.provider) {
      try {
        var result = await config.provider.upload(opts);
        if (result && result.ok === false) return createIntegrationError(INTEGRATION_ERRORS.providerError, result.message);
        return createIntegrationSuccess({ document: result.document || result });
      } catch (err) {
        return createIntegrationError(INTEGRATION_ERRORS.providerError, (err && err.message) || "upload failed");
      }
    }

    var doc = createDocumentRecord(opts);
    documentStore.set(doc.id, doc);
    return createIntegrationSuccess({ document: clone(doc) });
  }

  async function download(documentId) {
    if (config.provider) {
      try {
        var result = await config.provider.download(documentId);
        if (result && result.ok === false) return createIntegrationError(INTEGRATION_ERRORS.notFound, result.message);
        return createIntegrationSuccess({ content: result.content, document: result.document });
      } catch (err) {
        return createIntegrationError(INTEGRATION_ERRORS.providerError, (err && err.message) || "download failed");
      }
    }
    var doc = documentStore.get(documentId);
    if (!doc) return createIntegrationError(INTEGRATION_ERRORS.notFound, "Document not found: " + documentId);
    return createIntegrationSuccess({ content: doc.content, document: clone(doc) });
  }

  async function getMetadata(documentId) {
    if (config.provider) {
      try {
        var result = await config.provider.getMetadata(documentId);
        if (result && result.ok === false) return createIntegrationError(INTEGRATION_ERRORS.notFound, result.message);
        return createIntegrationSuccess({ document: result.document || result });
      } catch (err) {
        return createIntegrationError(INTEGRATION_ERRORS.providerError, (err && err.message) || "getMetadata failed");
      }
    }
    var doc = documentStore.get(documentId);
    if (!doc || doc.deletedAt) return createIntegrationError(INTEGRATION_ERRORS.notFound, "Document not found: " + documentId);
    var meta = clone(doc);
    delete meta.content;
    return createIntegrationSuccess({ document: meta });
  }

  async function listFiles(filters) {
    if (config.provider) {
      try {
        var result = await config.provider.listFiles(filters);
        if (result && result.ok === false) return createIntegrationError(INTEGRATION_ERRORS.providerError, result.message);
        return createIntegrationSuccess({ documents: result.documents || [] });
      } catch (err) {
        return createIntegrationError(INTEGRATION_ERRORS.providerError, (err && err.message) || "listFiles failed");
      }
    }
    var opts = filters || {};
    var docs = Array.from(documentStore.values()).filter(function (d) { return !d.deletedAt; });
    if (opts.parentId !== undefined) docs = docs.filter(function (d) { return d.parentId === opts.parentId; });
    if (opts.mimeType) docs = docs.filter(function (d) { return d.mimeType === opts.mimeType; });
    if (opts.type) docs = docs.filter(function (d) { return d.type === opts.type; });
    docs.sort(function (a, b) { return b.updatedAt - a.updatedAt; });
    return createIntegrationSuccess({ documents: docs.map(function (d) { var m = clone(d); delete m.content; return m; }) });
  }

  async function deleteFile(documentId) {
    if (config.provider) {
      try {
        var result = await config.provider.deleteFile(documentId);
        if (result && result.ok === false) return createIntegrationError(INTEGRATION_ERRORS.notFound, result.message);
        return createIntegrationSuccess({ documentId });
      } catch (err) {
        return createIntegrationError(INTEGRATION_ERRORS.providerError, (err && err.message) || "deleteFile failed");
      }
    }
    var doc = documentStore.get(documentId);
    if (!doc) return createIntegrationError(INTEGRATION_ERRORS.notFound, "Document not found: " + documentId);
    doc.deletedAt = Date.now();
    return createIntegrationSuccess({ documentId });
  }

  async function moveFile(documentId, newParentId) {
    if (config.provider) {
      try {
        var result = await config.provider.moveFile(documentId, newParentId);
        if (result && result.ok === false) return createIntegrationError(INTEGRATION_ERRORS.providerError, result.message);
        return createIntegrationSuccess({ document: result.document || result });
      } catch (err) {
        return createIntegrationError(INTEGRATION_ERRORS.providerError, (err && err.message) || "moveFile failed");
      }
    }
    var doc = documentStore.get(documentId);
    if (!doc) return createIntegrationError(INTEGRATION_ERRORS.notFound, "Document not found: " + documentId);
    doc.parentId = newParentId;
    doc.updatedAt = Date.now();
    return createIntegrationSuccess({ document: clone(doc) });
  }

  async function healthCheck() {
    if (config.provider && typeof config.provider.healthCheck === "function") {
      try {
        var r = await config.provider.healthCheck();
        return createIntegrationSuccess({ healthy: !r || r.ok !== false });
      } catch (_) {
        return createIntegrationSuccess({ healthy: false });
      }
    }
    return createIntegrationSuccess({ healthy: true });
  }

  return {
    name:         "document",
    type:         INTEGRATION_TYPES.document,
    capabilities: ["upload", "download", "getMetadata", "listFiles", "deleteFile", "moveFile", "healthCheck"],
    DOC_TYPES,
    upload,
    download,
    getMetadata,
    listFiles,
    deleteFile,
    moveFile,
    healthCheck,
  };
}

module.exports = { createDocumentProvider, DOC_TYPES };
