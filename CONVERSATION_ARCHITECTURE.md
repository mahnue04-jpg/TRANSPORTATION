# Conversation and UI Integration Layer

## Scope

This layer integrates assistant execution, planning, memory, tool activity, streaming, and workflow state visibility into a frontend conversation experience under `frontend/src/conversation`.

It preserves the existing backend architecture and does not add autonomous agents, browser automation, self-modifying behavior, or recursive autonomy.

## Frontend Execution Flow

1. `ConversationController.jsx` receives a user goal.
2. User message is persisted to `ConversationStore.js`.
3. Controller invokes the assistant adapter (connected to the assistant execution stack).
4. Streaming chunks are forwarded to `StreamingRenderer.jsx` and persisted as an in-progress assistant message.
5. Final assistant result updates:
- assistant state
- workflow timeline
- tool activity feed
- execution event feed
- memory context panel
6. Session snapshot is persisted for resumable conversations.

## Streaming Integration Model

`StreamingRenderer.jsx` provides non-blocking token rendering with buffered flushes:
- frequent token appends are batched by interval
- interrupt clears pending tokens and halts updates
- finalize commits remaining buffered tokens
- snapshot surfaces render health and buffer stats

This avoids blocking renders during rapid token updates and supports interruption controls.

## Workflow Visualization Model

`WorkflowTimeline.jsx` builds visual workflow state from execution snapshots:
- task graph nodes (`id`, `type`, `status`, `tool`, retries)
- dependency edges
- progress model (completed/failed/cancelled/running)
- deterministic progress percentage

## Tool Activity and Execution Feed

- `ToolActivityPanel.jsx` classifies and renders tool activity categories:
- filesystem actions
- search operations
- document processing
- workflow steps

- `ExecutionFeed.jsx` normalizes timeline events:
- assistant state transitions
- cancellation/retry events
- workflow status updates
- recovery and desync correction events

## Memory Display Model

`MemoryContextPanel.jsx` surfaces contextual memory usage with:
- retrieved summary text
- continuity indicators
- overflow/truncation indicators when context budgets are exceeded

This preserves session continuity visibility without exposing raw backend internals.

## Recovery and Interruption Handling

`ConversationRecovery.jsx` and controller actions support:
- cancel response
- cancel workflow
- retry workflow
- resume saved session
- desync recovery with safe terminal fallback

`ConversationStore.js` includes deterministic state desync recovery and capped history trimming for large sessions.

## Persistence Model

`ConversationStore.js` persists sessions with:
- saved session list
- active session pointer
- resumable message/workflow/tool histories
- bounded retention for scalable long-running conversations

Storage abstraction supports browser localStorage or injected adapters for tests.

## Performance and Scalability Controls

- bounded message/feed lengths
- batched token flushes
- deterministic ordering of timeline/tool/feed records
- snapshot-based render models
- no blocking synchronous UI loops

## Future Integration Notes

The layer is ready for future richer UI rendering and agent-assisted workflows, while retaining strict controls and deterministic behavior. Any future expansion should preserve:
- bounded recursion
- explicit user control for cancellation
- evidence-linked execution outputs
- architecture boundaries between frontend integration and backend systems
