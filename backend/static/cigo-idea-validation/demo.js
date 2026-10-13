(function () {
  var form = document.getElementById("worksheet");
  var result = document.getElementById("result-card");
  var fields = ["consumer", "job", "idea", "assumption", "evidence", "evidence_is_fictional", "result", "consent"];
  var example = null;

  function text(value) {
    return String(value == null ? "" : value)
      .replace(/&/g, "&amp;")
      .replace(/</g, "&lt;")
      .replace(/>/g, "&gt;");
  }

  function clearErrors() {
    fields.forEach(function (name) {
      var node = document.getElementById("error-" + name);
      if (node) node.textContent = "";
    });
  }

  function showErrors(errors) {
    clearErrors();
    Object.keys(errors || {}).forEach(function (name) {
      var node = document.getElementById("error-" + name);
      if (node) node.textContent = errors[name];
    });
  }

  function card(kind, title, body) {
    result.innerHTML = '<div class="card ' + kind + '"><strong>' + text(title) + '</strong><p>' + text(body) + '</p></div>';
  }

  function table(rows) {
    var columns = [
      { key: "id", label: "ID" },
      { key: "consumer", label: "Consumer" },
      { key: "idea", label: "Idea" },
      { key: "result", label: "Result" },
      { key: "status", label: "Status" }
    ];
    if (!rows.length) return "<p class=\"hint\">None yet.</p>";
    var head = "<tr>" + columns.map(function (col) { return "<th>" + col.label + "</th>"; }).join("") + "</tr>";
    var body = rows.map(function (row) {
      return "<tr>" + columns.map(function (col) {
        return "<td>" + text(row[col.key] || "—") + "</td>";
      }).join("") + "</tr>";
    }).join("");
    return "<table>" + head + body + "</table>";
  }

  function fill(data) {
    ["consumer", "job", "idea", "assumption", "evidence"].forEach(function (name) {
      document.getElementById(name).value = data[name] || "";
    });
    document.getElementById("result").value = data.result || "";
    document.getElementById("evidence-fictional").checked = data.evidence_is_fictional === true;
    document.getElementById("consent").checked = false;
  }

  function load() {
    return Promise.all([
      fetch("/dev/cigo-idea-validation/evidence").then(function (r) { return r.json(); }),
      fetch("/dev/cigo-idea-validation/worksheets").then(function (r) { return r.json(); })
    ]).then(function (parts) {
      var evidence = parts[0];
      example = evidence.example || null;
      document.getElementById("readiness").textContent = evidence.assessment_ready
        ? "Assessment status flag was unexpectedly true."
        : "Assessment status: not assessment-ready. No video is rendered here.";
      document.getElementById("script").textContent = (evidence.script && evidence.script.text) || "";
      document.getElementById("script-meta").textContent = evidence.script
        ? evidence.script.id + " · " + evidence.script.word_count + " words · rendered " + evidence.script.rendered
        : "";
      document.getElementById("workflow").innerHTML = (evidence.workflow || []).map(function (step) {
        return "<li>" + text(step.title) + "</li>";
      }).join("");
      document.getElementById("records").innerHTML = table(parts[1].records || []);
    });
  }

  document.getElementById("load-example").addEventListener("click", function () {
    if (example) fill(example);
  });

  form.addEventListener("submit", function (event) {
    event.preventDefault();
    clearErrors();
    var data = new FormData(form);
    var body = {
      consumer: String(data.get("consumer") || ""),
      job: String(data.get("job") || ""),
      idea: String(data.get("idea") || ""),
      assumption: String(data.get("assumption") || ""),
      evidence: String(data.get("evidence") || ""),
      evidence_is_fictional: document.getElementById("evidence-fictional").checked,
      result: String(data.get("result") || ""),
      consent: document.getElementById("consent").checked
    };
    var headers = { "Content-Type": "application/json" };
    if (document.getElementById("force-failure").checked) headers["X-Cigo-Force-Failure"] = "store";
    fetch("/dev/cigo-idea-validation/worksheets", { method: "POST", headers: headers, body: JSON.stringify(body) })
      .then(function (response) { return response.json().then(function (payload) { return { payload: payload }; }); })
      .then(function (out) {
        var payload = out.payload;
        if (payload.status === "created") {
          card("created", "Saved " + payload.record.id, "Fictional worksheet stored. Outbound sends: " + payload.outbound_sends + ".");
        } else if (payload.status === "duplicate") {
          card("duplicate", "Already saved as " + payload.record.id, "The same idea and consumer were kept as one worksheet. Outbound sends: " + payload.outbound_sends + ".");
        } else if (payload.status === "failed") {
          card("failed", "Storage failure", (payload.failure.fields && payload.failure.fields.store) || "Nothing was saved.");
        } else {
          card("invalid", "Check the form", "The worksheet was not saved.");
          showErrors(payload.failure && payload.failure.fields);
        }
        return load();
      })
      .catch(function () {
        card("failed", "Request failed", "The demo server did not accept the form.");
      });
  });

  document.getElementById("reset").addEventListener("click", function () {
    if (!window.confirm("Clear the fictional worksheets on this server?")) return;
    fetch("/dev/cigo-idea-validation/reset", { method: "POST" }).then(function () { return load(); });
  });

  load();
})();
