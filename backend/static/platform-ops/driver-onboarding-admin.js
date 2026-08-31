(function () {
  const API = "/api/platform-ops/driver-onboarding";
  const APPROVAL_API = "/api/approval-engine";
  const banner = document.getElementById("banner");
  const listEl = document.getElementById("application-list");
  const detailEl = document.getElementById("detail-panel");
  const FETCH_TIMEOUT_MS = 15000;
  const loginForm = document.getElementById("admin-login-form");
  const signOutBtn = document.getElementById("admin-sign-out");
  let signedIn = false;
  let selectedId = null;
  let loginPromise = null;
  let loadPromise = null;

  function showBanner(message, ok) {
    banner.textContent = message;
    banner.className = "banner " + (ok ? "ok" : "error");
    banner.classList.remove("hidden");
  }

  function setSignedIn(value) {
    signedIn = !!value;
    if (loginForm) loginForm.classList.toggle("hidden", signedIn);
    if (signOutBtn) signOutBtn.classList.toggle("hidden", !signedIn);
  }

  function detailText(detail) {
    if (detail == null) return "";
    if (typeof detail === "string") return detail;
    try { return JSON.stringify(detail); } catch (_) { return String(detail); }
  }

  function isAuthFailure(status, detail) {
    // Only hard auth failures — do not treat every 403 as expired token.
    if (status === 401) return true;
    const text = detailText(detail);
    return /token expired|not authenticated|invalid token|invalid token format|signature has expired|could not validate credentials/i.test(text);
  }

  async function sessionLogin(email, password) {
    const controller = new AbortController();
    const timer = setTimeout(function () { controller.abort(); }, FETCH_TIMEOUT_MS);
    let login;
    try {
      login = await fetch("/api/auth/admin-session", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ email: email, password: password }),
        credentials: "same-origin",
        signal: controller.signal,
      });
    } catch (err) {
      if (err && err.name === "AbortError") throw new Error("Login timed out. Try Sign in again.");
      throw err;
    } finally {
      clearTimeout(timer);
    }
    const body = await login.json().catch(function () { return {}; });
    if (!login.ok) throw new Error(detailText(body.detail) || "Login failed");
    setSignedIn(true);
    return body;
  }

  async function sessionLogout() {
    await fetch("/api/auth/admin-session/logout", { method: "POST", credentials: "same-origin" }).catch(function () {});
    setSignedIn(false);
  }

  async function fetchJson(url, options) {
    const controller = new AbortController();
    const timer = setTimeout(function () { controller.abort(); }, FETCH_TIMEOUT_MS);
    const opts = Object.assign({ credentials: "same-origin" }, options || {}, { signal: controller.signal });
    try {
      const response = await fetch(url, opts);
      const json = await response.json().catch(function () { return {}; });
      return { response: response, json: json };
    } catch (err) {
      if (err && err.name === "AbortError") {
        throw new Error("Request timed out after " + (FETCH_TIMEOUT_MS / 1000) + "s. Click Refresh or Sign in.");
      }
      throw err;
    } finally {
      clearTimeout(timer);
    }
  }

  async function requestJson(base, path, options) {
    if (!signedIn) {
      throw new Error("Sign in required. Use the admin sign-in form.");
    }
    const headers = Object.assign({}, (options && options.headers) || {});
    if (options && options.body && !headers["Content-Type"]) {
      headers["Content-Type"] = "application/json";
    }
    const result = await fetchJson(base + path, Object.assign({}, options || {}, { headers: headers }));
    const response = result.response;
    const json = result.json;
    if (!response.ok) {
      if (isAuthFailure(response.status, json.detail)) {
        setSignedIn(false);
        throw new Error("Session expired. Sign in again.");
      }
      throw new Error(detailText(json.detail) || response.statusText || ("HTTP " + response.status));
    }
    return json;
  }

  async function api(path, options) {
    return requestJson(API, path, options);
  }

  async function approvalApi(path, options) {
    return requestJson(APPROVAL_API, path, options);
  }

  async function fetchBlob(url) {
    const controller = new AbortController();
    const timer = setTimeout(function () { controller.abort(); }, FETCH_TIMEOUT_MS);
    try {
      const response = await fetch(url, { credentials: "same-origin", signal: controller.signal });
      if (!response.ok) {
        const json = await response.json().catch(function () { return {}; });
        throw new Error(detailText(json.detail) || ("HTTP " + response.status));
      }
      return await response.blob();
    } finally {
      clearTimeout(timer);
    }
  }

  function fieldValue(root, name) {
    const el = root.querySelector("[name='" + name + "']");
    return el ? String(el.value || "").trim() : "";
  }

  function appendField(form, label, name, type, value) {
    const wrap = document.createElement("label");
    wrap.textContent = label;
    const input = type === "textarea" ? document.createElement("textarea") : document.createElement("input");
    if (type !== "textarea") input.type = type || "text";
    input.name = name;
    if (value) input.value = value;
    wrap.appendChild(input);
    form.appendChild(wrap);
    return input;
  }

  function appendSelect(form, label, name, options, value) {
    const wrap = document.createElement("label");
    wrap.textContent = label;
    const select = document.createElement("select");
    select.name = name;
    options.forEach(function (opt) {
      const option = document.createElement("option");
      option.value = opt;
      option.textContent = opt;
      if (opt === value) option.selected = true;
      select.appendChild(option);
    });
    wrap.appendChild(select);
    form.appendChild(wrap);
    return select;
  }

  function readinessPill(state) {
    return "<span class='pill ready-" + (state || "PENDING") + "'>" + (state || "PENDING") + "</span>";
  }

  function latestDocumentsByCategory(documents) {
    const latest = {};
    const counts = {};
    (documents || []).forEach(function (doc) {
      counts[doc.category] = (counts[doc.category] || 0) + 1;
      const prev = latest[doc.category];
      if (!prev || String(doc.created_at || "") >= String(prev.created_at || "")) {
        latest[doc.category] = doc;
      }
    });
    return { latest: Object.keys(latest).sort().map(function (k) { return latest[k]; }), counts: counts };
  }

  function renderList(items) {
    listEl.innerHTML = "";
    if (!items.length) {
      listEl.innerHTML = "<p class='meta'>No applications found.</p>";
      return;
    }
    items.forEach((item) => {
      const div = document.createElement("div");
      div.className = "list-item" + (item.id === selectedId ? " active" : "");
      const name = item.applicant_name || "Unnamed applicant";
      const docsPct = item.document_completion_percentage != null ? item.document_completion_percentage : "—";
      div.innerHTML = ""
        + "<strong>" + name + "</strong>"
        + "<div class=\"meta\">" + (item.email || "") + " · " + (item.mobile_phone || "") + "</div>"
        + "<div><span class=\"pill\">" + (item.status || "") + "</span> · docs " + docsPct + "%</div>";
      div.addEventListener("click", () => loadDetail(item.id));
      listEl.appendChild(div);
    });
  }

  async function loadList() {
    listEl.innerHTML = "<p class='meta'>Loading applications…</p>";
    const items = await api("/applications");
    if (!Array.isArray(items)) {
      throw new Error("Application list response was not an array.");
    }
    renderList(items);
    return items.length;
  }

  async function refreshWorkspace(options) {
    const opts = options || {};
    if (loadPromise) return loadPromise;
    loadPromise = (async function () {
      showBanner(opts.loadingMessage || "Loading applications…", true);
      try {
        const count = await loadList();
        try {
          await loadDriver001();
        } catch (_) {
          // Driver #001 panel is optional; list load still succeeds.
        }
        showBanner("Loaded " + count + " application" + (count === 1 ? "" : "s") + ".", true);
        return count;
      } catch (err) {
        if (!listEl.innerHTML || listEl.innerHTML.indexOf("Loading applications") >= 0) {
          listEl.innerHTML = "<p class='meta'>Could not load applications. " + (err.message || err) + "</p>";
        }
        throw err;
      } finally {
        loadPromise = null;
      }
    })();
    return loadPromise;
  }

  function actionButton(label, handler, secondary) {
    const btn = document.createElement("button");
    btn.textContent = label;
    if (secondary) btn.className = "secondary";
    btn.addEventListener("click", handler);
    return btn;
  }

  async function loadDetail(id) {
    selectedId = id;
    const app = await api(`/applications/${id}`);
    await loadList();
    detailEl.innerHTML = "";
    const title = document.createElement("h2");
    title.textContent = `${app.legal_first_name || ""} ${app.legal_last_name || ""}`.trim() || "Application";
    detailEl.appendChild(title);

    const meta = document.createElement("p");
    meta.className = "meta";
    meta.textContent = `Platform Ops status: ${app.status} · License exp: ${app.license_expiration_date || "n/a"} · Activated driver: ${app.activated_driver_id || "not activated"}`;
    detailEl.appendChild(meta);

    try {
      const compliance = await approvalApi("/applications/" + encodeURIComponent(id) + "/compliance-summary");
      const board = document.createElement("section");
      board.className = "owner-card";
      board.innerHTML = renderComplianceBoard(compliance);
      detailEl.appendChild(board);
    } catch (_) {}

    const linkBox = document.createElement("section");
    linkBox.className = "owner-card";
    linkBox.innerHTML = "<h3>Applicant access</h3><p class='meta'>Reissue rotates the applicant token for this existing application only. The new link is shown once and is not stored here.</p>";
    const linkToolbar = document.createElement("div");
    linkToolbar.className = "toolbar";
    if (app.status !== "activated" && !app.activated_driver_id) {
      linkToolbar.appendChild(actionButton("Reissue applicant link", async function () {
        try {
          const issued = await api("/applications/" + id + "/applicant-token/reissue", { method: "POST", body: "{}" });
          const applyPath = issued.apply_path || (
            "/platform-ops/driver-apply?organization_id=" + encodeURIComponent(issued.organization_id || app.organization_id || "")
            + "&application_id=" + encodeURIComponent(issued.application_id || id)
            + "&token=" + encodeURIComponent(issued.applicant_access_token || "")
          );
          const abs = window.location.origin + applyPath;
          const once = document.createElement("div");
          once.className = "review-row";
          once.innerHTML = "<p class='meta'>New applicant link (shown once). Previous applicant token is revoked.</p>";
          const urlBox = document.createElement("input");
          urlBox.type = "text";
          urlBox.readOnly = true;
          urlBox.value = abs;
          once.appendChild(urlBox);
          const onceToolbar = document.createElement("div");
          onceToolbar.className = "toolbar";
          onceToolbar.appendChild(actionButton("Open application", function () {
            window.open(abs, "_blank", "noopener");
          }));
          onceToolbar.appendChild(actionButton("Copy link", function () {
            if (navigator.clipboard && navigator.clipboard.writeText) {
              navigator.clipboard.writeText(abs).then(function () {
                showBanner("Applicant link copied. It is not saved in this workspace.", true);
              }).catch(function () {
                urlBox.select();
                showBanner("Select the link and copy it manually.", false);
              });
            } else {
              urlBox.select();
              showBanner("Select the link and copy it manually.", false);
            }
          }, true));
          once.appendChild(onceToolbar);
          linkBox.appendChild(once);
          showBanner("Applicant access reissued for this application. Token is shown once.", true);
        } catch (err) { showBanner(err.message, false); }
      }));
    } else {
      linkBox.innerHTML += "<p class='meta'>Applicant link reissue is locked after activation.</p>";
    }
    linkBox.appendChild(linkToolbar);
    detailEl.appendChild(linkBox);

    const docs = document.createElement("section");
    docs.className = "owner-card";
    docs.innerHTML = "<h3>Admin document review</h3><p class='meta'>Inspect uses an authenticated download. Raw public document URLs are not exposed.</p>";
    const grouped = latestDocumentsByCategory(app.documents || []);
    if (!grouped.latest.length) docs.innerHTML += "<p class='meta'>No documents uploaded.</p>";
    grouped.latest.forEach((doc) => {
      const row = document.createElement("div");
      row.className = "review-row";
      const dup = grouped.counts[doc.category] > 1 ? " · showing latest of " + grouped.counts[doc.category] : "";
      row.innerHTML = "<strong>" + doc.category + "</strong>"
        + "<div class='meta'>Required type: " + doc.category
        + " · upload: " + (doc.original_filename || doc.status_only_value || "none")
        + " · status: " + (doc.review_status || "pending")
        + " · reviewer: " + (doc.reviewed_by || "—")
        + " · reviewed: " + (doc.reviewed_at || "—")
        + dup + "</div>";
      if (doc.review_reason) {
        const note = document.createElement("div");
        note.className = "meta";
        note.textContent = "Notes: " + doc.review_reason;
        row.appendChild(note);
      }
      const notes = document.createElement("input");
      notes.placeholder = "Review notes";
      notes.value = doc.review_reason || "";
      row.appendChild(notes);
      const toolbar = document.createElement("div");
      toolbar.className = "toolbar";
      if (doc.storage_backend !== "status_only") {
        toolbar.appendChild(actionButton("Inspect", async function () {
          try {
            const blob = await fetchBlob(API + "/applications/" + id + "/documents/" + doc.id + "/download");
            const objectUrl = URL.createObjectURL(blob);
            window.open(objectUrl, "_blank", "noopener");
            showBanner("Opened authenticated document inspect (not a public URL).", true);
          } catch (err) { showBanner(err.message, false); }
        }, true));
      }
      ["accepted", "rejected", "correction_requested"].forEach(function (status) {
        const label = status === "accepted" ? "ACCEPT" : status === "rejected" ? "REJECT" : "RETURN / REQUEST CORRECTION";
        toolbar.appendChild(actionButton(label, async function () {
          try {
            await api("/applications/" + id + "/documents/" + doc.id + "/review", {
              method: "PATCH",
              body: JSON.stringify({ review_status: status, review_reason: notes.value || status }),
            });
            showBanner("Document " + status + " recorded with audit trail.", true);
            await loadDetail(selectedId);
          } catch (err) { showBanner(err.message, false); }
        }, status !== "accepted"));
      });
      row.appendChild(toolbar);
      docs.appendChild(row);
    });
    detailEl.appendChild(docs);

    // Owner review experience — Approval Engine is the primary decision surface.
    const approvalSection = document.createElement("section");
    approvalSection.className = "owner-card";
    approvalSection.innerHTML = "<h3>Owner review</h3><p class='meta'>Loading AI Approval Engine case…</p>";
    detailEl.appendChild(approvalSection);
    let approvalCase = null;
    try {
      let cases = await approvalApi("/cases?limit=200");
      approvalCase = (cases || []).find(function (row) {
        return row.platform_ops_application_id === id;
      });
      if (!approvalCase) {
        approvalCase = await approvalApi("/cases", {
          method: "POST",
          body: JSON.stringify({
            platform_ops_application_id: id,
            display_badge: null,
            requested_service_tiers: ["BASE_PRIVATE_AMBULATORY"],
            run_ai_review: true,
          }),
        });
      } else {
        approvalCase = await approvalApi("/cases/" + approvalCase.id + "/ai-review", { method: "POST", body: "{}" });
      }
      const card = approvalCase.approval_card || {};
      const listBlock = function (items, emptyText) {
        if (!items || !items.length) return "<p class='meta'>" + emptyText + "</p>";
        return items.map(function (req) {
          const color = req.traffic_light === "green" ? "#0a7a3e" : req.traffic_light === "yellow" ? "#a36b00" : "#a11";
          return "<div class='meta'><span style='color:" + color + ";font-weight:700'>" + (req.traffic_light || "").toUpperCase()
            + "</span> " + (req.label || req.key) + " · " + (req.status || "")
            + (req.evidence_ref || req.evidence_source ? " · evidence on file" : "")
            + "</div>";
        }).join("");
      };
      const ready = card.ready_for_owner_decision === true;
      approvalSection.innerHTML = ""
        + "<h3>Owner review</h3>"
        + "<div class='owner-grid'>"
        + "<div class='owner-stat'><span class='meta'>Driver</span><strong>" + (approvalCase.legal_name || title.textContent) + "</strong></div>"
        + "<div class='owner-stat'><span class='meta'>Status</span><strong>" + (approvalCase.workflow_status || "") + "</strong></div>"
        + "<div class='owner-stat'><span class='meta'>Readiness</span><strong>" + (approvalCase.readiness_percentage || 0) + "%</strong></div>"
        + "<div class='owner-stat'><span class='meta'>Badge</span><strong>" + (approvalCase.display_badge || "—") + "</strong></div>"
        + "</div>"
        + "<h4>AI recommendation</h4><p>" + (card.ai_recommendation || approvalCase.ai_summary || "—") + "</p>"
        + "<p class='meta'><strong>Next action:</strong> " + (approvalCase.next_required_action || "—") + "</p>"
        + "<h4>Completed</h4>" + listBlock(card.completed_requirements, "None completed yet.")
        + "<h4>Missing</h4>" + listBlock(card.missing_requirements, "No missing blockers.")
        + "<h4>Pending external verifications</h4>" + listBlock(card.pending_external_verifications, "None pending.")
        + "<h4>Legal / compliance blockers</h4>" + listBlock(card.legal_compliance_blockers, "No open legal blockers.")
        + "<h4>Evidence / external tasks</h4>"
        + ((approvalCase.external_tasks || []).map(function (t) {
            return "<div class='meta'>" + (t.title || t.task_type) + " · " + t.status + "</div>";
          }).join("") || "<p class='meta'>None open.</p>")
        + "<h4>Prepared driver messages (not sent)</h4>"
        + ((card.prepared_driver_messages || []).map(function (m) {
            return "<div class='meta'>" + m.message + "</div>";
          }).join("") || "<p class='meta'>None.</p>")
        + (ready
          ? "<p class='banner ok' style='margin-top:0.75rem'>READY FOR OWNER APPROVAL — APPROVE is available.</p>"
          : "<p class='meta' style='margin-top:0.75rem'>APPROVE stays hidden until the case reaches READY_FOR_APPROVAL with no legal blockers.</p>");

      const approvalToolbar = document.createElement("div");
      approvalToolbar.className = "toolbar";
      approvalToolbar.appendChild(actionButton("Run AI review", async function () {
        try {
          await approvalApi("/cases/" + approvalCase.id + "/ai-review", { method: "POST", body: "{}" });
          showBanner("AI review complete", true);
          await loadDetail(selectedId);
        } catch (err) { showBanner(err.message, false); }
      }));
      approvalToolbar.appendChild(actionButton("View audit", async function () {
        try {
          const events = await approvalApi("/cases/" + approvalCase.id + "/audit?limit=50");
          const auditBox = document.createElement("pre");
          auditBox.textContent = (events || []).map(function (e) {
            return (e.created_at || "") + " · " + (e.actor_type || "") + " · " + (e.action || "") + " · " + (e.reason || "");
          }).join("\n") || "No audit events.";
          approvalSection.appendChild(auditBox);
        } catch (err) { showBanner(err.message, false); }
      }, true));
      if (ready) {
        approvalToolbar.appendChild(actionButton("APPROVE", async function () {
          const reason = prompt("Approval notes (optional)", "Owner approved package") || "Owner approved package";
          try {
            await approvalApi("/cases/" + approvalCase.id + "/owner-decision", {
              method: "POST",
              body: JSON.stringify({ decision: "APPROVE", reason: reason }),
            });
            showBanner("Owner approval recorded in audit trail", true);
            await loadDetail(selectedId);
          } catch (err) { showBanner(err.message, false); }
        }));
      }
      approvalToolbar.appendChild(actionButton("RETURN FOR INFORMATION", async function () {
        const reason = prompt("What information is needed?") || "Returned for information";
        try {
          await approvalApi("/cases/" + approvalCase.id + "/owner-decision", {
            method: "POST",
            body: JSON.stringify({ decision: "RETURN_FOR_CORRECTION", reason: reason }),
          });
          showBanner("Returned for information — recorded in audit trail", true);
          await loadDetail(selectedId);
        } catch (err) { showBanner(err.message, false); }
      }, true));
      approvalToolbar.appendChild(actionButton("REJECT", async function () {
        const reason = prompt("Rejection reason");
        if (!reason) return;
        try {
          await approvalApi("/cases/" + approvalCase.id + "/owner-decision", {
            method: "POST",
            body: JSON.stringify({ decision: "REJECT", reason: reason }),
          });
          showBanner("Owner rejection recorded in audit trail", true);
          await loadDetail(selectedId);
        } catch (err) { showBanner(err.message, false); }
      }, true));
      approvalSection.appendChild(approvalToolbar);
    } catch (err) {
      approvalSection.innerHTML = "<h3>Owner review</h3><p class='meta'>Unavailable: " + (err.message || err) + "</p>";
    }

    if (approvalCase) {
      try {
        const readiness = await approvalApi("/cases/" + approvalCase.id + "/readiness-view");
        const readyBox = document.createElement("section");
        readyBox.className = "owner-card";
        readyBox.innerHTML = "<h3>Driver readiness</h3>"
          + "<p class='meta'>PRIVATE and STS/MHCP stay separate. Dispatch eligibility stays blocked in this phase.</p>"
          + ((readiness.items || []).map(function (item) {
            return "<div class='meta'>" + readinessPill(item.state) + " <strong>" + item.label + "</strong> · "
              + (item.status || "—") + (item.tier === "STS_ELIGIBLE" ? " · STS/MHCP" : " · PRIVATE")
              + (item.notes ? " · " + item.notes : "") + "</div>";
          }).join("") || "<p class='meta'>No readiness items.</p>")
          + ((readiness.p1_blockers || []).length
            ? "<p class='meta'>P1 blockers: " + readiness.p1_blockers.join("; ") + "</p>"
            : "");
        detailEl.appendChild(readyBox);
      } catch (err) {
        const readyBox = document.createElement("section");
        readyBox.className = "owner-card";
        readyBox.innerHTML = "<h3>Driver readiness</h3><p class='meta'>" + (err.message || err) + "</p>";
        detailEl.appendChild(readyBox);
      }

      function complianceForm(title, help, fields, submitLabel, handler) {
        const box = document.createElement("section");
        box.className = "owner-card";
        box.innerHTML = "<h3>" + title + "</h3><p class='meta'>" + help + "</p>";
        const form = document.createElement("div");
        form.className = "review-form";
        fields.forEach(function (field) {
          if (field.type === "select") appendSelect(form, field.label, field.name, field.options, field.value);
          else appendField(form, field.label, field.name, field.type, field.value);
        });
        box.appendChild(form);
        const toolbar = document.createElement("div");
        toolbar.className = "toolbar";
        toolbar.appendChild(actionButton(submitLabel, async function () {
          try {
            await handler(form);
            showBanner(title + " recorded.", true);
            await loadDetail(selectedId);
          } catch (err) { showBanner(err.message, false); }
        }));
        box.appendChild(toolbar);
        detailEl.appendChild(box);
        return form;
      }

      complianceForm(
        "Manual MVR review",
        "No live MVR vendor is selected. AI and SYSTEM cannot clear MVR. VERIFIED/CLEARED requires source and evidence.",
        [
          { label: "Status", name: "status", type: "select", options: ["PENDING_EXTERNAL", "VERIFIED", "CLEARED", "FAILED", "DISQUALIFIED", "EXPIRED"] },
          { label: "Source / provider", name: "provider_key" },
          { label: "Reference / case number", name: "provider_reference_id" },
          { label: "Evidence / source note", name: "evidence_source" },
          { label: "Review date", name: "verification_date", type: "date" },
          { label: "Expiration / recheck date", name: "expiration_date", type: "date" },
          { label: "Notes", name: "notes", type: "textarea" },
        ],
        "Record MVR",
        async function (form) {
          await approvalApi("/cases/" + approvalCase.id + "/external/mvr/record", {
            method: "POST",
            body: JSON.stringify({
              status: fieldValue(form, "status"),
              provider_key: fieldValue(form, "provider_key") || undefined,
              provider_reference_id: fieldValue(form, "provider_reference_id") || undefined,
              evidence_source: fieldValue(form, "evidence_source") || undefined,
              verification_date: fieldValue(form, "verification_date") || undefined,
              expiration_date: fieldValue(form, "expiration_date") || undefined,
              notes: fieldValue(form, "notes") || undefined,
              actor_type: "USER",
            }),
          });
        }
      );

      complianceForm(
        "Insurance review",
        "PRIVATE transportation only. A personal policy is not required to be commercial. Expired insurance blocks eligibility.",
        [
          { label: "Insurer / carrier", name: "carrier", value: app.insurance_carrier || "" },
          { label: "Policy number (masked on save)", name: "policy_reference" },
          { label: "Effective date", name: "effective_date", type: "date", value: app.insurance_effective_date || "" },
          { label: "Expiration date", name: "expiration_date", type: "date", value: app.insurance_expiration_date || "" },
          { label: "Vehicle association", name: "vehicle_association" },
          { label: "Review status", name: "review_status", type: "select", options: ["pending", "accepted", "rejected", "expired", "correction_requested"], value: app.insurance_review_status || "pending" },
          { label: "Evidence / document reference", name: "evidence_ref" },
          { label: "Notes", name: "notes", type: "textarea" },
        ],
        "Save insurance review",
        async function (form) {
          await approvalApi("/cases/" + approvalCase.id + "/insurance-review", {
            method: "POST",
            body: JSON.stringify({
              carrier: fieldValue(form, "carrier") || undefined,
              policy_reference: fieldValue(form, "policy_reference") || undefined,
              effective_date: fieldValue(form, "effective_date") || undefined,
              expiration_date: fieldValue(form, "expiration_date") || undefined,
              vehicle_association: fieldValue(form, "vehicle_association") || undefined,
              review_status: fieldValue(form, "review_status") || "pending",
              evidence_ref: fieldValue(form, "evidence_ref") || undefined,
              notes: fieldValue(form, "notes") || undefined,
            }),
          });
        }
      );

      complianceForm(
        "Contractor agreement",
        "Typed/uploaded acceptance is preserved. No live e-sign vendor is connected.",
        [
          { label: "Agreement version", name: "version", value: app.agreement_version || "" },
          { label: "Status", name: "status", type: "select", options: ["pending", "accepted", "signed", "returned", "expired"], value: app.agreement_status || "accepted" },
          { label: "Accepted / signed date", name: "accepted_at", type: "date" },
          { label: "Evidence document id", name: "evidence_document_id" },
          { label: "Notes", name: "notes", type: "textarea" },
        ],
        "Save agreement version",
        async function (form) {
          await approvalApi("/cases/" + approvalCase.id + "/agreement", {
            method: "POST",
            body: JSON.stringify({
              version: fieldValue(form, "version"),
              status: fieldValue(form, "status") || "accepted",
              accepted_at: fieldValue(form, "accepted_at") || undefined,
              evidence_document_id: fieldValue(form, "evidence_document_id") || undefined,
              notes: fieldValue(form, "notes") || undefined,
            }),
          });
        }
      );

      complianceForm(
        "W-9 workflow",
        "Metadata only. Raw SSN/TIN is rejected. AMICOR does not store tax identifiers.",
        [
          { label: "Workflow status", name: "status", type: "select", options: ["requested", "pending", "completed", "externally_verified"], value: app.w9_workflow_status || "requested" },
          { label: "External provider (future)", name: "external_provider" },
          { label: "External reference token", name: "external_reference" },
          { label: "Notes", name: "notes", type: "textarea" },
        ],
        "Save W-9 workflow",
        async function (form) {
          await approvalApi("/cases/" + approvalCase.id + "/w9-workflow", {
            method: "POST",
            body: JSON.stringify({
              status: fieldValue(form, "status") || "pending",
              external_provider: fieldValue(form, "external_provider") || undefined,
              external_reference: fieldValue(form, "external_reference") || undefined,
              notes: fieldValue(form, "notes") || undefined,
              metadata: {},
            }),
          });
        }
      );

      const trainingBox = document.createElement("section");
      trainingBox.className = "owner-card";
      trainingBox.innerHTML = "<h3>Training evidence</h3><p class='meta'>Do not invent completion. Record only evidence staff actually have.</p>";
      (approvalCase.training_modules || []).forEach(function (module) {
        const row = document.createElement("div");
        row.className = "review-row";
        row.innerHTML = "<strong>" + (module.label || module.module_key) + "</strong>"
          + "<div class='meta'>status " + (module.status || "assigned")
          + " · version " + (module.module_version || "—")
          + " · assigned " + (module.assigned_at || "—")
          + " · completed " + (module.completed_at || "—")
          + " · expires " + (module.expires_at || "—")
          + " · evidence " + (module.evidence_ref || "—") + "</div>";
        const form = document.createElement("div");
        form.className = "review-form";
        appendSelect(form, "Status", "status", ["assigned", "in_progress", "completed", "failed", "expired", "retraining_required"], module.status || "assigned");
        appendField(form, "Version", "module_version", "text", module.module_version || "");
        appendField(form, "Assigned date", "assigned_at", "date", (module.assigned_at || "").slice(0, 10));
        appendField(form, "Completion date", "completed_at", "date", (module.completed_at || "").slice(0, 10));
        appendField(form, "Expiration / retraining", "expires_at", "date", module.expires_at || "");
        appendField(form, "Evidence / certificate reference", "evidence_ref", "text", module.evidence_ref || "");
        row.appendChild(form);
        const toolbar = document.createElement("div");
        toolbar.className = "toolbar";
        toolbar.appendChild(actionButton("Save training", async function () {
          try {
            const body = {
              status: fieldValue(form, "status"),
              module_version: fieldValue(form, "module_version") || undefined,
              assigned_at: fieldValue(form, "assigned_at") || undefined,
              completed_at: fieldValue(form, "completed_at") || undefined,
              expires_at: fieldValue(form, "expires_at") || undefined,
              evidence_ref: fieldValue(form, "evidence_ref") || undefined,
            };
            await approvalApi("/cases/" + approvalCase.id + "/training/" + module.module_key, {
              method: "PATCH",
              body: JSON.stringify(body),
            });
            showBanner("Training recorded.", true);
            await loadDetail(selectedId);
          } catch (err) { showBanner(err.message, false); }
        }));
        row.appendChild(toolbar);
        trainingBox.appendChild(row);
      });
      if (!(approvalCase.training_modules || []).length) {
        trainingBox.innerHTML += "<p class='meta'>No training modules assigned yet. Run AI review after the application exists.</p>";
      }
      detailEl.appendChild(trainingBox);

      const currentVehicle = (approvalCase.vehicles || [])[0] || {};
      complianceForm(
        "Vehicle / real plate (test data only)",
        "Do not use ONBD- placeholders. Linking a test vehicle does not activate live dispatch.",
        [
          { label: "Make", name: "make", value: currentVehicle.make || app.vehicle_make || "" },
          { label: "Model", name: "model", value: currentVehicle.model || app.vehicle_model || "" },
          { label: "Year", name: "year", type: "number", value: currentVehicle.year || app.vehicle_year || "" },
          { label: "Plate", name: "license_plate", value: currentVehicle.license_plate || app.vehicle_license_plate || "" },
          { label: "Registration expiration", name: "registration_expiration", type: "date", value: currentVehicle.registration_expiration || "" },
          { label: "Inspection status", name: "inspection_status", value: currentVehicle.inspection_status || "" },
          { label: "Inspection expiration", name: "inspection_expiration", type: "date", value: currentVehicle.inspection_expiration || "" },
          { label: "Insurance association", name: "insurance_association_ref", value: currentVehicle.insurance_association_ref || "" },
          { label: "Insurance expiration", name: "insurance_expiration", type: "date", value: currentVehicle.insurance_expiration || "" },
          { label: "Vehicle eligibility", name: "eligibility_status", type: "select", options: ["PENDING", "REVIEWED", "ELIGIBLE_NOT_ACTIVE", "BLOCKED", "EXPIRED"], value: currentVehicle.eligibility_status || "PENDING" },
        ],
        "Save test vehicle",
        async function (form) {
          const yearRaw = fieldValue(form, "year");
          await approvalApi("/cases/" + approvalCase.id + "/vehicle", {
            method: "POST",
            body: JSON.stringify({
              make: fieldValue(form, "make") || undefined,
              model: fieldValue(form, "model") || undefined,
              year: yearRaw ? Number(yearRaw) : undefined,
              license_plate: fieldValue(form, "license_plate") || undefined,
              registration_expiration: fieldValue(form, "registration_expiration") || undefined,
              inspection_status: fieldValue(form, "inspection_status") || undefined,
              inspection_expiration: fieldValue(form, "inspection_expiration") || undefined,
              insurance_association_ref: fieldValue(form, "insurance_association_ref") || undefined,
              insurance_expiration: fieldValue(form, "insurance_expiration") || undefined,
              eligibility_status: fieldValue(form, "eligibility_status") || "PENDING",
            }),
          });
        }
      );

      const notesBox = document.createElement("section");
      notesBox.className = "owner-card";
      notesBox.innerHTML = "<h3>Compliance notes + external verification</h3>";
      try {
        const notes = await api("/applications/" + id + "/notes");
        (notes || []).forEach(function (note) {
          const row = document.createElement("div");
          row.className = "meta";
          row.textContent = (note.created_at || "") + " · " + (note.category || "note") + " · " + (note.author_user_id || "") + " · " + (note.note_text || "");
          notesBox.appendChild(row);
        });
      } catch (err) {
        notesBox.innerHTML += "<p class='meta'>Notes unavailable: " + (err.message || err) + "</p>";
      }
      const noteForm = document.createElement("div");
      noteForm.className = "review-form";
      appendField(noteForm, "Verification category", "category", "text", "general");
      appendField(noteForm, "Note", "note_text", "textarea");
      notesBox.appendChild(noteForm);
      const noteToolbar = document.createElement("div");
      noteToolbar.className = "toolbar";
      noteToolbar.appendChild(actionButton("Add note", async function () {
        try {
          await api("/applications/" + id + "/notes", {
            method: "POST",
            body: JSON.stringify({
              category: fieldValue(noteForm, "category") || undefined,
              note_text: fieldValue(noteForm, "note_text"),
            }),
          });
          showBanner("Note recorded.", true);
          await loadDetail(selectedId);
        } catch (err) { showBanner(err.message, false); }
      }));
      notesBox.appendChild(noteToolbar);

      const extForm = document.createElement("div");
      extForm.className = "review-form";
      appendSelect(extForm, "Requirement", "requirement_key", ["mvr", "vehicle_insurance", "vehicle_registration", "vehicle_inspection", "drivers_license", "background_study", "fingerprint"], "vehicle_insurance");
      appendSelect(extForm, "Status", "status", ["PENDING_EXTERNAL", "VERIFIED", "CLEARED", "FAILED", "DISQUALIFIED", "EXPIRED", "MANUAL_REVIEW"], "PENDING_EXTERNAL");
      appendField(extForm, "Source", "provider_key");
      appendField(extForm, "Evidence / reference", "evidence_source");
      appendField(extForm, "Reference / case number", "provider_reference_id");
      appendField(extForm, "Review date", "verification_date", "date");
      appendField(extForm, "Expiration / recheck", "expiration_date", "date");
      appendField(extForm, "Notes", "notes", "textarea");
      notesBox.appendChild(extForm);
      const extToolbar = document.createElement("div");
      extToolbar.className = "toolbar";
      extToolbar.appendChild(actionButton("Record external verification", async function () {
        try {
          const key = fieldValue(extForm, "requirement_key") || "mvr";
          await approvalApi("/cases/" + approvalCase.id + "/external/" + key + "/record", {
            method: "POST",
            body: JSON.stringify({
              status: fieldValue(extForm, "status"),
              provider_key: fieldValue(extForm, "provider_key") || undefined,
              evidence_source: fieldValue(extForm, "evidence_source") || undefined,
              provider_reference_id: fieldValue(extForm, "provider_reference_id") || undefined,
              verification_date: fieldValue(extForm, "verification_date") || undefined,
              expiration_date: fieldValue(extForm, "expiration_date") || undefined,
              notes: fieldValue(extForm, "notes") || undefined,
              actor_type: "USER",
            }),
          });
          showBanner("External verification recorded.", true);
          await loadDetail(selectedId);
        } catch (err) { showBanner(err.message, false); }
      }));
      notesBox.appendChild(extToolbar);
      detailEl.appendChild(notesBox);
    }

    const legacy = document.createElement("details");
    legacy.innerHTML = "<summary class='meta'>Legacy Platform Ops tools (secondary)</summary>";
    const toolbar = document.createElement("div");
    toolbar.className = "toolbar";
    toolbar.appendChild(actionButton("Move to under review", () => transition("under_review"), true));
    toolbar.appendChild(actionButton("Documents pending", () => transition("documents_pending"), true));
    toolbar.appendChild(actionButton("Platform Ops Approve", () => decision("/approve"), true));
    const locked = document.createElement("p");
    locked.className = "meta";
    locked.textContent = "Activate is locked server-side until the Approval Engine is APPROVED/ACTIVE with no blocking requirements. Onboarding drivers cannot become live-dispatch eligible in this phase.";
    legacy.appendChild(toolbar);
    legacy.appendChild(locked);
    detailEl.appendChild(legacy);
  }

  async function transition(toStatus) {
    try {
      const confirmAction = ["rejected", "suspended", "approved", "activated"].includes(toStatus);
      await api(`/applications/${selectedId}/status`, {
        method: "POST",
        body: JSON.stringify({ to_status: toStatus, confirm: confirmAction, reason: "admin workspace" }),
      });
      showBanner(`Moved to ${toStatus}`, true);
      await loadDetail(selectedId);
    } catch (err) {
      showBanner(err.message, false);
    }
  }

  async function decision(path) {
    try {
      const reason = path.includes("reject") ? prompt("Rejection reason") : "";
      if (path.includes("reject") && !reason) return;
      const result = await api(`/applications/${selectedId}${path}`, {
        method: "POST",
        body: JSON.stringify({ confirm: true, reason: reason || undefined }),
      });
      showBanner(path.includes("activate") ? `Activated driver ${result.driver_id}` : "Updated", true);
      await loadDetail(selectedId);
    } catch (err) {
      showBanner(err.message, false);
    }
  }

  function renderDriver001Panel(payload) {
    const panel = document.getElementById("driver-001-panel");
    if (!panel) return;
    const caseInfo = payload.case || {};
    const walk = payload.walkthrough || {};
    const steps = walk.ordered_steps || [];
    const stepHtml = steps.map(function (step) {
      const focus = step.is_current_focus ? " <strong>(current focus)</strong>" : "";
      const c = step.classifications || {};
      return "<details " + (step.is_current_focus ? "open" : "") + ">"
        + "<summary>Step " + step.order + ": " + step.label
        + " · " + (step.live_traffic_light || "red").toUpperCase()
        + " · " + (step.live_status || "NOT_STARTED") + focus + "</summary>"
        + "<div class='meta'><em>Driver enters:</em> " + ((c.driver_enters || []).join("; ") || "—") + "</div>"
        + "<div class='meta'><em>Driver uploads:</em> " + ((c.driver_uploads || []).join("; ") || "—") + "</div>"
        + "<div class='meta'><em>AI auto-review:</em> " + ((c.ai_auto_review || []).join("; ") || "—") + "</div>"
        + "<div class='meta'><em>External verification:</em> " + ((c.external_verification || []).join("; ") || "—") + "</div>"
        + "<div class='meta'><em>Owner/admin approval:</em> " + ((c.owner_admin_approval || []).join("; ") || "—") + "</div>"
        + "</details>";
    }).join("");
    panel.innerHTML = ""
      + "<h3>Driver #001 · BASE ambulatory validation</h3>"
      + "<div class='meta'>Badge: " + (payload.driver_badge || "DRV-001")
      + " · Case: " + (caseInfo.case_id || caseInfo.id || "not prepared")
      + " · Workflow: " + (caseInfo.workflow_status || "—")
      + " · Readiness: " + (caseInfo.readiness_percentage != null ? caseInfo.readiness_percentage : "—") + "%</div>"
      + "<div class='meta'>App: " + ((payload.platform_ops_application && payload.platform_ops_application.id) || "—")
      + " · Status: " + ((payload.platform_ops_application && payload.platform_ops_application.status) || "—")
      + " · Activated: " + (payload.activated === true ? "YES" : "NO")
      + " · Fabricated verifications: " + (payload.fabricated_verifications === true ? "YES" : "NO")
      + " · Dispatch gate: " + (payload.dispatch_gate_enabled === true ? "ON" : "OFF") + "</div>"
      + "<p>" + (caseInfo.ai_summary || walk.ai_summary || "") + "</p>"
      + "<p class='meta'>Next action: " + (caseInfo.next_required_action || walk.next_required_action || "—") + "</p>"
      + "<h4>Ordered BASE requirements</h4>" + (stepHtml || "<p class='meta'>Prepare Driver #001 to load live steps.</p>")
      + "<h4>Kept separate from BASE</h4>"
      + "<p class='meta'>Background study, fingerprinting, STS training, MHCP credentialing — not required for BASE activation.</p>"
      + (payload.readiness_view ? "<h4>Readiness view</h4>" + ((payload.readiness_view.items || []).map(function (item) {
        return "<div class='meta'>" + readinessPill(item.state) + " " + item.label + " · " + (item.status || "—") + "</div>";
      }).join("")) : "")
      + (payload.compliance_summary ? renderComplianceBoard(payload.compliance_summary) : "");
  }

  function renderComplianceBoard(summary) {
    const items = summary.items || [];
    const rows = items.map(function (item) {
      return "<div class='meta'><strong>" + item.light + "</strong> "
        + item.label + " · " + item.status
        + (item.missing && item.missing.length ? " · missing: " + item.missing.join(", ") : "")
        + (item.expiration ? " · expires " + item.expiration : "")
        + "</div>";
    }).join("");
    return "<h4>Master compliance summary</h4>"
      + "<div class='meta'>Overall: " + (summary.overall_status || "—")
      + " · Progress: " + (summary.progress_percent != null ? summary.progress_percent : "—") + "%"
      + " · Online eligible: " + (summary.online_eligible ? "YES" : "NO") + "</div>"
      + "<div class='meta'>Blocked because: "
      + ((summary.blocked_from_online_reasons || []).join("; ") || "—") + "</div>"
      + rows;
  }

  async function loadDriver001() {
    try {
      const status = await approvalApi("/driver-001");
      try {
        status.compliance_summary = await approvalApi("/driver-001/compliance-summary");
      } catch (_) {}
      renderDriver001Panel(status);
    } catch (err) {
      const panel = document.getElementById("driver-001-panel");
      if (panel) panel.innerHTML = "<p class='meta'>Driver #001 panel unavailable: " + (err.message || err) + "</p>";
    }
  }

  async function prepareDriver001() {
    try {
      const email = prompt("Optional email for Driver #001 draft (driver will complete the rest)", "") || null;
      const phone = prompt("Optional mobile phone for Driver #001 draft", "") || null;
      const payload = await approvalApi("/driver-001/prepare", {
        method: "POST",
        body: JSON.stringify({
          legal_first_name: "Driver",
          legal_last_name: "001",
          email: email,
          mobile_phone: phone,
          reuse_existing: true,
        }),
      });
      renderDriver001Panel(payload);
      if (payload.platform_ops_application && payload.platform_ops_application.applicant_access_token) {
        showBanner(
          "Driver #001 prepared. Applicant token available once — use /platform-ops/driver-apply with that application. No verifications fabricated; not activated.",
          true
        );
        console.info("Driver #001 applicant_access_token", payload.platform_ops_application.applicant_access_token);
      } else {
        showBanner("Driver #001 validation record refreshed. AI next actions updated; nothing fabricated or activated.", true);
      }
      if (payload.platform_ops_application && payload.platform_ops_application.id) {
        selectedId = payload.platform_ops_application.id;
        await loadDetail(selectedId);
      } else {
        await loadList();
      }
    } catch (err) {
      showBanner(err.message, false);
    }
  }

  document.getElementById("refresh-list").addEventListener("click", () => {
    refreshWorkspace({ loadingMessage: "Refreshing applications…" }).catch(function (e) {
      showBanner(e.message || String(e), false);
    });
  });
  if (loginForm) {
    loginForm.addEventListener("submit", function (event) {
      event.preventDefault();
      const email = document.getElementById("admin-email").value;
      const password = document.getElementById("admin-password").value;
      sessionLogin(email, password).then(function () {
        document.getElementById("admin-password").value = "";
        return refreshWorkspace({ loadingMessage: "Signed in. Loading applications…" });
      }).catch(function (err) {
        showBanner(err.message || String(err), false);
      });
    });
  }
  if (signOutBtn) {
    signOutBtn.addEventListener("click", function () {
      sessionLogout().then(function () {
        listEl.innerHTML = "<p class='meta'>Sign in required to load applications.</p>";
        detailEl.innerHTML = "<p class='meta'>Select an application to review.</p>";
        showBanner("Signed out.", true);
      });
    });
  }
  const prepBtn = document.getElementById("prepare-driver-001");
  if (prepBtn) prepBtn.addEventListener("click", () => prepareDriver001());
  fetchJson("/api/auth/me", { method: "GET" }).then(function (result) {
    if (result.response.ok) {
      setSignedIn(true);
      return refreshWorkspace({ loadingMessage: "Loading applications…" });
    }
    setSignedIn(false);
    listEl.innerHTML = "<p class='meta'>Sign in required to load applications.</p>";
    showBanner("Sign in with the admin form. The session is stored in an HttpOnly cookie.", false);
  }).catch(function () {
    setSignedIn(false);
    listEl.innerHTML = "<p class='meta'>Sign in required to load applications.</p>";
  });
})();
