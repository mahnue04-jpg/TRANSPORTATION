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

## Follow-up: staging compatibility and release target

Read-only inspection confirmed the existing target is `nova-growth-validation-490` (`srv-dbqv8ip5efls73dtpmo0`) in Saye's workspace, with manual deployment and no automatic deploys. Its live commit remains `1395f7e47f0f2e4a94473621374f9219e180ac6b`; this branch has not been deployed there.

The integration now preserves that staging revision's reminder `available_at` fix and production Growth-table exclusion from global startup schema creation, along with its strict PostgreSQL tests and synthetic journey page. The conflict in the worker test file was resolved by retaining both the existing shutdown-lease check and staging reminder due-time check.

The prepared signal-handler correction preserves Uvicorn's previous handler, so the platform's shutdown-status hook does not swallow server termination. Its tests cover handler chaining without recursion and non-callable previous handlers; live SIGTERM verification is still required.

Growth CI now triggers for this stacked PR's actual base branch, and the disposable PostgreSQL test requires the new `20261114_nova_ga_campaigns` migration with no ORM fallback. It checks that the campaign table exists and the exact Alembic revision is current.

### Concrete staging change for owner approval

- **Target only:** existing `nova-growth-validation-490`, service `srv-dbqv8ip5efls73dtpmo0`; dedicated DB `dpg-dbqv7mmtlv9c73d7tnb0-a`, internal hostname `dpg-dbqv7mmtlv9c73d7tnb0-a`, database `nova_ga_490_dispos`.
- **Candidate:** the reviewed head of PR #510. Record its full SHA when approving. Do not substitute the moving default branch or another PR.
- **Source:** integration branch `feature/studio-growth-campaign-handoff`; automatic deployment stays off.
- **Build/start pin:** replace both existing `1395f7e...` checks with the approved candidate SHA, keeping the exact dedicated-database host/name assertions and single Uvicorn worker. Preserve PostgreSQL URL normalization and existing public-origin derivation.
- **Migration:** change only the explicit staging migration target to `20261114_nova_ga_campaigns`. Keep strict PostgreSQL verification against the dedicated database.
- **Flags:** add `NOVA_GROWTH_AGENT_CAMPAIGNS_ENABLED=true` on this target only; keep Growth widget/mock worker settings as currently approved. Retention deletion, live transports, provider keys and payments remain disabled.
- **Data preservation:** before the migration, export the staging database through an approved internal Render shell/client and retain the backup in a private durable destination; verify that it can be restored into a separate disposable database. Do not delete/reset existing records or downgrade the staging database.
- **Browser acceptance:** owner sign-in → create a synthetic Studio project in this isolated database → load it in Growth → campaign draft → explicit activation → public page anonymous chat → consented contact → CRM source → pause/kill-switch rejection. Verify the existing reminder due-time and controlled graceful-shutdown behavior too.
- **Rollback:** restore the previous app/service pin and disable the campaigns flag. Leave the additive campaign table intact; no schema downgrade or data deletion is part of rollback.
- **Cost:** use the existing approved service/database only; no new resources, worker services, subscriptions or plan increases.

Read-only PostgreSQL access through the connected management tool was blocked by the database's empty external IP allowlist. Do not loosen that restriction to make this test convenient. Internal backup/verification capability must be checked before any release. No backup, remote migration, settings update, merge or deployment is claimed by this preparation.

### Final local follow-up result

**127 passed** across Growth unit/integration/security/HTTP/worker-retention/campaign checks, startup-signal chaining and focused Casting/Work & Revenue regressions. The first rerun hit four existing duplicate-opportunity fixtures because this command runner reused process ID 2 and therefore reused the prior disposable `chat_test_2.db`; after removing only that generated local test database and its WAL/SHM files, the complete fresh run passed. No product deduplication rule was weakened.
