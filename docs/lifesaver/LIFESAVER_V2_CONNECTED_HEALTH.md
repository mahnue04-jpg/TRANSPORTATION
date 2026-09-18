# Lifesaver V2 connected health and home-test framework

Local simulation architecture only. No real medical device, specimen, lab, provider message, or emergency-service call is enabled.

## 1. Architecture

Lifesaver owns a vendor-neutral registry under `/api/lifesaver/connected-health/`.
It stores coordination records for future approved consumer/medical devices and at-home kits.
The Home Hub digital twin may display metadata-only status cards. It does not diagnose.

Regulatory boundary: **coordination and information storage**, not diagnostic medical-device functionality.

## 2. Device-category roadmap

Supported simulated categories: blood pressure, pulse oximeter, thermometer, weight scale, glucose meter / CGM placeholder, heart-rate, activity/mobility, medication-dispenser placeholder, sleep placeholder, future approved sensor.

Real connections remain disabled. `simulated=true` and `real_connection=false` on every record.

## 3. Home-test kit workflow

States: ORDERED → RECEIVED → READY → COLLECTED → PACKAGED → PICKUP_REQUESTED → SHIPPED → LAB_RECEIVED → RESULT_PENDING → RESULT_AVAILABLE → PROVIDER_SHARED.
Also CANCELLED and EXPIRED.

Lifesaver does not handle specimens, process laboratories, or interpret results.

## 4. Consent and sharing

Explicit consents: `connected_device_readings`, `home_test_status`, `laboratory_result_documents`, `provider_sharing`, `care_circle_health_share`.
Default is least privilege. Revocation stops future access and does not delete audit history.
Care Circle also requires existing `caregiver_sharing` plus a named permission.

## 5. Provider-result handoff

Result documents store a redacted reference, source, timestamps, and review flags only.
No automatic diagnosis. Optional informational note is a fixed non-clinical sentence.
Provider share creates a local `shared_simulated` record. No real provider message.

## 6. Future approved-device procedure

1. Keep this registry.
2. Add a vendor adapter that never logs secrets or PHI.
3. Require explicit consent and an allowlisted private path.
4. Leave production/public hosts rejected until a later approved program.

## 7. Home Hub presentation

Example cards: “Blood pressure monitor connected — simulated.”
“Home test kit collection recorded.”
“Result document received — provider review available.”
Physical safety/fall events stay separate. A reading or result never calls 911.

## 8. AMICOR ecosystem hooks

Placeholder contracts exist for AMICOR Health appointments, Delivery kit logistics, Nova summaries, provider share, and Care Circle notification.
None are activated. None write frozen product tables.

## 9. Prototype acceptance

- Consent required and revocation honored
- Simulated pair / offline / unsupported
- Kit lifecycle and expired-kit lock
- Result intake without diagnosis
- Provider and Care Circle share blocked without consent
- Audit metadata has no reading values or document contents
- Home Hub cards remain non-diagnostic
- `emergency_services_contacted=false`
