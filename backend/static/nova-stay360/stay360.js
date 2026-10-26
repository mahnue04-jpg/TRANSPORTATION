(function () {
  "use strict";

  var strings = {};
  var locale = window.localStorage.getItem("stay360.locale") || "en";

  function text(key) {
    return strings[key] || key;
  }

  function applyLocale() {
    document.documentElement.lang = locale === "en" ? "en" : locale;
    var nodes = document.querySelectorAll("[data-i18n]");
    for (var i = 0; i < nodes.length; i += 1) {
      var key = nodes[i].getAttribute("data-i18n");
      if (strings[key]) {
        nodes[i].textContent = strings[key];
      }
    }
  }

  function token() {
    return window.sessionStorage.getItem("stay360.token") || "";
  }

  function setStatus(message) {
    document.getElementById("session-status").textContent = message || "";
  }

  function clearNode(node) {
    while (node.firstChild) {
      node.removeChild(node.firstChild);
    }
  }

  function cell(row, value) {
    var item = document.createElement("td");
    item.textContent = value == null ? "" : String(value);
    row.appendChild(item);
  }

  function fillDefinition(target, pairs) {
    clearNode(target);
    pairs.forEach(function (pair) {
      var block = document.createElement("div");
      var term = document.createElement("dt");
      var detail = document.createElement("dd");
      term.textContent = pair[0];
      detail.textContent = pair[1] == null ? "" : String(pair[1]);
      block.appendChild(term);
      block.appendChild(detail);
      target.appendChild(block);
    });
  }

  function errorMessage(payload) {
    var detail = payload && payload.detail;
    var code = detail && detail.code;
    if (code === "reservation_not_found" || code === "guest_reservation_not_found" || code === "room_not_found") {
      return text("errors.not_found");
    }
    if (code === "role_not_permitted" || code === "tenant_not_enrolled" || code === "admin_required") {
      return text("errors.forbidden");
    }
    if (code === "not_eligible") {
      return text("errors.not_eligible");
    }
    return text("errors.generic");
  }

  function request(path, options) {
    var headers = { Accept: "application/json" };
    var bearer = token();
    if (bearer) {
      headers.Authorization = "Bearer " + bearer;
    }
    if (options && options.body) {
      headers["Content-Type"] = "application/json";
    }
    return fetch(path, {
      method: options && options.method ? options.method : "GET",
      headers: headers,
      body: options && options.body ? JSON.stringify(options.body) : undefined,
    }).then(function (response) {
      return response.json().then(function (payload) {
        if (!response.ok) {
          var error = new Error(errorMessage(payload));
          error.payload = payload;
          throw error;
        }
        return payload;
      });
    });
  }

  function renderCounts(dashboard) {
    document.getElementById("hotel-name").textContent = dashboard.hotel_name || "";
    document.getElementById("fixture-date").textContent = dashboard.fixture_date || "";
    var counts = dashboard.counts || {};
    fillDefinition(document.getElementById("counts"), [
      [text("table.reference"), counts.reservations],
      [text("nav.arrivals"), counts.arrivals_today],
      [text("readiness.ready"), counts.rooms_ready],
      [text("readiness.not_ready"), counts.rooms_not_ready],
      [text("table.eligibility"), counts.eligible_check_in],
      [text("nav.checkin"), counts.simulated_checked_in],
    ]);
  }

  function renderArrivals(rows) {
    var body = document.getElementById("arrivals");
    clearNode(body);
    var empty = document.getElementById("arrivals-empty");
    empty.hidden = rows.length > 0;
    rows.forEach(function (row) {
      var tr = document.createElement("tr");
      cell(tr, row.reservation_reference);
      cell(tr, row.guest_label);
      cell(tr, row.room_number);
      cell(tr, row.arrival_mode + " · " + row.arrival_status + " · " + row.eta_local);
      cell(tr, row.room_readiness);
      cell(tr, row.check_in_eligibility);
      body.appendChild(tr);
    });
  }

  function renderRooms(rows) {
    var body = document.getElementById("rooms");
    clearNode(body);
    rows.forEach(function (row) {
      var tr = document.createElement("tr");
      cell(tr, row.room_number);
      cell(tr, row.reservation_reference);
      cell(tr, row.guest_label);
      cell(tr, row.housekeeping_status + " · " + row.room_readiness);
      body.appendChild(tr);
    });
  }

  function loadDashboard() {
    return request("/api/nova/stay360/dashboard").then(function (dashboard) {
      renderCounts(dashboard);
      renderArrivals(dashboard.arrivals || []);
      renderRooms(dashboard.rooms || []);
      setStatus(text("nav.dashboard"));
    }).catch(function (error) {
      setStatus(error.message);
    });
  }

  function loadLocale(next) {
    locale = next;
    window.localStorage.setItem("stay360.locale", locale);
    return request("/api/nova/stay360/locales/" + encodeURIComponent(locale)).then(function (payload) {
      strings = payload.strings || {};
      applyLocale();
    }).catch(function () {
      applyLocale();
    });
  }

  document.getElementById("locale").value = locale;
  document.getElementById("locale").addEventListener("change", function (event) {
    loadLocale(event.target.value);
  });
  document.getElementById("load-dashboard").addEventListener("click", function () {
    window.sessionStorage.setItem("stay360.token", document.getElementById("token").value.trim());
    loadDashboard();
  });
  document.getElementById("clear-token").addEventListener("click", function () {
    window.sessionStorage.removeItem("stay360.token");
    document.getElementById("token").value = "";
    setStatus("");
  });
  document.getElementById("refresh-arrivals").addEventListener("click", function () {
    request("/api/nova/stay360/arrivals/refresh", { method: "POST", body: {} })
      .then(function () { return loadDashboard(); })
      .catch(function (error) { setStatus(error.message); });
  });
  document.getElementById("lookup-form").addEventListener("submit", function (event) {
    event.preventDefault();
    var reference = document.getElementById("lookup-reference").value.trim();
    request("/api/nova/stay360/reservations/" + encodeURIComponent(reference))
      .then(function (row) {
        fillDefinition(document.getElementById("lookup-result"), [
          [text("table.reference"), row.reservation_reference],
          [text("table.guest"), row.guest_label],
          [text("table.room"), row.room_number],
          [text("table.arrival"), row.arrival_detail],
          [text("table.readiness"), row.room_readiness],
          [text("table.eligibility"), row.check_in_eligibility],
        ]);
      })
      .catch(function (error) {
        fillDefinition(document.getElementById("lookup-result"), [[text("errors.generic"), error.message]]);
      });
  });
  document.getElementById("housekeeping-form").addEventListener("submit", function (event) {
    event.preventDefault();
    var room = document.getElementById("room-number").value.trim();
    var status = document.getElementById("housekeeping-status").value;
    request("/api/nova/stay360/rooms/" + encodeURIComponent(room) + "/housekeeping", {
      method: "POST",
      body: { status: status },
    }).then(function () {
      return loadDashboard();
    }).catch(function (error) {
      setStatus(error.message);
    });
  });
  document.getElementById("checkin-form").addEventListener("submit", function (event) {
    event.preventDefault();
    var reference = document.getElementById("checkin-reference").value.trim();
    request("/api/nova/stay360/reservations/" + encodeURIComponent(reference) + "/mobile-check-in", {
      method: "POST",
      body: {},
    }).then(function (result) {
      fillDefinition(document.getElementById("checkin-result"), [
        [text("table.reference"), result.reservation_reference],
        [text("nav.checkin"), result.check_in_status],
        [text("checkin.no_door_access"), result.door_access],
        [text("checkin.no_payment"), String(result.payment_captured)],
      ]);
    }).catch(function (error) {
      var denied = error.payload && error.payload.detail && error.payload.detail.result;
      fillDefinition(document.getElementById("checkin-result"), [
        [text("errors.not_eligible"), error.message],
        [text("checkin.no_door_access"), denied ? denied.door_access : "not_issued"],
        [text("checkin.no_payment"), denied ? String(denied.payment_captured) : "false"],
      ]);
    });
  });

  loadLocale(locale);
})();
