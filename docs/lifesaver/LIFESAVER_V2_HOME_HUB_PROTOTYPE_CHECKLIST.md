# Lifesaver V2 Home Hub prototype shopping / assembly checklist

Local physical-prototype shopping list for a future AMICOR Home Hub.
No SKU, vendor, or purchased part is locked in this document.

**Status of every physical item below: NOT YET PURCHASED.**

Branch: `feature/lifesaver-ai-care-cloud-v2`  
Hardware mode default: `AMICOR_LIFESAVER_HARDWARE_MODE=mock`  
This checklist does not authorize production, 911, live camera streaming, or medical-device attachment.

## Raspberry Pi / compute board

- [ ] Raspberry Pi-class compute board — **NOT YET PURCHASED**
- Exact board, memory, and wireless variant are not chosen.

## Power supply

- [ ] Official-class USB-C / barrel supply matched to the chosen board — **NOT YET PURCHASED**
- [ ] Surge-protected outlet strip — **NOT YET PURCHASED**

## Display

- [ ] Small local preview / status display (size and touch not chosen) — **NOT YET PURCHASED**
- Software camera preview remains disabled until a later pass.

## Camera

- [ ] Camera module compatible with the chosen board — **NOT YET PURCHASED**
- Do not enable a real stream until the camera contract is accepted and privacy gates are re-verified.

## Microphone

- [ ] USB or board-compatible microphone — **NOT YET PURCHASED**
- Microphone stays off unless explicitly enabled and privacy mode is off.

## Speaker

- [ ] Small speaker or USB audio output for speaker-test tones — **NOT YET PURCHASED**

## Motor / pan base

- [ ] Rotating / pan base with known min/max travel — **NOT YET PURCHASED**
- Infinite rotation is not supported unless later specified.

## Motor controller

- [ ] Controller / driver matched to the chosen motor — **NOT YET PURCHASED**
- Software already models angle, direction, speed profile, obstruction, timeout, stop, and home.

## Enclosure

- [ ] Protective enclosure for board, camera, and base — **NOT YET PURCHASED**
- Prefer an internal, non-shared build folder for any later drawings.

## Wiring

- [ ] Power, camera, audio, and motor wiring harness — **NOT YET PURCHASED**
- [ ] Strain relief and labeled connectors — **NOT YET PURCHASED**

## Cooling

- [ ] Heatsink and/or case fan if the chosen board requires it — **NOT YET PURCHASED**

## Local network

- [ ] Private LAN or dedicated test switch — **NOT YET PURCHASED**
- Public IPs are rejected. Allowlisted loopback / RFC1918 / link-local only.

## Emergency stop / physical stop consideration

- [ ] Physical stop or power-interrupt path that can cut motor power — **NOT YET PURCHASED**
- Software `ROTATE_STOP` / STOP MOTOR remains available at all times in the local UI.

## Optional battery backup

- [ ] UPS or battery pack for brief outage testing — **NOT YET PURCHASED**
- Optional. Default software power state is mains.

## Mounting hardware

- [ ] Table / wall / stand mounts and fasteners — **NOT YET PURCHASED**

## Tools

- [ ] Basic electronics tools (driver set, snips, multimeter) — **NOT YET PURCHASED** if not already on the bench
- Do not list specific brands here.

## 3D-printed enclosure parts

- [ ] Printed shell, camera hood, and base collar — **NOT YET PURCHASED / NOT YET PRINTED**
- Files are not selected. Print only after enclosure dimensions are chosen.

## Software / local safety (already in repo)

- Default hardware mode is `mock`.
- `local_pi` is explicit local-dev only and stays off in production.
- No Stripe, SMS, email, 911, or cloud device calls.
- No video or audio content is stored.
