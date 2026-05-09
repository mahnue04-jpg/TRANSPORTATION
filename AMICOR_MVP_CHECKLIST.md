# AMICOR MVP CHECKLIST

Use this as the required go/no-go checklist for MVP readiness.

## A) Core Product Reliability
- [ ] Backend starts cleanly with no fatal errors in production mode.
- [ ] Frontend `/app` loads with no fatal console/page errors.
- [ ] `/api/health` returns 200.
- [ ] `/api/health/detail` returns healthy in target environment.
- [ ] Startup validation script passes in deployment environment.

## B) Authentication & Session
- [ ] User signup works end-to-end in live product.
- [ ] User login works end-to-end in live product.
- [ ] User logout works and invalidates local/session state.
- [ ] Session restore after refresh works for authenticated user.
- [ ] Expired session handling is explicit and user-friendly (redirect + message + re-auth path).

## C) Conversation Experience
- [ ] User can send message and receive assistant response reliably.
- [ ] Streaming/typing feedback is visible and accurate.
- [ ] In-flight request cancel/interruption is available and works.
- [ ] Conversation persists and restores after refresh for same user/session.
- [ ] Error state includes retry path that succeeds when backend recovers.

## D) Memory Guarantees
- [ ] Session memory saves reliably during conversation.
- [ ] Retrieval uses relevant prior context in response flow.
- [ ] User-scoped memory is isolated (no cross-user leakage).
- [ ] Reset/clear memory action works and is reflected in UI state.

## E) Workflow Experience
- [ ] Workflow can be started from UI.
- [ ] Workflow timeline/progress states are visible to user.
- [ ] Workflow state updates are reflected in real time.
- [ ] Retry/cancel/recovery paths are user-accessible and functional.
- [ ] Failed workflow shows clear error reason and next action.

## F) Tool Runtime Safety
- [ ] Safe tools execute successfully from user prompts.
- [ ] Tool activity is visible in UI.
- [ ] Permission enforcement is validated for restricted operations.
- [ ] Tool failures surface actionable recovery options.

## G) File & Document Flow
- [ ] Upload button + drag/drop work in target browsers.
- [ ] Supported file types are processed correctly.
- [ ] Invalid file types are rejected with clear message.
- [ ] Oversized files are rejected with clear message.
- [ ] Upload retry path works and does not duplicate state.

## H) Capability Readiness
- [ ] Document workflow is complete and deterministic.
- [ ] Task workflow is complete and deterministic.
- [ ] Business summary workflow meets expected output quality.
- [ ] Report generation workflow is structured and reliable.
- [ ] Research assistant workflow handles missing API keys gracefully and succeeds when configured.

## I) Test & Deployment Gates
- [ ] `npm test` passes.
- [ ] `npm run test:production` passes.
- [ ] `npm run test:auth` passes.
- [ ] `npm run test:conversation` passes.
- [ ] `npm run test:capabilities` passes.
- [ ] `npm run test:deployment` passes.
- [ ] Cross-platform health check command(s) documented and validated.

## J) UX Quality Bar
- [ ] No broken primary buttons in core user journey.
- [ ] Loading states present for all network-bound actions.
- [ ] Mobile layout is usable at 375px width and common device sizes.
- [ ] Empty/error/offline states are understandable and actionable.
- [ ] Onboarding and first-use path are clear and skippable.

## MVP Decision Rule
MVP-ready only when:
- All Critical/High items from the latest audit are closed.
- All sections above are checked.
- Final smoke run in production-like environment passes without regressions.
