# Operational Automation Report

**Status:** Completed
**System:** Amicor Health ISF
**Focus:** Workflow automation, escalation management, self-healing operations

## Summary

The Health ISF module now has an operational automation layer that can detect abnormal ride conditions, generate workflow executions, escalate unresolved incidents, and replay dead-letter events. The implementation is tenant-scoped, auditable, and wired into the existing realtime dispatcher infrastructure.

## Operational Capabilities

### Workflow Recovery

- Detects stuck or delayed rides
- Creates workflow executions and incident records
- Supports dry-run and active recovery modes
- Broadcasts completion events to websocket subscribers

### Reassignment Automation

- Builds driver recommendations from operational intelligence
- Executes reassignment when policy allows it
- Creates escalation records when no safe reassignment is available

### Escalation Management

- Routes incidents to dispatcher-oriented escalation queues
- Records escalation level, target role, and status
- Preserves audit history for review and compliance

### Dead-Letter Replay

- Replays dead-letter events through the retry queue
- Preserves organization scoping
- Emits workflow replay completion events

### Policy Engine

- Persists tenant-scoped automation policies
- Supplies default policy values when none exist
- Supports approval, escalation, and replay controls

## Realtime Integration

- Workflow events reuse the existing websocket broadcaster
- Permitted roles can subscribe to workflow and incident updates
- Realtime payloads remain organization-scoped

## Persistence Layer

New tables are additive only and map directly to the workflow control plane:

- Workflow executions
- Workflow incidents
- Workflow escalations
- Automation policies
- Workflow audit logs

## Validation Results

The following slice passed after the final fixes:

```bash
cd backend
pytest tests/test_health_isf_workflow_automation.py -vv
```

## Rollout Notes

- Apply the workflow automation Alembic migration before deploying.
- Keep the websocket broadcaster and retry queue services initialized with the existing Health ISF startup flow.
- Validate tenant-scoped access for dispatcher and admin users before enabling operational use.
