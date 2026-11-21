# Stay360 blueprint coverage

Recorded against issue #391. This file does not claim the missing source document was reconstructed.

## Title and version

| Field | Value |
| --- | --- |
| Product title | AMICOR Nova Stay360 |
| Product descriptor | Intelligent Hospitality Operations |
| Document title | AMICOR Nova Stay360 — Intelligent Hospitality Operations |
| Blueprint document title | Hospitality & Travel Master Blueprint |
| Blueprint version | 1.1 |
| Named section count | 26 |
| Blueprint file in this repository | No |

Issue #391 retired the working label "AMICOR Nova Hospitality & Travel" for the product. The blueprint document keeps its own title and version. Those strings are different, and the dashboard title uses only the product title plus descriptor. `GET /api/nova/stay360/meta` returns `product_name`, `document_title`, `blueprint_title`, and `blueprint_version` as separate fields.

The count previously labeled "Not ready" includes rooms in `cleaning` and `blocked` as well as `not_ready`. The dashboard label for that aggregate is "Not ready, cleaning, or blocked". A single room whose readiness is `not_ready` still uses "Not ready".

## What was searched

The 26-section source document was not found in this repository. Searches covered `docs/`, the Stay360 package, and the text of issue #391. Issue #391 names the blueprint and the first slice, then names later increments. It does not list 26 section titles. Unnamed titles are left blank here rather than invented.

## Coverage of named work

| Item | Named in issue #391 | This package |
| --- | --- | --- |
| 1 | Hotel guest and reservation data model | Covered. Synthetic guests and reservations for Harbor Lantern Inn and Cedar Ridge House. |
| 2 | Privacy-safe guest prearrival and reservation lookup | Covered. Lookup is by reservation reference. Staff views omit raw identity, contact, government id, passport, address, loyalty, and payment-token fields. |
| 3 | Mock flight and road arrival updates | Covered. In-process fixture scripts. No airline, hotel, or map network call. |
| 4 | Housekeeping and room readiness | Covered. Transitions are constrained. Readiness is `ready` only after `inspected`. |
| 5 | Eligible mobile check-in simulation | Covered. Result is `simulated_checked_in`, `door_access` is `not_issued`, and `payment_captured` is false. |
| 6 | Staff dashboard | Covered at `/nova/stay360`. |
| 7 | Multilingual-ready interface | Covered for catalogs `en`, `es`, and `fr`. No translation API. |
| 8 | Role and tenant isolation | Covered. Cross-tenant references look like unknown references. Driver and dispatcher roles are denied. |
| 9 | API contracts | Covered by the Stay360 schemas and OpenAPI paths. |
| 10 | Integration and security tests | Covered by `test_nova_stay360_contracts.py`, `test_nova_stay360_integration.py`, `test_nova_stay360_security.py`, and `stay360_dashboard_behavior.test.cjs`. |
| 11 | Parking | Not implemented in this package yet. |
| 12 | Concierge | Not implemented. |
| 13 | Guest services | Not implemented. |
| 14 | Room inventory safeguards | Not implemented. |
| 15 | Family and events | Not implemented. |
| 16 | Marketing | Not implemented. |
| 17 | Itinerary | Not implemented. |
| 18–26 | Section titles are not in the repository | Not implemented. |

Nine issue items are covered. Seven named later increments are not implemented. The remaining nine of the 26 section titles cannot be mapped until the source document is added to the repo.

## Isolation and nonproduction readiness

- The package lives under `backend/app/core/nova/stay360/` and the page under `backend/static/nova-stay360/`. It does not rename other products.
- `backend/app/main.py` only adds the Stay360 router import and `include_router`. Creative Studio, Casting, Work & Revenue, Snap, Delivery, and Health ISF modules are not edited by this package.
- Responses send `X-Stay360-Synthetic: true`. Payment capture and physical door access stay off. External provider calls are rejected in process.
- Stay360 paths are not in the Nova customer frozen-product block list. Hotel fixture organizations are not Nova SaaS customer tenants. Expired Nova trials do not receive this package's data.
- Pull request #401 is unmerged. No deploy was performed.
- The repository's documented staging host in `backend/docs/RENDER_STAGING_DEPLOY_PHASE53.md` is `https://amicor-health-isf-py.onrender.com`, the same Render service as production. There is no separate nonproduction Stay360 host to promote.
- On 2026-10-27, a read-only `GET /api/nova/stay360/meta` against that host returned 404. `GET /nova/stay360` returned the public site shell and did not contain the Stay360 product name. The API is not live there.
- Nonproduction evidence is the local Stay360 pytest and dashboard behavior test on this branch. That is the staging-readiness check available without deploying.

## Still out of scope

Live hotel data, paid integrations, payment capture, physical door or gate access, and a production merge.
