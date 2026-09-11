# Lifesaver V2 failure recovery

Handled locally: network outage, agent restart, duplicate/stale/timed-out commands, reboot, invalid token, expired pairing, offline device, camera unavailable, motor fault, overheating simulation.

Rules:

- STOP MOTOR has highest priority
- Network loss stops simulated motion
- Retry ceiling is 0–3
- No infinite loops
- Recovery never silently overrides privacy
- Offline UI: `OFFLINE — CLOUD CONNECTION UNAVAILABLE`
- Cloud actions must not report success while offline
