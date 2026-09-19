# AMICOR business email (W9)

Official domain: **getamicor.com**.  
Public contact address: **info@getamicor.com**.  
Commercial alias: **sales@getamicor.com**.

**Email Routing is ACTIVE and VERIFIED.**

| Check | W9 result |
|---|---|
| Cloudflare Email Routing | Enabled / status `ready` |
| Public MX | `route1/2/3.mx.cloudflare.net` |
| info@getamicor.com | Forwards to the owner inbox. Owner tested from a separate iCloud account; message arrived. |
| sales@getamicor.com | Forwards to the same owner inbox. Owner tested from a separate iCloud account; message arrived. |
| Catch-all | Disabled |

Do not write the private destination inbox (the personal address that receives the forwarded mail) in this repository, in `site-config.js`, or on the public website.

Cloudflare Email Routing is included with the existing Cloudflare zone. Do not buy Google Workspace, Microsoft 365, or another paid mailbox for this phase unless the owner later chooses to.

## Recommended aliases

Active now:

| Public address | Use | Destination |
|---|---|---|
| info@getamicor.com | General public contact | Owner’s existing personal inbox already used for the Cloudflare / Wrangler login |
| sales@getamicor.com | Software, demo, and commercial conversations | Same destination inbox at first |

Optional later (same destination unless you split later):

| Public address | Use |
|---|---|
| support@getamicor.com | Product and early-access follow-up |
| partners@getamicor.com | Insurers, advisors, and operating partners |
| privacy@getamicor.com | Privacy and legal-draft questions |

Catch-all remains **disabled**. Do not enable it unless you want every misspelled address forwarded to the same inbox.

## Who should receive the mail

Route **info@** and **sales@** to the **same existing owner inbox** already used to sign in to Cloudflare. That keeps setup free and avoids a second mailbox.

Replies still come from the personal inbox until a later “send as info@getamicor.com” step is approved. Do not publish the personal address.

## Exact Cloudflare owner setup (reference)

info@ and sales@ are already live. Use these steps only to add later aliases or to rebuild routing if it is disabled.

Use the Cloudflare account that already owns getamicor.com and the Pages project `amicor-public`. You must be using Cloudflare DNS for this domain (already true for the public site).

### 1. Open Email Routing

1. Sign in at https://dash.cloudflare.com
2. Open the **getamicor.com** zone.
3. Try the current path first: **Compute** → **Email Service** → **Email Routing**.  
   If that menu is missing, use the classic path: **Email** → **Email Routing**.
4. If the page asks to onboard a domain, choose **getamicor.com**.

Official reference: https://developers.cloudflare.com/email-routing/get-started/enable-email-routing/

### 2. Enable routing and accept DNS records

1. Select **Onboard Domain** or **Enable Email Routing** / **Get started**.
2. Review the DNS records Cloudflare will add on getamicor.com:
   - **MX** records that send incoming mail to Cloudflare
   - **TXT** SPF record that authorizes Email Routing
   - **TXT** DKIM record for authentication
3. Confirm those records. DNS usually updates in 5–15 minutes; allow up to 24 hours.
4. Do **not** keep a different mail host’s MX records. getamicor.com has no mail host today.

### 3. Add and verify the destination inbox

1. Open **Destination addresses** (account-level; reusable across domains).
2. Enter the owner’s existing personal inbox (the Cloudflare login inbox). Do not type that address into this repo.
3. Submit.
4. Open the verification email Cloudflare sends to that inbox.
5. Select **Verify email address**.
6. Wait until the destination shows as verified. Routing rules will not deliver before this.

### 4. Create the info@ rule

1. Stay on **Email Routing** for **getamicor.com**.
2. Open the **Routing rules** tab.
3. Select **Create routing rule**.
4. Email pattern / custom address: `info` @ `getamicor.com`
5. Action: **Send to an email**
6. Destination: the verified owner inbox
7. Save.

### 5. Create the sales@ rule

1. **Create routing rule** again.
2. Email pattern: `sales` @ `getamicor.com`
3. Action: **Send to an email**
4. Destination: the same verified owner inbox
5. Save.

Optional aliases later: repeat for `support`, `partners`, and `privacy`.

### 6. Confirm status

Routing is actually active only when **all** of these are true:

- Email Routing shows **Enabled** for getamicor.com
- Destination address is **Verified**
- `info` and `sales` rules exist and are enabled
- Public DNS for getamicor.com has Cloudflare Email Routing **MX** records

### 7. Test from a different mailbox

1. Send a short test to info@getamicor.com from an account that is **not** the destination inbox (Gmail often drops mail that appears to come from itself).
2. Send a second test to sales@getamicor.com from that same other account.
3. Check the destination inbox and spam folder.
4. If nothing arrives after DNS has propagated, re-check MX records and that the destination is still verified.

## What this does not do

- It does **not** send Early Access form leads by email. Form leads stay in Cloudflare KV.
- It does **not** create a paid mailbox or a CRM.
- It does **not** let the public site send mail by itself.
- It does **not** change Health ISF, Stripe, Delivery, Driver 001, Lifesaver, or Nova.

## Lead form vs mailbox

| Path | What happens today | Depends on Email Routing? |
|---|---|---|
| Early Access / Request Demo form | Validated `POST /api/leads` writes the AMICOR KV lead store | No. Form success does not require mail. |
| Optional `LEAD_WEBHOOK_URL` | Pages dashboard secret only; best-effort notify | No. Must not be stored in git. |
| info@ / sales@ | Human-written email | Yes. W9: active and owner-verified. |

List stored form leads (owner only; this prints keys, not a public inbox):

```powershell
cd website
npx wrangler kv key list --namespace-id aef188e1167a41c98ee81deabbbce50d --remote --prefix lead:
```
