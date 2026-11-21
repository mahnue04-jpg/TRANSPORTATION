# AMICOR Nova — Unified Agents, Snap Communications, Autopilot and Customer Demo Blueprint
**Owner direction recorded:** 2026-11-21. **Status:** approved product vision and build requirements, NOT implemented or approved for production deployment. 
**Scope:** Nova Snap, Growth Agent, Operations Agent, Work & Revenue Agent, Creative Studio, Nova Workspace/Central Intelligence.

## North star
Nova should operate as ONE customer-facing business platform whose specialized agents can perform meaningful, authorized work end-to-end. Each product also retains a useful standalone workflow. Agents should handle routine operations continuously without repeatedly seeking owner approval; require approval only at clearly defined risk, money, identity, legal, customer-data, irreversible, or high-impact boundaries. "24/7" is target availability/automation, not a claim of verified uptime or permission to spam, charge, or disclose.

## Product roles
| Product | Standalone value | Connected role |
| --- | --- | --- |
| Growth Agent | AI-assisted inquiry intake, answers, consent-based lead capture, booking and follow-up | Qualify prospect and request Snap handoff; create authorized service opportunity |
| Nova Snap | Private opt-in messaging, groups, camera drafts; calls once REAL two-device verified | Common conversation layer and contact channel inside every product; thread linked to lead, appointment, project, or task, not a parallel source of truth |
| Operations Agent | Paid, scoped research/data/admin tasks starting at supervised $49 Starter | Receive exact paid-task authorization; intake file via secure portal; work, review, deliver, report |
| Work & Revenue | Find/qualify external jobs and prepare tracked applications | Surface verified opportunities and route owner-approved outreach through Snap/CRM |
| Creative Studio | Create videos/ads, scripts, voice/captions and customer-facing assets | Accept approved campaign brief; create preview, obtain review, produce customer-approved deliverables |
| Workspace/Central Intelligence | Owner dashboard, approvals, evidence, activity and revenue reports | Orchestration, traceability, policy, shared case/project IDs, visibility into all agent actions |

## Snap placement and UX
1. Primary **Snap / Conversations** entry in Nova Workspace, with inbox, unread alerts, customer/task context, handoff, consent and audit history.
2. Contextual **Message / Request Call / Updates** entry within Growth lead, Operations paid task, Work & Revenue opportunity and Creative Studio project.
3. A consistent thread can reference `tenant_id`, `customer_id`, `lead_id`, `engagement_id`, `task_id`, `studio_project_id`, `appointment_id`, or `opportunity_id`, using scoped references; do not broadcast across tenants or merge unrelated customer identities.
4. Snap is **not** the payment ledger, private artifact store, approval record, marketing bulk-send engine, or a replacement for Synapse. Serve files from the source product's scoped, expiring delivery grants; Snap shows status/authorized link only.
5. Audio/video calling must remain "preview/not live" until successful calls across two independent real devices/networks, mic/camera permissions, decline, hangup, reconnect, and TURN requirements are verified. No silent capture.

## Event and agent coordination (future implementation contract)
- Canonical domain events: `lead.created`, `consent.recorded`, `lead.qualified`, `appointment.booked`, `conversation.handoff_requested`, `quote.prepared`, `checkout.paid_verified`, `task.authorized`, `task.started`, `task.review_ready`, `owner.approved`, `delivery.granted`, `delivery.completed`, `campaign.brief_approved`, `studio.preview_ready`, `followup.due`, `opportunity.qualified`, `application.submission_verified`.
- Every event: unique idempotency key, producer/source, tenant/customer/context IDs, timestamp, actor (human/agent), consent state where applicable, audit record and processing status. Retries/recovery must never duplicate charges, work, outreach, or customer deliverables.
- One supervisory policy/orchestration layer in Nova Central Intelligence routes events to responsible agents. Use existing system-of-record data rather than copying secrets, raw payment data, or private files into Snap.
- Retryable jobs: durable queue, leases, bounded retries, dead-letter/manual recovery, audit and owner visibility. Do not claim always-on until hosted worker and actual recovery verified.

## Autopilot by default: action policy
**Automatically allowed after configured permissions and customer consent:** respond with accurate FAQ/info; tag and score leads; prepare a scope/quote draft; capture inquiries; offer available appointment times; create internal tasks; generate scripts/research drafts; analyze approved non-sensitive files within contracted scope; progress notifications that customers opted into; synthetic/demo jobs; report exceptions to owner.
**Owner/customer approval or separate signed authorization required:** final customer quote/price change outside published offer; application submission or outreach where standing owner approval does not cover recipient, channel or risk; paid provider spend beyond budget; external email/SMS without recipient opt-in; charging/refunding or enabling live subscription; accepting nonstandard legal terms; processing sensitive or regulated personal data without contract/appropriate controls; production deployment/migration; broad access change; release of external-facing creative/claims without review where required; final customer deliverable if review gate applies; destructive/irreversible data changes.
**Hard prohibitions unless separately authorized:** fabrication of qualifications, fake applications/purchases/reviews/metrics, scraping private accounts without permission, unsolicited bulk messaging, cross-tenant data exposure, reuse of a test Stripe paid event for a live customer, bypassing payment/identity checks.
Configurable owner approvals: standing preauthorization for specified low-risk actions, per-action thresholds and exceptions. "Autopilot" is workload automation, NOT unlimited financial or publishing authority.

