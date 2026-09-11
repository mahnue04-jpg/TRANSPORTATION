# Lifesaver V2 Home Hub agent

Local on-device agent package: `hardware/lifesaver-home-hub/`.

- Application name: `lifesaver-home-hub-agent`
- Version: `0.1.0-dev` (Python application, not device firmware)
- Mounted in Lifesaver at `/api/lifesaver/home-hub-agent/*`
- Default hardware mode remains `mock`
- No GPIO, no real camera stream, no 911, no Stripe, no cloud device calls

## Startup

`python hardware/lifesaver-home-hub/scripts/start_local.py` later starts a standalone process.
Today the agent also loads in-process through Lifesaver for local tests.

## Modules

Identity, token validation, health/status, command dispatcher, camera/mic/speaker/motor/sensor abstractions, safety-event emission, metadata-only audit, heartbeat, recovery, self-test, wizard, and emulator faults.
