# Nova Operations $49 Starter — customer release handoff

Status: **not live**. No production deployment or customer data use approved by this file.

## Verified deployment boundary (2026-11-18)
- Development code: `mahnue04-jpg/TRANSPORTATION`, PR #559, branch `feat/operations-supervised-csv-pilot-20261118`.
- Existing Render staging web: `nova-operations-staging-541` (`srv-dbujmrmk1f9s73afmp6g`), URL `https://nova-operations-staging-541.onrender.com`.
- Render service repository is `mahnue04-jpg/nova-central-intelligence-staging`, branch `feature/nova-hosted-operations-endpoint`.
- Render start is `bash start-operations.sh`; build command insists `RENDER_GIT_COMMIT=a24d806bf485a5ec7073783ed20b1ea609b283e0`.
- Automatic deploys and PR previews are OFF. Thus PR #559 commits are **not** running on this service, and CI passing in TRANSPORTATION does **not** establish staging acceptance.
- Do not silently repoint or redeploy this service; coordinate an explicitly approved release artifact or separate compatible staging service.

## Deployment mechanism verified — why redeploying old staging is not enough
Read-only inspection of `mahnue04-jpg/nova-central-intelligence-staging` / `feature/nova-hosted-operations-endpoint`:
- `build.sh` creates a scratch Git repository and fetches **fixed** upstream `ce3c39385e540f4b99a3340f20c01a1c55987a1f` from TRANSPORTATION. It applies `staging.patch`, `operations-handoff.patch` and `hosted-operations.patch`, then installs dependencies and moves the result into `.nova-source`.
- `start-operations.sh` launches `nova_operations_synthetic_staging:create_app` from that imported source. This is **not** the customer-capable FastAPI `app.main` entrypoint.
- Render additionally hard-pins its own staging repository commit `a24d806bf485a5ec7073783ed20b1ea609b283e0` in the build command. Therefore **neither PR #559 nor its CI automatically updates this service**.
- Do not remove pins/apply old patches against a new upstream head without checking source compatibility. Do not switch the public diagnostic staging service to `app.main` because that can activate unrelated application initialization with incompatible database and secrets.
- **Confirmed additional hazard:** importing `app.main` invokes `ensure_marketing_schema()`, which can create/alter tables; application startup runs multiple other schema ensures and auth seed logic. A generic full-app Render Blueprint is therefore **not** an acceptable zero-risk staging solution.

### Proposed isolated staging route — requires explicit owner approval
1. Preserve the existing synthetic staging service unchanged and keep production untouched.
2. **Do not directly start `app.main` for a validation-only service.** Read-only code inspection confirms `app.main` calls `ensure_marketing_schema()` during import, and the FastAPI lifespan calls `init_db()`, `init_platform_db()`, auth schema initialization and default-user seeding, Health ISF schema ensures, Nova Today schema ensures, and deferred platform startup. These are potentially mutating and broad in scope. First implement/review a narrowly scoped validation entrypoint that excludes these startup effects (or use only an explicitly disposable and isolated full-stack database with all initialization reviewed). Pin exact PR #559 SHA; no production data or shared credentials.
3. Use a separate disposable PostgreSQL database with a defined backup and rollback; run only reviewed migrations there. Set all live customer sales, customer processing, worker, queued processing, paid provider, and live Stripe flags OFF by default.
4. Initially check public readiness, owner login, route registration, and safe synthetic authorization denials; run a test-mode *lead-specific* payment-to-task flow only after the binding schema has been reviewed and applied in this disposable database.
5. Add private storage ONLY after provider credentials, bucket isolation, tenant scoping, retention, and cost have been approved. Never upload real customer files during rehearsal.
6. Before deploying to production, demonstrate secure customer-specific owner-approved delivery, explicit refund/cancellation/terms handling, failure recovery, monitoring and rollback.

