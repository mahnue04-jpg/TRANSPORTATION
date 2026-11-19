# Nova Operations $49 Starter — customer release handoff

Status: **not live**. No production deployment or customer data use approved by this file.

## Verified deployment boundary (2026-11-18)
- Development code: `mahnue04-jpg/TRANSPORTATION`, PR #559, branch `feat/operations-supervised-csv-pilot-20261118`.
- Existing Render staging web: `nova-operations-staging-541` (`srv-dbujmrmk1f9s73afmp6g`), URL `https://nova-operations-staging-541.onrender.com`.
- Render service repository is `mahnue04-jpg/nova-central-intelligence-staging`, branch `feature/nova-hosted-operations-endpoint`.
- Render start is `bash start-operations.sh`; build command insists `RENDER_GIT_COMMIT=a24d806bf485a5ec7073783ed20b1ea609b283e0`.
- Automatic deploys and PR previews are OFF. Thus PR #559 commits are **not** running on this service, and CI passing in TRANSPORTATION does **not** establish staging acceptance.
- Do not silently repoint or redeploy this service; coordinate an explicitly approved release artifact or separate compatible staging service.

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
