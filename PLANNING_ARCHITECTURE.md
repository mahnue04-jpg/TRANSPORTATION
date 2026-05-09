# Planning and Workflow Foundation

## Scope

This module adds a deterministic Node-compatible planning and execution foundation in `backend/static/planning` without rewriting runtime, memory, or orchestrator cores.

## Workflow Lifecycle

1. Planning request enters `planner.js` with goal, context, and candidate tasks/steps.
2. Context-aware planning enriches task context from the memory manager (`retrieve` + `assembleContext`).
3. Tool assignment is resolved through `toolSelector.js` against `AmiCorToolRuntime` registry and permission gates.
4. `planningValidator.js` validates safeguards before execution.
5. `workflowEngine.js` executes tasks through `AmiCorToolRuntime.execute(...)` using dependency ordering.
6. `executionTracker.js` records workflow and task events with deterministic sequence IDs.
7. Workflow ends in terminal state: `completed`, `failed`, or `cancelled`.

## Execution Flow

- `taskGraph.js` builds directed graph (`dependencies -> task`) and performs cycle checks.
- `dependencyResolver.js` computes deterministic ready queues sorted by priority then task ID.
- `workflowState.js` owns mutable state transitions and snapshot/recovery.
- `workflowEngine.js` applies:
  - conditional execution (`task.condition`)
  - branching via graph fan-out
  - retry scheduling and fallback handling
  - timeout budgeting and cancellation propagation

Execution is deterministic by design:
- no random scheduler decisions
- stable sorting for ready tasks
- bounded loops with terminal-state checks

## Recovery Strategy

`recoveryPlanner.js` provides three recovery modes:

1. Retry planning
- exponential backoff from task retry config
- max retry cap per task

2. Fallback planning
- optional fallback task (`fallbackTaskId`)
- original task can be marked recovered if fallback completes

3. Partial continuation
- downstream tasks can continue if `allowPartialContinuation` is true
- non-optional dependents are blocked after unrecoverable failure

`workflowState.js` also includes corruption recovery:
- invalid workflow/task statuses are normalized
- missing task entries are reconstructed from schema defaults

## Planning Constraints and Safeguards

Implemented in `planningValidator.js`:

- recursion limits (`recursionLimit`)
- execution depth limits (`executionDepthLimit`)
- timeout budgeting (`timeoutBudgetMs`)
- tool permission validation (via `toolSelector.js`)
- cycle detection (via `taskGraph.js`)

These safeguards prevent unbounded execution and enforce controlled planning behavior.

## Integration Points

- Runtime integration: `workflowEngine.js` executes through `AmiCorToolRuntime`.
- Memory integration: planner enriches with memory context; engine records workflow completion memory events.
- Orchestrator integration: planner/engine emit workflow lifecycle events when an orchestrator emitter is supplied.

## Workflow Visualization Schema

`planningSchemas.js` exposes `createWorkflowVisualization(workflow)` returning:
- `schemaVersion`
- `workflowId`
- `workflowStatus`
- `nodes[]` (`id`, `label`, `status`, `priority`, `assignedTool`)
- `edges[]` (`from`, `to`, `type`)
- `generatedAt`

This schema is intentionally tool-agnostic so future UI or diagnostics layers can consume it.

## Future Agent Integration (Not Implemented)

This foundation is prepared for later agent orchestration but intentionally excludes:
- autonomous self-prompting
- self-modification
- recursive agents
- unrestricted loops
- browser automation

Future integration can mount agent strategies on top of the existing validated planner and workflow engine boundaries.
