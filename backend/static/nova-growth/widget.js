(function () {
  var script = document.currentScript;
  if (!script) return;
  var token = script.getAttribute("data-amicor-growth-token") || "";
  var apiBase = script.getAttribute("data-amicor-growth-api") || "";
  if (!token) return;

  var css = document.createElement("link");
  css.rel = "stylesheet";
  css.href = (apiBase || "") + "/static/nova-growth/widget.css";
  document.head.appendChild(css);

  var root = document.createElement("div");
  root.className = "amicor-ga-root";
  root.innerHTML =
    '<div class="amicor-ga-panel" role="dialog" aria-label="Chat with business">' +
    '<div class="amicor-ga-header"><strong>Chat</strong><p>AI assistant — answers from approved FAQ only.</p></div>' +
    '<div class="amicor-ga-log" aria-live="polite"></div>' +
    '<form class="amicor-ga-form">' +
    '<label class="amicor-ga-consent"><input type="checkbox" name="consent_tx" /> I agree to be contacted about this inquiry (transactional).</label>' +
    '<label class="amicor-ga-consent"><input type="checkbox" name="consent_mkt" /> I opt in to occasional marketing messages (optional).</label>' +
    '<input type="text" name="name" placeholder="Your name (optional)" autocomplete="name" />' +
    '<input type="email" name="email" placeholder="Email (optional)" autocomplete="email" />' +
    '<input type="text" name="message" required placeholder="Ask a question" aria-label="Message" />' +
    '<button type="submit">Send</button>' +
    "</form></div>" +
    '<button type="button" class="amicor-ga-toggle" aria-expanded="false">Chat with us</button>';
  document.body.appendChild(root);

  var panel = root.querySelector(".amicor-ga-panel");
  var toggle = root.querySelector(".amicor-ga-toggle");
  var log = root.querySelector(".amicor-ga-log");
  var form = root.querySelector("form");
  var conversationId = null;

  toggle.addEventListener("click", function () {
    var open = panel.classList.toggle("open");
    toggle.setAttribute("aria-expanded", open ? "true" : "false");
  });

  function addMsg(text, cls) {
    var el = document.createElement("div");
    el.className = "amicor-ga-msg " + (cls || "");
    el.textContent = text;
    log.appendChild(el);
    log.scrollTop = log.scrollHeight;
  }

  form.addEventListener("submit", function (e) {
    e.preventDefault();
    var fd = new FormData(form);
    var message = String(fd.get("message") || "").trim();
    if (!message) return;
    addMsg(message, "");
    form.querySelector('[name="message"]').value = "";
    fetch((apiBase || "") + "/api/nova/growth-agent/widget/chat", {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
        // Explicit embed origin so same-origin demos still fail closed on domain match.
        "X-Amicor-Growth-Origin": window.location.origin,
      },
      body: JSON.stringify({
        token: token,
        campaign_id: script.getAttribute("data-amicor-growth-campaign") || null,
        message: message,
        conversation_id: conversationId,
        visitor_name: String(fd.get("name") || "") || null,
        visitor_email: String(fd.get("email") || "") || null,
        consent_transactional: !!fd.get("consent_tx"),
        consent_marketing: !!fd.get("consent_mkt"),
      }),
    })
      .then(function (res) {
        return res.json().then(function (data) {
          if (!res.ok) throw new Error((data && data.detail && (data.detail.message || data.detail)) || res.statusText);
          return data;
        });
      })
      .then(function (data) {
        conversationId = data.conversation_id;
        addMsg(data.reply || "No reply", "bot");
      })
      .catch(function (err) {
        addMsg(err.message || "Request failed", "bot");
      });
  });
})();
