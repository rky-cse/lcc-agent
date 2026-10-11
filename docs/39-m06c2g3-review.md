# M06c2g3 — Explicit browser recognition dispatch and status

Authorized by the user's “next” after M06c2g2. This part adds Run controls for saved reading/detection jobs in the existing recognition review page. Each click selects one exact saved job. Opening a session, refreshing, reopening after restart and rendering a result never start a worker. Queue enrollment, evidence review and inventory acceptance retain their separate actions.

## Design and contracts

The browser loads the queue and dispatcher status together with bounded requests and the existing page-generation guards. Queue failure clears evidence. Dispatcher failure or a response for another session leaves evidence visible but disables Run. Dispatch is available only for queued jobs in the displayed session, an enabled supported server mode/kind, and an idle worker. Closing, unknown, active or uncertain status disables Run. This is an advisory display; the existing server/queue transaction remains the authoritative concurrency guard if status changes after loading.

GET `/api/guidance/{session}/recognition/dispatch` now includes the requested `session_id`, configured `supported_kinds` and a global `worker_busy` flag computed from running or active claims. Other-session job IDs and outcomes remain hidden. The global flag conveys contention without exposing another session's evidence. GET performs no mutation or dispatch. POST still accepts only `{job_id}`: the browser copies the displayed saved token, never resubmits revisions, frame inputs, keys, models, paths or replay payloads.

`recognition.mjs` owns eligibility, exact-token request construction, literal status text and Run rendering. `recognition_page.mjs` owns explicit requests, abortable loads/mutations and session-generation checks, including a second check after the post-dispatch refresh. A session switch, refresh or page exit aborts outstanding browser requests and revokes late UI updates. An aborted request cannot prove that an accepted server task stopped; the user must refresh saved status. There is no polling scheduler or automatic retry.

Clicking Run disables the displayed Run controls immediately. HTTP acceptance is shown separately from completion. Refresh reads durable completion and exposes existing crop/result/registration links. Terminal jobs have no Run button. Cancel retains the existing publication-revocation behavior; active or active-cancelled jobs display worker-slot and stopped-worker recovery guidance. The UI never executes CLI interruption or silently clears an uncertain worker.

Refresh is explicitly labelled “Refresh evidence and job status”; its adjacent notice explains that it clears an unsaved shelf selection. No draft region is automatically submitted. Replay and Gemini modes are identified before Run, including that Gemini may make a provider request. Live activation, free-tier assertion, credentials and owned child lifecycle remain the M06c2g2 server contract. Recognition output remains an unverified proposal, with no automatic physical registration, accepted identity, metric geometry or valuation.

## Verification

Six added Node checks cover exact saved-token requests, session/mode/kind/disabled/busy guards, terminal and active-cancelled jobs, explicit click-only dispatch, recovery text and replay/provider/acceptance summaries. One added Python check covers session-scoped dispatcher status, supported replay kinds, cross-session global uncertainty and repeated read-only GETs. Existing late-session-response tests and the prior worker/lifecycle tests remain applicable.

Full regression: **407 Python tests and 55 Node tests passed**. JavaScript syntax and Git whitespace checks passed. Existing Starlette/HTTPX deprecation and isolated async-fixture slow-task diagnostics remain.

The actual HTTP/child-process smoke was rerun in `runs/m06c2g3-review`: selected reading and detection completed using typed synthetic replay, terminal repeats did not retry, default-disabled restart was enforced, inventory/originals stayed unchanged, worker slots were released and temporary replay files were removed. Provider requests: **zero**.

The laptop localhost browser smoke used a copied synthetic store in `runs/m06c2g3-browser`. Disabled dispatch showed disabled Run controls. After explicit server activation, UI clicks ran `browser-detection` and `first-reading` only. Manual refresh showed completed/success detection and completed/partial reading with artifact links. `untouched-reading` stayed queued. Reopening after server restart retained identical saved jobs, inventory revision 1 and reference revision 2. The completed recognition section was visually inspected. Browser artifacts: `before.json`, `after-dispatch.json`, `after-restart.json`, `smoke-summary.json` and `dispatch-completed.png`. Temporary test servers were stopped after verification.

This smoke validates synthetic browser dispatch and persistence, not real shelf accuracy, actual camera/Android behavior, microphone interruption, live Gemini quota/latency or three-minute acceptance. No live provider call, credential read, reference-app retest or dependency installation was needed. Existing CLI, server dispatcher, queue publication and evidence links were reused; no reference transport was copied or replaced in this part.

## Operation and next boundary

```powershell
.\.local\reference-env\Scripts\python.exe -B -m library_claim.server --store runs/m06c2g3-browser/store --port 4193 --synthetic --recognition-replay runs/m06c2g3-browser/replay.json
```

Open `/recognition?session=eeeeeeeeeeeeeeeeeeeeeeeeeeeeeeee`, inspect status and select one queued job's Run button. Refresh to inspect its saved result. The retained smoke store has one untouched queued reading. For real evidence, use the previously documented explicit Gemini activation and local credentials. After an abrupt worker/server stop, verify the old worker exited before using the existing explicit CLI recovery.

Proposed next small part: **M06c2h read-only recognition progress for the guided conversation**. Expose saved pending/completed/stale/uncertain counts and evidence readiness to the guide without starting jobs or accepting identities. Automatic capture/preview scheduling, association acquisition and stage acceptance remain later review boundaries. This proposal is not implemented here.

User expanded authorization to the whole M06 group before this review stop. M06c2h and the remaining integration were subsequently completed; see [group review](40-m06-group-review.md).
