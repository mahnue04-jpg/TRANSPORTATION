# AMICOR Nova Intelligence Workspace — Product and Launch Definition

**Status:** working name and positioning approved by owner on 2026-10-23. Product is NOT yet implemented or generally available. Do not publish purchase CTAs or claim regulated compliance before release gates.

## Name and identity
- Customer-facing name: **AMICOR Nova Intelligence Workspace**
- Short name: **Nova Intelligence**
- Tagline: **From recordings and documents to reviewed work.**
- First entry point: a distinct **Analyze Video** workflow connected to (not replacing) Nova Creative Studio's Create Video.
- Customer promise: permissioned uploads of non-sensitive business media; timestamped understanding and source-grounded notes; human-approved task and follow-up drafts.
- Avoid claims of autonomous diagnoses, surveillance conclusions, unrestricted streaming/video access, verified languages, guaranteed savings, or completed security certifications.
- Distinguish from generic transcription by linking media understanding → reviewed Operations Agent workflow → trackable customer deliverable. Real differentiated value must be measured in pilots.

## Phase 0 — protect current launch
1. Keep existing 30s Creative Studio render, checkout, downloadable MP4 and mobile verification as separate P0 work. Do not regress the 60s demo.
2. Inspect existing provider keys/usage without printing secrets. Maintain paid generation flags OFF until cost approval and reproducible test.
3. Do not promote or take payment for new Intelligence features before successful real test.

## Phase 1 — first 2 weeks (estimate, not commitment)
- Wireframe Analyze Video as disabled/coming soon; non-PHI, authorized uploaded MP4 first, not arbitrary streams.
- Backend async job API with owner/tenant auth, upload quota, validation, SSRF controls for future URLs, retention, audit logs, timestamped frames and transcripts.
- Reuse OCR service; provider-agnostic STT with optional diarization. No facial identification, automated correctional risk scores.
- Demonstrate real 2-minute synthetic meeting video → transcript + on-screen text + citations + reviewer task draft.
- Cost usage log per job; automatic budget ceilings and no-billing fallback.

## Phase 2 — 3–6 weeks (estimate)
- Studio review screen / correction of transcript, timestamp seeking, downloadable text/PDF report (after testing).
- Operations Agent supervised media-to-tasks, reply draft, and user approval checkpoints.
- Work & Revenue sample report generation, qualified lead tracking, follow-up drafts and verified-stage pipeline (lead ≠ submitted ≠ paid).
- Acceptance: secure test suites, no cross-tenant leakage, actual browser/mobile demonstration, traceable source timestamps, usability measures.

## Phase 3 — Lifesaver and regulated industries
- Lifesaver: separate privacy and clinical risk gates; accessible food-label reading, general nutrition education, nonclinical caregiver notes based on informed consent. No diagnosis, clinical alarm, or emergency claim.
- Clinical coding/FHIR/HL7/EHR sandbox only with synthetic data; HIPAA assessment + BAAs and patient consent before any PHI.
- Institutional admin pilots with synthetic documents; agency security requirements/CJIS assessment before any CJI. No individual security risk scoring or punitive decisions.

## First customers and promotion
- Offer three sample use cases: meeting→tasks; training video→searchable steps; consented business support call→action summary.
- Landing page with working video/demo, documented limitations, non-sensitive sample intake, and verified links to getamicor.com.
- Initial 20 discovery calls, aim 10 demo requests, 5 consented non-sensitive pilots, 2 paying pilots; these are GOALS not real outcomes.
- Direct email/outreach and professional social demos first; ads only after conversion and landing-page QA; approve campaigns before spend.
- Measure time saved against baseline, human correction rate, transcript WER, hallucination rate, source timestamp precision, cost/clip, conversion and actual collected revenue.

## Owner budget decision gates
- $0 planning/local synthetic tests using existing resources if possible.
- For transcription/vision APIs choose an initial **proposed maximum $25 total experimental usage** only after reviewing provider quotes; require explicit owner confirmation before new purchases/top-ups or enabling billing.
- Hosting, encryption, security and compliance costs may vary; request exact estimates before commitment.

## Weekly governance
Friday ~9am America/Chicago weekly review already scheduled through ChatGPT: PRs, tests, deployment, costs, demand, blockers. Scheduling a review does NOT schedule unattended GitHub coding.

## Source of truth
Issues #369 and #371, PR #370. Track separately design, implemented, tested, deployed, purchased and compliant.