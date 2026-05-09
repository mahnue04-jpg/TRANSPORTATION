# Productivity and Business Capability Layer

## Scope

This layer adds practical capability workflows under `backend/static/capabilities` without modifying core runtime, memory, planning, assistant, or backend architecture.

Implemented capabilities:
- document workflow
- task management
- scheduling assistance
- email drafting
- business summarization
- report generation
- workflow templates
- research assistance

## Workflow Execution Model

1. `capabilityRouter.js` receives a structured capability request.
2. Request is normalized by `capabilitySchemas.js`.
3. Capability is selected explicitly or inferred from goal text.
4. Capability module builds a multi-step workflow definition.
5. Router passes tasks through planning (`createTaskPlanner`) and execution (`createWorkflowEngine`).
6. Results are persisted with history metadata and optional memory/conversation hooks.
7. Router streams user-facing summary chunks via `onStreamChunk` callback.

## Capability Routing Model

Routing supports two paths:
- direct capability invocation (`capability` provided)
- inferred capability invocation (goal-based inference)

Template path:
- `workflowTemplates.js` provides reusable workflows
- templates instantiate concrete tasks and context variables
- required templates include:
  - business startup checklist
  - proposal drafting
  - invoice workflow
  - meeting preparation
  - document summarization
  - action-item extraction

## Integrations

The router integrates with existing foundation layers via dependency injection:
- assistant layer: optional adapter hook for higher-level orchestration
- planning layer: task planning and workflow validation/execution
- memory system: contextual retrieval and workflow memory persistence
- tool runtime: execution through planning/workflow engine and tool selection
- conversation layer: workflow and execution event persistence to session history

## Memory Integration

Before workflow build:
- assemble memory context for request goal
- retrieve relevant memories for continuity

After execution:
- persist workflow memory entries (`addWorkflowMemory` when available)
- include memory context in capability results for downstream response generation

## Persistence, Interruption, Recovery

Router persistence:
- stores workflow records and execution outcomes
- supports listing persisted workflows

Interruption:
- active workflow registry supports cancellation
- `interruptWorkflow(workflowId)` propagates cancellation to workflow engine

Recovery and continuation:
- `continueWorkflow(workflowId)` replays persisted snapshots for continuation attempts
- designed for partial failure handling and user-invoked recovery flows

## Safety and Determinism

- malformed and conflicting requests are blocked early
- deterministic workflow/task structures per capability
- bounded timeout budgeting via request config
- no autonomous recursive agents
- no unrestricted browser automation
- no self-modifying behavior

## Extensibility

New capabilities can be added by:
1. creating a capability module that returns `goal`, `summary`, and `tasks`
2. registering the module in `capabilityRouter.js`
3. adding template mappings when needed
4. validating behavior in capability tests and benchmarks
