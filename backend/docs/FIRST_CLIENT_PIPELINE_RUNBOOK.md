# First-client pipeline runbook

This runbook is for the owner board at `/nova/work`. It does not deploy anything, buy a subscription, or send an application.

## What the board is

`GET /api/nova/work/first-client/board` lists the signed-in owner's saved opportunities. It does not call a job source. A failed live search stays on the discovery control and is labeled source-unavailable. It is not shown as zero matches.

Sent means `externally_submitted` is already true. Approval, a draft, and a blocked handoff are not sends. This request never increments the sent count.

## Owner steps

1. Sign in on `/nova/work`.
2. Run Find Paid Jobs only when live discovery is enabled in the environment. If every source fails, stop. Do not treat that screen as an empty market.
3. Review the first-client board. Each card shows the source URL, qualification reasons, a proposal preview, the stage, and one next action.
4. Prepare a draft from a saved opportunity. The draft includes an evidence checklist, paid-pilot options with no committed price, and an eligibility assessment. Missing facts stay `[OWNER INPUT REQUIRED]`.
5. Approve a package only when the text is true. Approval still does not send.
6. Use Record blocked handoff when no verified submit channel is connected. The ledger state is `BLOCKED`. Open the source URL and submit it yourself if you choose to.
7. Schedule a follow-up only after a confirmed send or a submission you recorded yourself. Saving a follow-up does not send the message.
8. Record an employer acknowledgement or a delivery failure only after that submission exists. A delivery failure is not a successful send.

## What stays off

- No application fee, paid connect, or subscription purchase.
- No invented certification, client, year of experience, or signature.
- No production deploy from this change.
- No email is sent by the board, the handoff record, the follow-up, or the response record.

## Tests

`backend/tests/test_nova_first_client_pipeline.py` covers search honesty, the draft materials, user scope, the blocked handoff, and the follow-up gate. It does not call a live job source or an email provider.
