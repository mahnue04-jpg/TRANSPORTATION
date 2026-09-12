const PRODUCTS = new Set([
  "Autonomous Operations Agent",
  "AMICOR Health",
  "AMICOR Deliver",
  "Lifesaver AI Care Cloud",
  "Home Hub",
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

function tooLong(value, max) {
  return String(value || "").length > max;
}

function validEmail(value) {
  return /^[^\s@]+@[^\s@]+\.[^\s@]+$/.test(value);
}

async function rateLimited(request) {
  const ip = request.headers.get("CF-Connecting-IP") || "unknown";
  const key = new Request(`https://amicor-lead-rate.invalid/${encodeURIComponent(ip)}`);
  const cache = caches.default;
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

export async function onRequest(context) {
  const { request, env } = context;
  if (request.method === "OPTIONS") {
    return new Response(null, { status: 204, headers: { Allow: "POST, OPTIONS" } });
  }
  if (request.method !== "POST") {
    return json(405, { ok: false, error: "method_not_allowed" });
  }

  if (await rateLimited(request)) {
    return json(429, { ok: false, error: "rate_limited" });
  }

  let raw;
  try {
    raw = await request.json();
  } catch (err) {
    return json(400, { ok: false, error: "invalid_json" });
  }

  if (plain(raw.company_website, 200) || plain(raw.website, 200)) {
    return json(204, { ok: true });
  }

  for (const field of Object.keys(LIMITS)) {
    if (tooLong(raw[field], LIMITS[field])) {
      return json(400, { ok: false, error: "field_too_long" });
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
    return json(400, { ok: false, error: "missing_fields" });
  }
  if (!validEmail(payload.email)) {
    return json(400, { ok: false, error: "invalid_email" });
  }
  if (!PRODUCTS.has(payload.product)) {
    return json(400, { ok: false, error: "invalid_product" });
  }
  if (!payload.consent) {
    return json(400, { ok: false, error: "consent_required" });
  }

  const store = env.AMICOR_LEADS;
  const webhook = (env.LEAD_WEBHOOK_URL || "").trim();
  if (!store && !webhook) {
    return json(503, {
      ok: false,
      error: "lead_delivery_disabled",
    });
  }

  let stored = false;
  if (store) {
    const id = crypto.randomUUID();
    await store.put(`lead:${payload.receivedAt}:${id}`, JSON.stringify(payload));
    stored = true;
  }

  let notified = false;
  if (webhook) {
    try {
      const headers = { "Content-Type": "application/json" };
      if (env.LEAD_WEBHOOK_TOKEN) {
        headers.Authorization = `Bearer ${env.LEAD_WEBHOOK_TOKEN}`;
      }
      const forwarded = await fetch(webhook, {
        method: "POST",
        headers,
        body: JSON.stringify(payload),
      });
      notified = forwarded.ok;
    } catch (err) {
      notified = false;
    }
  }

  if (stored || notified) {
    return json(202, { ok: true, stored, notified });
  }
  return json(502, { ok: false, error: "delivery_failed" });
}
