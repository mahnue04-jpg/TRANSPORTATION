# AMICOR Nova Core V1 — Production Freeze

**Date:** 2026-09-09  
**Software status:** **SAFE TO FREEZE**  
**Stripe mode:** TEST only (LIVE not enabled)  
**Driver 001:** Untouched  
**AMICOR Delivery:** Remains frozen  
**AMICOR Health:** Unchanged; existing `/workspace` remains Health ISF  
**AMICOR Nova Freight V1:** Remains SOFTWARE FROZEN separately  

**AMICOR NOVA CORE V1 SOFTWARE BUILD FROZEN**

No further Nova Core V1 code changes unless required by:

1. a verified production bug  
2. a security issue  
3. a data-integrity issue  
4. a legal/compliance requirement  
5. a launch-critical correction  
6. explicitly authorized V2 work  

Do not silently expand V1.

---

## V1 architecture

Nova Core V1 is a Nova-owned product layer on the shared FastAPI / Render service `amicor-health-isf`.

Mrs. Nova Brain is the single intelligence layer. Home, Workspace, Communications, Government, and Business are linked product surfaces, not merged databases.

| Surface | UI | API | Tables |
|---------|----|-----|--------|
| Home | `/nova` | `/api/nova/*` (existing ask/status/search) | existing Nova core memory/status |
| Workspace | `/nova/workspace` | `/api/nova/workspace` | `nova_workspace_*` |
| Communications | `/nova/communications` | `/api/nova/communications` | `nova_communications_*` plus existing local email/calendar records |
| Government | `/nova/government` | `/api/nova/government` | `nova_government_*` |
| Business | `/nova/business` | `/api/nova/business` | `nova_business_*` |

Products remain linked, not merged:

- Health `/workspace` stays Health ISF
- Delivery stays `/app` + frozen ops-shell
- Freight stays `/nova/freight*` and `nova_freight_*`

---

## Routes

### Nova Core UI

- `/nova`, `/nova/`, `/nova/home`
- `/nova/workspace`
- `/nova/communications`
- `/nova/government`
- `/nova/business`

Nova Home is the central Nova entrance. All Core hubs link back to Home, Workspace, Communications, Government, Business, Web/Search, Files, Voice, Tools, Health, Delivery, and Freight.

### Adjacent products (not Core V1)

- `/workspace` — Health ISF Workspace
- `/app` — Delivery
- `/nova/freight*` — Freight V1 (separately frozen)

---

## Database boundaries

Nova Core tables are Nova-owned. Do not put Core records into Health, Delivery, or Freight schemas.

- Workspace: projects (`NW-`), files (`NWF-`), conversations (`NWC-`), activity
- Communications: messages, notifications; drafts/events reuse existing local stores
- Government: work items (`NG-`), checklists (`NGC-`), sources (`NGS-`), programs (`NGP-`)
- Business: profiles (`NB-`), customers (`NBC-`), opportunities (`NBO-`), tasks (`NBT-`), vendors (`NBV-`), documents (`NBD-`), expenses (`NBE-`), meetings (`NBM-`), activity (`NBA-`)

Business and Government reference Workspace/Communications/Government IDs. They do not copy those records into a second store.

---

## Mrs. Nova Brain architecture

Display name is exactly **Mrs. Nova Brain**.

One intelligence layer. Surfaces call existing Nova ask APIs:

- Home: `/api/nova/ask`
- Workspace: `/api/nova/workspace/ask`
- Communications: `/api/nova/communications/ask`
- Government: `/api/nova/government/ask`
- Business: `/api/nova/business/ask`

Do not create another assistant or competing brain.

---

## Trust-label system

Standard labels across Core surfaces:

- **VERIFIED DATA**
- **USER-SAVED INFORMATION**
- **AI SUGGESTION**

Government source/evidence may additionally identify:

- **OFFICIAL SOURCE**
- **CONFIRMED IN WRITING**
- **EXPIRED OR SUPERSEDED**

AI output is not an official government ruling. User-entered information is not verified fact without evidence.

---

## Workspace

Nova-owned projects, files, conversations, activity, search, recent work, and Mrs. Nova Brain.

File bytes stay in existing upload services. Workspace stores metadata and references only.

Health `/workspace` was not converted.

---

## Communications

Inbox/reference views, drafts, local calendar, contacts, notifications, voice/TTS, Mrs. Nova assistance.

External send remains behind explicit `confirm_send` plus `NOVA_COMMUNICATIONS_ALLOW_SEND=1`. Tests never send mail. No autonomous calling. No OAuth/password/secrets in the UI.

---

## Government

Organization, discovery, research, documents, deadlines, and assistance only.

Work items, jurisdictions, deadlines/renewals, checklists, grant/funding organization, licensing/compliance tracking, source/evidence, verification statuses, Workspace and Communications links.

Does **not** submit filings, pay government fees, impersonate agencies, claim AI guidance is an official ruling, or autonomously email agencies.

---

## Business

Operations organization: profiles, customers, opportunities, pipeline, tasks, documents/contracts, vendors, meetings, follow-ups, informational expenses, revenue forecasting, Government/Communications references, activity timeline.

Expense records are labeled **Operational Expense Tracking — NOT Accounting**.

No general ledger, journal, chart of accounts, bank reconciliation, payroll, tax engine, 1099 processing, LIVE Stripe wiring, or autonomous sales outreach.

---

## Security and tenancy

Preserved:

- JWT
- AmiCorSession
- `require_nova_access`
- `organization_id` scope
- role protections
- owner isolation for non-admin users

Cross-organization reads/writes fail (403). Reference IDs cannot bypass tenancy. Browser payloads must not include Stripe secrets, passwords, OAuth tokens, raw filesystem paths, or other-tenant data.

---

## Product isolation

Phases 1–6 did not change:

- Freight business logic, schemas, payout, settlement, remittance
- Delivery ops-shell or payment flow
- Driver 001
- Health lifecycle, billing, onboarding
- Health `/workspace`

---

## Known limitations

- Government is not connected to live agency systems
- Communications send is disabled unless explicitly enabled
- Business pipeline is operational forecasting, not booked revenue
- Expenses are informational, not accounting
- No hardware controls
- Stripe remains TEST only

---

## Master regression (2026-09-09)

Launch-critical suite: **119 passed, 0 failed, 0 skipped**.

| Suite | Result |
|-------|--------|
| Nova Home, Workspace, Communications, Government, Business, Core V1 freeze, Core intelligence, shell/UAT | 66 passed |
| Freight Phase 7 + shipments, Delivery branding, Health live/readiness | 49 passed |
| Health onboarding isolation | 4 passed |

Separately documented, **not** part of the freeze gate:

`test_health_isf_revenue_pilot_smoke.py` — **1 failed**. Test expects dispatcher approve → `approved`. Live Health behavior returns `dispatchable`.

This mismatch is **pre-existing**, is **not caused by Nova Core V1**, and **does not block** Nova Core V1 freeze. Health must not be modified merely to satisfy that assertion.

---

## Future V2 / V3 items — document only

Do not build in this freeze:

- accounting, general ledger, bank reconciliation
- payroll, tax, 1099
- advanced CRM automation
- autonomous outreach or calling
- payment automation
- live government system integrations
- physical Nova hardware
- rotating-base hardware controls
- camera, QR/barcode, NFC, Bluetooth
- dock mode, vehicle mode

These require later explicit authorization.

---

## Hardware future boundary

Core UX is prepared for phone, ~10-inch, ~15-inch, ~20-inch, and desktop displays. Rotating-base Nova hardware is a future approved program. This freeze does **not** implement hardware controls.
