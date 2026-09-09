"use strict";

(function () {
  var state = { messageId: null, notificationId: null };

  function $(id) { return document.getElementById(id); }
  function session() { return window.AmiCorSession || null; }
  function token() { return session() && session().getAccessToken ? session().getAccessToken() : ""; }
  function identity() {
    var current = session() && session().getCurrent ? session().getCurrent() : null;
    return current && current.identity ? current.identity : null;
  }
  function showBanner(message, ok) {
    var el = $("banner");
    el.textContent = message;
    el.classList.remove("hidden");
    el.classList.toggle("ok", !!ok);
  }
  function errorText(payload, fallback) {
    if (!payload) return fallback;
    if (typeof payload.detail === "string") return payload.detail;
    return fallback;
  }
  function escapeHtml(value) {
    return String(value || "")
      .replace(/&/g, "&amp;")
      .replace(/</g, "&lt;")
      .replace(/>/g, "&gt;")
      .replace(/"/g, "&quot;");
  }
  function listHtml(items, empty, render) {
    if (!items || !items.length) return empty;
    return items.map(render).join("");
  }
  async function api(path, options) {
    var headers = { "Content-Type": "application/json" };
    if (session() && session().getAuthHeaders) Object.assign(headers, session().getAuthHeaders());
    else if (token()) headers.Authorization = "Bearer " + token();
    var response = await fetch(path, Object.assign({}, options || {}, { headers: headers }));
    var body = null;
    try { body = await response.json(); } catch (_) {}
    if (response.status === 401) throw new Error("Session expired. Sign in to continue.");
    if (!response.ok) throw new Error(errorText(body, "Request failed (" + response.status + ")"));
    return body;
  }
  function setSignedIn(on) {
    $("sign-out").classList.toggle("hidden", !on);
    $("login-form").classList.add("hidden");
    var ident = identity();
    $("session-meta").textContent = on
      ? ((ident && (ident.name || ident.email)) || "Signed in") + " · Mrs. Nova Brain"
      : "Sign in to use Nova Communications.";
  }
  function renderDashboard(data) {
    $("inbox-list").innerHTML = listHtml(data.inbox, "No messages yet.", function (row) {
      return "<div class=\"item " + (row.read ? "" : "unread") + "\"><button class=\"linkish\" data-open-message=\"" +
        escapeHtml(row.message_id) + "\">" + escapeHtml(row.subject) + "</button><div class=\"muted\">" +
        escapeHtml(row.sender) + " · " + escapeHtml(row.created_at) + "</div></div>";
    });
    $("important-list").innerHTML = listHtml(data.important, "No important messages.", function (row) {
      return "<div class=\"item\">" + escapeHtml(row.subject) + "<div class=\"muted\">" + escapeHtml(row.sender) + "</div></div>";
    });
    $("draft-list").innerHTML = listHtml(data.drafts, "No drafts yet.", function (row) {
      return "<div class=\"item\">" + escapeHtml(row.subject) + "<div class=\"muted\">" + escapeHtml((row.to || []).join(", ")) +
        " · " + escapeHtml(row.status) + "</div></div>";
    });
    $("calendar-today").innerHTML = "<strong>Today</strong>" + listHtml(data.today, "<div class=\"muted\">Nothing today.</div>", function (row) {
      return "<div class=\"item\">" + escapeHtml(row.title) + "<div class=\"muted\">" + escapeHtml(row.start_time) +
        (row.location ? " · " + escapeHtml(row.location) : "") + "</div></div>";
    });
    $("calendar-upcoming").innerHTML = "<strong>Upcoming</strong>" + listHtml(data.upcoming, "<div class=\"muted\">No upcoming events.</div>", function (row) {
      return "<div class=\"item\">" + escapeHtml(row.title) + "<div class=\"muted\">" + escapeHtml(row.start_time) +
        " · " + escapeHtml((row.attendees || []).join(", ")) + "</div></div>";
    });
    $("contact-list").innerHTML = listHtml(data.contacts, "No contacts derived yet.", function (row) {
      return "<div class=\"item\"><strong>" + escapeHtml(row.name) + "</strong><div class=\"muted\">" +
        escapeHtml(row.email || "") + " · " + escapeHtml(row.recent_interaction || "") + "</div></div>";
    });
    $("notification-list").innerHTML = listHtml(data.notifications, "No notices yet.", function (row) {
      return "<div class=\"item\"><button class=\"linkish\" data-open-note=\"" + escapeHtml(row.notification_id) + "\">" +
        escapeHtml(row.title) + "</button><div class=\"muted\">" + escapeHtml(row.kind) +
        (row.link ? " · " + escapeHtml(row.link) : "") + "</div></div>";
    });
    $("recent-list").innerHTML = listHtml(data.recent, "No recent communication.", function (row) {
      return "<div class=\"item\">" + escapeHtml(row.title) + "<div class=\"muted\">" + escapeHtml(row.at || "") + "</div></div>";
    });
  }
  async function refresh() {
    if (!token()) {
      setSignedIn(false);
      $("brain-output").textContent = "Mrs. Nova Brain is ready when you are signed in.";
      return;
    }
    setSignedIn(true);
    renderDashboard(await api("/api/nova/communications/dashboard"));
    $("brain-output").textContent = "Mrs. Nova Brain is connected to Nova Communications.";
  }
  async function runBrain(action, question) {
    if (!token()) {
      showBanner("Sign in to ask Mrs. Nova Brain.");
      $("login-form").classList.remove("hidden");
      return;
    }
    var result = await api("/api/nova/communications/ask", {
      method: "POST",
      body: JSON.stringify({
        action: action,
        question: question || $("ask-input").value.trim(),
        message_id: state.messageId,
        notification_id: state.notificationId
      })
    });
    $("brain-output").textContent = result.answer || "No response from Mrs. Nova Brain.";
    if (result.draft) showBanner("Draft saved. Nothing was sent.", true);
    else showBanner("Mrs. Nova Brain used existing Nova intelligence APIs.", true);
    await refresh();
  }
  function speakText(text) {
    if (window.AmiCorHumanVoice && window.AmiCorHumanVoice.createEngine) {
      window.AmiCorHumanVoice.createEngine({ browserFallbackEnabled: true }).speak(text);
      return;
    }
    if (window.speechSynthesis) {
      window.speechSynthesis.speak(new SpeechSynthesisUtterance(text));
    }
  }

  if (session() && session().restore) session().restore();
  refresh().catch(function (err) { showBanner(err.message); });

  $("ask-form").addEventListener("submit", async function (event) {
    event.preventDefault();
    try { await runBrain("ask"); } catch (err) { showBanner(err.message); }
  });
  document.querySelectorAll("[data-brain]").forEach(function (button) {
    button.addEventListener("click", async function () {
      try { await runBrain(button.getAttribute("data-brain")); } catch (err) { showBanner(err.message); }
    });
  });
  $("speak").addEventListener("click", function () {
    speakText($("brain-output").textContent);
  });
  $("dictate").addEventListener("click", function () {
    var Speech = window.SpeechRecognition || window.webkitSpeechRecognition;
    if (!Speech) {
      showBanner("Browser dictation is not available on this device.");
      return;
    }
    var recognition = new Speech();
    recognition.onresult = function (event) {
      $("compose-body").value = event.results[0][0].transcript;
      $("ask-input").value = event.results[0][0].transcript;
      showBanner("Dictation captured locally. Nothing was sent.", true);
    };
    recognition.start();
  });
  $("compose-form").addEventListener("submit", async function (event) {
    event.preventDefault();
    try {
      await api("/api/nova/communications/drafts", {
        method: "POST",
        body: JSON.stringify({
          to: $("compose-to").value ? [$("compose-to").value] : [],
          subject: $("compose-subject").value,
          body: $("compose-body").value
        })
      });
      showBanner("Draft saved using existing email draft store. Nothing was sent.", true);
      await refresh();
    } catch (err) { showBanner(err.message); }
  });
  $("send-blocked").addEventListener("click", async function () {
    try {
      await api("/api/nova/communications/send", {
        method: "POST",
        body: JSON.stringify({ confirm_send: true, to: [$("compose-to").value], subject: $("compose-subject").value, body: $("compose-body").value })
      });
    } catch (err) {
      showBanner(err.message || "Send remains blocked unless explicitly enabled.");
    }
  });
  $("event-form").addEventListener("submit", async function (event) {
    event.preventDefault();
    try {
      await api("/api/nova/communications/events", {
        method: "POST",
        body: JSON.stringify({
          title: $("event-title").value,
          start_time: new Date($("event-start").value).toISOString(),
          end_time: new Date($("event-end").value).toISOString(),
          location: $("event-location").value,
          attendees: $("event-attendees").value ? $("event-attendees").value.split(",").map(function (item) { return item.trim(); }) : []
        })
      });
      showBanner("Local calendar event saved. Health appointments were not changed.", true);
      await refresh();
    } catch (err) { showBanner(err.message); }
  });
  $("contact-search-form").addEventListener("submit", async function (event) {
    event.preventDefault();
    try {
      var query = $("contact-search").value.trim();
      var contacts = await api("/api/nova/communications/contacts" + (query ? ("?q=" + encodeURIComponent(query)) : ""));
      $("contact-list").innerHTML = listHtml(contacts, "No matching people.", function (row) {
        return "<div class=\"item\"><strong>" + escapeHtml(row.name) + "</strong><div class=\"muted\">" +
          escapeHtml(row.email || "") + " · " + escapeHtml(row.recent_interaction || "") + "</div></div>";
      });
    } catch (err) { showBanner(err.message); }
  });
  document.addEventListener("click", async function (event) {
    var messageBtn = event.target.closest("[data-open-message]");
    var noteBtn = event.target.closest("[data-open-note]");
    try {
      if (messageBtn) {
        state.messageId = messageBtn.getAttribute("data-open-message");
        var message = await api("/api/nova/communications/messages/" + encodeURIComponent(state.messageId));
        $("message-detail").innerHTML = "<strong>" + escapeHtml(message.subject) + "</strong><div class=\"muted\">" +
          escapeHtml(message.sender) + "</div><p>" + escapeHtml(message.body || "") + "</p>";
      }
      if (noteBtn) {
        state.notificationId = noteBtn.getAttribute("data-open-note");
        if (!String(state.notificationId).startsWith("WS-")) {
          await api("/api/nova/communications/notifications/" + encodeURIComponent(state.notificationId) + "/read", { method: "POST" });
        }
        showBanner("Opened notification " + state.notificationId + ".", true);
      }
    } catch (err) { showBanner(err.message); }
  });
  $("sign-in-toggle").addEventListener("click", function () {
    $("login-form").classList.toggle("hidden");
  });
  $("login-form").addEventListener("submit", async function (event) {
    event.preventDefault();
    var response = await fetch("/api/auth/login", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ email: $("login-email").value, password: $("login-password").value })
    });
    var payload = await response.json();
    if (!response.ok) {
      showBanner(errorText(payload, "Sign-in failed"));
      return;
    }
    if (session() && session().start) {
      session().start({
        userId: payload.user_id,
        email: payload.email,
        name: payload.display_name,
        role: payload.role,
        accessToken: payload.access_token,
        refreshToken: payload.refresh_token,
        organizationId: payload.organization_id,
        organization_name: payload.organization_name,
        authorizedRoles: payload.authorized_roles
      });
    }
    await refresh();
    showBanner("Signed in. Nova Communications is available.", true);
  });
  $("sign-out").addEventListener("click", async function () {
    if (session() && session().logout) await session().logout();
    window.location.href = "/nova/communications";
  });
})();
