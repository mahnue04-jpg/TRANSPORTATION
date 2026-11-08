(function () {
  "use strict";
  const form = document.getElementById("operations-csv-form");
  const message = document.getElementById("operations-csv-result");
  if (!form || !message) return;
  form.addEventListener("submit", async function (event) {
    event.preventDefault();
    const file = document.getElementById("operations-csv-file").files[0];
    const button = form.querySelector('button[type="submit"]');
    if (!file) { message.textContent = "Choose a CSV file."; return; }
    if (file.size > 1000000) { message.textContent = "File must be no larger than 1 MB."; return; }
    const session = window.AmiCorSession;
    const headers = session && typeof session.getAuthHeaders === "function"
      ? session.getAuthHeaders() : {};
    if (!headers || !(headers.Authorization || headers.authorization)) {
      message.textContent = "Sign in as the AMICOR Work & Revenue owner first.";
      return;
    }
    button.disabled = true;
    message.textContent = "Processing CSV for owner review...";
    try {
      const response = await fetch("/api/nova/work/operations/csv-clean", {
        method: "POST",
        credentials: "same-origin",
        headers: Object.assign({}, headers, {
          "X-Nova-Owner-Action": "process-csv-for-owner-review",
          "X-Nova-File-Name": file.name,
          "Content-Type": "text/csv"
        }),
        body: file
      });
      if (!response.ok) {
        let detail = "Request failed (" + response.status + ").";
        try { const payload = await response.json(); detail = payload.detail || detail; } catch (_) {}
        message.textContent = detail;
        return;
      }
      const cleaned = await response.blob();
      const downloadUrl = URL.createObjectURL(cleaned);
      const anchor = document.createElement("a");
      anchor.href = downloadUrl;
      anchor.download = "nova-cleaned-review.csv";
      document.body.appendChild(anchor);
      anchor.click();
      anchor.remove();
      window.setTimeout(function () { URL.revokeObjectURL(downloadUrl); }, 10000);
      message.textContent = "Review required: " +
        (response.headers.get("X-Nova-Input-Rows") || "?") + " input rows, " +
        (response.headers.get("X-Nova-Output-Rows") || "?") +
        " cleaned rows. Downloaded for your inspection. No file was saved by the application.";
    } catch (_) {
      message.textContent = "Could not connect. Please check your sign-in and network.";
    } finally {
      button.disabled = false;
    }
  });
})();