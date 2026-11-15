(() => {
  "use strict";
  const $ = (id) => document.getElementById(id);
  const token = () => localStorage.getItem("amicor_growth_token") || "";
  const status = $("acquisition-status");
  let version = 0;
  let reviews = new Map();
  const feedback = $("acquisition-feedback");
  function setFeedback(message, error = false) {
    feedback.textContent = message;
    feedback.className = error ? "error" : "hint";
  }

  function clear() {
    version++;
    reviews = new Map();
    setFeedback("");
    $("acquisition-plan").replaceChildren();
    $("acquisition-counts").textContent = "";
    $("acquisition-contact").replaceChildren();
    $("acquisition-review").hidden = true;
    status.textContent = "Sign in, then load the campaign.";
  }

  async function request(path, session, body) {
    if (!session) throw new Error("Sign in with an owner account first.");
    const response = await fetch("/api/nova/growth-agent" + path, {
      method: body ? "POST" : "GET",
      headers: { Authorization: `Bearer ${session}`, "Content-Type": "application/json" },
      ...(body ? { body: JSON.stringify(body) } : {}),
    });
    const data = await response.json();
    if (!response.ok) {
      const detail = data.detail;
      const error = new Error(typeof detail === "string" ? detail : detail?.message || "Campaign request failed.");
      error.blockers = detail?.details?.blockers || data?.blockers || [];
      throw error;
    }
    return data;
  }

  function text(tag, value) {
    const node = document.createElement(tag);
    node.textContent = value;
    return node;
  }

  function selectReview() {
    const review = reviews.get($("acquisition-contact").value) || {};
    $("acquisition-stage").value = review.stage || "new";
    for (const [id, key] of [["open", "has_open_inquiries"], ["permission", "authorized_list_use"],
      ["sending", "requires_external_sending"], ["sensitive", "requires_sensitive_data"]]) {
      $("acquisition-" + id).checked = review[key] === true;
    }
  }

  async function load(selectedContact = "") {
    const session = token();
    const current = ++version;
    status.textContent = "Loading owner campaign...";
    try {
      const [board, crm] = await Promise.all([
        request("/acquisition", session), request("/leads", session),
      ]);
      if (current !== version || session !== token()) return;
      const plan = board.plan;
      const host = $("acquisition-plan");
      host.replaceChildren(text("h3", plan.name), text("p", plan.audience),
        text("p", plan.offer), text("p", plan.entry_offer), text("p", plan.scope),
        text("h3", "Opening hook"), text("p", plan.hook), text("p", plan.call_to_action));
      for (const channel of plan.channels) host.append(text("p", `${channel.name}: ${channel.action}`));
      $("acquisition-counts").textContent = Object.entries(board.counts)
        .map(([stage, count]) => `${stage}: ${count}`).join(" · ")
        + ` | Reviewed: ${board.total_reviewed}. Unassigned: ${board.unassigned_contacts}. Payments not verified; clicks not connected.`;
      reviews = new Map(board.contacts.map((c) => [c.id, c.review]));
      const contacts = $("acquisition-contact");
      contacts.replaceChildren();
      for (const contact of crm.leads.filter((c) => !c.is_synthetic_demo)) {
        const option = text("option", `${contact.display_name || "Unnamed contact"}${contact.do_not_contact ? " — do not contact" : ""}`);
        option.value = contact.id;
        contacts.append(option);
      }
      if (selectedContact && Array.from(contacts.options).some((option) => option.value === selectedContact)) {
        contacts.value = selectedContact;
      }
      $("acquisition-review").hidden = !contacts.options.length;
      selectReview();
      status.textContent = contacts.options.length
        ? "Draft campaign loaded. Select a contact and review scope. Contact picker shows up to 200 recent CRM contacts; reviews show up to 100 latest records. Counts cover the full campaign."
        : "Draft campaign loaded. No non-synthetic CRM contacts available. No customers or revenue have been created by this screen.";
    } catch (error) {
      if (current !== version || session !== token()) return;
      clear();
      status.textContent = error.message;
    }
  }

  $("acquisition-load").addEventListener("click", load);
  $("acquisition-contact").addEventListener("change", selectReview);
  $("sign-out").addEventListener("click", clear);
  $("login-form").addEventListener("submit", clear);
  window.addEventListener("storage", (event) => {
    if (event.key === "amicor_growth_token" || event.key === null) clear();
  });
  $("acquisition-review").addEventListener("submit", async (event) => {
    event.preventDefault();
    const session = token();
    const current = version;
    const contactId = $("acquisition-contact").value;
    const button = $("acquisition-save");
    setFeedback("");
    button.disabled = true;
    try {
      await request(`/acquisition/contacts/${encodeURIComponent(contactId)}/review`, session, {
        stage: $("acquisition-stage").value,
        has_open_inquiries: $("acquisition-open").checked,
        authorized_list_use: $("acquisition-permission").checked,
        requires_external_sending: $("acquisition-sending").checked,
        requires_sensitive_data: $("acquisition-sensitive").checked,
      });
      if (current !== version || session !== token()) return;
      await load(contactId);
      if (session === token()) setFeedback("Review saved for the selected contact.");
    } catch (error) {
      if (current === version && session === token()) {
        const details = error.blockers && error.blockers.length ? error.blockers.join("; ") : error.message;
        setFeedback(details, true);
      }
    } finally {
      button.disabled = false;
    }
  });
})();
