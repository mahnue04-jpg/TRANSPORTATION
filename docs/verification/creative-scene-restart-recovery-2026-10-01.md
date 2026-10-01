# Creative Studio restart recovery — October 1, 2026

## Production evidence

Owner-provided Render application logs show successful Creative Studio GETs through 07:04:24 CDT, `Instance restarted` at 07:04:43, and application startup at 07:05:04. This overlaps the owner's full-page Nova Today 502. The restart is confirmed; its trigger (memory limit, crash, manual restart, or infrastructure event) is not present in the supplied logs. No claim that memory exhaustion caused this restart is made.

The later government search logs are a separate failure: empty Tavily results, repeated 15-second DuckDuckGo connection timeouts, exhausted fallback providers, and requests completing with HTTP 200 after approximately 31 seconds. They do not establish the restart cause.

## Confirmed recovery defects and changes

- Background scene workers run inside the web process and are lost on restart. Previously a fresh persisted RUNNING job was treated as active for 20 minutes even when its worker no longer existed.
- Runway previously polled for up to its configured wait before returning the new task ID to the service. The background path now returns that ID immediately so the service can commit it before polling.
- Owner-scoped project polling now distinguishes this process's registered workers from interrupted jobs. It reconnects once to an interrupted job's persisted Runway task, retaining the same job and remote task. This recovery begins when the owner opens/polls the project, rather than automatically scanning every project at startup.
- A completed persisted result is recovered without generating the next scene. Unknown submissions without a saved task become an explicit ERROR with provider-history instructions; a GET never automatically creates replacement paid work.
- Scene workers are serialized within the current single-process service, and remote video downloads use 1 MiB reads with partial-file cleanup. These reduce concurrent resource pressure; they do not prove the cause of the observed restart.

## Verification

- 42 backend tests passed across Creative Studio and scene jobs, including restart reconnection, duplicate recovery polls, unknown submission handling, completion recovery, task-ID return before polling, partial download cleanup, database persistence, and real FFmpeg output.
- 7 existing frontend scene-poll tests passed.
- No paid provider calls were made. No live scene generation or production deployment was performed.

## Remaining limitations

The deployment still uses in-process workers and process-local ownership/concurrency locks. This is not a distributed queue for multiple web processes. A crash between remote task creation and its database commit is inherently ambiguous; this change reports that ambiguity rather than silently submitting another task. Render media storage persistence and the actual restart trigger still require production evidence. The observed Business access denial/identity answers are not changed by this scene recovery patch.
