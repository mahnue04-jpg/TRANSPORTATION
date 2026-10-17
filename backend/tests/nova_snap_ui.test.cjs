const test = require("node:test");
const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const vm = require("node:vm");

const root = path.join(__dirname, "../static/nova-snap");
const source = fs.readFileSync(path.join(root, "snap.js"), "utf8");
const html = fs.readFileSync(path.join(root, "index.html"), "utf8");
const css = fs.readFileSync(path.join(root, "snap.css"), "utf8");

function setup() {
  const nodes = new Map();
  const calls = [];
  const element = (id) => {
    if (!nodes.has(id)) {
      nodes.set(id, {
        value: "",
        hidden: false,
        disabled: false,
        checked: false,
        textContent: "",
        style: {},
        files: [],
        handlers: {},
        children: [],
        appendChild(node) { this.children.push(node); },
        replaceChildren() { this.children = []; },
        addEventListener(name, fn) { this.handlers[name] = fn; },
        setAttribute(name, value) { this[name] = value; },
        play() { return Promise.resolve(); }
      });
    }
    return nodes.get(id);
  };
  const fetch = async (url) => {
    calls.push(url);
    if (String(url).endsWith("/status")) {
      return { ok: true, json: async () => ({ calling_blocker: "No TURN relay is configured.", turn_configured: false, production_ready: false }) };
    }
    return { ok: false, status: 401, json: async () => ({ detail: "Authentication required" }) };
  };
  const navigator = { mediaDevices: { getUserMedia() { calls.push("getUserMedia"); return Promise.reject(Object.assign(new Error("denied"), { name: "NotAllowedError" })); } } };
  vm.runInNewContext(source, {
    document: { getElementById: element, hidden: false },
    window: { AmiCorSession: { getAccessToken() { return null; } } },
    localStorage: { getItem() { return "[]"; }, setItem() {} },
    fetch,
    navigator,
    URL: { createObjectURL() { return "blob:preview"; }, revokeObjectURL() {} },
    MediaRecorder: function () {},
    RTCPeerConnection: function () {},
    FormData: function () { this.append = () => {}; },
    setTimeout,
    clearTimeout
  });
  return { element, calls, navigator };
}

const settle = () => new Promise((resolve) => setImmediate(resolve));

test("snap page is a preview and does not borrow meeting screen share", () => {
  assert.match(html, /Not a production release/);
  assert.match(html, /not Synapse Meeting/);
  assert.match(html, /not Casting/);
  assert.equal(html.includes("getDisplayMedia"), false);
  assert.equal(source.includes("getDisplayMedia"), false);
  assert.equal(source.includes("innerHTML"), false);
  assert.equal(source.includes("setInterval"), false);
  assert.match(css, /min-height:\s*44px/);
  assert.equal(css.includes("@keyframes"), false);
});

test("camera permission is requested only from the button and denial does not retry", async () => {
  const view = setup();
  await settle();
  assert.equal(view.calls.includes("getUserMedia"), false);
  await view.element("camera-open").handlers.click();
  await settle();
  await settle();
  assert.equal(view.calls.filter((item) => item === "getUserMedia").length, 1);
  assert.match(view.element("camera-error").textContent, /denied/);
  assert.equal(view.element("record").disabled, true);
});

test("sharing stays disabled until a draft and explicit consent exist", async () => {
  const view = setup();
  await settle();
  assert.equal(view.element("share-capture").disabled, true);
  view.element("consent").checked = true;
  view.element("consent").handlers.change();
  assert.equal(view.element("share-capture").disabled, true);
  assert.match(view.element("network-note").textContent, /No TURN relay/);
});

test("call controls are labeled and the permission timer does not open a camera", () => {
  assert.match(html, /aria-label="Other person's video"/);
  assert.match(html, /aria-label="Your camera"/);
  assert.match(html, /aria-describedby="camera-help"/);
  assert.match(html, /role="tablist"/);
  assert.match(html, /snap-session\.js/);
  assert.match(html, /two separate devices/);
  assert.match(html, /No TURN server was purchased/);
  const tickStart = source.indexOf("async function tick");
  const tickEnd = source.indexOf("function bind");
  assert.equal(source.slice(tickStart, tickEnd).includes("getUserMedia"), false);
  assert.match(source, /Nothing was captured/);
  assert.match(source, /ArrowRight/);
});

test("simulated session exchanges descriptions without claiming a second device", () => {
  const session = require(path.join(root, "snap-session.js"));
  const caller = session.create("caller", { simulated: true });
  caller.apply("invite_out");
  caller.apply("media_granted");
  caller.apply("local_offer");
  caller.apply("local_ice");
  caller.apply("remote_answer");
  caller.apply("remote_ice");
  const evidence = caller.evidence();
  assert.equal(evidence.state, "connected");
  assert.equal(evidence.label, "simulated");
  assert.equal(evidence.media_path, "simulated-loopback");
  assert.equal(evidence.two_independent_devices, false);
  assert.equal(evidence.devices_used, 0);
  assert.equal(evidence.rtp_packets, 0);
  assert.equal(evidence.turn_purchased, false);
  const denied = session.create("caller", { simulated: true });
  denied.apply("invite_out");
  denied.apply("media_denied");
  assert.equal(denied.state, "permission_denied");
  assert.throws(() => denied.apply("local_offer"));
  denied.apply("hangup");
  assert.equal(denied.state, "ended");
  const callee = session.create("callee", { simulated: true });
  callee.apply("invite_in");
  callee.apply("decline");
  assert.equal(callee.state, "declined");
});

test("arrow keys move between snap sections", async () => {
  const view = setup();
  await settle();
  const event = {
    key: "ArrowRight",
    currentTarget: view.element("tab-chats"),
    preventDefault() { this.defaultPrevented = true; }
  };
  view.element("tab-chats").handlers.keydown(event);
  assert.equal(event.defaultPrevented, true);
  assert.equal(view.element("tab-camera")["aria-selected"], "true");
  assert.equal(view.element("panel-camera").hidden, false);
  assert.equal(view.element("panel-chats").hidden, true);
});
