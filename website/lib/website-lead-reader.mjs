import { normalizeWebsiteLeadEntries } from "./website-lead-normalize.mjs";

// Internal, read-only Cloudflare KV reader. Never call this from a public route.
// Owner authentication/tenant authorization must happen before any invocation.
// No imports, deliveries, CRM writes, or outbound marketing are performed.
export async function readWebsiteInquiries(store, options = {}) {
  const limit = Math.min(Math.max(Number(options.limit) || 25, 1), 100);
  const maxPages = Math.min(Math.max(Number(options.maxPages) || 3, 1), 10);
  if (!store || typeof store.list !== "function" || typeof store.get !== "function") {
    return { state: "unavailable", inquiries: [], complete: false };
  }
  const entries = [];
  let cursor;
  const seenCursors = new Set();
  try {
    for (let page = 0; page < maxPages; page++) {
      const result = await store.list({ prefix: "lead:", limit, ...(cursor ? { cursor } : {}) });
      if (!result || !Array.isArray(result.keys)) throw new Error("invalid_list");
      for (const item of result.keys) {
        if (!item || typeof item.name !== "string" || !item.name.startsWith("lead:")) continue;
        const value = await store.get(item.name);
        if (typeof value === "string") entries.push({ key: item.name, value });
      }
      if (result.list_complete === true) {
        return { state: "available", inquiries: normalizeWebsiteLeadEntries(entries), complete: true };
      }
      if (typeof result.cursor !== "string" || !result.cursor || seenCursors.has(result.cursor)) {
        return { state: "stale", inquiries: [], complete: false };
      }
      seenCursors.add(result.cursor);
      cursor = result.cursor;
    }
    // A partial dataset is never presented as a complete zero or final count.
    return { state: "stale", inquiries: [], complete: false };
  } catch {
    // Avoid leaking private records on ambiguous or partial failures.
    return { state: "unavailable", inquiries: [], complete: false };
  }
}
