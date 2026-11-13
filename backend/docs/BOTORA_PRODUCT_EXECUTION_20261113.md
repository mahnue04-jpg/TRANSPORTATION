# Botora prospect assignment — November 13, 2026

## Current result: independent discovery added

Nova's new development search path queried for Minnesota travel agencies, found eight candidate source pages, excluded the nine previously supplied business domains and retrieved seven pages. Five records have preliminary workflow evidence: Live Well Travel, Travelorer, Aeris Travel, Carrousel Travel and Tailored Travel. Emily's Travel and Travel Beyond were retrieved but have insufficient workflow evidence in the selected pages; they remain on hold. Pique Travel's source failed and was excluded. None has verified buying interest. Overlap with the historical 139 remains unknown.

A separate search-through-API run completed four retrieved records, review CSV download, duplicate-request reuse and retrieval from a fresh process. It uses a synthetic authentication identity and in-process HTTP transport. Twelve focused tests passed. This is development evidence, not a deployed or production acceptance result.

## Earlier baseline result

Development execution over nine owner-selected public business URLs: seven fetched and produced seven review rows; two sources failed and produced no prospect rows. All buying interest remains unverified. No outreach, referral submission, signing, tax approval or paid-service activation occurred.

This is not independent discovery of new businesses. These are existing research candidates, with unknown overlap with the historic unrecovered 139. Keyword workflow signals do not establish a business need, purchase intent or willingness to pay.

## Code exercised

Work & Revenue: new prospect_research.py fetches bounded HTTPS public sources selected for this assignment, extracts visible workflow evidence, keeps source hashes and timestamps, excludes failed sources and deduplicates domains. It never follows website instructions.

Operations: the existing operations_csv_cleanup.clean_csv_text processor creates the review CSV. Evidence files and output integrity were verified by a separate fresh Python process. This demonstrates local file persistence across process exit; it does not demonstrate a restarted hosted worker, private cloud storage, tenant authorization or the full customer-job workflow.

Initial execution failed all nine sources because local DNS was unavailable. The revised path checks public IP resolution via HTTPS DNS when local DNS fails. The retry fetched seven sources. iBookiGo failed source validation; 3 Sisters Trips returned an HTTP error. Both remain excluded pending diagnosis and verification.

Four targeted tests passed: failed sources cannot create prospects; domain duplicates collapse and tampering is detected; unapproved hosts/private addresses/embedded credentials are rejected; source content cannot grant consent or approval. They use explicit synthetic fixtures, separate from the real public-source execution.

## Live product inspection

The current production OpenAPI listing exposes paid-job discovery and an owner CSV cleanup route, but no dedicated Botora prospect-research route. The live Work & Revenue page required sign-in in this browser. Its CSV panel stated that the feature was unavailable until separately enabled for an authorized owner. This unauthenticated view does not establish the signed-in owner's enabled state. No hosted customer job was completed and no production settings were changed.

## Remaining work

1. Verify the signed-in hosted owner journey without changing production security or storage gates.
2. Verify search-source reliability and operational limits before an unattended schedule. The new keyless public-search path works in this development run; it stops on provider failure or a verification challenge and has no paid fallback.
3. Complete interactive browser acceptance of the new search/review panel and API. They are implemented in the development branch and are not deployed.
4. Prove the integrated staging workflow and persistence, then obtain any required production release approval. Do not substitute this local file check for cloud recovery evidence.
5. Qualify actual need, enquiry volume, buyer, budget, timing and introduction permission before treating any candidate as an accepted referral. Await signed Botora contract, approved materials and owner launch authorization before contact.

## Continuation: saved owner review API and interface

A development-only API and owner-facing review panel are now implemented. They let the owner supply selected source pages, create a scoped job, resume a saved review and download the Operations CSV. The panel is hidden unless the authenticated development-readiness check succeeds. There is no sending, contract approval, payment or referral-acceptance control.

The API namespaces files by the organization and owner. Repeat requests reuse their completed result without re-fetching sources. Read/download verify the saved output and evidence hashes. Cross-owner reads are denied. Production is rejected even if the development-enable flag is accidentally set. Credentials embedded in source URLs are rejected. This local-file implementation remains unsuitable for production multi-tenant storage.

Nine targeted tests passed. The HTTP acceptance run used seven real public source pages: seven records, zero source failures, successful review CSV download, duplicate-request reuse and successful retrieval/download from a fresh Python process. Its authentication dependency was explicitly replaced with a synthetic test identity, and requests used FastAPI's in-process HTTP test transport. This is not live owner authentication or hosted deployment evidence. No buying interest was confirmed and no outreach was sent.

The new route is included by the Work & Revenue router. Full application startup verification was blocked because the existing development Python environment lacks the unrelated weather module's requests dependency. Frontend JavaScript passed the syntax check; the new panel has not passed interactive browser acceptance.

Live sign-in was not completed in the previous session; no new credential attempt or production configuration change was made in this continuation. Hosted private storage, actual owner sign-in and interactive browser acceptance remain unfinished.

## Independent-search continuation

The new prospect_discovery.py calls the no-key public search connection once per assignment, follows the returned primary-page pointers through Nova's source reviewer, filters obvious directories, normalizes domains and deduplicates against provided exclusions. Search titles are provisional business labels. The API additionally excludes domains found in that owner's actual saved jobs. It does not claim to deduplicate against unrecovered records.

The owner panel now includes Find business candidates as well as selected-source review. Source record counts, preliminary workflow matches, insufficient evidence and source failures are shown separately. There are no contact, approval-of-contract or payment controls. Search results and page text cannot authorize actions. The assignment remains pending owner review and handoff remains on hold for the signed agreement, campaign approval, owner launch authorization and prospect introduction permission.

The independent API acceptance queried the same public Minnesota business search with a four-result limit, fetched four primary pages and downloaded the Operations CSV. A duplicate request reused the result. A new Python process reopened and downloaded it with integrity checks. Its synthetic authentication override is explicitly recorded in the evidence. The separate eight-candidate run and four-candidate API run overlap; do not add them together.

## Review packaging and control verification

Draft GitHub review #508 isolates Botora's changes against a dedicated review base at 7d65bb05. The original uploaded branch contains earlier development history and must not be merged directly to main as a Botora-only production release. This review does not authorize deployment.

Four JavaScript control tests passed in an isolated Node VM with synthetic DOM and HTTP fixtures: signed-out users make no request; retry preserves request identity; a late search response cannot restore records/download after sign-out; provider failure unlocks controls without fabricating output. These complement the 12 Python checks. They are not an interactive browser or hosted-owner-authentication test.

## Reproduce in development

From the repository root with its Python dependencies installed:

    PYTHONPATH=backend python backend/scripts/botora_product_assignment.py --seeds /absolute/path/seeds.json --output /new/private/output/directory
    PYTHONPATH=backend python backend/scripts/botora_product_assignment.py --verify --output /same/private/output/directory

The output directory must be new; execution will not overwrite an existing run. Store source HTML privately for reproducibility and do not deploy this filesystem-based implementation as multi-tenant customer storage. Exact allowlisting and public-address checks are initial protections; hosted integration needs its own outbound-network enforcement and authorization review.
