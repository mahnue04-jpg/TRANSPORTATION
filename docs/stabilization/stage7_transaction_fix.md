# Stage 7 Transaction Fix

## Root Cause
Recurring scheduling requests generated many rides in a single outer request transaction.
During each ride lifecycle transition, Phase 16 operational event publishing synchronously called event-bus persistence, which opened a second `SessionLocal()` and committed inline.

On SQLite, this produced nested write contention (outer transaction plus inner event persistence commit), causing large teardown/process completion delays after assertions passed.

Observed hot path:

`generate_recurring_rides_for_schedule -> create_ride -> RideLifecycleManager.transition_ride -> publish_phase16_operational_event -> OperationalEventBus._persist_event -> SessionLocal().commit()`

## Affected Files
- `backend/app/modules/health_isf/operational_workflow_orchestration.py`
- `backend/app/modules/health_isf/ride_execution_engine.py`
- `backend/tests/test_health_isf_distributed_sync.py`
- `backend/tests/conftest.py`

## Fix Summary
- Queue Phase 16 events in the active SQLAlchemy session (`session.info`) instead of persisting inline.
- Flush queued events only in `after_commit`.
- Clear queued events on rollback (`after_rollback` and `after_soft_rollback`).
- Preserve event payload shape, role scope, and nonce-based duplicate suppression behavior.

## Before Timings (Isolated Recurring Tests)
- `test_daily_generation`: ~169.52s
- `test_multi_day_generation_custom_weekdays`: ~83.32s
- `test_pause_schedule`: ~171.26s
- `test_resume_schedule`: ~170.27s
- `test_persistence_after_reload`: ~171.95s

## After Timings (Isolated Recurring Tests)
- `test_daily_generation`: ~10.89s
- `test_multi_day_generation_custom_weekdays`: ~10.01s
- `test_pause_schedule`: ~10.60s
- `test_resume_schedule`: ~10.37s
- `test_persistence_after_reload`: ~10.28s

Full class check:
- `TestRecurringTransportationScheduling`: 7 passed in ~9.48s pytest runtime (~12.62s wall clock)

## New Regression Tests
Added in `backend/tests/test_health_isf_distributed_sync.py`:
- `test_phase16_events_persist_only_after_outer_commit`
- `test_phase16_deferred_publish_does_not_create_duplicate_events`

## Validation Outcomes
- Phase 16 events still persist after successful commit.
- Rollback suppresses event persistence.
- Duplicate event suppression still works with deferred queueing.
- Focused distributed sync suite passed.
- Recurring scheduling class passed with no >60s tests.

## Remaining Warnings
- Pydantic v2 deprecation warnings (`class Config`, `json_encoders`, and Field extras).
- `datetime.utcnow()` deprecation warnings in some tests.

No functional Stage 7 failures remain in the targeted validation set.
