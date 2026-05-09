# Memory Architecture

## Retrieval Flow

Memory retrieval is asynchronous and layered:

1. Short-term memory is checked first for session-scoped and recent memories.
2. Semantic memory provides ranked recall through a pluggable embedding provider.
3. The retriever merges, deduplicates, and ranks the combined set.
4. The context assembler truncates or summarizes the set to fit the token budget.

## Context Assembly

The assembler converts memory entries into compact context blocks. If the memory set exceeds the available token budget, the compressor retains the highest-value entries and summarizes the rest.

## Summarization Strategy

Summarization is conservative by design:

- preserve the highest-ranked memories first
- summarize overflow into a compact text block
- truncate only after summarization has been attempted
- keep structured metadata alongside the summary result

## Future Vector Integration

The semantic layer uses a mock embedding provider today. The interface is intentionally narrow so a future vector database or external embedding service can be added without changing the manager API.

## Memory Lifecycle

Memory entries move through a simple lifecycle:

- created through `createMemoryEntry`
- stored in the persistence abstraction
- ranked and retrieved asynchronously
- compressed when token pressure is high
- pruned when stale or duplicated

This keeps the system safe for Node-only execution while preserving future extensibility.