# Lifesaver V2 safety model

Events are non-diagnostic.

Types: `POSSIBLE_FALL`, `INACTIVITY`, `POSTURE_CHANGE`, `DEVICE_TIPPED`, `MOTOR_OBSTRUCTION`, `DEVICE_OFFLINE`, `POWER_LOSS`, `HIGH_TEMPERATURE`.

Lifecycle: `DETECTED` / `NEEDS_REVIEW` → `ACKNOWLEDGED` | `FALSE_ALARM` | `ESCALATION_SIMULATED` | `RESOLVED`.

Copy: “Possible safety event — human review required.”

`emergency_services_contacted` is always `false` on local/test paths. Simulate escalation is labeled **SIMULATION ONLY — NO EMERGENCY SERVICE CONTACT**.
