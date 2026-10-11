# M06c1 — Reviewed correction execution and acknowledgment

Implemented for the latest “next”. M06c is split into M06c1 correction execution and M06c2 recognition orchestration so each stays independently reviewable. This part applies explicitly reviewed include/exclude or clear-identity intents through the existing audited stores and acknowledges verified outcomes. It adds no recognition worker, provider call, metric calculation or price lookup.

## Claimant flow

M06a still records a claimant intent and, when ambiguous, asks for the exact physical track. M06b still proposes spoken answers for confirmation; saving the answer does not execute the book correction. The `/voice` page now shows a **Book corrections** panel with literal statement, operation, physical ID, shelf/position, current ownership and original-frame link. **Apply reviewed correction** is the explicit execution action. It works without a live voice connection. **Dismiss book correction** resolves an unwanted or unsupported intent without changing inventory.

A stale physical revision disables Apply. The app never changes the proposed target/revision silently; the claimant must submit a new explicit intent against current state. Signed/first-edition assertions have no executable command and remain separate identity/appraisal review. Missing targets cannot be applied. Choosing by title or merging duplicate copies remains prohibited. Corrections can be reviewed after capture closes; this does not reopen capture or request a separate book scan.

The local browser records the reviewer label `Local browser reviewer` and retains the claimant's literal statement as the execution reason. This is an audit label, not authentication of a person's identity. The API/CLI can provide explicit reviewer/reason strings. The model cannot call the execution endpoint through its tool set; model tools still only read state or propose claimant answers.

## Contracts and authority

`CorrectionExecution` contains `request_id`, `session_id`, `intent_id`, `expected_guidance_revision`, `expected_inventory_revision`, `decision` (`apply` or `dismiss`), `reviewer` and `reason`. IDs/text are bounded, codes/session are validated, blank review text and extra fields are rejected. The request pins both independently changing revisions. Apply recomputes the existing proposed command from the stored intent, checks its exact payload and target, and requires the proposed inventory revision to remain current.

`CorrectionExecutor` reuses `TrackingCommand`/`TrackStore.apply` for ownership and `IdentityCommand`/`IdentityStore.apply` for clear identity. It introduces no alternative mutation algorithm. Ownership affects the selected physical copy only, preserving title/identity/observations and other copies. Identity clear preserves the physical track, ownership, originals and archived work evidence while removing the current bibliography/edition projection and retaining the existing dependency-invalidating event. It never authenticates an edition, signature or first printing and never generates a price.

Successful ownership receipts mark ownership-dependent totals/jobs for later consumers; identity clearing reuses the underlying event's edition/replacement/used/totals invalidations. No consumer/job is scheduled in this part. Recognition and valuation orchestration must honor these revisions and invalidations later.

## Recoverable dispatch protocol

1. Validate the explicit review against current guidance/inventory and immutable originals. Commit a `prepared` receipt and reserve that intent as `dispatching` in one SQLite transaction. Guidance revision advances; inventory is still unchanged.
2. Dispatch the frozen command through its existing store. That store atomically commits the physical mutation/audit event and already supports exact command retry. A dismissal skips this step.
3. Read and verify the physical event's command ID, payload, fingerprint and event revision. Commit the final receipt and guidance acknowledgment together. Guidance revision advances again. Only then does the intent become `applied`, with `applied=true`. A dismissal becomes `dismissed`/false.

There are two durable transactions around the separately authoritative inventory transaction, not a fictitious single atomic transaction across all steps. Interruption before dispatch leaves a prepared request with no mutation. Interruption after the inventory commit may leave changed inventory with an unfinished acknowledgment. **Resume prepared execution** replays the exact saved request, detects/idempotently retries the command and acknowledges its recorded event without adding another inventory revision. Recovery is explicit; GET/restart does not execute prepared work automatically.

The reservation prevents a different request taking over the same intent. Existing receipt lookup occurs before stale-revision checks for exact retry. Reusing a request ID with changed content is rejected. During acknowledgment, unrelated guidance turns are preserved rather than overwritten. Concurrent inventory changes before dispatch can reject the old command; a terminal `review_required` receipt carries a failed StageResult and requires a new explicit review. Storage failures stay prepared because a mutation might already have committed. No failure is reported as a successful correction.

The receipt records request fingerprint, frozen command/hash, original frame refs, preparation/completion times, before/observed-after inventory revisions, actual ledger-event revision, status, `applied`, typed stage and dependency invalidations. Terminal retry returns the original receipt with current guidance/inventory. An applied receipt is historical: a later reviewed include/exclude can change current ownership. The UI distinguishes the applied revision from current ownership; the voice policy reads `correction_targets` for current state.

