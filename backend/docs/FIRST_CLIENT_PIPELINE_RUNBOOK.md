# First-client pipeline runbook

This runbook is for the owner board at `/nova/work`. It does not deploy anything, buy a subscription, or send an application.

## What the board is

`GET /api/nova/work/first-client/board` lists the signed-in owner's saved opportunities. It does not call a job source. A failed live search stays on the discovery control and is labeled source-unavailable. It is not shown as zero matches.

Sent means a submission receipt is stored and `externally_submitted` is already true. Approval, a draft, a blocked handoff, and a delivery failure are not sends. A follow-up can be saved only after that receipt. This request does not send mail.

## Owner steps

1. Sign in on `/nova/work`.
2. Run Find Paid Jobs only when live discovery is enabled in the environment. If every source fails, stop. Do not treat that screen as an empty market.
3. Review the first-client board. Each card shows the source URL, qualification reasons, a proposal preview, the stage, and one next action.
4. Prepare a draft from a saved opportunity. The draft includes an evidence checklist, paid-pilot options with no committed price, and an eligibility assessment. Missing facts stay `[OWNER INPUT REQUIRED]`.
5. Approve a package only when the text is true. Approval still does not send.
6. Use Record blocked handoff when no authenticated permitted channel is connected. The ledger state is `BLOCKED`, with one owner step: connect that channel, or open the source URL and submit the approved package yourself.
7. A send is stored only when that channel accepts the one application and returns a receipt. The states are draft, approved-for-future, sent, delivery failure, acknowledgement, and blocked. Missing auth stays blocked. A transport that reports network use without a local receipt is blocked.
8. Schedule a follow-up only after a send receipt. Saving a follow-up does not send the message. Record an acknowledgement or a later delivery failure only after that same receipt. A delivery failure is not a successful send.

## Filter notes

Preferred experience, a commitment length, a company age, a gym or benefit membership, and "join our team" on an explicit contractor listing do not by themselves reject a listing. Mandatory years of experience, an application fee, an unsupported license, mandatory on-site work, a worker native-speaker requirement, an unmet permit or residency rule, and Upwork paid connects still reject it. A line such as "Philippines-based candidates" is a residency requirement. A company based in another country is not. "Email support for native English speakers" names the audience. "Native English speaker required" names the worker. Operational support, CRM, business process, workflow automation, and FastAPI or API integration titles stay in scope when the listing is remote contractor work.

A live search reports `funnel`, `exclusion_reason_counts`, and a short `exclusion_samples` list. `funnel.screened_rows` counts every provider row, including the same URL seen on a later query. `unique_screened` counts each public URL once. `unique_kept` plus `unique_excluded` equals `unique_screened` (`reconciled` is true). A later timeout keeps rows from a query that already finished and marks the run partial. If every queried provider fails before returning, `live_search_claimed` is false. A discovery reject also copies `NOT_QUALIFIED` onto the row, so a rejected listing is not counted as owner review.

## Board

Top matches are the signed-in owner's saved records that are not rejected and that have both a source URL and a fetch or discovery time. Rejected records stay in `counts.rejected`. A saved record with no URL stays under `incomplete_provenance`. Refresh the board from the button, from a Work page reload, or when the browser restores the page. Restarting the page loads the same owner-scoped rows. It does not search again.

## Proposals

Draft a proposal only for a qualified live record that has a source URL and a fetch time. The draft includes a 7-day paid-pilot option with no committed price, a cost and scope check, and an evidence checklist of mandatory owner facts. Fixture and example hosts draft nothing. A draft is not a send.

## Sandbox submission

The permitted-channel transport used in tests is not billable and does not open a socket. Missing auth does not call it. A send is stored only when that in-process channel returns a non-empty receipt and does not report network use. A blank receipt is not a receipt. Network use stays blocked even if a receipt string is present, because this board does not record a network send. The same local receipt is not stored twice. A delivery failure can be retried. A later failure does not erase a receipt already stored. This runbook does not send an application.

Draft PRs #331 and #335 are not merged here. Their dev-only funnel acceptance and fictional evidence export stay on those branches.

## Cloudflare Pages

The `amicor-public` Pages project builds the `website/` directory with no build command. That directory is on this branch because `main` was merged so the preview can find the site root. This change does not run Wrangler and does not deploy production.

## Rollback

Revert the commits on this branch. Saved opportunities, ledger rows, and drafts already written in an environment stay there. Reverting code does not delete them and does not send anything. Leave live discovery off unless the owner turns `NOVA_V3_LIVE_DISCOVERY_ENABLED` back on. Do not enable external submission or financial actions as part of a rollback.

## What stays off

- No application fee, paid connect, or subscription purchase.
- No invented certification, client, year of experience, or signature.
- No production deploy from this change.
- No email is sent by the board, the handoff record, the follow-up, or the response record.

## Tests

`backend/tests/test_nova_first_client_pipeline.py` covers search honesty, the draft materials, user scope, the blocked handoff, and the follow-up gate. It does not call a live job source or an email provider.
