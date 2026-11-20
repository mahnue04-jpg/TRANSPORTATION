# VoiceLedger Pro — commercial release decisions (owner review)
Date: November 19, 2026 (Central)
Status: **DRAFT — no offer for sale, no payment enabled**

## 1. Define the actual product before charging

The existing public VoiceLedger Pro v1.6 staging URL is already fully usable for income, expense, mileage, invoices, local backup and browser or iPhone dictation where supported. The current proposed $39 checkout **does not unlock a distinct feature**. Do not represent an unrestricted public preview as a restricted free trial or promise exclusive access.

**Proposed distinct paid deliverable, for owner decision only:** `VoiceLedger Pro Standalone Kit`, a packaged offline-first HTML/PWA bundle with a full usage guide, a local backup/restore guide, release notes, and downloadable customer copy. A downloadable offline copy and buyer support/updates may have value even while a hosted preview is free. However, any included support, updates, license length or device limits must be defined and approved before advertising them. This is a proposal, not an existing saleable license.

Separate alternatives to consider:
- Keep hosted VoiceLedger Pro **free as a lead-generation tool**, and monetize optional AMICOR setup/bookkeeping workflows later, if separately authorized.
- Sell a licensed standalone bundle at the proposed $39 one-time price, with clear differences from the free version.
- Monetize a hosted account/sync feature **only after it exists and is verified**. Do not advertise cloud backup now.

**Owner decisions required:** confirm or change $39 price; choose whether to sell the standalone bundle while the hosted app is free; decide exact contents, license scope, support promise, updates policy and return/refund policy.

## 2. Important mobile behavior

- In an HTTPS browser that supports speech recognition, tap Start Speaking, pause as needed, and tap Done Speaking before calculation. Explicit Save is still required.
- A locally opened HTML file on iOS often cannot use direct browser speech recognition. iPhone Keyboard Dictation can be used to fill the transcript field. Do not advertise guaranteed one-tap voice recognition for a locally downloaded file.
- Financial data is saved in **that browser's local storage only**, which is per-device and per-origin. Different URLs/browsers do not share a ledger. Weekly manual JSON backup is essential.
- Browser/OS transcription may use external speech providers. No bank connection and no AMICOR-hosted transaction sync are provided.

## 3. Minnesota tax classification — verify before first sale

Minnesota Department of Revenue guidance says sale or license of **prewritten computer software** is taxable, including electronically delivered/downloadable software:
https://www.revenue.state.mn.us/guide/computer-software-and-digital-products
https://www.revenue.state.mn.us/digital-products

Minnesota guidance states that a business must register for a Minnesota Tax ID and Sales and Use Tax account before making taxable Minnesota sales:
https://www.revenue.state.mn.us/guide/registering-your-business

AMICOR's **existing Minnesota sales tax registration has not been verified**. Do not infer it from the LLC formation or federal EIN. Check with a Minnesota tax professional about classification, seller nexus, state/local tax, other jurisdictions, Stripe Tax and filing obligations.

Do not enable live Stripe checkout or charge sales tax until registration and tax configuration are confirmed.

## 4. Calculation references

2026 optional IRS business mileage rate:
- January 1–June 30: **$0.725/mile**
- July 1–December 31: **$0.76/mile**

Source: https://www.irs.gov/tax-professionals/standard-mileage-rates

These match the staging application's current rate table. Eligibility, substantiation and choice of mileage-vs-actual-expense method depend on taxpayer circumstances. Any reserve percentage displayed by VoiceLedger is a user planning assumption, **not the amount of tax owed**.

## 5. Payment and secure delivery release gate

- Stripe connector currently exposes only **Amicor Nova live mode**, not test mode. Do not use live mode for a test purchase.
- Isolated Render checkout service `voiceledger-checkout-validation-562` is running on the **free** plan with `VL_CHECKOUT_MODE=disabled`. It has no test Stripe keys, pricing object or private package and cannot initiate charges.
- Checkout code and simulated webhook tests passed, but **no real Stripe test purchase** has been completed.
- To activate only in isolated test mode: connect a Stripe sandbox/test account; create a test $39 one-time price after owner confirms offer/tax treatment; store test secrets privately; configure a dedicated webhook, persistent order database and private ZIP; verify payment status, fulfillment, retries, refunds/disputes and recovery.
- Public free preview and customer package must not be confused. Do not display a purchase button until fulfillment works and the owner separately approves live checkout.

## 6. Proposed customer FAQ (not for publication yet)

**Does it connect to my bank?** No.
**Where are entries stored?** Locally in the browser/device. Export a backup regularly.
**Can I use my phone?** Yes, in a supported browser or with Apple keyboard Dictation; direct browser mic support varies.
**Can I change phones and keep my entries?** Only by creating and restoring a backup; there is no automatic sync.
**Does it calculate my actual taxes?** No. Calculations and reserves are estimates for review.
**What does the $39 buy?** **Undecided** until owner approves a distinct standalone deliverable, support, updates and license/refund terms.

## Owner launch signoff — currently pending
- [ ] Confirm sellable customer offering and differentiation from free preview
- [ ] Confirm final price and whether sales tax is included or extra
- [ ] Verify MN tax registration, product tax code and checkout tax treatment
- [ ] Approve license, refund, support, privacy and updates terms
- [ ] Verify correct iPhone experience and customer package integrity
- [ ] Connect Stripe test mode and complete real end-to-end test purchase
- [ ] Verify durable fulfillment, private delivery and recovery
- [ ] Separately approve production deployment and live sales

**CFSS Budget Co-Pilot remains the second, not-yet-built commercial offering.**
