# Lifesaver V2 physical Home Hub bring-up plan

Exact future sequence for attaching one allowlisted Raspberry Pi-class Home Hub on a private LAN.
This document is a plan only. No physical device is attached in this pass.

Default remains `AMICOR_LIFESAVER_HARDWARE_MODE=mock`.  
`local_pi` is local development only. Production forces mock.

Hard stops: no push, merge, Render, production, live Stripe, SMS/email, 911, real camera streaming, or medical-device attachment.

## Preconditions

1. V1 frozen product behavior is unchanged.
2. Lifesaver V2 software adapter `local_pi` exists and is disabled by default.
3. Host is on a private/local LAN and present in `LIFESAVER_LOCAL_DEVICE_ALLOWLIST`.
4. Device is unpaired until a human confirms pairing.
5. A device token exists after pair confirm. Commands require that token (or the owning local session injects the stored token).
6. Command idempotency uses `client_command_id`.
7. Timeout and retry ceiling come from `LIFESAVER_DEVICE_TIMEOUT_MS` and `LIFESAVER_DEVICE_RETRY_CEILING`.
8. Logs are metadata only. Never log credentials, PHI, video, audio, or journal contents.

## Sequence

### A. Assemble Pi

Assemble the compute board, power, cooling, and unused camera/mic/speaker/motor modules as **NOT YET PURCHASED** parts become available. Do not power a motor without a physical stop path.

### B. Boot OS

Boot a local OS image on the bench. Do not enroll the board in a cloud device-management service for this prototype.

### C. Connect LAN

Connect only to a private LAN or loopback test path. Public IPs are rejected by Lifesaver.

### D. Run Amicor Home Hub agent

Start the future on-device agent that speaks the JSON contract in `GET /api/lifesaver/devices/contract`.
Until that agent exists, Lifesaver uses an in-process transport. No raw sockets are opened from the Lifesaver module.

### E. Discover device

`POST /api/lifesaver/devices/discover` with `device_type=HOME_HUB` and an allowlisted private host.
Unknown devices are never auto-trusted.

### F. Pair device

Human `request` then `confirm` with `adapter_type=local_pi`.
Unpaired devices cannot receive Pi commands except `ROTATE_STOP`.

### G. Ping

`DEVICE_PING` / `GET_STATUS`. Expect `COMPLETED` and `acknowledgement=true` on the contract response.

### H. Health check

`GET_DEVICE_HEALTH` and `GET /api/lifesaver/devices/{id}/health`.
Confirm firmware, power, temperature, pairing, camera/mic/privacy, motor, last command, last acknowledgement, last seen, and safety-event status.

### I. Camera test

`CAMERA_ENABLE` / `CAMERA_DISABLE` only. Camera contract stays `stream_ready=false`. Do not store frames. Do not start Zoom/Twilio/WebRTC.

### J. Microphone test

`MIC_ENABLE` / `MIC_DISABLE`. Privacy mode forces microphone off.

### K. Speaker test

`SPEAKER_TEST` / `AUDIO_TEST`. Tone is simulated until a real speaker is attached.

### L. Motor stop test

`ROTATE_STOP` / STOP MOTOR first, including while unpaired or in privacy mode. Stop remains available at all times.

### M. Rotate left / right

`ROTATE_LEFT` / `ROTATE_RIGHT` after stop is proven. Privacy mode blocks new tracking motion.

### N. Rotate home

`ROTATE_HOME` and `ROTATE_TO_ANGLE` at 0 / 45 / 90 / 180 / 270 within min/max limits. No infinite rotation.

### O. Privacy-mode test

`PRIVACY_ENABLE` must turn camera and mic off and block tracking. `PRIVACY_DISABLE` must not enable camera or mic.

### P. Simulated safety-event test

Ingest a hardware contract event (`POSSIBLE_FALL_EVENT` or related). Copy: “Possible safety event — human review required.”
`emergency_services_contacted` stays `false`. No 911.

### Q. Disconnect / reconnect test

Force offline / timeout, confirm retry ceiling, then restore LAN and ping again.

### R. Final prototype acceptance

Accept only when:

- public IPs are rejected
- unpaired and invalid-token commands are rejected
- STOP MOTOR always works locally
- vehicle-control commands are rejected
- no PHI appears in command logs
- V1, Health ISF, Delivery, Freight, Driver 001, Nova Core, and Stripe remain untouched
- no real camera stream, media upload, or emergency-service call occurred

## Environment variables

| Variable | Default | Purpose |
| --- | --- | --- |
| `AMICOR_LIFESAVER_HARDWARE_MODE` | `mock` | `mock` or `local_pi`. Production forces `mock`. |
| `AMICOR_LIFESAVER_PI_HOST` | `127.0.0.1` | Local LAN host used when a device IP is absent. |
| `LIFESAVER_LOCAL_DEVICE_ALLOWLIST` | `127.0.0.1,localhost,::1` | Extra private hosts permitted for discovery/commands. |
| `LIFESAVER_DEVICE_TIMEOUT_MS` | `1500` | Per-attempt timeout (200–5000 ms). |
| `LIFESAVER_DEVICE_RETRY_CEILING` | `2` | Extra attempts after the first (0–3). |

## JSON contract

See `GET /api/lifesaver/devices/contract` and `backend/app/modules/lifesaver/hardware/device_contract.py`.
Camera, sensor, and motor contracts live beside that file and do not activate real hardware.
