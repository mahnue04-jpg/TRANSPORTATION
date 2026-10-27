const test = require("node:test");
const assert = require("node:assert/strict");
const fs = require("fs");
const path = require("path");
const vm = require("vm");

function memoryStore(initial) {
  const data = Object.assign({}, initial);
  return {
    getItem(key) {
      return Object.prototype.hasOwnProperty.call(data, key) ? data[key] : null;
    },
    setItem(key, value) {
      data[key] = String(value);
    },
    removeItem(key) {
      delete data[key];
    },
    snapshot() {
      return Object.assign({}, data);
    },
  };
}

function createNode(tag) {
  const node = {
    tag,
    textContent: "",
    value: "",
    hidden: false,
    children: [],
    listeners: {},
    appendChild(child) {
      this.children.push(child);
      return child;
    },
    removeChild(child) {
      const index = this.children.indexOf(child);
      if (index >= 0) {
        this.children.splice(index, 1);
      }
      return child;
    },
    addEventListener(type, fn) {
      this.listeners[type] = fn;
    },
    getAttribute() {
      return null;
    },
  };
  Object.defineProperty(node, "firstChild", {
    get() {
      return this.children[0] || null;
    },
  });
  return node;
}

function texts(node) {
  const found = [];
  if (node.textContent) {
    found.push(String(node.textContent));
  }
  (node.children || []).forEach((child) => {
    found.push(...texts(child));
  });
  return found;
}

function boot(fetchImpl) {
  const nodes = {};
  [
    "session-status",
    "locale",
    "load-dashboard",
    "token",
    "clear-token",
    "refresh-arrivals",
    "lookup-form",
    "lookup-reference",
    "lookup-result",
    "housekeeping-form",
    "room-number",
    "housekeeping-status",
    "arrivals",
    "arrivals-empty",
    "rooms",
    "counts",
    "hotel-name",
    "fixture-date",
    "checkin-form",
    "checkin-reference",
    "checkin-result",
    "parking",
    "parking-empty",
    "parking-form",
    "stall-code",
    "parking-status",
  ].forEach((id) => {
    nodes[id] = createNode(id);
  });
  nodes["hotel-name"].textContent = "\u2014";
  nodes["fixture-date"].textContent = "\u2014";
  const requests = [];
  const sessionStorage = memoryStore();
  const localStorage = memoryStore();
  const document = {
    documentElement: { lang: "en" },
    querySelectorAll() {
      return [];
    },
    getElementById(id) {
      if (!nodes[id]) {
        throw new Error("missing " + id);
      }
      return nodes[id];
    },
    createElement: createNode,
  };
  const context = {
    window: { localStorage, sessionStorage },
    document,
    fetch(url, options) {
      requests.push({ url, options });
      return Promise.resolve(fetchImpl(url, options, requests));
    },
  };
  vm.runInNewContext(
    fs.readFileSync(path.join(__dirname, "../static/nova-stay360/stay360.js"), "utf8"),
    context,
  );
  return { nodes, requests, sessionStorage };
}

function jsonResponse(status, body) {
  return {
    ok: status >= 200 && status < 300,
    status,
    json() {
      return Promise.resolve(body);
    },
  };
}

function localeResponse() {
  return jsonResponse(200, {
    strings: {
      "nav.dashboard": "Hotel dashboard",
      "dashboard.rooms_not_ready": "Not ready, cleaning, or blocked",
      "readiness.not_ready": "Not ready",
      "readiness.ready": "Ready",
      "table.reference": "Reference",
      "nav.arrivals": "Arrivals",
      "table.eligibility": "Check-in",
      "errors.forbidden": "This role cannot open that Stay360 action.",
      "checkin.confirmation": "Confirmation code",
      "nav.checkin": "Mobile check-in",
      "checkin.no_door_access": "No door access",
      "checkin.no_payment": "No payment",
    },
  });
}

