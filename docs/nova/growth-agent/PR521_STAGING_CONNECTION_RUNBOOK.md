# PR #521: controlled staging connection runbook

Status: **development candidate only**. The live `AMICOR_LEADS` Cloudflare namespace belongs to the public website. Owner-reviewed dashboard evidence showed 8 stored keys and 10 writes in November 2026, including internal testing. There is no verified external paying prospect. This evidence is not a production API integration test.

## Release prerequisites

- Verify the current PR head and all CI checks. Never treat an older green commit as validation for a new head.
- Create or select an **isolated and approved staging service** built from this PR head. Do **not** repin `nova-growth-validation-490` or change its dedicated PostgreSQL database, branch, build command, secrets, or URL. There is no known PR #521 Render service as of the inspected November 18 service list. Do not create a paid plan.
- Keep any new/approved staging instance's production database, workers, SMS, email, live AI, calendar, paid providers, Stripe, and migrations off. Do not copy production customer data into staging DB.
- Confirm the signed-in Growth admin's **actual immutable organization ID** from the trusted server-side auth record. Do not infer tenant from the lead values (company, source, email, product are customer-controlled). The dedicated Cloudflare KV namespace must be verified as AMICOR-only, with no sharing across tenants.
- Create a separate Cloudflare API token with **Workers KV Storage Read** scoped to the intended account/resource where the dashboard supports it; do not grant Workers KV Storage Write, account admin, or global API key access. Cloudflare API documentation: https://developers.cloudflare.com/api/resources/kv/subresources/namespaces/subresources/keys/methods/list/
- Enter token **directly in the approved staging environment's secret input**, never in GitHub, ChatGPT, CLI logs, screenshots, PR comments, browser query strings, or customer-facing pages. Never post the real token here.
- Restrict staging to owner/admin authentication; review logs to prevent request payload and PII collection.

## Staging-only environment values

Configured privately only on the approved isolated staging service, **not** on the public website, shared production, or existing protected Growth service.

| Variable | Required value |
| --- | --- |
| `AMICOR_ENVIRONMENT` | `staging` |
| `NOVA_WEBSITE_INQUIRY_KV_READ_ENABLED` | `true` **only after every prerequisite passes** (otherwise unset/false) |
| `NOVA_WEBSITE_INQUIRY_ORG_ID` | Exact server-verified owner organization ID; never a company name from the form |
| `NOVA_WEBSITE_INQUIRY_CF_ACCOUNT_ID` | Cloudflare account ID, entered privately |
| `NOVA_WEBSITE_INQUIRY_CF_NAMESPACE_ID` | Verified AMICOR-only KV namespace ID, entered privately |
| `NOVA_WEBSITE_INQUIRY_CF_READ_TOKEN` | Restricted read-only Cloudflare token, entered privately |

The factory in `website_inquiry_cloudflare_readonly.py` remains default-off unless the runtime explicitly identifies as staging and the feature flag is true. Missing token or invalid mapping => unavailable. The owner-only authenticated route is `GET /api/nova/growth-agent/website-inquiries/read-only`. It uses only Cloudflare `GET /keys` and `GET /values/:key` and performs no Cloudflare write/delete.

## Acceptance and abort criteria

1. Verify feature OFF: signed owner sees `503 source_unavailable`, and UI shows *Not connected* rather than zero inquiries.
2. Turn on only on isolated staging after credentials are private and correctly scoped; verify a signed **AMICOR admin** can see source records marked `needs_owner_review`. Keep source-key provenance and UTC timestamps.
3. Verify anonymous, dispatcher, support-role, foreign-tenant, and global-tenant denial **before** source initialization.
4. Check pagination and replay: no duplicates; incomplete/bad provider responses fail closed and report unavailable; the namespace is never modified. Disable the token to prove revocation behavior.
5. Mark owner/internal tests **not qualified** for sales reporting; do not automatically convert any record to Growth CRM contact, count as new paying prospects, send email/SMS, book, or bill.
6. Verify no Cloudflare record values, tokens, private messages or personal details land in service logs, error responses, GitHub Actions, screenshots, or public previews.

**Abort** if the existing staging service would need to be repinned, the tenant ownership is ambiguous, a read-only credential cannot be obtained, required scopes would permit writes, or any provider request discloses PII beyond authorized owner display. Return the flag to false and revoke the dedicated token. No DB migrations, no KV changes, and no webhook notification activation.

## Release status

Code-only integration is not deployment. CI success demonstrates synthetic/offline behavior, not real Cloudflare access. No live credentials or real customer inquiries were processed in development. A separately approved target and private token are prerequisites to finish staging verification.
