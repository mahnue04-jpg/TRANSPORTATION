(() => {
  "use strict";
  const button = document.getElementById("website-inquiries-live-check");
  const status = document.getElementById("website-inquiries-live-status");
  const list = document.getElementById("website-inquiries-live-list");
  if (!button || !status || !list) return;
  let version = 0;
  const token = () => localStorage.getItem("amicor_growth_token") || "";
  const clear = () => {
    version++;
    list.replaceChildren();
    status.textContent = "Sign in before checking. No live source configured.";
  };
  document.getElementById("sign-out")?.addEventListener("click", clear);
  document.getElementById("login-form")?.addEventListener("submit", clear);
  window.addEventListener("storage", event => {
    if (event.key === "amicor_growth_token" || event.key === null) clear();
  });
  button.addEventListener("click", async () => {
    const session = token();
    if (!session) { clear(); status.textContent = "Owner sign-in required."; return; }
    const current = ++version;
    list.replaceChildren();
    button.disabled = true;
    status.textContent = "Checking owner inquiry source...";
    try {
      const response = await fetch("/api/nova/growth-agent/website-inquiries/read-only", {
        method: "GET", cache: "no-store",
        headers: { Authorization: "Bearer " + session }
      });
      if (current !== version || session !== token()) return;
      if (response.status === 503) {
        status.textContent = "Not connected. Cloudflare inquiries are unavailable; this does not mean zero customer requests.";
        return;
      }
      if (response.status === 401 || response.status === 403 || response.status === 404) {
        status.textContent = "Owner access unavailable. Sign in with the correct account.";
        return;
      }
      if (!response.ok) throw new Error("Inquiry source could not be checked.");
      const data = await response.json();
      if (current !== version || session !== token()) return;
      if (data.status !== "ok" || data.read_only !== true ||
          !Array.isArray(data.inquiries) || !Number.isSafeInteger(data.count) ||
          data.count !== data.inquiries.length) {
        throw new Error("Inquiry source returned incomplete data.");
      }
      status.textContent = data.count === 0
        ? "Connected: no inquiries returned from the authorized source."
        : data.count + " inquiries returned for owner review. No messages sent.";
      for (const inquiry of data.inquiries) {
        const item = document.createElement("div");
        const heading = document.createElement("strong");
        heading.textContent = String(inquiry.company || "Customer inquiry");
        const detail = document.createElement("p");
        detail.textContent = [inquiry.product || "Service inquiry",
          inquiry.status || "needs_owner_review",
          inquiry.is_synthetic === true ? "TEST RECORD" : "UNVERIFIED CUSTOMER RECORD"].join(" · ");
        item.append(heading, detail);
        list.append(item);
      }
    } catch (error) {
      if (current === version && session === token()) {
        status.textContent = error.message;
        list.replaceChildren();
      }
    } finally { button.disabled = false; }
  });
})();