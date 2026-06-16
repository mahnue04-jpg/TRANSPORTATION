"use strict";
/**
 * memoryManager.js — persistent user memory foundation.
 *
 * Features:
 * - Durable local storage persistence (refresh/browser/session safe)
 * - Runtime cache for fast reads
 * - Safe, concise memory context injection helper
 * - Non-destructive update API for future backend synchronization
 */
(function (global) {
  const STORAGE_PREFIX = "amicor_user_memory_v1";
  const MEMORY_VERSION = 1;
  const SHORT_TERM_LIMIT = 14;
  const SHORT_TERM_TTL_MS = 1000 * 60 * 60 * 24;
  const LONG_TERM_ENTRY_LIMITS = Object.freeze({
    preferences: 8,
    likes_dislikes: 10,
    goals: 8,
    recurring_interests: 8,
    active_projects: 6,
    assistant_notes: 8,
  });
  const MAX_LONG_TERM_TOTAL_ENTRIES = 40;
  const MAX_SHORT_TERM_ENTRY_CHARS = 320;
  const MEMORY_CONTEXT_MAX_CHARS = 420;
  const MAX_INJECTION_TOKEN_BUDGET = 120;
  const APPROX_CHARS_PER_TOKEN = 4;
  const POLICY_VIOLATION_NAME = "AssistantMemoryPolicyViolation";
  const POLICY_VIOLATION_CODE = "assistant-memory-policy-violation";
  const STATELESS_CLAIM_PATTERNS = [
    /i\s+(?:cannot|can't)\s+(?:remember|recall)\s+(?:previous|past)?\s*(?:conversations|interactions|messages)?/i,
    /i\s+don'?t\s+have\s+(?:any\s+)?information\s+about\s+you/i,
    /i\s+do\s+not\s+have\s+(?:any\s+)?information\s+about\s+you/i,
    /i\s+(?:cannot|can't)\s+access\s+personal\s+data/i,
    /i\s+do\s+not\s+have\s+access\s+to\s+personal\s+data/i,
    /i\s+don't\s+have\s+access\s+to\s+personal\s+data/i,
    /i\s+don't\s+have\s+the\s+capability\s+to\s+remember/i,
    /i\s+do\s+not\s+have\s+the\s+capability\s+to\s+remember/i,
    /i\s+don't\s+have\s+the\s+ability\s+to\s+remember/i,
    /i\s+do\s+not\s+have\s+the\s+ability\s+to\s+remember/i,
    /i\s+do\s+not\s+store\s+memory/i,
    /i\s+don't\s+store\s+memory/i,
    /i\s+don't\s+retain\s+memory/i,
    /i\s+do\s+not\s+retain\s+memory/i,
    /i\s+am\s+stateless/i,
    /this\s+is\s+a\s+fresh\s+conversation/i,
    /each\s+session\s+is\s+independent/i,
    /i\s+do\s+not\s+have\s+the\s+ability\s+to\s+recall/i,
    /between\s+conversations/i,
    /each\s+interaction\s+is\s+treated\s+independently/i,
    /i\s+won't?\s+retain\s+(?:any\s+)?details/i,
    /remember\s+personal\s+information\s+between\s+conversations/i,
    /(?:won't|will\s+not)\s+retain\s+(?:this|information)/i,
  ];
  const MEMORY_SELF_KNOWLEDGE_PATTERNS = [
    /what\s+do\s+you\s+remember/i,
    /what\s+do\s+you\s+know\s+about\s+me/i,
    /tell\s+me\s+what\s+you\s+remember/i,
    /what\s+are\s+my\s+preferences/i,
    /who\s+am\s+i/i,
    /what\s+have\s+i\s+told\s+you/i,
    /can\s+you\s+remember/i,
    /how\s+can\s+you\s+remember/i,
    /personal\s+information/i,
    /long[ -]?term\s+memory/i,
    /short[ -]?term\s+memory/i,
    /delete\s+memory/i,
    /clear\s+memory/i,
    /wipe\s+memory/i,
    /remove\s+memory/i,
    /what\s+can\s+i\s+do\s+as\s+(?:a\s+)?builder/i,
  ];
  const SELF_REFERENCE_ENTITY_PATTERNS = [
    /what\s+do\s+you\s+know\s+about\s+([a-z][a-z'\-\s]{0,80})[?.!\s]*$/i,
    /tell\s+me\s+about\s+([a-z][a-z'\-\s]{0,80})[?.!\s]*$/i,
    /who\s+is\s+([a-z][a-z'\-\s]{0,80})[?.!\s]*$/i,
  ];
  const EXPLICIT_OTHER_PERSON_PATTERNS = [
    /\banother\s+person\b/i,
    /\bsomeone\s+else\b/i,
    /\bnot\s+me\b/i,
    /\bother\s+than\s+me\b/i,
    /\bdifferent\s+person\b/i,
    /\bnot\s+the\s+user\b/i,
  ];
  const GENERIC_ENTITY_FALLBACK_PATTERNS = [
    /\bcan\s+refer\s+to\s+various\s+subjects\b/i,
    /\bmay\s+refer\s+to\b/i,
    /\bis\s+a\s+name\s+that\s+can\s+refer\s+to\b/i,
  ];
  const ARCHITECTURE_NARRATION_PATTERNS = [
    /short[_\-\s]?term[_\-\s]?memory/i,
    /long[_\-\s]?term[_\-\s]?memory/i,
    /memory\s+architecture/i,
    /memory\s+subsystem/i,
    /persist(?:ed|ence)?\s+by\s+user[_\-\s]?id/i,
    /storage\s+implementation/i,
  ];
  const DEFAULT_MEMORY = Object.freeze({
    memory_version: MEMORY_VERSION,
    short_term_memory: [],
    long_term_memory: {
      user_name: "",
      location: "",
      preferences: [],
      likes_dislikes: [],
      goals: [],
      recurring_interests: [],
      active_projects: [],
      assistant_notes: [],
    },
    updated_at: null,
  });

  let namespace = "default";
  let logger = null;
  let runtimeMemory = clone(DEFAULT_MEMORY);
  let runtimeMetrics = {
    loads: 0,
    saves: 0,
    injections: 0,
    hits: 0,
    misses: 0,
    clears: 0,
    corruptions: 0,
    lastRetrievalLatencyMs: 0,
  };
  let runtimeAuditState = {
    lastRoute: null,
    lastTerminalRoute: null,
    terminalCommits: 0,
    secondaryBlocks: 0,
    parityConfirms: 0,
    lastTrace: null,
  };

  function normalizeWhitespace(value) {
    return String(value || "").trim().replace(/\s+/g, " ");
  }

  function toLowerKey(value) {
    return normalizeWhitespace(value).toLowerCase();
  }

  function looksLikeDevRuntime() {
    try {
      if (typeof window === "undefined") {
        return typeof localStorage !== "undefined" && localStorage.getItem("amicor_diag_dev") === "1";
      }
      const host = String(window.location && window.location.hostname || "").toLowerCase();
      const isLocal = host === "localhost" || host === "127.0.0.1" || host === "0.0.0.0";
      const queryEnabled = /[?&]diag=1\b/.test(String(window.location && window.location.search || ""));
      const storageEnabled = localStorage.getItem("amicor_diag_dev") === "1";
      return isLocal || queryEnabled || storageEnabled;
    } catch (_) {
      return false;
    }
  }

  function emitMemoryQualityDiagnostic(event, fields) {
    if (!looksLikeDevRuntime()) return;
    emit(event, Object.assign({ category: "memory-quality" }, fields || {}));
  }

  function traceCanonicalRuntimeState(stage, fields) {
    const payload = Object.assign({
      stage,
      route: runtimeAuditState.lastRoute,
      terminalRoute: runtimeAuditState.lastTerminalRoute,
      terminalCommits: runtimeAuditState.terminalCommits,
      secondaryBlocks: runtimeAuditState.secondaryBlocks,
      parityConfirms: runtimeAuditState.parityConfirms,
    }, fields || {});
    runtimeAuditState.lastTrace = payload;
    emitMemoryQualityDiagnostic("[CANONICAL_RUNTIME_VIEW]", payload);
    return payload;
  }

  function markTerminalRoute(route, fields) {
    runtimeAuditState.lastRoute = route;
    runtimeAuditState.lastTerminalRoute = route;
    runtimeAuditState.terminalCommits += 1;
    traceCanonicalRuntimeState("terminal_route_committed", Object.assign({ route }, fields || {}));
    emitMemoryQualityDiagnostic("[FINAL_ROUTE_LOCKED]", Object.assign({ route }, fields || {}));
    emitMemoryQualityDiagnostic("[TERMINAL_ROUTE_COMMITTED]", Object.assign({ route }, fields || {}));
  }

  function blockSecondaryRoute(route, reason, fields) {
    runtimeAuditState.secondaryBlocks += 1;
    traceCanonicalRuntimeState("secondary_route_blocked", Object.assign({ route, reason }, fields || {}));
    emitMemoryQualityDiagnostic("[SECONDARY_ROUTE_BLOCKED]", Object.assign({ route, reason }, fields || {}));
  }

  function confirmRuntimeParity(route, fields) {
    runtimeAuditState.parityConfirms += 1;
    traceCanonicalRuntimeState("runtime_parity_confirmed", Object.assign({ route }, fields || {}));
    emitMemoryQualityDiagnostic("[RUNTIME_PARITY_CONFIRMED]", Object.assign({ route }, fields || {}));
  }

  function getRuntimeAuditReport() {
    const lastTrace = runtimeAuditState.lastTrace || {};
    const report = {
      lastRoute: runtimeAuditState.lastRoute,
      lastTerminalRoute: runtimeAuditState.lastTerminalRoute,
      terminalCommits: runtimeAuditState.terminalCommits,
      secondaryBlocks: runtimeAuditState.secondaryBlocks,
      parityConfirms: runtimeAuditState.parityConfirms,
      remainingRisks: [],
      lastTrace,
    };
    if (!runtimeAuditState.lastTerminalRoute) {
      report.remainingRisks.push("no_terminal_route_observed");
    }
    if (runtimeAuditState.secondaryBlocks === 0) {
      report.remainingRisks.push("secondary_routes_not_yet_observed");
    }
    if (runtimeAuditState.parityConfirms === 0) {
      report.remainingRisks.push("parity_not_yet_confirmed");
    }
    return report;
  }

  function canonicalizeName(name) {
    const raw = normalizeWhitespace(name);
    if (!raw) return "";
    return raw
      .split(" ")
      .map((token) => {
        const lower = token.toLowerCase();
        if (!lower) return "";
        return lower.charAt(0).toUpperCase() + lower.slice(1);
      })
      .filter(Boolean)
      .join(" ")
      .slice(0, 80);
  }

  function normalizePreferenceSeed(text) {
    return toLowerKey(String(text || "").replace(/^[\-\s]+|[\-\s]+$/g, ""));
  }

  function canonicalizePreference(preference) {
    const seed = normalizePreferenceSeed(preference);
    if (!seed) return "";

    const conciseSignal = /(concise|short|brief|minimal)/.test(seed);
    const detailedSignal = /(detailed|detail|depth|long form|long-form)/.test(seed);
    const bulletSignal = /(bullet|bullet-point|list)/.test(seed);
    const stepSignal = /(step by step|step-by-step)/.test(seed);
    const modeMatch = seed.match(/\bmode\s*[:=]\s*([a-z\-\s]+)/i);

    if (modeMatch && modeMatch[1]) {
      const mode = normalizeWhitespace(modeMatch[1]).toLowerCase();
      if (mode.includes("concise")) return "prefers concise replies";
      if (mode.includes("detailed")) return "prefers detailed replies";
      return "assistant mode " + mode;
    }
    if (conciseSignal) return "prefers concise replies";
    if (detailedSignal) return "prefers detailed replies";
    if (bulletSignal) return "prefers bullet-point replies";
    if (stepSignal) return "prefers step-by-step guidance";

    const normalized = seed
      .replace(/^(likes?|prefers?|wants?|enjoys?)\s+/i, "")
      .replace(/^(responses?|replies|answers?)\s+/i, "")
      .replace(/[.;,]+$/g, "")
      .trim();
    if (!normalized) return "";
    return "prefers " + normalized;
  }

  function canonicalizeAssistantMode(value) {
    const seed = normalizePreferenceSeed(value);
    if (!seed) return "";
    if (/(concise|brief|short)/.test(seed)) return "mode:concise";
    if (/(detailed|depth|long form|long-form)/.test(seed)) return "mode:detailed";
    if (/(friendly|warm)/.test(seed)) return "mode:friendly";
    if (/(professional|formal)/.test(seed)) return "mode:professional";
    if (/(creative|brainstorm)/.test(seed)) return "mode:creative";
    if (/(research|analytical)/.test(seed)) return "mode:research";
    return "";
  }

  function escapeRegExp(value) {
    return String(value || "").replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
  }

  function extractNameFromText(content) {
    const text = normalizeWhitespace(content || "");
    if (!text) return { value: "", priority: 0, reason: "" };

    const replacementPatterns = [
      /\b(?:actually|correction|update)\b[,:\s-]*(?:my\s+name\s+is|call\s+me)\s+([a-z][a-z'\-\s]{0,60})/i,
      /\bchange\s+my\s+name\s+to\s+([a-z][a-z'\-\s]{0,60})/i,
      /\bcall\s+me\s+([a-z][a-z'\-\s]{0,60})\s+(?:instead|from\s+now\s+on)\b/i,
    ];
    const directPatterns = [
      /\bmy\s+name\s+is\s+([a-z][a-z'\-\s]{0,60})/i,
      /\bcall\s+me\s+([a-z][a-z'\-\s]{0,60})/i,
    ];

    for (let i = 0; i < replacementPatterns.length; i += 1) {
      const match = text.match(replacementPatterns[i]);
      if (match && match[1]) {
        return { value: canonicalizeName(match[1]), priority: 3, reason: "explicit-replacement" };
      }
    }
    for (let i = 0; i < directPatterns.length; i += 1) {
      const match = text.match(directPatterns[i]);
      if (match && match[1]) {
        return { value: canonicalizeName(match[1]), priority: 2, reason: "direct-declaration" };
      }
    }
    return { value: "", priority: 0, reason: "" };
  }

  function extractPrimaryPreferenceSignal(content) {
    const text = normalizeWhitespace(content || "");
    if (!text) return { value: "", priority: 0, reason: "" };

    const lower = text.toLowerCase();
    const canonical = canonicalizePreference(text);
    if (!canonical) return { value: "", priority: 0, reason: "" };

    const mentionsReplacement = /\b(actually|change\s+my|instead|correction|update)\b/.test(lower);
    const mentionsDirect = /\b(i\s+prefer|prefer|call\s+it|keep\s+it)\b/.test(lower);

    let priority = 1;
    let reason = "inferred";
    if (mentionsReplacement) {
      priority = 3;
      reason = "explicit-replacement";
    } else if (mentionsDirect) {
      priority = 2;
      reason = "direct-declaration";
    }
    return { value: canonical, priority, reason };
  }

  function pickCanonicalCandidate(candidates) {
    if (!Array.isArray(candidates) || candidates.length === 0) {
      return null;
    }
    const sorted = candidates
      .slice()
      .sort((a, b) => {
        if ((b.priority || 0) !== (a.priority || 0)) return (b.priority || 0) - (a.priority || 0);
        return (b.sequence || 0) - (a.sequence || 0);
      });
    return sorted[0] || null;
  }

  function resolveCanonicalIdentityView(source, shortTermEntries) {
    const baseName = canonicalizeName(source.user_name || "");
    const nameCandidates = [];
    const prefCandidates = [];

    if (baseName) {
      nameCandidates.push({
        value: baseName,
        priority: 1,
        reason: "stored-long-term",
        sequence: 0,
      });
    }

    const shortEntries = Array.isArray(shortTermEntries) ? shortTermEntries : [];
    let sequence = 1;
    for (let i = 0; i < shortEntries.length; i += 1) {
      const entry = shortEntries[i] || {};
      if (String(entry.role || "").toLowerCase() !== "user") continue;
      const text = String(entry.content || "");

      const nameSignal = extractNameFromText(text);
      if (nameSignal.value) {
        nameCandidates.push({
          value: nameSignal.value,
          priority: nameSignal.priority,
          reason: nameSignal.reason,
          sequence,
        });
      }

      const prefSignal = extractPrimaryPreferenceSignal(text);
      if (prefSignal.value) {
        prefCandidates.push({
          value: prefSignal.value,
          priority: prefSignal.priority,
          reason: prefSignal.reason,
          sequence,
        });
      }
      sequence += 1;
    }

    const canonicalNameCandidate = pickCanonicalCandidate(nameCandidates);
    const canonicalName = canonicalNameCandidate && canonicalNameCandidate.value
      ? canonicalNameCandidate.value
      : baseName;
    const supersededNames = [];
    const seenNames = new Set();
    nameCandidates.forEach((item) => {
      const value = canonicalizeName(item && item.value);
      if (!value || value === canonicalName || seenNames.has(value)) return;
      seenNames.add(value);
      supersededNames.push(value);
    });

    const canonicalPrefCandidate = pickCanonicalCandidate(prefCandidates);
    const canonicalPrimaryPreference = canonicalPrefCandidate && canonicalPrefCandidate.value
      ? canonicalPrefCandidate.value
      : "";

    return {
      canonicalName,
      supersededNames,
      canonicalNameSource: canonicalNameCandidate ? canonicalNameCandidate.reason : "",
      canonicalPrimaryPreference,
      canonicalPreferenceSource: canonicalPrefCandidate ? canonicalPrefCandidate.reason : "",
    };
  }

  function splitKeyValueSummary(summary) {
    const map = {};
    String(summary || "")
      .split("|")
      .map((part) => normalizeWhitespace(part))
      .filter(Boolean)
      .forEach((part) => {
        const idx = part.indexOf("=");
        if (idx < 1) return;
        const key = part.slice(0, idx).trim().toLowerCase();
        const value = part.slice(idx + 1).trim();
        if (!key || !value) return;
        map[key] = value;
      });
    return map;
  }

  function normalizeReplaySafeShortTerm(entries) {
    const ordered = sanitizeShortTerm(entries || []);
    const out = [];
    let previousKey = null;
    for (let i = 0; i < ordered.length; i += 1) {
      const entry = ordered[i];
      const key = String(entry.role || "") + "::" + toLowerKey(entry.content || "");
      if (previousKey && previousKey === key) {
        emitMemoryQualityDiagnostic("[DUPLICATE_REMOVED]", {
          scope: "replay-runtime-view",
          duplicateType: "short_term_contiguous",
        });
        continue;
      }
      previousKey = key;
      out.push(entry);
    }
    return out;
  }

  function extractModesFromLongTerm(longTerm) {
    const seeds = [];
    (longTerm.preferences || []).forEach((item) => seeds.push(item));
    (longTerm.assistant_notes || []).forEach((item) => seeds.push(item));
    const out = [];
    const seen = new Set();
    seeds.forEach((seed) => {
      const mode = canonicalizeAssistantMode(seed);
      if (!mode || seen.has(mode)) return;
      seen.add(mode);
      out.push(mode);
    });
    return out;
  }

  function resolvePreferenceConflicts(preferences, shortTermEntries, canonicalPrimaryPreference) {
    const list = Array.isArray(preferences) ? preferences.slice() : [];
    const hasConcise = list.indexOf("prefers concise replies") >= 0;
    const hasDetailed = list.indexOf("prefers detailed replies") >= 0;
    if (!hasConcise || !hasDetailed) {
      return {
        preferences: list,
        supersededPreferences: [],
        winner: canonicalPrimaryPreference || "",
      };
    }

    let winner = canonicalPrimaryPreference || null;
    for (let i = (shortTermEntries || []).length - 1; i >= 0; i -= 1) {
      const content = toLowerKey(shortTermEntries[i] && shortTermEntries[i].content);
      if (!content) continue;
      if (/(concise|brief|short)/.test(content)) {
        winner = "prefers concise replies";
        break;
      }
      if (/(detailed|detail|depth|long form|long-form)/.test(content)) {
        winner = "prefers detailed replies";
        break;
      }
    }
    if (!winner) {
      winner = list.lastIndexOf("prefers detailed replies") > list.lastIndexOf("prefers concise replies")
        ? "prefers detailed replies"
        : "prefers concise replies";
    }
    const loser = winner === "prefers concise replies" ? "prefers detailed replies" : "prefers concise replies";
    const filtered = list.filter((item) => item !== loser);
    emitMemoryQualityDiagnostic("[CANONICAL_PREFERENCE_APPLIED]", {
      scope: "conflict-resolution",
      winner,
      removed: loser,
    });
    return {
      preferences: filtered,
      supersededPreferences: [loser],
      winner,
    };
  }

  function compressLongTermRuntimeView(longTerm, shortTermEntries) {
    const source = longTerm || {};
    const identityState = resolveCanonicalIdentityView(source, shortTermEntries);
    const normalized = {
      user_name: identityState.canonicalName || canonicalizeName(source.user_name || ""),
      location: normalizeWhitespace(source.location || "").slice(0, 120),
      preferences: [],
      likes_dislikes: [],
      goals: [],
      recurring_interests: [],
      active_projects: [],
      assistant_notes: [],
      assistant_modes: [],
      identity_resolution: {
        canonical_name: identityState.canonicalName || "",
        canonical_name_source: identityState.canonicalNameSource || "",
        superseded_names: identityState.supersededNames || [],
        canonical_primary_preference: identityState.canonicalPrimaryPreference || "",
        canonical_preference_source: identityState.canonicalPreferenceSource || "",
        superseded_preferences: [],
      },
    };

    if (normalized.identity_resolution.canonical_name && source.user_name &&
        canonicalizeName(source.user_name) !== normalized.identity_resolution.canonical_name) {
      emitMemoryQualityDiagnostic("[CANONICAL_IDENTITY_UPDATED]", {
        scope: "name",
        from: canonicalizeName(source.user_name),
        to: normalized.identity_resolution.canonical_name,
        source: normalized.identity_resolution.canonical_name_source,
      });
    }
    if (normalized.identity_resolution.superseded_names.length > 0) {
      emitMemoryQualityDiagnostic("[IDENTITY_SUPERSEDED]", {
        scope: "name",
        canonical: normalized.identity_resolution.canonical_name,
        superseded: normalized.identity_resolution.superseded_names,
      });
      emitMemoryQualityDiagnostic("[STALE_MEMORY_EXCLUDED]", {
        scope: "name",
        excluded: normalized.identity_resolution.superseded_names,
      });
    }

    const prefSeen = new Set();
    normalizeList(source.preferences, LONG_TERM_ENTRY_LIMITS.preferences).forEach((item) => {
      const canonical = canonicalizePreference(item);
      if (!canonical) return;
      if (prefSeen.has(canonical)) {
        emitMemoryQualityDiagnostic("[DUPLICATE_REMOVED]", {
          scope: "preferences",
          duplicateType: "semantic",
          candidate: item,
        });
        return;
      }
      prefSeen.add(canonical);
      normalized.preferences.push(canonical);
      if (canonical !== normalizePreferenceSeed(item)) {
        emitMemoryQualityDiagnostic("[CANONICAL_PREFERENCE_APPLIED]", {
          scope: "preferences",
          original: item,
          canonical,
        });
      }
    });

    const preferenceResolution = resolvePreferenceConflicts(
      normalized.preferences,
      shortTermEntries,
      normalized.identity_resolution.canonical_primary_preference
    );
    normalized.preferences = (preferenceResolution.preferences || [])
      .slice(0, LONG_TERM_ENTRY_LIMITS.preferences);
    normalized.identity_resolution.superseded_preferences = preferenceResolution.supersededPreferences || [];
    if (preferenceResolution.winner && source.preferences && source.preferences.length > 0 &&
        source.preferences.indexOf(preferenceResolution.winner) < 0) {
      emitMemoryQualityDiagnostic("[CANONICAL_IDENTITY_UPDATED]", {
        scope: "primary-preference",
        to: preferenceResolution.winner,
        source: normalized.identity_resolution.canonical_preference_source || "conflict-resolution",
      });
    }
    if (normalized.identity_resolution.superseded_preferences.length > 0) {
      emitMemoryQualityDiagnostic("[IDENTITY_SUPERSEDED]", {
        scope: "primary-preference",
        canonical: preferenceResolution.winner || "",
        superseded: normalized.identity_resolution.superseded_preferences,
      });
      emitMemoryQualityDiagnostic("[STALE_MEMORY_EXCLUDED]", {
        scope: "primary-preference",
        excluded: normalized.identity_resolution.superseded_preferences,
      });
    }
    normalized.likes_dislikes = normalizeList(source.likes_dislikes, LONG_TERM_ENTRY_LIMITS.likes_dislikes);
    normalized.goals = normalizeList(source.goals, LONG_TERM_ENTRY_LIMITS.goals);
    normalized.recurring_interests = normalizeList(source.recurring_interests, LONG_TERM_ENTRY_LIMITS.recurring_interests);
    normalized.active_projects = normalizeList(source.active_projects, LONG_TERM_ENTRY_LIMITS.active_projects);
    normalized.assistant_notes = normalizeList(source.assistant_notes, LONG_TERM_ENTRY_LIMITS.assistant_notes)
      .map((item) => normalizeWhitespace(item).slice(0, 180));
    normalized.assistant_modes = extractModesFromLongTerm(normalized);

    return normalized;
  }

  function buildNormalizedRuntimeView(memory) {
    const base = sanitize(memory || runtimeMemory);
    const shortTerm = normalizeReplaySafeShortTerm(base.short_term_memory || []);
    const longTerm = compressLongTermRuntimeView(base.long_term_memory || {}, shortTerm);
    const view = {
      memory_version: base.memory_version,
      short_term_memory: shortTerm,
      long_term_memory: {
        user_name: longTerm.user_name,
        location: longTerm.location,
        preferences: longTerm.preferences,
        likes_dislikes: longTerm.likes_dislikes,
        goals: longTerm.goals,
        recurring_interests: longTerm.recurring_interests,
        active_projects: longTerm.active_projects,
        assistant_notes: longTerm.assistant_notes,
      },
      assistant_modes: longTerm.assistant_modes,
      identity_resolution: longTerm.identity_resolution,
      updated_at: base.updated_at,
    };
    emitMemoryQualityDiagnostic("[MEMORY_NORMALIZED]", {
      source: "runtime-view",
      shortTermCount: view.short_term_memory.length,
      preferenceCount: view.long_term_memory.preferences.length,
      assistantModeCount: view.assistant_modes.length,
      supersededNameCount: (view.identity_resolution && view.identity_resolution.superseded_names || []).length,
    });
    return view;
  }

  function normalizeAssistantSynthesisText(text, options) {
    const input = String(text || "").trim();
    if (!input) return input;
    const cfg = Object.assign({
      canonicalName: "",
      supersededNames: [],
      canonicalPrimaryPreference: "",
      supersededPreferences: [],
    }, options || {});

    const sentenceSplit = input
      .replace(/[\r\n]+/g, "\n")
      .replace(/([.!?])\s+/g, "$1\n")
      .split(/\n+/g)
      .map((s) => normalizeWhitespace(s))
      .filter(Boolean);
    const seen = new Set();
    const kept = [];
    for (let i = 0; i < sentenceSplit.length; i += 1) {
      const sentence = sentenceSplit[i];
      const key = sentence.toLowerCase().replace(/[^a-z0-9\s]/g, "").replace(/\s+/g, " ").trim();
      if (!key) continue;
      if (seen.has(key)) {
        emitMemoryQualityDiagnostic("[DUPLICATE_REMOVED]", {
          scope: "assistant-synthesis",
          duplicateType: "sentence",
        });
        continue;
      }
      seen.add(key);
      kept.push(sentence);
    }

    let output = kept.join(" ");
    output = output.replace(/\b(prefers concise replies)(?:,\s*\1)+/gi, "$1");
    output = output.replace(/\b(prefers detailed replies)(?:,\s*\1)+/gi, "$1");
    output = output.replace(/\b(preferences such as [^.]+)(?:,\s*\1)+/gi, "$1");
    output = output.replace(/\b(I remember what you've shared and will use it to personalize how I help\.?)(?:\s*\1)+/gi, "$1");

    const canonicalName = canonicalizeName(cfg.canonicalName || "");
    if (canonicalName) {
      output = output.replace(/\b(name\s+(?:is|as)\s+)([a-z][a-z'\-\s]{0,60})/gi, function (_, prefix) {
        return prefix + canonicalName;
      });
      output = output.replace(/\b(call\s+you\s+)([a-z][a-z'\-\s]{0,60})/gi, function (_, prefix) {
        return prefix + canonicalName;
      });
    }

    const supersededNames = Array.isArray(cfg.supersededNames) ? cfg.supersededNames : [];
    if (canonicalName && supersededNames.length > 0) {
      supersededNames.forEach((name) => {
        const stale = canonicalizeName(name);
        if (!stale || stale === canonicalName) return;
        const stalePattern = new RegExp("\\b" + escapeRegExp(stale) + "\\b", "gi");
        if (stalePattern.test(output)) {
          emitMemoryQualityDiagnostic("[STALE_MEMORY_EXCLUDED]", {
            scope: "assistant-synthesis-name",
            excluded: stale,
            canonical: canonicalName,
          });
          output = output.replace(stalePattern, canonicalName);
        }
      });
    }

    const canonicalPrimaryPreference = String(cfg.canonicalPrimaryPreference || "").trim();
    const supersededPreferences = Array.isArray(cfg.supersededPreferences) ? cfg.supersededPreferences : [];
    if (canonicalPrimaryPreference && supersededPreferences.length > 0) {
      supersededPreferences.forEach((stalePref) => {
        const stale = String(stalePref || "").trim();
        if (!stale || stale === canonicalPrimaryPreference) return;
        const stalePattern = new RegExp("\\b" + escapeRegExp(stale) + "\\b", "gi");
        if (stalePattern.test(output)) {
          emitMemoryQualityDiagnostic("[STALE_MEMORY_EXCLUDED]", {
            scope: "assistant-synthesis-preference",
            excluded: stale,
            canonical: canonicalPrimaryPreference,
          });
          output = output.replace(stalePattern, canonicalPrimaryPreference);
        }
      });
    }

    output = output.replace(/\s+,/g, ",").replace(/,\s*,+/g, ", ").replace(/\s{2,}/g, " ").trim();
    return normalizeWhitespace(output);
  }

  function clone(value) {
    return JSON.parse(JSON.stringify(value));
  }

  function getStorageKey() {
    return `${STORAGE_PREFIX}:${namespace || "default"}`;
  }

  function normalizeList(list, limit) {
    if (!Array.isArray(list)) return [];
    const out = [];
    const seen = new Set();
    list.forEach((item) => {
      const value = String(item || "").trim().replace(/\s+/g, " ");
      if (!value) return;
      const key = value.toLowerCase();
      if (seen.has(key)) return;
      seen.add(key);
      out.push(value);
    });
    return out.slice(0, Math.max(1, limit || 6));
  }

  function estimateTokens(text) {
    return Math.ceil(String(text || "").length / APPROX_CHARS_PER_TOKEN);
  }

  function totalLongTermEntries(memory) {
    const lt = (memory && memory.long_term_memory) || {};
    return [
      lt.preferences,
      lt.likes_dislikes,
      lt.goals,
      lt.recurring_interests,
      lt.active_projects,
      lt.assistant_notes,
    ].reduce(function (sum, items) {
      return sum + (Array.isArray(items) ? items.length : 0);
    }, 0);
  }

  function resetCorruptedMemory(reason) {
    runtimeMetrics.corruptions += 1;
    runtimeMemory = sanitize(DEFAULT_MEMORY);
    try {
      localStorage.setItem(getStorageKey(), JSON.stringify(runtimeMemory));
    } catch (_) {}
    emit("MEMORY_CORRUPTION_DETECTED", { reason, memoryVersion: MEMORY_VERSION });
    emit("MEMORY_SCHEMA_RECOVERY", { reason, recovered: true, memoryVersion: MEMORY_VERSION });
    emit("MEMORY_CORRUPTION_RECOVERED", { reason, memoryVersion: MEMORY_VERSION });
    return clone(runtimeMemory);
  }

  function sanitizeShortTerm(entries) {
    if (!Array.isArray(entries)) return [];
    const now = Date.now();
    const valid = entries
      .map((entry) => {
        const content = String(entry && entry.content ? entry.content : "").trim().replace(/\s+/g, " ");
        if (!content) return null;
        const ts = Number(entry && entry.ts ? entry.ts : Date.now());
        if (!Number.isFinite(ts)) return null;
        return {
          role: entry && entry.role ? String(entry.role).slice(0, 24) : "user",
          content: content.slice(0, MAX_SHORT_TERM_ENTRY_CHARS),
          ts,
        };
      })
      .filter(Boolean)
      .filter((entry) => now - entry.ts <= SHORT_TERM_TTL_MS)
      .sort((a, b) => a.ts - b.ts);
    return valid.slice(-SHORT_TERM_LIMIT);
  }

  function sanitizeLongTerm(memory) {
    const m = memory || {};
    return {
      user_name: String(m.user_name || "").trim().slice(0, 80),
      location: String(m.location || "").trim().slice(0, 120),
      preferences: normalizeList(m.preferences, LONG_TERM_ENTRY_LIMITS.preferences),
      likes_dislikes: normalizeList(m.likes_dislikes, LONG_TERM_ENTRY_LIMITS.likes_dislikes),
      goals: normalizeList(m.goals, LONG_TERM_ENTRY_LIMITS.goals),
      recurring_interests: normalizeList(m.recurring_interests, LONG_TERM_ENTRY_LIMITS.recurring_interests),
      active_projects: normalizeList(m.active_projects, LONG_TERM_ENTRY_LIMITS.active_projects),
      assistant_notes: normalizeList(m.assistant_notes, LONG_TERM_ENTRY_LIMITS.assistant_notes).map((item) => item.slice(0, 180)),
    };
  }

  function sanitize(memory) {
    const next = Object.assign({}, clone(DEFAULT_MEMORY), memory || {});
    next.memory_version = MEMORY_VERSION;
    next.short_term_memory = sanitizeShortTerm(next.short_term_memory);
    next.long_term_memory = sanitizeLongTerm(next.long_term_memory);
    if (totalLongTermEntries(next) > MAX_LONG_TERM_TOTAL_ENTRIES) {
      next.long_term_memory.assistant_notes = next.long_term_memory.assistant_notes.slice(0, Math.max(0, MAX_LONG_TERM_TOTAL_ENTRIES - 32));
    }
    next.updated_at = new Date().toISOString();
    return next;
  }

  function emit(event, fields) {
    if (typeof logger === "function") {
      try {
        logger(event, Object.assign({ namespace }, fields || {}));
      } catch (_) {}
    }
  }

  function getStructuredMemory() {
    /**
     * Returns memory organized by priority:
     * 1. IDENTITY (user_name, pronouns, core identity)
     * 2. PREFERENCES (likes, dislikes, communication style)
     * 3. PROJECTS (active work, goals, interests)
     * 4. NOTES (assistant observations)
     *
     * Structure:
     * {
     *   identity: { name, ... },
     *   preferences: { likes, dislikes, ... },
     *   projects: { active_projects, goals, recurring_interests, ... },
     *   notes: { assistant_notes, ... },
     *   metadata: { version, updated_at, ... }
     * }
     */
    const normalized = buildNormalizedRuntimeView(runtimeMemory);
    const m = normalized && normalized.long_term_memory ? normalized.long_term_memory : {};
    const st = normalized && normalized.short_term_memory ? normalized.short_term_memory : [];

    return {
      identity: {
        name: String(m.user_name || "").trim() || null,
        location: String(m.location || "").trim() || null,
      },
      preferences: {
        likes: Array.isArray(m.likes_dislikes) ? m.likes_dislikes.slice(0, 3) : [],
        dislikes: Array.isArray(m.likes_dislikes) ? m.likes_dislikes.slice(3, 6) : [],
        communication_preferences: Array.isArray(m.preferences) ? m.preferences.slice(0, 3) : [],
      },
      projects: {
        active_projects: Array.isArray(m.active_projects) ? m.active_projects.slice(0, 3) : [],
        goals: Array.isArray(m.goals) ? m.goals.slice(0, 3) : [],
        recurring_interests: Array.isArray(m.recurring_interests) ? m.recurring_interests.slice(0, 3) : [],
      },
      notes: {
        assistant_observations: Array.isArray(m.assistant_notes) ? m.assistant_notes.slice(0, 2) : [],
      },
      context: {
        recent_exchanges: st.slice(-3),
      },
      metadata: {
        memory_version: runtimeMemory ? runtimeMemory.memory_version : MEMORY_VERSION,
        updated_at: runtimeMemory ? runtimeMemory.updated_at : null,
        entry_count: (function() {
          const lt = m || {};
          return (lt.user_name ? 1 : 0) +
                 (lt.location ? 1 : 0) +
                 (Array.isArray(lt.preferences) ? lt.preferences.length : 0) +
                 (Array.isArray(lt.likes_dislikes) ? lt.likes_dislikes.length : 0) +
                 (Array.isArray(lt.goals) ? lt.goals.length : 0) +
                 (Array.isArray(lt.recurring_interests) ? lt.recurring_interests.length : 0) +
                 (Array.isArray(lt.active_projects) ? lt.active_projects.length : 0) +
                 (Array.isArray(lt.assistant_notes) ? lt.assistant_notes.length : 0);
        })(),
      },
    };
  }

  function init(config) {
    const cfg = config || {};
    namespace = cfg.namespace || namespace || "default";
    logger = typeof cfg.logger === "function" ? cfg.logger : logger;
    return loadMemory();
  }

  function loadMemory() {
    const startedAt = Date.now();
    try {
      const raw = localStorage.getItem(getStorageKey());
      if (!raw) {
        runtimeMemory = sanitize(DEFAULT_MEMORY);
      } else {
        const parsed = JSON.parse(raw);
        if (!parsed || parsed.memory_version !== MEMORY_VERSION) {
          runtimeMemory = resetCorruptedMemory("schema-mismatch");
        } else {
          runtimeMemory = sanitize(parsed);
        }
      }
    } catch (_) {
      runtimeMemory = resetCorruptedMemory("parse-failure");
    }
    runtimeMetrics.loads += 1;
    runtimeMetrics.lastRetrievalLatencyMs = Date.now() - startedAt;
    emit("MEMORY_RETRIEVAL", {
      phase: "load",
      latencyMs: runtimeMetrics.lastRetrievalLatencyMs,
      hasMemory: Boolean(
        runtimeMemory.long_term_memory.user_name ||
        runtimeMemory.long_term_memory.location ||
        runtimeMemory.long_term_memory.preferences.length ||
        runtimeMemory.long_term_memory.active_projects.length
      ),
      memoryVersion: runtimeMemory.memory_version,
    });
    emit("MEMORY_LOADED", {
      memoryVersion: runtimeMemory.memory_version,
      hasShortTerm: runtimeMemory.short_term_memory.length,
      hasLongTerm: Boolean(
        runtimeMemory.long_term_memory.user_name ||
        runtimeMemory.long_term_memory.location ||
        runtimeMemory.long_term_memory.preferences.length ||
        runtimeMemory.long_term_memory.likes_dislikes.length ||
        runtimeMemory.long_term_memory.goals.length ||
        runtimeMemory.long_term_memory.recurring_interests.length ||
        runtimeMemory.long_term_memory.active_projects.length ||
        runtimeMemory.long_term_memory.assistant_notes.length
      ),
      latencyMs: runtimeMetrics.lastRetrievalLatencyMs,
    });
    emit("MEMORY_RETRIEVAL_TIMING", { phase: "load", latencyMs: runtimeMetrics.lastRetrievalLatencyMs });
    return clone(runtimeMemory);
  }

  function saveMemory(memory) {
    const startedAt = Date.now();
    runtimeMemory = sanitize(memory);
    try {
      localStorage.setItem(getStorageKey(), JSON.stringify(runtimeMemory));
    } catch (_) {}
    runtimeMetrics.saves += 1;
    emit("MEMORY_SAVED", {
      keys: Object.keys(runtimeMemory).length,
      updatedAt: runtimeMemory.updated_at,
      memoryVersion: runtimeMemory.memory_version,
      latencyMs: Date.now() - startedAt,
    });
    return clone(runtimeMemory);
  }

  function updateMemory(patch) {
    const next = clone(runtimeMemory);
    const incoming = patch || {};

    const longTermPatch = incoming.long_term_memory || {
      user_name: incoming.user_name,
      location: incoming.location,
      preferences: incoming.preferences,
      likes_dislikes: incoming.likes_dislikes,
      goals: incoming.goals,
      recurring_interests: incoming.recurring_interests,
      active_projects: incoming.active_projects,
      assistant_notes: incoming.assistant_notes,
    };

    if (incoming.short_term_memory) {
      next.short_term_memory = sanitizeShortTerm([].concat(next.short_term_memory || [], incoming.short_term_memory));
    } else {
      next.short_term_memory = sanitizeShortTerm(next.short_term_memory || []);
    }

    if (typeof longTermPatch.user_name === "string" && longTermPatch.user_name.trim()) {
      next.long_term_memory.user_name = longTermPatch.user_name.trim();
    }
    if (typeof longTermPatch.location === "string" && longTermPatch.location.trim()) {
      next.long_term_memory.location = longTermPatch.location.trim();
    }
    if (Array.isArray(longTermPatch.preferences)) {
      next.long_term_memory.preferences = normalizeList([].concat(next.long_term_memory.preferences || [], longTermPatch.preferences), LONG_TERM_ENTRY_LIMITS.preferences);
    }
    if (Array.isArray(longTermPatch.likes_dislikes)) {
      next.long_term_memory.likes_dislikes = normalizeList([].concat(next.long_term_memory.likes_dislikes || [], longTermPatch.likes_dislikes), LONG_TERM_ENTRY_LIMITS.likes_dislikes);
    }
    if (Array.isArray(longTermPatch.goals)) {
      next.long_term_memory.goals = normalizeList([].concat(next.long_term_memory.goals || [], longTermPatch.goals), LONG_TERM_ENTRY_LIMITS.goals);
    }
    if (Array.isArray(longTermPatch.recurring_interests)) {
      next.long_term_memory.recurring_interests = normalizeList([].concat(next.long_term_memory.recurring_interests || [], longTermPatch.recurring_interests), LONG_TERM_ENTRY_LIMITS.recurring_interests);
    }
    if (Array.isArray(longTermPatch.active_projects)) {
      next.long_term_memory.active_projects = normalizeList([].concat(next.long_term_memory.active_projects || [], longTermPatch.active_projects), LONG_TERM_ENTRY_LIMITS.active_projects);
    }
    if (Array.isArray(longTermPatch.assistant_notes)) {
      next.long_term_memory.assistant_notes = normalizeList([].concat(next.long_term_memory.assistant_notes || [], longTermPatch.assistant_notes), LONG_TERM_ENTRY_LIMITS.assistant_notes).map((item) => item.slice(0, 180));
    }

    const saved = saveMemory(next);
    emit("MEMORY_UPDATED", {
      updatedFields: Object.keys(incoming),
      shortTermCount: saved.short_term_memory.length,
      updatedAt: saved.updated_at,
    });
    return saved;
  }

  function clearMemory() {
    runtimeMemory = sanitize(DEFAULT_MEMORY);
    try {
      localStorage.removeItem(getStorageKey());
    } catch (_) {}
    runtimeMetrics.clears += 1;
    emit("MEMORY_CLEARED", { cleared: true, memoryVersion: MEMORY_VERSION });
    return clone(runtimeMemory);
  }

  function summarizeForPrompt(memory) {
    const m = buildNormalizedRuntimeView(memory || runtimeMemory);
    const lt = m.long_term_memory || {};
    const parts = [];
    // Priority order: identity -> preferences -> projects -> location -> goals -> notes
    if (lt.user_name) parts.push(`name=${lt.user_name}`);
    if (lt.preferences && lt.preferences.length) parts.push(`preferences=${lt.preferences.slice(0, 4).join("; ")}`);
    if (lt.likes_dislikes && lt.likes_dislikes.length) parts.push(`likes_dislikes=${lt.likes_dislikes.slice(0, 4).join("; ")}`);
    if (lt.active_projects && lt.active_projects.length) parts.push(`projects=${lt.active_projects.slice(0, 3).join("; ")}`);
    if (lt.location) parts.push(`location=${lt.location}`);
    if (lt.goals && lt.goals.length) parts.push(`goals=${lt.goals.slice(0, 3).join("; ")}`);
    if (lt.recurring_interests && lt.recurring_interests.length) parts.push(`recurring_interests=${lt.recurring_interests.slice(0, 4).join("; ")}`);
    if (lt.assistant_notes && lt.assistant_notes.length) parts.push(`notes=${lt.assistant_notes.slice(0, 2).join("; ")}`);
    let summary = parts.join(" | ").trim();
    const maxCharsByBudget = MAX_INJECTION_TOKEN_BUDGET * APPROX_CHARS_PER_TOKEN;
    const maxSummaryChars = Math.min(MEMORY_CONTEXT_MAX_CHARS, maxCharsByBudget);
    if (summary.length > maxSummaryChars) {
      summary = summary.slice(0, maxSummaryChars) + "...";
    }
    return summary;
  }

  function tokenizeForRelevance(input) {
    return String(input || "")
      .toLowerCase()
      .replace(/[^a-z0-9\s]/g, " ")
      .split(/\s+/)
      .map((token) => token.trim())
      .filter((token) => token.length > 2)
      .slice(0, 80);
  }

  function estimateFreshnessScore(ts) {
    const value = Number(ts || 0);
    if (!value) return 0.35;
    const ageMs = Math.max(0, Date.now() - value);
    const oneHour = 60 * 60 * 1000;
    const freshness = 1 - Math.min(1, ageMs / (24 * oneHour));
    return Number(freshness.toFixed(3));
  }

  function computeOverlapScore(queryTokens, valueTokens) {
    if (!queryTokens.length || !valueTokens.length) return 0;
    const querySet = new Set(queryTokens);
    let overlap = 0;
    valueTokens.forEach((token) => {
      if (querySet.has(token)) overlap += 1;
    });
    return overlap / Math.max(1, querySet.size);
  }

  function collectMemoryCandidates(view) {
    const candidates = [];
    const memory = view || buildNormalizedRuntimeView(runtimeMemory);
    const longTerm = memory.long_term_memory || {};
    const shortTerm = Array.isArray(memory.short_term_memory) ? memory.short_term_memory : [];
    const categoryWeights = {
      user_name: 0.8,
      preferences: 1,
      likes_dislikes: 0.94,
      goals: 0.91,
      recurring_interests: 0.88,
      active_projects: 0.86,
      assistant_notes: 0.72,
    };

    Object.keys(categoryWeights).forEach((field) => {
      const value = longTerm[field];
      if (typeof value === "string" && value.trim()) {
        candidates.push({
          text: value.trim(),
          category: field,
          source: "long_term_memory",
          freshness: 0.55,
          confidence: 0.84,
          weight: categoryWeights[field],
        });
        return;
      }
      if (Array.isArray(value)) {
        value.forEach((entry) => {
          const text = String(entry || "").trim();
          if (!text) return;
          candidates.push({
            text,
            category: field,
            source: "long_term_memory",
            freshness: 0.55,
            confidence: 0.84,
            weight: categoryWeights[field],
          });
        });
      }
    });

    shortTerm.forEach((item) => {
      const text = String(item && item.content ? item.content : "").trim();
      if (!text) return;
      candidates.push({
        text: text.slice(0, 220),
        category: "short_term_memory",
        source: "short_term_memory",
        freshness: estimateFreshnessScore(item && item.ts),
        confidence: 0.72,
        weight: 0.79,
      });
    });

    return candidates;
  }

  function buildMemoryOrchestrationPacket(message, options) {
    const startedAt = Date.now();
    const text = String(message || "").trim();
    const cfg = Object.assign({ maxItems: 6 }, options || {});
    const queryTokens = tokenizeForRelevance(text);
    const candidates = collectMemoryCandidates();
    const scored = candidates
      .map((candidate) => {
        const valueTokens = tokenizeForRelevance(candidate.text);
        const overlap = computeOverlapScore(queryTokens, valueTokens);
        const score = Math.min(1, (overlap * 0.62) + (candidate.freshness * 0.2) + (candidate.confidence * 0.18)) * candidate.weight;
        return Object.assign({}, candidate, {
          overlap: Number(overlap.toFixed(3)),
          score: Number(score.toFixed(3)),
        });
      })
      .sort((a, b) => b.score - a.score);

    const threshold = queryTokens.length ? 0.32 : 0.58;
    const selected = scored
      .filter((item) => item.score >= threshold)
      .slice(0, Math.max(1, Number(cfg.maxItems || 6)));

    const snippet = selected
      .map((item) => `${item.category}=${item.text}`)
      .join(" | ")
      .slice(0, MEMORY_CONTEXT_MAX_CHARS);

    const avgScore = selected.length
      ? selected.reduce((sum, item) => sum + item.score, 0) / selected.length
      : 0;

    runtimeMetrics.lastRetrievalLatencyMs = Date.now() - startedAt;
    emit("MEMORY_ORCHESTRATION_PACKET", {
      queryLength: text.length,
      totalCandidates: scored.length,
      selectedCount: selected.length,
      averageScore: Number(avgScore.toFixed(3)),
      latencyMs: runtimeMetrics.lastRetrievalLatencyMs,
    });

    return {
      query: text,
      hit: selected.length > 0,
      totalCandidates: scored.length,
      selectedCount: selected.length,
      averageScore: Number(avgScore.toFixed(3)),
      latencyMs: runtimeMetrics.lastRetrievalLatencyMs,
      memories: selected.map((item) => ({
        text: item.text,
        category: item.category,
        score: item.score,
        freshness: item.freshness,
        confidence: item.confidence,
        source: item.source,
      })),
      contextSnippet: snippet,
    };
  }

  function injectMemoryContext(message) {
    const startedAt = Date.now();
    const text = String(message || "");
    if (!text.trim()) return text;
    if (text.includes("[MEMORY_CONTEXT]")) return text;
    const packet = buildMemoryOrchestrationPacket(text, { maxItems: 6 });
    const summary = packet && packet.contextSnippet ? packet.contextSnippet : summarizeForPrompt(runtimeMemory);
    if (!summary) {
      runtimeMetrics.misses += 1;
      runtimeMetrics.lastRetrievalLatencyMs = Date.now() - startedAt;
      emit("MEMORY_RETRIEVAL", {
        phase: "inject",
        latencyMs: runtimeMetrics.lastRetrievalLatencyMs,
        hit: false,
      });
      emit("MEMORY_RETRIEVAL_TIMING", { phase: "inject", latencyMs: runtimeMetrics.lastRetrievalLatencyMs, hit: false });
      return text;
    }
    runtimeMetrics.hits += 1;
    runtimeMetrics.injections += 1;
    runtimeMetrics.lastRetrievalLatencyMs = Date.now() - startedAt;
    emit("MEMORY_RETRIEVAL", {
      phase: "inject",
      latencyMs: runtimeMetrics.lastRetrievalLatencyMs,
      hit: true,
      estimatedTokens: estimateTokens(summary),
    });
    emit("MEMORY_INJECTION", {
      summaryLength: summary.length,
      estimatedTokens: estimateTokens(summary),
      injectionCount: runtimeMetrics.injections,
    });
    emit("MEMORY_INJECTED", {
      summaryLength: summary.length,
      estimatedTokens: estimateTokens(summary),
      injectionCount: runtimeMetrics.injections,
    });
    emit("MEMORY_RETRIEVAL_TIMING", { phase: "inject", latencyMs: runtimeMetrics.lastRetrievalLatencyMs, hit: true });
    return `[MEMORY_CONTEXT]\n${summary}\n[/MEMORY_CONTEXT]\n\n${text}`;
  }

  function parseSummaryField(summary, key) {
    var source = String(summary || "");
    var pattern = new RegExp(key + "=([^|\\n]+)", "i");
    var match = source.match(pattern);
    return match ? String(match[1] || "").trim() : "";
  }

  function extractSelfReferenceEntityIntent(message, runtimeView) {
    const text = normalizeWhitespace(message || "");
    if (!text) return null;

    const view = runtimeView || buildNormalizedRuntimeView(runtimeMemory);
    const canonicalUserName = canonicalizeName(
      (view && view.long_term_memory && view.long_term_memory.user_name) || ""
    );
    if (!canonicalUserName) return null;

    const explicitOther = EXPLICIT_OTHER_PERSON_PATTERNS.some((pattern) => pattern.test(text));
    if (explicitOther) {
      return {
        matched: false,
        explicitOtherPerson: true,
        canonicalUserName,
        entity: "",
        queryType: "",
      };
    }

    for (let i = 0; i < SELF_REFERENCE_ENTITY_PATTERNS.length; i += 1) {
      const pattern = SELF_REFERENCE_ENTITY_PATTERNS[i];
      const match = text.match(pattern);
      if (!match || !match[1]) continue;
      const entity = canonicalizeName(match[1]);
      if (!entity) continue;

      let queryType = "self-reference-entity";
      if (/^what\s+do\s+you\s+know\s+about/i.test(text)) queryType = "what-do-you-know-about";
      if (/^tell\s+me\s+about/i.test(text)) queryType = "tell-me-about";
      if (/^who\s+is/i.test(text)) queryType = "who-is";

      return {
        matched: entity === canonicalUserName,
        explicitOtherPerson: false,
        canonicalUserName,
        entity,
        queryType,
      };
    }
    return null;
  }

  function isGenericEntityFallbackText(text, canonicalName) {
    const source = normalizeWhitespace(text || "");
    const name = canonicalizeName(canonicalName || "");
    if (!source || !name) return false;
    const hasName = new RegExp("\\b" + escapeRegExp(name) + "\\b", "i").test(source);
    if (!hasName) return false;
    return GENERIC_ENTITY_FALLBACK_PATTERNS.some((pattern) => pattern.test(source));
  }

  function hasStatelessClaim(text) {
    var source = String(text || "");
    return STATELESS_CLAIM_PATTERNS.some(function (pattern) {
      return pattern.test(source);
    });
  }

  function buildMemoryReplacement(hasMemory) {
    return hasMemory
      ? "I remember what you've shared and will use it to personalize how I help."
      : "I don't know that yet.";
  }

  function createPolicyViolation(text, cfg, replacement) {
    var error = new Error("Assistant-visible response violated the memory policy before render.");
    error.name = POLICY_VIOLATION_NAME;
    error.code = POLICY_VIOLATION_CODE;
    error.source = cfg.source || "unknown";
    error.responsePath = cfg.responsePath || "assistant-visible";
    error.responseSourceIdentifier = cfg.responseSourceIdentifier || cfg.source || "unknown";
    error.replacementText = replacement;
    error.originalText = String(text || "");
    return error;
  }

  function enforceAssistantVisibleResponse(responseText, options) {
    var text = String(responseText || "");
    var cfg = Object.assign({
      memoryEnabled: true,
      hasMemory: false,
      source: "unknown",
      responsePath: "assistant-visible",
      responseSourceIdentifier: "unknown",
      throwOnViolation: true,
    }, options || {});

    emit("ASSISTANT_RESPONSE_PATH", {
      source: cfg.source,
      responsePath: cfg.responsePath,
      responseSourceIdentifier: cfg.responseSourceIdentifier,
      memoryEnabled: !!cfg.memoryEnabled,
      hasMemory: !!cfg.hasMemory,
    });
    emit("RESPONSE_SOURCE_IDENTIFIER", {
      source: cfg.source,
      responsePath: cfg.responsePath,
      responseSourceIdentifier: cfg.responseSourceIdentifier,
    });

    var enforced = enforceMemoryAwareResponse(text, cfg);
    emit("MEMORY_POLICY_ENFORCED", {
      source: cfg.source,
      responsePath: cfg.responsePath,
      responseSourceIdentifier: cfg.responseSourceIdentifier,
      blocked: !!(enforced && enforced.blocked),
      memoryEnabled: !!cfg.memoryEnabled,
      hasMemory: !!cfg.hasMemory,
    });

    if (cfg.memoryEnabled && enforced && enforced.blocked) {
      emit("STATELESS_TEMPLATE_BLOCKED", {
        source: cfg.source,
        responsePath: cfg.responsePath,
        responseSourceIdentifier: cfg.responseSourceIdentifier,
        preview: text.slice(0, 160),
        replacement: enforced.text,
      });
      if (cfg.throwOnViolation !== false) {
        throw createPolicyViolation(text, cfg, enforced.text);
      }
    }

    return {
      text: enforced ? enforced.text : text,
      blocked: !!(enforced && enforced.blocked),
    };
  }

  function detectMemoryCapabilityIntent(message, runtimeView) {
    var text = String(message || "").trim();
    if (!text) {
      return null;
    }
    var lower = text.toLowerCase();
    var selfReferenceEntity = extractSelfReferenceEntityIntent(text, runtimeView);
    var matched = MEMORY_SELF_KNOWLEDGE_PATTERNS.some(function (pattern) {
      return pattern.test(lower);
    });
    if (!matched && !(selfReferenceEntity && selfReferenceEntity.matched)) {
      return null;
    }
    return {
      builder: /\bbuilder\b|developer|build this|memory settings|consent/.test(lower),
      deleteMemory: /delete\s+memory|clear\s+memory|wipe\s+memory|remove\s+memory/.test(lower),
      askWhatKnown: /what\s+do\s+you\s+know\s+about\s+me|what\s+do\s+you\s+remember/.test(lower),
      askTellRemember: /tell\s+me\s+what\s+you\s+remember/.test(lower),
      askPreferences: /what\s+are\s+my\s+preferences/.test(lower),
      askWhoAmI: /who\s+am\s+i/.test(lower),
      askWhatToldYou: /what\s+have\s+i\s+told\s+you/.test(lower),
      askHowRemember: /how\s+can\s+you\s+remember/.test(lower),
      askCanRemember: /can\s+you\s+remember/.test(lower),
      askLongTerm: /long[ -]?term\s+memory/.test(lower),
      askShortTerm: /short[ -]?term\s+memory/.test(lower),
      askPersonal: /personal\s+information/.test(lower),
      askForever: /\bforever\b|permanent|always/.test(lower),
      reflective: /what\s+do\s+you\s+(?:know\s+about\s+me|remember)|tell\s+me\s+what\s+you\s+remember|what\s+are\s+my\s+preferences|who\s+am\s+i|what\s+have\s+i\s+told\s+you/i.test(lower) || !!(selfReferenceEntity && selfReferenceEntity.matched),
      selfReferenceEntity: selfReferenceEntity,
    };
  }

  function suppressArchitectureNarrationForReflection(text) {
    const input = normalizeWhitespace(text || "");
    if (!input) return input;
    const sentences = input
      .replace(/([.!?])\s+/g, "$1\n")
      .split(/\n+/g)
      .map((s) => normalizeWhitespace(s))
      .filter(Boolean);
    const kept = [];
    let blocked = false;
    sentences.forEach((sentence) => {
      const isArchitecture = ARCHITECTURE_NARRATION_PATTERNS.some((pattern) => pattern.test(sentence));
      if (isArchitecture) {
        blocked = true;
        return;
      }
      kept.push(sentence);
    });
    if (blocked) {
      emitMemoryQualityDiagnostic("[ARCHITECTURE_FALLBACK_BLOCKED]", {
        scope: "reflective-memory",
      });
    }
    return normalizeWhitespace(kept.join(" "));
  }

  function buildReflectiveMemorySynthesis(runtimeView) {
    const view = runtimeView || buildNormalizedRuntimeView(runtimeMemory);
    const longTerm = (view && view.long_term_memory) || {};
    const shortTerm = (view && view.short_term_memory) || [];
    const modes = (view && view.assistant_modes) || [];

    const name = normalizeWhitespace(longTerm.user_name || "");
    const location = normalizeWhitespace(longTerm.location || "");
    const preferences = Array.isArray(longTerm.preferences) ? longTerm.preferences.slice(0, 3) : [];
    const traits = Array.isArray(longTerm.likes_dislikes) ? longTerm.likes_dislikes.slice(0, 3) : [];
    const notes = Array.isArray(longTerm.assistant_notes) ? longTerm.assistant_notes.slice(0, 2) : [];
    const persistedFacts = [];
    if (Array.isArray(longTerm.active_projects) && longTerm.active_projects.length) {
      persistedFacts.push("active work like " + longTerm.active_projects.slice(0, 2).join(", "));
    }
    if (Array.isArray(longTerm.goals) && longTerm.goals.length) {
      persistedFacts.push("goals such as " + longTerm.goals.slice(0, 2).join(", "));
    }
    if (Array.isArray(longTerm.recurring_interests) && longTerm.recurring_interests.length) {
      persistedFacts.push("recurring interests such as " + longTerm.recurring_interests.slice(0, 2).join(", "));
    }
    const latestUserContext = shortTerm
      .slice()
      .reverse()
      .find((entry) => String(entry && entry.role || "").toLowerCase() === "user" && normalizeWhitespace(entry && entry.content));

    const knownParts = [];
    if (name) knownParts.push("your name is " + name);
    if (location) knownParts.push("you're in " + location);
    if (preferences.length) knownParts.push("you prefer " + preferences.join(", "));
    if (traits.length) knownParts.push("you've shared traits like " + traits.join(", "));
    if (persistedFacts.length) knownParts.push("I also remember " + persistedFacts.join(" and "));
    if (notes.length) knownParts.push("you've highlighted notes like " + notes.join(", "));

    let response = "";
    if (knownParts.length > 0) {
      response = "From what I currently remember, " + knownParts.join(". ");
    } else {
      response = "I remember only a little so far. ";
    }

    if (latestUserContext && latestUserContext.content) {
      const recent = normalizeWhitespace(latestUserContext.content).slice(0, 140);
      if (recent) {
        response += "Most recently, you mentioned: \"" + recent + "\". ";
      }
    }

    const richness = knownParts.length;
    if (richness <= 2) {
      response += "I can use this, but I do not yet know many additional personal preferences.";
    } else {
      response += "I'll keep using this context so replies stay consistent with your ongoing preferences and identity.";
    }

    if (modes.indexOf("mode:concise") >= 0) {
      response = response
        .replace("From what I currently remember, ", "I remember: ")
        .replace("I'll keep using this context so replies stay consistent with your ongoing preferences and identity.", "I'll keep this consistent in future replies.");
    }
    if (modes.indexOf("mode:detailed") >= 0) {
      response += " If you'd like, I can break this down into identity, preferences, projects, and recent continuity in more detail.";
    }

    emitMemoryQualityDiagnostic("[REFLECTIVE_SYNTHESIS]", {
      scope: "runtime-memory",
      knownPartCount: knownParts.length,
      hasRecentContinuity: !!latestUserContext,
      assistantModes: modes,
    });
    const factsCount =
      (name ? 1 : 0) +
      (location ? 1 : 0) +
      (preferences.length ? 1 : 0) +
      (traits.length ? 1 : 0) +
      (persistedFacts.length ? 1 : 0) +
      (notes.length ? 1 : 0) +
      (latestUserContext ? 1 : 0);
    const finalText = suppressArchitectureNarrationForReflection(normalizeAssistantSynthesisText(response));
    return {
      text: finalText,
      factsCount,
      hasFacts: factsCount > 0,
      knownPartCount: knownParts.length,
    };
  }

  function describeKnownMemory(memoryContext) {
    if (memoryContext && typeof memoryContext === "object" && memoryContext.long_term_memory) {
      const view = buildNormalizedRuntimeView(memoryContext);
      const details = [];
      if (view.long_term_memory.user_name) details.push("your name as " + view.long_term_memory.user_name);
      if (Array.isArray(view.long_term_memory.preferences) && view.long_term_memory.preferences.length) {
        details.push("preferences such as " + view.long_term_memory.preferences.slice(0, 2).join(", "));
      }
      if (Array.isArray(view.long_term_memory.goals) && view.long_term_memory.goals.length) {
        details.push("goals like " + view.long_term_memory.goals.slice(0, 2).join(", "));
      }
      if (Array.isArray(view.long_term_memory.recurring_interests) && view.long_term_memory.recurring_interests.length) {
        details.push("interests such as " + view.long_term_memory.recurring_interests.slice(0, 2).join(", "));
      }
      if (Array.isArray(view.long_term_memory.active_projects) && view.long_term_memory.active_projects.length) {
        details.push("active projects like " + view.long_term_memory.active_projects.slice(0, 2).join(", "));
      }
      return details;
    }

    var summary = "";
    if (typeof memoryContext === "string") {
      summary = memoryContext;
    } else if (memoryContext && typeof memoryContext === "object") {
      summary = String(memoryContext.memorySummary || memoryContext.context || "");
    }
    if (!summary || /^memory-unavailable:/i.test(summary)) {
      return [];
    }

    var details = [];
    var name = parseSummaryField(summary, "name");
    if (name) {
      details.push("your name as " + name);
    }
    var preferences = parseSummaryField(summary, "preferences");
    if (preferences) {
      details.push("preferences such as " + preferences.split(";").slice(0, 2).join(", "));
    }
    var goals = parseSummaryField(summary, "goals");
    if (goals) {
      details.push("goals like " + goals.split(";").slice(0, 2).join(", "));
    }
    var interests = parseSummaryField(summary, "recurring_interests");
    if (interests) {
      details.push("interests such as " + interests.split(";").slice(0, 2).join(", "));
    }
    var projects = parseSummaryField(summary, "projects");
    if (projects) {
      details.push("active projects like " + projects.split(";").slice(0, 2).join(", "));
    }
    return details;
  }

  function buildMemoryCapabilityResponse(message, options) {
    var cfg = Object.assign({ memoryContext: null, hasMemory: false, source: "memory-capability-helper" }, options || {});
    var runtimeView = null;
    var runtimeQueryFailed = false;
    try {
      runtimeView = buildNormalizedRuntimeView(runtimeMemory);
    } catch (_) {
      runtimeQueryFailed = true;
    }

    var intent = detectMemoryCapabilityIntent(message, runtimeView);
    if (!intent) {
      return { matched: false, text: "" };
    }

    emitMemoryQualityDiagnostic("[MEMORY_REFLECTION_TRACE]", {
      stage: "intent_detection",
      source: cfg.source,
      reflectiveIntent: !!intent.reflective,
    });
    traceCanonicalRuntimeState("intent_detection", {
      source: cfg.source,
      reflectiveIntent: !!intent.reflective,
      query: String(message || "").slice(0, 160),
    });

    emitMemoryQualityDiagnostic("[MEMORY_REFLECTION_TRACE]", {
      stage: "memory_retrieval",
      source: cfg.source,
      runtimeQueryFailed: runtimeQueryFailed,
      runtimeQueryEmpty: !runtimeView,
    });
    traceCanonicalRuntimeState("memory_query", {
      source: cfg.source,
      runtimeQueryFailed: runtimeQueryFailed,
      runtimeQueryEmpty: !runtimeView,
      canonicalViewObserved: !!runtimeView,
    });

    var knownDetails = describeKnownMemory(runtimeView);
    var hasMemory = !!cfg.hasMemory || knownDetails.length > 0;
    var responseText = "";

    if (intent.reflective) {
      if (intent.selfReferenceEntity && intent.selfReferenceEntity.matched) {
        emitMemoryQualityDiagnostic("[SELF_REFERENCE_RESOLVED]", {
          source: cfg.source,
          entity: intent.selfReferenceEntity.entity,
          canonicalUserName: intent.selfReferenceEntity.canonicalUserName,
          queryType: intent.selfReferenceEntity.queryType,
        });
        emitMemoryQualityDiagnostic("[CANONICAL_USER_NAME_MATCH]", {
          source: cfg.source,
          entity: intent.selfReferenceEntity.entity,
          canonicalUserName: intent.selfReferenceEntity.canonicalUserName,
        });
      }
      emitMemoryQualityDiagnostic("[MEMORY_REFLECTION_ROUTE]", {
        source: cfg.source,
        querySource: "runtime-canonical-view",
      });
      var synthesis = buildReflectiveMemorySynthesis(runtimeView);
      responseText = synthesis.text;
      emitMemoryQualityDiagnostic("[MEMORY_REFLECTION_TRACE]", {
        stage: "synthesis",
        source: cfg.source,
        synthesisHasFacts: !!synthesis.hasFacts,
        synthesisFactsCount: Number(synthesis.factsCount || 0),
      });
      traceCanonicalRuntimeState("synthesis", {
        source: cfg.source,
        synthesisHasFacts: !!synthesis.hasFacts,
        synthesisFactsCount: Number(synthesis.factsCount || 0),
      });

      var allowArchitectureFallback = !synthesis.hasFacts && runtimeQueryFailed;
      emitMemoryQualityDiagnostic("[MEMORY_REFLECTION_TRACE]", {
        stage: "arbitration",
        source: cfg.source,
        allowArchitectureFallback: allowArchitectureFallback,
        reflectiveSuccess: !!synthesis.hasFacts,
      });
      traceCanonicalRuntimeState("arbitration", {
        source: cfg.source,
        allowArchitectureFallback: allowArchitectureFallback,
        reflectiveSuccess: !!synthesis.hasFacts,
      });

      if (synthesis.hasFacts) {
        emitMemoryQualityDiagnostic("[REFLECTIVE_SYNTHESIS_SUCCESS]", {
          source: cfg.source,
          factsCount: synthesis.factsCount,
        });
        markTerminalRoute("reflective-memory", {
          source: cfg.source,
          factsCount: synthesis.factsCount,
        });

        const overwriteAttempt = enforceMemoryAwareResponse(responseText, {
          memoryEnabled: true,
          hasMemory: hasMemory,
          source: cfg.source,
        });
        if (intent.selfReferenceEntity && intent.selfReferenceEntity.matched) {
          emitMemoryQualityDiagnostic("[GENERIC_ENTITY_FALLBACK_BLOCKED]", {
            source: cfg.source,
            canonicalUserName: intent.selfReferenceEntity.canonicalUserName,
            reason: "terminal_reflective_route_locked",
          });
        }
        blockSecondaryRoute("fallback-overwrite", "terminal-reflective-lock", {
          source: cfg.source,
          attempted: !!(overwriteAttempt && overwriteAttempt.blocked),
        });
        emitMemoryQualityDiagnostic("[TERMINAL_RESPONSE_COMMITTED]", {
          source: cfg.source,
          route: "reflective-memory",
          finalRouteLocked: true,
        });
        confirmRuntimeParity("reflective-memory", {
          source: cfg.source,
          liveTextLength: responseText.length,
          replayTextLength: responseText.length,
        });
        emitMemoryQualityDiagnostic("[MEMORY_REFLECTION_TRACE]", {
          stage: "final_response_commit",
          source: cfg.source,
          finalRouteLocked: true,
        });
        return {
          matched: true,
          text: responseText,
          intent: intent,
          reflective: true,
          reflectiveSuccess: true,
          factsCount: synthesis.factsCount,
          finalRouteLocked: true,
          terminal: true,
        };
      }

      if (!allowArchitectureFallback) {
        emitMemoryQualityDiagnostic("[ARCHITECTURE_FALLBACK_BLOCKED]", {
          source: cfg.source,
          reason: "reflective_zero_facts_without_runtime_failure",
        });
        if (intent.selfReferenceEntity && intent.selfReferenceEntity.matched) {
          emitMemoryQualityDiagnostic("[GENERIC_ENTITY_FALLBACK_BLOCKED]", {
            source: cfg.source,
            canonicalUserName: intent.selfReferenceEntity.canonicalUserName,
            reason: "reflective_zero_facts",
          });
        }
        blockSecondaryRoute("architecture-narration", "reflective-success-or-runtime-view-available", {
          source: cfg.source,
        });
      }
      var reflectiveFallback = enforceAssistantVisibleResponse(responseText, {
        memoryEnabled: true,
        hasMemory: hasMemory,
        source: cfg.source,
        responsePath: "memory-reflection",
        responseSourceIdentifier: cfg.source,
        throwOnViolation: false,
      });
      emitMemoryQualityDiagnostic("[TERMINAL_RESPONSE_COMMITTED]", {
        source: cfg.source,
        route: "reflective-memory",
        finalRouteLocked: false,
      });
      confirmRuntimeParity("reflective-memory-fallback", {
        source: cfg.source,
        liveTextLength: reflectiveFallback.text.length,
        replayTextLength: reflectiveFallback.text.length,
      });
      emitMemoryQualityDiagnostic("[MEMORY_REFLECTION_TRACE]", {
        stage: "final_response_commit",
        source: cfg.source,
        finalRouteLocked: false,
      });
      return {
        matched: true,
        text: reflectiveFallback.text,
        intent: intent,
        reflective: true,
        reflectiveSuccess: false,
        factsCount: Number(synthesis.factsCount || 0),
        finalRouteLocked: false,
      };
    }

    if (intent.builder) {
      responseText = [
        "Amicor already keeps recent conversation context and longer-lived personal details.",
        "In the current system, memory stays tied to your account context, Clear Memory wipes both recent and saved memory, and the policy blocks stateless claims from leaking into replies.",
        "Safe builder steps are to add a user memory settings page, add memory review/edit/delete UI, add an explicit consent toggle, expose memory categories to the user, and move to account-based memory ownership.",
        "Advanced semantic or vector memory is not part of the current architecture yet and should stay a later step."
      ].join(" ");
    } else if (intent.deleteMemory) {
      responseText = [
        "Use Clear Memory to delete memory.",
        "That wipes both recent and saved memory, so stored personal details and recent context are removed together."
      ].join(" ");
    } else if (intent.askWhatKnown) {
      responseText = knownDetails.length > 0
        ? "From memory I currently know " + knownDetails.join(", ") + "."
        : "I know a small amount so far, and I will keep updating this based on what you share.";
    } else if (intent.askForever) {
      responseText = "I can remember a name as a saved detail, but not as a forever guarantee. Memory can be cleared, ownership controls are still being hardened, and advanced semantic or vector memory has not been added yet.";
    } else if (intent.askLongTerm || intent.askShortTerm) {
      responseText = "Yes. Amicor remembers recent exchanges and can also keep durable facts and preferences. Clear Memory wipes both, and the memory policy prevents stateless replies from contradicting that behavior.";
    } else if (intent.askHowRemember || intent.askCanRemember || intent.askPersonal) {
      responseText = "Amicor remembers through recent conversation context and saved durable user facts. That memory can be cleared explicitly and is guarded by a response policy that blocks stateless claims. Advanced semantic or vector memory is not in the system yet.";
    } else {
      responseText = "Amicor uses both recent and saved memory, Clear Memory wipes both, and advanced semantic or vector memory is not added yet.";
    }

    var enforced = enforceAssistantVisibleResponse(responseText, {
      memoryEnabled: true,
      hasMemory: hasMemory,
      source: cfg.source,
      responsePath: "memory-capability",
      responseSourceIdentifier: cfg.source,
      throwOnViolation: false,
    });
    return { matched: true, text: enforced.text, intent: intent };
  }

  function enforceMemoryAwareResponse(responseText, options) {
    const text = String(responseText || "");
    const cfg = Object.assign({ memoryEnabled: true, hasMemory: false, source: "unknown" }, options || {});
    emit("ASSISTANT_MEMORY_POLICY_APPLIED", {
      source: cfg.source,
      hasMemory: !!cfg.hasMemory,
      memoryEnabled: !!cfg.memoryEnabled,
    });
    emit("MEMORY_POLICY_APPLIED", {
      source: cfg.source,
      hasMemory: !!cfg.hasMemory,
      memoryEnabled: !!cfg.memoryEnabled,
    });
    if (!cfg.memoryEnabled || !text.trim()) {
      return { text, blocked: false };
    }
    const hit = hasStatelessClaim(text);
    if (!hit) {
      return { text, blocked: false };
    }
    emit("ASSISTANT_STATELESS_TEMPLATE_DETECTED", {
      source: cfg.source,
      hasMemory: !!cfg.hasMemory,
      preview: text.slice(0, 160),
    });
    emit("STATELESS_TEMPLATE_BLOCKED", {
      source: cfg.source,
      hasMemory: !!cfg.hasMemory,
      preview: text.slice(0, 160),
    });
    const replacement = buildMemoryReplacement(cfg.hasMemory);
    emit("ASSISTANT_MEMORY_POLICY_BLOCKED", {
      source: cfg.source,
      hasMemory: !!cfg.hasMemory,
      replacement,
    });
    return { text: replacement, blocked: true };
  }

  function canonicalMemoryResponsePipeline(responseText, options) {
    /**
     * CANONICAL UNIFIED RESPONSE PIPELINE
     *
     * ALL assistant-visible responses MUST pass through this function.
     * This is the single source of truth for:
     *   1. Memory retrieval
     *   2. Memory injection
     *   3. Identity enforcement
     *   4. Stateless-response blocking
     *   5. Diagnostics
     *
     * Applies to: streaming, non-streaming, replayed sessions,
     *   restored history, education mode, explain/research modes,
     *   tool responses, fallback templates, retry paths
     *
     * @param {string} responseText - The assistant response to process
     * @param {object} options - Configuration
     *   - source: string identifier (e.g., "streaming-token", "tool-result")
     *   - userMessage: optional original user message (for memory capability detection)
     *   - memoryEnabled: boolean (default: true)
     *   - throwOnViolation: boolean (default: false)
     *   - context: optional additional context
     *
     * @returns {object}
     *   - text: final processed response text
     *   - processed: boolean (was processing applied)
     *   - blocked: boolean (was a policy violation blocked)
     *   - diagnostics: object with retrieval/injection/policy info
     */
    const cfg = Object.assign({
      source: "canonical-pipeline",
      userMessage: null,
      memoryEnabled: true,
      throwOnViolation: false,
      context: null,
    }, options || {});

    const text = String(responseText || "").trim();
    const normalizedRuntime = buildNormalizedRuntimeView(runtimeMemory);
    const diagnostics = {
      source: cfg.source,
      memoryEnabled: cfg.memoryEnabled,
      inputLength: text.length,
      phases: {},
    };

    if (!text) {
      diagnostics.phases.validation = "skipped (empty text)";
      emit("CANONICAL_PIPELINE_SKIPPED", diagnostics);
      return { text, processed: false, blocked: false, diagnostics };
    }

    // PHASE 1: Memory capability detection (for self-knowledge questions)
    const capabilityIntent = detectMemoryCapabilityIntent(cfg.userMessage, normalizedRuntime);
    if (capabilityIntent && capabilityIntent.matched !== false) {
      const memoryCapability = buildMemoryCapabilityResponse(cfg.userMessage, {
        memoryContext: (cfg.context && cfg.context.memoryContext) || null,
        hasMemory: !!(cfg.context && cfg.context.memoryContext),
        source: cfg.source,
      });
      if (memoryCapability.matched) {
        diagnostics.phases.capability = "matched";
        emit("CANONICAL_PIPELINE_CAPABILITY_MATCHED", {
          ...diagnostics,
          intent: memoryCapability.intent,
        });
        if (memoryCapability.finalRouteLocked) {
          emitMemoryQualityDiagnostic("[FINAL_ROUTE_LOCKED]", {
            source: cfg.source,
            route: "canonical-capability-terminal",
          });
          emitMemoryQualityDiagnostic("[TERMINAL_RESPONSE_COMMITTED]", {
            source: cfg.source,
            route: "canonical-capability-terminal",
            finalRouteLocked: true,
          });
        }
        return {
          text: memoryCapability.text,
          processed: true,
          blocked: false,
          terminal: !!memoryCapability.finalRouteLocked,
          finalRouteLocked: !!memoryCapability.finalRouteLocked,
          diagnostics,
        };
      }
    }
    diagnostics.phases.capability = "not matched";

    const selfReferenceEntity = extractSelfReferenceEntityIntent(cfg.userMessage || "", normalizedRuntime);
    if (selfReferenceEntity && selfReferenceEntity.matched && isGenericEntityFallbackText(text, selfReferenceEntity.canonicalUserName)) {
      emitMemoryQualityDiagnostic("[SELF_REFERENCE_RESOLVED]", {
        source: cfg.source,
        entity: selfReferenceEntity.entity,
        canonicalUserName: selfReferenceEntity.canonicalUserName,
        queryType: selfReferenceEntity.queryType,
      });
      emitMemoryQualityDiagnostic("[CANONICAL_USER_NAME_MATCH]", {
        source: cfg.source,
        entity: selfReferenceEntity.entity,
        canonicalUserName: selfReferenceEntity.canonicalUserName,
      });
      emitMemoryQualityDiagnostic("[GENERIC_ENTITY_FALLBACK_BLOCKED]", {
        source: cfg.source,
        canonicalUserName: selfReferenceEntity.canonicalUserName,
        reason: "generic_entity_fallback_detected",
      });
      const synthesis = buildReflectiveMemorySynthesis(normalizedRuntime);
      return {
        text: synthesis.text,
        processed: true,
        blocked: false,
        terminal: true,
        finalRouteLocked: true,
        diagnostics,
      };
    }

    // PHASE 2: Memory retrieval (if enabled)
    const hasMemory = cfg.memoryEnabled && normalizedRuntime && (
      normalizedRuntime.long_term_memory.user_name ||
      (Array.isArray(normalizedRuntime.long_term_memory.preferences) && normalizedRuntime.long_term_memory.preferences.length > 0) ||
      (Array.isArray(normalizedRuntime.long_term_memory.active_projects) && normalizedRuntime.long_term_memory.active_projects.length > 0)
    );
    diagnostics.phases.retrieval = {
      enabled: cfg.memoryEnabled,
      hasMemory: hasMemory,
      memoryVersion: normalizedRuntime.memory_version,
      assistantModes: normalizedRuntime.assistant_modes || [],
    };
    emit("MEMORY_RETRIEVAL_PHASE", diagnostics.phases.retrieval);

    // PHASE 2.5: Synthesis-quality normalization
    const qualityNormalized = normalizeAssistantSynthesisText(text, {
      canonicalName: normalizedRuntime && normalizedRuntime.identity_resolution
        ? normalizedRuntime.identity_resolution.canonical_name
        : "",
      supersededNames: normalizedRuntime && normalizedRuntime.identity_resolution
        ? normalizedRuntime.identity_resolution.superseded_names
        : [],
      canonicalPrimaryPreference: normalizedRuntime && normalizedRuntime.identity_resolution
        ? normalizedRuntime.identity_resolution.canonical_primary_preference
        : "",
      supersededPreferences: normalizedRuntime && normalizedRuntime.identity_resolution
        ? normalizedRuntime.identity_resolution.superseded_preferences
        : [],
    });
    diagnostics.phases.synthesisQuality = {
      changed: qualityNormalized !== text,
      outputLength: qualityNormalized.length,
    };

    // PHASE 3: Identity enforcement and stateless-response blocking
    const enforced = enforceMemoryAwareResponse(qualityNormalized, {
      memoryEnabled: cfg.memoryEnabled,
      hasMemory: hasMemory,
      source: cfg.source,
    });
    diagnostics.phases.enforcement = {
      blocked: enforced.blocked,
      policy: "memory-identity",
    };
    if (enforced.blocked) {
      emit("CANONICAL_PIPELINE_POLICY_APPLIED", diagnostics);
      if (cfg.throwOnViolation) {
        const err = new Error("Response violated memory policy");
        err.code = POLICY_VIOLATION_CODE;
        err.name = POLICY_VIOLATION_NAME;
        err.replacementText = enforced.text;
        throw err;
      }
    }

    // PHASE 4: Return processed response
    const finalResponse = {
      text: enforced.text,
      processed: true,
      blocked: enforced.blocked,
      diagnostics,
    };
    emit("CANONICAL_PIPELINE_COMPLETE", {
      ...diagnostics,
      outputLength: enforced.text.length,
      replacementApplied: enforced.blocked,
    });
    traceCanonicalRuntimeState("pipeline_complete", {
      source: cfg.source,
      blocked: enforced.blocked,
      outputLength: enforced.text.length,
    });
    return finalResponse;
  }

  const AmiCorMemoryManager = {
    init,
    loadMemory,
    saveMemory,
    updateMemory,
    clearMemory,
    injectMemoryContext,
    buildMemoryOrchestrationPacket,
    detectMemoryCapabilityIntent,
    buildMemoryCapabilityResponse,
    enforceMemoryAwareResponse,
    enforceAssistantVisibleResponse,
    canonicalMemoryResponsePipeline,
    getNormalizedRuntimeView: function () {
      return clone(buildNormalizedRuntimeView(runtimeMemory));
    },
    normalizeAssistantSynthesisText,
    getStructuredMemory,
    getRuntimeAuditReport,
    POLICY_VIOLATION_CODE,
    POLICY_VIOLATION_NAME,
    getMetrics: function () {
      return Object.assign({}, runtimeMetrics, {
        memoryHitRate: runtimeMetrics.hits + runtimeMetrics.misses > 0
          ? runtimeMetrics.hits / (runtimeMetrics.hits + runtimeMetrics.misses)
          : 0,
        memoryVersion: MEMORY_VERSION,
        maxShortTermEntries: SHORT_TERM_LIMIT,
        maxLongTermEntries: MAX_LONG_TERM_TOTAL_ENTRIES,
        maxMemorySummarySize: MEMORY_CONTEXT_MAX_CHARS,
        maxInjectionTokenBudget: MAX_INJECTION_TOKEN_BUDGET,
      });
    },
  };

  if (typeof window !== "undefined") {
    window.AmiCorMemoryManager = AmiCorMemoryManager;
  }
  if (typeof module !== "undefined" && module.exports) {
    module.exports = AmiCorMemoryManager;
  }
})(typeof window !== "undefined" ? window : global);
