"use strict";
(function () {
  var $ = function (id) { return document.getElementById(id); };
  var state = {
    me: null,
    status: null,
    conversations: [],
    activeId: null,
    after: 0,
    captures: [],
    pendingCapture: null,
    draftId: null,
    call: null,
    pc: null,
    pcs: {},
    localStream: null,
    cameraStream: null,
    remoteNodes: [],
    remoteIce: {},
    iceConfig: null,
    videoHeld: false,
    facing: "user",
    micOn: false,
    signalAfter: 0,
    session: null,
    failures: 0,
    timer: null,
    recording: null,
    lastMessageId: null,
    myLastMessageId: null
  };

  function text(id, value) {
    var el = $(id);
    if (el) el.textContent = value || "";
  }
  function show(id, on) {
    var el = $(id);
    if (el) el.hidden = !on;
  }
  function token() {
    return window.AmiCorSession && window.AmiCorSession.getAccessToken && window.AmiCorSession.getAccessToken();
  }
  function outbox() {
    try { return JSON.parse(localStorage.getItem("nova_snap_outbox") || "[]"); }
    catch (err) { return []; }
  }
  function saveOutbox(rows) {
    try { localStorage.setItem("nova_snap_outbox", JSON.stringify(rows)); } catch (err) {}
  }
  function banner(message) { text("status-banner", message || ""); }

  async function api(path, options) {
    var headers = options && options.headers ? options.headers : {};
    if (!(options && options.body instanceof FormData)) headers["Content-Type"] = headers["Content-Type"] || "application/json";
    if (token()) headers.Authorization = "Bearer " + token();
    var response = await fetch("/api/nova/snap" + path, {
      method: (options && options.method) || "GET",
      headers: headers,
      body: options && options.body,
      cache: "no-store"
    });
    var payload = {};
    try { payload = await response.json(); } catch (err) { payload = {}; }
    if (!response.ok) {
      var detail = payload.detail;
      if (detail && typeof detail !== "string") detail = "Request failed";
      var error = new Error(detail || "Request failed");
      error.status = response.status;
      throw error;
    }
    return payload;
  }

  function renderContacts(rows) {
    var list = $("contact-list");
    if (!list) return;
    list.replaceChildren();
    rows.forEach(function (row) {
      var item = document.createElement("li");
      item.textContent = row.peer_label + " · " + row.status + " · " + row.direction;
      if (row.status === "pending" && row.direction === "incoming") {
        var accept = document.createElement("button");
        accept.type = "button";
        accept.textContent = "Accept";
        accept.addEventListener("click", function () { respond(row.contact_id, true); });
        var decline = document.createElement("button");
        decline.type = "button";
        decline.textContent = "Decline";
        decline.addEventListener("click", function () { respond(row.contact_id, false); });
        item.appendChild(accept);
        item.appendChild(decline);
      }
      if (row.status === "accepted") {
        var open = document.createElement("button");
        open.type = "button";
        open.textContent = "Message";
        open.addEventListener("click", function () { openDirect(row.peer_user_id); });
        item.appendChild(open);
      }
      list.appendChild(item);
    });
  }

  function renderConversations() {
    var list = $("conversation-list");
    if (!list) return;
    list.replaceChildren();
    var unread = 0;
    state.conversations.forEach(function (row) {
      unread += row.unread || 0;
      var item = document.createElement("li");
      var button = document.createElement("button");
      button.type = "button";
      button.textContent = (row.kind === "group" ? "Group: " : "") + row.title + (row.unread ? " (" + row.unread + " unread)" : "");
      button.addEventListener("click", function () { selectConversation(row.conversation_id); });
      item.appendChild(button);
      list.appendChild(item);
    });
    text("unread", unread ? unread + " unread" : "");
  }

  function renderMessages(rows) {
    var thread = $("thread");
    if (!thread) return;
    rows.forEach(function (row) {
      if (row.seq > state.after) state.after = row.seq;
      var item = document.createElement("li");
      var body = row.removed ? "Message removed" : row.body;
      item.textContent = row.sender_label + ": " + body + (row.untrusted_links ? " (link kept as text)" : "") + " · " + row.delivery;
      if (row.kind === "capture" && row.capture_id && !row.removed) {
        var play = document.createElement("button");
        play.type = "button";
        play.textContent = "Play private capture";
        play.addEventListener("click", function () { playCapture(row.capture_id); });
        item.appendChild(play);
      }
      thread.appendChild(item);
      state.lastMessageId = row.message_id;
      if (state.me && row.sender_user_id === state.me.user_id) state.myLastMessageId = row.message_id;
    });
  }

  async function refreshContacts() {
    renderContacts(await api("/contacts"));
  }
  async function refreshConversations() {
    state.conversations = await api("/conversations");
    renderConversations();
  }
  async function selectConversation(id) {
    state.activeId = id;
    state.after = 0;
    state.lastMessageId = null;
    state.myLastMessageId = null;
    var thread = $("thread");
    if (thread) thread.replaceChildren();
    var match = state.conversations.filter(function (row) { return row.conversation_id === id; })[0];
    text("thread-title", match ? match.title : "Conversation");
    var rows = await api("/conversations/" + id + "/messages");
    renderMessages(rows);
    if (state.lastMessageId) {
      try { await api("/conversations/" + id + "/read", { method: "POST", body: JSON.stringify({ message_id: state.lastMessageId }) }); } catch (err) {}
    }
    syncShareButton();
  }
  async function respond(id, accept) {
    await api("/contacts/" + id + "/respond", { method: "POST", body: JSON.stringify({ accept: accept }) });
    await refreshContacts();
    banner(accept ? "Contact accepted." : "Contact declined.");
  }
  async function openDirect(userId) {
    var row = await api("/conversations/direct", { method: "POST", body: JSON.stringify({ user_id: userId }) });
    await refreshConversations();
    await selectConversation(row.conversation_id);
    showPanel("chats");
  }

  async function sendBody(body, clientId) {
    if (!state.activeId) throw new Error("Choose a conversation first.");
    return api("/conversations/" + state.activeId + "/messages", {
      method: "POST",
      body: JSON.stringify({ body: body, client_message_id: clientId })
    });
  }
  function clientId() {
    return "m" + Date.now().toString(36) + Math.random().toString(36).slice(2, 10);
  }
  async function flushOutbox() {
    var pending = outbox();
    var kept = [];
    for (var i = 0; i < pending.length; i += 1) {
      var item = pending[i];
      if (item.conversation_id !== state.activeId) { kept.push(item); continue; }
      try {
        state.activeId = item.conversation_id;
        var saved = await sendBody(item.body, item.client_message_id);
        renderMessages([saved]);
      } catch (err) {
        kept.push(item);
      }
    }
    saveOutbox(kept);
    if (kept.length) banner("Some messages are still waiting to send.");
  }

  function showPanel(name) {
    ["chats", "camera", "calls"].forEach(function (panel) {
      show("panel-" + panel, panel === name);
      var tab = $("tab-" + panel);
      if (!tab) return;
      var on = panel === name;
      tab.setAttribute("aria-pressed", on ? "true" : "false");
      tab.setAttribute("aria-selected", on ? "true" : "false");
    });
  }
  function moveTab(event) {
    var names = ["chats", "camera", "calls"];
    var current = -1;
    for (var i = 0; i < names.length; i += 1) {
      if ($("tab-" + names[i]) === event.currentTarget) current = i;
    }
    if (current < 0) return;
    var next = current;
    if (event.key === "ArrowRight") next = (current + 1) % names.length;
    else if (event.key === "ArrowLeft") next = (current + names.length - 1) % names.length;
    else if (event.key === "Home") next = 0;
    else if (event.key === "End") next = names.length - 1;
    else return;
    if (event.preventDefault) event.preventDefault();
    showPanel(names[next]);
    var tab = $("tab-" + names[next]);
    if (tab && tab.focus) tab.focus();
  }
  function sessionApi() {
    if (typeof NovaSnapCallSession !== "undefined" && NovaSnapCallSession) return NovaSnapCallSession;
    return window.NovaSnapCallSession || null;
  }
  function note(event) {
    if (!state.session || !state.session.apply) return;
    try { state.session.apply(event); } catch (err) {}
  }
  function iceServers(config) {
    var turn = !!(config && config.turn_configured);
    var servers = (config && config.ice_servers) || [];
    var kept = [];
    servers.forEach(function (server) {
      var urls = server && server.urls;
      var list = Array.isArray(urls) ? urls : [urls];
      var usable = list.filter(function (url) {
        var value = String(url || "");
        if (/^turns?:/i.test(value)) return turn;
        return /^stuns?:/i.test(value);
      });
      if (!usable.length) return;
      var next = { urls: usable };
      if (turn && server.username) {
        next.username = server.username;
        next.credential = server.credential;
      }
      kept.push(next);
    });
    return kept;
  }

  function stopStream(stream) {
    if (!stream) return;
    stream.getTracks().forEach(function (track) { track.stop(); });
  }
  function cameraError(message) {
    text("camera-error", message);
    var record = $("record");
    if (record) record.disabled = true;
  }
  async function openCamera() {
    text("camera-error", "");
    if (!navigator.mediaDevices || !navigator.mediaDevices.getUserMedia) {
      cameraError("This browser cannot open the camera.");
      return;
    }
    try {
      stopStream(state.cameraStream);
      state.cameraStream = await navigator.mediaDevices.getUserMedia({
        video: { facingMode: state.facing },
        audio: state.micOn
      });
      var preview = $("camera-preview");
      preview.srcObject = state.cameraStream;
      preview.hidden = false;
      ["camera-flip", "mic-toggle", "record", "camera-close"].forEach(function (id) {
        var el = $(id);
        if (el) el.disabled = false;
      });
      text("mic-toggle", state.micOn ? "Microphone on" : "Microphone off");
    } catch (err) {
      cameraError(err && err.name === "NotAllowedError" ? "Camera or microphone permission was denied." : "The camera could not start.");
    }
  }
  function closeCamera() {
    if (state.recording) {
      try { state.recording.stop(); } catch (err) {}
      state.recording = null;
    }
    stopStream(state.cameraStream);
    state.cameraStream = null;
    var preview = $("camera-preview");
    if (preview) { preview.srcObject = null; preview.hidden = true; }
    ["camera-flip", "mic-toggle", "record", "camera-close"].forEach(function (id) {
      var el = $(id);
      if (el) el.disabled = true;
    });
  }
  function rememberClip(blob, duration) {
    if (state.pendingCapture) URL.revokeObjectURL(state.pendingCapture.url);
    var url = URL.createObjectURL(blob);
    state.pendingCapture = { blob: blob, url: url, duration: duration || 0, type: blob.type };
    var replay = $("replay");
    replay.src = url;
    replay.hidden = false;
    var save = $("save-draft");
    if (save) save.disabled = false;
    syncShareButton();
  }
  function recordClip() {
    if (!state.cameraStream || typeof MediaRecorder === "undefined") {
      cameraError("Recording is not available in this browser.");
      return;
    }
    var chunks = [];
    var started = Date.now();
    var recorder;
    try {
      recorder = new MediaRecorder(state.cameraStream, { mimeType: "video/webm" });
    } catch (err) {
      try { recorder = new MediaRecorder(state.cameraStream); } catch (inner) {
        cameraError("Recording is not available in this browser.");
        return;
      }
    }
    state.recording = recorder;
    recorder.ondataavailable = function (event) { if (event.data && event.data.size) chunks.push(event.data); };
    recorder.onstop = function () {
      state.recording = null;
      var blob = new Blob(chunks, { type: recorder.mimeType || "video/webm" });
      if (blob.size > 8000000) {
        cameraError("That clip is over the 8 MB preview limit.");
        return;
      }
      rememberClip(blob, Math.min(15000, Date.now() - started));
    };
    recorder.start(200);
    var record = $("record");
    if (record) record.disabled = true;
    setTimeout(function () {
      if (state.recording === recorder && recorder.state === "recording") recorder.stop();
      if (record) record.disabled = false;
    }, 15000);
  }
  async function saveDraft() {
    if (!state.pendingCapture) return;
    var body = new FormData();
    var type = state.pendingCapture.type || "video/webm";
    body.append("upload", state.pendingCapture.blob, type.indexOf("image/") === 0 ? "snap.jpg" : "snap.webm");
    body.append("duration_ms", String(type.indexOf("video/") === 0 ? state.pendingCapture.duration : 0));
    var saved = await api("/captures", { method: "POST", body: body, headers: {} });
    state.draftId = saved.capture_id;
    banner("Private draft saved. It is not shared.");
    syncShareButton();
    await refreshCaptures();
  }
  function syncShareButton() {
    var button = $("share-capture");
    var consent = $("consent");
    if (!button) return;
    button.disabled = !(state.draftId && state.activeId && consent && consent.checked);
  }
  async function refreshCaptures() {
    state.captures = await api("/captures");
    var list = $("capture-list");
    if (!list) return;
    list.replaceChildren();
    state.captures.forEach(function (row) {
      var item = document.createElement("li");
      item.textContent = row.status + " · " + row.content_type + " · " + row.byte_size + " bytes";
      var remove = document.createElement("button");
      remove.type = "button";
      remove.textContent = "Delete draft";
      remove.addEventListener("click", async function () {
        await api("/captures/" + row.capture_id, { method: "DELETE" });
        if (state.draftId === row.capture_id) state.draftId = null;
        syncShareButton();
        await refreshCaptures();
      });
      item.appendChild(remove);
      list.appendChild(item);
    });
  }
  async function playCapture(id) {
    var headers = {};
    if (token()) headers.Authorization = "Bearer " + token();
    var response = await fetch("/api/nova/snap/captures/" + id + "/media", { headers: headers, cache: "no-store" });
    if (!response.ok) { banner("That private capture is not available."); return; }
    var blob = await response.blob();
    var replay = $("replay");
    replay.src = URL.createObjectURL(blob);
    replay.hidden = false;
  }

  function guidance(status) {
    var note = $("network-note");
    if (!note || !status) return;
    note.textContent = status.calling_blocker || note.textContent;
  }
  async function placeCall(media) {
    if (!state.activeId) { banner("Open a conversation before calling."); return; }
    text("call-error", "");
    state.call = await api("/calls", { method: "POST", body: JSON.stringify({ conversation_id: state.activeId, media: media }) });
    state.signalAfter = 0;
    state.remoteIce = {};
    var sessions = sessionApi();
    state.session = sessions ? sessions.create("caller") : null;
    note("invite_out");
    showCall(true);
    text("call-state", "Calling. Your browser will ask for the microphone" + (media === "video" ? " and camera" : "") + ". Nothing is captured if you deny the prompt.");
    await attachMedia(media, true);
  }
  function showCall(on) {
    show("call-panel", on);
    showPanel("calls");
  }
  function remotePeers() {
    var mine = state.me && state.me.user_id;
    var people = (state.call && state.call.participants) || [];
    return people.filter(function (person) {
      return person.user_id && person.user_id !== mine && person.state !== "left" && person.state !== "declined";
    });
  }
  function eachPc() {
    var list = [];
    Object.keys(state.pcs).forEach(function (id) { list.push(state.pcs[id]); });
    if (!list.length && state.pc) list.push(state.pc);
    return list;
  }
  function pcForSender(senderId) {
    if (senderId && state.pcs[senderId]) return state.pcs[senderId];
    var ids = Object.keys(state.pcs);
    if (ids.length === 1) return state.pcs[ids[0]];
    return state.pc || null;
  }
  function parseWrapped(payload) {
    if (!payload || payload.charAt(0) !== "{") return null;
    try {
      var body = JSON.parse(payload);
      if (!body || !body.target) return null;
      if (typeof body.sdp === "string" || body.candidate) return body;
    } catch (err) {}
    return null;
  }
  function attachRemote(stream, remoteId) {
    var remote = $("remote-video");
    var slot = null;
    var nodes = [remote].concat(state.remoteNodes);
    for (var i = 0; i < nodes.length; i += 1) {
      var node = nodes[i];
      if (!node) continue;
      if (stream && node.srcObject === stream) { slot = node; break; }
      if (remoteId && node._remoteId === remoteId) { slot = node; break; }
    }
    if (!slot) {
      slot = remote && !remote.srcObject ? remote : document.createElement("video");
      if (slot !== remote) {
        slot.autoplay = true;
        slot.playsInline = true;
        slot.setAttribute("playsinline", "");
        var panel = $("call-panel");
        if (panel) panel.appendChild(slot);
        state.remoteNodes.push(slot);
      }
    }
    if (remoteId) slot._remoteId = remoteId;
    if (slot.srcObject && stream && slot.srcObject !== stream) {
      var incoming = stream.getTracks();
      for (var t = 0; t < incoming.length; t += 1) {
        var have = slot.srcObject.getTracks();
        var seen = false;
        for (var h = 0; h < have.length; h += 1) {
          if (have[h] === incoming[t]) seen = true;
        }
        if (!seen) slot.srcObject.addTrack(incoming[t]);
      }
    } else {
      slot.srcObject = stream;
    }
    slot.hidden = false;
    if (slot.play) slot.play().catch(function () { show("enable-sound", true); });
  }
  function buildPc(remoteId, config, wrapped) {
    var pc = new RTCPeerConnection({ iceServers: iceServers(config) });
    pc._remoteId = remoteId;
    pc._wrapped = !!wrapped;
    pc._descSent = false;
    pc._localIce = [];
    if (state.localStream) {
      state.localStream.getTracks().forEach(function (track) { pc.addTrack(track, state.localStream); });
    }
    pc.onicecandidate = function (event) {
      if (!event.candidate) return;
      var payload = pc._wrapped
        ? JSON.stringify({ target: pc._remoteId, candidate: event.candidate })
        : JSON.stringify(event.candidate);
      if (!pc._descSent) pc._localIce.push(payload);
      else sendSignal("ice", payload).then(function (ok) { if (ok) note("local_ice"); });
    };
    pc.ontrack = function (event) {
      var stream = (event.streams && event.streams[0]) || new MediaStream([event.track]);
      attachRemote(stream, pc._remoteId);
    };
    pc.onconnectionstatechange = function () {
      var value = pc.connectionState;
      if (value === "failed") note("ice_failed");
      if (value === "failed" || value === "disconnected") {
        text("call-error", "The direct connection failed. A relay server is not configured, so this network may be unable to complete the call.");
        text("call-quality", "Network quality: disconnected");
        sendSignal("quality", "disconnected");
      } else if (value === "connected") {
        text("call-quality", "Network quality: good");
        text("call-adapt", "This browser reports a direct path. Two separate devices have not been verified.");
      }
    };
    if (remoteId) state.pcs[remoteId] = pc;
    return pc;
  }
  async function releaseLocalIce(pc) {
    pc._descSent = true;
    var queued = (pc._localIce || []).splice(0);
    for (var i = 0; i < queued.length; i += 1) {
      if (await sendSignal("ice", queued[i])) note("local_ice");
    }
  }
  async function publishDescription(pc, kind, sdp) {
    var payload = pc._wrapped ? JSON.stringify({ target: pc._remoteId, sdp: sdp || "" }) : (sdp || "");
    if (!(await sendSignal(kind, payload))) return false;
    note(kind === "answer" ? "local_answer" : "local_offer");
    await releaseLocalIce(pc);
    return true;
  }
  async function restartPeer(pc) {
    var offer;
    try {
      offer = await pc.createOffer({ iceRestart: true });
    } catch (err) {
      if (pc.signalingState !== "have-local-offer" && pc.signalingState !== "have-remote-offer") {
        text("call-error", "The call could not update the connection.");
        return;
      }
      try { await pc.setLocalDescription({ type: "rollback" }); } catch (ignore) {}
      try {
        offer = await pc.createOffer({ iceRestart: true });
      } catch (again) {
        text("call-error", "The call could not update the connection.");
        return;
      }
    }
    var payload = pc._wrapped ? JSON.stringify({ target: pc._remoteId, sdp: offer.sdp || "" }) : (offer.sdp || "");
    if (!(await sendSignal("renego", payload))) return;
    if (pc.signalingState === "have-local-offer" || pc.signalingState === "have-remote-offer") {
      try { await pc.setLocalDescription({ type: "rollback" }); } catch (ignore) {}
    }
    try {
      await pc.setLocalDescription(offer);
    } catch (err) {
      text("call-error", "The call could not update the connection.");
      return;
    }
    pc._descSent = false;
    pc._localIce = [];
    note("local_offer");
    await releaseLocalIce(pc);
  }
  function stashRemoteIce(senderId, candidate) {
    var key = senderId || "_";
    if (!state.remoteIce[key]) state.remoteIce[key] = [];
    state.remoteIce[key].push(candidate);
  }
  async function flushRemoteIce(senderId, pc) {
    var key = senderId || "_";
    var queued = state.remoteIce[key] || [];
    state.remoteIce[key] = [];
    for (var i = 0; i < queued.length; i += 1) {
      try { await pc.addIceCandidate(queued[i]); note("remote_ice"); } catch (err) {}
    }
  }
  async function denyCallMedia(err) {
    note("media_denied");
    text("call-error", err && err.name === "NotAllowedError"
      ? "Microphone or camera permission was denied. Nothing was captured. Snap will not ask again until you start or accept another call."
      : "Microphone or camera could not start. Nothing was captured.");
    var error = $("call-error");
    if (error && error.focus) error.focus();
    if (!state.call) return;
    try { await sendSignal("media", "denied"); } catch (ignore) {}
    try {
      state.call = await api("/calls/" + state.call.call_id + "/end", { method: "POST" });
      text("call-state", "Call ended · permission_denied");
    } catch (ignore) {}
  }
  async function attachMedia(media, isCaller) {
    if (!navigator.mediaDevices || !navigator.mediaDevices.getUserMedia || typeof RTCPeerConnection === "undefined") {
      text("call-error", "This browser cannot place a real audio or video call. Signaling can still be tested.");
      return;
    }
    var stream;
    try {
      stream = await navigator.mediaDevices.getUserMedia({ audio: true, video: media === "video" });
    } catch (err) {
      await denyCallMedia(err);
      return;
    }
    note("media_granted");
    try { await sendSignal("media", "granted"); } catch (err) {}
    eachPc().forEach(function (pc) { try { pc.close(); } catch (err) {} });
    state.pcs = {};
    state.pc = null;
    state.remoteIce = {};
    stopStream(state.localStream);
    state.localStream = stream;
    var local = $("local-video");
    if (media === "video" && local) { local.srcObject = state.localStream; local.hidden = false; }
    show("call-mic", true);
    show("call-camera", media === "video");
    var config = await api("/calls/config");
    state.iceConfig = config;
    var others = remotePeers();
    if (!(state.me && state.me.user_id) || others.length <= 1) {
      var remoteId = others[0] ? others[0].user_id : "";
      state.pc = buildPc(remoteId, config, false);
      if (isCaller) {
        var offer = await state.pc.createOffer();
        await state.pc.setLocalDescription(offer);
        await publishDescription(state.pc, "offer", offer.sdp || "");
      }
      return;
    }
    if (!isCaller) return;
    for (var i = 0; i < others.length; i += 1) {
      var pc = buildPc(others[i].user_id, config, true);
      if (!state.pc) state.pc = pc;
      var groupOffer = await pc.createOffer();
      await pc.setLocalDescription(groupOffer);
      await publishDescription(pc, "offer", groupOffer.sdp || "");
    }
  }
  async function sendSignal(kind, payload) {
    if (!state.call) return false;
    var id = kind.slice(0, 4) + Date.now().toString(36) + Math.random().toString(36).slice(2, 8);
    try {
      await api("/calls/" + state.call.call_id + "/signals", {
        method: "POST",
        body: JSON.stringify({ kind: kind, payload: payload, client_signal_id: id })
      });
      return true;
    } catch (err) {
      text("call-error", err.message);
      return false;
    }
  }
  async function consumeSignals() {
    if (!state.call || !state.localStream) return;
    var rows = await api("/calls/" + state.call.call_id + "/signals?after=" + state.signalAfter);
    for (var i = 0; i < rows.length; i += 1) {
      var row = rows[i];
      if (row.seq > state.signalAfter) state.signalAfter = row.seq;
      if (row.kind === "quality") {
        text("call-quality", "Network quality: " + row.payload);
        adapt(row.payload);
        continue;
      }
      if (row.kind === "media") {
        if (row.payload === "denied") {
          text("call-error", "The other person denied microphone or camera access. No audio or video was exchanged.");
        }
        continue;
      }
      var wrapped = parseWrapped(row.payload);
      if (wrapped && wrapped.target && state.me && wrapped.target !== state.me.user_id) continue;
      if (row.kind === "offer" || row.kind === "answer" || row.kind === "renego") {
        var sdp = wrapped && typeof wrapped.sdp === "string" ? wrapped.sdp : row.payload;
        var incomingOffer = row.kind !== "answer";
        var pc = pcForSender(row.sender_user_id);
        if (!pc && incomingOffer) {
          pc = buildPc(row.sender_user_id, state.iceConfig || { ice_servers: [] }, !!wrapped);
          if (!state.pc) state.pc = pc;
        }
        if (!pc) continue;
        try {
          if (incomingOffer && pc.signalingState === "have-remote-offer") {
            try { await pc.setLocalDescription({ type: "rollback" }); } catch (err) {}
          }
          if (incomingOffer && pc.signalingState === "have-local-offer") {
            var polite = !!(state.me && row.sender_user_id < state.me.user_id);
            if (!polite) continue;
            try { await pc.setLocalDescription({ type: "rollback" }); } catch (err) {}
          }
          note(incomingOffer ? "remote_offer" : "remote_answer");
          await pc.setRemoteDescription({ type: incomingOffer ? "offer" : "answer", sdp: sdp });
          await flushRemoteIce(row.sender_user_id, pc);
          if (incomingOffer) {
            pc._descSent = false;
            pc._localIce = [];
            var answer = await pc.createAnswer();
            await pc.setLocalDescription(answer);
            await publishDescription(pc, "answer", answer.sdp || "");
          }
        } catch (err) {
          text("call-error", "The call could not update the connection.");
        }
      } else if (row.kind === "ice") {
        var candidate = wrapped && wrapped.candidate ? wrapped.candidate : null;
        if (!candidate) {
          try { candidate = JSON.parse(row.payload); } catch (err) { candidate = null; }
        }
        if (!candidate) continue;
        var icePc = pcForSender(row.sender_user_id);
        if (!icePc || !icePc.remoteDescription) stashRemoteIce(row.sender_user_id, candidate);
        else {
          try { await icePc.addIceCandidate(candidate); note("remote_ice"); } catch (err) {}
        }
      }
    }
  }
  async function connectMesh() {
    if (!state.call || !state.me || !state.localStream || !state.iceConfig) return;
    var others = remotePeers();
    if (others.length < 2) return;
    for (var i = 0; i < others.length; i += 1) {
      var peer = others[i];
      if (state.pcs[peer.user_id]) continue;
      if (state.me.user_id > peer.user_id) continue;
      var pc = buildPc(peer.user_id, state.iceConfig, true);
      if (!state.pc) state.pc = pc;
      var offer = await pc.createOffer();
      await pc.setLocalDescription(offer);
      await publishDescription(pc, "offer", offer.sdp || "");
    }
  }
  function adapt(quality) {
    var weak = quality === "poor" || quality === "disconnected";
    var pcs = eachPc();
    for (var p = 0; p < pcs.length; p += 1) {
      var pc = pcs[p];
      if (!pc.getSenders) continue;
      var sender = pc.getSenders().filter(function (item) { return item.track && item.track.kind === "video"; })[0];
      if (!sender || !sender.track) continue;
      if (weak) {
        if (sender.track.enabled) state.videoHeld = true;
        sender.track.enabled = false;
      } else if (state.videoHeld) {
        sender.track.enabled = true;
      }
      if (!weak && sender.getParameters && sender.setParameters) {
        try {
          var params = sender.getParameters();
          if (params.encodings && params.encodings[0]) {
            if (quality === "fair") params.encodings[0].maxBitrate = 120000;
            else delete params.encodings[0].maxBitrate;
          }
          sender.setParameters(params);
        } catch (err) {}
      }
    }
    if (!weak && state.videoHeld) state.videoHeld = false;
    if (weak) text("call-adapt", "Video paused because the network is weak.");
    else if (quality === "fair") text("call-adapt", "Picture rate lowered because the network is fair.");
    else text("call-adapt", "");
  }
  async function sampleQuality() {
    var pc = state.pc || eachPc()[0];
    if (!pc || !pc.getStats) return;
    try {
      var stats = await pc.getStats();
      var lost = 0;
      var received = 0;
      var rtt = 0;
      stats.forEach(function (report) {
        if (report.type === "inbound-rtp") {
          lost += report.packetsLost || 0;
          received += report.packetsReceived || 0;
        }
        if (report.type === "candidate-pair" && report.currentRoundTripTime) rtt = report.currentRoundTripTime;
      });
      var ratio = received ? lost / received : 0;
      var quality = "good";
      if (pc.connectionState === "failed") quality = "disconnected";
      else if (ratio > 0.1 || rtt > 0.7) quality = "poor";
      else if (ratio > 0.03 || rtt > 0.3) quality = "fair";
      else if (ratio < 0.01 && rtt && rtt < 0.15) quality = "excellent";
      text("call-quality", "Network quality: " + quality);
      adapt(quality);
      await sendSignal("quality", quality);
    } catch (err) {
      text("call-quality", "Network quality: unknown");
    }
  }
  function paintCall() {
    if (!state.call) return;
    if (state.session && state.session.state === "permission_denied") {
      text("call-state", "Microphone or camera permission was denied. Nothing was captured. Snap will not ask again until you start or accept another call.");
      return;
    }
    var hint = state.call.session_hint || state.call.state;
    text("call-state", "Call " + hint + (state.call.ended_reason ? " · " + state.call.ended_reason : ""));
    if (state.call.calling_blocker && $("call-guidance")) $("call-guidance").textContent = state.call.calling_blocker;
  }
  function endLocalMedia() {
    stopStream(state.localStream);
    state.localStream = null;
    eachPc().forEach(function (pc) { try { pc.close(); } catch (err) {} });
    state.pcs = {};
    state.pc = null;
    state.remoteIce = {};
    state.videoHeld = false;
    state.remoteNodes.forEach(function (node) {
      try { node.srcObject = null; } catch (err) {}
      if (node.parentNode) node.parentNode.removeChild(node);
    });
    state.remoteNodes = [];
    ["remote-video", "local-video"].forEach(function (id) {
      var el = $(id);
      if (el) { el.srcObject = null; el.hidden = true; }
    });
  }
  async function acceptIncoming(call) {
    state.call = await api("/calls/" + call.call_id + "/accept", { method: "POST" });
    state.signalAfter = 0;
    state.remoteIce = {};
    if (!state.session) {
      var sessions = sessionApi();
      state.session = sessions ? sessions.create("callee") : null;
      note("invite_in");
    }
    note("accept");
    showCall(true);
    text("call-state", "Call accepted. Your browser will ask before the microphone or camera turns on.");
    show("call-accept", false);
    show("call-decline", false);
    await attachMedia(call.media, false);
  }
  async function pollIncoming() {
    var rows = await api("/calls/incoming");
    var finished = state.call && (state.call.state === "ended" || state.call.state === "failed" || state.call.state === "declined");
    if (!rows.length || (state.call && !finished)) return;
    state.call = rows[0];
    var sessions = sessionApi();
    state.session = sessions ? sessions.create("callee") : null;
    note("invite_in");
    showCall(true);
    text("call-state", "Incoming " + rows[0].media + " call. Camera and microphone stay off until you accept.");
    show("call-accept", true);
    show("call-decline", true);
    var accept = $("call-accept");
    accept.onclick = function () { acceptIncoming(rows[0]); };
    if (accept && accept.focus) accept.focus();
    $("call-decline").onclick = async function () {
      note("decline");
      await api("/calls/" + rows[0].call_id + "/decline", { method: "POST" });
      state.call = null;
      state.session = null;
      showCall(false);
      banner("Call declined.");
    };
  }

  function schedule(ms) {
    if (state.timer) clearTimeout(state.timer);
    state.timer = setTimeout(tick, ms);
  }
  async function tick() {
    var wait = document.hidden ? 8000 : 2000;
    if (!token()) { schedule(4000); return; }
    try {
      await refreshConversations();
      if (state.activeId) {
        var rows = await api("/conversations/" + state.activeId + "/messages?after=" + state.after);
        renderMessages(rows);
        await flushOutbox();
      }
      if (state.call && state.call.state !== "ended" && state.call.state !== "failed" && state.call.state !== "declined") {
        state.call = await api("/calls/" + state.call.call_id);
        paintCall();
        text("call-quality", "Network quality: " + (state.call.quality || "unknown"));
        await consumeSignals();
        await connectMesh();
        await sampleQuality();
        if (state.call.state === "failed" || state.call.state === "ended" || state.call.state === "declined") {
          if (state.call.state === "declined") note("remote_decline");
          else if (state.call.state === "failed") note("timeout");
          else note("end");
          endLocalMedia();
          state.session = null;
        }
      } else {
        await pollIncoming();
      }
      state.failures = 0;
    } catch (err) {
      state.failures += 1;
      wait = Math.min(8000, 1000 * Math.pow(2, state.failures));
      banner("Connection problem. Snap will retry. " + err.message);
    }
    schedule(wait);
  }

  function bind() {
    $("login-form").addEventListener("submit", async function (event) {
      event.preventDefault();
      var response = await fetch("/api/auth/login", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ email: $("login-email").value, password: $("login-password").value })
      });
      var payload = await response.json();
      if (!response.ok) { banner(payload.detail || "Sign-in failed"); return; }
      if (window.AmiCorSession && window.AmiCorSession.start) {
        window.AmiCorSession.start({
          userId: payload.user_id,
          email: payload.email,
          name: payload.display_name,
          role: payload.role,
          accessToken: payload.access_token,
          refreshToken: payload.refresh_token,
          organizationId: payload.organization_id
        });
      }
      show("login-form", false);
      show("sign-out", true);
      text("session-meta", "Signed in");
      state.me = await api("/me");
      text("session-meta", "Signed in as " + state.me.email);
      await refreshContacts();
      await refreshConversations();
      schedule(400);
    });
    $("sign-out").addEventListener("click", async function () {
      if (window.AmiCorSession && window.AmiCorSession.logout) await window.AmiCorSession.logout();
      state.me = null;
      show("login-form", true);
      show("sign-out", false);
      text("session-meta", "Signed out");
      closeCamera();
      endLocalMedia();
    });
    $("tab-chats").addEventListener("click", function () { showPanel("chats"); });
    $("tab-camera").addEventListener("click", function () { showPanel("camera"); });
    $("tab-calls").addEventListener("click", function () { showPanel("calls"); });
    ["chats", "camera", "calls"].forEach(function (name) {
      $("tab-" + name).addEventListener("keydown", moveTab);
    });
    $("contact-form").addEventListener("submit", async function (event) {
      event.preventDefault();
      try {
        var requested = await api("/contacts", { method: "POST", body: JSON.stringify({ email: $("contact-email").value }) });
        $("contact-email").value = "";
        await refreshContacts();
        banner(requested.status === "accepted" ? "This contact is already accepted." : "Contact request sent. The other person must accept.");
      } catch (err) { banner(err.message); }
    });
    $("new-group").addEventListener("click", function () { show("group-form", true); });
    $("group-form").addEventListener("submit", async function (event) {
      event.preventDefault();
      try {
        var ids = $("group-members").value.split(",").map(function (part) { return part.trim(); }).filter(Boolean);
        var row = await api("/conversations/group", { method: "POST", body: JSON.stringify({ title: $("group-title").value, user_ids: ids }) });
        await refreshConversations();
        await selectConversation(row.conversation_id);
      } catch (err) { banner(err.message); }
    });
    $("composer").addEventListener("submit", async function (event) {
      event.preventDefault();
      var body = $("message-body").value;
      var id = clientId();
      try {
        var saved = await sendBody(body, id);
        renderMessages([saved]);
        $("message-body").value = "";
        banner(saved.duplicate ? "Duplicate send ignored." : "Message stored.");
      } catch (err) {
        var rows = outbox();
        rows.push({ conversation_id: state.activeId, body: body, client_message_id: id });
        saveOutbox(rows);
        banner("Message not sent. It will retry when the connection returns.");
      }
    });
    $("retry-outbox").addEventListener("click", function () { flushOutbox().catch(function (err) { banner(err.message); }); });
    $("report-form").addEventListener("submit", async function (event) {
      event.preventDefault();
      var match = state.conversations.filter(function (row) { return row.conversation_id === state.activeId; })[0];
      var target = match && match.members.filter(function (person) { return !state.me || person.user_id !== state.me.user_id; })[0];
      if (!target) { banner("Open a conversation before reporting."); return; }
      try {
        var saved = await api("/reports", { method: "POST", body: JSON.stringify({ target_user_id: target.user_id, conversation_id: state.activeId, message_id: state.lastMessageId, reason: $("report-reason").value }) });
        banner(saved.note);
      } catch (err) { banner(err.message); }
    });
    $("block-user").addEventListener("click", async function () {
      var match = state.conversations.filter(function (row) { return row.conversation_id === state.activeId; })[0];
      var target = match && match.members.filter(function (person) { return !state.me || person.user_id !== state.me.user_id; })[0];
      if (!target) return;
      await api("/blocks", { method: "POST", body: JSON.stringify({ user_id: target.user_id }) });
      banner("Blocked. You will no longer see this conversation.");
      state.activeId = null;
      await refreshConversations();
    });
    $("delete-last").addEventListener("click", async function () {
      if (!state.myLastMessageId) return;
      try {
        var row = await api("/messages/" + state.myLastMessageId, { method: "DELETE" });
        banner(row.removed ? "Message removed." : "Message unchanged.");
      } catch (err) { banner(err.message); }
    });
    $("remove-my-content").addEventListener("click", async function () {
      var result = await api("/privacy/remove-my-content", { method: "POST" });
      banner("Removed " + result.messages_removed + " messages and " + result.captures_removed + " captures.");
      closeCamera();
    });
    $("camera-open").addEventListener("click", function () { openCamera(); });
    $("camera-close").addEventListener("click", function () { closeCamera(); });
    $("camera-flip").addEventListener("click", function () {
      state.facing = state.facing === "user" ? "environment" : "user";
      openCamera();
    });
    $("mic-toggle").addEventListener("click", function () {
      state.micOn = !state.micOn;
      text("mic-toggle", state.micOn ? "Microphone on" : "Microphone off");
      if (!state.cameraStream) return;
      var tracks = state.cameraStream.getAudioTracks();
      if (!state.micOn) {
        tracks.forEach(function (track) { track.enabled = false; });
        return;
      }
      if (tracks.length) {
        tracks.forEach(function (track) { track.enabled = true; });
        return;
      }
      if (!navigator.mediaDevices || !navigator.mediaDevices.getUserMedia) {
        state.micOn = false;
        text("mic-toggle", "Microphone off");
        cameraError("This browser cannot open the microphone.");
        return;
      }
      navigator.mediaDevices.getUserMedia({ audio: true, video: false }).then(function (extra) {
        if (!state.cameraStream || !state.micOn) {
          stopStream(extra);
          return;
        }
        extra.getAudioTracks().forEach(function (track) {
          track.enabled = true;
          state.cameraStream.addTrack(track);
        });
      }).catch(function (err) {
        state.micOn = false;
        text("mic-toggle", "Microphone off");
        cameraError(err && err.name === "NotAllowedError" ? "Camera or microphone permission was denied." : "The microphone could not start.");
      });
    });
    $("record").addEventListener("click", function () { recordClip(); });
    $("camera-file").addEventListener("change", function () {
      var file = $("camera-file").files && $("camera-file").files[0];
      if (!file) return;
      rememberClip(file, file.type.indexOf("video/") === 0 ? 1000 : 0);
    });
    $("save-draft").addEventListener("click", function () { saveDraft().catch(function (err) { cameraError(err.message); }); });
    $("consent").addEventListener("change", syncShareButton);
    $("share-capture").addEventListener("click", async function () {
      if ($("share-capture").disabled) return;
      try {
        await api("/captures/" + state.draftId + "/share", { method: "POST", body: JSON.stringify({ conversation_id: state.activeId, consent: true }) });
        banner("Draft shared with the open conversation only.");
        state.draftId = null;
        $("consent").checked = false;
        syncShareButton();
        await refreshCaptures();
      } catch (err) { cameraError(err.message); }
    });
    $("call-start-audio").addEventListener("click", function () { placeCall("audio").catch(function (err) { text("call-error", err.message); }); });
    $("call-start-video").addEventListener("click", function () { placeCall("video").catch(function (err) { text("call-error", err.message); }); });
    $("call-hangup").addEventListener("click", async function () {
      if (!state.call) return;
      note("hangup");
      await api("/calls/" + state.call.call_id + "/end", { method: "POST" });
      endLocalMedia();
      text("call-state", "Call ended.");
      state.call = null;
      state.session = null;
    });
    $("call-reconnect").addEventListener("click", async function () {
      if (!state.call) return;
      try {
        state.call = await api("/calls/" + state.call.call_id + "/reconnect", { method: "POST" });
        note("reconnect");
        if (state.call.state !== "active") {
          text("call-error", "Restart the connection only after the call is active.");
          text("call-state", "Waiting. Picture and sound depend on a direct network path. Two-device audio and video are not verified.");
          return;
        }
        text("call-state", "Reconnecting. Picture and sound depend on a direct network path. Two-device audio and video are not verified.");
        var pcs = eachPc();
        for (var i = 0; i < pcs.length; i += 1) {
          if (!pcs[i].createOffer) continue;
          await restartPeer(pcs[i]);
        }
      } catch (err) { text("call-error", err.message); }
    });
    $("enable-sound").addEventListener("click", function () {
      var nodes = [$("remote-video")].concat(state.remoteNodes);
      var pending = nodes.filter(function (node) { return node && node.play; }).map(function (node) { return node.play(); });
      Promise.all(pending).then(function () { show("enable-sound", false); }).catch(function () {});
    });
    $("call-mic").addEventListener("click", function () {
      if (!state.localStream) return;
      var tracks = state.localStream.getAudioTracks();
      var enabled = !(tracks[0] && tracks[0].enabled);
      tracks.forEach(function (track) { track.enabled = enabled; });
      text("call-mic", enabled ? "Mute microphone" : "Unmute microphone");
    });
    $("call-camera").addEventListener("click", function () {
      if (!state.localStream) return;
      state.videoHeld = false;
      var tracks = state.localStream.getVideoTracks();
      var enabled = !(tracks[0] && tracks[0].enabled);
      tracks.forEach(function (track) { track.enabled = enabled; });
      text("call-camera", enabled ? "Turn camera off" : "Turn camera on");
    });
    syncShareButton();
  }

  bind();
  fetch("/api/nova/snap/status", { cache: "no-store" }).then(function (response) { return response.json(); }).then(function (status) {
    state.status = status;
    guidance(status);
  }).catch(function () {});
  if (token()) {
    show("login-form", false);
    show("sign-out", true);
    api("/me").then(function (me) {
      state.me = me;
      text("session-meta", "Signed in as " + me.email);
      return refreshContacts();
    }).then(refreshConversations).then(function () { schedule(400); }).catch(function (err) { banner(err.message); });
  }
})();
