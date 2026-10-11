# M06c2g2 — Opt-in server dispatch with owned recognition workers

Authorized by the user's “next” after M06c2g1. This part exposes exact-job dispatch through the local server and owns the child worker lifetime. Browser buttons and automatic capture/recognition scheduling remain separate review boundaries. Queue enrollment, artifact/registration/resolution review and explicit CLI dispatch continue to work.

## Activation and credentials

Server dispatch is disabled by default. `--recognition --free-tier-confirmed` explicitly enables existing Gemini recognition with the configured local `--key-file` or environment key and allowlisted `--recognition-model`. Voice and recognition activation remain independent; enabling voice alone does not enable recognition dispatch. The existing free-tier flag is an operator assertion, not a quota/account-tier check. There is no paid fallback or automatic provider retry.

For controlled smoke/evaluation, `--synthetic --recognition-replay PATH` enables a local JSON mapping of reading/detection replay responses. The mapping is limited to 2 MiB at CLI startup, rejects unknown kinds and validates the existing typed response schemas. Replay and Gemini startup modes are mutually exclusive. Replay dispatch requires saved evidence marked synthetic; a synthetic server flag alone does not turn existing real originals into synthetic evidence. Unconfigured replay kinds are rejected before spawn. HTTP callers cannot supply a replay, model, key, free-tier assertion, file path or worker token.

Live credentials remain in server memory and the child environment, never command-line arguments, queue records, status responses or saved replay files. Child stdout/stderr are discarded rather than buffering or exposing provider exceptions. Dataclass repr and dispatcher snapshots omit credentials. Existing provider adapters retain their single image request, socket timeout, structured validation and redaction; no provider transport or SDK is added. No actual credentials were read for this part's verification.

## HTTP contract

GET `/api/guidance/{session}/recognition/dispatch` reads dispatcher activation/mode/model, local-task active state, selected job ID, shutdown flag and fixed last outcome. It requires a known guided session. Other sessions can see a busy dispatcher but cannot see its selected job ID or last outcome. Queue GET remains the authoritative durable job/artifact/worker_active view; dispatcher active describes the owned local task, not all external CLI workers.

POST on the same path accepts only `{job_id}` using the existing bounded token contract. Host/Origin, no-store/CSP, ten-second body timeout and 4 KiB body bound apply. Unknown/cross-session targets are 404, invalid controls/extra fields 422, size 413 and disabled/busy/uncertain/missing-replay conflicts 409. It never dispatches a FIFO substitute or another kind.

A new accepted selected request returns **202** with accepted=true, observed job state and dispatcher state. Acceptance is not evidence completion or a guarantee that a provider request has begun. Poll existing queue/artifact endpoints or dispatcher state for completion. A repeat while the same owned task is active acknowledges that task without spawning again; a different job conflicts. A terminal selection returns **200**, accepted=false and verified saved job status/evidence without rerunning it. Publication/staleness and cancellation semantics remain those of the existing queue. Reads never start workers.

A lost HTTP response does not cancel the app-owned task. Repeating the selected job can acknowledge an active owned task or return its terminal result; running/active-cancelled attempts without this server's ownership are not automatically reset. If launch fails before a claim, fixed dispatch_failed status and the still-queued job permit a later explicit selection; no automatic retry is scheduled. Only the explicit POST can initiate a new child.

## Architecture and worker lifetime

RecognitionDispatcher retains one asyncio task, one process handle and a per-dispatch random worker ownership token. It launches the existing exact-ID recognition CLI through create_subprocess_exec, with no shell and hidden Windows process creation. CLI kind comes from saved job inputs. RecognitionQueue still arbitrates the global per-store worker slot under BEGIN IMMEDIATE, preventing overlap with independently invoked CLI workers. Reference/inventory/original validation and result hash/publication remain in that worker. No ledger registration, accepted identity, valuation or calibration is applied.

A backward-compatible optional worker_owner field is recorded on claim. CLI --worker-id is bounded and only allowed on --run-one. The interruption method accepts an optional expected_worker_id guard, checked under the same writer lock as closing the attempt. This prevents cleanup from closing an external worker's claim.

