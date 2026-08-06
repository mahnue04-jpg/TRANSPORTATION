# AMICOR Website Phase 2 — Release Notes

**Status:** Complete (committed and pushed; not deployed in Phase 2 finalize)  
**Commit:** `502a4c10a08bf3cb11a73163b7eb5477bf456b5b`  
**Commit message:** `feat(marketing): Phase 2 provider and driver conversion website`  
**Branch:** `main`  
**Repository:** `https://github.com/mahnue04-jpg/TRANSPORTATION.git`  
**Company:** AMICOR HEALTH ISF LLC

---

## Summary

Phase 2 upgraded the public AMICOR marketing website into a conversion-focused site for provider partnerships and driver recruitment, while preserving all existing ride, dispatch, billing, authentication, admin, provider portal, driver app, API, and `/workspace` functionality.

No ride-engine, dispatch, billing, or auth business logic was changed. Marketing lead capture was added as an isolated module.

---

## Public Pages

| Page | Route | Phase 2 focus |
|------|-------|----------------|
| Home | `/` | Trust section added; existing hero/CTAs retained |
| About | `/about` | Unchanged content; shared shell/SEO upgrades |
| Services | `/services` | Unchanged content; shared shell/SEO upgrades |
| For Providers | `/for-providers` | Full conversion rebuild |
| For Drivers | `/for-drivers` | Full conversion rebuild |
| Contact | `/contact` | API-backed form with consent |
| Privacy | `/privacy` | Placeholder legal page (shared shell/SEO) |
| Terms | `/terms` | Placeholder legal page (shared shell/SEO) |

### Preserved platform routes (not replaced)

| Route | Behavior |
|-------|----------|
| `/workspace` | Health ISF / Nova app shell |
| `/app/*` | Ops shell (dispatch, riders, providers, mobile, etc.) |
| `/providers`, `/drivers` | Legacy redirects to `/app/providers`, `/app/drivers` |
| `/platform-ops/driver-apply` | Existing driver application |
| `/admin` | Admin dashboard |

---

## For Providers (`/for-providers`)

Conversion page for hospitals, clinics, behavioral health, assisted living, skilled nursing, dialysis centers, and county/community organizations.

**Sections**
1. Hero — Minnesota provider headline, consultation + workspace CTAs  
2. Why Providers Choose Amicor — six benefit cards (no unsupported HIPAA/Medicaid/insurance claims)  
3. How It Works — four-step request → complete workflow  
4. Provider Use Cases — appointments, behavioral health, dialysis, discharge, senior/disability, recurring treatment  
5. Shared trust section  
6. Provider FAQ (with matching FAQ schema)  
7. Provider Interest Form

**Primary CTAs**
- Request a Provider Consultation → `#provider-interest-form`
- Access Provider Workspace → `/app/providers`

---

## For Drivers (`/for-drivers`)

Driver recruitment page with careful, non-guaranteed benefit wording.

**Sections**
1. Hero — purpose-driven headline  
2. Driver Benefits — flexible opportunities, tech coordination, clear trip info, earnings visibility, community service, independent work (subject to agreement)  
3. Basic Eligibility — license, record, vehicle, registration, insurance, smartphone, background screening, professional assistance  
4. Onboarding Process — five steps from application to approved trips  
5. Shared trust section  
6. Driver FAQ (with matching FAQ schema)  
7. Final CTA band

**Primary CTAs**
- Start Driver Application → `/platform-ops/driver-apply`
- Driver Login → `/app/mobile`

---

## Shared Trust Section

Heading: **Transportation Coordination Built Around Care**

Included on:
- Home (`/`)
- For Providers (`/for-providers`)
- For Drivers (`/for-drivers`)

Items: Minnesota-based company; secure account-based platform; real-time trip coordination tools; provider/driver/operations workspaces; documented trip workflow; human support backed by technology.

---

## Backend Changes (Isolated Marketing Module)

New package: `backend/app/modules/marketing/`

| File | Purpose |
|------|---------|
| `__init__.py` | Module marker |
| `models.py` | `MarketingWebsiteLead` ORM + `ensure_marketing_schema()` |
| `schemas.py` | Request validation for lead payloads |
| `routes.py` | Public lead-capture API |

**Table:** `marketing_website_leads`  
- Bootstrap via targeted `create_all` (does not alter ride tables)  
- Stores provider/contact interest submissions only

