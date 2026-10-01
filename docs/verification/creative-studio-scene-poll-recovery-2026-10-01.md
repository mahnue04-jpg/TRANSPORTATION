# Creative Studio step 8: status-check recovery

The owner confirmed that the remaining 502 appears while using **8. Generate Next Scene**, after deployment of main commit 57434bc containing PRs #219 and #220. Screenshots show generated scene clips and a voice result alongside an error banner. They do not identify which HTTP request failed or establish a completed final promo.

## Verified defect and change

The browser's scene-job polling function threw on the first failed GET request. A 502 from the gateway or a network interruption therefore stopped monitoring the persisted job, even though the backend job could continue. During RUNNING status it also fetched the entire project a second time to refresh assets; failure of this redundant read also stopped monitoring.

Status reads now retry network and HTTP 5xx failures against the same project and job ID, without submitting another generation request. Successful reads reset the consecutive-failure count. After twelve consecutive failures (approximately one minute), the UI identifies the saved job and explicitly says its result is unknown, with instructions to reconnect. Authentication and provider-job errors continue to surface immediately. The redundant project read during polling is removed.

This corrects an independently reproduced frontend defect. It does not prove why Render returned the production 502. Authenticated request traces and Render application/process logs at the failing timestamp were unavailable. A worker restart, resource pressure, proxy interruption, or a different failing request must be distinguished with that evidence before claiming the infrastructure fault is resolved.

## Verification

Seven frontend tests pass, covering exact-job correlation, project switching, worker errors, transient 502/503 recovery through completion, bounded persistent failures, immediate session errors, and API error classification. JavaScript syntax and whitespace checks pass. No paid generation requests were made and no deployment was initiated.

After deployment, verify step 8 on the existing project. If an error remains, record its timestamp and the failing request URL/status in browser Network, plus Render logs covering that timestamp (including restart/OOM events). Do not infer real AI motion, complete assembly, or production reliability from GENERATED labels alone.
