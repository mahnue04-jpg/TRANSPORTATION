"use strict";

/**
 * emailProvider.js — Email provider abstraction.
 * Plug in any backend: SMTP, SendGrid, SES, Mailgun, etc.
 */

const {
  INTEGRATION_TYPES,
  INTEGRATION_ERRORS,
  uid,
  clone,
  createIntegrationError,
  createIntegrationSuccess,
} = require("./integrationSchemas");

function createEmailProvider(options) {
  var config = Object.assign(
    {
      provider: null,   // async adapter: { sendEmail(message), [connect], [healthCheck] }
      from:     null,   // default sender
      replyTo:  null,
      trackingEnabled: false,
    },
    options || {}
  );

  // In-memory sent log (useful for test/mock providers)
  var sentLog = [];

  function validateMessage(message) {
    if (!message) return { ok: false, message: "Message is required" };
    if (!message.to || (Array.isArray(message.to) && message.to.length === 0)) {
      return { ok: false, message: "Recipient (to) is required" };
    }
    if (!message.subject || !String(message.subject).trim()) {
      return { ok: false, message: "Subject is required" };
    }
    if (!message.text && !message.html) {
      return { ok: false, message: "Message body (text or html) is required" };
    }
    return { ok: true };
  }

  async function send(message) {
    var validation = validateMessage(message);
    if (!validation.ok) {
      return createIntegrationError(INTEGRATION_ERRORS.invalidConfig, validation.message);
    }

    var envelope = {
      id:        uid("email"),
      to:        Array.isArray(message.to) ? message.to : [message.to],
      cc:        message.cc ? (Array.isArray(message.cc) ? message.cc : [message.cc]) : [],
      bcc:       message.bcc ? (Array.isArray(message.bcc) ? message.bcc : [message.bcc]) : [],
      from:      message.from || config.from || "noreply@amicore.app",
      replyTo:   message.replyTo || config.replyTo || null,
      subject:   message.subject,
      text:      message.text || null,
      html:      message.html || null,
      metadata:  clone(message.metadata || {}),
      sentAt:    null,
    };

    if (!config.provider) {
      // Offline/mock mode
      envelope.sentAt = Date.now();
      sentLog.push(clone(envelope));
      return createIntegrationSuccess({ messageId: envelope.id, envelope: clone(envelope) });
    }

    try {
      var result = await config.provider.sendEmail(envelope);
      if (result && result.ok === false) {
        return createIntegrationError(INTEGRATION_ERRORS.providerError, result.message || "Send failed");
      }
      envelope.sentAt = Date.now();
      sentLog.push(clone(envelope));
      return createIntegrationSuccess({
        messageId: (result && result.messageId) || envelope.id,
        envelope: clone(envelope),
      });
    } catch (err) {
      return createIntegrationError(INTEGRATION_ERRORS.providerError, (err && err.message) || "Send failed");
    }
  }

  async function sendBatch(messages) {
    if (!Array.isArray(messages) || messages.length === 0) {
      return createIntegrationError(INTEGRATION_ERRORS.invalidConfig, "messages must be a non-empty array");
    }
    var results = await Promise.all(messages.map(function (m) { return send(m); }));
    var failed = results.filter(function (r) { return !r.ok; }).length;
    return createIntegrationSuccess({ total: messages.length, sent: messages.length - failed, failed, results });
  }

  function getSentLog() { return sentLog.slice(); }
  function clearSentLog() { sentLog = []; }

  async function healthCheck() {
    if (!config.provider) return createIntegrationSuccess({ healthy: true, mode: "offline" });
    if (typeof config.provider.healthCheck === "function") {
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
    name:          "email",
    type:          INTEGRATION_TYPES.email,
    capabilities:  ["send", "sendBatch", "healthCheck"],
    send,
    sendBatch,
    healthCheck,
    getSentLog,
    clearSentLog,
  };
}

module.exports = { createEmailProvider };
