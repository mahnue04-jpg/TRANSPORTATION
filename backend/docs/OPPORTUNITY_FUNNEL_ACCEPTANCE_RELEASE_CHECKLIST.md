# Opportunity funnel acceptance release checklist

This checklist is for the dev-only synthetic acceptance of the existing Work and Revenue opportunity funnel. It does not authorize a merge, a deploy, a credit purchase, an external application, contact with a lead, or a production workflow.

The acceptance file is `backend/tests/test_nova_opportunity_funnel_acceptance.py`. CI runs it as the `opportunity-funnel` job in `.github/workflows/work-revenue-regression.yml` on disposable sqlite `test_nova_opportunity_funnel_acceptance.db`. A missing file, a missing required case, a skip, or a failed case fails that job.

## Required cases

- `test_acceptance_database_is_isolated_sqlite`
- `test_discovery_ranks_fictional_postings_without_saving`
- `test_qualification_closes_remote_negation`
- `test_qualification_closes_foreign_residency`
- `test_qualification_closes_upfront_fee_and_keeps_no_fee_data_entry`
- `test_saved_lead_is_isolated_and_duplicate_save_reuses_it`
- `test_retry_after_insert_conflict_reuses_the_lead`
- `test_failures_stay_closed_and_do_not_open_a_draft`
- `test_proposal_draft_stays_internal`
- `test_owner_review_queue_requires_an_explicit_gate`
- `test_external_send_stays_off_without_and_after_approval`
- `test_audit_trail_records_the_stage_events`
- `test_ui_status_matches_each_funnel_stage`
- `test_stage_logs_name_the_funnel_and_keep_external_send_off`

## Before calling the funnel accepted

1. Confirm the database URL is sqlite. Under pytest, `TESTING=true` replaces it with `backend/data/chat_test_<pid>.db`. A direct run may use `test_nova_opportunity_funnel_acceptance.db`. It must not be Postgres and it must not be the shared `chat.db`.
2. Confirm every posting and company in the run is fictional and every source URL is on `example.invalid`.
3. Confirm discovery ranks those postings in process and does not save them by itself.
4. Confirm qualification closes negated remote status, an explicit remote denial, a foreign residency requirement, and an upfront fee. A no-fee data-entry title stays in the data-entry lane.
5. Confirm a clear fictional lead can be saved, a second save reuses that lead, and a simulated insert conflict retries onto the same lead.
6. Confirm a blank posting is not saved and a closed residency posting cannot open an application draft.
7. Confirm the draft includes a proposal and a cover letter, the owner-review queue lists it, and submit is refused until the owner approves.
8. Confirm owner approval still does not send. The provider handoff reports no external action, and the email confirmation path is not allowed to call the sender during this acceptance.
9. Confirm the audit trail contains create, qualify, draft, owner-review, and owner-approval events for that fictional lead, with no email address in the summaries.
10. Confirm Work and Revenue shows one of these labels on discovery results, saved leads, and applications, and that only a recorded external submission uses "Sent externally.":

    - Discovered. Not yet a saved lead.
    - Qualified. Not saved yet.
    - Qualification needs owner review. Not saved yet.
    - Not qualified. Closed.
    - Saved lead. Qualification pending. Not sent.
    - Qualified saved lead. Not sent.
    - Application draft. Not sent.
    - In the owner-review queue. Not sent.
    - Approved for future submission. Not sent.
    - Closed. Not sent.
    - Sent externally.
    - Stage not confirmed. Not sent.

11. Confirm the stage log names `funnel_stage` and `external_send` and does not include an email address.

## Local run

From `backend/`, with credentials unset:

```bash
export TESTING=true
export DATABASE_URL=sqlite:///./test_nova_opportunity_funnel_acceptance.db
export HEALTH_ISF_STRIPE_ENABLED=false
export NOVA_STRIPE_LIVE_ENABLED=false
unset SAM_GOV_API_KEY OPENAI_API_KEY STRIPE_SECRET_KEY STRIPE_API_KEY HEALTH_ISF_STRIPE_SECRET_KEY NOVA_STRIPE_SECRET_KEY ANTHROPIC_API_KEY
rm -f test_nova_opportunity_funnel_acceptance.db
python -m pytest tests/test_nova_opportunity_funnel_acceptance.py -v --tb=line
```

## Stop

Stop if any required case is missing, skipped, or failed. Stop if the run used a shared or production database, a live posting, a real identity, or an external send. This acceptance does not change Creative Studio, the CIGO prototype, the public website, Synapse language work, or the independent QA suite.
