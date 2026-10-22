# CIGO consumer idea validation — 2026-10-13

Owner budget acknowledged: up to USD $20 total for one original assessment video, and only if this exact account and tier is confirmed in writing for a watermark-free commercial MP4, presenter and voice rights, and a final checkout price. No recurring subscription. No IP transfer. No third-party submission.

This pass did not charge a card, start a subscription, sign a commercial or IP acknowledgement, merge, deploy, or submit anything to CIGO.

## Provider evidence

HeyGen API pay-as-you-go is not confirmed for this job.

- Watermark removal: [How to Remove the HeyGen Watermark](https://help.heygen.com/en/articles/11057301-how-to-remove-the-heygen-watermark) says a user must be on “any paid plan (Creator, Pro, Business, Enterprise, or a legacy plan)” and use the Studio toggle. API pay-as-you-go is not named.
- Commercial output: [HeyGen Terms](https://www.heygen.com/terms) section 3, “License to Your Content (For Users In the Creator, Pro and Business Plans),” is the section that allows use “including for commercial purposes” and assigns HeyGen’s rights in that output to the user. Section 4 limits Free-plan output to “personal, non-commercial, and internal evaluation purposes.”
- API wallet: [HeyGen API Pricing Explained](https://help.heygen.com/en/articles/10060327-heygen-api-pricing-explained), last updated September 16, 2026, says pay-as-you-go credits can be bought without Creator, Pro, or Business, including by free users. [HeyGen’s FAQ](https://www.heygen.com/faq) says the API can start at $5 with no monthly commitment, and that Creator is $29 a month ($24 a month annual) and includes watermark removal.
- Create-video docs support `aspect_ratio` `9:16` and Avatar IV. They do not state that a seated full-length synced look is included on pay-as-you-go. The create-video `watermark` field is a custom overlay for select Enterprise customers. Lipsync `enable_watermark` defaults to false, which only means that endpoint can skip adding a mark. That is not a commercial license.
- This environment has no HeyGen API key and no payment method. Quoted checkout: none. Amount charged: $0.

Creator at $29 a month is over the $20 cap and is a subscription, so it was not started. D-ID’s studio FAQ says Trial and Lite videos carry a D-ID watermark, and its help center describes subscriptions rather than a one-time commercial export. No other provider page confirmed a watermark-free commercial seated 9:16 full-length synced MP4 for a one-time charge at or under $20 on an account this environment can use.

## Unpaid worksheet

`CIGO_IDEA_VALIDATION_DEMO=1` with a non-production `RUNTIME_ENVIRONMENT` mounts `/dev/cigo-idea-validation`. Production stays unmounted even if the flag is set. The page is `noindex`.

The page shows script `cigo-consumer-idea-validation-script-v1` and a five-step fictional workflow for the invented Lease Lens checklist. Saving a worksheet returns an `idea_` id. The same idea and consumer return that id. Invalid fields and a simulated storage failure save nothing. JSON and CSV export stay on this machine. `outbound_sends` stays 0.

`assessment_ready`, `video_rendered`, and `repeating_plate_created` are false. No plate, narration file, or lip-sync was created.

## Video QA, unchanged

PR #323, `backend/static/nova-one-minute-demo/acceptance.json`, still records `assessment_ready: false` for `amicor-nova-60-second-full-body.mp4`: 59.875 seconds, 1280×948 landscape, standing motion repeating about every 5.04 seconds, mouth not locked to the separate Coral narration, commercial use not cleared. This pass did not open, replace, or re-encode that file.

Separate from PR #330, website PR #333, Synapse, QA, Revenue, and Casting. Nothing here is merged or deployed.
