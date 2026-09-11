# Lifesaver V2 device protocol

Shared command vocabulary between Lifesaver and the Home Hub agent.

Commands: `DEVICE_PING`, `GET_STATUS`, `GET_DEVICE_HEALTH`, `CAMERA_ENABLE`, `CAMERA_DISABLE`, `MIC_ENABLE`, `MIC_DISABLE`, `AUDIO_TEST` / `SPEAKER_TEST`, `PRIVACY_ENABLE`, `PRIVACY_DISABLE`, `ROTATE_LEFT`, `ROTATE_RIGHT`, `ROTATE_HOME`, `ROTATE_TO_ANGLE`, `ROTATE_STOP` / `STOP_MOTOR`, `DEVICE_RESTART`.

Lifecycle: `QUEUED` → `SENT_LOCAL` → `RECEIVED` → `ACKNOWLEDGED` → `EXECUTING` → `COMPLETED` | `FAILED` | `TIMED_OUT` | `CANCELLED` | `REJECTED`.

Agent routes: `GET /health`, `GET /status`, `GET /capabilities`, `POST /commands`, `GET /commands/{id}`, `POST /events`, `GET /events/recent`.

Public IPs are rejected. Tokens are required for paired-device commands except `STOP MOTOR`.
