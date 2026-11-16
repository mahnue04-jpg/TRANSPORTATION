# Receptionist owner status panel (pilot UI)

Static owner dashboard slice for the Nova Growth Agent receptionist pilot. Ships as additive assets on `/nova/growth` — no live PSTN or customer outreach.

## Files

| Asset | Role |
| --- | --- |
| `backend/static/nova-growth/receptionist.js` | Panel logic, API wiring, `window.NovaReceptionist` |
| `backend/static/nova-growth/receptionist.css` | Mobile-friendly grid and simulated voice banner |
| `backend/static/nova-growth/index.html` | Receptionist panel section + asset includes |
| `backend/static/nova-growth/growth.js` | `signOut()` calls `NovaReceptionist.clearState()` |
| `backend/static/nova-growth/receptionist.test.cjs` | Node `node:test` coverage |

## Owner flows

1. **Sign in** — same bearer session as the rest of the Growth dashboard (`amicor_growth_token`).
2. **Setup wizard** — FAQs and operating hours remain the source of truth; the receptionist panel summarizes counts and links to `#setup-wizard`.
3. **Receptionist panel** — refresh loads parallel GETs for status, sync errors, notifications, and handoffs.
4. **Calendar** — explicit **Not connected** when OAuth is missing or disconnected; connect/disconnect call the calendar OAuth routes (server may return 404 until backend lands).
5. **Handoffs** — queue with per-row **Acknowledge** → `POST .../handoffs/{id}/acknowledge`.
6. **Agent pause/disable** — display-only in this panel; owners still use Setup wizard **Pause**, **Disable**, and **Resume** buttons.
7. **Voice simulator** — banner **SIMULATED — not a live phone call**; `POST .../voice/simulator/run` with `simulated: true`.

## API paths (future / staging)

| Method | Path |
| --- | --- |
| GET | `/api/nova/growth-agent/receptionist/status` |
| POST | `/api/nova/growth-agent/calendar/oauth/start` |
| POST | `/api/nova/growth-agent/calendar/disconnect` |
| GET | `/api/nova/growth-agent/calendar/sync-errors` |
| GET | `/api/nova/growth-agent/notifications` |
| GET | `/api/nova/growth-agent/handoffs` |
| POST | `/api/nova/growth-agent/handoffs/{id}/acknowledge` |
| POST | `/api/nova/growth-agent/voice/simulator/run` |

Until routes exist, the UI degrades gracefully: calendar stays **Not connected**, lists empty, and errors surface in `receptionist-status` without retaining tokens.

## Security / privacy

- `redactForDisplay()` strips `access_token`, `refresh_token`, `token`, and related keys from API payloads before render.
- `signOut()` (growth + receptionist) clears in-memory caches and replaces panel DOM; no OAuth material is shown.
- Mock or pending bookings are labeled **not externally confirmed** — never presented as provider-confirmed calendar events.

## Tests

```bash
cd backend/static/nova-growth
node --test receptionist.test.cjs
```

Asserts: disconnected calendar copy, sign-out clearing, SIMULATED labeling, and no token substrings in rendered HTML.

## Mobile

Two-column grid collapses to a single column under 800px. Buttons use enlarged tap targets (`min-height: 2.75rem`). Tables scroll horizontally inside `.recv-table-wrap`.