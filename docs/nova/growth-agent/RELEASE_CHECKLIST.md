# Release checklist — Nova Growth Agent

**This draft PR does not authorize merge, deploy, or paid activation.**

## Before merge (owner)

- [ ] Review draft PR against Issue #485  
- [ ] Confirm no edits to Ops CSV (#475/#477) or Creative Studio (#478) surfaces  
- [ ] Confirm live flags remain hard-off  
- [ ] Confirm synthetic demo passes locally/CI  
- [ ] Legal counsel review scheduled before any customer messaging  

## Before migration on shared DB

- [ ] Explicit owner approval to apply `20261112_nova_growth_agent` DDL (currently production-gated)  
- [ ] Backup / rollback plan: downgrade drops only `nova_ga_*` tables when not prod-locked  
- [ ] Staging verification with synthetic data only  

## Before Render / env changes

- [ ] Set `NOVA_GROWTH_AGENT_ENABLED` only on approved non-prod first  
- [ ] Optional `NOVA_GROWTH_AGENT_WIDGET_ENABLED`, `NOVA_GROWTH_AGENT_DEMO_MODE`  
- [ ] `NOVA_GROWTH_AGENT_WIDGET_SECRET` in vault/env — never commit  
- [ ] No Render hostname rename away from `amicor-health-isf`  

## Before any paid provider

- [ ] Provider contract + spend caps  
- [ ] Credentials only in env/vault  
- [ ] Flip hard-coded live flags via a **separate** owner-approved change (not this PR)  
- [ ] TCPA / CAN-SPAM / state law confirmation  

## Explicitly out of scope for this PR

- Merge to main without owner approval  
- Production deploy  
- Contacting Makkan / Botora / AMICOR prospects  
- Live Stripe charges or subscription creation  
- Real SMS/email/voice/calendar writes  
