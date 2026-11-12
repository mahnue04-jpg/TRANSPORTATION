# Studio release acceptance — 2026-10-12

Verdict: **not assessment-ready.** No paid provider was called. The saved MP4 and its source paths were left in place.

Deadline stated by the owner: Wednesday 14 October 2026.

## File inspected

`backend/static/nova-one-minute-demo/amicor-nova-60-second-full-body.mp4` at PR #323 head `21c7345eb39c562d88c90e3b183ce4b06a9118d4`.

| Check | Measured |
| --- | --- |
| Container / video | MP4, H.264, 1280×948, 24 fps, yuv420p |
| Duration | Video 59.875s, audio 59.856s |
| Audio | AAC LC, mono, 24000 Hz, mean −28.7 dB, max −7.8 dB |
| Faststart | `moov` atom before `mdat` |
| Captions | Burned into a bottom band, plus `.srt` and `.vtt` |
| Aspect | Landscape. Not 9:16 vertical |
| Motion | Presenter pixels repeat about every 5.04s |
| Pose | Standing, head to about the knees. Not sitting |
| Lip-sync | No. The mouth belongs to the short plate, not the narration |
| Watermark | None visible in frames at 0.5s, 8s, 20s, and 45s |
| Mobile markup | `playsinline` is set. Chrome played it at 390×844 |
| Chrome playback | Unmuted, readyState 4, time reached 1.93s after 2s, 23,454 audio bytes decoded |
| Phone captions | Burned-in type is about 8.5 CSS pixels tall at 390px wide. The 22.5s line was still readable |

Frame difference of the presenter area (captions cropped off), mean absolute pixel difference on an 80×53 gray frame:

- 1.20s versus 6.24s (one 5.04s cycle): about 0.44
- 1.20s versus 3.40s (different moment in the plate): about 3.3

## Browser playback

Chrome played `amicor-nova-60-second-full-body.mp4` from the start on a desktop page and in a 390×844 mobile viewport. The element reported duration 59.875, size 1280×948, `muted` false, and `readyState` 4. After two seconds, `currentTime` was 1.93 and `webkitAudioDecodedByteCount` was 23454, so the audio track is being decoded. The active caption at the start was “Meet AMICOR Nova, your AI operations workspace built”. A frame at 22.5s, scaled to 390px wide, shows “The Operations Agent turns business requests into clear”. On that phone width the burned-in caption is about 8.5 CSS pixels tall. The face at both times is the same standing plate, not a new mouth shape for the later sentence.

A physical phone was not used. Scrubbing did not complete against a static server that answered byte-range requests with a full 200 response; that limit is the server, and the file still has the `moov` atom first.

## Tools and licensing

Assembly tool: local FFmpeg through `assemble_full_body_demo`. This pass did not generate new pixels or speech.

Source plate still referenced by the page: `/media/nova-creative/nova-da25e10f80924d6ca99e62a04c9eb346.mp4`. Prior Studio motion used fal Kling image-to-video, which the 2026-10-04 note limits to about 5 seconds and says does not establish lip-sync or watermark-free output.

Narration still referenced by the page: `/media/nova-creative/nova-bb9d59169aef4733ba8c07d1b0d418f6.mp3`, the existing Coral voice file.

No new commercial license was granted and no IP agreement was signed. Fal/Kling terms still govern the plate. OpenAI terms still govern the Coral narration. Absence of a visible watermark is not a license.

## Why a replacement file was not rendered

A credible 30–60s vertical photorealistic sitting woman, with mouth movement locked to the narration, needs a sitting source plate and a lip-sync model. This environment has no GPU and no funded provider. Calling Kling lip-sync, HeyGen, D-ID, or another credit API was out of bounds. A local cartoon or a re-crop of the standing loop would not meet the requirement, so neither was saved as the assessment file.

## Prior CI on this head, before this acceptance note

Workflow run evidence at `21c7345`, completed 2026-10-12:

- Jekyll site CI `build`: success — run 38275185433
- Render backend diagnostic `qualification-regression`: success — run 38275185412
- Render backend diagnostic `backend-diagnostic`: success — run 38275185412
- Work and Revenue `qualification`, `country-eligibility`, `work-and-revenue`: success — run 38275185292
- Netlify deploy preview: success

Those checks do not measure lip-sync, pose, or aspect ratio.
