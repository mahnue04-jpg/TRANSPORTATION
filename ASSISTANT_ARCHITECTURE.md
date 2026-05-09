# Assistant Execution Layer

## Scope

This layer provides controlled assistant execution in `backend/static/assistant` with deterministic behavior and strict safeguards. It intentionally does not implement autonomous recursive agents, self-modifying behavior, or browser autonomy.

## Execution Lifecycle

1. `assistantController.js` receives a request and loads conversation state.
2. `assistantExecutor.js` transitions state through:
- `interpreting`
- `planning`
- `executing`
- `responding`
- terminal state (`completed`, `failed`, `interrupted`)
3. `goalInterpreter.js` normalizes goal text into objective clauses.
4. `intentParser.js` converts clauses into task intents and rejects conflicts.
5. `contextManager.js` composes bounded context from conversation + memory.
6. `executionCoordinator.js` creates a structured workflow plan and executes it via planning engine.
7. `responseSynthesizer.js` merges tool outputs into a user-facing response and streams chunks.

## Context Flow

- Input context sources:
- user goal
- recent conversation history
- memory layer context assembly

- Context controls:
- token estimation and max token clipping
- overflow signaling for response transparency
- deterministic ordering of context segments

## Reasoning Flow

The user-facing reasoning pipeline returns structured reasoning steps (`reasoningTrace`) rather than hidden autonomous behavior.

Typical reasoning phases:
- goal interpretation summary
- intent parsing summary
- planning and validation outcomes
- execution status summary
- response synthesis evidence status

## Safety Model

` safetyGuardrails.js` enforces:

- recursion prevention by limiting task expansion patterns
- max workflow depth guard
- timeout budget guard
- tool permission validation against runtime tool metadata
- forbidden autonomous/self-modifying instruction patterns
- hallucination resistance via evidence checks between execution summary and synthesized claims

Additional controls:
- deterministic tool/task ordering from planning layer
- cancellation propagation using conversation/request interrupt signals
- no unrestricted loops or autonomous self-prompting

## Integrations

- Planning layer: `createTaskPlanner` + `createWorkflowEngine`
- Memory layer: context assembly and workflow memory writes
- Tool runtime: tool discovery + execution through planning engine
- Orchestrator: state and lifecycle events via `onAgentEvent`
- Streaming engine: chunk-based response streaming hooks

## Recovery and Interruption

- Interruption:
- request-level interrupt flag
- conversation-level interrupt state
- workflow cancellation propagation

- Recovery:
- transient failures can recover on subsequent deterministic re-execution
- response synthesis falls back safely when output is malformed
- workflow-level recovery remains delegated to planning/workflow state recovery

## Future Agent Integration

Prepared extension points are available for future agent composition while preserving controls:
- richer intent routing strategies
- specialized planner policies
- additional safe tool domains

These are explicitly deferred and must retain the same bounded execution and safety contract.