## Cross-product journeys (build sequentially)
### Journey A: first $49 supervised customer project
1. Growth captures opted-in lead and agreed scope; Snap opens authorized conversation.
2. Operations creates lead-specific checkout; verify signed Stripe webhook, saved session, exact $49 USD payment, customer/tenant/engagement/task binding.
3. Operations accepts authorized input through private portal, executes bounded cleaning/research, holds review output.
4. Owner approves final deliverable; customer accesses a time-limited, customer-bound download; Snap shares status, not raw files.
5. Growth schedules consent-based feedback/referral/follow-up. Central Intelligence records verified revenue and work evidence.

### Journey B: Work & Revenue qualified contract
1. Agent verifies public paid opportunity, capability fit, no application fee and rules of eligibility; records sources and confidence.
2. Draft application/proposal and task; owner review when standing approvals do not cover real external submission.
3. On verifiable submission, store receipt/evidence and status; Snap records approved one-to-one conversation, Growth handles consent-based appointment and follow-up.
4. No claim that discovery equals submission, award or earned revenue.

### Journey C: Creative Studio campaign
1. Owner/customer submits brief with agreed usage rights and brand assets.
2. Creative Studio creates genuine preview, captions, voice and CTA; Snap holds revision conversation.
3. Approved asset published only to owner-authorized channels via connected app; Growth captures new inquiries; Operations handles paid service fulfillment.
4. Capture actual traffic/leads/bookings/sales attribution without fabricated results.

## Customer-facing integrated demo (must prove work, not merely animation)
- **Demo asset 1:** 90–120 second narrated product tour, real screen recordings of verified workflows.
- **Demo asset 2:** 30-second promotional commercial for social.
- **Demo asset 3:** interactive sandbox "Try a sample job" using synthetic lead + small non-sensitive sample CSV, clearly identified as demo, showing: site inquiry → Growth response → Snap thread/handoff → authorized sample task → Operations processing → preview result → owner review → synthetic delivery → dashboard evidence. Include Studio-produced promotional asset and Work & Revenue opportunity card as distinct optional paths, never fake a paid customer or completed application.
- Evidence banner per segment: LIVE / VERIFIED STAGING / SYNTHETIC DEMO / PLANNED. No claims of working live calling, 24/7 guaranteed service, automatic sales, unverified integrations, real revenue or external submission.
- Capture recordings from actual deployed apps when possible; do not use static mockup as proof of working software.

### Draft 30-second commercial story
0–5s: "One business. One Nova workspace." Display customer inquiry.
5–11s: Growth Agent answers and qualifies, Snap carries the conversation.
11–18s: Operations receives an authorized $49 task; show real sample spreadsheet before/after and review status.
18–24s: Creative Studio produces a marketing preview; Work & Revenue tracks a qualified business opportunity.
24–30s: Owner sees approvals, status and evidence in one dashboard. CTA: "Explore AMICOR Nova at getamicor.com." Use "Preview" labels where capabilities are not live.

### Draft 90–120-second demo outline
Problem → single signed-in Workspace → Growth inquiry → Snap handoff → $49 sample scope → payment identity (Stripe **test mode** only) → secured file sample → actual processing output → approval and delivery gate → Studio sample preview → Work & Revenue sourced opportunity with no invented submission → owner dashboard, automation rules and exceptions → CTA. Use human narration/captions and honest feature labels.

## Phased engineering delivery and acceptance
- **P0 preserve current releases:** Operations $49 completion first; Work & Revenue; Growth; Snap; no unrelated feature work that blocks a narrowly approved release.
- **P1 shared identity/context and events:** design tenant-safe, permissions-checked cross-product links; audit schema; implement read-only timeline and Snap thread association behind flags.
- **P2 Growth→Snap→Operations supervised pilot:** prove one synthetic end-to-end flow with idempotency, verified payment identity and private delivery; test tenant isolation and recovery.
- **P3 Growth appointments and consent messaging; Work & Revenue opportunity handoff; Studio script-preview-review handoff.** Honor provider budgets, only real provider integrations after explicit approval.
- **P4 Snap calling and camera:** two physical device/real network checks; TURN cost approval if needed.
- **P5 release evidence and marketing:** acceptance matrix, user experience walkthrough, demo recording, product availability copy, 30-second ad and launch landing page.
**Minimum owner dashboard:** new leads, qualified leads, pending replies, scheduled calls, task/payment binding status, completed deliveries, qualified opportunities, verified submissions, completed studio assets, real revenue, blockers, approvals and audit evidence.
**Minimum acceptance:** customer/tenant isolation; precise role and consent boundaries; no duplicate payments/tasks/messages; failure/restart recovery; owner approvals honored; real hosted end-to-end journey verified; rollback plan; accurate marketing claims.

## Owner decisions and non-authorization
This blueprint is a durable product/build requirement, not authorization to merge/deploy, turn on production/live billing, purchase TURN/AI/SMS providers, send external outreach, migrate shared databases or expose customer media. Seek owner approval at actual risk gates. Respect active AMICOR budget limits. Keep legacy product functionality intact, and do not block currently approved Operations $49 launch with Snap integration scope.
