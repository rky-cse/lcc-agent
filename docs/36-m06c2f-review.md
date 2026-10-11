# M06c2f — Reviewed unresolved-observation resolution

Authorized by the user's “next” after M06c2e. This part resolves one already-registered unresolved physical observation at a time through the existing TrackStore resolve command. A reviewer explicitly chooses a new physical copy or an existing copy on the same shelf, with reviewer, overall reason and physical-evidence provenance. Leaving the page without applying preserves ambiguity. New-copy resolution retains the existing included/owned=true default; same-copy resolution preserves ownership and bibliography. No model, title matching, calibration or valuation decides association.

## Architecture and evidence

`ResolutionReviewer` reuses GuidanceStore, immutable FrameStore originals and the TrackStore transaction/receipt machinery. It reads the observation's archived import from the ledger rather than requiring a still-eligible queue job. Registration intentionally makes old detection jobs stale; that must not prevent later physical review. The archived structured detector response is recomputed against its saved request and verified original. Its computed proposals must match the archived result and the selected observation's frame SHA, shelf, polygon and orientation. Ledger command hashes are checked before receipts are shown. Detection export files and queue files need not stay present for this operation, but saved originals and the existing ledger archive remain required.

A typed ResolutionReview pins session, current inventory and reference revisions. It accepts exactly one existing Decision, action new or same, and nonblank reviewer/reason/provenance. A deterministic command ID derived from session/review ID stores review metadata and the selected decision in the existing ledger event. No additional outbox or receipt database is introduced.

For a new operation, a guard checks bound capture/reference revision and selected evidence under TrackStore's BEGIN IMMEDIATE writer lock. TrackStore then enforces the inventory revision, unresolved target, same-shelf association and no two detections from one frame merged into one physical book. All changes and the event commit together. Invalid targets or races roll back. Exact command retries occur before stale revision guards, recover a committed event after a lost HTTP acknowledgment, and never add a revision. Changed content with the same review ID fails. Historical event revision and current inventory are distinct in the response; later reference changes do not invalidate a verified exact receipt replay.

The imported archive remains the existing ledger format. This module verifies recomputed geometry and recorded command hashes; it does not introduce an externally signed or tamper-proof database. Reviewer names remain local declarations without authentication. Same-copy correctness still depends on explicit human physical comparison.

## HTTP and browser

GET `/api/guidance/{session}/resolution/{observation}` is read-only and returns the selected observation, public saved-frame metadata, current pins, same-shelf physical targets with saved evidence, historical resolution events and can_resolve. Already assigned observations remain readable with can_resolve=false. Unknown/cross-session observations return 404; guidance must have a bound capture, including closed captures.

POST on the same path accepts ResolutionReview with URL/body target equality. This single-observation route permits a bounded 16 KiB body and retains the ten-second control timeout, exact Host/Origin checks, no-store and CSP. Other control limits are unchanged. Invalid schema/URL target is 422, body size is 413, association/staleness/integrity conflict is 409 and storage failure is 503. Ledger work runs outside the async audio/HTTP loop.

Unresolved observation rows on `/recognition` link to `/resolution?session=...&observation=...`. The page reuses the numbered saved-original overlay and physical-decision renderer, with only blank/new/same choices. It shows target IDs, ownership, observations and links to original frames/geometry. Apply reviewed resolution is the sole mutation control. Reviewer and physical reasons are required. Unconfirmed unchanged retries preserve the exact review ID/payload; editing an unconfirmed payload requires refreshing and inspecting the ledger. Refresh clears unsaved choices. Epoch guards prevent old responses from updating a newer view. Successful application disables Apply and shows the recorded action/reason and historical revision. Text uses textContent; evidence URLs are encoded. Narrow-screen fields and long evidence text wrap inside the page.

## Verification

Full regression: **382 Python tests and 49 Node tests passed**. Ten new Python checks cover read-only inspection, new resolution leaving a second observation unresolved, same-copy counts/ownership, exact retry/restart after reference change, commit-before-ack recovery, stale inventory/reference, an injected reference race under the writer lock, unknown target/same-frame rollback, blank/unresolved/multiple-decision rejection, archived geometry/event corruption and HTTP target/origin/size/history boundaries. Four new Node checks cover current pins, cloned decisions, preserving ambiguity without submission, explicit same-shelf targets/provenance and literal historical receipts. Existing registration tests also passed after shared renderer reuse. JavaScript syntax and Git whitespace checks passed. Existing Starlette/HTTPX deprecation warning remains; no dependency installation was required.

Actual synthetic HTTP/process/restart smoke: `runs/m06c2f-review`. It builds a registration fixture, reads its unresolved observation without mutation, explicitly resolves it as a new copy, verifies four assigned tracks and zero unresolved observations at revision 3, and verifies exact receipt replay after restarting the server. Changed same-ID content is rejected and original hashes remain unchanged. Artifacts: review-request.json, receipt.json, smoke-summary.json, server.log and nested setup evidence. Provider requests: zero.

Actual browser smoke: isolated `runs/m06c2f-browser`. A separate saved-frame synthetic import explicitly left one observation unresolved at revision 4. The browser displayed its saved original/polygon, accepted an explicit new-copy choice with physical reason/reviewer, committed revision 5 and displayed the recorded receipt. The receipt survived server restart and page reload. Artifacts: observation.json, receipt.json, smoke-summary.json and resolution-applied.png. Test servers were stopped afterward.

## Operations and next boundary

```powershell
.\.local\reference-env\Scripts\python.exe -B -m scripts.smoke_resolution --output runs/my-resolution-smoke
.\.local\reference-env\Scripts\python.exe -B -m library_claim.server --store runs/my-resolution-smoke/setup/setup/store --port 4191 --synthetic
```

The smoke store has already resolved its selected observation; its receipt can still be reviewed through its saved observation ID. New unresolved evidence is required for another decision. This module performs no provider calls and does not retest the user-tested reference app. Real bookshelf/revisit precision, camera/microphone/Android acceptance, metric geometry and three-minute end-to-end acceptance remain unmeasured.

Proposed next small boundary: M06c2g bounded dispatch for one explicitly selected queued recognition job, with free-tier/provider activation and worker lifecycle limits settled before dispatch. Automatic capture scheduling and correspondence acquisition remain later review boundaries. No next-part implementation is authorized by this record.

**Awaiting user review.**
