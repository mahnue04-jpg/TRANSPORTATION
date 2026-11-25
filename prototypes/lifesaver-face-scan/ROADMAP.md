# Nova Lifesaver: Smartphone-first / Home Hub later — Engineering contract

Status: RESEARCH PROTOTYPE ONLY (not clinical, not approved for launch)
Related: issue #348, draft PR #349

## Owner-approved product direction
Implement and validate the smartphone workflow first. Build a common domain/data contract that can later be shared with a Home Hub adapter. Do not imply that a phone camera and Home Hub camera have identical accuracy or hardware capabilities.

## Phase 1 — smartphone
- User-initiated opt-in camera permission, start/stop, denied-permission and device-incompatible states.
- Local camera preview and lighting feedback only (already present in prototype). **No real vital measurements yet**.
- Device coverage: iOS Safari, Android Chrome, laptop Chrome/Firefox where available. Test consent withdrawal, tab switching, backgrounding, reload, loss of permissions, and camera busy.
- Research rPPG with commercially usable license and security review before integration. Pulse/breathing values must remain unavailable until validated, not randomly simulated as real.
- Diverse participant/device/lighting tests with informed consent and reference measurements; define acceptance metrics with clinical advisor. Do not collect face video or PHI by default.
- Accessibility and localization; camera not required for basic product navigation.

## Shared domain contract — conceptual, not deployed API
Each future observation includes:
- observation_id, subject pseudonymous ID, timestamp with timezone
- source: phone_camera | home_hub_sensor | manual
- measurement_type, unit, value only when independently validated
- quality state: unsupported | insufficient_signal | experimental | validated
- method/version and optional reference-validation metadata
- consent scope and retention metadata

Never promote experimental estimates to clinical truths; existing Lifesaver observation-quality and AI-provenance safeguards must reject invalid, missing, stale or simulated data from clinical summaries.

## Phase 2 — shared Lifesaver architecture
- Shared event schemas, local privacy controls, authenticated sync only when user opts in.
- No cloud video upload in baseline. Explicit consent, role-based access, encryption, retention policy and account deletion testing required before sync.
- Separate wellness insights from any alert or emergency workflow.

## Phase 3 — Home Hub adapter
- Verify actual hardware capability, camera processing, sensor certifications and offline power handling.
- Reuse domain rules and visual patterns, but use device-specific capture and permissions.
- Establish recovery, no-network state, and physical safety testing.
- No assumption of identical binaries or measurement accuracy across hardware.

## Blockers & release gates
- Phone and Home Hub **not yet validated on hardware**.
- Face Scan rPPG and breathing **not implemented**.
- Medical, biometric, child-protection and HIPAA applicability require qualified review, as does FDA intended use.
- Release only after security and mobile acceptance evidence, independent measurement validation where claimed, and explicit owner approval.
- Never edit production website, deploy or acquire paid dependencies under this draft work.

## Phase 1 smoke test checklist
- [ ] iPhone Safari on secure origin: no camera before consent
- [ ] Decline browser permission: actionable feedback and no lingering tracks
- [ ] Consent and start: front-camera preview and lighting feedback
- [ ] Stop: all tracks ended and preview cleared
- [ ] Withdraw consent while running: tracks ended immediately
- [ ] Switch tab or lock screen: tracks stopped and state reset
- [ ] Navigate away/reload: tracks stopped
- [ ] Start->Stop->Start: no stale handle or duplicate streaming
- [ ] Permission revoked / camera busy: safe errors and recovery
- [ ] Android Chrome equivalent flows
- [ ] Verify no external requests, analytics, video uploads, storage, or biometrics
- [ ] Check dark/light/uneven lighting and different skin tones for UX fairness
- [ ] Accessibility: keyboard, labels, screen reader announcements
- [ ] Evaluate securely licensed rPPG candidate *separately* before adding any measured number

Next implementer: add automated browser-level permission/cleanup tests, then a phone test report; keep PR draft pending review.
