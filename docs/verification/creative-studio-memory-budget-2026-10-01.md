# Creative Studio memory-limit failure — October 1, 2026

## Confirmed production cause

The owner's Render Events screenshot identifies `Instance failed: k4kn7` at 08:13 CDT with `Ran out of memory (used over 512MB) while running your code.` The service is Starter, not the free-plan setting in render.yaml. Commit b0d9770 (PR 223) was deployed at 07:37. Render subsequently reported recovery at 08:13. This confirms a memory-limit kill as the outage mechanism after the recovery patch. A gateway has no healthy application response during that kill/restart, explaining the associated 502. The screenshot does not identify the individual allocation or request responsible.

## Findings

PR 223 serialized scene workers only. Standalone image generation and final-promo generation could overlap those workers. FFmpeg's veryfast encoder also buffered frames despite single-thread settings. A local import of the application peaked near 177 MiB; this is not a measurement of production's warm baseline.

A controlled local 5-second encode from a 1024×1536 PPM into 720×1280 H.264 used cumulative child-process peak RSS of approximately 141 MiB with zerolatency/ref=1, then 203 MiB with the previous settings. The lower-memory configuration ran first, so the second cumulative maximum represents the higher-memory encode. Both completed successfully. This demonstrates a reduction for this fixture, not a reconstruction of production's exact peak.

## Changes

- One reentrant capacity lock shared by image generation, scene-video generation, and final-promo assembly. Nested image creation within a scene/final promo remains supported.
- All Studio FFmpeg encoding stages use zerolatency and one reference frame, retaining output dimensions, frame rate, and CRF.
- A cgroup-aware runner refuses to start FFmpeg with less than 256 MiB of headroom. During encoding it checks memory every 20 ms and kills the encoder if headroom drops below a 96 MiB web-service reserve.
- Encoder logs spool to a temporary file; only the last 16 KiB is loaded into Python memory.
- Internal phase and encoder logs record cgroup usage/limit and sampled peak, providing evidence for any further allocation investigation.

## Verification

- 46 backend tests passed, including actual MP4 rendering, persistent/restart scene recovery, refusal under simulated 512 MiB pressure, termination of a real child process when the reserve is crossed, bounded logs, and shared/reentrant concurrency.
- 7 frontend scene polling tests passed.
- No paid provider calls or production deployment performed by the assistant.

## Limits

This is a memory-pressure mitigation and graceful encoder-failure path, not an increase to Render's 512 MiB limit. The sampling guard cannot guarantee protection against instantaneous allocation spikes or unrelated application allocations. It requires readable cgroup memory metrics; on unsupported/unlimited systems the runner retains timeout and bounded-log protection. The shared lock assumes the existing single web process. Actual production scene completion and memory stability must be checked after deployment. If the warmed application's baseline leaves insufficient headroom, rendering will report a normal error and the workload will need further reduction or a separate appropriately sized worker. The owner has not authorized a hosting-plan upgrade.
