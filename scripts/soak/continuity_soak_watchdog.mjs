#!/usr/bin/env node
"use strict";

import fs from "node:fs";
import path from "node:path";
import { chromium } from "playwright";

const START_URL = process.env.AMICOR_SOAK_URL || "http://127.0.0.1:8011/app/dispatch";
const BASE_ORIGIN = process.env.AMICOR_SOAK_BASE || "http://127.0.0.1:8011";
const DURATION_MIN = Number(process.env.AMICOR_SOAK_MINUTES || "5");
const OUT_DIR = process.env.AMICOR_SOAK_OUT_DIR || "artifacts/soak";

const NAV_TIMEOUT_MS = Number(process.env.AMICOR_SOAK_NAV_TIMEOUT_MS || "15000");
const SELECTOR_TIMEOUT_MS = Number(process.env.AMICOR_SOAK_SELECTOR_TIMEOUT_MS || "12000");
const MODAL_DISMISS_TIMEOUT_MS = Number(process.env.AMICOR_SOAK_MODAL_TIMEOUT_MS || "3000");
const RECONNECT_TIMEOUT_MS = Number(process.env.AMICOR_SOAK_RECONNECT_TIMEOUT_MS || "12000");
const ABOUT_BLANK_THRESHOLD_MS = Number(process.env.AMICOR_SOAK_ABOUT_BLANK_THRESHOLD_MS || "6000");
const NO_RENDER_THRESHOLD_MS = Number(process.env.AMICOR_SOAK_NO_RENDER_THRESHOLD_MS || "30000");
const LOOP_INTERVAL_MS = Number(process.env.AMICOR_SOAK_LOOP_INTERVAL_MS || "3000");

const SAFE_ROUTES = [
  "/app/dispatch",
  "/app/drivers",
  "/app/operations/medical-coordinator",
  "/app/ai-assistant",
];

const SAFE_SELECTORS = [
  "main",
  "[role='main']",
  "h2",
  "[data-runtime-root]",
  "#app",
];

function nowIso() {
  return new Date().toISOString();
}

function sleep(ms) {
  return new Promise((resolve) => setTimeout(resolve, ms));
}

function ensureDir(dir) {
  fs.mkdirSync(dir, { recursive: true });
}

function sanitizeFileStem(input) {
  return input.replace(/[^a-z0-9_-]+/gi, "_").slice(0, 80);
}

function logLine(msg) {
  process.stdout.write(`[SOAK ${nowIso()}] ${msg}\n`);
}

function pickWsState(summary) {
  if (!summary || typeof summary !== "object") return "unknown";
  const monitorReport = summary.monitorReport || {};
  const dataReport = summary.dataReport || {};
  const opsState = summary.opsState || {};
  const candidates = [
    opsState.websocketStatus,
    opsState.websocket,
    dataReport.websocketStatus,
    monitorReport.websocketStatus,
  ];
  const found = candidates.find((v) => typeof v === "string" && v.trim().length > 0);
  return found || "unknown";
}

function pickHydration(summary) {
  if (!summary || typeof summary !== "object") return "unknown";
  const opsState = summary.opsState || {};
  const hydration = opsState.hydration || {};
  if (hydration.integrityState) return String(hydration.integrityState);
  if (typeof hydration.opsHydrated === "boolean") return hydration.opsHydrated ? "hydrated" : "not_hydrated";
  return "unknown";
}

async function captureDiagnostics(page, telemetry, reason, outDir, detail = null) {
  const stamp = Date.now();
  const stem = sanitizeFileStem(`${stamp}_${reason}`);
  const screenshotPath = path.join(outDir, `${stem}.png`);
  const jsonPath = path.join(outDir, `${stem}.json`);

  const diag = {
    timestamp: nowIso(),
    reason,
    detail,
    url: page.url(),
    telemetrySnapshot: telemetry,
  };

  try {
    await page.screenshot({ path: screenshotPath, fullPage: true, timeout: 4000 });
    diag.screenshot = screenshotPath;
  } catch (err) {
    diag.screenshotError = String(err?.message || err);
  }

  try {
    const html = await page.content();
    diag.domLength = html.length;
    diag.domPreview = html.slice(0, 2000);
  } catch (err) {
    diag.domError = String(err?.message || err);
  }

  fs.writeFileSync(jsonPath, JSON.stringify(diag, null, 2), "utf8");
  logLine(`Captured diagnostics (${reason}) -> ${jsonPath}`);
  return { screenshotPath, jsonPath };
}

