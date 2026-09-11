# Lifesaver V2 Hardware Interface

Local software contract for future AMICOR Home Hub and Car Hub devices. This pass uses **simulated adapters only**. There is no production-device dependency, no Raspberry Pi requirement, and no live vendor API.

Branch: `feature/lifesaver-ai-care-cloud-v2`  
API prefix: `/api/lifesaver/devices`

## Home Hub contract

Device type: `HOME_HUB`

Capabilities represented in software:

- touchscreen
- camera (defaults **off**)
- microphone (defaults **off**)
- speaker
- motorized rotating base
- motion / proximity sensing
- orientation / IMU
- Wi-Fi
- Bluetooth
- privacy mode
- device health
- simulated fall / event input

Commands: `DEVICE_PING`, `GET_STATUS`, `GET_DEVICE_HEALTH`, `CAMERA_ENABLE`, `CAMERA_DISABLE`, `MIC_ENABLE`, `MIC_DISABLE`, `PRIVACY_ENABLE`, `PRIVACY_DISABLE`, `ROTATE_LEFT`, `ROTATE_RIGHT`, `ROTATE_HOME`, `ROTATE_STOP`, `AUDIO_TEST`, `SENSOR_SAMPLE`, `SET_MOTION`, `SET_ONLINE`, `SET_OFFLINE`, `START_VIDEO_SESSION`, `END_VIDEO_SESSION`, `SIMULATE_FALL_EVENT`, `DEVICE_RESTART_SIMULATED`

This is not a medical device and is not a certified fall detector.

## Car Hub contract

Device type: `CAR_HUB`

Capabilities represented in software:

- display
- microphone
- speaker
- network connectivity
- Nova / Lifesaver interface (simulated link status only)
- device health
- safe vehicle-use mode

Commands: `DEVICE_PING`, `GET_STATUS`, `GET_DEVICE_HEALTH`, `AUDIO_TEST`, `CONNECTION_TEST`, `SAFE_MODE_ENABLE`, `SAFE_MODE_DISABLE`, `DISPLAY_ENABLE`, `DISPLAY_DISABLE`, `PRIVACY_ENABLE`, `PRIVACY_DISABLE`, `SET_ONLINE`, `SET_OFFLINE`, `LIFESAVER_LINK_STATUS`, `NOVA_LINK_STATUS`, `DEVICE_RESTART_SIMULATED`

Car Hub does **not** control the vehicle. No CAN, OEM, or steering/braking interface exists.

## Privacy model

1. Camera defaults off unless explicitly enabled.
2. Privacy mode disables camera, rotation tracking, and passive observation simulation.
3. Camera state is always visible in the Devices UI.
4. Rotation always accepts `ROTATE_STOP`.
5. No automatic 911 calls.
6. Fall / emergency workflow is simulation only.
7. No continuous recording.
8. No hidden recording.
9. No hidden microphone activation.
10. Hardware actions write safe audit metadata only. Video and audio content are never stored.

## Camera state model

Stored on the simulated device as `camera_enabled` (boolean). Serialized as `camera_state: on|off`. Privacy mode forces `off` even if an enable command is sent. The UI always renders Camera ON/OFF in bold.

## Rotation command model

`ROTATE_LEFT` / `ROTATE_RIGHT` set a simulated heading and `rotation_moving=true`.  
`ROTATE_HOME` returns heading `home` and stops motion.  
`ROTATE_STOP` always succeeds, including during privacy mode.  
Privacy mode blocks new tracking motion.

## Simulated fall workflow

`SIMULATE_FALL_EVENT` (Home Hub only):

1. Create a Lifesaver safety event with status `needs_human_review`.
2. Copy: “Possible fall or safety event detected. Human review required.”
3. Show the event on Care Coordination as HIGH.
4. Queue a `LOCAL_SIMULATION` caregiver notification (`safety_event_review`).
5. Display local confirm / review controls.
6. `emergency_services_contacted` remains `false`.

No injury diagnosis. No claim that a fall definitely occurred. No 911, SMS, or email send.

## Video communication foundation

Local session-request model only: request → accept / decline. Accept requires camera on and privacy mode off. Provider is `local_simulation`. No Zoom or other paid provider is connected. `media_stored` is always false.

## Hardware serial / identity strategy

Each simulated device receives a tenant-scoped `serial_number` (default `SIM-{TYPE}-{id}`) unique per organization. Future physical hubs should present the same fields: `device_id`, `organization_id`, optional `profile_id`, `device_type`, `display_name`, `serial_number`, `firmware_version`, `software_version`, `status`, `last_seen_at`.

Do not reuse Health ISF vehicle IDs, Delivery IDs, Freight shipment IDs, or Driver 001 identifiers.

## Future Raspberry Pi communication strategy

When hardware arrives, a local Pi agent should speak this same command/event contract over a private LAN:

- Pi hosts a loopback or LAN HTTP/WebSocket endpoint
- Cloud/Lifesaver talks only to a tenant-authorized adapter
- Commands remain authorized, audited, and privacy-gated
- Media stays on-device unless a later consented provider is added

This pass does not implement the Pi agent.

## Future local-network / API strategy

Keep adapters behind `backend/app/modules/lifesaver/hardware/adapters/`. Replace `simulated_home_hub` / `simulated_car_hub` with LAN adapters that map the same command names. Do not introduce vendor SDKs, OTA, or production firmware in this foundation.

## Device health

`GET /api/lifesaver/devices/{id}/health` returns online, last seen, software/firmware versions, adapter status, camera/microphone/speaker/motor/sensor availability, privacy mode, and warnings. `external_device_contacted` is always false. `medical_certified` is always false.

## No production-device dependency yet

V2 software can be developed and tested without physical hardware, Raspberry Pi units, cameras, motors, or vehicles. Real device attach is a later V2/V3 task.
