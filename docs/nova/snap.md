# Nova Snap preview

Nova Snap is a private communications and camera preview at `/nova/snap`.
It is a different product from:

- AMICOR Synapse meetings at `/nova/synapse` (LiveKit meeting rooms, guest links, screen sharing)
- Nova Casting auditions inside Creative Studio
- Nova Communications at `/nova/communications` (inbox, mail drafts, calendar)
- Work & Revenue

The public website card stays Coming Soon until an owner approves a production release.
This preview is not a production release.

## What the preview does

- Organization-scoped contact requests. Both people must accept before a direct conversation or group exists.
- Direct messages and groups of up to 8 accepted contacts.
- Client message ids so a retry after a dropped network does not insert a second copy.
- Unread counts, delivered and read receipts, tombstones for deleted messages, and a 30-day message retention sweep when a conversation is read.
- Block, report, and remove-my-content. Reports are stored for the signed-in reporter only. Nothing is emailed.
- Unsafe `javascript:`, `data:`, `vbscript:`, `file:`, and `blob:` links are rejected. Ordinary `https` links stay as text and are not opened.
- Audio and video call invitation, accept, decline, hang up, signaling replay, reconnect, and network-timeout failure.
- Opt-in camera preview, flip, microphone mute, 15-second clip limit, private draft, and consent-gated share into one conversation.
- Camera and microphone permissions are requested from a button. Denial stops. Nothing is captured on page load.

## Calling limits

Calls are browser WebRTC between the signed-in participants. The server only exchanges call state and signaling. It does not forward audio or video.

The call machine on each peer is `idle → ringing → permission → connecting → connected`, plus decline, hangup, reconnect, and failure. Permission denial ends that invite with `permission_denied` and does not open the camera again until the person starts or accepts another call. Nothing is captured on page load.

`connected` in a browser means that browser reported a peer connection. It does not mean two devices exchanged audio or video. The automated test that reaches `connected` uses an in-process fake RTC layer and is labeled `simulated`. Its media path is `simulated-loopback`. It sends no RTP and opens no camera.

## STUN and TURN

This preview does not buy a relay.

| Piece | What it is | This build |
| --- | --- | --- |
| STUN | Tells a browser its public address (`stun:` or `stuns:`). It does not carry audio or video. | On by default: `SNAP_STUN_URLS=stun:stun.l.google.com:19302`. Set `off` to disable. A public STUN host is not an AMICOR service and is not a quality promise. |
| TURN | Relays packets when a direct path cannot be built (`turn:` or `turns:`), with a username and credential. | Off unless an operator sets `SNAP_TURN_URLS`, `SNAP_TURN_USERNAME`, and `SNAP_TURN_CREDENTIAL`. URLs with embedded passwords are ignored. |
| Relay candidate | An ICE candidate of type `relay`. | Rejected while TURN is off, including relay lines inside SDP. |

`/api/nova/snap/status` reports `preview_transport: stun-only`, `turn_configured: false`, `turn_purchased: false`, `two_device_verified: false`, and `quality_guarantee: false` unless an operator has configured TURN. Configuring those variables is not a purchase made by this change. Strict NATs, some mobile carriers, and many international paths fail without a relay. There is no international quality claim.

A future team option could add a TURN provider. There is no checkout and no new paid account in this change.

## What a person still has to prove

The simulated loopback does not replace a human test. Before any release, two physical devices on two networks must show all of the following:

1. Each device is signed in as a different account in the same organization.
2. The contact is accepted and one direct conversation is open.
3. An audio call: each person hears the other person, not only their own sidetone.
4. A video call: each person sees the other person's camera.
5. Decline, hangup, and reconnect after a network change all behave as labeled.
6. Denying the microphone and camera turns the browser capture indicator off, and it does not return by itself.
7. A strict NAT or mobile-carrier path is expected to fail because no TURN relay is configured.
8. The public website card stays Coming Soon until that checklist passes and the owner approves a release.

## Release hold

Not release-ready. Do not deploy this preview. Keep the public website card on Coming Soon.

On `origin/main` (`7173f17a`, not edited here) `website/catalog.py` sets Nova Snap `status="Coming Soon"` and `website/products/index.html` shows Coming Soon. This branch does not contain `website/` and does not mark Snap live. Nova Home links to the signed-in preview and does not say Available.

## Privacy

- Every conversation, message, call, and capture is organization-scoped.
- Another account, including one in the same organization, receives not-found for a conversation it does not belong to.
- Capture bytes live under `SNAP_MEDIA_DIR` or `backend/data/snap-private`, which is outside `/static`. Downloads require an authenticated member and use `Content-Disposition: attachment`.
- Drafts expire after 72 hours. Sharing requires `consent: true` and a conversation the owner still belongs to.
- There is no public media upload and no silent capture.

## Rollback

Do not deploy this preview to production without owner approval. If it is deployed and must be removed:

1. Stop routing users to `/nova/snap`.
2. Leave the `nova_snap_*` tables in place. They are additive and are not read by Synapse, Casting, or Work & Revenue.
3. Delete `SNAP_MEDIA_DIR` only after confirming it contains no captures an owner still needs. Deleting that directory removes private drafts.

Tables are created by the existing platform `create_all` path, the same path that creates `nova_synapse_meetings`. No new database purchase is required.
