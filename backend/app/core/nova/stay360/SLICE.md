# AMICOR Nova Stay360

Descriptor: Intelligent Hospitality Operations.

Slice id: `guest-prearrival-room-readiness`.

This package is an isolated synthetic slice. It does not rename other products, call paid providers, capture payment, or issue door access.

## What this slice covers

- Synthetic hotel guests and reservations for two invented properties, Harbor Lantern Inn and Cedar Ridge House.
- Privacy-safe guest prearrival and staff reservation lookup by reservation reference.
- Staff lists omit raw identity, contact, government id, passport, address, loyalty, and payment-token fields.
- Mock flight and road arrival updates from in-process fixture scripts. No airline, hotel, or map network call is made.
- Housekeeping status and derived room readiness.
- Eligible mobile check-in simulation. The result records `simulated_checked_in`, sets `door_access` to `not_issued`, and sets `payment_captured` to false.
- A hotel admin and staff dashboard at `/nova/stay360`.
- Locale catalogs `en`, `es`, and `fr` stored in the package. No translation API is called.
- Role and tenant isolation. Staff of one hotel organization cannot read another hotel's reservations. A driver or dispatcher role is denied. A guest rider can read and simulate check-in only for the bound reservation.

## Acceptance criteria

1. `GET /api/nova/stay360/meta` returns product name `AMICOR Nova Stay360` and descriptor `Intelligent Hospitality Operations`.
2. The dashboard page at `/nova/stay360` shows that product name and descriptor and binds locale keys from the Stay360 catalog.
3. Staff reservation lists and lookup responses exclude sensitive field names and the synthetic secret values stored on guest records.
4. Reservation lookup accepts a reservation reference. Email, phone, and other raw identity query parameters are rejected and are not echoed.
5. A staff or admin actor of tenant A receives the same not-found response for a tenant B reservation reference as for an unknown reference, and the body contains no tenant B secrets.
6. A guest rider can open prearrival and mobile check-in only for the reservation bound to that user id. Another guest's reference in the same hotel is not found.
7. `POST /api/nova/stay360/arrivals/refresh` advances the in-process flight or road script by one step and reports `network_providers: disabled`.
8. Housekeeping follows allowed transitions. `dirty` cannot jump straight to `inspected`. Room readiness becomes `ready` only after `inspected`.
9. Only a hotel admin can move a room to or from `out_of_order`. That readiness is `blocked`.
10. Mobile check-in simulation succeeds only when no eligibility blocker remains. A denied simulation returns `door_access: not_issued`, `physical_access_control: false`, and `payment_captured: false`.
11. A successful simulation returns confirmation code `SIM-{reference}` and does not return a door code, lock id, or payment capture.
12. Repeating a successful simulation returns `already_checked_in` and still does not issue access or capture payment.
13. Unauthenticated operational calls return 401. Driver and dispatcher roles return 403 even when the organization id matches a Stay360 hotel.
14. Locale catalogs `en`, `es`, and `fr` contain the same keys. `product.name` stays `AMICOR Nova Stay360`.

## Blueprint gap

The product title is AMICOR Nova Stay360. The source document title is Hospitality & Travel Master Blueprint version 1.1 (26 sections) and that document is not in the repo. Those titles are different. The parking stall assignment is included. Sections not implemented: concierge, guest services, inventory safeguards, family/events, marketing, itinerary.

Section-by-section coverage is in `BLUEPRINT_COVERAGE.md`. The page title is `AMICOR Nova Stay360 — Intelligent Hospitality Operations`. The blueprint title is a separate citation and is not the product title.

## Fixture clock

Operational "today" is the synthetic date `2026-10-26` in `America/Chicago`. Tests do not follow the wall clock.

## Hard limits

Synthetic invented guests only. No live hotel data, no real guest PII, no production secrets, no Stripe call, no door lock, and no physical access control.
