# Driver Onboarding — Business Operations Sprint 1

**Module:** `backend/app/modules/platform_ops/`  
**Status:** Sprint 1 foundation (production configuration pending for document storage)  
**Transportation engine:** Frozen v1.0 — no ride/dispatch/billing changes

---

## Purpose

Introduce a separate driver onboarding workflow connected to the existing transportation system through an activation adapter. Existing production drivers and the frozen ride workflow remain unchanged.

---

## Workflow

```
draft
  → submitted
  → under_review
  → documents_pending (optional loop)
  → background_review
  → approved
  → activated   (separate admin action)
```

Terminal / exception paths:

- `rejected` — from review stages (confirmation required)
- `suspended` — from review, approved, or activated (confirmation required)

**Important:** Submitting an application does **not** activate a driver. Approval and activation are separate actions.

---

## Status definitions

| Status | Meaning |
|--------|---------|
| `draft` | Applicant editing; not yet submitted |
| `submitted` | Complete application received |
| `under_review` | Staff reviewing answers |
| `documents_pending` | Missing or rejected documents |
| `background_review` | Background / MVR review stage (advisory in Sprint 1) |
| `approved` | Applicant passed review; not yet a driver |
| `rejected` | Application denied |
| `suspended` | Application paused |
| `activated` | Linked to `HealthISFDriver` via activation adapter |

Every status change writes an audit event to `platform_driver_onboarding_audit_events`.

---

## Required application fields

### Personal

- Legal first name, optional middle name, legal last name
- Date of birth, email, mobile phone
- Home address, city, state, ZIP
- Emergency contact name and phone
- Preferred language

### Driver

- Driver's license number, issuing state, expiration date
- Years of driving experience
- Employment type: `independent_contractor` or `employee`
- Availability days, start/end times
- Weekend willingness, wheelchair transport willingness
- Service area / counties

### Declarations (all required at submit)

- Valid license confirmation
- MVR authorization
- Background screening authorization
- Drug & alcohol policy acknowledgment
- Truthful information certification
- Electronic signature and signed date

---

## Document checklist

| Category | Upload required | Sensitive |
|----------|-----------------|-----------|
| drivers_license_front | Yes | No |
| drivers_license_back | Yes | No |
| proof_of_auto_insurance | Yes | No |
| vehicle_registration | Yes | No |
| vehicle_inspection_record | Yes | No |
| driver_profile_photo | Yes | No |
| ssn_tax_verification_status | Status-only | Yes |
| w9_status | Status-only | Yes |
| background_check_consent | Yes | Yes |
| motor_vehicle_record_consent | Yes | Yes |
| independent_contractor_agreement | Yes | No |
| training_certificates | Yes | No |
| cpr_first_aid_certificate | Yes | No |

Document **contents** are not returned in list responses — metadata only.

---

## Permissions

| Action | Roles |
|--------|-------|
| Create/edit own draft (applicant token) | Public applicant |
| Submit own application | Public applicant |
| List applications | admin, super_admin_support, supervisor, dispatcher, driver_support, compliance_officer |
| Review documents / internal notes | Review roles above |
| Compliance status-only fields | admin, super_admin_support, compliance_officer, supervisor |
| Approve / reject / suspend / activate | admin, super_admin_support, supervisor |

Rules:

- Applicants see only their own application (applicant token or staff)
- Drivers cannot approve themselves
- Public users cannot list applications
- License numbers and phones are masked in list/log contexts

---

## Approval rules

- Approve requires `confirm: true`
- Valid source statuses: `under_review`, `background_review`, `documents_pending`
- Approval sets `approved_at` but does **not** create a driver record
- Self-approval blocked when applicant email matches approver email

---

## Activation behavior

Activation endpoint: `POST /api/platform-ops/driver-onboarding/applications/{id}/activate`

- Requires status `approved` and `confirm: true`
- Calls existing `health_isf.service.create_driver()` — **does not modify** ride engine code
- Creates placeholder plate `ONBD-{token}` until vehicle assignment
- Sets `activated_driver_id` on application
- Idempotent: repeated activation returns the same driver
- New driver defaults to offline via existing `create_driver` behavior
- Preserves onboarding + audit history on application row

Legacy drivers (no onboarding record) are unaffected.

---

## Feature flags

| Variable | Default | Behavior |
|----------|---------|----------|
| `PLATFORM_OPS_DRIVER_ONBOARDING_GATE` | off | When enabled, `evaluate_workforce_readiness()` applies advisory checks to newly activated drivers only |
| `PLATFORM_OPS_DOCUMENT_STORAGE` | `local_dev` | Document storage backend selector |

Sprint 1: gate is **advisory only** and **not wired** into frozen dispatch assignment paths.

---

## Storage limitations

- Sprint 1 uses `LocalDocumentStorage` under `backend/data/onboarding_docs/`
- Marked as **development-only** — not production-ready
- Production requires durable private object storage (Azure Blob, S3, etc.) — deferred configuration

---

## Security considerations

- Applicant access tokens stored as SHA-256 hashes
- No SSN fields persisted in Sprint 1 (status-only categories)
- Do not log license numbers, document bytes, or background details
- Sensitive categories flagged in API metadata

---

## API surface

Base path: `/api/platform-ops/driver-onboarding`

| Method | Path | Description |
|--------|------|-------------|
| GET | `/document-categories` | Checklist metadata |
| POST | `/applications` | Create draft |
| GET | `/applications` | Admin list |
| GET/PUT | `/applications/{id}` | Detail / update draft |
| POST | `/applications/{id}/submit` | Submit |
| POST | `/applications/{id}/documents` | Upload |
| PATCH | `/applications/{id}/documents/{doc_id}/review` | Staff review |
| POST | `/applications/{id}/status` | Controlled transition |
| POST | `/applications/{id}/approve` | Approve |
| POST | `/applications/{id}/reject` | Reject |
| POST | `/applications/{id}/suspend` | Suspend |
| POST | `/applications/{id}/activate` | Activate driver |
| GET | `/applications/{id}/readiness` | Advisory readiness |

### UI pages

- Applicant form: `/platform-ops/driver-apply?organization_id={org_id}`
- Admin workspace: `/platform-ops/driver-onboarding-admin`

---

## Compliance readiness (advisory)

Indicators computed per application:

- Identity complete
- License valid/unexpired
- Insurance present/unexpired
- Registration present/unexpired
- Required agreements signed
- Background review complete
- MVR review complete
- Training complete
- Vehicle assignment complete

These do **not** block the frozen transportation engine globally in Sprint 1.

---

## Deferred to Sprint 2

- Third-party background check vendor integration
- Live MVR vendor integration
- Screening payments
- Electronic tax filing / payroll / contractor payments
- Automated insurance verification
- Automated government database checks
- Training course delivery
- Vehicle inspection scheduling
- SMS campaigns
- Provider onboarding
- Rider onboarding
- Production document storage provisioning
- Enforcing onboarding gate in dispatch (optional wiring behind flag)

---

## Database

Migration: `20260731_driver_onboarding_s1`

Tables:

- `platform_driver_onboarding_applications`
- `platform_driver_onboarding_documents`
- `platform_driver_onboarding_audit_events`
- `platform_driver_onboarding_internal_notes`

---

## Regression requirement

Frozen transportation suites must remain green:

- `test_phase49_end_to_end_ride_workflow.py`
- Driver acceptance / dispatch lifecycle tests
- Scheduling tests (`test_scheduled_route_activation.py`, `test_multi_ride_driver_scheduling.py`)

Sprint 1 adds `test_driver_onboarding_sprint1.py` without modifying frozen engine files.
