# Nova Casting & Auditions — Secure Backend Implementation Contract

Status: PROPOSED / NOT IMPLEMENTED. This document belongs to the existing AMICOR Nova Creative Studio; do not create a second standalone platform.

## Product boundaries
- One Nova product, with organizer campaigns for reality TV, beauty events, film and commercial auditions.
- No affiliation or transmission to Zeus or any entertainment organization without a contract and explicit configuration.
- The current `casting-preview.html` is an in-memory fictional demo. Never accept genuine applicant data through it.
- Do not auto-rank people using face, appearance, perceived protected characteristics, or model-generated suitability. Casting decisions remain with authorized humans.

## Phase 1: access-controlled backend
1. Reuse the existing Nova authentication and tenant/organization boundaries; do not create competing login credentials.
2. Define `CastingOrganization` (tenant, verified status), `CastingCampaign` (org, title, category, roles, open/close, age limits), `CastingApplication` (campaign, applicant, state, consent version), `CastingMedia` (private object key, mime, size, scan status), `CastingReview` (reviewer, note, score, stage) and `CastingAuditEvent` (actor, action, timestamp).
3. Enforce object-level permission checks in every read and write. Applicants may see only their own submissions; reviewers only their assigned organization's campaigns; admins have scoped and audited access.
4. Require verified organizer activation before publishing a campaign; all campaigns are unpublished by default. Disallow minors pending a completed guardian/age-safety workflow.
5. Use migrations and database constraints for foreign keys, unique review keys, ownership, state, size limits and timestamps. Do not store raw videos or secrets in database rows.

## Proposed API boundaries (not live)
- `GET /api/nova/casting/campaigns`: only public approved campaigns or organizer-owned drafts.
- `POST /api/nova/casting/campaigns`: organizer-only, creates an unpublished draft.
- `POST /api/nova/casting/campaigns/{id}/applications`: logged-in applicant; requires active campaign and versioned consent.
- `GET /api/nova/casting/campaigns/{id}/applications`: verified authorized organizers only.
- `POST /api/nova/casting/applications/{id}/media-request`: applicant ownership, upload limits, short-lived signed URL.
- `POST /api/nova/casting/applications/{id}/reviews`: scoped reviewer, no external sends.
- `POST /api/nova/casting/applications/{id}/callbacks`: stage proposal only; sending invitations requires explicit approved integration.

## Media/privacy safeguards
- Store uploads in private storage with server-side encryption; short-lived signed retrieval URLs, never public static asset paths.
- Allowlist video MIME and inspect file signatures; cap size, length and count; quarantine until malware checks and media validation complete.
- Prohibit direct third-party forwarding unless campaign recipients are authorized and applicants consent to that recipient.
- Establish documented retention/deletion schedule, applicant data export/removal, incident logging and consent records before production.
- Use rate limits, CSRF-safe authenticated APIs as applicable, security event logs, and monitoring; redact private data from logs.
- No provider billing, automated publishing, external delivery, or marketing contact enabled by default.

## Acceptance gates for a real beta
- Cross-tenant isolation tests for every object type and both read/write routes.
- Authorization tests for anonymous, applicant, organizer, reviewer and admin actors.
- Upload tests for spoofed MIME, oversize data, malicious files, replayed URLs, unauthorized media reads and aborted uploads.
- Minors and consent policy review, deletion tests, retention tests and breach-response ownership.
- A real browser end-to-end test in a staging environment, followed by a controlled opt-in beta.
- Existing Creative Studio regression suite passes, including any unrelated UI-contract drift that is resolved by the responsible owner.

## Commercial/partner posture
- Demo to independent event organizers before building costly integrations.
- Zeus is a potential customer, not an integration already provided or a confirmed partner.
- Keep PR #308 in draft until design, implementation, tests, and owner review are complete.
