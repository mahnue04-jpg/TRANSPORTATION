# Nova Studio Kling alternative

Kling 2.5 Turbo Pro via fal is an optional image-to-motion provider. It reuses existing scene source artwork and returns saved MP4 assets for Nova's dialogue/caption assembly. Runway remains the default. No automatic failover or payment is performed.

## Owner setup

In the production service's secure environment settings, configure `FAL_KEY`, set `NOVA_CREATIVE_VIDEO_PROVIDER=kling`, and enable both `NOVA_CREATIVE_VIDEO_LIVE_ENABLED=true` and `NOVA_CREATIVE_KLING_LIVE_ENABLED=true` only after funding and activation are authorized. Never put the key in chat, code, client-side JavaScript, or screenshots. Changing the selected provider alone does not enable Kling generation.

The fixed model is `fal-ai/kling-video/v2.5-turbo/pro/image-to-video`; each request is a 5-second clip. Existing voice assets remain separate. This provider does not establish lip-sync or watermark-free output.

## Recovery and limits

Queue request identifiers and fal-issued tracking URLs are saved together before background polling. Resuming a job checks that request rather than submitting another. Status connection failures and output-download failures keep the request recoverable. URLs carrying the API key are limited to the HTTPS fal queue origin, with redirects refused. Provider response bodies are not exposed in errors.

An unfinished task from another provider blocks switching rather than forwarding its identifier to the new API. Complete it under its original provider before switching. A submission connection failure with no returned request identifier cannot be automatically reconciled: inspect fal usage before retrying to avoid duplicate paid work.

## Verification

39 offline tests passed across Kling lifecycle, scene restart recovery, short drama, and image timeout suites. Tests cover submit/persist/resume, failed generation, polling/download recovery, activation gates, foreign-provider tasks, and rejection of foreign tracking origins. No paid generation or fal account funding was attempted.

Sources: https://fal.ai/models/fal-ai/kling-video/v2.5-turbo/pro/image-to-video/api and https://fal.ai/docs/documentation/model-apis/inference/queue.
