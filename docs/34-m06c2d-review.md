# M06c2d — Browser shelf-region selection and detection enrollment

Authorized by “next” after M06c2c; completed 11 October 2026. A further “next” arrived during the unfinished browser smoke and was treated as continuation of this same part. This module lets the reviewer select a saved original, mark an explicit shelf rectangle and queue one detection. Automatic capture enrollment, registration and identity acceptance remain separate work.

## Architecture and interaction

The existing `/recognition` page now displays independently paged saved frames as well as existing physical observations. Frame choices come from the saved-frame manifest, so detection enrollment also works before any observations/tracks have been imported. The API returns frame ID, SHA256, encoded width/height, EXIF orientation and synthetic flag; it exposes no local filesystem path. Inventory and reference revision pins remain displayed and supplied to the existing DetectionJob contract.

Selecting a frame loads its unchanged original through the existing hash-verifying frame route. Decoded dimensions must exactly match manifest dimensions before enrollment is enabled. Unsupported EXIF orientation disables selection rather than guessing a rotated coordinate mapping. The saved original is displayed at its natural aspect ratio; a separate translucent DOM overlay shows the selected rectangle without modifying the image.

Drag in either direction to select a shelf. Display coordinates are mapped to original encoded pixel edges, clamped to original bounds, and rounded outward (floor minimum, ceil maximum). Zero-width/height gestures are rejected before rounding, including fractional clicks. Pointer capture permits releases outside the image; cancellation/lost capture clears an unfinished gesture. Manual integer pixel-edge inputs provide a keyboard alternative and repaint the overlay. Blank edge fields never become assumed zero values.

Shelf ID and detection review limits are explicit required inputs: smallest candidate area in original pixels² and maximum overlap fraction between zero and one. These fields start blank; no shelf, region or policy is chosen automatically. Values are validated locally and by the existing server/detector gates. These are proposal-review limits, not calibrated confidence or book-size measurements.

Queue shelf detection submits one exact DetectionJob with selected original hash, rectangle, shelf ID, policy and the displayed inventory/reference revisions. The browser uses one stable job ID per exact input during its page lifetime, so an unconfirmed request can be retried idempotently. A stale request is rejected by the queue; refresh never silently rebases a draft. A successful enrollment refreshes the queue and clears the editor. The independent CLI worker still processes jobs; the page makes no provider request and never imports physical tracks.

## State and HTTP boundaries

ShelfSelector uses generation guards for image loads and pointer events. Selecting another frame, changing session/page, refreshing or leaving the page revokes the old selection. A late old-image load cannot enable enrollment. View loads abort earlier requests and check session, observation offset and frame offset; old results cannot replace the new evidence page. Original-load errors or dimension mismatch keep enrollment disabled. Unsaved drafts are intentionally local and cleared on refresh/reload; they are not durable jobs.

GET `/api/guidance/{session}/recognition` adds `frames`, `total_frames`, `frame_offset` and `frame_limit`. Frame paging is independent of observation paging: default 50, maximum 100, nonnegative offsets. Invalid bounds return 422. Each frame's six public fields are explicitly projected from verified saved evidence. Existing session binding, mutation Origin/Host checks, control-body bounds, DetectionJob validation, artifact integrity and cancellation remain in force. Health identifies M06c2d with an explicit CLI worker. No new endpoint dispatches recognition.

Changed components: server evidence-page projection and asset whitelist; `shelf_selector.mjs` for coordinate/intake guards; recognition page integration and layout; ReadingView frame-page guards; detection-aware cancellation label. No provider transport, ledger import contract or reference code was changed. No dependency installation or reference retest was needed.

## Verification and smoke

Three new Python HTTP checks cover public frame metadata/revision pins, frame selection before any physical track exists, frame paging/bounds, page/assets and unchanged inventory. Seven new Node checks cover scaled reverse drags, outside release/clamping, fractional zero gestures, immutable enrollment inputs, required policy/EXIF/hash/bounds, stale image events, decoded-dimension mismatch and explicit manual enrollment with blank-field rejection. Existing view tests also check a wrong frame-page response cannot render.

Full regression: 359 Python tests and 40 Node tests passed. After the final fractional-click guard and small label/page-text updates, all Node checks passed again; strengthened HTTP and view checks also passed. Existing Starlette/HTTPX deprecation warning remains. Git whitespace checks and JavaScript syntax checks passed.

Synthetic HTTP/CLI/restart smoke reused the target M06c2c controlled fixture in `runs/m06c2d-review` and passed. It preserves original hashes, exact enqueue/restart outcomes and stale-result handling without physical registration. The user-tested reference app was not run.

Actual in-app browser smoke selected the saved 1600×900 synthetic original. A scaled drag produced original edges `[108, 51, 701, 780]`; shelf ID `browser-shelf` and review limits `100` pixels² / `0.5` overlap were explicitly entered as fixture values. The browser/session was interrupted before submission; the resumed smoke reselected the original and entered those same reviewed edges through the manual controls. Queue shelf detection enrolled job `22c7fa3d-90f8-4dca-83d7-8708a58cce7b`, pinned to inventory revision 2 and reference revision 2. A separate replay CLI worker completed it successfully. The original metadata/hash and inventory revision remained unchanged. The completed job and proposal/envelope links survived a server restart and browser refresh.

Artifacts: `runs/m06c2d-review/browser-request.json`, `browser-result.json`, `browser-smoke-summary.json`, `browser-completed.png`, initial `smoke-summary.json`, HTTP history and the original/setup store. `browser-completed.png` shows both the historical stale job and the new completed unverified proposal. Provider requests: zero. Test servers were stopped afterward. A closed temporary tab was replaced during resumed verification; no unsaved selection was claimed durable.

For local review:

```powershell
.\.venv\Scripts\python.exe -B -m library_claim.server --store runs/m06c2d-review/setup/store --port 4189 --synthetic
```

Open `/recognition?session=eeeeeeeeeeeeeeeeeeeeeeeeeeeeeeee`. Select a frame, draw or type its rectangle, enter shelf ID/review limits and explicitly queue. Run the existing CLI with `--kind detection --run-one` and an explicit replay response or confirmed free-tier provider configuration. The setup fixture's old detection is stale because a separate explicit ownership correction advanced the inventory; this is expected.

Android/touch device behavior, actual camera/books, detection precision/recall and live-provider queue calls remain unmeasured. No metric scale or calibration is inferred by this selector. Proposed next small part: M06c2e explicit review of a queued detection's physical registration decisions, reusing the existing audited tracking import and preserving duplicate-copy/revisit ambiguity. Automatic registration and capture scheduling need later boundaries.

**Awaiting user review.**
