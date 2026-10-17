# Issue #351 — TEST feature deploy checklist

**Goal:** Deploy the Studio walking-commercial feature in **TEST mode** so we can see what still needs fixing. Not live billing. Not paid Genova. Not ad publish.

## Already done in code (this branch)

- [x] 5s walking presenter proof
- [x] 30s walking talking commercial (H.264/AAC, speech, phoneme lip sync, captions)
- [x] AMICOR Stripe TEST checkout + simulated complete + receipts + job status
- [x] Voice license acceptance (AMBER → GREEN)
- [x] Guardrails expose `studio_test_feature` / TEST readiness in UI
- [x] Automated tests for service + signed-in API paths
- [x] Approved 60s commercial unchanged; live providers default OFF

## Owner steps to put TEST feature on the host

1. **Open & merge PR** from `cursor/creative-studio-presenter-351-09a7` → `main`  
   Compare: https://github.com/mahnue04-jpg/TRANSPORTATION/compare/main...cursor/creative-studio-presenter-351-09a7?expand=1
2. **Deploy** the backend to the existing Studio host (do not rename `amicor-health-isf`).
3. **Optional but useful:** add Render secrets `STRIPE_SECRET_KEY` (`sk_test_...`) and `STRIPE_PUBLISHABLE_KEY` (`pk_test_...`). Without them, simulated TEST checkout still works.
4. **Confirm host can reach edge-tts** (outbound HTTPS). Natural female voice needs network; no API key purchase.
5. **Smoke on the live TEST host:**
   1. Sign in to Creative Studio  
   2. Check **TEST feature readiness** card  
   3. Create 30s project → storyboard  
   4. Accept voice license  
   5. Build 30s walking commercial → download on phone  
   6. Start TEST checkout → Complete TEST payment → confirm receipt  

## What to watch for after TEST deploy

| Symptom | Likely fix |
| --- | --- |
| Voice render fails | Host blocked from edge-tts / outbound HTTPS |
| Checkout says unconfigured | Add Stripe TEST keys, or use Complete TEST payment (simulation) |
| Download 401/404 | Session / owner scoping; re-sign-in |
| Duration outside 28–32s | File a bug with ffprobe output |
| Want photoreal Genova | Separate paid-provider budget approval — not part of TEST feature |

## Explicitly still OFF after TEST deploy

- Stripe LIVE / real customer charges  
- fal/Kling/D-ID/OpenAI live flags and credit purchases  
- Public advertisement publish  
- Changes to the approved 60s commercial  
