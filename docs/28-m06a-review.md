# M06a — Durable guided session

Implemented for the latest “next”: a typed conversation backend that asks for country/currency first, collects reference-object declarations, requests same-sweep evidence and prepares targeted correction commands. This is the state and question layer for later voice integration. No microphone, speech recognition, playback, language-model interpretation or browser controls were added.

## Scope and state

`library_claim/guidance.py` persists sessions and audited turns in the existing FrameStore SQLite database. A session starts without a locale or camera. Its phases are `awaiting_locale` → `awaiting_reference` → `ready_to_capture` → `capture_bound`. Explicitly unknown dimensions keep the reference question open; an explicit skip permits capture with unknown scale. A measured reference declaration can permit capture, but `metric_ready` always remains false until a separate geometry path validates it.

Country and currency are supplied by the claimant, with no defaults or timezone inference. Codes receive the existing Sweep format validation; this module does not validate a country/currency registry or interpret spoken place names. The reference question asks for the actual object, independently measured width/height in centimetres, tolerances and measurement provenance. All four numeric inputs must be known together or unknown together. Dimensions must be positive and finite; each tolerance must be smaller than its dimension. `dimensions_verified` records a declaration, not successful geometric calibration. No card, paper or book size is assumed.

Capture begins through the existing M02 endpoint using the returned `capture_start_proposal`. An agent `bind_capture` turn then verifies the same session ID, locale and active capture. This backend never opens the camera. It rejects adopting an existing capture as a new guidance session and rejects changing locale after capture creation.

## Typed turns and guards

Every `GuidanceCommand` contains `command_id`, `session_id`, `expected_revision`, `speaker` and a discriminated `payload.action`. Claimant actions are `locale`, `reference`, `skip_reference`, `binding`, `decline_evidence`, `correction` and `choose_target`. Agent actions are `bind_capture`, `request_evidence` and `evidence_received`. Extra fields, blank declarations, invalid role/action combinations and stale guidance revisions are rejected.

Guidance revision, physical-inventory revision and reference revision are separate. Evidence requests and corrections pin the inventory revision; reference changes increment their own revision and record metric dependency invalidations. These invalidation markers must be consumed by later job scheduling; this part does not execute or modify measurement jobs. Exact command retries preserve the revision; reusing a command ID with changed content is rejected. Accepted turns carry a partial `guided_session_turn` StageResult, command hash and dependency markers. Bounds are 1,000 turns, 100 evidence requests and 100 correction intents per session.

Evidence request reasons are unreadable spine, invisible ISBN, unknown binding, glare and invisible reference. Questions keep books in place during the continuous shelf pass. The ISBN prompt explicitly asks only if it is visible without moving a book; otherwise the edition stays unknown. Reference evidence asks for the same plane as the spines. Binding answers distinguish hardcover, paperback, other print and unknown and retain the literal claimant statement.

A received frame must be a verified original in the same sweep. Receipt means `received_analysis_pending`, not successful OCR, identification or calibration. Declining evidence leaves it unknown. New evidence requests are rejected after capture closes; unfinished analysis/review remains visible. Binding answers are assertions and cannot independently accept an edition.

## Corrections remain reviewable proposals

Ownership include/exclude and identity clear intents prepare the existing TrackingCommand or IdentityCommand. They do not apply it. A missing target produces `awaiting_target` and a question asking for the physical track using shelf position and original evidence. Duplicate titles are never used to select a copy. The projection offers the first 20 physical choices and reports the total/completeness; the existing paginated inventory endpoint supplies remaining rows.

An explicit, current target produces `pending_review`, `applied=false` and a revision-guarded proposed command. Signed/first-edition assertions also remain pending and require separate review; they do not authenticate a signature or edition. The later command dispatcher must apply an authorized proposal through the existing audited store and acknowledge its actual outcome. This module never reports a correction as completed and never mutates inventory, identity or prices.

## API, CLI and reuse

The target server adds `POST /api/guidance` with an explicit 32-character lowercase hexadecimal `session_id`, `GET /api/guidance/{id}`, and `POST /api/guidance/{id}/turns`. URL and command session IDs must agree. Existing localhost Host/Origin checks, 4 KiB control-body limit, timeout and error handling apply. Storage work runs off the async HTTP loop. Missing sessions return 404; stale/conflicting commands return 409; invalid input returns 422.

```powershell
.\.venv\Scripts\python.exe -B scripts/smoke_guidance.py --output runs/my-guidance-smoke
.\.venv\Scripts\python.exe -B -m library_claim.guidance --store runs/my-guidance-smoke/store --session-id eeeeeeeeeeeeeeeeeeeeeeeeeeeeeeee --output runs/my-guidance-export
```

Choose fresh output directories. The CLI also accepts `--start` or `--command path.json`, mutually exclusively. It exports `guidance.json` and escaped `report.html`. A committed turn is not rolled back if subsequent export fails; exact retry and a fresh export directory recover the review artifact. Local verification used `.local/reference-env/Scripts/python.exe`.

Reused: FrameStore original integrity, CaptureSessions lifecycle, physical TrackStore snapshot/revisions, StageResult, canonical JSON, existing command schemas, and target HTTP boundaries. New: the guided state machine, questions, declarations and correction intent ledger. Reference audio transport/playback remains deferred to M06b; no policy, avatar or sketch logic was copied. No API keys, provider calls or new dependencies are needed here.

## Verification and artifacts

20 new targeted tests passed. The full Python regression suite passed 277 tests. Coverage includes locale-first behavior, dimensions/unknowns, role validation, stale revisions, exact retry/restart, frame integrity/cross-sweep rejection, closed capture, claimant binding provenance, ambiguous targets, pending corrections, HTML escaping and HTTP boundaries. Browser assets were unchanged; the earlier 16 Node tests were not rerun for this backend-only part. The existing Starlette/HTTPX deprecation warning remains.

`scripts/smoke_guidance.py` exercised a real localhost HTTP server and CLI with explicitly synthetic originals and two physical tracks. It declared GB/GBP, first supplied unknown reference dimensions, then a 12 × 8 cm ±0.1 cm ruler declaration. It started/bound capture, declined an invisible ISBN, declared paperback binding, requested an ambiguous borrowed-book correction and selected a physical copy explicitly. Final guidance revision was 10; the inventory stayed at revision 1 with both copies owned. Exact retry did not advance the revision. Server restart preserved state. Capture closure was observed and a late evidence request returned 409. Provider requests: zero; metric readiness: false; voice connected: false.

Review files are in `runs/m06a-review/`: `smoke-summary.json`, the full HTTP prompt/state sequence in `dialogue.json`, structured command inputs, server log, saved originals/store and `review/report.html` with `review/guidance.json`.

Real claimant speech, camera capture, book reading, reference accuracy, metric geometry and applied conversational corrections remain unverified. The camera-intrinsics setup preference is still unanswered. The next separately authorized part is M06b voice/media transport and interruption/reconnect integration. Recognition scheduling and command execution can then be reviewed as M06c; they are not silently included in this part.
