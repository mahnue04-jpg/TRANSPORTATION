# Lifesaver AI Care Cloud V2 — Build Plan

Branch: `feature/lifesaver-ai-care-cloud-v2`  
Starts from accepted V1 freeze: `c46a7dbb2a90854cd248bf2b06acb5d2a2dcd4ee`  
V1 branch `feature/lifesaver-ai-care-cloud-v1` remains the frozen product line.

## Goal

Turn Lifesaver from a software-only / simulated-reading product into the **foundation** for AMICOR Home Hub and Car Hub integration. This pass adds a hardware abstraction layer. It does **not** require physical hardware, Raspberry Pi, cameras, or vehicle buses.

## This pass

- Lifesaver-owned device domain (`HOME_HUB`, `CAR_HUB`)
- Simulated adapters only
- Authorized, tenant-scoped, audited command contract
- Privacy-first camera/rotation defaults
- Simulated fall / safety review workflow (no 911)
- Local video-session request/accept/decline foundation (no Zoom)
- Devices UI
- Isolation from Health ISF, Delivery, Freight, Driver 001, Nova Core, LIVE Stripe

## Later V2 / V3 (explicitly out of this pass)

Real 911, patient-monitoring claims, facial recognition, diagnosis, hidden surveillance, vendor device APIs, production firmware, OTA, manufacturing, PCB design, and direct automobile control.

## Safety

No push, merge, Render deploy, production DB, live secrets, real email/SMS, emergency services, or real medical devices.

## This-pass implementation

- Module: `backend/app/modules/lifesaver/hardware/`
- Routes: `/api/lifesaver/devices`
- UI: Devices tab + mobile bottom-nav item
- Alembic (local only): `20260911_lifesaver_v2_hardware_schema`, `20260911_lifesaver_v2_bridge_schema`
- Tests: `backend/tests/test_lifesaver_v2_hardware.py`, `backend/tests/test_lifesaver_v2_hardware_bridge.py`
- Interface: `docs/lifesaver/LIFESAVER_V2_HARDWARE_INTERFACE.md`
- Prototype: `docs/lifesaver/LIFESAVER_V2_HARDWARE_PROTOTYPE.md`

V1 remains feature-frozen on `feature/lifesaver-ai-care-cloud-v1`.
