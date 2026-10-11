# M04b3 — Capture inventory viewer

Status: implemented; **awaiting user review**. This connects the M04b1 ledger to the local capture UI. It does not run recognition on camera frames or acquire registration landmarks automatically.

## Architecture and behavior

```text
M04a detection / reviewed M04b2 proposal -> M04b1 ledger import or correction
  -> read-only inventory HTTP projection -> independent browser poller
  -> provisional book/review rows and original evidence links
```

The capture page now shows assigned/owned physical track counts, unresolved review entries, sweep inventory revision, explicit unknown total, unidentified book rows and excluded ownership state. First-observation original links remain available; the full exported ledger includes every observation and source. No title, metric dimension, price or coverage is invented. Camera recognition is visibly described as not connected when no imports exist. Reviewed detection imports from a separate CLI process appear on the next successful poll.

An Open saved sweep form supports review without camera permission and recovery in a fresh browser context. It loads the actual stored country/currency, manifest, saved frames and sequence cursor. Switching is disabled while camera start/capture, encoding, uploads, finalization or recovery are active. Unknown IDs leave the previous sweep intact and show an error. Browser-local recovery continues to work on reload. The user must open a sweep belonging to this store; a standalone M04b fixture store without a CaptureSessions sweep is not exposed as a capture sweep.

## HTTP contracts

- `GET /api/sweeps/{id}/inventory?offset=0&limit=50`: paginated read projection. Nonnegative offset; limit 1–100; default 50. Includes capture status, revision, assigned/owned counts, review/import counts, unknown total, unverified/provisional flags and combined book/review rows. No provider responses or credentials are returned in this regular view. Each book includes evidence frame ID and observation count. Review entries include their reason/frame and shelf where known.
- `GET /api/sweeps/{id}/inventory/export`: attachment containing the full M04b1 snapshot, detection sources and audit events. This is provisional ledger export, not the final portable claim packet. Its original evidence references require the FrameStore.

Both routes require an existing capture sweep and use original integrity verification. Unknown sweeps return 404; invalid paging 422; inconsistent/tampered evidence 409. Existing exact Host boundaries, cache suppression and CSP remain. Neither endpoint mutates inventory. The new asset is explicitly allowlisted. The capture API continues to operate independently of imports. Reviewed jobs can update inventory after capture closes; closing transport is not a finalization barrier or a complete recognition claim.

Paging bounds response row count, not ledger verification work: current reads still validate full capture/ledger evidence and build the complete row list before slicing. Polling a large store may be expensive. This is the small-room implementation; a future indexed projection/job invalidation cache must preserve integrity and revision semantics. No HTTP correction/import endpoint or arbitrary client-provided file path was added.

## Browser state and failure handling

`web/inventory.mjs` supplies a separate poller and DOM renderer. Poll interval is 2 seconds after each completed request, with a 10-second AbortController timeout and at most one scheduled request for the active generation. Changing sweep/page or hiding/unloading stops the active generation and aborts its request. Late old responses/errors are ignored even if the transport ignores abort. Older revisions cannot replace newer displayed inventory, including across page changes/manual retry within one sweep. Hidden-page polling resumes when visible.

Failures retain displayed rows, warn that they may be stale, and retry automatically. Successful reconnect clears the warning. Manual refresh and previous/next controls are available. Repeated unchanged responses do not rebuild rows, so focused evidence links remain stable. Changed revisions replace rows. Model text is assigned with `textContent`; evidence IDs are URL-encoded and links use `noopener`. Tables scroll horizontally where needed and headers avoid broken words. The inventory status is separate from upload/camera status.

The browser smoke caught a real browser-only timer-binding defect: calling the browser timer as a poller object method caused `Illegal invocation`. Default timer functions now wrap calls in arrows, preserving the browser binding. Node checks alone did not reveal that defect. Browser recovery was rerun after the fix.

## Run and review

```powershell
.\.venv\Scripts\python.exe -m scripts.smoke_inventory_http --output runs/my-inventory-smoke --fixture runs/m04b2-final-review
.\.venv\Scripts\python.exe -m library_claim.server --store runs/my-inventory-smoke/store --port 4183 --synthetic
```

The fixture argument must point to completed `scripts.smoke_matching` output. The HTTP smoke uses labeled synthetic images and reviewed identity associations, not automatic detection or camera access. Open `http://127.0.0.1:4183/`, enter the sweep ID from `smoke-summary.json` in Open saved sweep, and inspect rows/evidence/download. Leave `--synthetic` off for real capture stores. Example IN/INR locale belongs to the synthetic smoke, not application defaults.

The review server was left running at port 4183 against `runs/m04b3-review/store`, with a browser tab retained for review. Sweep ID: `cccccccccccccccccccccccccccccccc`. It is a synthetic closed sweep; starting a camera creates a new sweep. The original reference app was not tested or modified.

## Validation and evidence

**186 Python tests passed**, including five inventory HTTP tests covering empty unknown inventory/capture independence, exact Host/paging/unknown-sweep/asset boundaries, import pagination, evidence reopening and new-app persistence, ownership after capture closure, complete export, and corrupted-original rejection. Existing Starlette/HTTPX deprecation warning remains.

**16 JavaScript tests passed**: existing nine capture queue/camera lifecycle checks and seven inventory checks for late sweep/page replies, reconnect/retry, monotonic revisions, stop/abort/timeout, unchanged-row focus preservation, successful warning clearing, and literal model text/encoded links/exclusions. Module syntax checks passed. Browser layout and main script recovery were also checked in the actual in-app browser.

Actual HTTP/server-restart smoke: `runs/m04b3-review`. Two original fixture images uploaded through HTTP and received durable acknowledgments. Reviewed imports yielded three tracks/seven observations, with one identity review. Ownership exclusion yielded two owned tracks at revision 3. Page slicing, full snapshot download and every visible original link worked; a new server process returned an identical view. Saved artifacts: `smoke-summary.json`, `inventory-view.json`, `inventory-export.json`, bundles and `server.log`.

Actual browser checks loaded that saved sweep without camera access and showed revision 3 with three tracks, two owned and one review. An explicitly labeled synthetic CLI ownership correction produced revision 4/three owned and appeared automatically without page reload. Stopping the server showed stale-data warning with rows retained; restarting recovered automatically. Open saved sweep and final page reload restored evidence/inventory. Artifacts: `browser-command.json`, `browser-revision-4.json`, `browser-inventory.png` and `browser-smoke.json`. The HTTP summary describes revision 3; the browser then deliberately advanced the live test ledger to revision 4. No provider calls.

No real-camera or actual-shelf recognition accuracy is claimed. Browser paging across >50 live rows, actual phone viewport/device, visibility-driven pause/resume, and a continuous recognized shelf sweep were not exercised in the browser; paging/lifecycle logic has automated coverage as described. Metric calibration and real measurement acceptance remain pending from earlier modules.

## Remaining project work

M04 still needs automatic landmark acquisition, an integrated recognition/job adapter, and held-out real detection/identity evaluation before its continuous-sweep acceptance bar can pass. M05 OCR, M06 voice/provider scheduling and later valuation/export modules remain separate. This step does not silently waive those requirements.

**Awaiting user review.**
