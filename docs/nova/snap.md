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

`SNAP_STUN_URLS` defaults to `stun:stun.l.google.com:19302`. Set it to `off` to disable STUN. That host is a public address-discovery service, not an AMICOR relay, and it is not a quality promise.

`SNAP_TURN_URLS`, `SNAP_TURN_USERNAME`, and `SNAP_TURN_CREDENTIAL` enable a relay only when all three are set by an operator. This change does not buy or provision TURN. Without TURN, strict NATs, some mobile carriers, and many international paths fail. `/api/nova/snap/status` reports `turn_configured: false` and `quality_guarantee: false`.

Optional later team tier: a TURN relay and longer retention. No checkout and no new paid account are included.

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
