"use strict";
/* Keep transitions aligned with backend/app/core/nova/snap/session.py.
   media_granted is an explicit user gesture. Timers must not apply it.
   simulated=true is the in-process loopback only. A browser connection is unverified. */
(function (root, factory) {
  var api = factory();
  if (typeof module === "object" && module.exports) module.exports = api;
  if (root) root.NovaSnapCallSession = api;
})(typeof globalThis !== "undefined" ? globalThis : this, function () {
  var terminal = { declined: true, ended: true, failed: true };
  var mediaStates = { connecting: true, reconnecting: true, connected: true };

  function PeerSession(role, simulated) {
    this.role = role;
    this.simulated = !!simulated;
    this.state = "idle";
    this.accepted = false;
    this.mediaGranted = false;
    this.mediaDenied = false;
    this.localDesc = null;
    this.remoteDesc = null;
    this.localIce = 0;
    this.remoteIce = 0;
    this.media_path = "none";
    this.error = null;
  }

  PeerSession.prototype.evidence = function () {
    return {
      label: this.simulated ? "simulated" : "browser-unverified",
      simulated: this.simulated,
      state: this.state,
      role: this.role,
      media_path: this.media_path,
      media_granted: this.mediaGranted,
      media_denied: this.mediaDenied,
      two_independent_devices: false,
      devices_used: 0,
      rtp_packets: 0,
      turn_purchased: false,
      error: this.error
    };
  };

  PeerSession.prototype._ready = function () {
    var pair = {};
    pair[this.localDesc] = true;
    pair[this.remoteDesc] = true;
    if (!pair.offer || !pair.answer || this.localIce < 1 || this.remoteIce < 1) return;
    this.state = "connected";
    this.error = null;
    this.media_path = this.simulated ? "simulated-loopback" : "browser-webrtc-unverified";
  };

  PeerSession.prototype._onSignal = function (event) {
    if (!mediaStates[this.state] || !this.mediaGranted || this.mediaDenied) {
      throw new Error("illegal:" + this.state + ":" + event);
    }
    if (event === "local_offer") this.localDesc = "offer";
    else if (event === "remote_offer") this.remoteDesc = "offer";
    else if (event === "local_answer") {
      if (this.remoteDesc !== "offer") throw new Error("illegal:answer-without-offer");
      this.localDesc = "answer";
    } else if (event === "remote_answer") {
      if (this.localDesc !== "offer") throw new Error("illegal:answer-without-offer");
      this.remoteDesc = "answer";
    } else if (event === "local_ice") {
      if (this.localDesc !== "offer" && this.localDesc !== "answer") throw new Error("illegal:ice-without-description");
      this.localIce += 1;
    } else if (event === "remote_ice") {
      if (this.remoteDesc !== "offer" && this.remoteDesc !== "answer") throw new Error("illegal:ice-without-description");
      this.remoteIce += 1;
    }
    this._ready();
  };

  PeerSession.prototype.apply = function (event) {
    var name = String(event || "").trim();
    var state = this.state;
    if ((name === "hangup" || name === "end") && !terminal[state]) {
      this.state = "ended";
      this.error = null;
      return this.evidence();
    }
    if (name === "timeout" && !terminal[state]) {
      this.state = "failed";
      this.error = "network_timeout";
      this.media_path = "none";
      return this.evidence();
    }
    if (name === "ice_failed" && mediaStates[state]) {
      this.state = "failed";
      this.error = "ice_failed";
      this.media_path = "none";
      return this.evidence();
    }
    if (state === "idle" && name === "invite_out" && this.role === "caller") {
      this.state = "ringing_out";
      this.accepted = true;
      return this.evidence();
    }
    if (state === "idle" && name === "invite_in" && this.role === "callee") {
      this.state = "ringing_in";
      return this.evidence();
    }
    if (state === "ringing_in" && name === "accept" && this.role === "callee") {
      this.accepted = true;
      return this.evidence();
    }
    if (state === "ringing_in" && name === "decline") {
      this.state = "declined";
      this.error = null;
      return this.evidence();
    }
    if ((state === "ringing_out" || state === "connecting") && name === "remote_decline") {
      this.state = "declined";
      this.media_path = "none";
      return this.evidence();
    }
    if (name === "media_denied" && this.accepted && (state === "ringing_out" || state === "ringing_in" || state === "connecting" || state === "reconnecting")) {
      this.mediaGranted = false;
      this.mediaDenied = true;
      this.state = "permission_denied";
      this.media_path = "none";
      this.error = "permission_denied";
      return this.evidence();
    }
    if (name === "media_granted" && this.accepted && (state === "ringing_out" || state === "ringing_in" || state === "permission_denied" || state === "reconnecting")) {
      this.mediaDenied = false;
      this.mediaGranted = true;
      this.error = null;
      if (state !== "reconnecting") this.state = "connecting";
      return this.evidence();
    }
    if (name === "local_offer" || name === "remote_offer" || name === "local_answer" || name === "remote_answer" || name === "local_ice" || name === "remote_ice") {
      this._onSignal(name);
      return this.evidence();
    }
    if (name === "reconnect" && (state === "connecting" || state === "connected")) {
      this.state = "reconnecting";
      this.remoteDesc = null;
      this.localIce = 0;
      this.remoteIce = 0;
      this.media_path = "none";
      this.error = null;
      return this.evidence();
    }
    throw new Error("illegal:" + state + ":" + name);
  };

  return {
    create: function (role, options) {
      if (role !== "caller" && role !== "callee") throw new Error("role");
      return new PeerSession(role, !!(options && options.simulated));
    }
  };
});
