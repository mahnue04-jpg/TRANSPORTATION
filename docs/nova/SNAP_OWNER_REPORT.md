# Nova Snap owner report

Session: `bc-0754c7aa-4d2a-54d4-b6cd-1a8d12278f69`
Branch: `cursor/nova-snap-comms-camera-8f69`
Issue: https://github.com/mahnue04-jpg/TRANSPORTATION/issues/337

The GitHub token for this session cannot comment on issues (`Resource not accessible by integration`). Ownership is recorded here and on the draft pull request. No second Snap agent was running on this repository.

This is a preview. It is not a production release, and it was not deployed.

## Milestone 1 — audit

Main at `d0a3f2b1` has AMICOR Synapse meetings (`/nova/synapse`, LiveKit) and Nova Casting auditions inside Creative Studio. It had no Snap messaging, calling, or camera module.

Draft PR #333 (`cursor/website-preview-release-7a7a`) adds a public catalog card for Nova Snap and labels it Coming Soon. That branch was not edited. The card stays Coming Soon.

Not touched: Work & Revenue #336, Casting #332, Synapse meeting behavior, Delivery, and Driver 001.

Nova Home now has one added tile, "Open Snap preview", that says the feature is not a production release. It does not say Available.

## What was built

Nova Snap lives at `/nova/snap` and `/api/nova/snap`. It is separate from Synapse meetings, Casting auditions, the Nova inbox, and Work & Revenue.

- Contacts are opt-in inside one organization. Direct messages and groups of up to 8 start only after acceptance.
- Messages keep a client id so a retry does not duplicate. Unread, delivered, and read state are stored. Unsafe `javascript:`, `data:`, `vbscript:`, `file:`, and `blob:` links are rejected. Ordinary https links stay as text.
- Block, report, delete, 30-day message retention, and remove-my-content are implemented. Reports are stored for the reporter only. Nothing is emailed.
- Calls have invite, accept, decline, hang up, signaling replay, reconnect, and a network-timeout failure. The server does not forward audio or video.
- Camera preview, flip, mute, 15-second clips, private drafts, and consent-gated sharing are implemented. Bytes are outside `/static`. There is no public upload and no capture on page load.

## Calling, honestly

`turn_configured` is false unless an operator sets `SNAP_TURN_URLS`, `SNAP_TURN_USERNAME`, and `SNAP_TURN_CREDENTIAL`. This change does not buy a relay. Default STUN is `stun:stun.l.google.com:19302`, which only helps address discovery. Strict NATs, some mobile carriers, and many international paths will fail. There is no sound or picture quality guarantee.

A future team option could add TURN. There is no checkout and no new paid account.

## Tests

Passed on this branch:

- `tests/test_nova_snap.py`: 10 passed. Covers auth rejection, opt-in contacts, groups, duplicate sends, unsafe links, cross-user and cross-organization reads, block, report, delete, retention, rate limit, call signaling, reconnect, network timeout, decline, hang up, bad media, consent, private share, and account removal.
- `test_two_account_synthetic_journey`: dispatcher and staff on the seeded accounts. Driver in the same organization cannot read the conversation or the capture. The journey sends a message, retries the same client id, places and ends an audio call, shares a JPEG only after consent, and removes the sender's content.
- `tests/nova_snap_ui.test.cjs`: 3 passed. Page copy, no screen-share API, no `innerHTML`, no blinking animation, camera permission only after the button, denial does not retry, share stays disabled without consent.
- `tests/test_nova_home.py`:  the home file passed, including the new Snap tile.
- `tests/test_nova_synapse.py`: passed. Synapse camera and screen-share policy is unchanged. Snap does not enable screen capture.

Headless Chrome on the local preview:

- Desktop and phone signed-out pages show the preview warning and the TURN limitation.
- Staff signed in and saw the accepted dispatcher contact.
- Dispatcher opened the direct conversation and the title became "Direct message".
- A scripted wait for the sent message did not finish in the browser runner. The same two-account send, call, and private share passed through the API test. This was not a test on two physical phones.

## What is not verified

- No second physical iPhone or Android device.
- No real microphone or camera picture between two networks.
- No TURN relay, so worldwide call quality was not tested and is not claimed.
- No production deploy, public media, live outreach, or new purchase.

## Release

Not release-ready. Keep the public card on Coming Soon. Do not merge to production until an owner wants this preview. Rollback is in `docs/nova/snap.md`: stop linking `/nova/snap`. The `nova_snap_*` tables are additive. Synapse, Casting, and Work & Revenue do not read them.

## Continuation 2026-10-14

PR #340 is still a preview. This pass hardened signaling and added a simulated two-account audio/video path. It did not buy TURN, did not deploy, and did not use two physical devices.

Audio/video evidence:

- Test `test_simulated_two_peer_audio_video_loopback` drives two signed-in accounts through the real Snap call API.
- Offer, answer, host ICE, reconnect, and hangup are stored for those accounts only.
- The RTC layer is `CallSession(simulated=True)`. Label: `simulated`. Media path: `simulated-loopback`.
- `two_independent_devices` is false. `devices_used`, `browsers_used`, `cameras_used`, and `rtp_packets` are 0.
- `turn_configured` and `turn_purchased` are false. Relay candidates are rejected.
- This VM has no `/dev/video*` node. Headless Chrome rendered the signed-out page only. That render is not a call and is not two-device success.

Tests on this pass:

- `python3 -m pytest backend/tests/test_nova_snap.py -q`: 17 passed, 0 failed.
- `node --test backend/tests/nova_snap_ui.test.cjs`: 6 passed, 0 failed.
- `python3 -m pytest backend/tests/test_nova_home.py backend/tests/test_nova_synapse.py -q`: 27 passed, 0 failed (15 Home, 12 Synapse). Home and Synapse product code were not edited.

A human two-device checklist remains in `docs/nova/snap.md`. Public Coming Soon on `origin/main` `website/catalog.py` was not edited.

## Continuation 2026-10-18

Two open review findings on `e751760c`:

- Reconnect posted `renego` after installing a new local offer. The server rejected that restart while the call was ringing and while the first offer was still unanswered, so the browser and the other person diverged.
- A group timeout marked every quiet peer left and could leave one person in an active call, which blocked the next call.

The active-call restart now replaces that sender's unanswered offer. Ringing restarts stay rejected. The browser sends the restart before `setLocalDescription`, and it does not install the offer when the call is not active. A timeout that would leave fewer than two people fails the call with `network_timeout`.

This is still a simulated signaling check. `two_independent_devices` stays false. No TURN server was purchased. The public card stays Coming Soon.

Tests on this pass:

- `python3 -m pytest tests/test_nova_snap.py tests/test_nova_home.py tests/test_nova_synapse.py -q`: 45 passed, 0 failed (18 Snap, 27 Home and Synapse).
- `node --test tests/nova_snap_ui.test.cjs`: 7 passed, 0 failed.

No browser on two devices was used. Headless rendering from earlier passes is still the signed-out page, not a call.
