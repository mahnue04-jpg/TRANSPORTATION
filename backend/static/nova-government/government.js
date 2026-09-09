"use strict";

(function () {
  var state = { itemId: null };

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
      : "Sign in to use Nova Government.";
  }
  function itemHtml(row, extraClass) {
    return "<div class=\"item " + (extraClass || "") + "\"><button class=\"linkish\" data-open-item=\"" +
      escapeHtml(row.item_id) + "\">" + escapeHtml(row.title) + "</button><div class=\"agency\">" +
      escapeHtml(row.agency || "No agency saved") + " · " + escapeHtml(row.government_level) +
      " · " + escapeHtml(row.status) + "</div><div class=\"muted\">Due " +
      escapeHtml(row.due_date || "none") + " · Renewal " + escapeHtml(row.renewal_date || "none") +
      "</div></div>";
  }
  function renderDashboard(data) {
    $("section-list").innerHTML = listHtml(data.sections, "No sections yet.", function (row) {
      return "<div class=\"item\"><strong>" + escapeHtml(row.label) + "</strong><div class=\"muted\">" +
        escapeHtml(row.count) + " saved items</div></div>";
    });
    $("work-list").innerHTML = listHtml(data.saved_work, "No saved government work yet.", function (row) {
      return itemHtml(row);
    });
    $("deadline-list").innerHTML = listHtml(data.upcoming_deadlines, "No upcoming deadlines.", function (row) {
      return itemHtml(row, "deadline");
    });
    $("renewal-list").innerHTML = listHtml(data.renewals, "No upcoming renewals.", function (row) {
      return itemHtml(row, "deadline");
    });
    var waiting = (data.overdue || []).concat(data.waiting_response || []);
    $("waiting-list").innerHTML = listHtml(waiting, "None.", function (row) {
      return itemHtml(row, row.due_date ? "overdue" : "");
    });
    $("program-list").innerHTML = listHtml(data.programs, "No saved programs.", function (row) {
      return "<div class=\"item\"><strong>" + escapeHtml(row.program_name) + "</strong><div class=\"muted\">" +
        escapeHtml(row.agency || "") + " · " + escapeHtml(row.status) + "</div></div>";
    });
  }
  async function loadItemExtras(itemId) {
    var checks = await api("/api/nova/government/items/" + encodeURIComponent(itemId) + "/checklist");
    $("check-list").innerHTML = listHtml(checks, "No checklist items yet.", function (row) {
      return "<div class=\"item\">" + (row.completed ? "✓ " : "○ ") + escapeHtml(row.label) +
        (row.file_id ? "<div class=\"muted\">Workspace file " + escapeHtml(row.file_id) + "</div>" : "") +
        "</div>";
    });
    var sources = await api("/api/nova/government/items/" + encodeURIComponent(itemId) + "/sources");
    $("source-list").innerHTML = listHtml(sources, "No sources saved.", function (row) {
      return "<div class=\"item\"><strong>" + escapeHtml(row.page_title) + "</strong><div class=\"muted\">" +
        escapeHtml(row.verification_status) + " · " + escapeHtml(row.source_url || "no URL") + "</div></div>";
    });
  }
  async function refresh() {
    if (!token()) {
      setSignedIn(false);
      $("brain-output").textContent = "Mrs. Nova Brain is ready when you are signed in.";
      return;
    }
    setSignedIn(true);
    renderDashboard(await api("/api/nova/government/dashboard"));
    if (state.itemId) await loadItemExtras(state.itemId);
    $("brain-output").textContent = "Mrs. Nova Brain is connected to Nova Government. AI SUGGESTION is not an official ruling.";
  }
  async function runBrain(action, question) {
    if (!token()) {
      showBanner("Sign in to ask Mrs. Nova Brain.");
      $("login-form").classList.remove("hidden");
      return;
    }
    var result = await api("/api/nova/government/ask", {
      method: "POST",
      body: JSON.stringify({
        action: action,
        question: question || $("ask-input").value.trim(),
        item_id: state.itemId
      })
    });
    $("brain-output").textContent = (result.fact_label || "AI SUGGESTION") + "\n\n" + (result.answer || "No response from Mrs. Nova Brain.");
    $("fact-label").textContent = result.fact_label || "AI SUGGESTION is not an official government ruling.";
    showBanner("Mrs. Nova Brain used existing Nova intelligence. Nothing was filed or sent.", true);
    await refresh();
  }

  if (session() && session().restore) session().restore();
  refresh().catch(function (err) { showBanner(err.message); });

  $("search-form").addEventListener("submit", async function (event) {
    event.preventDefault();
    try {
      var result = await api("/api/nova/government/search", {
        method: "POST",
        body: JSON.stringify({
          query: $("gov-search").value.trim(),
          government_level: $("search-level").value || null,
          category: $("search-category").value || null
        })
      });
      var sources = (result.web && result.web.sources) || [];
      $("search-results").innerHTML =
        "<p class=\"muted\">" + escapeHtml(result.disclaimer || "") + "</p>" +
        listHtml(result.saved_work, "<div class=\"muted\">No matching saved work.</div>", function (row) {
          return itemHtml(row);
        }) +
        listHtml(sources, "<div class=\"muted\">No web sources returned.</div>", function (row) {
          return "<div class=\"item\">" + escapeHtml(row.title || row.url || "Source") +
            "<div class=\"muted\">" + escapeHtml(row.url || "") + "</div></div>";
        });
      showBanner("Search reused existing Nova/web search. Results are research aids only.", true);
    } catch (err) { showBanner(err.message); }
  });
  $("ask-form").addEventListener("submit", async function (event) {
    event.preventDefault();
    try { await runBrain("ask"); } catch (err) { showBanner(err.message); }
  });
  document.querySelectorAll("[data-brain]").forEach(function (button) {
    button.addEventListener("click", async function () {
      try { await runBrain(button.getAttribute("data-brain")); } catch (err) { showBanner(err.message); }
    });
  });
  $("item-form").addEventListener("submit", async function (event) {
    event.preventDefault();
    try {
      var created = await api("/api/nova/government/items", {
        method: "POST",
        body: JSON.stringify({
          title: $("item-title").value,
          agency: $("item-agency").value || null,
          government_level: $("item-level").value,
          category: $("item-category").value,
          state: $("item-state").value || null,
          county: $("item-county").value || null,
          city: $("item-city").value || null,
          due_date: $("item-due").value || null,
          renewal_date: $("item-renewal").value || null,
          workspace_id: $("item-workspace").value || null,
          file_id: $("item-file").value || null,
          notes: $("item-notes").value || null
        })
      });
      state.itemId = created.item_id;
      showBanner("Government work saved as USER-SAVED INFORMATION. Nothing was filed.", true);
      await refresh();
    } catch (err) { showBanner(err.message); }
  });
  $("program-form").addEventListener("submit", async function (event) {
    event.preventDefault();
    try {
      await api("/api/nova/government/programs", {
        method: "POST",
        body: JSON.stringify({
          program_name: $("program-name").value,
          agency: $("program-agency").value || null
        })
      });
      showBanner("Grant/funding program saved for organization only. No scraping or filing.", true);
      await refresh();
    } catch (err) { showBanner(err.message); }
  });
  $("check-form").addEventListener("submit", async function (event) {
    event.preventDefault();
    if (!state.itemId) {
      showBanner("Open or save a work item before adding a checklist.");
      return;
    }
    try {
      await api("/api/nova/government/items/" + encodeURIComponent(state.itemId) + "/checklist", {
        method: "POST",
        body: JSON.stringify({
          label: $("check-label").value,
          file_id: $("check-file").value || null
        })
      });
      showBanner("Checklist item saved. Files stay in Nova Workspace.", true);
      await refresh();
    } catch (err) { showBanner(err.message); }
  });
  $("source-form").addEventListener("submit", async function (event) {
    event.preventDefault();
    if (!state.itemId) {
      showBanner("Open or save a work item before adding a source.");
      return;
    }
    try {
      await api("/api/nova/government/items/" + encodeURIComponent(state.itemId) + "/sources", {
        method: "POST",
        body: JSON.stringify({
          page_title: $("source-title").value,
          source_url: $("source-url").value || null,
          verification_status: $("source-status").value
        })
      });
      showBanner("Source saved with verification status. This is not an official ruling.", true);
      await refresh();
    } catch (err) { showBanner(err.message); }
  });
  document.addEventListener("click", async function (event) {
    var openBtn = event.target.closest("[data-open-item]");
    if (!openBtn) return;
    try {
      state.itemId = openBtn.getAttribute("data-open-item");
      var item = await api("/api/nova/government/items/" + encodeURIComponent(state.itemId));
      showBanner("Opened USER-SAVED INFORMATION: " + item.title + ".", true);
      await loadItemExtras(state.itemId);
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
    showBanner("Signed in. Nova Government is available.", true);
  });
  $("sign-out").addEventListener("click", async function () {
    if (session() && session().logout) await session().logout();
    window.location.href = "/nova/government";
  });
})();
