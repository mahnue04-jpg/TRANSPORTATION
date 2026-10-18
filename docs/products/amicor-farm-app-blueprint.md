# AMICOR Farm App — Product Blueprint (Draft v0.1)

Decision date: 2026-10-14  
Source: owner-approved replacement of Car Hub (GitHub Issue #341).  
Status: CONCEPT / COMING SOON — not launched, not for sale.

## Product decision
Retire the AMICOR Car Hub and phone-first Car Companion initiatives. Replace their single website catalog slot with AMICOR Farm App. Do not change the other eleven product entries, pricing, or engineering workstreams. Maintain twelve catalog products.

## Audience and problem
Initial hypothesis: small farms, market gardeners, and independent growers need a simple phone-friendly place to keep crop, field, work, harvest, supply and expense records without spreadsheets. This is **not yet validated**.

## Proposed minimum viable application
1. Farm profile and field/plot directory with simple crop and planting records.
2. Task calendar with planting, watering, maintenance and harvest reminders.
3. Harvest log: crop, date, quantity, unit, notes.
4. Supplies/inventory entries and simple expenses (not bookkeeping/tax advice).
5. Exportable CSV summaries; clear manual edit history.
6. Accessible, phone-first interface with basic privacy and account controls.

## Not in the first release
Physical sensors, equipment control, automated irrigation, pesticide or fertilizer prescriptions, weather predictions, crop-yield guarantees, financial/tax advice, or any claim that connected hardware exists. Optional weather information may be considered after validation.

## Customer validation gate
Interview at least 10-15 small growers, observe recordkeeping tasks, test a clickable prototype and evaluate willingness to pay before building a full platform. Only announce an actual feature when tested.

## Website content contract
- Product label: AMICOR Farm App
- Description: "A planned phone-friendly workspace for planting, field tasks, harvest logs and basic farm records."
- Availability: Coming Soon / Concept
- CTA: Join waitlist (must use a functional lead endpoint and supported product value)
- Suggested route: `/farm-app/` with canonical link, metadata and sitemap entry.
- Retire `/car-hub/` using a safe redirect or explanation; remove it from active navigation and sitemap.
- Use a farm illustration clearly labeled as a concept, not a working product screenshot.
- Do not claim the Farm App works now or solicit payment.

## Implementation checklist — Issue #341
- Update `website/catalog.py` and regenerate all dependent site pages.
- Update homepage, product catalog, footer/nav, full status table and early-access product selectors.
- Update leads allowlist (`website/functions/api/leads.js`), lead docs and website README.
- Update sitemap and site metadata; preserve other URLs.
- Audit all old "Car Hub" references and old route links.
- Run link, accessibility, mobile, form and product-count checks.
- Open a PR with before/after preview and test evidence; deploy only after review and successful QA.

## Business priority
Keep existing assigned engineering work untouched. The Farm App is a website/catalog substitution and product discovery concept; production engineering starts only after demand validation and explicit prioritization.
