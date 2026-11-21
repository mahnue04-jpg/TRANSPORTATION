(function () {
  "use strict";
  const button = document.getElementById("reload");
  const status = document.getElementById("status");
  const list = document.getElementById("deliverables");
  const prefix = "/api/nova/work/operations/customer/deliveries";

  function authHeaders() {
    const session = window.AmiCorSession;
    return session && typeof session.getAuthHeaders === "function"
      ? (session.getAuthHeaders() || {}) : {};
  }

  async function errorText(response) {
    if (response.status === 401 || response.status === 403) {
      return "Please sign in to your verified customer account.";
    }
    if (response.status === 503) {
      return "Customer deliveries are not available yet. Contact AMICOR for assistance.";
    }
    return "Unable to load your deliverables (" + response.status + ").";
  }

  async function download(jobId, itemButton) {
    itemButton.disabled = true;
    status.textContent = "Verifying your customer download...";
    try {
      const headers = authHeaders();
      if (!(headers.Authorization || headers.authorization)) {
        throw new Error("Sign in to your verified customer account first.");
      }
      const response = await fetch(prefix + "/" + encodeURIComponent(jobId), {
        method: "GET", credentials: "same-origin", cache: "no-store", headers
      });
      if (!response.ok) throw new Error(await errorText(response));
      const blob = await response.blob();
      const objectUrl = URL.createObjectURL(blob);
      const link = document.createElement("a");
      link.href = objectUrl;
      link.download = "nova-completed-task.csv";
      document.body.appendChild(link);
      link.click();
      link.remove();
      window.setTimeout(function () { URL.revokeObjectURL(objectUrl); }, 10000);
      status.textContent = "Download prepared. AMICOR does not treat this as confirmed receipt.";
    } catch (error) {
      status.textContent = error.message || "Download unavailable.";
    } finally {
      itemButton.disabled = false;
    }
  }

  async function refresh() {
    const headers = authHeaders();
    list.replaceChildren();
    if (!(headers.Authorization || headers.authorization)) {
      status.textContent = "Please sign in to your verified customer account before checking files.";
      return;
    }
    button.disabled = true;
    status.textContent = "Checking approved deliverables...";
    try {
      const response = await fetch(prefix, {
        method: "GET", credentials: "same-origin", cache: "no-store", headers
      });
      if (!response.ok) throw new Error(await errorText(response));
      const payload = await response.json();
      const entries = Array.isArray(payload.deliveries) ? payload.deliveries : [];
      if (!entries.length) {
        status.textContent = "No downloadable files are available for this account.";
        return;
      }
      entries.forEach(function (entry) {
        // Never interpret server-supplied text as HTML, and only use the
        // authenticated API prefix as a destination.
        if (!entry || typeof entry.job_id !== "string"
            || !/^[a-zA-Z0-9_-]{1,64}$/.test(entry.job_id)) return;
        const item = document.createElement("div");
        item.className = "item";
        const heading = document.createElement("strong");
        heading.textContent = "Approved Nova Operations deliverable";
        const expiry = document.createElement("p");
        expiry.className = "hint";
        const date = new Date(entry.expires_at);
        expiry.textContent = Number.isFinite(date.getTime())
          ? "Download available until " + date.toLocaleString()
          : "Time-limited approved download";
        const action = document.createElement("button");
        action.type = "button";
        action.textContent = "Download approved CSV";
        action.addEventListener("click", function () { download(entry.job_id, action); });
        item.append(heading, expiry, action);
        list.appendChild(item);
      });
      status.textContent = list.children.length
        ? "Your approved files are listed below."
        : "No downloadable files are available for this account.";
    } catch (error) {
      status.textContent = error.message || "Unable to check deliverables.";
    } finally {
      button.disabled = false;
    }
  }

  button.addEventListener("click", refresh);
})();