async function evaluateRuntimeSummary(page) {
  return page.evaluate(() => {
    const summary = {
      activeUrl: window.location.href,
      title: document.title,
      visibility: document.visibilityState,
      modalCount: document.querySelectorAll("[role='dialog'], dialog, .modal, .overlay").length,
      renderAnchorPresent: !!document.querySelector("main, [role='main'], h2, #app"),
      monitorReport: null,
      dataReport: null,
      opsState: null,
      hasAmicorMonitor: !!window.AmiCorMonitor,
      hasHealthIsfRuntime: !!window.HealthIsfRuntime,
    };

    try {
      if (window.AmiCorMonitor?.getReport) {
        summary.monitorReport = window.AmiCorMonitor.getReport();
      }
    } catch (_) {}

    try {
      const monitorEl = document.getElementById("amicor-monitor-data");
      const raw = monitorEl?.getAttribute("data-report");
      if (raw) summary.dataReport = JSON.parse(raw);
    } catch (_) {}

    try {
      if (window.HealthIsfRuntime?.getState) {
        summary.opsState = window.HealthIsfRuntime.getState();
      }
    } catch (_) {}

    return summary;
  });
}

async function safeNavigate(page, url, telemetry, outDir) {
  try {
    await page.goto(url, { waitUntil: "domcontentloaded", timeout: NAV_TIMEOUT_MS });
    if (page.url() === "about:blank") {
      telemetry.navigationFailures += 1;
      telemetry.lastFailureReason = `Navigation landed on about:blank for ${url}`;
      await captureDiagnostics(page, telemetry, "goto_about_blank", outDir, telemetry.lastFailureReason);
      throw new Error(`Navigation landed on about:blank for ${url}`);
    }
  } catch (err) {
    telemetry.navigationFailures += 1;
    telemetry.lastFailureReason = `Navigation failure for ${url}: ${String(err?.message || err)}`;
    await captureDiagnostics(page, telemetry, "goto_failure", outDir, telemetry.lastFailureReason);
    throw err;
  }

  let renderSeen = false;
  for (const selector of SAFE_SELECTORS) {
    try {
      await page.waitForSelector(selector, { timeout: Math.floor(SELECTOR_TIMEOUT_MS / SAFE_SELECTORS.length) });
      renderSeen = true;
      break;
    } catch (_) {}
  }
  if (!renderSeen) {
    telemetry.selectorTimeouts += 1;
    telemetry.lastFailureReason = `Selector timeout for ${url}`;
    await captureDiagnostics(page, telemetry, "selector_timeout", outDir, telemetry.lastFailureReason);
    throw new Error(`No render selector became visible after navigation to ${url}`);
  }
}

async function dismissModals(page, telemetry) {
  const start = Date.now();
  const closeSelectors = [
    "button[aria-label='Close']",
    "button:has-text('Close')",
    "button:has-text('Dismiss')",
    "button:has-text('Cancel')",
  ];
  while (Date.now() - start < MODAL_DISMISS_TIMEOUT_MS) {
    const count = await page.locator("[role='dialog'], dialog, .modal, .overlay").count();
    telemetry.modalCount = count;
    if (count === 0) return;
    let dismissed = false;
    for (const selector of closeSelectors) {
      const locator = page.locator(selector).first();
      if ((await locator.count()) > 0) {
        try {
          await locator.click({ timeout: 600 });
          dismissed = true;
          telemetry.modalDismissals += 1;
          break;
        } catch (_) {}
      }
    }
    if (!dismissed) {
      try {
        await page.keyboard.press("Escape", { timeout: 500 });
        dismissed = true;
        telemetry.modalDismissals += 1;
      } catch (_) {}
    }
    if (!dismissed) break;
    await sleep(200);
  }
  const remaining = await page.locator("[role='dialog'], dialog, .modal, .overlay").count();
  telemetry.modalCount = remaining;
  if (remaining > 0) telemetry.modalTimeouts += 1;
}

