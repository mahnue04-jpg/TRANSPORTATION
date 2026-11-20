# AMICOR Nova — CFSS Budget Co-Pilot professional review packet

**Prepared:** November 20, 2026  
**Status:** Independent program review requested; **not DHS/FMS approved**, not for real participant financial information, not authorized for production or paid sales.  
**Review environment:** https://deploy-preview-564--grand-beignet-6447ea.netlify.app/cfss-copilot/  
**Source PR:** https://github.com/mahnue04-jpg/TRANSPORTATION/pull/564

## Purpose and scope

A private-on-device **planning companion** for participants or representatives who already have an approved Minnesota CFSS **budget-model** authorization and monthly financial management services (FMS) statements. It **does not** determine CFSS eligibility or a service authorization, replace the consultation services provider/FMS provider, approve purchases, process payroll, calculate official billable units, or exchange data with DHS.

The reviewer should evaluate whether the app's labels, assumptions, displays, and exported reports are **understandable and not misleading** under the current CFSS program. This is **not** a request for DHS endorsement or authority to use real participant records.

## Accepted fictional demonstration (already accepted by AMICOR owner)

| Fictional scenario input or calculated result | Amount |
|---|---:|
| Entered approved period budget | $48,000 |
| Plan duration | 12 months |
| Elapsed | 3 months |
| Reported spent to date | $9,500 |
| Planned worker wage and weekly hours | $20/hour; 30 hours/week |
| User-entered employer-related cost estimate | 17% |
| Other monthly planned expenses | $200 |
| One-time planned purchase | $450 |
| Months remaining | 9 |
| Monthly estimated future spending | $3,242 |
| Projected future spending | $29,628 |
| Projected period-end spending | $39,128 |
| Projected budget difference | $8,872 |
| Fictional monthly FMS amounts | $3,200 + $3,100 + $3,200 = $9,500 |
| Alternative staffing scenario | $22/hour; 28 hours/week |
| Alternative projected period-end spending | $39,858.08 |
| Difference from baseline | +$730.08 |

**This is an arithmetic demonstration, not a claim that any wage, service, hour, cost, or good is authorized.** The owner's desktop screenshots already verified that the buttons, formatting and fictional calculation results display correctly. There is no reason to repeat that demonstration for this program review.

## Reviewer questions (mark YES / CHANGE NEEDED / NOT APPLICABLE)

1. **Budget source and timeframe.** Does "authorized budget" clearly direct users to the approved CFSS **service-delivery plan** and current lead-agency authorization, rather than a self-estimated balance or generic annual rate?
2. **FMS reporting.** Is the distinction between **spent to date**, **individual monthly spending** and **cumulative month-end totals** clear enough to prevent double-counting? Can a participant understand that this tool is not the official record?
3. **Worker wage.** Is the warning that wages must comply with current CFSS **tiered wage floors**, bargaining terms and applicable state/local law strong enough? Are any additional worker-related cost elements typically required by FMS reports but absent from this simplified model?
4. **Employer costs and FMS fees.** Does the treatment of user-entered burden percentage and recurring expenses risk double counting separately authorized FMS fees or misrepresenting insurance, background-study, overtime, payroll and benefit expenses?
5. **Service authorizations.** Could "illustrative weekly hours budget may cover" be mistaken for a worker **service-hours authorization**, even with its explicit disclaimer? Should the card be removed or renamed?
6. **Timing and variance.** Are 52 weeks / 12 months, constant weekly staffing and **whole months elapsed** clear as forecast simplifications rather than DHS rate formulas or payroll accounting? Should partial months be omitted from public evaluation until modeled?
7. **Goods/services.** Do labels make clear that any goods/services must already be in the approved plan and separately verified with the consultation/FMS provider? Does the model confuse agency and budget models?
8. **Accessibility.** Can a keyboard and assistive-technology user access the optional monthly inputs, calculate results, understand over-budget messaging, save/restore a **fictional** plan locally and follow result focus/scroll? Please report device/browser, not any participant details.
9. **Privacy and storage.** Is it clear that the calculator sends no entered figures to AMICOR, that visits may appear in ordinary hosting logs, and that user-downloaded JSON/CSV files remain the person's responsibility?
10. **Public evaluation wording.** Is any phrase still likely to imply DHS approval, FMS accreditation, eligibility determination, direct participant service, or a guarantee that projected funds may be spent?

For each **CHANGE NEEDED**, provide the specific phrase, expected compliant wording or program reference, and severity (**blocker** / **improvement**). Do not send real FMS statements, participant names, screenshots containing participant information, or financial records. Use **fictional numbers only**.

## Current technical safeguards

- No accounts, bank integration, automated financial-record upload, customer payment route or cloud ledger.
- Budget entry and formulas run in browser memory using same-origin `app.js`/`style.css`; page Content Security Policy blocks script/style third-party hosts and outbound connections.
- Optional local JSON plan saving/restoring, CSV export and printing by user action only.
- A separate AMICOR feedback inquiry link asks for general comments, not participant records.
- Owner-confirmed fictional example and CI for computation, privacy, UI controls and website build.

## Acceptance and launch decision

Review outcome: **PENDING independent CFSS/FMS-qualified reviewer**  
Reviewer role/qualification: _____________________  
Date reviewed: _____________________  
Result: [ ] Suitable for a limited *fictional-data* evaluation  [ ] Changes required  [ ] Not suitable  
Blocking issues: _____________________  
Corrective action and evidence: _____________________  

**Production deployment, public customer use, real participant data, subscription or live payments remain separate owner decisions after review.** A green automated test or visual acceptance does not constitute program or legal approval.

## Official review references

- Minnesota DHS, CFSS and lead agencies FAQ: https://mn.gov/dhs/partners-and-providers/news-initiatives-reports-workgroups/long-term-services-and-supports/cfss/cfss-faq-la.jsp
- DHS, FMS documentation and monthly reporting: https://www.dhs.state.mn.us/main/idcplg?IdcService=GET_DYNAMIC_CONVERSION&RevisionSelectionMethod=LatestReleased&dDocName=cfss-001002
- Minnesota Statutes 2026, section 256B.85: https://www.revisor.mn.gov/statutes/2026/cite/256B.85
- DHS, Community First Services and Supports: https://www.dhs.state.mn.us/main/idcplg/001024.doc?IdcService=GET_DYNAMIC_CONVERSION&RevisionSelectionMethod=LatestReleased&dDocName=MNDHS-067912

**AMICOR HEALTH ISF LLC — independent software evaluation only.**