Guidance command turns remain in `events`; execution preparation/outcome stages are in `execution_events`. Both advance guidance revision. While an execution is unresolved, `correction_execution_pending=true`; `inventory_mutated` is unknown (`null`) unless an earlier acknowledged mutation is already known. `metric_ready` stays false. The acknowledgment stores its complete receipt on the intent, allowing browser restart to recover the exact request. Bounds are 200 execution requests per session, alongside M06a's 100-intent bound; no production compaction/retention policy is added.

## API, CLI and export

POST `/api/guidance/{id}/corrections` accepts the execution contract; body and URL session must match. GET on the same path returns verified receipt history without mutations. Existing exact Host/Origin, 4 KiB control body, timeout and typed error boundaries apply. Invalid body/target mismatch is 422, stale/missing/unsupported intent is 409 and storage failure is 503. A dispatch rejected after preparation returns its explicit failed receipt for review. SQLite/store work runs off the async HTTP/audio loop. No new dependency or key is needed.

```powershell
.\.venv\Scripts\python.exe -B scripts/smoke_corrections.py --output runs/my-correction-smoke
.\.venv\Scripts\python.exe -B -m library_claim.correction_execution --store runs/my-correction-smoke/setup/store --session-id eeeeeeeeeeeeeeeeeeeeeeeeeeeeeeee --output runs/my-correction-export
```

The CLI optionally accepts `--request path.json` to execute one explicit review before export. Choose fresh output directories. It exports receipt/guidance/current-inventory JSON, a summary HTML report and the reused portable original/identity-evidence report under `evidence/`. A revision check rejects concurrent changes during review export. This is a review snapshot, not M10's finalization barrier or a complete insurance packet. An execution already committed is not rolled back if export fails; exact retry and fresh export recover it.

## Verification and artifacts

22 new Python tests passed; full Python regression passed 322 tests. Six new Node checks plus prior browser checks passed all 27 Node tests. They cover the selected copy, exact retry/restart, changed request content, stale guidance/inventory, unresolved/appraisal assertions, dismissal, closed capture, interruption before dispatch and after commit, reservation ownership, concurrent unrelated turns, competing inventory update, verified event acknowledgment, later reverse ownership, clearing an accepted work, original/proposal tampering, missing ledger proof, HTTP bounds and portable escaped export. The existing Starlette/HTTPX deprecation warning remains.

The first targeted run exposed an invalid nullable `StageError.field` in the rejection branch; it now uses the required string field and the inventory-race test passes. The initial smoke launcher also lacked repository import resolution for the reused helper; it now invokes that helper as a Python module. These failures were corrected before final regression.

Actual synthetic target HTTP/restart/CLI smoke passed in `runs/m06c1-review-final`. It used two separate physical tracks from the earlier controlled guidance fixture, excluded exactly the reviewed borrowed copy, replayed after restart without new revision, included it through a separate process that exited after the inventory commit but before acknowledgment, then recovered the exact request without double application. Signed assertion execution and stale target execution were rejected; dismissal did not authenticate a signature or mutate inventory. Identity clear preserved the physical count and ownership. Final inventory revision: 5; assigned copies: 2; owned copies: 1; original hash preserved; provider requests: zero; metric readiness: false.

The HTTP smoke's identity clear starts from unknown identity; the separate unit case first accepts a supported synthetic work, then verifies its title/identity is removed while physical evidence/ownership and archived artifacts remain. Neither is an actual shelf-reading claim.

Artifacts: `runs/m06c1-review-final/smoke-summary.json`, `http-dialogue.json`, the interrupted include request, server log, full setup originals/store and `portable-review/report.html`. The first `review/` export is also retained; `portable-review/` adds the original-evidence bundle. Actual in-app browser smoke used an isolated copy of the store in `runs/m06c1-browser`, displayed stale Apply disabled, then applied an explicit include at inventory revision 6 and displayed current ownership plus historical receipt revisions. Screenshot: `correction-applied.png`.

Real voice target selection, microphone/three-minute M06b acceptance, actual camera/books, calibrated geometry and physical accuracy remain unverified. The camera-intrinsics setup preference remains unanswered. The next separately authorized part is M06c2's bounded recognition scheduling; automatic landmarks, capture preview automation and later recognition acceptance must be split further if needed. No work on those parts is included here.
