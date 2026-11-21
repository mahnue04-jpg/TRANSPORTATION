# CIGO AI Automator deliverables — 14 October 2026

The official Google Form was submitted on 2026-10-14 at 13:20:50 UTC. Google returned HTTP 200 and the message “Your response has been recorded.” Google did not show a separate receipt number. An earlier POST the same day returned HTTP 400 because the agreement checkbox was unchecked. The owner then authorized that checkbox after stating that written acceptance of CIGO’s one-page agreement had already been emailed. That checkbox was selected on this successful POST. No second submission was sent after the recorded response.

No new video was generated and no money was spent in this pass.

## 1. Final video link

https://v3b.fal.media/files/b/0aae5147/n7o5OtUWOjW2VvYEWJr9f_output.mp4

Downloaded and checked as this exact file. SHA-256 `e6434ca7b8ecfda805a6c033ffbcdf7835d4577dc484ce1dd7851d3cb357c1b8`.

| Check | Measured |
| --- | --- |
| Duration | Video 60.000s, audio 59.861s |
| Picture | 720×1280, H.264, 30 fps, vertical |
| Audio | AAC stereo, 44100 Hz, mean −31.7 dB, max −10.8 dB |
| Captions | Burned into the picture. No separate subtitle track (`closed_captions=0`) |
| Motion | Frames 5 seconds apart are different. This is not the old 5-second loop |
| Producer metadata | Kling, ProduceID `KLingMuse_8e44d2f1-2a64-4e64-bfaf-ea233bfc0d2b` |
| Chrome | A 390×844 page loaded the file as 60s, 720×1280 |

Sampled frames show a seated presenter, burned-in captions, and no visible watermark. The owner had already approved the voice, lip movement, captions, and presentation. This pass did not re-grade that approval.

The container identifies Kling as the producer. It does not contain a license grant. The owner stated that CIGO’s one-page agreement was already accepted by email, and authorized the form checkbox for that agreement.

A copy is served by the demonstration at `/dev/cigo-validation/approved.mp4`. It is the same bytes. The older PR #323 loop was not used.

## 2. Two alternative opening hooks and a social caption

These are text alternatives for testing. They are not a new video.

- Hook A: “The request is already in. The draft can be waiting before you open the laptop.”
- Hook B: “Keep the decision. Let Nova prepare the busywork.”
- Caption: “AMICOR Nova drafts the next step and waits for your approval. You stay in control. Share the idea and the budget.”

## 3. AI tools and editing software disclosure

- Video producer, from the file’s AIGC metadata: Kling, ProduceID `KLingMuse_8e44d2f1-2a64-4e64-bfaf-ea233bfc0d2b`.
- Container encoder: Lavf 60.16.100 and Lavc 60.31.102 h264_slapi.
- The owner supplied the finished file on fal.media. This pass did not call Kling, fal, or any other generator.
- The file does not name the voice vendor or a separate caption editor.
- The intake page was built in this repository with Python, SQLite, and the browser. It does not send email.

## 4. Video production explanation

The owner supplied one finished MP4. This pass downloaded that URL, hashed it, read both streams, sampled frames at 1s, 8s, 20s, 40s, and 55s, and played it in Chrome. The picture is a seated presenter in a vertical frame with burned-in captions and an audio track. Frame differences show the picture changes across the minute. Limitations: there is no separate caption file, no audio-description track, and no license document inside the file. No replacement video was rendered.

## 5. Working demonstration form

Route: `/dev/cigo-validation`

The page plays the approved video and accepts an idea, a budget, a currency (USD, EUR, GBP, or CAD), an optional email, a follow-up choice, and consent. A saved idea gets a `cigo_` id. The same idea and email return the original id. Invalid fields and a simulated storage failure save nothing.

Chrome on a 390×844 viewport loaded the video at 720×1280 and saved fictional idea `cigo_a2f92d905d2d4bfb95101d46224a1a43` with outbound sends 0.

The page is mounted only when `CIGO_VALIDATION_DEMO` is on and the process is not production (`RUNTIME_ENVIRONMENT`, `ENVIRONMENT`, `APP_ENV`, or `AMICOR_ENVIRONMENT`). It is not on the public internet.

CI on commit `4c2cc05c` is green: Jekyll run 38555811341, Nova Casting Preview run 38555811348, Work and Revenue run 38555811353, and Render backend diagnostic run 38555811342. A later commit keeps the route off the production host and escapes stored fields before they are shown.

Production `https://amicor-health-isf-py.onrender.com/dev/cigo-validation` still serves the main site shell, not this page. The Netlify preview for PR #330 returns 404 for that path because it does not run the Python app. Deploying this branch would restart the live Health ISF service, which also serves Delivery. That restart was not performed.

## 6. Connected database with fictional submissions

SQLite file `cigo-validation.sqlite` on the app data directory, or `/data/onboarding_docs/cigo_validation.sqlite` when that disk exists. Fictional rows use `@example.com` only.

Committed export from that database logic:

- `docs/verification/cigo-fictional-submissions.csv`
- `docs/verification/cigo-automation-workflow.json`

The three fictional ids are `cigo_fictional_bakery`, `cigo_fictional_tutor`, and `cigo_fictional_clinic`.

## 7. Automation workflow export

`GET /dev/cigo-validation/workflow.json` and the committed JSON file above.

Follow-up email creates a notification with status `suppressed_no_outbound`, `sent: false`, and `outbound_sends: 0`. The notice text is stored. It is not delivered. There is no live email provider in this flow.

## 8. Social media testing strategy

No social post was published, so there are no campaign results to report.

Proposed measures, all at zero spend:

- Three organic posts, one per hook, same caption, same form link.
- For each post record impressions, 50% video views, clicks to the form, and completed fictional-safe submissions.
- Compare hook A and hook B on form completion rate after the same number of impressions.
- Stop a hook if the form completion rate is under 1% after 1,000 impressions.
- Do not put real customer data in the post or the form export.

Local measurements that do exist: the approved file is 60 seconds and 720×1280, and the form test above saved one fictional record with zero outbound sends.
