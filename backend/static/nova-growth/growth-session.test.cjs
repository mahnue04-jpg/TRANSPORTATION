const test = require("node:test");
const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const vm = require("node:vm");

const source = fs.readFileSync(path.join(__dirname, "growth.js"), "utf8");
const html = fs.readFileSync(path.join(__dirname, "index.html"), "utf8");
const css = fs.readFileSync(path.join(__dirname, "growth.css"), "utf8");

function harness({ token = "", meStatus = 200 } = {}) {
  const store = new Map(token ? [["amicor_growth_token", token]] : []);
  const elements = new Map();
  const inputs = ["login-email", "login-password"].map((id) => get(id));
  function get(id) {
    if (!elements.has(id)) {
      const label = { hidden: false };
      elements.set(id, {
        id, hidden: false, disabled: false, value: "", innerHTML: "", textContent: "",
        className: "", handlers: {},
        closest() { return label; },
        querySelectorAll() { return id === "login-form" ? inputs : []; },
        addEventListener(type, cb) { this.handlers[type] = cb; },
      });
    }
    return elements.get(id);
  }
  // The form and all other controls are simple DOM doubles. No network is used.
  const fetched = [];
  const context = {
    document: { getElementById: get },
    window: { NovaReceptionist: null },
    localStorage: {
      getItem(k) { return store.get(k) || null; },
      setItem(k, v) { store.set(k, v); },
      removeItem(k) { store.delete(k); },
    },
    fetch: async (url) => {
      fetched.push(url);
      if (url === "/api/auth/me") {
        return {
          ok: meStatus === 200, status: meStatus, statusText: "Error",
          text: async () => JSON.stringify(meStatus === 200
            ? { email: "admin@amicor.local", role: "admin" }
            : { detail: "Session unavailable" }),
        };
      }
      return { ok: true, status: 200, text: async () => JSON.stringify(
        url.includes("/analytics") ? { inquiries: 0 } :
        url.includes("/conversations") ? { items: [] } : { items: [] }
      ) };
    },
    Date, setTimeout, console,
  };
  vm.runInNewContext(source, context, { filename: "growth.js" });
  return { get, store, fetched };
}

async function flush() {
  await new Promise((resolve) => setImmediate(resolve));
  await new Promise((resolve) => setImmediate(resolve));
}

test("restored valid token requires a verified owner and only displays sign out", async () => {
  const h = harness({ token: "valid", meStatus: 200 });
  await flush();
  assert.ok(h.fetched.includes("/api/auth/me"));
  assert.equal(h.get("login-submit").hidden, true);
  assert.equal(h.get("sign-out").hidden, false);
  assert.match(h.get("session-meta").textContent, /admin@amicor.local/);
});

test("expired stored token is cleared and the user can sign in", async () => {
  const h = harness({ token: "expired", meStatus: 401 });
  await flush();
  assert.equal(h.store.has("amicor_growth_token"), false);
  assert.equal(h.get("sign-out").hidden, true);
  assert.equal(h.get("login-submit").hidden, false);
  assert.match(h.get("session-meta").textContent, /session expired/i);
});

test("temporary backend failure is not mistaken for bad credentials", async () => {
  const h = harness({ token: "saved", meStatus: 502 });
  await flush();
  assert.equal(h.store.get("amicor_growth_token"), "saved");
  assert.equal(h.get("sign-out").hidden, true);
  assert.equal(h.get("login-submit").hidden, false);
  assert.match(h.get("session-meta").textContent, /unable to verify/i);
});

test("sign out clears saved token, identity, and password field", async () => {
  const h = harness({ token: "valid", meStatus: 200 });
  await flush();
  h.get("login-password").value = "temporary";
  h.get("sign-out").handlers.click();
  assert.equal(h.store.has("amicor_growth_token"), false);
  assert.equal(h.get("login-password").value, "");
  assert.equal(h.get("sign-out").hidden, true);
  assert.equal(h.get("login-submit").hidden, false);
});

test("website setup uses plain language but preserves secure element IDs", () => {
  assert.match(html, /Add Nova Chat to Your Website/);
  assert.match(html, /Set Up Website Chat/);
  assert.match(html, /Website Connection Key/);
  assert.match(html, /id="widget-token"/);
  assert.match(html, /id="create-widget"/);
  assert.match(css, /\[hidden\]\s*\{\s*display:\s*none\s*!important/);
});
