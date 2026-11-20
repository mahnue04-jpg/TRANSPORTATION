# CFSS Budget Co-Pilot — Controlled Evaluation Guide
Updated: November 20, 2026
Status: **Development preview, not released for customer use or sale**

## Goal
Evaluate whether a Minnesota CFSS budget-model participant, representative, consultation services professional, or FMS-informed adviser can understand a simple planning forecast. This tool is not part of the official DHS, consultation or FMS systems.

## Safe evaluation process
1. Open the isolated development preview at https://deploy-preview-564--grand-beignet-6447ea.netlify.app/cfss-copilot/ (not the production AMICOR domain).
2. Use the built-in **Load fictional example**. Do **not** enter participant names, member IDs, contact details, medical information, actual payroll, or real FMS statements during this evaluation.
3. Compare the two synthetic staffing scenarios. Confirm that the displayed *budget difference* is labeled as a forecast, not an approval.
4. Expand monthly FMS reconciliation. Enter each month's **individual spending amount**, not a cumulative balance. Missing monthly reports must remain blank rather than zero.
5. Evaluate the **Save plan (JSON)**, **Open saved plan**, print and CSV functions using fictional figures. Treat downloaded files as private financial records even if this demonstration contains only synthetic data.
6. Use the **Send evaluation feedback or request details** link for qualitative comments only. The separate AMICOR inquiry form must not receive actual financial figures, medical records or files.
7. Consult the official DHS materials and the participant's consultation/FMS provider before using any proposed staffing or goods/services amounts to make decisions.

## Known mathematical simplifications
- Assumes wages and hours remain constant through the forecast period.
- Uses 52 weeks / 12 months to approximate monthly staffing costs. This is **not** a DHS billing-unit or service-hours authorization calculation.
- Uses an employer-cost percentage entered by the user; it is not a verified FMS expense factor.
- Worker hourly wages are illustrative; CFSS tiered wage rules, collective bargaining requirements and applicable wage laws are **not validated by this app**. The 2026 DHS CFSS notice describes quarterly budget adjustments for qualifying experienced direct-support workers. Participants must obtain the current authorized amount rather than assume an increase.
- **FMS provider fees are billed on a separate authorization line in the CFSS budget model**, according to DHS. Do not subtract fees that are separately authorized from the service budget a second time. Use a fee in the planning model only if a consultation/FMS professional confirms it belongs in the exact budget total entered.
- FMS monthly reports can use cumulative totals; do not add cumulative month-end balances together. Enter discrete monthly spending amounts or ask the FMS provider to clarify.
- Uses *whole months elapsed* and a future-spending forecast; it does not model partial months, payroll timing, holidays, overtime or FMS administrative fees unless represented in the user's explicit inputs.
- Calculates projected budget differences using total budget minus actual spent-to-date minus forecast future costs.
- Does not determine eligible goods/services, authorize employment, validate wage limits, or certify FMS payment.

## Privacy and accessibility status
- Calculator does not submit entered values to AMICOR, external analytics, or a financial-data service. Script and style files load from the same origin under a restrictive Content Security Policy.
- Routine hosting access logs may capture requests and IP addresses. Do not promise absolute anonymity.
- Browser values are not automatically persisted. JSON/CSV files are saved only by user action and should not be uploaded to untrusted services.
- Owner accepted the fictional-example layout and results on desktop. Keyboard, screen reader, mobile and on-device save/restore accessibility have not been fully accepted by an independent reviewer.

## Review gate before customer evaluation or sale
- [x] Desktop fictional-example calculations visually verified by the owner.
- [x] Same-origin CSS/JS loads and browser-click regression passed.
- [x] Separate qualitative feedback link and no-PHI/no-records caution.
- [ ] Independent review of key budgeting assumptions and CFSS-specific disclosures by a knowledgeable professional.
- [ ] Mobile and accessibility acceptance with non-sensitive fictional data.
- [ ] Final pricing, support, license, refunds, tax classification and payment/delivery workflow, if a paid product is contemplated.
- [ ] Owner approval for production deployment and customer evaluation scope.

## Official references
- Minnesota DHS, CFSS program guidance: https://mn.gov/dhs/disability-aging/home-and-community-services/programs-and-services/cfss-faq/
- Minnesota Statutes 256B.85: https://www.revisor.mn.gov/statutes/cite/256B.85
- DHS goods and services through CFSS (separate FMS fee line in budget model): https://www.dhs.state.mn.us/main/idcplg?IdcService=GET_DYNAMIC_CONVERSION&dID=148505
- DHS FMS responsibilities and rates: https://www.dhs.state.mn.us/main/idcplg?IdcService=GET_DYNAMIC_CONVERSION&dID=148519
- DHS CFSS 2026 tiered-wage budget adjustments: https://www.dhs.state.mn.us/main/idcplg?IdcService=GET_DYNAMIC_CONVERSION&RevisionSelectionMethod=LatestReleased&dDocName=MNDHS-076194

**No production merge, live payments, DHS integration, customer solicitation, or real client-data processing is authorized by this document.**