FastAPI lifespan owns shutdown. It marks the dispatcher closing, stops the known child, waits up to five seconds before escalating termination to kill, verifies process exit and waits for the managed task. A concurrent spawn is retained as a shielded task; shutdown waits for it to yield a handle, and the worker notices closing before continuing. A known exited child with this ownership token may have its unfinished running/active-cancelled claim marked interrupted/provider_outcome_unknown. Completed/cancelled-finished jobs retain their state. Other ownership tokens and pre-existing uncertain workers are never cleared by cleanup.

A hard server/process crash is not graceful shutdown. Durable active markers remain and require the existing explicit stopped-worker recovery; the server does not claim to detect or terminate orphan workers after restart. No automatic lease expiry, polling scheduler or implicit replay occurs. Graceful cleanup cannot undo a provider request already submitted, so stopped attempts retain unknown-outcome semantics. External --interrupt still requires confirming that the old process has exited.

Replay files are written off the HTTP/audio loop to server-owned per-dispatch local paths and removed after worker exit/failure. Provider work runs in the child, and queue/storage checks run off the async HTTP loop. The dispatcher retains only its latest fixed outcome; durable job status is the completion record. No raw process log or unbounded task queue is introduced. Store queue limits remain 200 retained/20 pending and one active worker.

## Verification and artifacts

Full regression: **406 Python tests and 49 Node tests passed**. All 30 targeted dispatch/selection/HTTP checks also passed. Git whitespace checks passed. Existing Starlette/HTTPX deprecation warning remains. Isolated async fixture setup may produce Python slow-task diagnostic messages; no new dependency is required.

Thirteen new Python checks cover real reading/detection subprocess completion via HTTP, exact repeats/restart, Host/Origin/body/session scope, default-disabled and free-tier/replay configuration, owned-child repetition and busy rejection, request-independent lifetime and active cancellation, shutdown during delayed spawn, fixed launch-failure status, owner mismatch protection, existing uncertain claims, live key transport only through a mocked child's environment, real-evidence/missing-kind replay rejection, and actual child termination before owned recovery. The termination check uses a controlled local child that claims the same ownership contract and then blocks without network; cleanup verifies its actual returncode before ledger recovery. It is not a live provider shutdown test.

Actual HTTP/process/restart smoke passed in `runs/m06c2g2-review`. A replay-enabled server enrolled two reading jobs and one detection job. Explicit POST selected the detection and second reading only. Real exact-ID child processes published reviewable evidence, while first-reading stayed queued and inventory/original frames stayed unchanged. Terminal repeats were 200 and no rerun. Restarting without activation rejected dispatch; restarting with replay activation returned identical saved jobs. Temporary response files were cleaned. Artifacts: replay.json, http-history.json, smoke-summary.json, server.log and setup/store originals/reports. Provider requests: zero. Test servers exited after smoke cleanup; no live reference retest was run.

The short existing provider checks from earlier modules remain historical. Real server-dispatched Gemini latency/quota, bookshelf/revisit accuracy, actual voice/camera/Android, metric geometry and three-minute end-to-end acceptance remain unmeasured. API controls are local prototype controls without user authentication; existing explicit origins still define allowed request sources.

## Operation

```powershell
.\.local\reference-env\Scripts\python.exe -B -m scripts.smoke_dispatch_http --output runs/my-http-dispatch
.\.local\reference-env\Scripts\python.exe -B -m library_claim.server --store runs/my-http-dispatch/setup/store --port 4192 --synthetic --recognition-replay runs/my-http-dispatch/replay.json
```

Select a saved job through the dispatch POST with its exact guided-session path and an allowed Origin header, then inspect the existing queue. The example store's selected jobs are already completed; first-reading is still queued. Starting the server alone does not consume it. Live activation uses --recognition --free-tier-confirmed and a local key file; never place keys in HTTP bodies, chat or queued JSON. Use graceful server shutdown when possible. After an abrupt exit, stop/verify any old worker before explicit CLI recovery of its uncertain job.

Proposed next part: **M06c2g3 explicit browser dispatch/status controls** using this opt-in API and saved job IDs, with active/uncertain/cancellation guidance. No automatic scheduling or browser dispatch implementation is included here.

**Awaiting user review.**
