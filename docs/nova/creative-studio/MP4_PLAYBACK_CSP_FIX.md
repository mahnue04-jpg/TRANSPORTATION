# Creative Studio embedded MP4 black-player fix

## Root cause (verified against staging)

Staging served `/nova/creative` with CSP:

`default-src 'self'; …` and **no** `media-src 'self' blob:`.

Authenticated preview fetches the private MP4 with a bearer token, then sets `<video src="blob:…">`. Without `media-src blob:`, Chrome blocks the media element → **black frame at 0:00**, while the same bytes downloaded as a file play in Windows.

PR #487 / #489 correctly fixed premature `revokeObjectURL` and added diagnostics; those alone cannot overcome a CSP media-src denial. Live staging already included the blob-lifecycle diagnostics script, and still lacked Creative Studio `media-src blob:`.

## Fix in this branch

1. `backend/app/middleware.py` — allow `media-src 'self' blob:` for `/nova/creative` and `/static/nova-creative/*`.
2. `creative.js` — keep blob URLs, normalize `video/mp4` MIME, surface CSP/codec errors, expand private preview to `private-studio://` assets, add in-page narration listen.
3. Cache-bust `creative.js?v=private-video-csp-blob-playback-20261112`.

## Presenter motion (separate)

Imported finished footage and offline montage are **not** proof of paid Kling / D-ID moving-actor generation. Treat presenter-motion as a separate paid-provider workflow that remains owner-gated and unverified by this fix.

## Owner action to finish the commercial on staging

1. Deploy this branch to `nova-studio-validation-350` (or equivalent isolated Creative Studio staging). Do **not** merge to production without separate authorization.
2. Hard-refresh Creative Studio (`Ctrl+Shift+R`).
3. Confirm response header on `GET /nova/creative` includes `media-src 'self' blob:`.
4. Open the project with the saved commercial → **Load and play saved video (free)** → play full length with narration.
5. In **Review and approve Genova narration**, **Load and listen**, then **Approve narration** if the recording matches the script (note: a ~28s narration file is shorter than a 30s target — re-record or extend before calling it a 30s commercial).
6. Complete visual/caption QC checklist; keep commercial status unpublished until owner approval.
7. Download the finished MP4 as the delivery copy.

No paid Kling credits are required for playback verification of an existing authorized MP4.
