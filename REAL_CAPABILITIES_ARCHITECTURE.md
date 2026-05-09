# Real Capabilities Architecture

## Scope

This phase upgrades Amicor from an MVP assistant shell into a live-capability assistant without changing the core runtime, planning, or memory architecture. The existing FastAPI router remains the orchestration seam. The frontend still speaks to the backend through the same `/api/chat`, `/api/upload`, `/api/history/{user_id}`, `/api/reset`, and `/api/health` endpoints.

## Active Capabilities

### Real Web Search
- Entry point: `backend/app/modules/search.py`
- Backend service: `backend/app/web_search.py`
- Providers:
  - Tavily when `TAVILY_API_KEY` is available
  - Google News RSS for live news lookups
  - DuckDuckGo HTML fallback for general search
  - Wikipedia API fallback for factual lookup recovery
- Output:
  - summarized multi-result answer
  - attributed `sources[]`
  - `status` (`success`, `partial`, `error`)
  - provider metadata

### Real Weather
- Entry point: `backend/app/modules/weather.py`
- Backend service: `backend/app/weather.py`
- Providers:
  - Open-Meteo geocoding + forecast
  - IP-based location detection through `ipwho.is`
  - `wttr.in` fallback forecast
- Output:
  - current conditions
  - next-day forecast
  - location-aware response
  - fallback status + provider metadata

### Real Time
- Entry point: `backend/app/modules/time.py`
- Providers:
  - WorldTimeAPI for live timezone-aware time
  - static offset fallback for common cities
  - location detection reused from weather service when explicit city is missing
- Output:
  - locale-like formatted local time
  - scheduling hint for phrases like `in 3 hours` or `tomorrow`
  - timezone metadata

### Real Email Drafting
- Entry point: `backend/app/modules/email.py`
- Storage:
  - `email_drafts` table in SQLite
- Features:
  - subject generation
  - body generation
  - tone detection
  - editable persisted draft state
  - simulated send action only

### Real Upload Parsing
- Endpoint: `POST /api/upload`
- Parsers:
  - UTF-8 text / JSON
  - PDF via `pypdf`
  - DOCX via `python-docx`
- Output:
  - extracted text preview
  - `chunk_count`
  - chunk array for downstream context injection
  - parser diagnostics and truncation flag

### Persistent Memory
- Storage: SQLite via `backend/app/database.py`
- Tables:
  - `messages`
  - `user_preferences`
  - `memory_summaries`
  - `email_drafts`
- Features:
  - persisted chat history
  - lightweight preference extraction
  - rolling conversation summary
  - session continuity through `/api/history/{user_id}`

## Execution Flow

### Chat Execution Flow
1. Frontend `sendMessage()` posts `{ user_id, message }` to `/api/chat`.
2. `backend/app/main.py` calls `route_message()`.
3. `backend/app/router.py` matches the message against the capability registry.
4. The selected capability runs through its existing handler surface.
5. The router normalizes the result into a structured envelope:
   - `tool`
   - `response`
   - `sources`
   - `status`
   - `capability`
   - `meta`
6. User and assistant turns are saved in SQLite.
7. Preference extraction and memory summary update run inline.
8. Frontend renders the reply, source labels, and capability state badges.

### Upload Flow
1. Frontend `AmiCorUpload` validates MIME type and file size.
2. Upload posts to `/api/upload` as multipart form data.
3. Backend selects parser by MIME type.
4. Extracted text is chunked.
5. Diagnostics are returned to the UI.
6. `AmiCorUpload.getExtractedContext()` injects parsed text into the next chat turn.

### Memory Flow
1. Every chat turn is persisted in `messages`.
2. Lightweight preference extraction watches for phrases like `my name is`, `call me`, `I live in`, `I prefer`.
3. A rolling summary is derived from recent history.
4. `GET /api/history/{user_id}` returns:
   - stored messages
   - summary
   - preferences
5. Frontend session restore calls `/api/history/{user_id}` and rehydrates visible conversation state.

## Capability Registry and Orchestration

The orchestration layer remains in `backend/app/router.py`.

Each capability entry now includes:
- trigger keywords
- handler function
- `needs_history`
- permission label
- live capability flag

This preserves the original router architecture while adding:
- capability permissions metadata
- execution status tracking
- graceful error normalization
- source attribution support

## Frontend Capability Feedback

The existing chat UI now exposes execution feedback through:
- tool badges on assistant messages
- source links beneath assistant messages
- capability state pills (`Live capability`, `Live result with fallback`, `Capability error`)
- upload chip diagnostics (`parser • chunks`)
- restored history after session recovery
- existing retry UX for failed requests

## Provider Abstraction Strategy

Provider abstraction is intentionally thin and local:
- `web_search.py` owns search provider fallback order
- `weather.py` owns weather provider fallback order
- `time.py` owns live time + fallback logic
- modules remain simple adapters so routing does not change

This keeps external integrations isolated without creating a new subsystem.

## Future Extension Model

The next capability additions can follow the same pattern:
1. Add a module under `backend/app/modules/`
2. Add a provider/service helper if needed
3. Register it in `backend/app/router.py`
4. Return the standard normalized response envelope
5. Reuse the frontend metadata rendering path

Examples that fit cleanly:
- calendar availability
- OCR for uploaded images
- richer memory summarization with model assistance
- attachment-aware drafting flows
- per-capability permission prompts

## Live Validation Targets

This architecture is validated through `npm run test:capabilities-live`, which covers:
- health availability
- live web search
- live weather
- live time
- email drafting + send simulation
- upload parsing
- history/memory persistence
- service continuity after execution burst
