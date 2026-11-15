"use strict";
(function () {
  var button = document.getElementById("growth-website-inquiries-refresh");
  var output = document.getElementById("growth-website-inquiries-result");
  if (!button || !output) return;
  var generation = 0;
  function message(value) { output.textContent = value; }
  button.addEventListener("click", async function () {
    var current = window.AmiCorSession || null;
    var token = current && current.getAccessToken && current.getAccessToken();
    if (!token) { message("Sign in as an AMICOR administrator to check website inquiries."); return; }
    var thisRequest = ++generation;
    var headers = current.getAuthHeaders
      ? current.getAuthHeaders() : { Authorization: "Bearer " + token };
    button.disabled = true;
    message("Checking the website inquiry source...");
    try {
      var response = await fetch("/api/nova/growth-agent/website-inquiries", {
        method: "GET", headers: headers, credentials: "same-origin", cache: "no-store"
      });
      if (response.status === 401) throw new Error("Session expired. Sign in again.");
      if (response.status === 403) throw new Error("Access denied for this account.");
      if (response.status === 404) throw new Error("Growth Agent API is disabled here.");
      if (!response.ok) throw new Error("Website inquiries could not be verified.");
      var data = await response.json();
      if (thisRequest !== generation ||
          !window.AmiCorSession ||
          window.AmiCorSession.getAccessToken() !== token) {
        message("Session changed. No inquiries displayed.");
        return;
      }
      if (!data || data.state === "unavailable") {
        message("Website inquiries: not connected. This is not a count of zero customers.");
        return;
      }
      if (data.state === "stale") {
        message("Website inquiries: source incomplete or stale. No count shown.");
        return;
      }
      if (data.state !== "available" || data.complete !== true ||
          !Array.isArray(data.inquiries) || data.inquiries.length > 100 ||
          data.inquiries.some(function (row) {
            return !row || row.source_system !== "cloudflare_amicor_leads" ||
              typeof row.source_key !== "string" || !row.source_key.startsWith("lead:");
          })) {
        throw new Error("Unexpected website inquiry response. No count shown.");
      }
      var synthetic = data.inquiries.filter(function (row) { return row.is_synthetic === true; }).length;
      message("Website inquiry snapshot: " + data.inquiries.length +
        " records (" + synthetic + " synthetic).\n" +
        "This is a source snapshot, not CRM contacts, completed jobs, or paid customers.\n" +
        "No messages sent and no records imported.");
    } catch (error) {
      message("Website inquiries unavailable for this review. " +
        (error && error.message || "Connection failed.") + "\nNo actions were taken.");
    } finally {
      button.disabled = false;
    }
  });
})();
