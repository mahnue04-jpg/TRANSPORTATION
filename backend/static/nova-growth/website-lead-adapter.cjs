'use strict';

// Pure staging adapter: no network access or Cloudflare credentials.
function normalizeWebsiteLead(key, raw, options = {}) {
  if (typeof key !== 'string' || !key.startsWith('lead:')) return null;
  const legacy = /^lead:(\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d+)?Z):([0-9a-f-]{36})$/i.test(key);
  const reference = /^lead:(AMQ-[A-Z0-9]{8})$/.exec(key);
  if (!legacy && !reference) return null;
  let payload;
  try { payload = typeof raw === 'string' ? JSON.parse(raw) : raw; } catch (_) { return null; }
  if (!payload || typeof payload !== 'object' || Array.isArray(payload)) return null;
  if (payload.consent !== true || !payload.name || !payload.email || !payload.company) return null;
  const receivedAt = payload.receivedAt;
  if (typeof receivedAt !== 'string' || !Number.isFinite(Date.parse(receivedAt))) return null;
  return Object.freeze({
    source_system: 'amicor_cloudflare_kv',
    source_key: key,
    reference_id: reference ? reference[1] : (typeof payload.referenceId === 'string' ? payload.referenceId : null),
    received_at: receivedAt,
    name: String(payload.name),
    company: String(payload.company),
    email: String(payload.email),
    product: typeof payload.product === 'string' ? payload.product : null,
    message: typeof payload.message === 'string' ? payload.message : '',
    consent: true,
    is_synthetic: options.trustedSyntheticFixture === true,
    status: 'needs_owner_review',
  });
}
function normalizeWebsiteLeadPage(entries, options = {}) {
  if (!Array.isArray(entries)) throw new TypeError('Expected KV entry array');
  const found = new Map();
  for (const entry of entries) {
    if (!entry || typeof entry !== 'object') continue;
    const item = normalizeWebsiteLead(entry.key, entry.value, options);
    if (item && !found.has(item.source_key)) found.set(item.source_key,item);
  }
  return [...found.values()];
}
module.exports = { normalizeWebsiteLead, normalizeWebsiteLeadPage };
