// Keep FIRST_CUSTOMER_FUNNEL_PUBLISHED equal to firstCustomerFunnel in
// assets/js/site-config.js. The production build reads the config flag and
// omits the pages when it is false. This constant is the runtime gate.
export const FIRST_CUSTOMER_FUNNEL_PUBLISHED = false;

export function funnelRequestAllowed(env = {}) {
  if (String(env.AMICOR_FUNNEL_PREVIEW || "") === "local") return true;
  return FIRST_CUSTOMER_FUNNEL_PUBLISHED === true && String(env.FIRST_CUSTOMER_FUNNEL || "") === "true";
}

export function funnelDeniedResponse() {
  return new Response("Not found", {
    status: 404,
    headers: {
      "Cache-Control": "no-store",
      "Content-Type": "text/plain; charset=utf-8",
      "X-Robots-Tag": "noindex, nofollow",
    },
  });
}

export function gateFunnelRequest(context) {
  const env = (context && context.env) || {};
  if (!funnelRequestAllowed(env)) return funnelDeniedResponse();
  return context.next();
}
