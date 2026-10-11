# M06c2b — Browser reading enrollment and review

Authorized by “next” after M06c2a. This part exposes the durable reading queue through explicit HTTP controls and a small browser page. Recognition still runs through the independent CLI worker. No automatic camera scheduling, detection registration, text confirmation, identity acceptance or valuation is added.

## Architecture and behavior

`/recognition` opens a bound guided session, displays saved physical observation/track/shelf IDs and original links, then offers Queue reading. Requests freeze the displayed inventory/reference revisions, observation ID and original SHA256. Enqueue reuses the M06c2a gates; stale inputs are rejected rather than rebased. The browser retains a stable job ID for exact retries of the same displayed inputs during that page lifetime. Refresh does not enqueue, retry a provider or change inventory.

The observation list is paged (50 by default, 100 maximum), with revision pins displayed. Jobs are filtered to the selected guided session and bounded by the queue's existing 200-per-store retention cap. The page shows queue lifecycle separately from the reading stage result and current review eligibility. A partial completed result is still unverified; stale evidence is visibly ineligible. Published evidence JSON and crop links remain available for historical inspection after staleness. The original saved evidence stays linked separately.

Cancel reading explicitly revokes queued/running publication. It cannot undo a provider call already submitted. Interrupted running attempts are resolved through the existing explicit CLI workflow after the old worker is stopped; the browser cannot interrupt or start workers. A successful cancellation does not authorize automatically enrolling another attempt. A fresh page/new job ID is needed for a new attempt with the same pins. Queue requests never accept reading text into inventory.

`ReadingView` aborts previous loads, uses generation guards for late responses after session/page changes, verifies the response target and bounds load time to ten seconds. The page clears old enrollment controls during refresh/navigation. Mutation responses from an old view cannot refresh a newer session; their explicit submitted request may still commit. Mutation timeouts retain the same enrollment ID for retry and direct the reviewer to inspect saved state. Rendered IDs/statuses use textContent; evidence URL components are encoded.

## HTTP contracts

- GET `/api/guidance/{session}/recognition?offset=0&limit=50`: bound session, current revision pins, observation page, total count, session-filtered job projections and explicit CLI worker mode. Read-only.
- POST on the same path: existing ReadingJob contract; body and URL session must match. Exact enqueue retry is idempotent.
- POST `/api/guidance/{session}/recognition/cancel`: bounded token `job_id`; job must belong to this session. No provider dispatch.
- GET `/api/guidance/{session}/recognition/{job_id}/reading_result.json` or `/crop.png`: published artifacts only, matching session, full manifest integrity plus returned-byte hash validation. Other filenames are refused; arbitrary directories/reports/provider payloads are not served.

Existing exact Host/Origin boundaries, 4 KiB control-body limit, ten-second body timeout and typed errors apply. Invalid control/page bounds are 422, stale input/artifact corruption or absent published artifact is 409, missing or different-session jobs are 404, and storage failure is 503. API storage mutations run in the threadpool; read handlers are synchronous FastAPI worker handlers. Health advertises M06c2b and `recognition_worker=explicit_cli`. The optional voice key is unnecessary for this page. Local prototype reviewer authentication remains unchanged; Origin/Host checks are not remote user authentication.

## Regression repair

The first full regression run had one Windows locked-file cleanup failure in the existing voice resumption test. Its SQLite connections already closed explicitly, but cancellation of a threadpool waiter could let its SQLite work outlive the voice task. Voice storage calls now shield and drain the underlying local worker before a cancelled voice task releases its session. A deterministic test holds a worker open, cancels its waiter and proves task completion waits for resource release. No provider call is wrapped by this helper. The failed run is recorded rather than counted as passed.

## Verification and artifacts

Six new Python HTTP checks cover enqueue/exact retry/restart without dispatch, control/Host/Origin/page bounds, stale/hash rejection, cancellation and different-session access, publication/artifact integrity and page/assets/health. Five new Node tests cover pinned enrollment, late session response rejection, response-target validation, literal rendering/explicit actions and stale-result presentation. The voice storage drain regression adds one Python check.

Final full regression: 344 Python tests and 32 Node tests passed. Existing Starlette/HTTPX deprecation warning remains.

Actual synthetic target HTTP/CLI/restart smoke passed in `runs/m06c2b-review`: saved two observations, exact enrollment retry, restart with queued state, separate replay worker, partial evidence/crop retrieval, cancellation before worker, restart with completed/cancelled states and unchanged inventory. Provider requests: zero. Files include `http-history.json`, `smoke-summary.json`, `response.json`, server log and reused setup store/originals. Run:

```powershell
.\.venv\Scripts\python.exe -B -m scripts.smoke_recognition_http --output runs/my-browser-reading-smoke
.\.venv\Scripts\python.exe -B -m library_claim.server --store runs/my-browser-reading-smoke/setup/store --port 4188 --synthetic
```

Open `/recognition?session=eeeeeeeeeeeeeeeeeeeeeeeeeeeeeeee` on that server. Actual in-app browser smoke displayed physical targets/revision pins and partial result links, queued a new saved observation through Queue reading, then cancelled it through Cancel reading and verified the terminal outcome. Screenshot: `runs/m06c2b-review/browser-cancelled.png`. Browser startup was unusually slow; page controls then worked. The test server was stopped afterward. The user-tested reference was not run.

No real shelf reading accuracy, provider queue call, Android/microphone/three-minute conversation or geometric readiness is claimed. These remain the earlier documented validation boundaries. Proposed next small part: M06c2c bounded saved-frame detection jobs with explicit shelf-region inputs, keeping physical registration and acceptance reviewed separately. Automatic capture enrollment still needs a later boundary.

**Awaiting user review.**
