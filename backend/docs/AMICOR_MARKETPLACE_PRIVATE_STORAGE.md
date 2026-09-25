# AMICOR Marketplace private storage

## Purpose
Paid and free customer deliverables must not be committed to GitHub or served from a public static directory.

## Required runtime setting
Set `AMICOR_MARKETPLACE_PRIVATE_DIR` to a persistent, non-static directory on the deployed service.

The directory must:
- persist across application restarts and deploys;
- not be mounted under `backend/static`;
- be writable by the backend process;
- be excluded from public web serving.

## Owner upload
After deployment, an authenticated ADMIN or SUPER_ADMIN_SUPPORT user opens:

`/nova/marketplace/admin`

Upload each approved PDF. The backend verifies PDF signature, exact byte size, and SHA-256 against the approved manifest. Wrong or modified files are rejected.

## Payment gate
- Free checklist: download becomes available only after its approved file verifies.
- Paid products: a verified file is necessary but not sufficient. Stripe remains TEST-only.
- Paid download additionally requires a paid purchase and valid entitlement.
- Live Stripe is not enabled by this migration.

## Deployment warning
Do not point `AMICOR_MARKETPLACE_PRIVATE_DIR` at ephemeral storage. If persistent private storage is unavailable, leave marketplace files unconfigured and checkout unavailable.
