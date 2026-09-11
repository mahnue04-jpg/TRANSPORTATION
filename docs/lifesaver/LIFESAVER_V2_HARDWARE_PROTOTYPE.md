# Lifesaver V2 hardware prototype profile

Local software contract for a future Raspberry Pi-class Home Hub and Car Hub.
This document does not bind the product to one manufacturer, SKU, or vendor API.

Branch: `feature/lifesaver-ai-care-cloud-v2`  
No real hardware is connected in this pass.

## Home Hub prototype

Controller class: Raspberry Pi-class

Modules represented in software:

- camera module
- microphone
- speaker
- rotating-base motor
- power module
- optional battery backup
- optional environmental sensors

Local discovery fields: `device_id`, `device_type`, `hardware_model`, `firmware_version`, `local_ip`, `connection_state`, battery/temperature when present, capability flags, `last_seen_at`.

## Car Hub prototype

Controller class: Raspberry Pi-class or equivalent

Modules represented in software:

- display
- speaker / microphone
- local connectivity
- optional GPS interface later

Car Hub does not steer, brake, throttle, ignite, or lock a vehicle.

## Adapters

The application talks to one command contract. Adapters underneath may be:

- `simulated`
- `local_lan` (allowlisted loopback / private test hosts only)
- `raspberry_pi` (same local contract; no live GPIO yet)
- `offline` fallback

Public internet addresses are rejected by default.

## Mock Pi

In-process routes: `/api/lifesaver/mock-pi/health|status|commands|events`  
Optional localhost runner: `scripts/lifesaver_mock_pi_server.py` on `127.0.0.1:8040`.
