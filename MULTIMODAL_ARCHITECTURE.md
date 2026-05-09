# Amicore Multimodal Architecture

> **Status:** Production — implemented in `main` branch

---

## 1. Image OCR Pipeline

### Entry Point

`POST /api/upload` → `_extract_upload_text()` in `backend/app/main.py`

### Provider Chain

```
Upload (image/png, image/jpeg, image/webp)
    │
    ▼
app.image_ocr.extract(content_type, bytes)
    │
    ├─ [1] OpenAI Vision (gpt-4o-mini)
    │       Input: base64 data URL
    │       Output: {text, description, method:"vision_api", confidence:0.92, word_count}
    │       Prompt: extracts TEXT: and DESCRIPTION: sections
    │
    ├─ [2] Tesseract OCR (optional, graceful fail)
    │       Requires: pytesseract + Pillow installed
    │       Output: {text, method:"tesseract", confidence:0.75}
    │
    └─ [3] Metadata Fallback
            Pure Python struct-parsing (no external deps)
            Handles: PNG IHDR, JPEG SOF, WEBP VP8L
            Output: {method:"metadata", image dimensions, format}
```

### Context Block Format

`image_ocr.build_context_block(filename, result)` produces:

```
[Image: photo.png]
Visual description: A chart showing quarterly revenue trends…
Extracted text:
Q1: $1.2M
Q2: $1.8M
…
```

This block is injected into the chat message before sending to OpenAI.

### OCR Response Fields

| Field | Type | Description |
|---|---|---|
| `method` | str | `vision_api`, `tesseract`, or `metadata` |
| `confidence` | float | 0.0–1.0 quality estimate |
| `word_count` | int | Words extracted |
| `text` | str | Raw extracted text |
| `description` | str | Visual scene description |
| `diagnostics` | dict | Provider-specific debug info |

### Upload Response (images)

```json
{
  "filename": "invoice.png",
  "content_type": "image/png",
  "size_bytes": 84231,
  "extracted_text": "[Image: invoice.png]\nVisual description…",
  "status": "uploaded",
  "ocr": {
    "method": "vision_api",
    "confidence": 0.92,
    "word_count": 47,
    "description": "A scanned invoice…",
    "has_text": true
  }
}
```

---

## 2. Provider Resilience System

### Location

`backend/app/providers/resilience.py`

### Components

#### `CircuitBreaker`

```
States:
  CLOSED    — normal operation, requests pass through
  OPEN      — provider is unhealthy, requests blocked
  HALF_OPEN — probe state, one request allowed to test recovery
```

**Transition rules:**

| From | To | Trigger |
|---|---|---|
| CLOSED | OPEN | failure_count ≥ failure_threshold in rolling window |
| OPEN | HALF_OPEN | recovery_timeout seconds elapsed |
| HALF_OPEN | CLOSED | probe succeeds |
| HALF_OPEN | OPEN | probe fails |

**Configuration per provider:**

| Provider | failure_threshold | recovery_timeout |
|---|---|---|
| open-meteo | 3 | 30s |
| wttr.in | 4 | 20s |
| tavily | 3 | 30s |
| google_news | 3 | 60s |
| duckduckgo | 4 | 20s |
| wikipedia | 5 | 60s |

#### `RetryBudget`

- `max_retries=2` per request
- Exponential backoff: `base_delay * (2 ** attempt)` seconds
- Used by `resilient_call()` before trying next provider

#### `resilient_call(providers, *args, retry_budget, **kwargs)`

Iterates provider list, skips OPEN breakers, retries within budget.
Raises `RuntimeError` if all providers fail.

#### `get_breaker(name, failure_threshold, recovery_timeout)`

Global singleton per process — thread-safe, shared across requests.

#### `all_diagnostics()`

Returns state snapshot for all registered breakers:
```json
{
  "open_meteo": {"state": "CLOSED", "health_score": 0.95, "failure_count": 1, "total_calls": 42},
  "tavily":     {"state": "OPEN",   "health_score": 0.1,  "failure_count": 3, "total_calls": 10}
}
```

### Health Endpoint

```
GET /api/diagnostics/providers
→ {"providers": {...}, "version": "dev"}
```

---

## 3. Response Streaming

### Endpoint

```
POST /api/chat/stream
Content-Type: application/json
→ text/event-stream
```

### Protocol

```
data: {"type": "token",    "content": "Hello"}
data: {"type": "token",    "content": " world"}
data: {"type": "complete", "reply": "...", "tool": "weather", "sources": [...], "meta": {...}}
data: {"type": "error",    "content": "Provider unavailable"}
data: [DONE]
```

- **Tool calls** (weather, search, news, etc.) → single `complete` event
- **OpenAI chat** → incremental `token` events, then `[DONE]`

### Fallback Logic

The streaming endpoint checks `CAPABILITIES` triggers first. If a capability matches, it runs via `route_message()` and emits a single `complete` event. Otherwise, it opens an OpenAI stream with `gpt-4o-mini` and yields tokens incrementally.

---

## 4. Memory Quality

### Summarization (`router.py: _summarize_history`)

**For histories ≥ 4 messages with OpenAI available:**
- Calls `gpt-4o-mini` with a compression prompt (max 180 tokens)
- Produces 1–3 sentence factual summary
- Stored in `memory_summaries` table per `user_id`

**Fallback (no API key or error):**
- Extractive heuristic: last 3 user topics + last 2 assistant replies
- Capped at 800 characters

### Preference Extraction

`_extract_preferences()` parses intent phrases:
- `"my name is …"` → `name`
- `"call me …"` → `preferred_name`
- `"i live in …"` → `location`
- `"i prefer …"` → `preference`
- `"i work in …"` → `industry`
- `"i am a …"` → `role`

---

## 5. Degraded Mode Behaviour

| Scenario | Behaviour |
|---|---|
| All weather providers OPEN | Returns error string with health scores |
| All search providers OPEN | Returns error with provider error list |
| OpenAI vision unavailable | Falls back to Tesseract, then metadata |
| Tesseract not installed | Silently falls through to metadata |
| OpenAI chat down | Stream emits `{"type":"error"}` event |
| History summarization fails | Uses extractive fallback, does not crash |

---

## 6. Supported File Types

| MIME type | Parser |
|---|---|
| `text/*`, `application/json` | UTF-8 decode |
| `application/pdf` | pypdf |
| `application/vnd.openxmlformats-officedocument.wordprocessingml.document` | python-docx |
| `image/png`, `image/jpeg`, `image/webp` | image_ocr (vision → tesseract → metadata) |

---

## 7. Running Tests

```bash
# All existing tests (178 pass)
npm run test:unit
npm run test:integration

# Multimodal — OCR pipeline, image upload, context injection
npm run test:multimodal

# Resilience — circuit breaker states, fallback chains, health scoring
npm run test:resilience

# Provider benchmarks — response times, fallback frequency
npm run benchmark:providers
```
