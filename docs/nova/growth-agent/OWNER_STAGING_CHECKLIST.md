# Owner staging checklist — Growth Agent (PR #490)

**Keep Draft.** Do not merge, do not enable live messaging/payments/retention deletion, do not contact prospects.

## Isolated staging under test

| Item | Value |
|------|-------|
| Staging URL | `http://127.0.0.1:8770/nova/growth` (isolated agent-environment staging) |
| Dedicated DB | `nova_ga_staging_dispos` (local disposable Postgres — not shared/prod) |
| Deployed commit | `a81de10b7cc5c483a08877eb641680542962bb3a` |
| Flags | Growth/Demo/Widget/Mock worker/Retention schedule **on**; **retention delete off**; live transports hard-off |
| Remote Render isolated Growth Agent service | **Not found / not deployed** from this agent (no Render API credentials). Production `amicor-health-isf` was **not** used. |

## Checklist

1. [ ] Open staging URL → sign in as staging owner.
2. [ ] Confirm banner: not live messaging; live providers off.
3. [ ] Setup → Save & activate synthetic business.
4. [ ] Create widget install for allowlisted staging domain → FAQ chat with transactional consent.
5. [ ] CRM: lead appears → edit state/notes → Save.
6. [ ] Owner-assisted booking: load slots → book.
7. [ ] Preview reminder workflow → approve dry-run → Mock worker tick → `sent_mock` / `live_send=false`.
8. [ ] Diagnostics: `live_delivery=false`, retention `mode=dry_run`, delete off.
9. [ ] Retention dry-run only (do **not** enable delete).
10. [ ] Kill switch Disable → Resume.
11. [ ] Confirm Ops Agent / Work & Revenue / Creative Studio untouched.
12. [ ] Decide merge readiness (owner only).

## Rollback

1. Stop staging process (`SIGTERM` uvicorn / unset flags).
2. Redeploy previous known-good commit (`9370d0b0` or earlier).
3. Keep `NOVA_GROWTH_AGENT_RETENTION_DELETE_ENABLED=false`.
4. Disposable DB only: restore `pg_dump` or recreate `nova_ga_staging_dispos`. Never touch production DB.

## Pass / fail gate

- **PASS** requires: chat → CRM → booking → mock reminder with `live_send=false`, crash/lease reclaim OK, retention dry-run only, Creative/Ops untouched.
- **FAIL** if live send appears true, delete runs without explicit flag, or shared/prod DB is mutated.
