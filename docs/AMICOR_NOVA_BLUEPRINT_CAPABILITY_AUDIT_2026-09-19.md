# AMICOR Nova Blueprint Capability Audit — 2026-09-19

This audit compares the intended Nova assistant experience with the capabilities currently present in the TRANSPORTATION repository.

## Intended Nova assistant experience

Nova is intended to act as the AMICOR central intelligence and orchestration assistant: conversational memory, live information retrieval, web/search, voice, work/revenue automation, files/tools, business/government support, and later creative production such as image and video generation.

## Current capability status

| Capability | Status | Current implementation / gap |
|---|---|---|
| Durable user identity memory | WORKING | Nova Today stores/retrieves the signed-in user's remembered name on the platform account, with Nova per-user memory as supplemental state. |
| Voice input | WORKING | Browser SpeechRecognition/webkitSpeechRecognition on Nova Today. |
| Spoken replies | WORKING | Browser speechSynthesis with selectable natural browser voice where available and Stop control. |
| Weather | WORKING | Live Open-Meteo lookup from Nova Today. |
| News | WORKING | Live Google News RSS briefing with cleaned output. |
| General web search | INTEGRATION IN PROGRESS | Existing app.web_search provider chain already supports Tavily when configured, DuckDuckGo, and Wikipedia. Nova Today is being wired to this existing search system with clickable sources. |
| Open common websites | INTEGRATION IN PROGRESS | Nova Today is being wired to safe links for YouTube and common social platforms. |
| Clickable source links | INTEGRATION IN PROGRESS | Nova Today answer schema/UI is being extended to render clickable live sources. |
| Live job discovery | WORKING | Nova V3 live discovery, ranking, and opportunity save flow are present. |
| Master Work Profile / tailored resumes | INTEGRATION IN PROGRESS | PR #53 adds reusable owner-approved facts and job-specific application materials. |
| External job submission | NOT YET LIVE | Application preparation exists. Controlled submission adapters/connectors still require final implementation and testing; CAPTCHA, login, signature, and identity-sensitive steps remain owner-controlled. |
| Image generation | NOT IMPLEMENTED IN CURRENT REPO | No current Nova image-generation provider/endpoint found. Requires a dedicated Create Studio/image provider integration. |
| Video generation | NOT IMPLEMENTED IN CURRENT REPO | No current Nova video-generation provider/endpoint found. Requires a dedicated Create Studio/video provider integration. |
| Create Studio | BLUEPRINT / NOT YET IMPLEMENTED HERE | Intended for image, video, voice, presentation, email, and marketing creation. |
| Blueprint Studio | BLUEPRINT / NOT YET IMPLEMENTED HERE | Intended to coordinate product construction plans, hardware/software plans, and supervised integrated development. |
| Owner-only Work & Revenue | WORKING / VERIFY IN UI | Backend protects Work & Revenue from Nova SaaS customer orgs and restricts it to configured AMICOR owner emails. |

## Immediate build order

1. Finish Nova Today general web search and clickable source links.
2. Verify web queries such as:
   - "Can you search the web?"
   - "Look up the latest movie playing today."
   - "Open YouTube."
   - "Search the web for [topic]."
3. Deploy and validate PR #53 Master Work Profile.
4. Run one real live job through discovery → saved opportunity → tailored resume/application package → owner review.
5. Complete controlled external submission adapters where permitted.
6. Complete Stripe production-readiness audit before enabling live billing.
7. Build Create Studio image generation.
8. Build Create Studio video generation.
9. Expand Blueprint Studio / product-construction orchestration.

## Safety / trust boundaries

- Nova should never invent credentials, work history, licenses, certifications, references, or financial facts.
- Live web answers should show source links.
- External writes, submissions, payments, filings, signatures, or sensitive account actions remain approval-controlled until explicitly validated.
- Customer accounts must not see owner-only Work & Revenue or administrative records.
