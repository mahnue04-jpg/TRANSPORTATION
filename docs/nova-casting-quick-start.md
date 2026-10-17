# Casting sandbox quick-start

Owner demo for draft pull request #339 on branch `cursor/casting-auditions-pilot-e1ae`. Harborlight is a fictional sample. This is not a contract, a partnership, or a public casting call. Nothing on this page sends email, SMS, or WhatsApp, and nothing publishes a campaign.

Use an existing Nova account. Casting does not register users. Leave `enabled`, `applications_enabled`, and `media_uploads_enabled` false.

## Open the sandbox

1. Point the process at a disposable database and set `AMICOR_ENVIRONMENT`, `ENVIRONMENT`, and `APP_ENV` to the same allowlisted name, such as `disposable`.
2. Set `NOVA_CASTING_STAGING_READS=true` on that process only.
3. Sign in and open `/static/nova-creative/casting-sandbox.html`.
4. Create the sandbox organization and keep the campaign at `DRAFT`.
5. Choose **Load Harborlight sample**. The page must say the sample was saved and that nothing was sent.

## Walk the authenticated journey

1. Save an adult pilot draft with an `https://` audition link and the consent box checked. Submit it. The receipt starts with `CA-`.
2. Search the review queue and shortlist the submitted application. Save a rubric note. The note does not cast anyone.
3. Draft a callback email and approve it. Delivered stays false.
4. In **Authenticated sandbox journey**, set an expiration and choose **Issue invitation**.
5. Reload the page and choose **Reload saved pilot**. The invitation token must come back in the journey field. That is the server copy.
6. Choose **Redeem invitation**. The same draft application is reused.
7. Load the call sheet. It uses the schedule timezone already stored for the sample.
8. Choose **Run mock transport**. The status must show `mock_accepted` and `Real delivery: false`. The receipt starts with `MOCK-`. Running it again returns the same receipt.
9. Choose **Export sandbox CSV**. The file must not contain an `https` link.
10. Choose **Try expired invitation**. The status must say the expired invitation stayed closed.
11. Choose a synthetic video file and **Validate mock upload**. A clean result still has no public URL and does not play. **Wipe mock memory** clears the hold.

## What a failed step means

- Age under 18, missing consent, or a non-https link: no receipt.
- Unapproved draft: mock transport is refused.
- Closed campaign: a new invitation is refused with "Campaign cannot be published".
- Another tenant: "Application unavailable".
- STOP, revoked consent, or an empty address: the mock outcome is `suppressed`. Unsubscribe: `opted_out`.

## Stop

Unset `NOVA_CASTING_STAGING_READS`. Routes return 503. Rollback steps are in `docs/nova-casting-staging-runbook.md`. Do not merge, deploy, or turn on public intake from this demo.
