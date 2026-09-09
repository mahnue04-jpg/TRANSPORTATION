# Driver 001 — deferred blockers

**Status:** Frozen verified draft. Do not resume the onboarding repair cycle until explicitly authorized.

Verified state (2026-09-09):

- Existing application remains `DRV-001` (`ed17c75c-04ec-407a-aba6-a48988d5051c`).
- Resume and applicant-token authorization work.
- Agreement signature, tax information, vehicle, and documents remain preserved.
- Payout remains not started. Stripe stays TEST. Do not create a Connect account in TEST.
- Application remains draft, unapproved, and inactive.
- Do not ask the applicant to acknowledge attorney-draft policies.

## Deferred

| ID | Blocker | Why deferred |
|---|---|---|
| D001-1 | Attorney review and replacement of the draft contractor agreement (`AMICOR-ICA-2026.1`) | Legal, not an engineering rewrite |
| D001-2 | Attorney review and publication of the 10 driver policies | Legal; do not collect acknowledgments on drafts |
| D001-3 | Stripe LIVE credentials and Connect configuration | TEST only until LIVE is explicitly authorized |
| D001-4 | Stripe Connect webhook registration and verification | Completes payout status without relying only on return/refresh |
| D001-5 | Final document review, submission, approval, and activation | After legal + LIVE payout readiness |

Do not submit, approve, activate, create a Health ISF driver, or start Freight work from this backlog.
