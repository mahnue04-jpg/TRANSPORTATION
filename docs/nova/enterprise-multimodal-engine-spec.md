# Nova Enterprise Multimodal Engine — Implementation Specification
Status: DESIGN ONLY — NOT DEPLOYED. Tracking: #369.

## Existing components and gap
Reuse existing Nova auth, chat, image OCR at backend/app/image_ocr.py, uploads, provider resiliency, and file processors. Existing ride-intake authorization_adapter.py is not medical prior authorization. No claim of HIPAA, CJIS, or SOC 2 compliance. All regulated uses remain disabled.

## Boundary and operations
- Synthetic media and sample medical documents only until separate privacy/security sign-off.
- Client provides only footage and documents they are authorized to process, with required consent.
- Private immutable originals with explicit retention windows and deletion support; least privilege and tenant isolation; no raw contents in logs.
- Media pipeline runs asynchronously in isolated workers rather than request web process; limited CPU/memory quotas, FFmpeg sandbox, no outbound access except approved providers.
- Strict HTTPS allowlist, DNS resolution and redirect enforcement to block SSRF; protect against private/reserved addresses, oversized/decompression-bomb files, spoofed MIME, and malicious files.
- Encryption in transit and at rest, key management, incident response, access logs, evidence-based security review.

## API draft (authenticated, feature-flagged OFF by default)
POST /api/nova/media/jobs
Request: {source: {type: "upload_id" | "https_url", value: string}, options: {transcribe: true, ocr: true, scene_summary: true, diarize: false}}
Response 202: {job_id, status:"queued"}
GET /api/nova/media/jobs/{job_id} -> {status:"queued"|"processing"|"completed"|"failed", progress, error_code?}
GET /api/nova/media/jobs/{job_id}/result -> {duration_seconds, transcript_segments:[{start,end,speaker_id?,text,confidence?}], frame_observations:[{timestamp,text?,description?,confidence?}], scenes:[{start,end,summary,evidence_timestamps}], summary, warnings}
DELETE /api/nova/media/jobs/{job_id} -> recorded erasure request/status
All endpoints must validate tenant/owner permissions; no public results.

## First vertical slice
1. Ingest authorized uploaded MP4 (< configured quotas) in quarantine.
2. Validate content/codec; extract safe metadata; sample frames with FFmpeg.
3. Reuse image_ocr.extract on selected frames with timestamps.
4. Transcribe audio using configured vetted STT vendor. Speaker labels optional and explicitly uncertain.
5. Align scenes, OCR, and transcript into timestamp-indexed observations; produce grounded summaries with citations to media times.
6. Return reviewable evidence, failure state, processing-cost accounting, retention expiry.
7. Tests: auth/tenant boundaries, SSRF, duplicate retry/idempotency, malformed media, timeouts, transcript/vision grounding, erasure, provider outage and rate caps.
8. Document verified smoke-test evidence before enabling public demo.

## Healthcare next (mock-only)
Clinician-reviewed SOAP draft; payer rule versioning and human-validated ICD-10-CM/CPT/HCPCS suggestions; FHIR read-only sandbox with SMART on FHIR; HL7 only if purchased need. Do not submit claims or update EHR autonomously. Separate HIPAA security risk analysis, required BAAs including vendors, minimum-necessary requirements, consent, and secure data management before any PHI.

## Institutional next (mock-only)
Administrative document indexing, shift-summary drafts, maintenance hazard reports with human review. Do NOT autonomously classify offender risk, decide discipline, infer crime/contraband from imagery, or triage medical crises. No OMS access or criminal justice information before institutional agreements and applicable CJIS controls.

## Delivery gates
Design -> code -> CI security tests -> synthetic test -> staging demonstration -> production feature flag review -> customer approvals and contracts. Record each gate separately. SOC 2 Type II requires independent audit; do not mark as obtained from a checklist.
