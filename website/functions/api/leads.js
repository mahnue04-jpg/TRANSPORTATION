const PRODUCTS = new Set([
  "Business Services", "Ask Nova", "Nova Operations Agent", "Nova Creative Studio",
  "Nova Casting & Auditions",
  "Autonomous Operations Agent",
  "AMICOR Nova Work & Revenue",
  "AMICOR Nova Today",
  "AMICOR Nova Create",
  "AMICOR Health",
  "AMICOR Deliver",
  "Lifesaver AI Care Cloud",
  "Home Hub",
  "Car Hub",
  "Partnership",
  "Other",
]);

const LIMITS = {
  name: 120,
  company: 160,
  email: 254,
  phone: 40,
  industry: 80,
  companySize: 20,
  product: 80,
  message: 2000,
};

const QUOTE_PROMPT = "Project goal: Deliverables needed: Approximate volume: Deadline:";
const DEDUPE_TTL_SEC = 24 * 60 * 60;

function json(status, body) {
  return new Response(JSON.stringify(body), {
    status,
    headers: {
      "Content-Type": "application/json; charset=utf-8",
      "Cache-Control": "no-store",
    },
  });
}

function plain(value, max) {
  return String(value || "")
    .replace(/<[^>]*>/g, "")
    .replace(/[\u0000-\u001F\u007F]/g, " ")
    .trim()
    .slice(0, max);
}

function collapsed(value) {
  return String(value || "").replace(/\s+/g, " ").trim();
}

function tooLong(value, max) {
  return String(value || "").length > max;
}

function validEmail(value) {
  return /^[^\s@]+@[^\s@]+\.[^\s@]+$/.test(value);
}

function emailNotification(attempted, sent, reason) {
  return { attempted: !!attempted, sent: !!sent, reason };
}

async function rateLimited(request, cache) {
  if (!cache) return false;
  const ip = request.headers.get("CF-Connecting-IP") || "unknown";
  const key = new Request(`https://amicor-lead-rate.invalid/${encodeURIComponent(ip)}`);
  const hit = await cache.match(key);
  if (!hit) {
    await cache.put(key, new Response("1", { headers: { "Cache-Control": "max-age=3600" } }));
    return false;
  }
  const count = Number(await hit.text()) || 0;
  if (count >= 5) return true;
  await cache.put(key, new Response(String(count + 1), { headers: { "Cache-Control": "max-age=3600" } }));
  return false;
}

async function fingerprint(email, product, message) {
  const bytes = new TextEncoder().encode([email, product, message].join("\n"));
  const digest = await crypto.subtle.digest("SHA-256", bytes);
  return [...new Uint8Array(digest)].map((part) => part.toString(16).padStart(2, "0")).join("");
}

function makeReference(randomUUID) {
  return `AMQ-${randomUUID().replace(/-/g, "").slice(0, 8).toUpperCase()}`;
}

