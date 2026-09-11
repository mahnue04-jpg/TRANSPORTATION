"use strict";

(function () {
  const banner = document.getElementById("banner");
  const loginCard = document.getElementById("login-card");
  const appShell = document.getElementById("app-shell");
  const loginForm = document.getElementById("login-form");
  const CAREGIVER_PERMISSIONS = [
    { id: "view_today", label: "View Today" },
    { id: "view_medications", label: "View medications" },
    { id: "view_appointments", label: "View appointments" },
    { id: "view_wellness", label: "View wellness check-ins" },
    { id: "view_journal", label: "View journal" },
    { id: "view_readings", label: "View health readings" },
    { id: "view_transport", label: "View transportation status" },
    { id: "receive_alerts", label: "Receive alerts" },
    { id: "acknowledge_alerts", label: "Acknowledge alerts" },
    { id: "manage_tasks", label: "Manage shared tasks" },
    { id: "handoff", label: "Participate in handoffs" },
  ];
  let state = {
    me: null,
    memberProfileId: "",
    view: "today",
    coordFilter: "all",
  };

  function session() {
    return window.AmiCorSession;
  }

  function showBanner(message, kind) {
    banner.textContent = message;
    banner.className = "banner " + (kind || "");
    banner.classList.toggle("hidden", !message);
  }

  function applyA11y(prefs) {
    const root = document.documentElement;
    root.dataset.text = prefs && prefs.large_text ? "large" : "normal";
    root.dataset.contrast = prefs && prefs.high_contrast ? "high" : "standard";
    root.dataset.motion = prefs && prefs.reduce_motion ? "reduce" : "full";
  }

  async function api(path, options) {
    const opts = options || {};
    const headers = Object.assign(
      { "Content-Type": "application/json" },
      session() && session().getAuthHeaders ? session().getAuthHeaders() : {},
      opts.headers || {}
    );
    const response = await fetch(path, Object.assign({}, opts, { headers }));
    const body = await response.json().catch(function () { return {}; });
    if (!response.ok || body.ok === false) {
      const detail = (body.detail && (body.detail.msg || body.detail)) || body.error || response.statusText;
      throw new Error(typeof detail === "string" ? detail : "Request failed");
    }
    return body.data;
  }

  function escapeHtml(value) {
    return String(value == null ? "" : value)
      .replace(/&/g, "&amp;")
      .replace(/</g, "&lt;")
      .replace(/>/g, "&gt;")
      .replace(/"/g, "&quot;");
  }

  function memberQuery() {
    return state.memberProfileId ? ("?member_profile_id=" + encodeURIComponent(state.memberProfileId)) : "";
  }

  function setView(name) {
    state.view = name;
    document.querySelectorAll(".view").forEach(function (node) {
      node.classList.toggle("hidden", node.id !== "view-" + name);
    });
    document.querySelectorAll("[data-view]").forEach(function (button) {
      const current = button.getAttribute("data-view") === name;
      if (button.hasAttribute("aria-current")) {
        button.setAttribute("aria-current", current ? "page" : "false");
      }
    });
    loadView(name);
  }

  async function loadMe() {
    state.me = await api("/api/lifesaver/me");
    document.getElementById("session-name").textContent = state.me.profile.display_name || "Signed in";
    document.getElementById("session-meta").textContent = (state.me.session.email || "") + " · " + state.me.profile.profile_role;
    document.getElementById("product-disclaimer").textContent = state.me.disclaimer;
    applyA11y(state.me.profile.accessibility || {});
  }

  function caregiverName(circle, profileId) {
    const match = (circle || []).find(function (row) { return row.caregiver_profile_id === profileId; });
    return (match && match.caregiver_display_name) || profileId || "caregiver";
  }

  function handoffCreateForm(circle, myProfileId) {
    const active = (circle || []).filter(function (row) { return row.status === "active"; });
    if (active.length < 2) {
      return "<p class='meta'>Invite at least two active caregivers before creating a handoff.</p>";
    }
    function options(selectedId) {
      return active.map(function (row) {
        return "<option value='" + escapeHtml(row.caregiver_profile_id) + "'" +
          (row.caregiver_profile_id === selectedId ? " selected" : "") + ">" +
          escapeHtml(row.caregiver_display_name || row.caregiver_profile_id) + "</option>";
      }).join("");
    }
    return "<form id='handoff-form'><label>From caregiver<select name='from_caregiver_id' required>" +
      options(active[0].caregiver_profile_id) +
      "</select></label><label>To caregiver<select name='to_caregiver_id' required>" +
      options(active[1].caregiver_profile_id) +
      "</select></label><label>Handoff description<input name='note' required maxlength='256' /></label>" +
      "<p class='meta'>Only the selected recipient can accept or decline. No email or SMS is sent.</p>" +
      "<input type='hidden' name='member_profile_id' value='" + escapeHtml(myProfileId || "") + "' />" +
      "<div class='actions'><button type='submit'>Create handoff</button></div></form>";
  }

  function renderList(items, emptyText, formatter) {
    if (!items || !items.length) return "<p class='meta'>" + escapeHtml(emptyText) + "</p>";
    return "<ul class='list'>" + items.map(formatter).join("") + "</ul>";
  }

  async function loadToday() {
    const data = await api("/api/lifesaver/today" + memberQuery());
    const caring = await api("/api/lifesaver/circle/caring-for");
    document.getElementById("view-today").innerHTML = [
      "<section class='card'><h2>Today</h2>",
      caring.length ? ("<label>Viewing Care Circle member<select id='member-select'><option value=''>Myself</option>" +
        caring.map(function (row) {
          return "<option value='" + escapeHtml(row.member_profile_id) + "'" +
            (row.member_profile_id === state.memberProfileId ? " selected" : "") + ">" +
            escapeHtml(row.member_display_name || row.member_profile_id) + "</option>";
        }).join("") + "</select></label>") : "",
      "<h3>Reminders</h3>",
      renderList(data.reminders, "No upcoming reminders.", function (row) {
        return "<li><strong>" + escapeHtml(row.title) + "</strong><div class='meta'>" +
          escapeHtml(row.status) + " · " + escapeHtml(row.due_at || "") +
          "</div><div class='actions'><button type='button' data-ack-reminder='" + escapeHtml(row.id) +
          "'>Acknowledge</button></div></li>";
      }),
      "<h3>Appointments</h3>",
      renderList(data.appointments, "No upcoming appointments.", function (row) {
        return "<li><strong>" + escapeHtml(row.title) + "</strong><div class='meta'>" +
          escapeHtml(row.starts_at || "") + " · " + escapeHtml(row.location || "") + "</div></li>";
      }),
      "<h3>Shared tasks</h3>",
      renderList(data.tasks, "No open care tasks.", function (row) {
        return "<li><strong>" + escapeHtml(row.title) + "</strong><div class='meta'>" +
          escapeHtml(row.status) + "</div></li>";
      }),
      "</section>"
    ].join("");
  }

  async function loadCare() {
    let meds = [];
    let readings = [];
    let wellness = [];
    let journal = [];
    let transport = null;
    let sos = [];
    const errors = [];
    async function tryLoad(label, fn) {
      try { return await fn(); } catch (err) { errors.push(label + ": " + err.message); return []; }
    }
    meds = await tryLoad("Medications", function () { return api("/api/lifesaver/medications" + memberQuery()); });
    const appointments = await tryLoad("Appointments", function () { return api("/api/lifesaver/appointments" + memberQuery()); });
    readings = await tryLoad("Readings", function () { return api("/api/lifesaver/readings" + memberQuery()); });
    wellness = await tryLoad("Wellness", function () { return api("/api/lifesaver/wellness" + memberQuery()); });
    journal = await tryLoad("Journal", function () { return api("/api/lifesaver/journal" + memberQuery()); });
    try { transport = await api("/api/lifesaver/transport" + memberQuery()); } catch (err) { errors.push("Transport: " + err.message); }
    sos = await tryLoad("SOS", function () { return api("/api/lifesaver/sos"); });

    document.getElementById("view-care").innerHTML = [
      errors.length ? "<p class='card disclaimer'>" + escapeHtml(errors.join(" ")) + "</p>" : "",
      "<section class='card'><h2>Medications and reminders</h2>",
      "<p class='meta'>User-entered schedules only. This is not treatment advice.</p>",
      "<form id='med-form'><label>Name<input name='name' required /></label>",
      "<label>Instructions<input name='instructions' /></label>",
      "<label>Times (HH:MM, comma separated)<input name='schedule' placeholder='08:00, 20:00' /></label>",
      "<div class='actions'><button type='submit'>Save medication</button></div></form>",
      renderList(meds, "No medications saved.", function (row) {
        return "<li><strong>" + escapeHtml(row.name) + "</strong><div class='meta'>" +
          escapeHtml((row.schedule_times || []).join(", ")) + "</div></li>";
      }),
      "</section>",
      "<section class='card' id='care-appointments'><h2>Appointments</h2>",
      "<form id='appt-form'><label>Title<input name='title' required /></label>",
      "<label>When<input name='starts_at' type='datetime-local' required /></label>",
      "<label>Location<input name='location' /></label>",
      "<div class='actions'><button type='submit'>Save appointment</button></div></form>",
      renderList(appointments, "No appointments saved.", function (row) {
        return "<li data-appointment-id='" + escapeHtml(row.id) + "'><strong>" + escapeHtml(row.title) +
          "</strong><div class='meta'>" + escapeHtml(row.starts_at || "") + " · " +
          escapeHtml(row.location || "") + "</div></li>";
      }),
      "</section>",
      "<section class='card'><h2>Wellness check-in</h2>",
      "<form id='wellness-form'><label>Mood<input name='mood' required /></label>",
      "<label>Energy<input name='energy' required /></label>",
      "<label>Notes<textarea name='notes'></textarea></label>",
      "<label><input type='checkbox' name='notify' /> Notify Care Circle</label>",
      "<div class='actions'><button type='submit'>Save check-in</button></div></form>",
      renderList(wellness, "No check-ins yet.", function (row) {
        return "<li><strong>" + escapeHtml(row.mood) + "</strong> · " + escapeHtml(row.energy) + "</li>";
      }),
      "</section>",
      "<section class='card'><h2>Health journal</h2>",
      "<form id='journal-form'><label>Entry<textarea name='body' required></textarea></label>",
      "<div class='actions'><button type='submit'>Save entry</button></div></form>",
      renderList(journal, "No journal entries.", function (row) {
        return "<li>" + escapeHtml(row.body) + "<div class='meta'>" + escapeHtml(row.created_at || "") + "</div></li>";
      }),
      "</section>",
      "<section class='card'><h2>Health readings</h2>",
      "<p class='meta'>" + escapeHtml((state.me && state.me.reading_disclaimer) || "") + "</p>",
      "<form id='reading-form'><label>Type<select name='reading_type'>",
      "<option value='blood_pressure'>Blood pressure</option>",
      "<option value='glucose'>Glucose</option>",
      "<option value='oxygen_saturation'>Oxygen saturation</option>",
      "<option value='temperature'>Temperature</option>",
      "<option value='weight'>Weight</option></select></label>",
      "<label>Primary value<input name='value_primary' type='number' step='0.1' required /></label>",
      "<label>Secondary value (diastolic)<input name='value_secondary' type='number' step='0.1' /></label>",
      "<label>Source<select name='source'><option value='user_entered'>User entered</option>",
      "<option value='simulated'>Simulated</option></select></label>",
      "<div class='actions'><button type='submit'>Save reading</button></div></form>",
      renderList(readings, "No readings yet.", function (row) {
        const value = row.reading_type === "blood_pressure"
          ? row.value_primary + "/" + row.value_secondary
          : row.value_primary;
        const sim = row.source === "simulated_device" ? " · SIMULATED — NOT FROM A MEDICAL DEVICE" : "";
        return "<li><strong>" + escapeHtml(row.reading_type) + "</strong> " +
          escapeHtml(value) + " " + escapeHtml(row.unit) +
          "<div class='meta'>source: " + escapeHtml(row.source) + " · not device-sourced" + sim + "</div></li>";
      }),
      "<form id='device-form'><h3>Simulated device reading</h3>",
      "<p class='disclaimer'>SIMULATED — NOT FROM A MEDICAL DEVICE</p>",
      "<label>Type<select name='reading_type'>",
      "<option value='blood_pressure'>Blood pressure</option>",
      "<option value='glucose'>Glucose</option>",
      "<option value='spo2'>SpO2</option>",
      "<option value='temperature'>Temperature</option>",
      "<option value='weight'>Weight</option></select></label>",
      "<label>Primary value<input name='value_primary' type='number' step='0.1' required /></label>",
      "<label>Secondary value (diastolic)<input name='value_secondary' type='number' step='0.1' /></label>",
      "<label>Device alias<input name='device_alias' value='local-simulator' /></label>",
      "<div class='actions'><button type='submit'>Save simulated device reading</button></div></form>",
      "</section>",
      "<section class='card'><h2>Transportation status</h2>",
      "<p>" + escapeHtml(transport ? transport.status_text : "Consent required to view transportation status.") + "</p>",
      "<p class='meta'>This interface does not dispatch production rides.</p>",
      "<div class='actions'><button type='button' id='transport-request' class='secondary'>Request connection</button></div>",
      "</section>",
      "<section class='card'><h2>SOS demonstration</h2>",
      "<p class='disclaimer'>" + escapeHtml((state.me && state.me.sos_disclaimer) || "") + "</p>",
      "<form id='sos-form'><label>Optional note<input name='note' /></label>",
      "<div class='actions'><button type='submit' class='danger'>Start demonstration</button></div></form>",
      renderList(sos, "No SOS demonstrations.", function (row) {
        return "<li><strong>" + escapeHtml(row.status) + "</strong><div class='meta'>Emergency services contacted: no</div>" +
          (row.status === "draft"
            ? "<div class='actions'><button type='button' data-confirm-sos='" + escapeHtml(row.id) +
              "'>I understand this is not emergency response</button></div>"
            : "") + "</li>";
      }),
      "</section>"
    ].join("");
  }

  async function loadCoord() {
    const data = await api("/api/lifesaver/coordination" + (memberQuery() ? memberQuery() + "&filter=" + encodeURIComponent(state.coordFilter || "all") : "?filter=" + encodeURIComponent(state.coordFilter || "all")));
    const requests = await api("/api/lifesaver/transport/requests" + memberQuery()).catch(function () { return []; });
    const appointments = await api("/api/lifesaver/appointments" + memberQuery()).catch(function () { return []; });
    const filters = data.filters || ["all", "today", "appointments", "reminders", "transportation", "care_circle", "tasks", "alerts"];
    document.getElementById("view-coord").innerHTML = [
      "<section class='card' id='care-coordination'><h2>Care Coordination</h2>",
      "<p class='disclaimer'>" + escapeHtml(data.disclaimer || "") + "</p>",
      "<p class='meta'>HIGH " + escapeHtml(String((data.counts || {}).high || 0)) +
        " · MEDIUM " + escapeHtml(String((data.counts || {}).medium || 0)) +
        " · LOW " + escapeHtml(String((data.counts || {}).low || 0)) + "</p>",
      "<div class='filter-row'>" + filters.map(function (name) {
        return "<button type='button' class='" + (name === (data.filter || "all") ? "" : "secondary") +
          "' data-coord-filter='" + escapeHtml(name) + "'>" + escapeHtml(name) + "</button>";
      }).join("") + "</div>",
      (data.cards || []).map(function (card) {
        return "<article class='priority-card priority-" + escapeHtml(card.priority) + "'>" +
          "<strong>" + escapeHtml(card.priority) + " · " + escapeHtml(card.title) + "</strong>" +
          "<div class='meta'>" + escapeHtml(card.kind) + " · " + escapeHtml(card.status || "") + "</div>" +
          "<p>Why: " + escapeHtml(card.why) + "</p>" +
          (card.needs_human_review ? "<span class='badge'>Needs human review</span>" : "") +
          "</article>";
      }).join("") || "<p class='meta'>No coordination items for this filter.</p>",
      "</section>",
      "<section class='card' id='transport-coordination'><h2>Transportation coordination</h2>",
      "<p class='disclaimer'>Transportation coordination only. This does not dispatch a ride.</p>",
      "<form id='treq-form'><label>Appointment reference<select name='appointment_id'><option value=''>None</option>" +
        (appointments || []).map(function (row) {
          return "<option value='" + escapeHtml(row.id) + "'>" + escapeHtml(row.title) + "</option>";
        }).join("") + "</select></label>",
      "<label>Pickup date/time<input name='pickup_at' type='datetime-local' /></label>",
      "<label>Pickup label<input name='pickup_label' required /></label>",
      "<label>Destination label<input name='destination_label' required /></label>",
      "<label>Accessibility needs<input name='accessibility_needs' /></label>",
      "<label>Mobility assistance note<input name='mobility_note' /></label>",
      "<label><input type='checkbox' name='companion_needed' /> Companion needed</label>",
      "<div class='actions'><button type='submit'>Create transportation request</button></div></form>",
      renderList(requests, "No transportation requests.", function (row) {
        return "<li><strong>" + escapeHtml(row.status) + (row.simulated ? " · SIMULATED" : "") +
          "</strong><div class='meta'>" + escapeHtml(row.pickup_label) + " → " +
          escapeHtml(row.destination_label) + "</div><p class='meta'>" +
          escapeHtml(row.disclaimer || "") + "</p>" +
          (row.status === "requested" || row.status === "needs_review"
            ? "<div class='actions'><button type='button' data-confirm-treq='" + escapeHtml(row.id) +
              "'>Confirm ready for handoff</button></div>"
            : "") +
          (row.status === "ready_for_handoff"
            ? "<div class='actions'><button type='button' data-handoff-treq='" + escapeHtml(row.id) +
              "'>Simulated handoff</button></div>"
            : "") +
          (row.status === "requested" || row.status === "needs_review" || row.status === "ready_for_handoff"
            ? "<div class='actions'><button type='button' class='secondary' data-cancel-treq='" +
              escapeHtml(row.id) + "'>Cancel request</button></div>"
            : "") + "</li>";
      }),
      "</section>"
    ].join("");
  }

  async function loadNotify() {
    const notices = await api("/api/lifesaver/notifications");
    const circle = await api("/api/lifesaver/circle").catch(function () { return []; });
    document.getElementById("view-notify").innerHTML = [
      "<section class='card' id='notification-center'><h2>Notification Center</h2>",
      "<p class='disclaimer'>LOCAL SIMULATION — no external message sent.</p>",
      "<form id='notice-form'><label>Type<select name='notification_type'>",
      "<option value='appointment_reminder'>Appointment reminder</option>",
      "<option value='medication_reminder'>Medication reminder</option>",
      "<option value='transport_update'>Transportation update</option>",
      "<option value='care_circle_invite'>Care Circle invitation</option>",
      "<option value='handoff_assigned'>Handoff assigned</option>",
      "<option value='task_assigned'>Shared task assigned</option>",
      "<option value='alert_ack_request'>Alert acknowledgment request</option></select></label>",
      "<label>Channel<select name='channel'><option value='email'>Email</option><option value='sms'>SMS</option></select></label>",
      "<label>Title<input name='title' required /></label>",
      "<label>Reason<input name='reason' /></label>",
      "<label>Recipient<select name='recipient_profile_id'><option value=''>Myself / unassigned</option>" +
        (circle || []).filter(function (row) { return row.status === "active"; }).map(function (row) {
          return "<option value='" + escapeHtml(row.caregiver_profile_id) + "'>" +
            escapeHtml(row.caregiver_display_name || "Caregiver") + "</option>";
        }).join("") + "</select></label>",
      "<div class='actions'><button type='submit'>Queue locally</button></div></form>",
      renderList(notices, "No local notifications.", function (row) {
        return "<li><strong>" + escapeHtml(row.status) + "</strong> · " +
          escapeHtml(row.channel) + "<div class='meta'>" + escapeHtml(row.title) +
          " · " + escapeHtml(row.recipient_role) + " · " + escapeHtml(row.created_at || "") +
          " · " + escapeHtml(row.reason || "") + "</div><p class='meta'>" +
          escapeHtml(row.label || "LOCAL SIMULATION — no external message sent.") + "</p>" +
          "<div class='actions'>" +
          (row.status === "queued_local" || row.status === "failed_simulated"
            ? "<button type='button' data-notice-deliver='" + escapeHtml(row.id) + "'>Simulate delivery</button>" +
              "<button type='button' class='secondary' data-notice-fail='" + escapeHtml(row.id) + "'>Simulate failure</button>"
            : "") +
          (row.status === "failed_simulated"
            ? "<button type='button' class='secondary' data-notice-retry='" + escapeHtml(row.id) + "'>Retry locally</button>"
            : "") +
          (row.status !== "suppressed" && row.status !== "delivered_simulated"
            ? "<button type='button' class='secondary' data-notice-suppress='" + escapeHtml(row.id) + "'>Suppress</button>"
            : "") +
          "</div></li>";
      }),
      "</section>"
    ].join("");
  }

  async function loadCircle() {
    const circle = await api("/api/lifesaver/circle");
    const caring = await api("/api/lifesaver/circle/caring-for");
    const alerts = await api("/api/lifesaver/alerts");
    const handoffs = await api("/api/lifesaver/handoffs");
    const tasks = await api("/api/lifesaver/tasks" + memberQuery()).catch(function () { return []; });
    document.getElementById("view-circle").innerHTML = [
      "<section class='card'><h2>Care Circle</h2>",
      "<form id='invite-form'><label>Caregiver email in this organization<input name='email' type='email' required /></label>",
      "<p class='meta'>Default permissions stay least-privilege: view today, receive alerts, and acknowledge alerts. Extra access requires an explicit save below.</p>",
      "<div class='actions'><button type='submit'>Invite caregiver</button></div></form>",
      renderList(circle, "No caregivers yet.", function (row) {
        const current = row.permissions || [];
        const editor = row.status === "active"
          ? "<form class='perm-form' data-link-id='" + escapeHtml(row.id) + "'>" +
            "<fieldset><legend>Permissions for " + escapeHtml(row.caregiver_display_name || "caregiver") + "</legend>" +
            CAREGIVER_PERMISSIONS.map(function (perm) {
              return "<label class='perm-row'><input type='checkbox' name='permission' value='" +
                escapeHtml(perm.id) + "'" + (current.indexOf(perm.id) >= 0 ? " checked" : "") +
                " /> " + escapeHtml(perm.label) + "</label>";
            }).join("") +
            "</fieldset><p class='meta'>Health readings stay hidden unless you explicitly grant View health readings, then save.</p>" +
            "<div class='actions'><button type='submit'>Save permissions</button></div></form>"
          : "<div class='meta'>Permissions can be edited after the relationship is active.</div>";
        return "<li><strong>" + escapeHtml(row.caregiver_display_name || "Caregiver") + "</strong> · " +
          escapeHtml(row.status) + "<div class='meta'>Current: " +
          escapeHtml(current.join(", ") || "none") +
          "</div>" + editor + "<div class='actions'><button type='button' class='secondary' data-revoke='" +
          escapeHtml(row.id) + "'>Revoke</button></div></li>";
      }),
      "</section>",
      "<section class='card'><h2>People I support</h2>",
      renderList(caring, "You are not an active caregiver for anyone.", function (row) {
        return "<li><strong>" + escapeHtml(row.member_display_name || "Member") + "</strong></li>";
      }),
      "</section>",
      "<section class='card'><h2>Alerts</h2>",
      renderList(alerts, "No alerts.", function (row) {
        return "<li><strong>" + escapeHtml(row.title) + "</strong><div class='meta'>" +
          escapeHtml(row.status) + " · " + escapeHtml(row.severity) + "</div>" +
          (row.status === "open"
            ? "<div class='actions'><button type='button' data-ack-alert='" + escapeHtml(row.id) +
              "'>Acknowledge</button></div>"
            : "") + "</li>";
      }),
      "</section>",
      "<section class='card'><h2>Shared tasks</h2>",
      "<form id='task-form'><label>Task title<input name='title' required /></label>",
      "<div class='actions'><button type='submit'>Add task</button></div></form>",
      renderList(tasks, "No tasks.", function (row) {
        return "<li><strong>" + escapeHtml(row.title) + "</strong> · " + escapeHtml(row.status) +
          (row.status === "open"
            ? "<div class='actions'><button type='button' data-complete-task='" + escapeHtml(row.id) +
              "'>Complete</button></div>"
            : "") + "</li>";
      }),
      "</section>",
      "<section class='card'><h2>Handoffs</h2>",
      handoffCreateForm(circle, state.me && state.me.profile ? state.me.profile.id : ""),
      renderList(handoffs, "No handoffs.", function (row) {
        const mine = state.me && state.me.profile && state.me.profile.id === row.to_caregiver_id;
        const fromName = caregiverName(circle, row.from_caregiver_id);
        const toName = caregiverName(circle, row.to_caregiver_id);
        return "<li data-handoff-id='" + escapeHtml(row.id) + "'><strong>" +
          escapeHtml(row.status) + "</strong><div class='meta'>from " +
          escapeHtml(fromName) + " to " + escapeHtml(toName) +
          (row.note ? " · " + escapeHtml(row.note) : "") + "</div>" +
          (row.status === "pending" && mine
            ? "<div class='actions'><button type='button' data-accept-handoff='" + escapeHtml(row.id) +
              "'>Accept</button><button type='button' class='secondary' data-decline-handoff='" +
              escapeHtml(row.id) + "'>Decline</button></div>"
            : row.status === "pending"
              ? "<p class='meta'>Only the receiving caregiver can accept or decline.</p>"
              : "") + "</li>";
      }),
      "</section>"
    ].join("");
  }

  async function loadPrivacy() {
    const consents = (state.me && state.me.consents) || await api("/api/lifesaver/consents");
    const audit = await api("/api/lifesaver/audit");
    const prefs = (state.me && state.me.profile.accessibility) || {};
    document.getElementById("view-privacy").innerHTML = [
      "<section class='card' id='privacy-center'><h2>Privacy and consent</h2>",
      consents.map(function (row) {
        return "<div class='consent-row'><div><strong>" + escapeHtml(row.label) +
          "</strong><div class='meta'>" + escapeHtml(row.consent_type) + "</div></div>" +
          "<button type='button' class='switch " + (row.granted ? "" : "secondary") +
          "' data-consent='" + escapeHtml(row.consent_type) + "' data-granted='" +
          (row.granted ? "1" : "0") + "'>" + (row.granted ? "On" : "Off") + "</button></div>";
      }).join(""),
      "</section>",
      "<section class='card'><h2>Accessibility</h2>",
      "<label><input type='checkbox' id='pref-large' " + (prefs.large_text ? "checked" : "") + " /> Large text</label>",
      "<label><input type='checkbox' id='pref-contrast' " + (prefs.high_contrast ? "checked" : "") + " /> High contrast</label>",
      "<label><input type='checkbox' id='pref-motion' " + (prefs.reduce_motion ? "checked" : "") + " /> Reduce motion</label>",
      "<label><input type='checkbox' id='pref-sr' " + (prefs.screen_reader_hints ? "checked" : "") + " /> Screen-reader hints</label>",
      "<div class='actions'><button type='button' id='save-a11y'>Save accessibility</button></div></section>",
      "<section class='card' id='ai-card'><h2>AI Care conversation</h2>",
      "<p class='meta'>" + escapeHtml((state.me && state.me.ai_disclaimer) || "") + "</p>",
      "<div id='chat-log' class='chat' aria-live='polite'></div>",
      "<form id='ai-form'><label>Message<input name='message' required /></label>",
      "<div class='actions'><button type='submit'>Send</button></div></form></section>",
      "<section class='card'><h2>Audit trail</h2>",
      renderList(audit, "No audit events yet.", function (row) {
        return "<li><strong>" + escapeHtml(row.action) + "</strong> · " +
          escapeHtml(row.outcome) + "<div class='meta'>" + escapeHtml(row.resource_type) + "</div></li>";
      }),
      "</section>"
    ].join("");
  }

  async function loadView(name) {
    try {
      if (name === "today") await loadToday();
      if (name === "care") await loadCare();
      if (name === "coord") await loadCoord();
      if (name === "circle") await loadCircle();
      if (name === "notify") await loadNotify();
      if (name === "privacy") await loadPrivacy();
    } catch (err) {
      showBanner(err.message, "error");
    }
  }

  async function afterLogin() {
    loginCard.classList.add("hidden");
    loginCard.setAttribute("aria-hidden", "true");
    appShell.classList.remove("hidden");
    appShell.removeAttribute("aria-hidden");
    await loadMe();
    setView(state.view || "today");
    showBanner("", "");
  }

  loginForm.addEventListener("submit", async function (event) {
    event.preventDefault();
    try {
      const response = await fetch("/api/auth/login", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          email: document.getElementById("login-email").value,
          password: document.getElementById("login-password").value,
        }),
      });
      const body = await response.json();
      if (!response.ok) throw new Error(body.detail || "Sign in failed");
      session().start({
        accessToken: body.access_token,
        refreshToken: body.refresh_token,
        email: body.email,
        name: body.display_name,
        role: body.role,
        userId: body.user_id,
        organizationId: body.organization_id,
        organization_name: body.organization_name,
        authorizedRoles: body.authorized_roles,
      });
      await afterLogin();
    } catch (err) {
      showBanner(err.message, "error");
    }
  });

  document.getElementById("sign-out").addEventListener("click", function () {
    session().clear();
    window.location.reload();
  });

  document.body.addEventListener("click", async function (event) {
    const target = event.target;
    if (!(target instanceof HTMLElement)) return;
    if (target.dataset.view) {
      if (target.dataset.jump === "ai") {
        state.view = "privacy";
        setView("privacy");
        setTimeout(function () {
          const card = document.getElementById("ai-card");
          if (card) card.focus ? card.scrollIntoView({ behavior: "smooth" }) : card.scrollIntoView();
        }, 50);
        return;
      }
      setView(target.dataset.view);
      return;
    }
    try {
      if (target.dataset.ackReminder) {
        await api("/api/lifesaver/reminders/" + target.dataset.ackReminder + "/acknowledge", { method: "POST" });
        await loadToday();
      }
      if (target.dataset.consent) {
        await api("/api/lifesaver/consents", {
          method: "POST",
          body: JSON.stringify({
            consent_type: target.dataset.consent,
            granted: target.dataset.granted !== "1",
          }),
        });
        await loadMe();
        await loadPrivacy();
        showBanner("Consent updated.", "ok");
      }
      if (target.id === "save-a11y") {
        const prefs = {
          large_text: document.getElementById("pref-large").checked,
          high_contrast: document.getElementById("pref-contrast").checked,
          reduce_motion: document.getElementById("pref-motion").checked,
          screen_reader_hints: document.getElementById("pref-sr").checked,
        };
        await api("/api/lifesaver/accessibility", { method: "PUT", body: JSON.stringify(prefs) });
        applyA11y(prefs);
        showBanner("Accessibility saved.", "ok");
      }
      if (target.id === "transport-request") {
        await api("/api/lifesaver/transport", {
          method: "POST",
          body: JSON.stringify({ status: "requested", confirm: true }),
        });
        await loadCare();
      }
      if (target.dataset.confirmSos) {
        await api("/api/lifesaver/sos/" + target.dataset.confirmSos + "/confirm", {
          method: "POST",
          body: JSON.stringify({ confirm: true, understood_not_emergency: true }),
        });
        await loadCare();
      }
      if (target.dataset.revoke) {
        await api("/api/lifesaver/circle/" + target.dataset.revoke + "/revoke", { method: "POST" });
        await loadCircle();
      }
      if (target.dataset.ackAlert) {
        await api("/api/lifesaver/alerts/" + target.dataset.ackAlert + "/acknowledge", { method: "POST" });
        await loadCircle();
      }
      if (target.dataset.completeTask) {
        await api("/api/lifesaver/tasks/" + target.dataset.completeTask + "/complete", { method: "POST" });
        await loadCircle();
      }
      if (target.dataset.acceptHandoff) {
        await api("/api/lifesaver/handoffs/" + target.dataset.acceptHandoff + "/accept", { method: "POST" });
        await loadCircle();
      }
      if (target.dataset.declineHandoff) {
        await api("/api/lifesaver/handoffs/" + target.dataset.declineHandoff + "/decline", { method: "POST" });
        await loadCircle();
      }
      if (target.dataset.coordFilter) {
        state.coordFilter = target.dataset.coordFilter;
        await loadCoord();
      }
      if (target.dataset.confirmTreq) {
        await api("/api/lifesaver/transport/requests/" + target.dataset.confirmTreq + "/confirm", {
          method: "POST",
          body: JSON.stringify({ confirm: true }),
        });
        await loadCoord();
      }
      if (target.dataset.handoffTreq) {
        await api("/api/lifesaver/transport/requests/" + target.dataset.handoffTreq + "/handoff-simulated", { method: "POST" });
        await loadCoord();
      }
      if (target.dataset.cancelTreq) {
        await api("/api/lifesaver/transport/requests/" + target.dataset.cancelTreq + "/cancel", { method: "POST" });
        await loadCoord();
      }
      if (target.dataset.noticeDeliver) {
        await api("/api/lifesaver/notifications/" + target.dataset.noticeDeliver + "/simulate-deliver", { method: "POST" });
        await loadNotify();
      }
      if (target.dataset.noticeFail) {
        await api("/api/lifesaver/notifications/" + target.dataset.noticeFail + "/simulate-fail", { method: "POST" });
        await loadNotify();
      }
      if (target.dataset.noticeRetry) {
        await api("/api/lifesaver/notifications/" + target.dataset.noticeRetry + "/retry", { method: "POST" });
        await loadNotify();
      }
      if (target.dataset.noticeSuppress) {
        await api("/api/lifesaver/notifications/" + target.dataset.noticeSuppress + "/suppress", { method: "POST" });
        await loadNotify();
      }
    } catch (err) {
      showBanner(err.message, "error");
    }
  });

  document.body.addEventListener("change", function (event) {
    if (event.target && event.target.id === "member-select") {
      state.memberProfileId = event.target.value;
      loadView(state.view);
    }
  });

  document.body.addEventListener("submit", async function (event) {
    const form = event.target;
    if (!(form instanceof HTMLFormElement)) return;
    if (form.id === "login-form") return;
    event.preventDefault();
    const data = new FormData(form);
    try {
      if (form.id === "med-form") {
        await api("/api/lifesaver/medications", {
          method: "POST",
          body: JSON.stringify({
            name: data.get("name"),
            instructions: data.get("instructions"),
            schedule_times: String(data.get("schedule") || "").split(",").map(function (item) { return item.trim(); }).filter(Boolean),
          }),
        });
        await loadCare();
      }
      if (form.id === "appt-form") {
        await api("/api/lifesaver/appointments", {
          method: "POST",
          body: JSON.stringify({
            title: data.get("title"),
            location: data.get("location"),
            starts_at: new Date(String(data.get("starts_at"))).toISOString(),
          }),
        });
        await loadCare();
      }
      if (form.id === "wellness-form") {
        await api("/api/lifesaver/wellness", {
          method: "POST",
          body: JSON.stringify({
            mood: data.get("mood"),
            energy: data.get("energy"),
            notes: data.get("notes"),
            notify_caregivers: Boolean(data.get("notify")),
          }),
        });
        await loadCare();
      }
      if (form.id === "journal-form") {
        await api("/api/lifesaver/journal", {
          method: "POST",
          body: JSON.stringify({ body: data.get("body") }),
        });
        await loadCare();
      }
      if (form.id === "reading-form") {
        const secondary = data.get("value_secondary");
        await api("/api/lifesaver/readings", {
          method: "POST",
          body: JSON.stringify({
            reading_type: data.get("reading_type"),
            value_primary: Number(data.get("value_primary")),
            value_secondary: secondary ? Number(secondary) : null,
            source: data.get("source"),
          }),
        });
        await loadCare();
      }
      if (form.id === "device-form") {
        const secondary = data.get("value_secondary");
        await api("/api/lifesaver/readings/simulated-device", {
          method: "POST",
          body: JSON.stringify({
            reading_type: data.get("reading_type"),
            value_primary: Number(data.get("value_primary")),
            value_secondary: secondary ? Number(secondary) : null,
            device_alias: data.get("device_alias"),
            source: "simulated_device",
          }),
        });
        await loadCare();
      }
      if (form.id === "treq-form") {
        const pickup = data.get("pickup_at");
        await api("/api/lifesaver/transport/requests", {
          method: "POST",
          body: JSON.stringify({
            appointment_id: data.get("appointment_id") || null,
            pickup_at: pickup ? new Date(String(pickup)).toISOString() : null,
            pickup_label: data.get("pickup_label"),
            destination_label: data.get("destination_label"),
            accessibility_needs: data.get("accessibility_needs"),
            mobility_note: data.get("mobility_note"),
            companion_needed: Boolean(data.get("companion_needed")),
          }),
        });
        await loadCoord();
      }
      if (form.id === "notice-form") {
        await api("/api/lifesaver/notifications", {
          method: "POST",
          body: JSON.stringify({
            notification_type: data.get("notification_type"),
            channel: data.get("channel"),
            title: data.get("title"),
            reason: data.get("reason"),
            recipient_profile_id: data.get("recipient_profile_id") || null,
            recipient_role: "caregiver",
          }),
        });
        await loadNotify();
      }
      if (form.id === "sos-form") {
        await api("/api/lifesaver/sos/start", {
          method: "POST",
          body: JSON.stringify({ note: data.get("note") }),
        });
        await loadCare();
      }
      if (form.id === "invite-form") {
        await api("/api/lifesaver/circle/invite", {
          method: "POST",
          body: JSON.stringify({ caregiver_email: data.get("email") }),
        });
        await loadCircle();
      }
      if (form.classList.contains("perm-form")) {
        const permissions = data.getAll("permission");
        await api("/api/lifesaver/circle/" + form.getAttribute("data-link-id") + "/permissions", {
          method: "PATCH",
          body: JSON.stringify({ permissions: permissions }),
        });
        await loadCircle();
      }
      if (form.id === "handoff-form") {
        await api("/api/lifesaver/handoffs", {
          method: "POST",
          body: JSON.stringify({
            member_profile_id: data.get("member_profile_id") || null,
            from_caregiver_id: data.get("from_caregiver_id"),
            to_caregiver_id: data.get("to_caregiver_id"),
            note: data.get("note"),
          }),
        });
        await loadCircle();
      }
      if (form.id === "task-form") {
        await api("/api/lifesaver/tasks", {
          method: "POST",
          body: JSON.stringify({ title: data.get("title") }),
        });
        await loadCircle();
      }
      if (form.id === "ai-form") {
        const result = await api("/api/lifesaver/ai/converse", {
          method: "POST",
          body: JSON.stringify({ message: data.get("message") }),
        });
        const log = document.getElementById("chat-log");
        log.innerHTML += "<div class='bubble user'>" + escapeHtml(data.get("message")) + "</div>";
        log.innerHTML += "<div class='bubble'>" + escapeHtml(result.reply) + "</div>";
        form.reset();
      }
      showBanner("Saved.", "ok");
    } catch (err) {
      showBanner(err.message, "error");
    }
  });

  async function boot() {
    if (location.hostname === "127.0.0.1" || location.hostname === "localhost") {
      const hint = document.getElementById("local-login-hint");
      if (hint) hint.classList.remove("hidden");
      const email = document.getElementById("login-email");
      if (email && !email.value) email.value = "rider@amicor.local";
    }
    try {
      if (session() && session().restore) session().restore();
      if (session() && session().ensureReady) await session().ensureReady();
      if (session() && session().getAuthHeaders && session().getAuthHeaders().Authorization) {
        await afterLogin();
      }
    } catch (_) {
      session() && session().clear && session().clear();
    }
  }

  boot();
})();
