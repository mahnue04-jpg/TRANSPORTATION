"use strict";

const net = require("net");

const { createSecurityError } = require("./pathSanitizer");

function isPrivateIPv4(hostname) {
  const parts = hostname.split(".").map(function (part) { return Number(part); });
  if (parts.length !== 4 || parts.some(function (part) { return !Number.isInteger(part) || part < 0 || part > 255; })) {
    return false;
  }
  const first = parts[0];
  const second = parts[1];
  return first === 10 ||
    first === 127 ||
    (first === 169 && second === 254) ||
    (first === 172 && second >= 16 && second <= 31) ||
    (first === 192 && second === 168);
}

function isPrivateIPv6(hostname) {
  const normalized = hostname.toLowerCase();
  return normalized === "::1" || normalized.startsWith("fe80:") || normalized.startsWith("fc") || normalized.startsWith("fd");
}

function isInternalHostname(hostname) {
  const normalized = String(hostname || "").toLowerCase();
  if (!normalized) {
    return true;
  }
  if (normalized === "localhost" || normalized.endsWith(".localhost") || normalized.endsWith(".local")) {
    return true;
  }
  if (net.isIP(normalized) === 4) {
    return isPrivateIPv4(normalized);
  }
  if (net.isIP(normalized) === 6) {
    return isPrivateIPv6(normalized);
  }
  return false;
}

function isAllowedDomain(hostname, allowlist) {
  const list = Array.isArray(allowlist) ? allowlist : [];
  if (list.length === 0) {
    return false;
  }
  const normalized = String(hostname || "").toLowerCase();
  return list.some(function (item) {
    const candidate = String(item || "").toLowerCase();
    return candidate === normalized || normalized.endsWith("." + candidate);
  });
}

function validateDomain(targetUrl, options) {
  const opts = options || {};
  let parsed;

  try {
    parsed = new URL(targetUrl);
  } catch (err) {
    throw createSecurityError("invalid-url", "Target URL is invalid", { targetUrl: targetUrl });
  }

  if (parsed.protocol !== "http:" && parsed.protocol !== "https:") {
    throw createSecurityError("invalid-protocol", "Only HTTP and HTTPS are allowed", {
      protocol: parsed.protocol,
    });
  }

  if (isInternalHostname(parsed.hostname)) {
    throw createSecurityError("internal-host-blocked", "Local and internal network targets are blocked", {
      hostname: parsed.hostname,
    });
  }

  if (!isAllowedDomain(parsed.hostname, opts.allowlist || [])) {
    throw createSecurityError("domain-not-allowlisted", "Domain is not allowlisted", {
      hostname: parsed.hostname,
      allowlist: opts.allowlist || [],
    });
  }

  return parsed;
}

module.exports = {
  isInternalHostname: isInternalHostname,
  isAllowedDomain: isAllowedDomain,
  validateDomain: validateDomain,
};