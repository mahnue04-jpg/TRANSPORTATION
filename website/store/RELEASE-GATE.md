# AMICOR Nova Digital Products — Release Gate (November 19, 2026)

This document belongs to the review-only digital store branch. It is **not** permission to merge, bill customers, deploy production, or enable downloads.

## Verified in this session
- VoiceLedger Pro voice-first staging app runs at https://voiceledger-pro-staging-v15.onrender.com/ and user reported its functionality working.
- Current staging code is a browser-local ledger and does not provide customer accounts or purchase entitlements.
- The existing store branch proposes VoiceLedger Pro at **$39 one-time** and CFSS Budget Co-Pilot at **$199 one-time**. Both prices are proposals, not currently payable.
- Connected Stripe account name: **Amicor Nova** (live account). No Stripe products, payment links, prices, customers, or live charges were created in this release-gate work.
- The store branch is draft-only, noindex and explicitly not for sale.

## Requirements before VoiceLedger can be sold
1. **Customer offering**: confirm the price, license scope, update/support policy, refund terms, privacy notice and disclosures that browser speech services may process voice. Staging preview is currently public and free; do not describe it as purchased or private access.
2. **Customer data**: browser-local storage is not cloud backup. Provide safe first-run onboarding, backup and restore steps; ensure no buyer is promised remote recovery or sync. Test Safari microphone and Apple Dictation on actual iPhone.
3. **Tax and compliance**: determine whether Minnesota/state sales tax applies to this software and whether Stripe Tax should be enabled; verify any needed registrations. Validate IRS mileage calculations, accounting labels and tax disclaimers for the commercial version.
4. **Checkout**: use Stripe-hosted checkout or payment links with a clearly defined one-time USD price after merchant approval. Confirm product and tax configuration first. Never place Stripe secret keys in frontend HTML.
5. **Purchase-verified delivery**: implement a server-side Stripe webhook handler verifying signature and paid Checkout session/payment status, using event deduplication and recoverable fulfillment state. Send an expiring customer access link or a licensed downloadable package only after verified payment; the success URL alone is not proof of payment.
6. **Operational checks**: verify end-to-end purchase in Stripe test mode, refund and duplicate-webhook behavior, failed payments, receipt emails, customer support contact, product delivery recovery and privacy. Never use synthetic charges in livemode.
7. **Owner release gate**: obtain explicit owner approval for any live product, payment links, charges, production store merge/deploy or paid resource.

## CFSS Budget Co-Pilot — separate workstream
- Only a proposed planning tool, not ready for sale.
- Verify Minnesota CFSS budget model rules, participant-authorized service amounts, worker pay and employer taxes, FMS responsibilities, and applicable accessibility/privacy considerations against current DHS primary sources.
- Do not use or collect PHI in a public prototype.
- Do not present calculations as DHS authorization, claim payment, or FMS spending balances.
- Keep paid offers disabled until the data model, compliance review, calculations and acceptance work are complete.

## Current status
**Review only.** This branch contains marketing copy, a link to the free VoiceLedger staging preview, and a sales-readiness checklist. The production AMICOR website remains unchanged and no live payment flow was enabled.
