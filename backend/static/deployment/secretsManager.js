"use strict";

/**
 * secretsManager.js — AES-256-GCM encrypted in-memory secrets store.
 * Never logs plaintext secrets.
 */

const crypto = require("crypto");

const ALGORITHM = "aes-256-gcm";
const IV_LENGTH = 12;
const TAG_LENGTH = 16;

function deriveMasterKey(keyInput) {
  if (Buffer.isBuffer(keyInput) && keyInput.length === 32) return keyInput;
  if (typeof keyInput === "string") {
    return crypto.createHash("sha256").update(keyInput).digest();
  }
  // Generate random key if none provided (ephemeral — lost on restart)
  return crypto.randomBytes(32);
}

function encrypt(plaintext, masterKey) {
  var iv = crypto.randomBytes(IV_LENGTH);
  var cipher = crypto.createCipheriv(ALGORITHM, masterKey, iv, { authTagLength: TAG_LENGTH });
  var encrypted = Buffer.concat([cipher.update(String(plaintext), "utf8"), cipher.final()]);
  var tag = cipher.getAuthTag();
  // Store: iv(12) + tag(16) + ciphertext
  return Buffer.concat([iv, tag, encrypted]).toString("base64");
}

function decrypt(ciphertext, masterKey) {
  var buf = Buffer.from(ciphertext, "base64");
  var iv  = buf.subarray(0, IV_LENGTH);
  var tag = buf.subarray(IV_LENGTH, IV_LENGTH + TAG_LENGTH);
  var enc = buf.subarray(IV_LENGTH + TAG_LENGTH);
  var decipher = crypto.createDecipheriv(ALGORITHM, masterKey, iv, { authTagLength: TAG_LENGTH });
  decipher.setAuthTag(tag);
  return Buffer.concat([decipher.update(enc), decipher.final()]).toString("utf8");
}

function createSecretsManager(options) {
  var opts = options || {};
  var masterKey = deriveMasterKey(opts.masterKey);

  // name → { encrypted, rotatedAt }
  var store = new Map();
  // audit log (no plaintext ever)
  var auditLog = [];

  function audit(action, name) {
    auditLog.push({ action, name, timestamp: Date.now() });
    if (auditLog.length > 500) auditLog.shift();
  }

  function setSecret(name, value) {
    if (!name || typeof name !== "string") return { ok: false, error: "Secret name must be a non-empty string" };
    if (value === undefined || value === null) return { ok: false, error: "Secret value must not be null" };
    var encrypted = encrypt(String(value), masterKey);
    store.set(name, { encrypted, rotatedAt: Date.now() });
    audit("set", name);
    return { ok: true };
  }

  function getSecret(name) {
    var record = store.get(name);
    if (!record) return { ok: false, error: "Secret not found: " + name };
    try {
      var value = decrypt(record.encrypted, masterKey);
      audit("get", name);
      return { ok: true, value };
    } catch (err) {
      return { ok: false, error: "Decryption failed for secret: " + name };
    }
  }

  function hasSecret(name) { return store.has(name); }

  function deleteSecret(name) {
    if (!store.has(name)) return { ok: false, error: "Secret not found: " + name };
    store.delete(name);
    audit("delete", name);
    return { ok: true };
  }

  function rotateSecret(name, newValue) {
    if (!store.has(name)) return { ok: false, error: "Secret not found: " + name };
    if (newValue === undefined || newValue === null) return { ok: false, error: "New value must not be null" };
    var encrypted = encrypt(String(newValue), masterKey);
    store.set(name, { encrypted, rotatedAt: Date.now() });
    audit("rotate", name);
    return { ok: true };
  }

  function listSecretNames() { return Array.from(store.keys()); }

  function secretCount() { return store.size; }

  function getAuditLog() { return auditLog.slice(); }

  return {
    setSecret,
    getSecret,
    hasSecret,
    deleteSecret,
    rotateSecret,
    listSecretNames,
    secretCount,
    getAuditLog,
  };
}

module.exports = { createSecretsManager };
