# Nova Intelligence synthetic media slice

Honest status, kept separate. This file does not claim a production launch.

## Designed

Issues #369 and #371 describe a multimodal enterprise workflow: authenticated media jobs, tenant isolation, SSRF controls, timestamped evidence, erasure, and later healthcare or institutional drafts. The design spec is the unmerged draft in PR #370 (`docs/nova/enterprise-multimodal-engine-spec.md` on `feature/nova-enterprise-multimodal-blueprint`). Positioning copy is the unmerged draft in PR #372. Timed evidence ordering is the unmerged draft in PR #374. Those branches are not merged here.

The designed pipeline still includes quarantine uploads, FFmpeg frame sampling, OCR, paid speech-to-text, and async workers. That pipeline is not what this slice runs.

## Coded

This package is an offline synthetic slice:

- Flag name: `NOVA_INTELLIGENCE_MEDIA`. Default is **off**. If the variable is unset or is any value other than exactly `1`, every `/api/nova/intelligence/media` route and `/nova/intelligence/media-demo` return 404.
- Ingest uses the existing `app.auth.get_current_user_context` dependency. There is no new login and no new secret.
- A job is stored in process memory and is visible only to the organization id that created it. Another tenant receives the same not-found response as an unknown job.
- Sources are a known fixture id or an https URL that passes a pure SSRF check and then matches an in-process allowlist of synthetic fixture URLs. The code does not open a connection, resolve DNS, or follow a redirect.
- Evidence is authored fixture text with start and end seconds and source refs. Ordering goes through `timeline()`. Empty and failed fixtures add no observations.
- Warnings state that speakers are unknown and that the summary is fixture text.
- DELETE writes an in-memory erasure. Later reads return not-found for that tenant.
- Declared byte size and media type are rejected in the request validator. No malware scanner is called.
- The audit log line may include job id, tenant id, status, and fixture id only.
- The owner-review page is static HTML with timestamps and source refs. It is labeled synthetic and not a production analysis.

`NovaIntelligenceEngine` remains importable from `app.core.nova.intelligence`. The previous module file is `operational_engine.py` in this package so the directory can exist. That engine was moved unchanged and is not part of the media slice.

## Tested

Local pytest covers timeline ordering, auth, cross-tenant hiding, SSRF and path traversal, flag off, erasure, and fixture provenance. Tests turn the flag on themselves. There is no staging run and no production run.

## Not deployed

This slice is not deployed. It is not a HIPAA program. It is not connected to Creative Studio render. It does not call FFmpeg, Tesseract, paid speech-to-text, OpenAI, Stripe, or the network. No PHI, hotel data, or customer data is included.

## Flag default

`NOVA_INTELLIGENCE_MEDIA` stays off unless the process environment is exactly `1`. Production behavior of every other route is unchanged while the flag is off, because these routes answer 404.