**Registration:** router included from `backend/app/main.py` without coupling to Health ISF ride routes.

---

## API Endpoints

### `POST /api/marketing/leads`

Accepts public website lead submissions.

**Lead types**
- `provider_interest`
- `contact`
- `driver_interest` (schema-ready)

**Provider interest fields**
- Organization name, contact name, work email, phone  
- Organization type, estimated monthly rides, service area  
- Transportation needs, preferred contact method  
- Consent (required)

**Protections**
- Server-side validation  
- Honeypot field (`website`) — silent spam filter  
- Basic IP rate limiting  
- Consent required for provider/contact submissions

**Related discovery endpoints**
- `GET /robots.txt`
- `GET /sitemap.xml`

---

## Forms

| Form | Location | Backend |
|------|----------|---------|
| Provider Interest Form | `/for-providers` | `POST /api/marketing/leads` (`provider_interest`) |
| Contact Form | `/contact` | `POST /api/marketing/leads` (`contact`) |

Front-end handling in `backend/static/marketing/site.js`:
- Client validation and accessible error messages  
- Success/error status regions  
- Honeypot field  
- Consent checkbox  

Driver applications continue to use the existing `/platform-ops/driver-apply` flow (not the marketing lead API).

---

## SEO & Technical Improvements

- Unique page titles and meta descriptions  
- Canonical URLs  
- Open Graph / Twitter card metadata  
- Organization JSON-LD (confirmed company facts only)  
- FAQPage JSON-LD on provider and driver pages (matches visible FAQ content)  
- Accessible heading structure (single `h1` per page)  
- Keyboard-accessible navigation and forms  
- Mobile menu behavior  
- `robots.txt` and `sitemap.xml`  
- Official AMICOR logo and blue/teal/green brand system retained  

---

## Frontend / Static Assets

Primary location: `backend/static/marketing/`

| Asset | Role |
|-------|------|
| `_head.html`, `_foot.html` | Shared shell (nav/footer) |
| `_trust.html` | Shared trust block |
| `home.html`, `about.html`, `services.html` | Page bodies |
| `providers.html`, `drivers.html`, `contact.html` | Conversion/contact bodies |
| `privacy.html`, `terms.html` | Legal placeholders |
| `site.css`, `site.js` | Styles and form/nav behavior |
| `phase2-screenshots/` | Approval screenshots |
| `phase2-final-qa/` | Final visual QA viewport captures |

Shell assembly and marketing routes live in `backend/app/main.py`.

---

## QA Results

### Final Visual QA
- Evidence: `backend/artifacts/PHASE2_FINAL_VISUAL_QA.json` (local; gitignored)  
- Script: `backend/scripts/phase2_final_visual_qa.py`  
- Result: **PASS** — 0 FAIL, 0 WARNING  
- Closing line: **PHASE 2 APPROVED — READY FOR COMMIT.**

### Verified
- All marketing routes HTTP 200  
- `/workspace` and app routes preserved  
- CTA destinations correct  
- Provider and contact forms succeed via API  
- Driver Apply → `/platform-ops/driver-apply`  
- Provider Workspace → `/app/providers`  
- Driver Login → `/app/mobile`  
- No JS console errors in QA run  
- Mobile (390), tablet (768), desktop (1440) layouts checked  
- Favicon and logo assets load  

---

## Git Finalize

| Item | Value |
|------|-------|
| Commit hash | `502a4c10a08bf3cb11a73163b7eb5477bf456b5b` |
| Short hash | `502a4c1` |
| Branch | `main` |
| Push | Successful (`729491e..502a4c1  HEAD -> main`) |
| Render deploy | **Not performed** in Phase 2 finalize |

---

## Assumptions / Open Items

- Marketing forms persist leads to the database; outbound email notification is not yet configured.  
- Privacy Policy and Terms of Use remain placeholders pending counsel-approved language.  
- No public street address or phone number published (not confirmed for marketing use).  
- Production Render deploy of Phase 2 was intentionally deferred after GitHub push.

---

## Local Review URL (development)

When running the app locally:

- Home: `http://127.0.0.1:<port>/`  
- Providers: `http://127.0.0.1:<port>/for-providers`  
- Drivers: `http://127.0.0.1:<port>/for-drivers`
