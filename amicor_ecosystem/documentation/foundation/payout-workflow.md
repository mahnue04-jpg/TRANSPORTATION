# Payout Workflow

## Objective

Track and settle driver payouts with clear auditability and predictable timelines.

## MVP Flow

1. Ride is marked `completed` and validated.
2. Fare and payout basis are calculated.
3. Exceptions (disputes, cancellations, partial completions) are reviewed.
4. Approved payouts move to settlement queue.
5. Settlement status is recorded and reportable.

## Core Controls

- Immutable ride completion references
- Manual review path for disputed records
- Weekly reconciliation report by driver and partner