**Not yet approved or performed**: creating a Render service/database, modifying environment variables, applying DDL, sending test Stripe requests, redirecting DNS, enabling paid checkout, or deploying production.

## Minimal validation entrypoint prepared (not deployed)
The PR now includes `backend/operations_isolated_validation.py`, a separate FastAPI application that mounts only the owner Operations router with **all processing/payment/worker flags required OFF at startup**. It does not import `app.main` or call its startup lifecycle. It exposes `GET /health` with explicit `synthetic_only=true`, `customer_processing=false`, and `customer_delivery=false`. It has no customer-facing purchase route or delivery method. If a prohibited flag is enabled, startup raises an error.

For an **owner-approved** isolated Render web service, an example reviewed source configuration would be:
- Repo: `mahnue04-jpg/TRANSPORTATION`; immutable reviewed branch commit, never a floating development branch.
- Root directory: `backend`.
- Build: `pip install -r requirements.txt`.
- Start: `uvicorn operations_isolated_validation:app --host 0.0.0.0 --port $PORT`.
- Health: `/health`.
- APP_ENV and AMICOR_ENVIRONMENT: `development` or `staging` (never production).
- Explicitly set `NOVA_STRIPE_LIVE_ENABLED=false`, `NOVA_OPERATIONS_CUSTOMER_SALES_ENABLED=false`, `NOVA_OPERATIONS_OWNER_CSV_ENABLED=false`, `NOVA_OPERATIONS_STARTER_BINDING_ENABLED=false`, `NOVA_OPERATIONS_DURABLE_CSV_ENABLED=false`, `NOVA_OPERATIONS_QUEUED_CSV_HTTP_ENABLED=false`, `NOVA_OPERATIONS_LEASE_WORKER_ENABLED=false`.
- No production secrets, customer PostgreSQL, private S3, external payment provider API keys or background jobs. Do not turn this diagnostic web service into customer processing by changing its flags.

**Limit:** This service is useful to validate isolated startup and route denial, but by design it cannot complete the paid customer journey. A separate approved data-backed staging plan and secure customer delivery path must be built before live release.

## Minnesota sales-tax classification and Stripe launch gate (2026-11-20)

**Tax research is preliminary, not a determination letter or authorization to collect tax.** Minnesota DOR distinguishes between prewritten downloaded software (generally taxable), remotely hosted software without customer possession (subscriptions generally not taxable), and most professional and customer-data-processing services (generally nontaxable). Apply the classification to the actual contractual deliverables, not the Nova branding.

| Product / commercial promise | Preliminary Minnesota classification | Release action |
| --- | --- | --- |
| $49 Operations Starter: owner-reviewed processing of a customer CSV into a cleaned file | Generally nontaxable data processing/service, if no software license is delivered | Confirm scoped statement of work, invoice description, no bundled software license; request tax adviser review before sales |
| $99/$299 Operations monthly managed work | Generally nontaxable services when primarily human-reviewed support | Do not sell subscriptions until service limits, billing, and fulfillment reviewed |
| VoiceLedger Pro downloadable prewritten app/standalone ZIP license | Generally taxable prewritten software even when electronically delivered | Verify MN registration, tax coding, customer address sourcing, local rates and returns BEFORE paid license checkout |
| Growth Agent or CFSS Co-Pilot hosted-only access | Generally nontaxable hosted software if the customer receives no software copy | Confirm terms/delivery and compliance; both remain gated from live commerce |

Official Minnesota DOR references:
- https://www.revenue.state.mn.us/guide/computer-software-and-digital-products
- https://www.revenue.state.mn.us/guide/nontaxable-sales-8
- https://www.revenue.state.mn.us/guide/registering-your-business
- https://www.revenue.state.mn.us/guide/taxes-and-rates
- https://www.revenue.state.mn.us/guide/accounting-services
- https://www.revenue.state.mn.us/sites/default/files/2023-12/fs173.pdf

