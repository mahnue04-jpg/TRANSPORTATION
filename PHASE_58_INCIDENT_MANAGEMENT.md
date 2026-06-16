# PHASE 58 INCIDENT MANAGEMENT

## Objective
Add realtime operational incident classification and command-center visibility while preserving transport runtime contracts.

## Detection Model (Existing Runtime State Only)
Incident signals are derived from existing frontend/runtime state sources:
1. state.rides
2. state.dispatchActiveAssignments
3. state.operationalEventFeed
4. state.runtimeReplay
5. state.hydration
6. state.websocketStatus
7. state.reconnectAttempt

## Incident Classes Implemented
1. delayed_rides
2. stalled_assignments
3. reconnect_storm
4. websocket_degradation
5. replay_backlog_pressure
6. dispatcher_overload
7. hydration_timeout_recovery
8. orphaned_ride_ownership

## Severity Levels
1. info
2. warning
3. critical

Severity rendering is mapped to command-center tones for immediate operator triage.

## Bounded Retention
1. Timeline retention and processing are bounded via PHASE 58 retention/window controls.
2. Unified timeline uses finite retained entries (default bounded retention).
3. Timeline display uses a bounded window with navigation controls instead of rendering full history.

## Unified Timeline Behavior
1. Merges chronology from:
   - realtime transport events
   - dispatch timeline events
   - ride risk signals
   - incident entries
2. Supports filters:
   - severity
   - role
   - category
   - search query
3. Supports windowing:
   - newer window
   - older window
4. Preserves no-polling-loop behavior (rendered from existing update cycles/state refresh).

## Role-Aware Visibility
Timeline and incident entries are tagged with operator roles:
1. dispatcher
2. driver
3. supervisor
4. system

## Recovery-Aware Incident Overlay
Recovery banner layer surfaces active state for:
1. reconnect recovery
2. replay synchronization
3. websocket degradation
4. hydration recovery
5. stale event protection

## Result
PHASE 58 incident management provides realtime, bounded, role-aware operational triage visibility without backend rewrites or contract changes.
