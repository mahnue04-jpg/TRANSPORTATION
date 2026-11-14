# Creative Studio → Growth Agent campaign handoff

Implemented on an isolated branch based on Growth Agent `e4d0aec2`. This change is not deployed.

## Working flow

1. Select a Creative Studio project and follow **Prepare a customer inquiry campaign** into Growth Agent.
2. Sign in to Growth Agent with the same owner account. Load **my Studio projects and campaigns**. Only that owner's persisted Studio projects are listed. A project query parameter selects a project only after this authorized list is loaded.
3. Configure and activate the business profile with approved FAQs. Create a widget for the hostname that will serve the inquiry page. Keep its public installation token in the widget setup field.
4. Enter a campaign title and customer-facing description and save a draft. This does not generate a video or publish anything.
5. Review the displayed content, then approve and activate. Copy the resulting inquiry-page link into the commercial CTA or an owner-approved post. The page must be hosted on the widget's configured domain.
6. A visitor can ask an anonymous question. Contact capture requires transactional or marketing consent. A later consented turn attaches the contact to the anonymous conversation.
7. The CRM shows the observed campaign and Studio project source with the lead. Review the inquiry before accepting work. Repeated sequential chat turns reuse the source event.
8. Pause a campaign or disable the business agent to make its inquiry page unavailable. Widget rotation invalidates the saved public embed token; create a replacement campaign using the new setup token.

## Scope and boundaries

- New `nova_ga_campaigns` table and additive migration `20261114_nova_ga_campaigns`, following `20261112_nova_ga_retention`. Production DDL is gated like the existing Growth migrations.
- Feature defaults off: `NOVA_GROWTH_AGENT_CAMPAIGNS_ENABLED=true` is required in addition to the Growth Agent and public-widget flags.
- Campaigns remain drafts until their owner explicitly approves activation. Campaign title/description are escaped on the public page; no Studio project metadata, owner credentials, or owner session is exposed there.
- Saved public widget tokens are public embed configuration, not owner authorization or provider credentials. They are omitted from owner list responses and audit records. Existing signature, active-installation, token-hash, domain, consent and rate-limit checks still apply.
- Public inquiry URLs are available only while campaign, profile and widget gates permit. They provide a chat inquiry, not a payment or self-service appointment checkout.
- Campaign source is an observed link, not a verified sale or causal attribution claim. Existing CRM state is not advanced to paid/accepted by this connection.
- No social publishing, paid generation, outbound provider activation, Ops task creation, or customer delivery was added. Operations handoff is a later integration requiring scope approval.
- This branch stacks on PR #490; it does not merge other Studio/Operations branches. It reads existing Studio SQL project records and leaves media, providers and rendering untouched.

## Local verification

- Combined local Growth/casting/work-revenue run: **119 passed**, including the first four campaign tests (115 existing checks).
- Final campaign suite after adding installation-binding and migration tests: **6 passed**. Covers the anonymous → consented HTTP journey, grounded chat, escaped customer page, CRM source linkage, sequential duplicate reuse, owner/tenant boundaries, mismatched domain/installation, token rotation, pause/kill switch, missing consent, default-off flag and local SQLite migration upgrade/downgrade/production lock.
- JavaScript syntax checks passed for Growth dashboard, widget and Studio script. `git diff --check` passed.
- The owner dashboard, widget and Studio link were implemented; visual/browser acceptance remains unverified. Chromium launch was blocked by this environment (`socket() failed: Operation not permitted`). No screenshots or browser-success claim.
- No PostgreSQL verification of this new migration, remote staging verification, or production deployment was performed in this pass.

## Staging release boundary

Use only the existing isolated Growth staging target after reviewing its current commit and database. Do not deploy this branch to Creative Studio staging or production. Confirm the staging database has the relevant Studio project records for the same owner; separate databases cannot share those records automatically.

Before staging: record target and exact candidate SHA, take the staging database backup, apply the additive campaign migration only to that approved isolated database, and enable the campaigns flag there. Verify real owner login, selection, draft/approval, public inquiry chat and CRM source in a browser. Keep all live transports, provider keys, payments and retention deletion disabled. Rollback by disabling the campaigns flag and returning to the previous application commit; the additive table can remain for recovery.

No merge, deployment, remote migration or new paid resource was performed by this change.
