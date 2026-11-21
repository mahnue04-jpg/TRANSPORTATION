# Creative Studio: reviewed explainer planning and finished MP4 import

Baseline: PR #406 head `7789ae1279a138d481c4b00965225a9cfd319307`.
This isolated change does not merge, deploy, activate providers, or resolve the separate provider-submission/assembly audit.

## Observed staging failures

A signed-in explainer project, `TEST — Kids Education — Counting to Three`, had a saved counting lesson. Generating its storyboard instead produced “Meet AMICOR, your AI operations workspace” and business busywork scenes. The finished-video asset panel offered no MP4 import control.

## Corrections

- Explainer scripts, caption copy, storyboards and image prompts require the latest saved presenter narration. They preserve that narration instead of inserting the AMICOR sales template. Missing narration fails before creating a generation job. Existing marketing templates remain available for other project types. Two-character dramas retain their existing planner.
- Educational storyboards divide the saved narration into up to six sentence-based planning beats (up to three for 15s). Durations are word-based estimates and explicitly not verified narration alignment. Visuals, age suitability, factual correctness and actual audio timing still require review. This is not an automatic educational lesson writer.
- `POST /api/nova/creative/projects/{project_id}/finished-video-upload` accepts a bounded MP4 upload. Existing authentication and project ownership checks apply. Validation forces local MOV/MP4 parsing with external references disabled, requires H.264/AAC video plus audio, limits duration/dimensions and fully decodes both tracks. Blocking decode runs off the async event loop under the media serialization lock.
- Validated bytes become a downloadable project video asset. A repeat of the same bytes reuses the existing local asset when its file still matches. No scripts, narration approvals, provider flags or spend gates are changed. Import is not licensing verification or publishing approval. Failed asset persistence removes the output file.
- The asset panel adds an explicit free import control. Project-switch responses are guarded and file inputs reset with project/session changes. Existing owner-scoped media download handles imported videos.

## Completed local validation

`python3 tools/check_content_import_offline.py`: 9 tests passed, using real generation code, exact service method ASTs and real FFmpeg/ffprobe media. This harness excludes application/DB initialization and does not substitute for HTTP integration testing.

Covered: lesson preservation across four planners; missing-script blocking; latest-script selection; existing advertising template; valid import and byte-identical download; duplicate-upload reuse; owner isolation; corrupt/empty/wrong-type/oversize/no-audio rejection; failure cleanup; no implicit approval changes.

The owner's already-approved commercial separately passed the new validator: 30.0 seconds, 720×1280, H.264/AAC, full decode succeeded. This was a local read-only media check, not a Studio upload or a provider job.

Python compilation, JavaScript syntax and `git diff --check` passed.

## Required CI and staging acceptance

`backend/tests/test_studio_content_import.py` adds actual service and FastAPI upload/download/unauthenticated/cross-owner tests. This suite was authored but could not run locally: pytest, FastAPI, SQLAlchemy and multipart are absent in this environment. The guarded workflow installs dependencies and runs it with paid-provider flags disabled.

After review and separately authorized staging deployment:

1. Upload the approved commercial once. Refresh and download it; compare SHA-256 to the original. Repeat upload and confirm the existing asset is returned. Confirm narration/image approvals are unchanged.
2. From another signed-in owner and signed out, verify the original asset is inaccessible.
3. Reload the saved counting project and run storyboard/script/caption/image-prompt generation. Verify exact lesson words, correct visuals, no business advertising, and unverified timing displayed honestly.
4. Exercise the browser upload file picker, validation errors, project switching and session expiry. Local syntax checks do not establish browser-flow correctness.
5. Render children’s lesson, drama and cartoon samples only under a separately authorized provider budget. Verify movement, character/speaker continuity, every spoken word, caption timing, complete downloadable MP4 and actual provider billing. Saved plans and successful CI alone are not finished videos.

No paid provider calls or deployment occurred during this work. The approved commercial remains stored separately; staging currently contains its reference link, not imported MP4 bytes.
