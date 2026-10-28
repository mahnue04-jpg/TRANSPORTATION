# Nova evaluation readiness demonstration

This isolated draft implements an evidence-processing prototype for Work & Revenue
and Operations Agent. It does not change existing application routes, the generic
spreadsheet executor, database models, or production behavior.

## Reproduce

From the repository root with Python 3.12 (standard library only):

```sh
python -m unittest discover -s backend/tests/evaluation -v
python scripts/nova_evaluation/run_demo.py --output /tmp/nova-evaluation-demo
```

33 tests cover independently specified counts, source references, malformed and
conflicting records, replay, missing-data handling, report escaping, cross-site
review attempts, stale corrections and preservation of genuine capture errors.
The standalone runner imports the isolated package without starting FastAPI.

The fixture contains 32 invented calls across two fictional sites and two intake
channels, linked to invented transcripts, data-transfer events and case records.
This is data-export reconciliation, not live call transfer, speech recognition,
semantic transcript annotation or a LegalServer integration test.

## Metric contract

All definitions below are demonstration choices, not approved buyer methodology.

| Measure | Numerator | Denominator or population |
| --- | --- | --- |
| Completion | Completed calls | Completed + abandoned calls; ineligible excluded |
| Abandonment | Abandoned calls | Same eligible-call population |
| Field completeness | Completed calls flagged complete | Completed calls with known completeness flag |
| County accuracy | Captured county equals fixture reference county | Completed calls with a linked reference county |
| Data-transfer success | Request has one terminal success and matching matter evidence | Calls requesting a data transfer |
| Staff time | Sum of observed staff minutes | Eligible calls with known staff time; missing is not zero |
| Median duration | Median seconds, with all observations retained | Completed calls only |

Language strata below five eligible observations suppress their rate under a
demonstration rule. Five is not asserted to establish statistical sufficiency.
Differences are descriptive; timing, sample mix, eligibility and instrument bias
must be assessed by a qualified evaluator before any real comparative conclusion.
There are no causal claims, significance tests or population/fairness conclusions.
No pooled metric erases site differences. No overall accuracy beyond the county
field has been implemented.

## Identity and provenance

Raw records have unique record IDs, content hashes and retained source rows. Call
identity is `(site, call_id)`. A repeated identical import is collapsed with both
references retained. Conflicting versions quarantine the identity rather than
choose a convenient value. Different calls are retained even if business values
match. Transcript, transfer and matter links must match the same site and call.

`analysis_v1.json` and `analysis_v2.json` retain source snapshots, every metric's
numerator/denominator references, exclusions and hashes. The error run records
blocking reasons and never produces approved output. The HTML site reports expose
metric evidence and preserve separate initial/revised versions.

The simulated reviewer corrects an **import mapping error** in the Tennessee
analysis table using the original fictional case export. The raw source remains
unchanged and the previous snapshot is retained. The independent Florida capture
error stays counted; the correction API rejects rewriting it to a desired outcome.
This is not evidence of an actual human review or an improved live AI agent.

The module always returns `approved_for_client_delivery=false`. No CLI command or
fixture actor can approve a client report. Real review must later use authenticated
owner/evaluator identities, immutable review records and scope-specific authority.

## Upgrade assessment and next integrations

| Priority | Feature | Present proof | Required before client use |
| --- | --- | --- | --- |
| P0 | Identity-aware evidence ingestion | Offline fixture import, scoped joins, duplicate/conflict handling | Approved CSV/LegalServer/call-log adapters, schema versioning and timestamp policy |
| P0 | Versioned metric registry | Explicit definitions and source-linked deterministic calculations | Buyer-approved definitions, sampling, baseline alignment and independent validation |
| P0 | Reviewer correction and report regeneration | Immutable simulated mapping correction and versioned reports | Authenticated UI, actual reviewer authority, amendment/approval events and durable storage |
| P0 | Secure project workspace | No client data or network used | Tenant/engagement authorization, encryption, retention/deletion, consent and audit tests |
| P0 | Voice evaluation methods | Structured fictional transcript references | Ground-truth annotation, audio/transcript scoring, sampling, interview/usability instruments |
| P1 | Work & Revenue adapter | Prototype lives beside existing core modules | Persist source IDs, issues, artifacts and reviewer tasks using existing engagement permissions |
| P1 | Operations Agent adapter | Deterministic evaluator callable offline | Register a scoped executor; show real run evidence, failures and no automatic client release |
| P1 | Reusable domain profiles | Same evidence/metric/revision pattern | Approved transport/delivery metrics, ride/POD adapters; no clinical or payment decisions |

Transport reuse could measure accepted-to-completed trips, dispatch delays,
document completeness and delivery reconciliation. Those definitions are not
interchangeable with legal-intake measures; implement and validate domain adapters.

This draft is **not** ready to accept confidential client data. The synthetic flag
and DEMO prefixes are accidental-use controls, not privacy detection, encryption,
authentication, security certification or a protection against mislabeled PII.
The reports do not establish contract readiness, deployment or approved staffing.

## Safe integration boundary

No HTTP routes or existing executor branches are registered in this change. Keep
it isolated until an authenticated integration can bind an evaluation input to an
authorized engagement and retain its full artifact/review history. Never route a
client evaluation through generic exact-row deduplication or mark it done solely
because a task status or owner approval exists. Real source collection, qualified
methodology, security acceptance and demonstrated end-to-end operation remain gates.