async function restartPage(context, oldPage, telemetry, outDir, reason) {
  telemetry.pageRestarts += 1;
  telemetry.pageReloadCount += 1;
  try {
    await captureDiagnostics(oldPage, telemetry, `watchdog_${reason}`, outDir, telemetry.lastFailureReason || null);
  } catch (_) {}
  try {
    await oldPage.close({ runBeforeUnload: false });
  } catch (_) {}
  const page = await context.newPage();
  page.setDefaultNavigationTimeout(NAV_TIMEOUT_MS);
  page.setDefaultTimeout(SELECTOR_TIMEOUT_MS);
  await wirePageListeners(page, telemetry);
  await safeNavigate(page, START_URL, telemetry, outDir);
  return page;
}

async function wirePageListeners(page, telemetry) {
  page.on("console", (msg) => {
    if (msg.type() === "error") {
      telemetry.runtimeExceptions += 1;
      telemetry.consoleErrors.push({ timestamp: nowIso(), text: msg.text() });
      if (telemetry.consoleErrors.length > 50) telemetry.consoleErrors.shift();
    }
  });
  page.on("pageerror", (err) => {
    telemetry.runtimeExceptions += 1;
    telemetry.pageErrors.push({ timestamp: nowIso(), message: String(err?.message || err) });
    if (telemetry.pageErrors.length > 50) telemetry.pageErrors.shift();
  });
  page.on("dialog", async (dialog) => {
    telemetry.modalDialogs += 1;
    try {
      await Promise.race([
        dialog.dismiss(),
        sleep(MODAL_DISMISS_TIMEOUT_MS).then(() => {
          throw new Error("dialog dismiss timeout");
        }),
      ]);
    } catch (_) {
      telemetry.modalTimeouts += 1;
    }
  });
  page.on("close", () => {
    telemetry.detachedContexts += 1;
  });
}