const harborBoard = {
  hotel_name: "Harbor Lantern Inn",
  fixture_date: "2026-10-26",
  counts: {
    reservations: 1,
    arrivals_today: 1,
    rooms_ready: 0,
    rooms_not_ready: 1,
    eligible_check_in: 0,
    simulated_checked_in: 0,
  },
  arrivals: [{
    reservation_reference: "STAY-HLI-1001",
    guest_label: "A. Lane",
    room_number: "214",
    arrival_mode: "flight",
    arrival_status: "scheduled",
    eta_local: "16:10",
    room_readiness: "not_ready",
    check_in_eligibility: "ineligible",
  }],
  rooms: [{
    room_number: "214",
    reservation_reference: "STAY-HLI-1001",
    guest_label: "A. Lane",
    housekeeping_status: "dirty",
    room_readiness: "not_ready",
  }],
};

async function flush() {
  for (let i = 0; i < 20; i += 1) {
    await Promise.resolve();
  }
}

test("refresh and check-in use the token in the field and the board follows the API", async () => {
  const ui = boot((url) => {
    if (String(url).includes("/locales/")) {
      return localeResponse();
    }
    if (String(url).includes("mobile-check-in")) {
      return jsonResponse(200, {
        reservation_reference: "STAY-HLI-1008",
        check_in_status: "simulated_checked_in",
        confirmation_code: "SIM-STAY-HLI-1008",
        door_access: "not_issued",
        payment_captured: false,
      });
    }
    return jsonResponse(200, harborBoard);
  });
  await flush();

  ui.nodes.token.value = "harbor-token";
  ui.nodes["load-dashboard"].listeners.click();
  await flush();
  const dashboardCall = ui.requests.find((call) => call.url === "/api/nova/stay360/dashboard");
  assert.equal(dashboardCall.options.headers.Authorization, "Bearer harbor-token");
  assert.ok(texts(ui.nodes.arrivals).includes("A. Lane"));
  assert.ok(texts(ui.nodes.counts).includes("Not ready, cleaning, or blocked"));
  assert.equal(texts(ui.nodes.counts).includes("Not ready"), false);

  ui.nodes.token.value = "cedar-token";
  ui.nodes["refresh-arrivals"].listeners.click();
  await flush();
  const refreshCall = ui.requests.find((call) => call.url === "/api/nova/stay360/arrivals/refresh");
  assert.equal(refreshCall.options.headers.Authorization, "Bearer cedar-token");

  ui.nodes["clear-token"].listeners.click();
  assert.equal(ui.sessionStorage.snapshot()["stay360.token"], undefined);
  assert.equal(texts(ui.nodes.arrivals).includes("A. Lane"), false);
  assert.equal(ui.nodes["hotel-name"].textContent, "\u2014");

  ui.nodes.token.value = "guest-token";
  ui.nodes["checkin-reference"].value = "STAY-HLI-1008";
  ui.nodes["checkin-form"].listeners.submit({ preventDefault() {} });
  await flush();
  assert.ok(texts(ui.nodes["checkin-result"]).includes("SIM-STAY-HLI-1008"));
  const checkinIndex = ui.requests.findIndex((call) => String(call.url).includes("mobile-check-in"));
  assert.ok(checkinIndex >= 0);
  assert.equal(ui.requests[checkinIndex].options.headers.Authorization, "Bearer guest-token");
  assert.ok(ui.requests.slice(checkinIndex + 1).some((call) => call.url === "/api/nova/stay360/dashboard"));
});

test("a failed dashboard load removes the previous hotel from the screen", async () => {
  let dashboardCalls = 0;
  const ui = boot((url) => {
    if (String(url).includes("/locales/")) {
      return localeResponse();
    }
    dashboardCalls += 1;
    if (dashboardCalls === 1) {
      return jsonResponse(200, harborBoard);
    }
    return jsonResponse(403, { detail: { code: "role_not_permitted" } });
  });
  await flush();
  ui.nodes.token.value = "harbor-token";
  ui.nodes["load-dashboard"].listeners.click();
  await flush();
  assert.ok(texts(ui.nodes.arrivals).includes("A. Lane"));

  ui.nodes.token.value = "cedar-token";
  ui.nodes["load-dashboard"].listeners.click();
  await flush();
  assert.equal(texts(ui.nodes.arrivals).includes("A. Lane"), false);
  assert.equal(ui.nodes["hotel-name"].textContent, "\u2014");
  assert.equal(ui.nodes["session-status"].textContent, "This role cannot open that Stay360 action.");
  assert.equal(ui.requests.filter((call) => call.url === "/api/nova/stay360/dashboard").at(-1).options.headers.Authorization, "Bearer cedar-token");
});
