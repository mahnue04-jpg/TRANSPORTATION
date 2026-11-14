# Controlled five-second shot: price guard and retry suppression

The controlled shot previously accepted an estimate acknowledgement without a
per-shot limit, and fal queue requests did not explicitly disable provider
retries or model fallbacks. The fixed endpoint requires a finite, positive USD
limit no greater than $1 and persists it in the existing atomic shot claim.
Project switching clears the entered limit. No provider flags are enabled by
this change.

Immediately before a new controlled Kling submission, the adapter retrieves
account pricing for the exact fixed five-second endpoint using the existing
server-side credential. It accepts only positive finite USD prices with known
per-second or per-video units. Decimal arithmetic compares five seconds (or one
video) against the persisted limit. Missing, ambiguous, inaccessible, or
over-limit pricing blocks the video POST. There is no cached-price fallback.
GET-only recovery of a saved task does not request fresh generation or pricing.

Kling queue requests set `X-Fal-No-Retry: 1` and
`x-app-fal-disable-fallback: true`. Existing durable duplicate and ambiguous-post
claims remain in force. No top-up or purchase implementation was added.

## Limits and activation requirements

This is an application submission-price guard, **not a provider-enforced final
invoice ceiling**. Price checks and generation submission are separate calls;
the provider's eventual charges cannot be guaranteed by this code. The UI and
result metadata state this limitation. Do not represent the price evidence as
a paid invoice or a guaranteed $1 billing cap.

Existing owner budget confirmation, reviewed balance, provider activation and
protected storage checks remain required. Never invent an owner-reported
balance to bypass those checks. Keep paid generation disabled until the
authorized run can meet its cost conditions. No SQLite migration, storage
activation, production deployment, or paid render is part of this patch.

## References checked

- https://fal.ai/docs/documentation/model-apis/pricing
- https://fal.ai/docs/documentation/model-apis/common-parameters

## Offline verification

Focused Python tests cover missing/invalid limits, boundary prices, malformed
pricing, currency/model/unit mismatches, pricing permission errors, retry and
fallback headers, preserved saved-task recovery, durable shot claims, and
private storage checks. HTTP is intercepted in the new spending tests; no
credentials or provider spending are used.

The Creative Studio browser-script tests cover passing the entered limit,
rejecting invalid limits without a request, clearing it on project changes,
and existing selection/playback/download behavior.
