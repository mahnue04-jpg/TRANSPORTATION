# PR #521: production Cloudflare source security gates (not approval to activate)

The public Pages form writes `lead:<timestamp>:<uuid>` objects into the Cloudflare binding `AMICOR_LEADS`. The object has customer-submitted company, contact, product and consent fields, but **no server-trusted tenant/organization ID**. Consequently no legitimate per-tenant partition may be inferred from those fields. All historical KV entries must remain excluded from multi-tenant access unless the namespace has been independently verified to belong solely to one authorized organization.

## Hard requirements before connection

1. **Signed owner session:** reuse `require_growth_owner` to validate the active JWT, server-side user role, and organization. The stricter inquiry boundary additionally requires `ROLE_ADMIN` and exact organization equality. Super-admin support must not browse another tenant's inquiries.
2. **Operator-owned source mapping:** a trusted, server-controlled map must bind a single specific organization to exactly one lead namespace. Never accept namespace IDs, Cloudflare account IDs, API tokens, endpoints, or organization-to-namespace mappings from an HTTP request or customer payload. Fail closed on missing mapping or shared namespace. `website_inquiry_source_binding.py` supplies a pure offline selector; it is **not connected** to the endpoint or to Cloudflare.
3. **Least privilege:** if later enabled, supply a separately issued Cloudflare token restricted to read/list operations for the verified namespace where supported. Do not use a general account admin token or activate webhook forwarding. Review exact provider scope before attaching secrets; never put the token in the repository, querystring, logs, HTML, or browser.
4. **Read-only and privacy:** no list/get unless identity, role, tenant, source map, and explicit activation gate all pass. Bound pagination and record size; incomplete listing, bad JSON, provider errors, or missing keys mean unavailable, never an empty queue. No production data in CI; do not export real inquiries to build logs, screenshots, monitoring, LLM providers, or other tenants.
5. **Operational acceptance:** before staged authorization verify actual Cloudflare storage ownership, how production leads are retained/deleted, the exact RBAC tests, and whether public form submissions are durably stored. Independently validate retrieval, pagination, revocation, privacy, and auditability on an explicitly approved isolated setup. Keep messaging, payment, and automated outreach disabled until separately authorized.

## Current implementation and evidence

The default `GET /api/nova/growth-agent/website-inquiries/read-only` returns 503 source unavailable for authenticated owners because no source factory or Cloudflare credentials are configured. Fixture-based HTTP tests and browser tests prove the authentication/tenant contract, not production connectivity. The trusted namespace selector remains an offline design gate. Existing `nova-growth-validation-490` and public Pages production remain untouched.

**Do not merge, deploy, configure a Cloudflare token, or read live customer data without a subsequent explicit approval and passed latest-commit CI.**
