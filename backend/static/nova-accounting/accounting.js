"use strict";

(function () {
  function $(id) { return document.getElementById(id); }
  function session() { return window.AmiCorSession || null; }
  function token() { return session() && session().getAccessToken ? session().getAccessToken() : ""; }
  function identity() {
    var current = session() && session().getCurrent ? session().getCurrent() : null;
    return current && current.identity ? current.identity : null;
  }
  function escapeHtml(value) {
    return String(value || "")
      .replace(/&/g, "&amp;")
      .replace(/</g, "&lt;")
      .replace(/>/g, "&gt;")
      .replace(/"/g, "&quot;");
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
  async function api(path, options) {
    var headers = { "Content-Type": "application/json" };
    if (session() && session().getAuthHeaders) Object.assign(headers, session().getAuthHeaders());
    else if (token()) headers.Authorization = "Bearer " + token();
    var response;
    try {
      response = await fetch(path, Object.assign({}, options || {}, { headers: headers }));
    } catch (_) {
      throw new Error("Network error. Saved work was not changed.");
    }
    var body = null;
    try { body = await response.json(); } catch (_) {}
    if (response.status === 401) throw new Error("Session expired. Sign in again.");
    if (response.status === 403) throw new Error("Access denied.");
    if (response.status === 404) throw new Error("Not found / unavailable.");
    if (response.status >= 500) throw new Error("Temporary system error.");
    if (!response.ok) throw new Error(errorText(body, "Request failed."));
    return body;
  }
  function moneyText(amount) {
    if (typeof amount !== "number") return "Unavailable";
    return "$" + amount.toFixed(2);
  }
  function documentMoney(amount, currency) {
    if (typeof amount !== "number") return "Not found";
    return (currency === "USD" ? "$" : "") + amount.toFixed(2) + (currency && currency !== "USD" && currency !== "UNKNOWN" ? " " + currency : "");
  }
  function renderDocumentResult(result) {
    var host = $("financial-document-result");
    if (!host) return;
    var fields = [
      ["Type", result.document_type || "Unknown"],
      ["Vendor / customer", result.vendor_or_customer || "Not found"],
      ["Invoice #", result.invoice_number || "—"],
      ["Receipt #", result.receipt_number || "—"],
      ["Document date", result.document_date || "Not found"],
      ["Due date", result.due_date || "—"],
      ["Subtotal", documentMoney(result.subtotal, result.currency)],
      ["Tax", documentMoney(result.tax, result.currency)],
      ["Tip", documentMoney(result.tip, result.currency)],
      ["Total", documentMoney(result.total, result.currency)],
      ["Confidence", typeof result.confidence === "number" ? Math.round(result.confidence * 100) + "%" : "Unknown"]
    ];
    var warnings = Array.isArray(result.warnings) ? result.warnings : [];
    var check = result.math_check || {};
    var checkClass = check.status === "matches" ? "document-check-ok" : "document-check-review";
    var checkText = check.status === "matches" ? "Numbers reconcile." :
      (check.status === "review" ? "Numbers need review. Difference: " + documentMoney(check.difference, result.currency) : "Not enough data to reconcile totals.");
    host.innerHTML =
      "<div class=\"document-summary-grid\">" +
      fields.map(function (row) {
        return "<div class=\"document-field\"><strong>" + escapeHtml(row[0]) + "</strong><span>" + escapeHtml(row[1]) + "</span></div>";
      }).join("") +
      "</div>" +
      "<p class=\"" + checkClass + "\">" + escapeHtml(checkText) + "</p>" +
      (warnings.length ? "<div><strong>Review flags</strong><ul class=\"document-warnings\">" +
        warnings.map(function (item) { return "<li>" + escapeHtml(item) + "</li>"; }).join("") + "</ul></div>" : "<p class=\"document-check-ok\">No review flags detected.</p>") +
      "<p class=\"hint\">Review only. Nova did not send an invoice, collect payment, or write to a ledger.</p>";
    host.classList.remove("hidden");
  }
  async function uploadAndProcessDocument(file) {
    if (!token()) throw new Error("Sign in before processing a financial document.");
    var headers = {};
    if (session() && session().getAuthHeaders) Object.assign(headers, session().getAuthHeaders());
    else if (token()) headers.Authorization = "Bearer " + token();
    var form = new FormData();
    form.append("file", file);
    var uploadResponse = await fetch("/api/upload", { method: "POST", headers: headers, body: form });
    var uploadBody = null;
    try { uploadBody = await uploadResponse.json(); } catch (_) {}
    if (!uploadResponse.ok) throw new Error(errorText(uploadBody, "Document upload failed."));
    if (!uploadBody || !uploadBody.extracted_text) throw new Error("Nova could not extract readable text from this document.");
    return api("/api/nova/accounting/process-document", {
      method: "POST",
      body: JSON.stringify({
        filename: uploadBody.filename || file.name,
        upload_category: uploadBody.upload_category || null,
        extracted_text: uploadBody.extracted_text
      })
    });
  }
  var currentWindow = "all";
  function renderMetrics(metrics) {
    var host = $("metrics-box");
    if (!host) return;
    if (!metrics || !metrics.length) {
      host.innerHTML = "<p class=\"hint\">Unavailable</p>";
      return;
    }
    host.innerHTML = metrics.map(function (row) {
      var unavailable = !row || row.status === "unavailable" || row.amount_usd == null;
      var state = unavailable ? "unavailable" : (row.state || "unavailable");
      var value = unavailable ? "Unavailable" : moneyText(row.amount_usd);
      var windowLabel = row.window_label || "All time";
      var sourceNote = row.source_note || "";
      return "<article class=\"metric-card\" data-metric-key=\"" + escapeHtml(row.key || "") + "\">" +
        "<h3>" + escapeHtml(row.label || "Metric") + "</h3>" +
        "<p class=\"state " + escapeHtml(state) + "\">" + escapeHtml(state) + "</p>" +
        "<p class=\"window-label\">" + escapeHtml(windowLabel) + "</p>" +
        "<p class=\"source-note\">" + escapeHtml(sourceNote) + "</p>" +
        "<p class=\"value\">" + escapeHtml(value) + "</p>" +
        "<p class=\"definition\">" + escapeHtml(row.definition || "") + "</p>" +
        "</article>";
    }).join("");
  }
  function setWindowButtons() {
    document.querySelectorAll(".window-btn").forEach(function (btn) {
      btn.setAttribute("aria-pressed", btn.getAttribute("data-window") === currentWindow ? "true" : "false");
    });
  }
  function setSignedIn(on) {
    $("sign-out").classList.toggle("hidden", !on);
    $("login-form").classList.add("hidden");
    var ident = identity();
    $("session-meta").textContent = on
      ? ((ident && (ident.name || ident.email)) || "Signed in") + " · Stripe TEST · read-only"
      : "Sign in to load accounting totals.";
  }
  async function refresh() {
    if (!token()) {
      setSignedIn(false);
      return;
    }
    var summary = await api("/api/nova/accounting/summary?window=" + encodeURIComponent(currentWindow));
    setSignedIn(true);
    try {
      renderMetrics(summary.metrics);
    } catch (_) {
      renderMetrics([]);
    }
  }
  document.querySelectorAll(".window-btn").forEach(function (btn) {
    btn.addEventListener("click", function () {
      currentWindow = btn.getAttribute("data-window") || "all";
      setWindowButtons();
      refresh().catch(function (err) { showBanner(err.message || String(err)); });
    });
  });
  $("financial-document-form").addEventListener("submit", function (event) {
    event.preventDefault();
    var input = $("financial-document-file");
    var file = input && input.files && input.files[0];
    if (!file) {
      showBanner("Choose a receipt or invoice first.");
      return;
    }
    $("financial-document-process").disabled = true;
    $("financial-document-status").textContent = "Nova is reading and checking " + file.name + "…";
    $("financial-document-result").classList.add("hidden");
    uploadAndProcessDocument(file).then(function (result) {
      renderDocumentResult(result);
      $("financial-document-status").textContent = result.review_required
        ? "Processed. Review the flagged fields before using the result."
        : "Processed. Review the extracted fields before using the result.";
      showBanner("Document processed for review. No financial action was executed.", true);
    }).catch(function (err) {
      $("financial-document-status").textContent = "Processing failed.";
      showBanner(err.message || String(err));
    }).finally(function () {
      $("financial-document-process").disabled = false;
    });
  });
  $("sign-in-toggle").addEventListener("click", function () {
    $("login-form").classList.toggle("hidden");
  });
  $("sign-out").addEventListener("click", function () {
    if (session() && session().logout) session().logout();
    setSignedIn(false);
    showBanner("Signed out.", true);
  });
  $("login-form").addEventListener("submit", function (event) {
    event.preventDefault();
    api("/api/auth/login", {
      method: "POST",
      body: JSON.stringify({
        email: $("login-email").value.trim(),
        password: $("login-password").value
      })
    }).then(function (payload) {
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
      return refresh();
    }).then(function () {
      showBanner("Signed in. Accounting totals are read-only.", true);
    }).catch(function (err) {
      showBanner(err.message || String(err));
    });
  });
  if (session() && session().restore) session().restore();
  refresh().catch(function (err) { showBanner(err.message || String(err)); });
})();