export async function handleLead(request, env, deps = {}) {
  const cache = deps.cache || (typeof caches !== "undefined" ? caches.default : null);
  const fetchImpl = deps.fetchImpl || fetch;
  const randomUUID = deps.randomUUID || (() => crypto.randomUUID());

  if (request.method === "OPTIONS") {
    return new Response(null, { status: 204, headers: { Allow: "POST, OPTIONS" } });
  }
  if (request.method !== "POST") {
    return json(405, { ok: false, stored: false, error: "method_not_allowed" });
  }

  if (await rateLimited(request, cache)) {
    return json(429, { ok: false, stored: false, error: "rate_limited" });
  }

  let raw;
  try {
    raw = await request.json();
  } catch (err) {
    return json(400, { ok: false, stored: false, error: "invalid_json" });
  }

  if (
    plain(raw.middle_name_confirm, 200) ||
    plain(raw.company_website, 200) ||
    plain(raw.website, 200)
  ) {
    return json(204, { ok: true, stored: false });
  }

  for (const field of Object.keys(LIMITS)) {
    if (tooLong(raw[field], LIMITS[field])) {
      return json(400, { ok: false, stored: false, error: "field_too_long" });
    }
  }

  const payload = {
    receivedAt: new Date().toISOString(),
    name: plain(raw.name, LIMITS.name),
    company: plain(raw.company, LIMITS.company),
    email: plain(raw.email, LIMITS.email).toLowerCase(),
    phone: plain(raw.phone, LIMITS.phone),
    industry: plain(raw.industry, LIMITS.industry),
    companySize: plain(raw.companySize, LIMITS.companySize),
    product: plain(raw.product, LIMITS.product),
    message: plain(raw.message, LIMITS.message),
    consent: raw.consent === true || raw.consent === "yes",
    source: "amicor-public-website-w8",
  };

  if (!payload.name || !payload.company || !payload.industry || !payload.companySize || !payload.message) {
    return json(400, { ok: false, stored: false, error: "missing_fields" });
  }
  if (collapsed(payload.message) === QUOTE_PROMPT) {
    return json(400, { ok: false, stored: false, error: "message_incomplete" });
  }
  if (!validEmail(payload.email)) {
    return json(400, { ok: false, stored: false, error: "invalid_email" });
  }
  if (!PRODUCTS.has(payload.product)) {
    return json(400, { ok: false, stored: false, error: "invalid_product" });
  }
  if (!payload.consent) {
    return json(400, { ok: false, stored: false, error: "consent_required" });
  }

  const store = env.AMICOR_LEADS;
  if (!store) {
    return json(503, {
      ok: false,
      stored: false,
      error: "lead_delivery_disabled",
      emailNotification: emailNotification(false, false, "not_configured"),
    });
  }

  function notSaved() {
    return json(500, {
      ok: false,
      stored: false,
      error: "not_saved",
      notified: false,
      emailNotification: emailNotification(false, false, "not_attempted"),
    });
  }

  const dedupeKey = `dedupe:${await fingerprint(payload.email, payload.product, payload.message)}`;
  let existingRaw;
  try {
    existingRaw = await store.get(dedupeKey);
  } catch (err) {
    return notSaved();
  }
  if (existingRaw) {
    let existing = null;
    try {
      existing = JSON.parse(existingRaw);
    } catch (err) {
      existing = null;
    }
    const priorId = existing && existing.referenceId;
    if (priorId) {
      let priorLead;
      try {
        priorLead = await store.get(`lead:${priorId}`);
      } catch (err) {
        return notSaved();
      }
      if (priorLead) {
        return json(200, {
          ok: true,
          stored: true,
          referenceId: priorId,
          duplicate: true,
          notified: false,
          dedupeIndexed: true,
          emailNotification: emailNotification(false, false, "duplicate"),
        });
      }
    }
  }

  let referenceId = "";
  try {
    for (let attempt = 0; attempt < 5; attempt += 1) {
      const candidate = makeReference(randomUUID);
      const taken = await store.get(`lead:${candidate}`);
      if (!taken) {
        referenceId = candidate;
        break;
      }
    }
  } catch (err) {
    return notSaved();
  }
  if (!referenceId) return notSaved();

  const record = { ...payload, referenceId };
  try {
    await store.put(`lead:${referenceId}`, JSON.stringify(record));
  } catch (err) {
    return notSaved();
  }

  let dedupeIndexed = true;
  try {
    await store.put(dedupeKey, JSON.stringify({ referenceId }), { expirationTtl: DEDUPE_TTL_SEC });
  } catch (err) {
    dedupeIndexed = false;
  }

  const webhook = (env.LEAD_WEBHOOK_URL || "").trim();
  let notification = emailNotification(false, false, "not_configured");
  if (webhook) {
    notification = emailNotification(true, false, "webhook_failed");
    try {
      const headers = { "Content-Type": "application/json" };
      if (env.LEAD_WEBHOOK_TOKEN) {
        headers.Authorization = `Bearer ${env.LEAD_WEBHOOK_TOKEN}`;
      }
      const forwarded = await fetchImpl(webhook, {
        method: "POST",
        headers,
        body: JSON.stringify(record),
      });
      if (forwarded.ok) {
        notification = emailNotification(true, false, "webhook_accepted");
      }
    } catch (err) {
      notification = emailNotification(true, false, "webhook_failed");
    }
  }

  return json(202, {
    ok: true,
    stored: true,
    referenceId,
    duplicate: false,
    notified: false,
    dedupeIndexed,
    emailNotification: notification,
  });
}

export async function onRequest(context) {
  return handleLead(context.request, context.env);
}
