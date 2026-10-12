# CIGO AI Automator checklist — 2026-10-12

Owner deadline: **Wednesday 14 October 2026**. Nothing in this pass was merged, deployed, published, or sent to CIGO.

The repository and a public search do not contain a document titled “CIGO AI Automator” brief. This checklist follows the requirements in the owner request. If the official brief adds items, those items are unmet until the owner supplies them.

## What was verified

| Item | Result |
| --- | --- |
| Continue Studio PR #323 | Yes. Acceptance note is on `cursor/studio-static-contract-a5ee` |
| Avoid website PR #329 | Yes. No `website/` or website workflow files changed |
| Avoid Synapse #311 and QA #312 | Those pull requests are not in this repository. No Synapse or workflow files changed |
| Saved 30–60s vertical lip-synced sitting presenter | **Fail.** See Studio acceptance below |
| Paid providers, credits, publication, real responses, IP signing, third-party submission | Not done |
| Nonpublic mock validation demo | Built behind `CIGO_VALIDATION_DEMO=1` and forced off when `RUNTIME_ENVIRONMENT` is production |

## Studio video

Inspected file: `backend/static/nova-one-minute-demo/amicor-nova-60-second-full-body.mp4` at previous head `21c7345`.

- Duration 59.875s video / 59.856s audio, inside 30–60s
- 1280×948 landscape H.264, not 9:16
- AAC mono 24000 Hz, mean −28.7 dB, max −7.8 dB
- Faststart is present. The page sets `playsinline`. A physical phone was not available
- Captions are burned in and also saved as SRT and VTT. Sampled frames show white caption text on a dark band
- Motion repeats about every 5.04s. Pose is standing, head to about the knees
- Mouth movement is the short plate, not speech locked to the Coral narration
- No watermark was visible in frames at 0.5s, 8s, 20s, and 45s
- Original presenter and narration URLs are still on the page

Tool this pass: local FFmpeg only. No new pixels or speech were generated.

Prior providers, not called again here:

- Motion plate: fal Kling image-to-video, about 5 seconds. The 2026-10-04 note says that provider does not establish lip-sync or watermark-free output.
- Narration: existing OpenAI TTS voice Coral.

Commercial use and IP: **not cleared.** No license was granted and no IP agreement was signed. Fal/Kling terms still govern the plate. OpenAI terms still govern the narration. A missing visible watermark is not permission to submit the file.

`assessment_ready` is false in `backend/static/nova-one-minute-demo/acceptance.json`.

## Mock validation demo

Run locally with `CIGO_VALIDATION_DEMO=1` and a non-production `RUNTIME_ENVIRONMENT`, then open `/dev/cigo-validation`.

Covered with mock data only:

- Idea, budget, currency, optional email, consent, and follow-up
- Unique `cigo_` id on first save
- Duplicate idea and email returns the original id
- Invalid idea, budget, currency, email, follow-up, and missing consent return field errors and save nothing
- Email follow-up without an email is rejected
- Records, suppressed alerts, and failure events are listed
- Storage failure can be simulated and leaves the record list unchanged
- JSON and CSV export
- `outbound_sends` stays 0. Alerts use `suppressed_no_outbound`

Chrome on the local demo process checked the form at desktop width and at 390×844. A valid save showed a `cigo_` id and outbound sends 0. Submitting that same idea again kept the original id. A short idea, zero budget, missing currency, bad email, and missing consent showed field errors. A simulated storage failure returned 503 and left the record list empty.

## Explicit gaps

- No photorealistic sitting talking presenter
- No natural lip-sync
- No vertical 9:16 assessment master
- No commercial-use clearance for the current media
- Official CIGO brief text is not in the repo, so extra brief items cannot be checked off
- No physical-phone playback of the Studio file
- Synapse #311 and QA #312 could not be coordinated by number because they are not open here

## Owner decisions still required

1. Fund and approve a lip-sync provider plus a licensed sitting plate, or accept that the 14 October visual bar cannot be met without that.
2. Paste or point to the official CIGO brief if it differs from the request.
3. Decide whether this mock demo may be shown privately. It still will not send email or submit the form anywhere.
4. Approve any merge, deploy, publication, IP signature, or third-party submission separately. None of those happened here.
