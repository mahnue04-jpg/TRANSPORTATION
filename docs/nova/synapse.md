# AMICOR Synapse

Synapse is the AMICOR-branded meeting workspace at `/nova/synapse`.
It uses LiveKit Client 2.22.4 (vendored locally with Apache 2.0 license).
The browser never receives the provider API secret. No third-party scripts or public demo rooms are loaded.

## Activation

Configure one LiveKit deployment (managed or self-hosted with TLS and TURN) using the existing server's secure environment settings:

- `LIVEKIT_URL`: secure WebSocket origin, e.g. `wss://your-project.livekit.cloud`, with no path, query or credentials.
- `LIVEKIT_API_KEY`: deployment API key.
- `LIVEKIT_API_SECRET`: corresponding secret, at least 32 characters.

Restart/redeploy after setting these values. No service or billing subscription is provisioned by this change. `/api/nova/synapse/status` reports configuration presence, not a connectivity or quality guarantee. Until configured, calls and meeting creation are disabled with an explicit explanation.

## Acceptance before offering calls

1. Sign in as a host; create a meeting and copy its AMICOR invitation.
2. Open the invitation on a second real device/network. Join with a display name.
3. Camera and microphone remain off until the participant enables them.
4. Test bidirectional audio/video, sound activation, screen sharing and Unicode chat.
5. Test Arabic RTL and the other screen languages. The selector covers English, Somali, Arabic, French, Spanish, Portuguese, Simplified Chinese, German, Hindi, Japanese, Italian, Russian, Greek, Korean, and Turkish. These are interface labels only. Synapse does not translate live speech and does not claim native-speaker voice or fluency.
6. Test reconnecting on a changing network and ending for everyone.
7. Verify invite expiry and locked invite rejection; previously minted grants remain valid for up to 5 minutes. Locking prevents new grant requests, not immediate revocation of existing grants.

Meetings are scoped to the creating account and organization. Invitations are bearer links: only the hash is stored; the secret stays in the URL fragment and POST body. Links expire after 8 hours. Join tokens expire after 5 minutes for initial connections; token expiry does not end active calls. Host ends active calls through the provider DeleteRoom API. Meeting chat is transient and is not saved to Nova. A failed send shows next to the composer and does not clear the draft. An existing host can resume from the Saved meetings list and issue a new invitation link. Saved meetings are titles stored on `nova_synapse_meetings.title` for the signed-in owner and organization. They are not recordings. A title remains listed until the meeting ends or the eight-hour invitation window expires. Saving a title writes through `PATCH /api/nova/synapse/meetings/{id}/title` and the list reloads from that row. Issuing a new link invalidates previous invitation links without disconnecting active participants. The participant roster remains visible even when cameras are off. A waiting room, recording, live interpretation, captions, scheduled meetings, integration with projects are not implemented.

## Voice input behavior

Workspace recording continues through pauses and has no fixed 60-second timer. Press Finish to transcribe, review/edit, then Ask Nova. Asking while recording/transcribing is blocked. Text from repeated recordings is appended. Echo cancellation, noise suppression and gain control are requested from the browser; support and quality vary. The existing 10 MB audio upload limit remains; recording is automatically finalized at 9 MB to preserve collected speech. Other Nova browser dictation controls restart on silence, append final words, and never submit automatically. Stop ends that dictation; Ask Nova/Start Nova submits explicitly.

## Layout evidence, 2026-10-14

This pass used simulated viewports in headless Chrome. It did not use a physical iPhone, a second browser, or a configured LiveKit deployment. Camera, microphone, screen share, and live two-device audio were not exercised here.

- Desktop, inner 1280×713: with the meeting class applied, the chat composer was inside the viewport (top 270, bottom 349). The failed-send message was inside the composer form. Before joining, the Saved meetings heading was inside the viewport (top 483). Arabic set direction to RTL and translated the heading and create button.
- Narrow viewport, inner 500×757: headless Chrome did not apply the requested 390px width. The chat composer was inside the viewport (top 656, bottom 706) and the send error sat on the same row as the send button. The Saved meetings heading was inside the viewport before joining (top 518).
- Node UI tests simulated a local send, a remote data message, a failed send that keeps the draft, and a renamed title reloaded from the meeting list. Those tests are not a live call.

## Business readiness

Nova stores projects, conversations and uploaded document text in its existing Workspace. This meeting feature does not claim all business functions are connected. Easy Care's Pavillio integration, agency-approved rules and account trial extension remain separate setup tasks. Validate each advertised workflow with real authorized inputs before declaring the whole business workspace operational.