async function run() {
  ensureDir(OUT_DIR);
  const reportPath = path.join(OUT_DIR, `continuity_soak_report_${Date.now()}.json`);

  const telemetry = {
    startedAt: nowIso(),
    durationMinutes: DURATION_MIN,
    activeUrl: START_URL,
    websocketState: "unknown",
    reconnectCount: 0,
    lastSuccessfulRenderTimestamp: null,
    hydrationStatus: "unknown",
    modalCount: 0,
    runtimeExceptions: 0,
    pageReloadCount: 0,
    pageRestarts: 0,
    navigationFailures: 0,
    selectorTimeouts: 0,
    modalTimeouts: 0,
    modalDismissals: 0,
    modalDialogs: 0,
    detachedContexts: 0,
    lastFailureReason: null,
    consoleErrors: [],
    pageErrors: [],
    samples: [],
  };

  const browser = await chromium.launch({ headless: true });
  const context = await browser.newContext({
    viewport: { width: 1440, height: 900 },
  });

  let page = await context.newPage();
  page.setDefaultNavigationTimeout(NAV_TIMEOUT_MS);
  page.setDefaultTimeout(SELECTOR_TIMEOUT_MS);
  await wirePageListeners(page, telemetry);

  const timeoutAt = Date.now() + DURATION_MIN * 60_000;
  let routeIndex = 0;
  let aboutBlankSince = null;
  let lastRenderAt = Date.now();

  await safeNavigate(page, START_URL, telemetry, OUT_DIR);

  while (Date.now() < timeoutAt) {
    const route = SAFE_ROUTES[routeIndex % SAFE_ROUTES.length];
    routeIndex += 1;
    const target = `${BASE_ORIGIN}${route}`;
    try {
      await safeNavigate(page, target, telemetry, OUT_DIR);
      await dismissModals(page, telemetry);
    } catch (err) {
      logLine(`Route navigation failed: ${err?.message || err}`);
      telemetry.reconnectCount += 1;
      page = await restartPage(context, page, telemetry, OUT_DIR, "navigation");
      await sleep(Math.min(RECONNECT_TIMEOUT_MS, 3000));
      continue;
    }

    const summary = await evaluateRuntimeSummary(page);
    telemetry.activeUrl = summary.activeUrl;
    telemetry.websocketState = pickWsState(summary);
    telemetry.hydrationStatus = pickHydration(summary);
    telemetry.modalCount = Number(summary.modalCount || 0);
    if (summary.renderAnchorPresent) {
      lastRenderAt = Date.now();
      telemetry.lastSuccessfulRenderTimestamp = nowIso();
    }

    if (summary.activeUrl === "about:blank") {
      if (!aboutBlankSince) aboutBlankSince = Date.now();
    } else {
      aboutBlankSince = null;
    }

    if (aboutBlankSince && Date.now() - aboutBlankSince > ABOUT_BLANK_THRESHOLD_MS) {
      logLine("Watchdog detected persistent about:blank; restarting automation page only");
      telemetry.reconnectCount += 1;
      page = await restartPage(context, page, telemetry, OUT_DIR, "about_blank");
      aboutBlankSince = null;
      await sleep(Math.min(RECONNECT_TIMEOUT_MS, 3000));
      continue;
    }

    if (Date.now() - lastRenderAt > NO_RENDER_THRESHOLD_MS) {
      logLine("Watchdog detected no render activity; restarting automation page only");
      telemetry.reconnectCount += 1;
      page = await restartPage(context, page, telemetry, OUT_DIR, "no_render_activity");
      lastRenderAt = Date.now();
      await sleep(Math.min(RECONNECT_TIMEOUT_MS, 3000));
      continue;
    }

    telemetry.samples.push({
      timestamp: nowIso(),
      url: telemetry.activeUrl,
      websocketState: telemetry.websocketState,
      hydrationStatus: telemetry.hydrationStatus,
      modalCount: telemetry.modalCount,
      runtimeExceptions: telemetry.runtimeExceptions,
      pageReloadCount: telemetry.pageReloadCount,
      reconnectCount: telemetry.reconnectCount,
    });
    if (telemetry.samples.length > 500) telemetry.samples.shift();

    await sleep(LOOP_INTERVAL_MS);
  }

  telemetry.endedAt = nowIso();
  telemetry.outcome = telemetry.pageRestarts > 0 || telemetry.navigationFailures > 0 ? "recovered_with_watchdog" : "stable";

  fs.writeFileSync(reportPath, JSON.stringify(telemetry, null, 2), "utf8");
  logLine(`Continuity soak completed -> ${reportPath}`);

  await context.close();
  await browser.close();

  return { reportPath, telemetry };
}

run()
  .then(({ telemetry, reportPath }) => {
    const summary = {
      reportPath,
      outcome: telemetry.outcome,
      reconnectCount: telemetry.reconnectCount,
      pageRestarts: telemetry.pageRestarts,
      navigationFailures: telemetry.navigationFailures,
      selectorTimeouts: telemetry.selectorTimeouts,
      modalTimeouts: telemetry.modalTimeouts,
      runtimeExceptions: telemetry.runtimeExceptions,
      finalWebsocketState: telemetry.websocketState,
      finalHydrationStatus: telemetry.hydrationStatus,
      lastSuccessfulRenderTimestamp: telemetry.lastSuccessfulRenderTimestamp,
    };
    process.stdout.write(`${JSON.stringify(summary, null, 2)}\n`);
    process.exit(0);
  })
  .catch((err) => {
    process.stderr.write(`Soak failed: ${String(err?.message || err)}\n`);
    process.exit(1);
  });
