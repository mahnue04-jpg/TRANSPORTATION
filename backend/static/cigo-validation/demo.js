(function () {
  var form = document.getElementById("intake");
  var result = document.getElementById("result");
  var fields = ["idea", "budget", "currency", "email", "follow_up", "consent"];

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
    result.innerHTML = '<div class="card ' + kind + '"><strong>' + title + '</strong><p>' + body + '</p></div>';
  }

  function table(rows, columns) {
    if (!rows.length) return "<p class=\"hint\">None yet.</p>";
    var head = "<tr>" + columns.map(function (col) { return "<th>" + col.label + "</th>"; }).join("") + "</tr>";
    var body = rows.map(function (row) {
      return "<tr>" + columns.map(function (col) {
        var value = row[col.key];
        if (value === null || value === undefined || value === "") value = "—";
        return "<td>" + String(value) + "</td>";
      }).join("") + "</tr>";
    }).join("");
    return "<table>" + head + body + "</table>";
  }

  function load() {
    return Promise.all([
      fetch("/dev/cigo-validation/records").then(function (r) { return r.json(); }),
      fetch("/dev/cigo-validation/alerts").then(function (r) { return r.json(); }),
      fetch("/dev/cigo-validation/failures").then(function (r) { return r.json(); })
    ]).then(function (parts) {
      document.getElementById("records").innerHTML = table(parts[0].records || [], [
        { key: "id", label: "ID" },
        { key: "idea", label: "Idea" },
        { key: "budget", label: "Budget" },
        { key: "currency", label: "Currency" },
        { key: "email", label: "Email" },
        { key: "follow_up", label: "Follow-up" },
        { key: "follow_up_status", label: "Follow-up status" },
        { key: "source", label: "Source" }
      ]);
      document.getElementById("alerts").innerHTML = table(parts[1].alerts || [], [
        { key: "id", label: "Alert" },
        { key: "record_id", label: "Record" },
        { key: "kind", label: "Kind" },
        { key: "status", label: "Status" },
        { key: "sent", label: "Sent" }
      ]);
      document.getElementById("failures").innerHTML = table(parts[2].failures || [], [
        { key: "id", label: "Failure" },
        { key: "kind", label: "Kind" },
        { key: "at", label: "When" }
      ]);
    });
  }

  form.addEventListener("submit", function (event) {
    event.preventDefault();
    clearErrors();
    var data = new FormData(form);
    var follow = data.get("follow_up");
    var body = {
      idea: String(data.get("idea") || ""),
      budget: String(data.get("budget") || "").trim(),
      currency: String(data.get("currency") || ""),
      email: String(data.get("email") || "").trim(),
      follow_up: follow,
      consent: document.getElementById("consent").checked
    };
    var headers = { "Content-Type": "application/json" };
    if (document.getElementById("force-failure").checked) headers["X-Cigo-Force-Failure"] = "store";
    fetch("/dev/cigo-validation/submissions", { method: "POST", headers: headers, body: JSON.stringify(body) })
      .then(function (response) { return response.json().then(function (payload) { return { response: response, payload: payload }; }); })
      .then(function (out) {
        var payload = out.payload;
        if (payload.status === "created") {
          card("created", "Saved " + payload.record.id, "Mock record stored. Outbound sends: " + payload.outbound_sends + ".");
        } else if (payload.status === "duplicate") {
          card("duplicate", "Already saved as " + payload.record.id, "The same idea and email were kept as one record. Outbound sends: " + payload.outbound_sends + ".");
        } else if (payload.status === "failed") {
          card("failed", "Storage failure", (payload.failure.fields && payload.failure.fields.store) || "Nothing was saved.");
        } else {
          card("invalid", "Check the form", "The record was not saved.");
          showErrors(payload.failure && payload.failure.fields);
        }
        return load();
      })
      .catch(function () {
        card("failed", "Request failed", "The demo server did not accept the form.");
      });
  });

  document.getElementById("reset").addEventListener("click", function () {
    if (!window.confirm("Clear the demonstration records, notifications, and failures on this server?")) return;
    fetch("/dev/cigo-validation/reset", { method: "POST" }).then(load);
  });

  document.getElementById("seed").addEventListener("click", function () {
    fetch("/dev/cigo-validation/seed-fictional", { method: "POST" }).then(load);
  });

  load();
})();
