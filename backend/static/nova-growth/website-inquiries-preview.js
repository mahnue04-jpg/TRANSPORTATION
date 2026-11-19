(() => {
  "use strict";
  const button = document.getElementById("website-inquiries-preview-load");
  const status = document.getElementById("website-inquiries-preview-status");
  const list = document.getElementById("website-inquiries-preview-list");
  if (!button || !status || !list) return;
  let requestVersion = 0;
  const token = () => localStorage.getItem("amicor_growth_token") || "";
  const clear = () => {
    requestVersion++;
    list.replaceChildren();
    status.textContent = "Sign in before loading. Not live customer information.";
  };
  const text = (tag, value) => {
    const node = document.createElement(tag);
    node.textContent = String(value);
    return node;
  };
  document.getElementById("sign-out")?.addEventListener("click", clear);
  document.getElementById("login-form")?.addEventListener("submit", clear);
  window.addEventListener("storage", event => {
    if (event.key === "amicor_growth_token" || event.key === null) clear();
  });
  button.addEventListener("click", async () => {
    const session = token();
    if (!session) { clear(); status.textContent = "Owner sign-in required."; return; }
    const version = ++requestVersion;
    button.disabled = true;
    list.replaceChildren();
    status.textContent = "Loading synthetic preview...";
    try {
      const response = await fetch("/api/nova/growth-agent/website-inquiries/preview", {
        method: "GET", cache: "no-store", headers: { Authorization: "Bearer " + session }
      });
      if (!response.ok) throw new Error(response.status === 403 ? "Access denied." :
        response.status === 401 ? "Sign in again." : "Synthetic preview unavailable.");
      const data = await response.json();
      if (version !== requestVersion || session !== token()) return;
      if (data.status !== "synthetic_preview" || data.production_kv_connected !== false ||
          !Array.isArray(data.inquiries)) {
        status.textContent = "Synthetic preview unavailable. Live inquiries were not queried.";
        return;
      }
      status.textContent = "Synthetic example only — not live leads or revenue.";
      for (const inquiry of data.inquiries) {
        if (inquiry.is_synthetic !== true) continue;
        const item = document.createElement("div");
        item.append(text("strong", inquiry.company || "Fictional business"),
          text("p", [inquiry.product || "Other", inquiry.status || "Needs review", "SYNTHETIC"].join(" · ")));
        list.append(item);
      }
    } catch (error) {
      if (version === requestVersion && session === token()) {
        status.textContent = error.message;
        list.replaceChildren();
      }
    } finally {
      button.disabled = false;
    }
  });
})();
