/**
 * In-memory lead probe. Uses a fake KV binding and never calls the network.
 * Do not point this file at production KV or a public hostname.
 */
import { onRequest } from "../functions/api/leads.js";

const puts = [];
const store = {
  async put(key, value) {
    puts.push({ key, value: JSON.parse(value) });
  },
};

globalThis.fetch = async () => {
  throw new Error("staging probe must not call the network");
};
globalThis.caches = {
  default: {
    async match() {
      return null;
    },
    async put() {},
  },
};

function lead(product, consent) {
  return {
    name: "Staging Probe",
    company: "AMICOR Website Test",
    email: "website-staging-probe@example.com",
    phone: "",
    industry: "Software",
    companySize: "1-10",
    product,
    message: "Safe staging probe. Do not contact. Not a customer record.",
    consent,
    middle_name_confirm: "",
    company_website: "",
    website: "",
  };
}

async function post(body) {
  const response = await onRequest({
    request: new Request("https://staging.invalid/api/leads", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
    }),
    env: { AMICOR_LEADS: store },
  });
  const text = await response.text();
  return { status: response.status, body: text ? JSON.parse(text) : null };
}

const empty = await post({});
if (empty.status !== 400 || empty.body.error !== "missing_fields" || puts.length !== 0) {
  console.error("empty", empty, puts.length);
  process.exit(1);
}

const denied = await post(lead("Nova Snap", false));
if (denied.status !== 400 || denied.body.error !== "consent_required" || puts.length !== 0) {
  console.error("denied", denied, puts.length);
  process.exit(2);
}

const snap = await post(lead("Nova Snap", true));
if (snap.status !== 202 || snap.body.stored !== true || puts.length !== 1) {
  console.error("snap", snap, puts.length);
  process.exit(3);
}
if (puts[0].value.product !== "Nova Snap" || puts[0].value.consent !== true) {
  console.error("snap stored", puts[0]);
  process.exit(4);
}

const casting = await post(lead("Nova Casting & Auditions", true));
if (casting.status !== 202 || puts.length !== 2 || puts[1].value.product !== "Nova Casting & Auditions") {
  console.error("casting", casting, puts);
  process.exit(5);
}

const unknown = await post(lead("Nova Casting and Auditions", true));
if (unknown.status !== 400 || unknown.body.error !== "invalid_product" || puts.length !== 2) {
  console.error("unknown", unknown, puts.length);
  process.exit(6);
}

console.log(`STAGING_PROBES_PASSED=5 stored_in_memory=${puts.length}`);
