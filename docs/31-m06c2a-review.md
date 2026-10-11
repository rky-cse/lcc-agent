# M06c2a — Durable reading queue

Authorized by the latest “next”; M06c2 is split to preserve the requested small implementation/review boundaries. This first part queues one saved physical observation for the existing M05a reader and runs one job per independent CLI worker invocation. Detection scheduling, HTTP/browser enrollment, automatic camera/preview scheduling and recognition acceptance remain separate follow-ups.

## Architecture and contracts

`library_claim.recognition_jobs` reuses FrameStore SQLite, GuidanceStore, `prepare_crop`, `export_reading` and the existing bounded Gemini adapter. No reference app retest, dependency installation or new provider transport was needed. Recognition workers run outside the audio/camera server; this part adds no server startup task or automatic inference.

`ReadingJob` contains a globally unique bounded token job ID, bound guidance session, expected reference revision and the existing ReadingRequest (sweep, inventory revision, observation ID, original SHA256). Enqueue validates capture binding, reference revision, observation/geometry and original integrity. An exact enqueue retry returns the original job even after inputs become stale; changed inputs with the same ID fail. No input is silently rebased. Reference revision is conservatively pinned even though reading does not calculate metric scale. Unrelated dialogue revisions do not invalidate reading.

SQLite writer transactions serialize enqueue/claim/publication. Bounds: 200 retained jobs per store, 20 queued/running jobs, one globally running worker. Jobs progress from queued to running, then completed, stale or failed; explicit cancellation revokes publication. Completed is an attempt outcome, with the reader's separate success/partial/unavailable stage status. It never means verified text or accepted identity. All outputs retain the M05a original/crop/region provenance and report. Every exported file is hashed before publication and verified when reading completed results.

The worker commits running before any provider request and releases the database lock during recognition. It checks pinned inputs before recognition, after recognition and under the writer lock before publication. Later corrections also make a completed result project as stale and ineligible for review. Artifacts may remain on disk after cancellation/invalidation but are not eligible queue results. The inventory is never mutated by this worker.

Provider exceptions are recorded only as fixed error codes; keys and exception messages are not journaled. Existing provider failures remain explicit unavailable stage results with no automatic retry. The selected attempt provider is saved before execution. Replay responses are labeled offline replay and remain unverified.

## Restart and operations

A crashed running job remains running and blocks the worker. Stop/verify the old worker is gone, inspect the job and explicitly use `--interrupt JOB_ID`. This records provider outcome unknown and never requeues that job. A further provider call requires an explicitly enrolled new job ID with newly reviewed current pins. Interrupting/cancelling cannot undo a provider request already submitted; a late old worker cannot publish into a revoked attempt. This prototype has no process supervisor, worker lease, automatic result recovery or retention deletion.

```powershell
.\.venv\Scripts\python.exe -B -m scripts.smoke_recognition_jobs --output runs/my-reading-queue-smoke
.\.venv\Scripts\python.exe -B -m library_claim.recognition_jobs --store runs/my-reading-queue-smoke/setup/store --list
.\.venv\Scripts\python.exe -B -m library_claim.recognition_jobs --store PATH --enqueue job.json
.\.venv\Scripts\python.exe -B -m library_claim.recognition_jobs --store PATH --run-one --response response.json
```

For an explicit live invocation, replace `--response` with `--gemini --free-tier-confirmed --key-file PATH`. The existing allowed model list and default apply; no paid fallback. Keys stay in the local environment/file. Only one job is processed per invocation. Empty queue returns JSON null. `--cancel JOB_ID` revokes queued/running work; `--interrupt JOB_ID` closes only a running uncertain attempt. Listing is read-only and does not start jobs. Outputs are under `STORE/recognition/JOB_ID/`; enqueue inputs are not paths and cannot choose an arbitrary output location.

## Verification

15 new Python tests cover restart/idempotency, changed job content, stale enrollment, corrections before/during/after recognition, reference changes, unrelated guidance turns, cancellation during recognition, interruption blocking/recovery without retry, busy worker, capacity bounds, artifact corruption, redacted worker failures and provider-unavailable exports. The initial test fixture incorrectly pinned reference revision zero after a reference skip; it now pins the actual saved revision. SQLite connections are explicitly closed.

Actual synthetic CLI smoke passed at `runs/m06c2a-review`: six independent queue CLI processes, exact enqueue replay, partial reading export, identical result after restart, no automatic rerun, unchanged inventory after reading, then result invalidation after an explicit ownership correction. Setup reused the controlled M06a target HTTP/restart fixture; the reference app was not run. Provider requests: zero. Summary and exact CLI history are saved beside the setup store and reading report.

Full regression: 337 Python tests and 27 Node tests passed. The existing Starlette/HTTPX deprecation warning remains. No real provider call, new browser feature, real camera/reading accuracy, three-minute voice or geometric calibration is claimed by this part. The live worker path reuses the previously checked reader and has a mocked unavailable-provider test; live queue invocation remains unmeasured.

Next proposed part: M06c2b explicit queue HTTP/browser review/enrollment, with bounded control inputs and no automatic recognition acceptance. Detection and automatic same-pass camera scheduling need their own subsequent boundaries.

**Awaiting user review.**
