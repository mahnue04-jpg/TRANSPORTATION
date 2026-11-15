import { readWebsiteInquiries } from "./website-lead-reader.mjs";

// Internal service boundary only. NOT an HTTP route. Authentication must be
// verified by a trusted server-side resolver, never from request JSON/headers.
// The Cloudflare KV binding must remain server-side.
export async function getOwnerWebsiteInquiries({ resolvePrincipal, session, kv, tenantId }) {
  if (typeof resolvePrincipal !== "function") {
    return { status: 503, body: { state: "unavailable", inquiries: [] } };
  }
  let principal;
  try {
    principal = await resolvePrincipal(session);
  } catch {
    return { status: 401, body: { error: "unauthenticated" } };
  }
  if (!principal || principal.authenticated !== true) {
    return { status: 401, body: { error: "unauthenticated" } };
  }
  if (principal.role !== "admin" && principal.role !== "super_admin_support") {
    return { status: 403, body: { error: "forbidden" } };
  }
  if (!principal.userId || typeof principal.userId !== "string" ||
      typeof tenantId !== "string" || !tenantId ||
      typeof principal.tenantId !== "string" || principal.tenantId !== tenantId) {
    return { status: 403, body: { error: "forbidden" } };
  }
  const result = await readWebsiteInquiries(kv, { limit: 25, maxPages: 4 });
  return { status: result.state === "available" ? 200 : 503, body: result };
}
