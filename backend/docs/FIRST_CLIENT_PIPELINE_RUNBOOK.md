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

Preferred experience, a commitment length, a company age, and a gym or benefit membership do not by themselves reject a listing. Mandatory years of experience, an application fee, an unsupported license, mandatory on-site work, and Upwork paid connects still reject it. A line such as "Philippines-based candidates" is a residency requirement. A company based in another country is not. Operational support, CRM, business process, workflow automation, and FastAPI or API integration titles stay in scope when the listing is remote contractor work.

Draft PRs #331 and #335 are not merged here. Their dev-only funnel acceptance and fictional evidence export stay on those branches.

## Proposals

Draft a proposal only for a qualified live record that has a source URL and a fetch time. Fixture and example hosts draft nothing. A draft is not a send.

## What stays off

- No application fee, paid connect, or subscription purchase.
- No invented certification, client, year of experience, or signature.
- No production deploy from this change.
- No email is sent by the board, the handoff record, the follow-up, or the response record.

## Tests

`backend/tests/test_nova_first_client_pipeline.py` covers search honesty, the draft materials, user scope, the blocked handoff, and the follow-up gate. It does not call a live job source or an email provider.
