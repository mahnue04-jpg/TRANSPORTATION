(function () {
  "use strict";
  var posts = {
    research: "AMICOR Nova — Business Operations Research\n\nNeed organized answers instead of hours of searching? We provide AI-assisted vendor research, business and market research, option comparisons, organized findings, and action briefs with owner review before client delivery.\n\nHave a research task slowing your business down? Send us the question and the result you need.",
    admin: "AMICOR Nova — Administrative & Executive Operations Support\n\nWe help businesses organize documents, clean up spreadsheets, prepare meeting summaries and action lists, draft proposals and follow-ups, and structure project/operations work. AI-assisted work is owner-reviewed before client delivery.\n\nBring the messy work. We help turn it into usable business output.",
    workflow: "AMICOR Nova — AI Workflow & Knowledge Operations\n\nWe help businesses organize knowledge, review workflows, structure recurring reports and checklists, and turn scattered information into repeatable operating processes. AI-assisted work is owner-reviewed before client delivery.\n\nIf your business information is hard to track or act on, send us the problem and the result you need."
  };
  function status(message) { var el = document.getElementById("copy-status"); if (el) el.textContent = message; }
  async function copyText(value) { try { await navigator.clipboard.writeText(value); status("Copied."); } catch (_) { status("Copy was blocked by the browser. Select the text manually."); } }
  document.querySelectorAll("[data-copy]").forEach(function (button) { button.addEventListener("click", function () { copyText(posts[button.getAttribute("data-copy")] || ""); }); });
  document.querySelectorAll("[data-copy-text]").forEach(function (button) { button.addEventListener("click", function () { var el = document.getElementById(button.getAttribute("data-copy-text")); copyText(el ? el.value : ""); }); });
  document.querySelectorAll("[data-print]").forEach(function (button) { button.addEventListener("click", function () { var target = document.getElementById(button.getAttribute("data-print")); if (!target) return; target.classList.add("print-target"); window.print(); setTimeout(function () { target.classList.remove("print-target"); }, 300); }); });
}());
