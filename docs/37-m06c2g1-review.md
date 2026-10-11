# M06c2g1 — Exact-job recognition dispatch and retained worker slot

Authorized by the user's “next” after M06c2f. M06c2g is split to keep one small implementation/review boundary: this first part dispatches one explicitly selected saved job from the CLI. HTTP/browser dispatch controls remain a separate next part. Existing reading/detection contracts, provider adapters and reviewed inventory operations are reused.

## Dispatch contract and architecture

RecognitionQueue.run_job(job_id, response=... or key=..., model=...) infers reading/detection kind from immutable queued inputs and delegates to the existing atomic worker claim/publication logic with that exact ID. It never substitutes the oldest job or another kind. Unknown IDs fail before execution. A conflicting explicit kind fails. A stale queued selection marks only that job stale without a provider request; unrelated queued jobs remain untouched.

The CLI accepts `--run-one --job-id ID`. Kind is inferred; optional `--kind` must agree. Without --job-id, the established one-job FIFO-by-kind behavior remains compatible, with reading as the omitted-kind default. --job-id on another CLI action is rejected. Every invocation still requires exactly one replay response or explicit Gemini mode; Gemini requires the existing --free-tier-confirmed assertion, local key/environment and allowlisted model. Keys and replay responses are not added to queued input records. No provider configuration is inferred from chat or queued data.

Selected completed, cancelled, failed, interrupted or stale records return their stored/projected status without another attempt. Completed evidence is hash-verified; later revision changes project it stale without rerunning it. Repeat selection is a status/evidence lookup for that attempted job; a newly supplied response or model does not replace a terminal result. A new attempt would require an explicitly enrolled new job ID with current evidence pins. Missing artifacts or hash corruption remain concrete failures. A selected running attempt requires explicit stopped-worker recovery. Job-ID uniqueness continues across kinds and sessions.

The existing transaction checks reference/inventory/original geometry before claim, after recognition and under the publication writer lock. Provider work occurs outside SQLite transactions and does not change physical inventory, accept transcription, register detections, match titles or schedule another job. Worker errors retain fixed public codes and no exception text. Actual provider transport remains the existing single bounded image request, 45-second socket timeout, no redirects, retries or paid fallback; this is not a measured end-to-end latency guarantee.

## Cancellation and worker lifecycle

A dispatch claim now records worker_active=true. The global one-worker check includes both status=running and retained worker_active records. Cancellation revokes publication but retains the active slot until the execution exits. The final publication transaction clears the marker even when the job was cancelled and saves no cancelled result as eligible evidence. Active cancelled records also count against the bounded pending limit. The existing 200 retained/20 pending limits remain.

This closes a concrete gap: previously cancellation changed status away from running before the provider returned, allowing another invocation to overlap it. Both exact selection and legacy FIFO workers now respect the retained slot. Legacy running records without the new field still block; cancelling them adds the activity marker before changing their status.

After process interruption, the durable running/active-cancelled marker blocks another worker across restarts. Existing `--interrupt ID` can close either uncertain state as interrupted with provider_outcome_unknown and worker_active=false. The operator must first stop/confirm exit of the old worker; an explicit recovery command is an operator assertion, not process-liveness detection. It never requeues the uncertain job. There is no heartbeat lease, automatic timeout reset or automatic provider retry. A normal returning worker releases its slot, leaving any cancelled evidence unpublished. Markers are per store; independent stores do not share a provider-quota scheduler.

## Verification

Full regression: **393 Python tests and 49 Node tests passed**. The final targeted rerun of all 11 new dispatch checks also passed after covering legacy cancellation markers and blank selected IDs. Git whitespace checks passed. Existing Starlette/HTTPX deprecation warning remains. No dependency installation was required.

Eleven new Python checks cover non-FIFO exact reading selection without inventory mutation, terminal lookup after restart without provider invocation, unknown/mismatched selection without fallback, cancelled/failed/stale selections without retries, completed stale/hash-integrity gates, a concurrent active cancellation blocking both selected and FIFO workers, uncertain legacy running cancellation/restart and explicit stopped-worker recovery, CLI kind/free-tier/action/blank-ID validation, and inferred detection selection with one mocked provider invocation across repeat requests. The threaded cancellation check uses a controlled entered/release barrier; it does not rely on sleeps or live-network timing. Existing recognition/detection tests also pass.

Actual synthetic independent-process smoke: `runs/m06c2g1-review`. Four jobs were explicitly enrolled. The last detection job was selected before the first detection; then the last reading job was selected before the first reading. Each repeat CLI invocation returned identical stored evidence in a fresh process. The first reading was cancelled and selecting it returned cancelled without claiming the still-queued first detection. Fourteen independent CLI processes were used. Physical inventory and original evidence remained unchanged; normal worker slots were released. Artifacts: job inputs, replay responses, cli-history.json, smoke-summary.json and nested setup/store originals and published reports. Provider requests: zero. Guidance setup's temporary target server was stopped by its smoke cleanup.

No reference-app test, key read, dependency installation or real Gemini recognition call was performed in this part. Existing free-tier eligibility is an explicit runtime assertion; real quota/latency and recognition accuracy remain unmeasured. Real bookshelf, camera/Android/microphone, metric geometry and three-minute acceptance gates remain open.

## Operation

```powershell
.\.local\reference-env\Scripts\python.exe -B -m scripts.smoke_selected_dispatch --output runs/my-selected-dispatch
.\.local\reference-env\Scripts\python.exe -B -m library_claim.recognition_jobs --store runs/my-selected-dispatch/setup/store --list
.\.local\reference-env\Scripts\python.exe -B -m library_claim.recognition_jobs --store runs/my-selected-dispatch/setup/store --run-one --job-id selected-detection --response runs/my-selected-dispatch/detection-response.json
```

The example's selected-detection is already completed: selecting it again reads its saved result, with no execution. For live work, explicitly enroll a fresh job against current revisions, then select its exact ID with --gemini --free-tier-confirmed and a local --key-file path, or a locally configured key environment variable. Never put credentials in chat or queued JSON. Do not mark an active attempt interrupted until its old process has exited. Inspect --list and its worker_active field before dispatch/recovery.

Proposed next part: M06c2g2 opt-in server dispatch of one explicitly selected job, with configured local free-tier credentials and an owned worker lifetime. Browser dispatch controls can then be reviewed separately. No automatic capture scheduling or next-part implementation is authorized by this record.

**Awaiting user review.**
