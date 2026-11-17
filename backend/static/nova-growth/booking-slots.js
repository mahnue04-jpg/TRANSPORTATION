(() => {
  "use strict";

  function validSlot(value) {
    if (typeof value !== "string" || !/^\\d{4}-\\d{2}-\\d{2}T\\d{2}:\\d{2}:\\d{2}(?:\\.\\d+)?(?:Z|[+-]\\d{2}:\\d{2})$/.test(value)) return false;
    return Number.isFinite(Date.parse(value));
  }

  function formatSlot(value) {
    if (!validSlot(value)) return "";
    return new Intl.DateTimeFormat(undefined, {
      year: "numeric", month: "short", day: "numeric", hour: "numeric",
      minute: "2-digit", timeZoneName: "short"
    }).format(new Date(value));
  }

  function availableSlots(payload) {
    if (!payload || !Array.isArray(payload.slots)) return [];
    const seen = new Set();
    return payload.slots
      .filter(s => s && validSlot(s.starts_at_utc) && s.available !== false)
      .map(s => s.starts_at_utc)
      .filter(v => !seen.has(v) && seen.add(v))
      .sort((a, b) => Date.parse(a) - Date.parse(b));
  }

  function populate(select, payload) {
    select.replaceChildren(new Option("Choose an available time", ""));
    for (const value of availableSlots(payload)) {
      select.add(new Option(formatSlot(value), value));
    }
    select.value = "";
    return select.options.length - 1;
  }

  window.NovaBookingSlots = { validSlot, availableSlots, populate, formatSlot };
})();