**Owner confirmation (2026-11-20):** AMICOR HEALTH ISF LLC does not have a Minnesota Sales and Use Tax account/permit. State registration remains outstanding. Do not claim registered status or take taxable Minnesota software orders. This does not require stopping separate nontaxable managed-service inquiries; their exact statements of work still require tax classification review.

**State registration checklist:** Use the official Minnesota Department of Revenue business-registration process (https://www.revenue.state.mn.us/guide/registering-your-business) before the first taxable Minnesota sale. Confirm whether AMICOR already has a Minnesota Tax ID for another tax type (federal EIN and Secretary of State filing number are not the same). Prepare exact legal name, business mailing/physical address, federal EIN, ownership/legal structure, primary contact, business activity, first planned taxable sale date, cash/accrual accounting method, and expected filing cadence. Select Sales and Use Tax, plus applicable local-tax obligations. Save the issued state confirmation securely; do not put IDs, secrets, or login credentials in GitHub. After registration, configure and verify the actual registration jurisdiction and product-specific tax behavior in Stripe; do not register a jurisdiction there until state registration has occurred. Filing obligations continue according to the assigned schedule.

**Tax-obligation caveat:** The Minnesota DOR states that businesses selling only nontaxable items generally need not register for sales tax; AMICOR may nevertheless need a Minnesota Tax ID or use-tax registration for other purposes or purchases. Confirm the exact position with DOR or a Minnesota tax professional. Do not delay the nontaxable service's technical acceptance while resolving downloadable-software tax.

**Read-only live Stripe evidence on 2026-11-20:** Account `Amicor Nova` has charges/payouts enabled, but Stripe Tax settings report `pending`, no default tax code/behavior or head-office address in Tax settings, and `GET /v1/tax/registrations` returned zero registrations. This does NOT establish AMICOR's actual state tax-registration status. Verify it through Minnesota e-Services or with the accountant before treating taxable software as eligible for sale.

**Payment release controls:** Do not activate automatic tax, register jurisdictions in Stripe, add taxable products, or enable live purchases by guessing a tax code or tax registration. In particular, the generic live $49 Payment Link is not a lead/task-specific checkout and must NOT be linked as a ready purchase path until controlled fulfillment is operational. Existing owner-approved live payout banking can remain unchanged. Review out-of-state customer tax obligations separately.

## $49 first-customer acceptance chain
1. Save lead and explicitly agreed one-time CSV scope. Confirm legal customer identity and authorization to process their data. No implied unlimited work.
2. Create a **saved lead-specific** Stripe Checkout; verify the signed checkout event, exact saved checkout/session/customer, USD 4900, payment status paid. Do not assume the public generic Stripe Payment Link maps to a lead/task.
3. Persist exact one-to-one paid Starter checkout -> tenant owner -> engagement -> task binding. Migration for `nova_operations_starter_payment_bindings` is review-only and NOT executed. Preserve existing data, take backup and validate migration first.
4. Owner confirms and explicitly accepts the saved task scope before file intake. Service denies mismatched payment, client, tenant or task.
5. Use secure authenticated customer intake and private storage; ensure no plaintext file in public URL/log. Current reviewed CSV flows are development-only and private object storage is NOT activated.
6. Execute bounded CSV cleanup, validate output, and hold for owner approval. Approval is **not** customer delivery.
7. Deliver through a restricted, expiring customer-specific mechanism after owner approval, with delivery evidence and retention/deletion controls. There is **no verified live customer delivery service** yet.
8. Complete isolated staging run with noncustomer synthetic data, then separately authorize release and verify real website route, billing, backend, storage, monitoring and rollback.

## Release constraints
- Feature switches stay off until matching DB+storage+operational readiness, contract/authorization, and a controlled release.
- No customer data in synthetic rehearsal and no live customer order until the service can securely fulfill it.
- $99 and $299 monthly plans are later releases; no automatic enrollment after Starter Task.
- Never represent a synthetic Render health check as verified customer processing.
