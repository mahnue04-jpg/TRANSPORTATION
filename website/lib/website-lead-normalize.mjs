// Read-only normalization for AMICOR_LEADS Cloudflare KV entries.
// This module does not contact KV, write contacts, send messages, or expose secrets.
// Use only inside an authenticated, tenant-scoped owner route.
const MAX = { name: 120, company: 160, email: 254, product: 80, message: 2000 };
function limitedText(value, limit) {
  return typeof value === "string" ? value.trim().slice(0, limit) : "";
}
function parseRecord(value) {
  if (typeof value !== "string" || value.length > 16000) return null;
  try {
    const obj = JSON.parse(value);
    return obj && typeof obj === "object" && !Array.isArray(obj) ? obj : null;
  } catch {
    return null;
  }
}
export function normalizeWebsiteLeadEntry(entry) {
  if (!entry || typeof entry.key !== "string" || !entry.key.startsWith("lead:")) return null;
  if (entry.key.startsWith("dedupe:") || entry.key.length > 300) return null;
  const record = parseRecord(entry.value);
  if (!record) return null;
  const received = record.receivedAt ?? record.received_at;
  if (typeof received !== "string" || !Number.isFinite(Date.parse(received))) return null;
  const consent = record.consent === true || record.consent === "yes";
  const name = limitedText(record.name, MAX.name);
  const email = limitedText(record.email, MAX.email).toLowerCase();
  if (!name || !email || !/^[^\s@]+@[^\s@]+\\.[^\s@]+$/.test(email)) return null;
  const referenceId = entry.key.startsWith("lead:AMQ-") ? entry.key.slice(5) : null;
  return {
    source_system: "cloudflare_amicor_leads",
    source_key: entry.key,
    reference_id: referenceId,
    received_at: new Date(received).toISOString(),
    name,
    company: limitedText(record.company, MAX.company),
    email,
    product: limitedText(record.product, MAX.product),
    message: limitedText(record.message, MAX.message),
    consent,
    is_synthetic: record.is_synthetic === true,
    status: "needs_review",
  };
}
export function normalizeWebsiteLeadEntries(entries) {
  if (!Array.isArray(entries)) return [];
  const seen = new Set();
  const leads = [];
  for (const entry of entries) {
    const normalized = normalizeWebsiteLeadEntry(entry);
    if (!normalized || seen.has(normalized.source_key)) continue;
    seen.add(normalized.source_key);
    leads.push(normalized);
  }
  return leads;
}
