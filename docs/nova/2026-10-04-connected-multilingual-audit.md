# Nova connected modules and multilingual audit — 2026-10-04

Production target: `amicor-health-isf-py.onrender.com`, Render service `srv-d8v1bl1kh4rs73d54lh0` in the user-selected Saye workspace. Live revision `36cf5f50a5f3ac9d03a0999c5e7eb6ba291e5dfa` (PR #239). PR #240 is open, not deployed to that service.

## Findings and changes

- Ask Nova Today now consumes the Work & Revenue / Operations intake snapshot for relevant owner questions. The same existing Work & Revenue owner and SaaS exclusion gate runs before adding that data. Work opportunities are scoped to current organization and owner. Operations marketing intake is platform-owned intake, not tenant-owned execution history.
- Includes PR #240's owner coordination API and post-commit approval notifications. Actual SMTP configuration/delivery remains unverified.
- The public Operations Agent is a supervised request intake and sandbox demonstration. It is not evidence of autonomous fulfillment or two executing agents exchanging task outcomes.
- Fixed a Government-to-Today server error: `proposed` is not a permitted verification result; the response now uses `unknown`.
- Corrected double-escaped Government text extraction regexes (whitespace, boundaries, HTML block removal). Added service-level HTTPS .gov validation and explicit applicability warning.
- Added a shared language preference for Ask Nova and module brain forms, microphone locale, matching browser voice selection, and an Operations request language preference.
- Explicit reply-language preferences are removed before source querying. Translation masks and restores numeric facts, URLs and record identifiers, retains response metadata, and returns the original with an availability notice on failure.
- Language choices: English, Spanish, French, Portuguese, Arabic, Chinese, Hindi, German, Swahili, Somali and Hmong. These choices are not certification of fluency or browser voice availability. Interface labels, source documents, direct sandbox demonstration copy, and structured action labels are not fully localized. Creative Studio presenter voice language is not changed in this patch.

## Validation and limitations

The unchanged main branch audit ran 223 checks across Core, Government, Business, Communications, Workspace, Accounting, Aging, Trends, Today, Work & Revenue and public marketing intake: 187 passed, 35 failed, 1 fixture error. Failures include stale navigation/layout expectations, outdated mocks (`require_domains`), invalid SaaS test constructors, missing test fixtures, and behavioral expectations needing review.

The expanded patched run returned 197 passed, 32 failed and 1 fixture error. One failure newly exposed by cache versioning was subsequently corrected in the test's asset-path assertion and rechecked separately. No remaining failure ID was new relative to main after that correction. The suite is still red and this change is not an end-to-end certification.

Focused checks cover current-owner/current-organization handoff isolation, customer exclusion before handoff prompt construction, translation preserving evidence, translation failure fallback, post-commit/rollback owner notification behavior, the Government-to-Today crash, and .gov source validation. JavaScript tests verify Spanish voice selection, missing-voice refusal and invalid-locale fallback. Repository build and lint passed; TypeScript check reports no configured tsconfig and skips compilation.

Live read-only observations: Nova Today renders but this browser has no signed-in owner session. Render reports deployment live, memory approximately 241.7 MB of 536.9 MB (~45%), low idle CPU, no error-level logs since the current deployment (queried from 2026-10-03T17:42:49Z). No HTTP latency series was available. Older logs show external search timeouts and a D-ID audio request error; these are historical, not proof that they persist in the current release.

## Remaining release work

1. Reconcile remaining stale/invalid tests without weakening access, evidence or capability contracts; investigate any genuine failures.
2. Obtain a signed-in owner session and test source loading, saved-record create/read/update, Ask Nova handoffs, tenant isolation and owner notification configuration end to end.
3. Test real text translation and actual listening/playback on target devices for supported languages; do not claim all-language fluency.
4. Verify approved Operations fulfillment and status reporting separately from public intake.
5. Merge/deploy only after readiness checks are complete, then repeat the signed-in workflow checks on production. Production uses manual deployment.
