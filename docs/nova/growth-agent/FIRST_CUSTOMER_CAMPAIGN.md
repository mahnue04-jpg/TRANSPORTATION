# AMICOR first customer campaign

Owner priority: dependable paid work and repeat customers with less daily owner effort.

## First offer

Audience hypothesis: small cleaning and home-service businesses with open inquiries or unfinished quotes. Offer remote list organization, a next-action tracker and follow-up drafts for customer review. Entry route: Free Scope Check, then an agreed $49 Starter Task. Do not promise recovered sales, live sending or integrations. After successful delivery, evaluate a specifically scoped recurring service using the existing monthly offers; measure delivery time and costs before pricing that scope.

Use three routes around this one offer: before-and-after demonstrations using synthetic example data, introductions through existing business relationships, and individual prospect research with owner-reviewed outreach drafts. No messages or posts are sent by this change. The paused Makkan prospect pipeline stays paused.

## Implemented in this branch

The owner dashboard has a First customer campaign panel. Load campaign shows the offer, hook, call to action, distribution actions, existing non-synthetic CRM contacts and saved review stages. Qualification checks open inquiries, authorized list use, external sending and sensitive-data requirements. Opted-out contacts cannot advance. These answers are owner confirmations, not independent verification.

- `GET /api/nova/growth-agent/acquisition` returns the draft campaign and tenant-scoped board.
- `POST /api/nova/growth-agent/acquisition/contacts/{contact_id}/review` persists an owner review in existing lead events.
- Stages: new → qualified → quoted → ordered → delivered; decline is supported. Ordered and delivered are owner assertions, not verified money.
- Counts cover all reviewed contacts; the visible review list is capped at 100, and the existing CRM picker at 200 recent contacts.
- Existing contacts are manually assigned to this campaign. Website clicks, new inbound attribution and payment verification are not connected. Verified revenue is null, not invented zero or estimated sales.
- Duplicate identical reviews do not create another event. Contact rows are locked during transition checks on databases supporting row locking.
- Owner role, tenant checks, feature gates and disabled external transports remain in place. No schema changes or migrations.

Built from PR #517 head b30c8de05891dbceb73ae6ac28ade12765166e29, preserving its owner authorization fixes. Creative Studio, Operations Agent and Work & Revenue files are untouched.

## Launch acceptance

Before public use, review the offer and delivery capacity; verify public intake and attribution; connect and verify payment evidence; verify delivery of one authorized paid task; then authorize content publishing and any outbound contact separately. Current Growth Agent restoration/startup and deployment gates remain. Do not describe this panel as an autonomous or live revenue system.

The first business targets are three paid pilots and one repeat purchase or recurring agreement, with owner time and delivery costs measured. These are targets, not forecasts.

## Market evidence

FreshBooks surveyed 750 US small-business owners. Its 2025 report found 47% said customer acquisition was harder and 57% reported worsening time management/work-life balance. This supports researching the problem; it does not validate AMICOR's specific audience or offer.

https://www.freshbooks.com/press/releases/freshbooks-2025-state-of-us-small-business
