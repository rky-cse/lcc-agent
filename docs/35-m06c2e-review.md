# M06c2e — Reviewed queued-detection registration

Authorized by “next” after M06c2d. This part lets a reviewer register completed detection candidates through the existing audited TrackStore import. Every candidate needs an explicit new physical copy, same existing copy or unresolved decision with provenance. No title-based deduplication, automatic registration, identity acceptance, valuation or camera scheduling is added.

## Architecture and atomicity

RegistrationReviewer opens a hash-verified published detection bundle from the queue and reuses the existing `load_bundle` validator. A review pins session/job IDs, inventory/reference revisions, a bounded review ID, reviewer/reason and up to 256 existing typed Decision entries. Review and decision provenance must be nonblank. The service builds a deterministic registration command ID from session/review ID and records the full review metadata as command provenance. Decisions and detector SHA remain in the existing TrackingCommand.

TrackStore.apply accepts an optional dependency guard, evaluated under its existing BEGIN IMMEDIATE writer transaction after exact historical command replay and before a new import. The registration guard verifies completed eligible success/partial detection and exact inventory/reference pins under that same writer lock. Reference or inventory changes between an earlier HTTP read and commit reject the import. No decision is automatically rebased.

All physical observation/track creation, unresolved decisions, source bundle archive and ledger event commit together through the existing import. Same-copy review requires an existing physical track on the same shelf. Two detections in one frame cannot merge into a single book. Existing frame/shelf import and command-ID limits still apply. New tracks retain the existing ownership defaults and unknown bibliography; same-copy links preserve the existing track/ownership. Identity and pricing are not inferred by registration.

The existing ledger event is the durable receipt, so this service needs no separate dispatch outbox. Only a matching command hash/event supports `applied=true`. Exact retries recover after a commit lost its HTTP acknowledgment and do not add revisions, even though that import made the queue result stale. Changed content with the same review ID fails. Receipt revision is historical; the response separately supplies verified current inventory. Subsequent original/bundle corruption is a concrete integrity failure, not a silently accepted replay. New reviews against stale/unavailable/cancelled/unpublished detections are rejected.

## Browser review

Detection entries in `/recognition` link to `/registration?session=...&job=...`. The review page shows the unchanged original with separately drawn numbered polygons, detector review warnings, current/detection/reference revisions and a form for every validated candidate. Decision selects start blank. Same-copy choices list physical track IDs on that shelf, ownership, observation count and links to saved originals/geometry; titles are not used to choose a target. Ambiguity can stay unresolved.

Apply reviewed registration is the only mutation control. It requires every decision/reason plus reviewer and overall reason. A failed/unconfirmed submission retains its exact review ID/payload for an unchanged retry. Editing an unconfirmed request requires refresh and saved-ledger inspection. Refresh/reload clears unsaved decisions; epoch guards and aborted loads prevent old responses from rendering into a newer view. Loading, refreshing and viewing receipts do not apply decisions. After registration, Apply is disabled and the historical receipt displays actual recorded actions, target IDs and literal reasons. Rendered text uses textContent and evidence URLs are encoded.

This local prototype does not authenticate the entered reviewer name. Same-copy judgment is explicit human review, not an automatic correspondence algorithm or a measured duplicate-detection accuracy claim. Existing ledger limits bound targets; the page currently lists all same-shelf targets rather than adding another search/index service.

## HTTP contracts and operations

GET `/api/guidance/{session}/registration/{job}` returns verified bundle proposals/candidates, original public metadata, same-shelf physical targets, current inventory revision and hash-verified historical import events. It provides `can_register=false` for stale/already-imported/unavailable detection. A queued/unpublished job has no reviewable bundle and returns 409. Different-session jobs are 404.

POST on the same path accepts RegistrationReview; session/job must match URL. Existing exact Host/Origin checks apply. Registration alone permits a bounded 600 KiB control body to accommodate up to 256 decisions with provenance; all other control routes retain 4 KiB limits. Body timeout stays ten seconds. Invalid schema/target is 422, oversized body 413, stale/invalid/integrity conflicts 409 and storage failure 503. TrackStore and registration execute off the async HTTP/audio loop. No provider key or call is needed.

```powershell
.\.venv\Scripts\python.exe -B -m scripts.smoke_registration --output runs/my-registration-smoke
.\.venv\Scripts\python.exe -B -m library_claim.server --store runs/my-registration-smoke/setup/store --port 4190 --synthetic
```

Use the queue link to inspect the published detection. The smoke's registration is already committed; its historical receipt remains reviewable. A newly published eligible job is needed to make new decisions. `unresolved` observations can be resolved later through the existing reviewed resolve contract; this page adds import review only.

## Verification and artifacts

13 new Python checks cover read-only review, explicit new/unresolved import, exact retry/restart, commit-before-ack recovery, missing/duplicate decisions and invalid-target rollback, same-copy revisit counts/ownership, forbidden same-frame merge, reference race inside the atomic guard, stale inventory, wrong pins/blank provenance, bundle corruption, receipt-event tampering, HTTP session/control bounds and unavailable detection rejection. Five new Node checks cover immutable pinned decisions, missing/duplicate decisions, same-copy target guards, stale/blank submission rejection and literal historical receipt actions/reasons.

Full regression: 372 Python tests and 45 Node tests passed. Existing Starlette/HTTPX deprecation warning remains. JavaScript syntax and Git whitespace checks passed. No dependency installation or reference retest was needed; reused components are queue evidence verification, M04a bundle validation and M04b1 transactional tracking.

Actual synthetic target HTTP/CLI/restart smoke passed in `runs/m06c2e-review`. It completed a two-candidate replay detection, read the review without mutation, explicitly registered one new copy and kept one unresolved, then retried before/after restart without adding a revision. Final canonical smoke inventory: revision 2, three assigned physical tracks, one unresolved observation. The original hash stayed unchanged. Provider requests: zero. Saved artifacts: review-request.json, receipt.json, smoke-summary.json, replay response, server log and setup original/store.

Actual in-app browser smoke used an isolated copy under `runs/m06c2e-browser`. It displayed the original/numbered candidate, explicitly selected Keep unresolved with a reason and reviewer, then applied. Ledger revision advanced from 2 to 3, while assigned tracks stayed three; the additional observation stayed unresolved. The page disabled further Apply and displayed the verified historical event plus actual unresolved decision/reason. The receipt persisted after server restart and page reload. Screenshot: registration-applied.png; saved event data: receipt.json. Test servers were stopped afterward.

Real physical revisit/deduplication precision, actual bookshelf capture, Android/microphone/three-minute acceptance and live recognition queue calls remain unmeasured. No shelf/room metric scale is inferred by registration. Proposed next small part: M06c2f explicit review and resolution of unresolved physical observations through the existing TrackStore resolve operation. Automatic correspondence acquisition and same-pass scheduling remain later boundaries.

**Awaiting user review.**
