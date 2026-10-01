# Nova Workspace and Business: discovery routing and status evidence

## Confirmed causes

Workspace and Business sent owner requests such as “Find suitable revenue-ready jobs and prepare applications” and “Find clients for Nova Anonymous Operations Agent” directly to the founder advisor. Nova Today already had dedicated job and client discovery/preparation paths, but these pages did not call them. The advisor received platform setup context instead of actual search results.

Core context also converted Health ISF readiness into a fixed 48/61/72 percent build estimate (plus a production-status bonus). This was not measured completion. Legacy seed memory supplied “MVP stabilization”, “foundation-in-progress”, “staging-validation-pending”, and a generic recommended next step. Zero alert/workflow counts produced an overall “stable” health statement without infrastructure health evidence.

## Changes

- Explicit job and Nova Operations Agent client discovery requests from Workspace/Business now use the existing Today workflow, after the same Work & Revenue owner/SaaS access check. Workspace continues saving its conversation.
- Both responses preserve discovery trust labels and source links. Both pages render those links and the Work & Revenue review link.
- Discovery failures remain honest unavailable results; they do not fall back to generic setup advice. Fix an invalid `proposed` verification status in the existing client-error response so that it can serialize correctly.
- Build completion is unknown until measured evidence exists. Legacy default memory values become unknown in Core answer/status context; stored data is not overwritten. Nondefault saved setup/deployment statuses remain visible but explicitly unverified.
- Health summaries describe recorded Health ISF counts and do not claim that the entire service is healthy. Answer context explains these evidence limits.
- Update two stale navigation tests to match existing owner-module separation and the current Voice URL; no navigation HTML changes.

## Verification

41 focused backend tests passed: new routing/evidence tests, existing Core/Workspace/Business tests, and three existing Today discovery/error regressions. Two Node tests exercise both Ask Nova handlers and confirm trust labels, clickable source/review links, and rejection of script URLs. JavaScript syntax and whitespace checks pass. New regressions are included in backend diagnostic CI.

Broader checks also found eight pre-existing failures: five Today relevance cases expect an LLM call although current dedicated live/memory handlers return directly; a web-search mock lacks current filter keyword arguments; two old Core freeze tests expect obsolete Home API/navigation wiring. These failures were independently reproduced on unchanged main 2cda35e, and are not counted as passing validation.

Tests use mocked discovery results and do not establish that live providers will return qualified opportunities. Existing qualification, application preparation, owner review, and external-action restrictions remain in force. No actual application was submitted by these tests. This change connects existing workflows; it does not guarantee a contract or payment.

The previous Creative Studio recovery fix is already merged in PR #221 and included in the base. Its remaining server-side 502 attribution still requires Render/request logs. Deployment is left to the owner.
